"""Estado del grafo -> contrato HTTP. Funciones puras (se prueban sin servidor).

Adaptado de los formateadores de la demo anterior (`ui.py`, PR #21). Qué se filtra a propósito:
- el token del agente (nunca sale del servidor);
- la traza de turnos anteriores (la respuesta describe SOLO este turno);
- ids internos de producto en la acción pendiente (el cliente ve la etiqueta enmascarada de la tarjeta).
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from ..responses import fmt_option
from .schemas import (Candidate, Decision, Evidence, Handoff, HandoffPolicy, PendingAction, Rule, ToolCall,
                      TraceStep, TurnResult, Understanding)

HANDOFF_REASONS = {
    "out_of_scope": "Fuera del alcance del canal automático",
    "tool_failure": "Falla persistente de una herramienta",
    "action_not_verified": "La acción no se pudo verificar",
    "no_active_card": "El cliente no tiene tarjetas activas",
    "security_lockout": "Conversación pausada por intentos bloqueados repetidos",
    # motivos que agrega feat/conversational-robustness (#38-#44); los desconocidos se muestran crudos
    "customer_request": "El cliente pidió hablar con una persona",
    "clarification_limit": "Demasiadas aclaraciones sin llegar a un cargo concreto",
    "account_takeover": "Señales de toma de cuenta",
}
HANDOFF_KNOWN_KEYS = {"reason", "created_at", "language", "request", "verified_facts", "policy", "actions_taken",
                      "evidence", "unresolved_questions"}


def jsonable(v: Any) -> Any:
    """Convierte fechas y Decimal de DuckDB a tipos JSON, recursivamente."""
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [jsonable(x) for x in v]
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _tool(c: dict) -> ToolCall:
    return ToolCall(tool=c["tool"], ok=bool(c.get("ok")), attempt=int(c.get("attempt", 1)),
                    ms=c.get("ms"), error=c.get("error"))


def turn_trace(state: dict) -> list[TraceStep]:
    turn = state.get("turn")
    steps = []
    for e in state.get("trace") or []:
        if e.get("turn") != turn:
            continue
        nxt = e.get("next")
        steps.append(TraceStep(node=e["node"], next="fin" if nxt in (None, "__end__") else nxt,
                               ms=float(e.get("ms") or 0.0), detail=e.get("detail"),
                               tools=[_tool(c) for c in e.get("tools") or []], llm=jsonable(e.get("llm"))))
    return steps


def _rules(rules: list[dict] | None) -> list[Rule]:
    return [Rule(id=r.get("id", ""), outcome=r.get("outcome", ""), explain=r.get("explain", "")) for r in rules or []]


def decision_view(d: dict | None) -> Decision | None:
    if not d:
        return None
    return Decision(outcome=d.get("outcome", ""), policy_version=str(d.get("policy_version", "")),
                    rules=_rules(d.get("rules")), facts=jsonable(d.get("facts") or {}))


def handoff_view(p: dict | None) -> Handoff | None:
    if not p:
        return None
    rules = _rules((p.get("policy") or {}).get("rules_fired"))
    reason = p.get("reason", "")
    reason_text = HANDOFF_REASONS.get(reason) or next((r.explain for r in rules if r.id == reason), reason)
    return Handoff(
        reason=reason, reason_text=reason_text, language=p.get("language", "es"),
        created_at=str(p.get("created_at", "")), request=list(p.get("request") or []),
        verified_facts=jsonable(p.get("verified_facts") or {}),
        policy=HandoffPolicy(version=(p.get("policy") or {}).get("version"), rules_fired=rules),
        actions_taken=[_tool(a) for a in p.get("actions_taken") or []],
        evidence=[Evidence(turn=e["turn"], node=e["node"], tools=list(e["tools"])) for e in p.get("evidence") or []],
        unresolved_questions=list(p.get("unresolved_questions") or []),
        extra=jsonable({k: v for k, v in p.items() if k not in HANDOFF_KNOWN_KEYS}),
    )


def understanding_view(u: dict | None) -> Understanding | None:
    if not u:
        return None
    slots = {k: v for k, v in (u.get("slots") or {}).items() if v is not None}
    return Understanding(intent=str(u.get("intent", "unknown")), confidence=float(u.get("confidence") or 0.0),
                         router=str(u.get("router", "")), slots=jsonable(slots))


def candidates_view(state: dict) -> list[Candidate]:
    if state.get("awaiting") != "option":
        return []  # los candidatos persisten en el estado, pero solo importan mientras se espera una opción
    return [Candidate(index=i, kind="card" if c.get("kind") == "card" else "transaction", label=fmt_option(c))
            for i, c in enumerate(state.get("candidates") or [], 1)]


def pending_view(state: dict) -> PendingAction | None:
    a = state.get("pending_action") if state.get("awaiting") == "confirmation" else None
    if not a:
        return None
    return PendingAction(type=str(a.get("type", "")), card_label=a.get("card_label"))


def turn_result(conversation_id: str, state: dict) -> TurnResult:
    trace = turn_trace(state)
    lang = state.get("lang") if state.get("lang") in ("es", "pt") else "es"
    return TurnResult(
        conversation_id=conversation_id, turn=int(state.get("turn") or 0), reply=state.get("reply") or "",
        outcome=state.get("outcome") or "clarify", lang=lang, awaiting=state.get("awaiting"),
        candidates=candidates_view(state), pending_action=pending_view(state),
        understanding=understanding_view(state.get("understanding")),
        # la decisión y el handoff se muestran solo si se produjeron en ESTE turno
        decision=decision_view(state.get("decision")), handoff=handoff_view(state.get("handoff")),
        trace=trace, trace_total_ms=round(sum(s.ms for s in trace), 2),
    )
