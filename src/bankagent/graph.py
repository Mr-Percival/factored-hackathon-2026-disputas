"""Grafo del agente (LangGraph).

    guard -> understand -> find_transaction -> decide -> (confirmación) -> act
                  |               |                |
                  |               +-> clarify      +-> handoff
                  +-> handoff / respond

Reglas del diseño:
- Cada nodo devuelve `next`; los destinos permitidos de cada nodo están declarados en EDGES
  (el diagrama se genera desde aquí: `Agent(...).mermaid()`).
- El modelo (router / writer) nunca llama herramientas ni decide política: lo hacen los nodos.
- Una acción solo se reporta como hecha si la herramienta la verificó (`verified=True`).
- Cada nodo agrega un registro a `trace` (nodo, latencia, herramientas usadas, detalle): ese es el
  artefacto de auditoría, no el razonamiento del modelo.
"""
from __future__ import annotations

import datetime as dt
import operator
import time
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from .audit import AuditLog
from .guard import InjectionDetector, detector_from_env, redact
from .identity import AuthError
from .observability import emit as emit_trace
from .policy import PolicyEngine
from .responses import TemplateWriter, fmt_option, fmt_txn, handoff_summary
from .tools import BankTools, ToolError
from .understanding import Router, RuleRouter, detect_language

DISPUTABLE_TYPES = {"Purchase", "Withdrawal", "Payment", "Transfer", "Adjustment"}
TRANSIENT_ERRORS = {"unavailable", "timeout"}


class State(TypedDict, total=False):
    # entrada del turno
    token: str
    user_text: str
    # contexto que persiste entre turnos (checkpointer)
    turn: int
    lang: str
    awaiting: str | None           # None | "option" | "confirmation"
    candidates: list[dict]
    txn: dict | None
    pending_action: dict | None    # {type, transaction_id, block_card, card_label, declined}
    consent_retries: int           # re-preguntas por una confirmación ambigua (límite en policy.yaml)
    conversation: Annotated[list[dict], operator.add]  # mensajes ya enmascarados
    strikes: int                   # intentos bloqueados + accesos prohibidos en esta conversación
    owner: str | None              # cliente del primer turno autenticado; el hilo no se comparte entre clientes
    # salida del turno
    understanding: dict | None
    decision: dict | None
    outcome: str | None            # resolved | clarify | informed | rejected | handoff | cancelled | blocked | auth_error
    reply: str | None
    handoff: dict | None
    trace: Annotated[list[dict], operator.add]
    # comunicación entre nodos dentro del turno
    next: str
    reply_key: str | None
    reply_prefix: str | None       # frase fija antes de la respuesta (ej. "no me quedó clara tu respuesta")
    handoff_reason: str | None
    action_result: dict | None


# Destinos permitidos por nodo (documentación ejecutable del flujo)
EDGES: dict[str, list[str]] = {
    "guard": ["understand", "respond", "handoff"],
    "understand": ["find_transaction", "find_card", "select_option", "act", "cancel", "handoff", "respond"],
    "find_card": ["respond", "handoff"],
    "find_transaction": ["decide", "respond", "handoff"],
    "select_option": ["decide", "respond"],
    "decide": ["respond", "handoff"],
    "act": ["respond", "handoff"],
    "cancel": ["respond"],
    "handoff": ["respond"],
    "respond": [END],
}


