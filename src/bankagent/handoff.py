"""Paquete de handoff versionado (#44): un caso listo para el asesor, no un volcado técnico.

Qué trae (esquema: docs/handoff.schema.json, versión en `policy.yaml > handoff.schema_version`):
- identidad del caso: `handoff_id` (el cliente lo recibe en su idioma), cola, prioridad, SLA y siguiente paso,
  todo leído de la política por motivo;
- lo que el cliente RECLAMÓ (`customer_claim`: monto/fechas/país/comercio/cantidad que dijo) y cómo se llegó al
  movimiento (`match`: única candidata o elegido por el cliente, diferencia de monto y de fecha);
- hechos verificados con LISTA BLANCA de campos (minimización: nada de customer_id, product_id, is_fraud...);
- preguntas abiertas por motivo (de la política) + la de reconocimiento adecuada al movimiento (comercio si
  hay comercio; canal si es un retiro o transferencia), y las otras reglas que también se cumplieron;
- evidencia (nodos y herramientas) y, si falló una herramienta, cuál y con qué error.
Las claves históricas (`reason`, `request`, `verified_facts`, `policy`, `actions_taken`, `evidence`,
`unresolved_questions`, `summary`) se mantienen: el harness de evaluación y el kit humano las leen.
"""
from __future__ import annotations

import datetime as dt
import uuid

from .guard import safe_display
from .policy import PolicyEngine
from .responses import fmt_txn, handoff_summary

# Campos de la transacción que ve el asesor. Alcanzan para re-evaluar la política (evals/completeness.py).
TXN_WHITELIST = ("transaction_id", "transaction_date", "transaction_type", "amount", "currency", "channel",
                 "merchant_name", "transaction_country", "transaction_city", "transaction_status", "fraud_score")
CUSTOMER_FACTS = ("customer_status", "segment", "complaints_last_90d", "is_repeat_complainer",
                  "open_dispute_transactions")


def _jsonable(v):
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "as_tuple"):  # Decimal
        return float(v)
    return v


def route(policy: PolicyEngine, reason: str) -> dict:
    """Cola, prioridad, SLA, siguiente paso y preguntas del motivo (o las por defecto)."""
    cfg = policy.cfg.get("handoff", {})
    return {**cfg.get("default", {}), **cfg.get("reasons", {}).get(reason, {})}


def queue_label(policy: PolicyEngine, queue: str, lang: str) -> str:
    labels = policy.cfg.get("handoff", {}).get("queues", {}).get(queue, {})
    return labels.get(lang) or labels.get("es") or queue


def _date(v) -> dt.date | None:
    if v is None:
        return None
    if isinstance(v, str):
        v = dt.datetime.fromisoformat(v) if "T" in v or " " in v else dt.date.fromisoformat(v)
    return v.date() if isinstance(v, dt.datetime) else v


def _match(claim: dict, txn: dict | None, method: str | None) -> dict | None:
    if not txn:
        return None
    amount, d = float(txn["amount"]), _date(txn["transaction_date"])
    out = {"transaction_id": txn["transaction_id"], "selected_by": method or "unknown",
           "amount_diff": None, "date_diff_days": None}
    if claim.get("amount"):
        out["amount_diff"] = round(amount - float(claim["amount"]), 2)
    lo, hi = _date(claim.get("date_from")), _date(claim.get("date_to"))
    if lo and hi and d:
        out["date_diff_days"] = 0 if lo <= d <= hi else min(abs((d - lo).days), abs((d - hi).days))
    return out


def _questions(reason: str, r: dict, txn: dict | None, rules: list[dict]) -> list[str]:
    qs = list(r.get("open_questions") or [])
    if txn and reason.startswith("H0"):  # reconocimiento según el tipo de movimiento: sin "comercio" en un retiro
        what = (f"el comercio {txn['merchant_name']}" if txn.get("merchant_name")
                else f"el {txn.get('transaction_type', 'movimiento')} por {txn.get('channel') or 'canal desconocido'}")
        qs.insert(0, f"Validar con el cliente si reconoce {what} ({fmt_txn(txn)}).")
    for h in rules[1:]:  # las demás reglas que se cumplieron también le importan al asesor
        qs.append(f"También se cumplió {h['id']}: {h['explain']}")
    return qs


def build_packet(s: dict, policy: PolicyEngine, reason: str) -> dict:
    r = route(policy, reason)
    txn = s.get("txn")
    decision = s.get("decision") or {}
    rules = decision.get("rules") or []
    trace = s.get("trace", [])
    claim = {k: _jsonable(v) for k, v in (s.get("claim") or {}).items() if v not in (None, [], "")}
    facts = decision.get("facts") or {}
    packet = {
        "schema_version": policy.cfg.get("handoff", {}).get("schema_version", "handoff/v1"),
        "handoff_id": "HND-" + uuid.uuid4().hex[:10].upper(),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "as_of": policy.as_of.isoformat(),
        "reason": reason,
        "queue": r.get("queue"), "priority": r.get("priority"), "sla_hours": r.get("sla_hours"),
        "next_action": r.get("next_action"),
        "language": s.get("lang", "es"),
        # solo lo que escribió el cliente (enmascarado); la conversación completa, con quién habló, va aparte
        "request": [m["text"] for m in s.get("conversation", []) if m.get("role") == "user"][-5:],
        "transcript": [{"role": m.get("role"), "turn": m.get("turn"), "text": m["text"]}
                       for m in s.get("conversation", [])][-10:],
        "customer_claim": claim,
        "match": _match(claim, txn, s.get("match_method")),
        "verified_facts": {"transaction": {k: _jsonable(txn.get(k)) for k in TXN_WHITELIST} if txn else None,
                           **{k: facts[k] for k in CUSTOMER_FACTS if k in facts}},
        "policy": {"version": decision.get("policy_version"), "rules_fired": rules},
        "actions_taken": [c for e in trace for c in e["tools"] if c["tool"] in ("open_dispute", "block_card") and c["ok"]],
        "evidence": [{"turn": e["turn"], "node": e["node"], "tools": [c["tool"] for c in e["tools"]]}
                     for e in trace if e["tools"]],
        "failures": [{"turn": e["turn"], "tool": c["tool"], "error": c.get("error")}
                     for e in trace for c in e["tools"] if not c["ok"]],
        "unresolved_questions": _questions(reason, r, txn, rules),
    }
    packet["summary"] = handoff_summary(packet)  # una línea determinista para el asesor (#32)
    # Red team #33: el paquete lleva texto NO confiable (lo que escribió el cliente, nombre de comercio y ciudad de
    # los datos). Se codifica para quien lo muestra o exporta: sin caracteres invisibles/bidi (un RLO invertía lo
    # que leía el asesor) y sin celdas-fórmula (=HYPERLINK(...) en un CSV exportado). Se hace aquí, en la salida,
    # para cubrir cualquier campo presente o futuro del paquete.
    return safe_display(packet)
