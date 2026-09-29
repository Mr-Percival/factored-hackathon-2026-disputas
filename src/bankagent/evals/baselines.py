"""Líneas base ingenuas para comparar contra el agente sobre el mismo conjunto reservado.

- B0 · "transferir todo": bot de palabras clave que pasa a un humano cualquier pedido no trivial. Es la opción
  segura por diseño y con la contención más baja. Corre dentro del mismo grafo (guard, sesión, handoff), así que
  el paquete de handoff existe, pero sin transacción verificada ni regla.
- B1 · "automatización ingenua": entiende igual que el RuleRouter, pero NO aplica la política ni pide
  confirmación. Abre la disputa y bloquea la tarjeta sobre la primera coincidencia. Muestra qué resultados
  inseguros evitan la política y la confirmación. Usa las mismas herramientas con permisos por sesión, así que no
  puede leer datos ajenos: su riesgo es actuar mal sobre lo propio.

Ninguna de las dos es un sistema que se propondría. Existen para dar escala a las métricas.
"""
from __future__ import annotations

import datetime as dt
import re
import time

from ..graph import DISPUTABLE_TYPES
from ..guard import detect_injection
from ..identity import AuthError
from ..policy import PolicyEngine
from ..responses import TemplateWriter, fmt_txn
from ..tools import BankTools, ToolError
from ..understanding import KEYWORDS, RuleRouter, Understanding, _has, _norm, detect_language


class TransferAllRouter:
    """B0: cualquier mensaje con contenido pasa a humano (el grafo lo trata como fuera de alcance)."""

    name = "b0-transfer-all"

    def understand(self, text: str, today: dt.date, awaiting: str | None) -> Understanding:
        t, lang = _norm(text), detect_language(text)
        words = re.findall(r"[a-z0-9]+", t)
        substantive = len(words) >= 3 or any(_has(t, k) for kws in KEYWORDS.values() for k in kws if len(k) > 3)
        return Understanding("out_of_scope" if substantive else "unknown", 0.9 if substantive else 0.2, lang)


class NaiveAutomationAgent:
    """B1: misma interfaz `chat()` que `Agent`, sin política ni confirmación."""

    def __init__(self, tools: BankTools, policy: PolicyEngine):
        self.tools, self.today = tools, policy.as_of
        self.router, self.writer = RuleRouter(), TemplateWriter()
        self.router.name = "b1-naive-automation"
        self._turns: dict[str, int] = {}

    def chat(self, thread_id: str, token: str, text: str) -> dict:
        turn = self._turns[thread_id] = self._turns.get(thread_id, 0) + 1
        t0 = time.perf_counter()
        u = self.router.understand(text, self.today, None)
        lang = u.language
        out = {"turn": turn, "awaiting": None, "candidates": [], "decision": None, "handoff": None, "txn": None,
               "lang": lang, "understanding": {"intent": u.intent, "confidence": u.confidence, "language": lang,
                                               "router": self.router.name, "slots": vars(u.slots)}}
        try:
            self.tools.identity.resolve(token)
            if detect_injection(text):
                out.update(outcome="blocked", reply=self.writer.write("blocked_input", lang))
            elif u.intent == "dispute_charge":
                out.update(self._dispute(token, u, lang))
            elif u.intent == "block_card":
                cards = [c for c in self.tools.list_cards(token) if c["product_status"] == "Active"]
                if cards:
                    self.tools.block_card(token, cards[0]["product_id"], confirmed=True)  # sin preguntar
                    out.update(outcome="resolved", reply=self.writer.write("block_done", lang, card=cards[0]["product_number"]))
                else:
                    out.update(outcome="clarify", reply=self.writer.write("unknown", lang))
            elif u.intent == "out_of_scope":
                out.update(outcome="handoff", reply=self.writer.write("out_of_scope", lang),
                           handoff={"reason": "out_of_scope", "request": [text], "unresolved_questions": ["Atender el pedido."]})
            else:
                out.update(outcome="clarify", reply=self.writer.write("unknown", lang))
        except AuthError as e:
            out.update(outcome="auth_error", reply=self.writer.write(e.code, lang))
        except ToolError:
            out.update(outcome="handoff", reply=self.writer.write("tool_failure", lang),
                       handoff={"reason": "tool_failure", "request": [text], "unresolved_questions": ["Reintentar."]})
        out["trace"] = [{"turn": turn, "node": "naive", "ms": round((time.perf_counter() - t0) * 1000, 2), "tools": []}]
        return out

    def _dispute(self, token: str, u: Understanding, lang: str) -> dict:
        sl, amt = u.slots, u.slots.amount
        found = self.tools.search_transactions(token, date_from=sl.date_from, date_to=sl.date_to,
                                               amount_min=amt * 0.9 if amt else None, amount_max=amt * 1.1 if amt else None,
                                               limit=20)
        found = [t for t in found if t["transaction_type"] in DISPUTABLE_TYPES]
        if not found:
            return {"outcome": "clarify", "reply": self.writer.write("no_match", lang)}
        txn = found[0]  # la más reciente: no pregunta cuál
        res = self.tools.open_dispute(token, txn["transaction_id"], "cargo_no_reconocido", confirmed=True)
        card = next((c for c in self.tools.list_cards(token)
                     if c["product_id"] == txn["product_id"] and c["product_status"] == "Active"), None)
        suffix = ""
        if card:
            self.tools.block_card(token, card["product_id"], confirmed=True)
            suffix = self.writer.write("block_suffix", lang, card=card["product_number"])
        return {"outcome": "resolved", "txn": txn,
                "reply": self.writer.write("done_dispute", lang, case_id=res["case_id"], txn=fmt_txn(txn), block=suffix)}