class Agent:
    def __init__(self, tools: BankTools, policy: PolicyEngine, router: Router | None = None,
                 writer: TemplateWriter | None = None, min_confidence: float = 0.6, max_retries: int = 2,
                 audit: AuditLog | None = None, max_strikes: int = 3,
                 detector: InjectionDetector | None = None):
        self.tools, self.policy = tools, policy
        self.audit, self.max_strikes = audit, max_strikes
        self.router = router or RuleRouter()
        self.writer = writer or TemplateWriter()
        self.detector = detector or detector_from_env()  # regex salvo que se pida otro (ADR 0005)
        self.min_confidence, self.max_retries = min_confidence, max_retries
        self.graph = self._build().compile(checkpointer=InMemorySaver())

    # ------------------------------------------------------------------ API
    def chat(self, thread_id: str, token: str, text: str) -> dict:
        cfg = {"configurable": {"thread_id": thread_id}}
        prev = self.graph.get_state(cfg).values
        turn = prev.get("turn", 0) + 1
        out = self.graph.invoke({"token": token, "user_text": text, "turn": turn,
                                 "reply": None, "outcome": None, "handoff": None, "decision": None,
                                 "understanding": None, "reply_key": None, "handoff_reason": None,
                                 "action_result": None, "reply_prefix": None}, cfg)
        if self.audit:  # persiste la traza del turno (sin texto del cliente); el último registro lleva el resultado
            entries = [e for e in out.get("trace", []) if e["turn"] == turn]
            for i, e in enumerate(entries):
                self.audit.append(thread_id, e, out.get("outcome") if i == len(entries) - 1 else None)
        return out

    def mermaid(self) -> str:
        return self.graph.get_graph().draw_mermaid()

    # ------------------------------------------------------------------ construcción
    def _build(self) -> StateGraph:
        g = StateGraph(State)
        nodes = {"guard": self.guard, "understand": self.understand, "find_transaction": self.find_transaction, "find_card": self.find_card,
                 "select_option": self.select_option, "decide": self.decide, "act": self.act,
                 "cancel": self.cancel, "handoff": self.handoff, "respond": self.respond}
        for name, fn in nodes.items():
            g.add_node(name, self._traced(name, fn))
        g.add_edge(START, "guard")
        for name, targets in EDGES.items():
            if targets == [END]:
                g.add_edge(name, END)
            else:
                g.add_conditional_edges(name, lambda s: s["next"], {t: t for t in targets})
        return g

    def _traced(self, name: str, fn):
        """Mide latencia, registra herramientas usadas y convierte errores en salidas seguras."""
        def wrapper(state: State) -> dict:
            calls: list[dict] = []
            t0 = time.perf_counter()
            try:
                out = fn(state, calls)
            except AuthError as e:
                out = {"next": "respond", "outcome": "auth_error", "reply_key": e.code, "detail": e.code}
                if e.code == "forbidden":  # intento de acceso a datos ajenos: cuenta para el bloqueo
                    out["strikes"] = state.get("strikes", 0) + 1
            except ToolError as e:  # falla persistente tras reintentos -> humano
                out = {"next": "handoff", "handoff_reason": "tool_failure", "detail": str(e)}
            if out["next"] not in EDGES[name]:
                raise RuntimeError(f"Transición no declarada {name} -> {out['next']}")
            entry = {"turn": state.get("turn"), "node": name, "ms": round((time.perf_counter() - t0) * 1000, 2),
                     "next": out.get("next"), "detail": out.pop("detail", None), "tools": calls}
            if out.get("llm"):  # telemetría del modelo (router/writer): versión, tokens, costo, fallback
                entry["llm"] = out["llm"]
            out.pop("llm", None)
            emit_trace(entry)  # JSON por nodo si BANKAGENT_LOG_JSON=1 (docs/operations.md)
            return {**out, "trace": [entry]}
        return wrapper

    def _call(self, calls: list, tool: str, *args, **kwargs):
        """Llamada a herramienta con reintentos acotados solo para errores transitorios."""
        for attempt in range(self.max_retries + 1):
            t0 = time.perf_counter()
            try:
                res = getattr(self.tools, tool)(*args, **kwargs)
                calls.append({"tool": tool, "ok": True, "attempt": attempt + 1, "ms": round((time.perf_counter() - t0) * 1000, 2)})
                return res
            except ToolError as e:
                calls.append({"tool": tool, "ok": False, "attempt": attempt + 1, "error": str(e)})
                if str(e) not in TRANSIENT_ERRORS or attempt == self.max_retries:
                    raise
            except AuthError as e:
                calls.append({"tool": tool, "ok": False, "attempt": attempt + 1, "error": e.code})
                raise

    # ------------------------------------------------------------------ nodos
    def guard(self, s: State, calls) -> dict:
        text = s["user_text"]
        msg = {"role": "user", "turn": s["turn"], "text": redact(text)}
        strikes = s.get("strikes", 0)
        # Identidad y dueño del hilo ANTES que el bloqueo: si no, un intruso que bloquea el hilo ajeno recibiría el
        # handoff de seguridad con el paquete (mensajes y hechos del dueño). Detectado por la invariante I2.
        session = self.tools.identity.resolve(s.get("token"))  # AuthError -> respuesta segura
        # El hilo queda atado al cliente de su primer turno autenticado: la sesión válida de OTRO cliente no puede
        # continuarlo (vería candidatos/confirmaciones ajenos guardados en el estado). Cuenta como acceso prohibido.
        if s.get("owner") and s["owner"] != session.customer_id:
            raise AuthError("forbidden")
        if strikes >= self.max_strikes:  # conversación bloqueada: nada más se procesa, pasa a un humano
            return {"next": "handoff", "handoff_reason": "security_lockout", "conversation": [msg],
                    "detail": f"locked strikes={strikes}"}
        reason = self.detector.detect(text)
        if reason:
            strikes += 1
            out = {"next": "respond", "outcome": "blocked", "reply_key": "blocked_input", "strikes": strikes,
                   "lang": detect_language(text), "conversation": [msg], "owner": session.customer_id,
                   "detail": f"injection {self.detector.name}: {reason} strikes={strikes}"}
            if strikes >= self.max_strikes:
                out.update(next="handoff", handoff_reason="security_lockout")
            return out
        return {"next": "understand", "conversation": [msg], "owner": session.customer_id}

    def understand(self, s: State, calls) -> dict:
        today = self.policy.as_of
        awaiting = s.get("awaiting")
        pending = s.get("pending_action") or {}
        # Una confirmación solo vale en el turno INMEDIATAMENTE posterior a la pregunta. Si en medio hubo otro turno
        # (mensaje no entendido, inyección bloqueada, sesión vencida...), el "sí" ya no responde a esa pregunta.
        fresh = awaiting == "confirmation" and pending.get("asked_turn") == s["turn"] - 1
        if awaiting == "confirmation" and not fresh:
            awaiting = None
        u = self.router.understand(redact(s["user_text"]), today, awaiting)
        out: dict[str, Any] = {"understanding": {"intent": u.intent, "confidence": u.confidence, "language": u.language,
                                                 "router": u.router, "slots": vars(u.slots)},
                               "lang": u.language, "detail": f"{u.intent}@{u.confidence:.2f} router={u.router}",
                               "llm": u.llm}
        if awaiting == "confirmation":  # solo si la pregunta se hizo en el turno anterior (#49)
            if u.intent == "confirm" and u.confidence >= self.min_confidence:
                narrowed = _apply_denials(pending, u.sub_action_denials)
                return {**out, "next": "act", "pending_action": narrowed} if narrowed else {**out, "next": "cancel"}
            if u.intent == "deny":
                return {**out, "next": "cancel"}
            # Duda explícita ("no sé, creo que sí") o un "sí" poco seguro: se re-pregunta. Un mensaje sin ninguna
            # señal de respuesta (otro tema) descarta la pregunta, como cualquier confirmación no usada (#49).
            if u.intent == "unclear" or (u.intent == "confirm" and u.confidence < self.min_confidence):
                return {**out, **self._reask_consent(s, u.sub_action_denials)}
        if s.get("awaiting") == "confirmation":  # pregunta no respondida en su turno: se descarta, nunca se reusa
            out.update(awaiting=None, pending_action=None)
        if awaiting == "option" and u.intent == "select_option":
            return {**out, "next": "select_option"}
        if u.confidence < self.min_confidence or u.intent == "unknown":
            return {**out, "next": "respond", "outcome": "clarify", "reply_key": "unknown"}
        if u.intent == "out_of_scope":
            return {**out, "next": "handoff", "handoff_reason": "out_of_scope"}
        nxt = "find_card" if u.intent == "block_card" else "find_transaction"
        return {**out, "next": nxt, "awaiting": None, "pending_action": None, "txn": None, "consent_retries": 0}

    def _reask_consent(self, s: State, denials: list[str]) -> dict:
        """Confirmación ambigua: nunca se actúa. Se re-pregunta una vez (sin lo que el cliente ya rechazó) y,
        si sigue sin quedar claro, pasa a un humano con motivo `consent_unclear`."""
        retries = s.get("consent_retries", 0)
        if retries >= self.policy.conversation.get("max_consent_reasks", 1):
            return {"next": "handoff", "handoff_reason": "consent_unclear", "detail": f"consent_retries={retries}"}
        pending = s.get("pending_action") or {}
        narrowed = _apply_denials(pending, denials)
        if narrowed is None:  # rechazó la única acción ofrecida (el bloqueo)
            return {"next": "cancel"}
        narrowed = {**narrowed, "asked_turn": s["turn"]}  # la re-pregunta vale solo para el turno siguiente
        newly_declined = set(narrowed.get("declined", [])) - set(pending.get("declined", []))
        return {"next": "respond", "outcome": "clarify", "reply_key": _confirm_key(narrowed),
                "reply_prefix": "block_excluded" if newly_declined else "reask_consent",
                "pending_action": narrowed, "consent_retries": retries + 1,
                "detail": f"consent unclear retry={retries + 1}"}

    def find_transaction(self, s: State, calls) -> dict:
        sl = s["understanding"]["slots"]
        amt = sl.get("amount")
        found = self._call(calls, "search_transactions", s["token"],
                           date_from=sl.get("date_from"), date_to=sl.get("date_to"),
                           amount_min=amt * 0.9 if amt else None, amount_max=amt * 1.1 if amt else None,
                           country=sl.get("country"), limit=20)
        found = [t for t in found if t["transaction_type"] in DISPUTABLE_TYPES][:5]
        if not found:
            return {"next": "respond", "outcome": "clarify", "reply_key": "no_match", "detail": "0 candidates"}
        if len(found) == 1:
            return {"next": "decide", "txn": found[0], "candidates": [], "detail": "1 candidate"}
        return {"next": "respond", "outcome": "clarify", "reply_key": "choose", "candidates": found,
                "awaiting": "option", "detail": f"{len(found)} candidates"}

    def select_option(self, s: State, calls) -> dict:
        opt = s["understanding"]["slots"].get("option")
        cands = s.get("candidates") or []
        if not opt or opt > len(cands):
            return {"next": "respond", "outcome": "clarify", "reply_key": "choose", "detail": "invalid option"}
        chosen = cands[opt - 1]
        if chosen.get("kind") == "card":
            return {"next": "respond", "outcome": "clarify", "reply_key": "block_confirm", "candidates": [],
                    "awaiting": "confirmation", "detail": f"card option={opt}", "consent_retries": 0,
                    "pending_action": {"type": "block_card", "block_card": chosen["product_id"],
                                       "card_label": chosen["product_number"], "asked_turn": s["turn"]}}
        return {"next": "decide", "txn": cands[opt - 1], "candidates": [], "awaiting": None, "detail": f"option={opt}"}

    def decide(self, s: State, calls) -> dict:
        txn = self._call(calls, "get_transaction", s["token"], s["txn"]["transaction_id"])  # hecho verificado
        customer = self._call(calls, "get_profile", s["token"])
        history = self._call(calls, "dispute_history", s["token"])
        d = self.policy.decide_dispute(txn, customer, history)
        decision = {"outcome": d.outcome, "policy_version": d.policy_version,
                    "rules": [vars(h) for h in d.hits], "facts": {"customer_status": customer["customer_status"],
                                                                  "segment": customer["segment"], **history}}
        base = {"txn": txn, "decision": decision, "detail": f"{d.outcome} rules={[h.id for h in d.hits]}"}
        if d.outcome == "handoff":
            return {**base, "next": "handoff", "handoff_reason": d.deciding_rule.id}
        if d.outcome in ("reject", "inform"):
            return {**base, "next": "respond", "outcome": "rejected" if d.outcome == "reject" else "informed",
                    "reply_key": "rule"}
        cards = self._call(calls, "list_cards", s["token"])
        card = next((c for c in cards if c["product_id"] == txn["product_id"]), None)
        offer = self.policy.offer_block(card, txn)  # solo tarjeta activa del producto (actions.block_card.offer_when)
        action = {"type": "open_dispute", "transaction_id": txn["transaction_id"],
                  "block_card": card["product_id"] if offer else None,
                  "card_label": card["product_number"] if offer else None, "declined": [], "asked_turn": s["turn"]}
        return {**base, "next": "respond", "outcome": "clarify", "reply_key": _confirm_key(action),
                "pending_action": action, "awaiting": "confirmation", "consent_retries": 0}

    def find_card(self, s: State, calls) -> dict:
        cards = [c for c in self._call(calls, "list_cards", s["token"]) if c["product_status"] == "Active"]
        if not cards:
            return {"next": "handoff", "handoff_reason": "no_active_card", "detail": "0 active cards"}
        if len(cards) == 1:
            c = cards[0]
            return {"next": "respond", "outcome": "clarify", "reply_key": "block_confirm", "awaiting": "confirmation",
                    "consent_retries": 0,
                    "pending_action": {"type": "block_card", "block_card": c["product_id"], "card_label": c["product_number"],
                                       "asked_turn": s["turn"]}}
        cands = [{"kind": "card", **c} for c in cards[:5]]
        return {"next": "respond", "outcome": "clarify", "reply_key": "choose", "candidates": cands, "awaiting": "option",
                "detail": f"{len(cands)} cards"}

    def act(self, s: State, calls) -> dict:
        a = s.get("pending_action")
        if not a:
            return {"next": "respond", "outcome": "clarify", "reply_key": "unknown", "awaiting": None}
        res = None
        if a["type"] == "open_dispute":
            res = self._call(calls, "open_dispute", s["token"], a["transaction_id"], "cargo_no_reconocido", confirmed=True)
        blocked = self._call(calls, "block_card", s["token"], a["block_card"], confirmed=True) if a.get("block_card") else None
        if (res is not None and not res["verified"]) or (blocked is not None and not blocked["verified"]):
            return {"next": "handoff", "handoff_reason": "action_not_verified", "detail": "verification failed"}
        return {"next": "respond", "outcome": "resolved", "reply_key": "done_dispute" if res else "block_done",
                "awaiting": None, "pending_action": None,
                "action_result": {"dispute": res, "block": blocked, "card_label": a.get("card_label"),
                                  "declined": a.get("declined", [])},
                "detail": f"case={res and res['case_id']} blocked={bool(blocked)}"}

    def cancel(self, s: State, calls) -> dict:
        return {"next": "respond", "outcome": "cancelled", "reply_key": "cancelled", "awaiting": None,
                "pending_action": None}

    def handoff(self, s: State, calls) -> dict:
        reason = s.get("handoff_reason") or "unspecified"
        txn = s.get("txn")
        decision = s.get("decision") or {}
        actions = [c for e in s.get("trace", []) for c in e["tools"]
                   if c["tool"] in ("open_dispute", "block_card") and c["ok"]]
        unresolved = {
            "out_of_scope": ["Atender la solicitud fuera del alcance del canal automático."],
            "tool_failure": ["Reintentar la consulta de movimientos; el sistema no pudo verificar datos."],
            "action_not_verified": ["Confirmar en core si la disputa/bloqueo quedaron registrados."],
            "security_lockout": ["Revisar los intentos bloqueados en el log de auditoría.",
                                 "Validar la identidad del cliente por un canal seguro antes de reabrir la conversación."],
        }.get(reason, ["Validar con el cliente si reconoce al comercio.", "Decidir apertura de disputa y abono provisional."])
        packet = {
            "reason": reason,
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            "language": s.get("lang", "es"),
            "request": [m["text"] for m in s.get("conversation", [])][-5:],
            "verified_facts": {"transaction": _jsonable(txn) if txn else None, **(decision.get("facts") or {})},
            "policy": {"version": decision.get("policy_version"), "rules_fired": decision.get("rules", [])},
            "actions_taken": actions,
            "evidence": [{"turn": e["turn"], "node": e["node"], "tools": [c["tool"] for c in e["tools"]]}
                         for e in s.get("trace", []) if e["tools"]],
            "unresolved_questions": unresolved,
        }
        packet["summary"] = handoff_summary(packet)  # una línea determinista para el asesor (#32)
        return {"next": "respond", "outcome": "handoff", "handoff": packet, "awaiting": None, "pending_action": None,
                "reply_key": reason if reason in HANDOFF_REPLIES else "handoff",
                "detail": reason}

    def respond(self, s: State, calls) -> dict:
        lang = s.get("lang") or "es"
        key = s.get("reply_key") or "unknown"
        txn = s.get("txn")
        facts: dict[str, Any] = {}
        if txn:
            facts["txn"] = fmt_txn(txn)
        if key == "choose":
            facts["options"] = "\n".join(f"{i}) {fmt_option(t)}" for i, t in enumerate(s.get("candidates") or [], 1))
        if key in ("confirm_dispute", "block_confirm"):
            facts["card"] = s["pending_action"]["card_label"]  # estas claves solo se usan si hay tarjeta ofrecida
        if key == "done_dispute":
            r = s["action_result"]
            facts["case_id"] = r["dispute"]["case_id"]
            facts["block"] = ""
            if r["block"]:
                facts["block"] = self.writer.write("block_suffix", lang, card=r["card_label"])
            elif "block_card" in r.get("declined", []):
                facts["block"] = self.writer.write("block_declined_suffix", lang)
        if key == "block_done":
            facts["card"] = s["action_result"]["card_label"]
        if key in ("rule", "handoff"):
            hit = (s.get("decision") or {}).get("rules", [{}])[0] if s.get("decision") else {}
            facts["explain"] = self.writer.rule_text(hit.get("id", ""), hit.get("explain", ""), lang) if hit else ""
            facts.setdefault("txn", "-")
        # el país (dialecto) se consulta solo si el writer lo necesita para esta respuesta
        reply, llm = self.writer.compose(key, lang, facts, country=lambda: self._customer_country(s, calls))
        if s.get("reply_prefix"):  # texto fijo (no pasa por el modelo): dice por qué se vuelve a preguntar
            reply = f"{self.writer.write(s['reply_prefix'], lang)}\n{reply}"
        return {"next": END, "reply": reply, "outcome": s.get("outcome") or "clarify", "llm": llm,
                "detail": f"writer_fallback={llm['fallback']}" if llm and llm["fallback"] else None,
                "conversation": [{"role": "assistant", "turn": s.get("turn"), "text": reply}]}

    def _customer_country(self, s: State, calls) -> str | None:
        """País del perfil (dato verificado) para el dialecto del writer. Si no hay sesión válida, None."""
        if s.get("outcome") == "auth_error":
            return None
        try:
            return self._call(calls, "get_profile", s["token"]).get("country")
        except (AuthError, ToolError):
            return None


# Motivos de handoff con una respuesta propia al cliente; el resto usa la plantilla genérica "handoff".
HANDOFF_REPLIES = {"tool_failure", "out_of_scope", "security_lockout", "consent_unclear", "no_active_card"}


def _confirm_key(action: dict) -> str:
    """Plantilla de confirmación según lo que efectivamente se ofrece (nunca "tarjeta -")."""
    if action.get("type") == "block_card":
        return "block_confirm"
    return "confirm_dispute" if action.get("block_card") else "confirm_dispute_no_card"


def _apply_denials(pending: dict | None, denials: list[str]) -> dict | None:
    """Quita de la acción pendiente las sub-acciones que el cliente rechazó. None = no queda nada por hacer."""
    if not pending or "block_card" not in denials:
        return pending
    if pending.get("type") == "block_card":
        return None
    declined = set(pending.get("declined", [])) | ({"block_card"} if pending.get("block_card") else set())
    return {**pending, "block_card": None, "declined": sorted(declined)}


def _jsonable(d: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else float(v) if hasattr(v, "as_tuple") else v)
            for k, v in d.items()}
