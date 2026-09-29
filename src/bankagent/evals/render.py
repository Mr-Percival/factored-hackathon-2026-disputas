"""Tarjeta Markdown de un paquete de handoff: lo que vería el asesor humano. Sin nada que delate si es un control."""
from __future__ import annotations

import datetime as dt
import json

NONE = "_(no disponible)_"
KNOWN = {"reason", "created_at", "language", "request", "verified_facts", "policy", "actions_taken", "evidence",
         "unresolved_questions", "summary"}


def _date(v) -> str:
    if not v:
        return NONE
    try:
        return dt.datetime.fromisoformat(str(v)).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return str(v)


def _cell(v) -> str:
    return NONE if v in (None, "") else str(v).replace("|", "\\|").replace("\n", " ")


def _code(v) -> str:
    return NONE if v in (None, "") else f"`{_cell(v)}`"


def render_card(pid: str, p: dict, heading: str = "##") -> str:
    h, sub = heading, heading + "#"
    facts = p.get("verified_facts") or {}
    t = facts.get("transaction")
    pol = p.get("policy") or {}
    L = [f"{h} Paquete {pid}", "",
         f"**Motivo de la derivación:** `{p.get('reason') or '-'}` · **Idioma del cliente:** {p.get('language') or '-'}"
         f" · **Creado:** {p.get('created_at') or '-'}", ""]
    if p.get("summary"):
        L += [f"**Resumen:** {p['summary']}", ""]

    L += [f"{sub} Lo que escribió el cliente (PII enmascarada)", ""]
    req = p.get("request") or []
    L += [f"> {i}. {_cell(m)}" + ("  " if i < len(req) else "") for i, m in enumerate(req, 1)] or ["_(sin mensajes)_"]

    L += ["", f"{sub} Hechos verificados (leídos de los sistemas, no del chat)", "", "| Campo | Valor |", "|---|---|"]
    if t:
        where = t.get("merchant_name")
        cat = f" ({t['merchant_category']})" if t.get("merchant_category") else ""
        place = ", ".join(x for x in (t.get("transaction_country"), t.get("transaction_city")) if x)
        amount = f"{float(t['amount']):,.2f} {t.get('currency') or ''}" if t.get("amount") is not None else None
        L += [f"| Transacción | {_code(t.get('transaction_id'))} |",
              f"| Fecha | {_date(t.get('transaction_date'))} |",
              f"| Monto | {_cell(amount)} |",
              f"| Tipo / canal | {_cell(t.get('transaction_type'))} / {_cell(t.get('channel'))} |",
              f"| Comercio | {_cell(where)}{_cell(cat) if cat else ''} |",
              f"| Lugar | {_cell(place)} |",
              f"| Estado de la transacción | {_cell(t.get('transaction_status'))} |",
              f"| Puntaje de fraude (0–100) | {_cell(t.get('fraud_score'))} |",
              f"| Producto | {_code(t.get('product_id'))} |",
              f"| Cliente | {_code(t.get('customer_id'))} |"]
    else:
        L.append("| Transacción | _(ninguna identificada)_ |")
    if "customer_status" in facts or "segment" in facts:
        L.append(f"| Estado / segmento del cliente | {_cell(facts.get('customer_status'))} / {_cell(facts.get('segment'))} |")
    if "complaints_last_90d" in facts or "is_repeat_complainer" in facts:
        rep = {True: "sí", False: "no"}.get(facts.get("is_repeat_complainer"), NONE)
        L.append(f"| Reclamos últimos 90 días | {_cell(facts.get('complaints_last_90d'))} · reclamante recurrente: {rep} |")
    if "open_dispute_transactions" in facts:
        L.append(f"| Disputas abiertas en esta sesión | {', '.join(facts['open_dispute_transactions']) or 'ninguna'} |")

    L += ["", f"{sub} Política aplicada", ""]
    rules = pol.get("rules_fired") or []
    L.append(f"Versión: `{pol.get('version')}`." if pol.get("version") else "Versión: _(no se evaluó la política)_.")
    L += [f"- `{r.get('id')}` ({r.get('outcome')}): {r.get('explain')}" for r in rules] or ["- _(ninguna regla disparada)_"]

    L += ["", f"{sub} Acciones ya realizadas por el agente", ""]
    L += [f"- `{a.get('tool')}` (ok={a.get('ok')}, intento {a.get('attempt')})" for a in p.get("actions_taken") or []] \
        or ["- ninguna"]

    L += ["", f"{sub} Evidencia (qué herramientas se consultaron, por turno)", ""]
    L += [f"- turno {e.get('turn')} · `{e.get('node')}`: {', '.join(e.get('tools') or [])}"
          for e in p.get("evidence") or []] or ["- _(sin llamadas a herramientas)_"]

    L += ["", f"{sub} Preguntas abiertas para el asesor", ""]
    L += [f"{i}. {q}" for i, q in enumerate(p.get("unresolved_questions") or [], 1)] or ["_(ninguna)_"]

    # Campos nuevos del paquete (p. ej. los de #44) se muestran tal cual: la tarjeta no esconde nada al evaluador.
    extra = {k: v for k, v in p.items() if k not in KNOWN}
    if extra:
        L += ["", f"{sub} Otros campos del paquete", ""]
        L += [f"- **{k}**: {_cell(json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else v)}"
              for k, v in extra.items()]
    return "\n".join(L) + "\n"
