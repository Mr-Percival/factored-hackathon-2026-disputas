"""Regla de emparejamiento queja -> transacción disputada (la más plausible).

Las quejas del dataset NO traen la transacción: `origin_interaction_id` es 100% nulo, la descripción es una
plantilla y `affected_product_id` nunca pertenece al cliente de la queja (0% en el marco; ver
reports/replay.md). Por eso la transacción se infiere con una regla explícita y escalonada. Todas las reglas
parten del mismo conjunto de candidatas (POOL):

    POOL = transacciones del MISMO cliente, de un tipo disputable (el mismo filtro del agente:
           Purchase/Withdrawal/Payment/Transfer/Adjustment; un depósito no se disputa) y con
           creation_date - WINDOW_DAYS <= transaction_date <= creation_date.

    R1_amount          claimed_amount presente, misma moneda que la transacción y |monto - reclamado| <= 10%
                       del reclamado -> la de monto más cercano (empate: la más reciente).
    R2_type_approved   la más reciente Approved del tipo esperado por subcategoría
                       (Cargo no reconocido: Purchase/Withdrawal; Cobro indebido: Adjustment/Purchase).
    R3_any_approved    la más reciente Approved de cualquier tipo disputable.
    R4_any_status      la más reciente de cualquier estado (Declined/Pending/Reversed): el cliente pudo ver un
                       cargo rechazado o pendiente; la política lo trata con D02-D04.
    unmatched          POOL vacío -> no hay transacción plausible: en operación iría a un humano.

"La más reciente" porque el cliente suele reclamar poco después de ver el cargo. Es un supuesto, no una
etiqueta: el replay mide al agente CONTRA ESTA REGLA, no contra una verdad conocida.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from ..graph import DISPUTABLE_TYPES

WINDOW_DAYS = 60
AMOUNT_TOL = 0.10
PREFERRED_TYPES = {
    "Cargo no reconocido": ("Purchase", "Withdrawal"),
    "Cobro indebido": ("Adjustment", "Purchase"),
}
RULES = ("R1_amount", "R2_type_approved", "R3_any_approved", "R4_any_status", "unmatched")


@dataclass
class Match:
    rule: str                       # uno de RULES
    txn: dict | None
    pool_size: int                  # candidatas en la ventana (mide la ambigüedad del caso)
    notes: list[str] = field(default_factory=list)


def _day(x) -> dt.date:
    return x.date() if isinstance(x, dt.datetime) else x


def _ts(x) -> dt.datetime:
    return x if isinstance(x, dt.datetime) else dt.datetime.combine(x, dt.time.max)


def candidate_pool(complaint: dict, txns: list[dict], window_days: int = WINDOW_DAYS) -> list[dict]:
    """Transacciones del cliente de la queja que podrían ser la disputada, de la más reciente a la más antigua."""
    created = _ts(complaint["creation_date"])
    start = created - dt.timedelta(days=window_days)
    pool = [t for t in txns
            if t["customer_id"] == complaint["customer_id"] and t["transaction_type"] in DISPUTABLE_TYPES
            and start <= _ts(t["transaction_date"]) <= created]
    # el desempate por id hace la regla determinista aunque dos transacciones compartan fecha y hora
    return sorted(pool, key=lambda t: (_ts(t["transaction_date"]), t["transaction_id"]), reverse=True)


def match_complaint(complaint: dict, txns: list[dict], window_days: int = WINDOW_DAYS,
                    tol: float = AMOUNT_TOL) -> Match:
    pool = candidate_pool(complaint, txns, window_days)
    if not pool:
        return Match("unmatched", None, 0)
    claimed, cur = complaint.get("claimed_amount"), complaint.get("currency")
    notes = []
    if claimed is not None and float(claimed) > 0:
        same_cur = [t for t in pool if t["currency"] == cur]
        if not same_cur:
            notes.append("claimed_currency_mismatch")
        close = [t for t in same_cur if abs(float(t["amount"]) - float(claimed)) <= tol * float(claimed)]
        if close:  # sorted() es estable: ante igual diferencia gana la más reciente (orden del pool)
            return Match("R1_amount", sorted(close, key=lambda t: abs(float(t["amount"]) - float(claimed)))[0],
                         len(pool), notes)
        notes.append("claimed_amount_no_match")
    preferred = PREFERRED_TYPES.get(complaint.get("subcategory"), ())
    for rule, cond in (("R2_type_approved", lambda t: t["transaction_status"] == "Approved" and t["transaction_type"] in preferred),
                       ("R3_any_approved", lambda t: t["transaction_status"] == "Approved"),
                       ("R4_any_status", lambda t: True)):
        hit = next((t for t in pool if cond(t)), None)
        if hit:
            return Match(rule, hit, len(pool), notes)
    raise AssertionError("pool no vacío siempre produce un match")  # pragma: no cover


def pool_class(n: int) -> str:
    """Ambigüedad: 1 candidata (identificación directa), 2-5 (el agente muestra opciones), 0 o >5."""
    return "0" if n == 0 else "1" if n == 1 else "2-5" if n <= 5 else ">5"
