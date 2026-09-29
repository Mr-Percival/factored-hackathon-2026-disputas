"""Verificador determinista de completitud del paquete de handoff: la contraparte automática de la evaluación humana.

Un paquete está COMPLETO si pasa todos los chequeos que le aplican según su motivo:
- campos presentes y no vacíos (pedido, preguntas abiertas, resumen, idioma válido);
- en motivos de política (H0x): transacción y hechos del cliente presentes, versión de política, la primera regla
  disparada es el motivo, y **re-evaluar la política con los hechos del paquete reproduce las mismas reglas**
  (así un hecho alterado o una regla equivocada se detectan sin mirar el texto);
- en motivos técnicos: evidencia de las herramientas (tool_failure) o acciones registradas (action_not_verified).

    python -m bankagent.evals.human_kit check --db data/demo/demo.duckdb [--router rules --router embeddings]
"""
from __future__ import annotations

import datetime as dt
import json

from ..identity import IdentityService
from ..policy import PolicyEngine
from ..tools import BankTools

REQUIRED = ("reason", "created_at", "language", "request", "verified_facts", "policy", "actions_taken", "evidence",
            "unresolved_questions", "summary")
TECHNICAL_REASONS = ("out_of_scope", "tool_failure", "security_lockout", "security_review", "action_not_verified", "no_active_card",
                     # motivos conversacionales (#40)
                     "consent_unclear", "customer_request", "account_takeover", "clarification_exhausted",
                     "dispute_status", "cancel_dispute")
TXN_FIELDS = ("transaction_id", "transaction_date", "amount", "currency", "transaction_status", "transaction_type")
CUSTOMER_FIELDS = ("customer_status", "segment", "complaints_last_90d", "is_repeat_complainer")


def _txn_for_policy(t: dict) -> dict:
    t = dict(t)
    d = t.get("transaction_date")
    if isinstance(d, str):
        t["transaction_date"] = dt.datetime.fromisoformat(d)
    return t


