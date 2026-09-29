"""Herramientas bancarias SIMULADAS sobre la base serving.

Reglas de esta capa (no negociables, no dependen del prompt):
- Cada herramienta recibe el token de sesión y deriva el customer_id de él. Jamás acepta un
  customer_id que venga de la conversación.
- Toda lectura filtra por ese customer_id; pedir un recurso ajeno da AuthError('forbidden').
- La base serving es de solo lectura. Las acciones se escriben en un almacén de operaciones aparte
  (ops) y se VERIFICAN releyendo el estado antes de reportarlas como hechas.
- Cada llamada queda en el registro de auditoría con entrada, resultado y latencia.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
import uuid
from dataclasses import dataclass, field

import duckdb

from .identity import AuthError, IdentityService

CARD_TYPES = ("Tarjeta Crédito", "Tarjeta Débito")


class ToolError(Exception):
    """Falla técnica de una herramienta (timeout, base caída). Se reintenta de forma acotada."""


@dataclass
class ToolCall:
    tool: str
    args: dict
    ok: bool
    result_summary: str
    ms: float


@dataclass
class BankTools:
    serving_db: str
    identity: IdentityService
    ops_db: str = ":memory:"
    audit: list[ToolCall] = field(default_factory=list)

    def __post_init__(self):
        self._ro = duckdb.connect(self.serving_db, read_only=True)
        self._ops = duckdb.connect(self.ops_db)
        self._local = threading.local()
        self._ops.execute("""CREATE TABLE IF NOT EXISTS card_blocks (
            product_id VARCHAR PRIMARY KEY, customer_id VARCHAR, blocked_at TIMESTAMP, reason VARCHAR)""")
        self._ops.execute("""CREATE TABLE IF NOT EXISTS disputes (
            case_id VARCHAR PRIMARY KEY, customer_id VARCHAR, transaction_id VARCHAR UNIQUE,
            reason VARCHAR, status VARCHAR, created_at TIMESTAMP)""")

    # ------------------------------------------------------------------ utilidades
    # Un cursor por hilo. Una conexión DuckDB compartida entre hilos MEZCLA resultados: la prueba de carga
    # (#19) mostró a un cliente recibiendo filas de otro. Ver tests/test_concurrency.py.
    @property
    def _ro_c(self) -> duckdb.DuckDBPyConnection:
        if getattr(self._local, "ro", None) is None:
            self._local.ro = self._ro.cursor()
        return self._local.ro

    @property
    def _ops_c(self) -> duckdb.DuckDBPyConnection:
        if getattr(self._local, "ops", None) is None:
            self._local.ops = self._ops.cursor()
        return self._local.ops

    def _run(self, tool: str, args: dict, fn):
        t0 = time.perf_counter()
        try:
            out = fn()
            self.audit.append(ToolCall(tool, args, True, _summary(out), (time.perf_counter() - t0) * 1000))
            return out
        except (AuthError, ToolError) as e:
            self.audit.append(ToolCall(tool, args, False, f"{type(e).__name__}:{e}", (time.perf_counter() - t0) * 1000))
            raise

    def _rows(self, sql: str, params: list) -> list[dict]:
        cur = self._ro_c.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ------------------------------------------------------------------ lecturas
    def get_profile(self, token: str) -> dict:
        def fn():
            cid = self.identity.resolve(token).customer_id
            rows = self._rows("SELECT customer_id, first_name, country, segment, customer_status FROM customers WHERE customer_id = ?", [cid])
            if not rows:
                raise ToolError("customer_not_found")
            return rows[0]
        return self._run("get_profile", {}, fn)

    def list_cards(self, token: str) -> list[dict]:
        def fn():
            cid = self.identity.resolve(token).customer_id
            cards = self._rows(f"""WITH own AS MATERIALIZED (SELECT product_id, product_type, product_number, currency,
                    product_status FROM products WHERE customer_id = ?)
                SELECT * FROM own WHERE product_type IN {CARD_TYPES} ORDER BY product_type""", [cid])
            blocked = {r[0] for r in self._ops_c.execute("SELECT product_id FROM card_blocks WHERE customer_id = ?", [cid]).fetchall()}
            for c in cards:
                if c["product_id"] in blocked:
                    c["product_status"] = "Blocked"
            return cards
        return self._run("list_cards", {}, fn)

    def search_transactions(self, token: str, date_from: dt.date | None = None, date_to: dt.date | None = None,
                            amount_min: float | None = None, amount_max: float | None = None,
                            merchant: str | None = None, country: str | None = None, limit: int = 10) -> list[dict]:
        args = dict(date_from=date_from, date_to=date_to, amount_min=amount_min, amount_max=amount_max,
                    merchant=merchant, country=country, limit=limit)

        def fn():
            cid = self.identity.resolve(token).customer_id
            where, params = [], [cid]
            if date_from: where.append("transaction_date >= ?"); params.append(date_from)
            if date_to: where.append("transaction_date < ? + INTERVAL 1 DAY"); params.append(date_to)
            if amount_min is not None: where.append("amount >= ?"); params.append(amount_min)
            if amount_max is not None: where.append("amount <= ?"); params.append(amount_max)
            if merchant: where.append("merchant_name ILIKE ?"); params.append(f"%{merchant}%")
            if country: where.append("transaction_country = ?"); params.append(country)
            # CTE materializada: aísla `customer_id = ?` para que DuckDB use el índice (ver pipeline.LOOKUP_INDEXES);
            # con los demás filtros y el ORDER BY ... LIMIT en la misma consulta, el optimizador recorre la tabla entera.
            return self._rows(f"""WITH own AS MATERIALIZED (
                    SELECT transaction_id, transaction_date, product_id, transaction_type, amount, currency,
                    channel, merchant_name, transaction_country, transaction_city, transaction_status
                    FROM transactions WHERE customer_id = ?)
                SELECT * FROM own WHERE {' AND '.join(where) or 'true'} ORDER BY transaction_date DESC LIMIT {int(limit)}""", params)
        return self._run("search_transactions", args, fn)

    def get_transaction(self, token: str, transaction_id: str) -> dict:
        def fn():
            cid = self.identity.resolve(token).customer_id
            rows = self._rows("SELECT * FROM transactions WHERE transaction_id = ?", [transaction_id])
            if not rows:
                raise ToolError("transaction_not_found")
            if rows[0]["customer_id"] != cid:
                raise AuthError("forbidden")  # existe, pero no es suyo: no se revela nada
            return rows[0]
        return self._run("get_transaction", {"transaction_id": transaction_id}, fn)

    def dispute_history(self, token: str) -> dict:
        """Hechos para la política: reclamos previos y disputas abiertas en esta sesión."""
        def fn():
            cid = self.identity.resolve(token).customer_id
            r = self._ro_c.execute("""SELECT count(*) FILTER (WHERE creation_date >= (SELECT max(creation_date) FROM complaints) - INTERVAL 90 DAY),
                    bool_or(is_repeat_complainer) FROM complaints WHERE customer_id = ?""", [cid]).fetchone()
            open_disputes = [x[0] for x in self._ops_c.execute("SELECT transaction_id FROM disputes WHERE customer_id = ?", [cid]).fetchall()]
            return {"complaints_last_90d": r[0] or 0, "is_repeat_complainer": bool(r[1]), "open_dispute_transactions": open_disputes}
        return self._run("dispute_history", {}, fn)

    def list_disputes(self, token: str) -> list[dict]:
        """Disputas abiertas por ESTE cliente (ops). Para "¿en qué va mi disputa?": nunca de otro cliente."""
        def fn():
            cid = self.identity.resolve(token).customer_id
            cur = self._ops_c.execute("""SELECT case_id, transaction_id, status, created_at FROM disputes
                WHERE customer_id = ? ORDER BY created_at DESC""", [cid])
            return [dict(zip(("case_id", "transaction_id", "status", "created_at"), r)) for r in cur.fetchall()]
        return self._run("list_disputes", {}, fn)

    # ------------------------------------------------------------------ acciones (requieren confirmación)
    def block_card(self, token: str, product_id: str, confirmed: bool) -> dict:
        def fn():
            cid = self.identity.resolve(token).customer_id
            if not confirmed:
                raise ToolError("confirmation_required")
            own = self._rows("""WITH p AS MATERIALIZED (SELECT product_type, customer_id FROM products WHERE product_id = ?)
                SELECT product_type FROM p WHERE customer_id = ?""", [product_id, cid])
            if not own or own[0]["product_type"] not in CARD_TYPES:
                raise AuthError("forbidden")
            self._ops_c.execute("INSERT OR IGNORE INTO card_blocks VALUES (?, ?, now(), 'customer_reported')", [product_id, cid])
            verified = self._ops_c.execute("SELECT count(*) FROM card_blocks WHERE product_id = ?", [product_id]).fetchone()[0] == 1
            return {"product_id": product_id, "status": "Blocked" if verified else "Unknown", "verified": verified}
        return self._run("block_card", {"product_id": product_id, "confirmed": confirmed}, fn)

    def open_dispute(self, token: str, transaction_id: str, reason: str, confirmed: bool) -> dict:
        def fn():
            cid = self.identity.resolve(token).customer_id
            if not confirmed:
                raise ToolError("confirmation_required")
            self.get_transaction(token, transaction_id)  # valida propiedad
            existing = self._ops_c.execute("SELECT case_id FROM disputes WHERE transaction_id = ?", [transaction_id]).fetchone()
            case_id = existing[0] if existing else "DSP-" + uuid.uuid4().hex[:10].upper()
            if not existing:  # idempotente: repetir la acción no abre dos casos
                self._ops_c.execute("INSERT INTO disputes VALUES (?, ?, ?, ?, 'Open', now())", [case_id, cid, transaction_id, reason])
            verified = self._ops_c.execute("SELECT count(*) FROM disputes WHERE case_id = ? AND customer_id = ?", [case_id, cid]).fetchone()[0] == 1
            return {"case_id": case_id, "transaction_id": transaction_id, "status": "Open", "verified": verified}
        return self._run("open_dispute", {"transaction_id": transaction_id, "confirmed": confirmed}, fn)


def _summary(out) -> str:
    if isinstance(out, list):
        return f"{len(out)} rows"
    if isinstance(out, dict):
        return ", ".join(f"{k}={v}" for k, v in list(out.items())[:4])
    return str(out)[:80]