def check_packet(p: dict, policy: PolicyEngine) -> list[tuple[str, bool, str]]:
    """Lista de (chequeo, ok, detalle). Solo incluye los chequeos que aplican al motivo del paquete."""
    rule_ids = {r["id"] for r, _ in policy.rules}
    reason = p.get("reason")
    out: list[tuple[str, bool, str]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        out.append((name, bool(ok), "" if ok else detail))

    missing = [k for k in REQUIRED if k not in p]
    add("campos_presentes", not missing, f"faltan {missing}")
    add("motivo_valido", reason in rule_ids or reason in TECHNICAL_REASONS, f"motivo {reason!r}")
    req = p.get("request") or []
    add("pedido_no_vacio", bool(req) and all(isinstance(m, str) and m.strip() for m in req), "sin mensajes del cliente")
    add("idioma_valido", p.get("language") in ("es", "pt"), f"idioma {p.get('language')!r}")
    add("preguntas_no_vacias", bool(p.get("unresolved_questions")), "sin preguntas abiertas")
    add("resumen_presente", isinstance(p.get("summary"), str) and bool(p.get("summary", "").strip()), "sin resumen")

    facts = p.get("verified_facts") or {}
    txn = facts.get("transaction")
    pol = p.get("policy") or {}
    fired = [r.get("id") for r in pol.get("rules_fired") or []]
    if reason in rule_ids:
        miss_t = [k for k in TXN_FIELDS if not txn or txn.get(k) in (None, "")]
        add("hechos_transaccion", not miss_t, f"transacción sin {miss_t}")
        miss_c = [k for k in CUSTOMER_FIELDS if facts.get(k) is None]
        add("hechos_cliente", not miss_c, f"sin {miss_c}")
        add("politica_version", bool(pol.get("version")), "sin versión de política")
        add("regla_es_el_motivo", bool(fired) and fired[0] == reason, f"motivo {reason} pero reglas {fired}")
        if not miss_t and not miss_c:
            d = policy.decide_dispute(_txn_for_policy(txn), {"customer_status": facts["customer_status"],
                                                             "segment": facts["segment"]},
                                      {"complaints_last_90d": facts["complaints_last_90d"],
                                       "is_repeat_complainer": facts["is_repeat_complainer"],
                                       "open_dispute_transactions": facts.get("open_dispute_transactions") or []})
            again = [h.id for h in d.hits]
            add("reglas_reproducibles", again == fired,
                f"con los hechos del paquete la política dispara {again}, el paquete dice {fired}")
        else:
            add("reglas_reproducibles", False, "no se puede re-evaluar la política sin hechos")
    if reason == "tool_failure":
        add("evidencia_presente", bool(p.get("evidence")), "sin evidencia de la falla")
    if reason == "action_not_verified":
        add("acciones_registradas", bool(p.get("actions_taken")), "sin acciones registradas")
        add("evidencia_presente", bool(p.get("evidence")), "sin evidencia")
    return out


def is_complete(p: dict, policy: PolicyEngine) -> bool:
    return all(ok for _, ok, _ in check_packet(p, policy))


def scenario_packets(db: str, scenarios_path: str, router: str = "rules") -> list[tuple[str, dict]]:
    """Corre los escenarios de docs/demo/demo_customers.json con el agente real y junta todos los handoffs."""
    from ..factory import build_agent

    with open(scenarios_path, encoding="utf-8") as f:
        doc = json.load(f)
    out = []
    for sc in doc["scenarios"]:
        identity = IdentityService()
        tools = BankTools(db, identity)
        try:
            agent = build_agent(tools, router=router, writer="templates")
            token = identity.login(sc["customer_id"])
            for i, turn in enumerate(sc["turns"], 1):
                if turn.get("action") == "expire_session":
                    identity.expire(token)
                    continue
                r = agent.chat(sc["id"], token, turn["say"])
                if r.get("handoff"):
                    out.append((f"{sc['id']}#t{i}", r["handoff"]))
        finally:
            tools._ro.close()
            tools._ops.close()
    return out


def report(groups: dict[str, list[tuple[str, dict]]], policy: PolicyEngine) -> str:
    """Markdown: % completo por origen, fallas por chequeo y el detalle de cada paquete incompleto."""
    lines = ["# Completitud de los paquetes de handoff (verificador determinista)", "",
             "Generado por `python -m bankagent.evals.human_kit check`. Es la contraparte automática de la evaluación "
             "humana (`evals/human/RUBRIC.md`): mide si el paquete trae lo necesario y si es **consistente con la "
             "política** (re-evaluando `config/policy.yaml` con los hechos del paquete), no si es útil para el asesor.",
             "", f"Política: `{policy.version}`.", "",
             "| Origen | Paquetes | Completos | % |", "|---|---|---|---|"]
    detail, fails_by_check = [], {}
    for name, items in groups.items():
        ok_n = 0
        for pid, p in items:
            checks = check_packet(p, policy)
            bad = [(c, d) for c, ok, d in checks if not ok]
            ok_n += not bad
            for c, _ in bad:
                fails_by_check.setdefault(name, {}).setdefault(c, 0)
                fails_by_check[name][c] += 1
            if bad:
                detail.append(f"- `{name}` · `{pid}` (`{p.get('reason')}`): " + "; ".join(f"**{c}** {d}" for c, d in bad))
        pct = f"{100 * ok_n / len(items):.1f}%" if items else "-"
        lines.append(f"| {name} | {len(items)} | {ok_n} | {pct} |")
    lines += ["", "## Fallas por chequeo", ""]
    if not fails_by_check:
        lines.append("Ninguna.")
    for name, fc in fails_by_check.items():
        lines.append(f"- **{name}**: " + ", ".join(f"`{c}` × {n}" for c, n in sorted(fc.items())))
    lines += ["", "## Paquetes incompletos", ""] + (detail or ["Ninguno."])
    return "\n".join(lines) + "\n"
