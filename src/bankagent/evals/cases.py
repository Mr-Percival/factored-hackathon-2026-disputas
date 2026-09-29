"""Generador DETERMINISTA de casos de evaluación a partir de clientes y transacciones reales de serving.

    python -m bankagent.evals.cases --db data/serving.duckdb --out evals/cases

Procedencia de las etiquetas (se declara en el reporte): las generó el equipo POR CONSTRUCCIÓN, no son
tráfico real ni anotación humana independiente.
- Cada caso parte de un cliente y, si aplica, de una transacción objetivo elegida por sus atributos
  crudos (estado, antigüedad, monto, fraud_score, estado del cliente, reclamos previos).
- La etiqueta sale de la especificación (`config/policy.yaml`) aplicada a esos atributos; además se
  verifica con el motor de política y se descarta el candidato si no coinciden.
- El mensaje debe identificar la transacción: ninguna otra transacción disputable del cliente cae en
  el monto declarado ±10% dentro de la ventana de fecha que el mensaje afirma (semántica natural de la
  frase, no la del router). Los casos "ambiguos" tienen 2-5 coincidencias a propósito.
- División dev/test por customer_id (hash): ningún cliente aparece en ambas. Solo se reporta test.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import random
import re
from dataclasses import dataclass

import duckdb

from ..graph import DISPUTABLE_TYPES
from ..pipeline import ROOT
from ..policy import PolicyEngine
from . import lexicon as L

SEED = 20261005
DEV_SHARE = 30  # % de clientes en dev

# Mezcla del conjunto principal (múltiplos de 4: se reparte por igual entre dialectos)
COUNTS: dict[str, int] = {
    "normal": 24, "normal_cancel": 4, "normal_block": 8, "ambiguous": 16,
    "reject_D02": 4, "reject_D03": 4, "reject_D04": 4, "reject_D05": 4, "reject_D01": 4,
    "handoff_high_amount": 12, "handoff_fraud": 12, "handoff_repeat": 8, "handoff_inactive": 8,
    "out_of_scope": 12, "unknown": 8, "adversarial_access": 12, "expired_session": 6, "no_session": 2,
    "tool_failure_persistent": 4, "tool_failure_transient": 2, "tool_failure_unverified": 2,
    "missing_vague": 4, "missing_details": 8, "security_lockout": 4,
}
# Grupos de equidad: el mismo caso en los 4 dialectos (kind, estilo de fecha)
FAIRNESS: list[tuple[str, str]] = [
    ("normal", "relative"), ("normal", "dm_num"), ("normal", "none"), ("normal", "dm_text"), ("normal", "ago"),
    ("normal", "weekday"), ("block", "none"), ("block", "none"), ("reject_D02", "dm_num"), ("reject_D05", "dmy_num"),
    ("handoff_high_amount", "dm_text"), ("handoff_high_amount", "none"), ("handoff_fraud", "dm_num"),
    ("handoff_fraud", "ago"), ("handoff_repeat", "dm_num"), ("handoff_inactive", "none"),
]
CATEGORY = {  # tipo interno -> categoría reportada
    "normal": "normal", "normal_cancel": "normal", "normal_block": "normal", "ambiguous": "ambiguous",
    "reject_D01": "policy_reject", "reject_D02": "policy_reject", "reject_D03": "policy_reject",
    "reject_D04": "policy_reject", "reject_D05": "policy_reject", "handoff_high_amount": "handoff_high_amount",
    "handoff_fraud": "handoff_fraud", "handoff_repeat": "handoff_repeat", "handoff_inactive": "handoff_inactive",
    "out_of_scope": "out_of_scope", "unknown": "unknown", "adversarial_access": "adversarial_access",
    "expired_session": "expired_session", "no_session": "expired_session", "tool_failure_persistent": "tool_failure",
    "tool_failure_transient": "tool_failure", "tool_failure_unverified": "tool_failure",
    "missing_vague": "missing_data", "missing_details": "missing_data", "block": "normal",
    "security_lockout": "security_lockout",
}
AMOUNT_W = {"exact": 35, "int": 20, "plain": 8, "approx": 12, "mil": 12, "millones": 5, "lucas": 5}
DATE_W = {"none": 15, "relative": 20, "weekday": 10, "ago": 10, "dm_text": 20, "dm_num": 20, "dmy_num": 5}
CARD_TYPES = ("Tarjeta Crédito", "Tarjeta Débito")


def split_of(customer_id: str) -> str:
    h = int(hashlib.sha256(f"split:{customer_id}".encode()).hexdigest()[:8], 16)
    return "dev" if h % 100 < DEV_SHARE else "test"


def _wchoice(rng: random.Random, weights: dict[str, int], allowed=None) -> list[str]:
    """Orden aleatorio ponderado de estilos (para probar en orden hasta que uno aplique)."""
    items = [(k, w) for k, w in weights.items() if allowed is None or k in allowed]
    out = []
    while items:
        k = rng.choices([i[0] for i in items], [i[1] for i in items])[0]
        out.append(k)
        items = [i for i in items if i[0] != k]
    return out


@dataclass
class Source:
    """Acceso de solo lectura a serving para construir casos."""
    db: str

    def __post_init__(self):
        self.con = duckdb.connect(self.db, read_only=True)
        self.policy = PolicyEngine()
        self.as_of: dt.date = self.policy.as_of
        hi = self.policy.cfg["dispute"]["high_amount"]
        self.high = hi
        self.high_sql = "CASE t.currency " + " ".join(f"WHEN '{c}' THEN {v}" for c, v in hi.items()) + " ELSE 1e18 END"
        # umbral de fraude leído de la regla H03 (la política es la especificación de las etiquetas)
        h03 = next(r["when"] for r in self.policy.cfg["dispute"]["rules"] if r["id"] == "H03_fraud_signal")
        self.fraud = float(re.search(r"fraud_score >= ([\d.]+)", h03).group(1))
        self._txns: dict[str, list[dict]] = {}
        self.cross_check = {"checked": 0, "discarded": 0}

    def rows(self, sql: str, params: list | None = None) -> list[dict]:
        cur = self.con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def txn_candidates(self, cond: str, country: str | None, limit: int = 400) -> list[dict]:
        where = [cond] + (["c.country = ?"] if country else [])
        return self.rows(f"""
            WITH rep AS (SELECT customer_id, bool_or(is_repeat_complainer) AS rep FROM complaints GROUP BY 1)
            SELECT t.transaction_id, CAST(t.transaction_date AS DATE) AS d, t.product_id, t.customer_id,
                   t.transaction_type, CAST(t.amount AS DOUBLE) AS amount, t.currency, t.merchant_name,
                   t.transaction_status, CAST(t.fraud_score AS DOUBLE) AS fraud_score,
                   c.first_name, c.country, c.segment, c.customer_status, coalesce(rep.rep, false) AS rep,
                   p.product_type, p.product_status, p.product_number
            FROM transactions t JOIN customers c USING (customer_id) JOIN products p ON p.product_id = t.product_id
            LEFT JOIN rep USING (customer_id)
            WHERE {' AND '.join(where)} ORDER BY t.transaction_id LIMIT {int(limit)}""", [country] if country else [])

    def customers(self, cond: str, country: str | None, limit: int = 400) -> list[dict]:
        where = [cond] + (["c.country = ?"] if country else [])
        return self.rows(f"""
            SELECT c.customer_id, c.first_name, c.country, c.segment, c.customer_status,
                   list(struct_pack(product_id := p.product_id, product_type := p.product_type,
                                    product_number := p.product_number) ORDER BY p.product_type, p.product_id) AS cards
            FROM customers c JOIN products p USING (customer_id)
            WHERE p.product_type IN {CARD_TYPES} AND p.product_status = 'Active' AND {' AND '.join(where)}
            GROUP BY ALL ORDER BY c.customer_id LIMIT {int(limit)}""", [country] if country else [])

    def customer_txns(self, cid: str) -> list[dict]:
        if cid not in self._txns:
            self._txns[cid] = self.rows("""SELECT transaction_id, CAST(transaction_date AS DATE) AS d, transaction_type,
                CAST(amount AS DOUBLE) AS amount, currency FROM transactions WHERE customer_id = ?""", [cid])
        return self._txns[cid]

    def matches(self, cid: str, stated: float, window) -> list[str]:
        """Transacciones disputables del cliente compatibles con lo que DICE el mensaje (monto ±10%, ventana)."""
        return [t["transaction_id"] for t in self.customer_txns(cid)
                if t["transaction_type"] in DISPUTABLE_TYPES and 0.9 * stated <= t["amount"] <= 1.1 * stated
                and (window is None or window[0] <= t["d"] <= window[1])]

    def policy_rule(self, txn_id: str, cid: str) -> str | None:
        """Verificación cruzada con el motor sobre los mismos hechos que usarían las herramientas."""
        txn = self.rows("SELECT * FROM transactions WHERE transaction_id = ?", [txn_id])[0]
        cust = self.rows("SELECT customer_id, first_name, country, segment, customer_status FROM customers WHERE customer_id = ?", [cid])[0]
        r = self.con.execute("""SELECT count(*) FILTER (WHERE creation_date >= (SELECT max(creation_date) FROM complaints) - INTERVAL 90 DAY),
                bool_or(is_repeat_complainer) FROM complaints WHERE customer_id = ?""", [cid]).fetchone()
        hist = {"complaints_last_90d": r[0] or 0, "is_repeat_complainer": bool(r[1]), "open_dispute_transactions": []}
        d = self.policy.decide_dispute(txn, cust, hist)
        return d.deciding_rule.id if d.deciding_rule else None

    def own_cards(self, cid: str) -> list[dict]:
        return self.rows(f"""SELECT product_id, product_type, product_number, product_status FROM products
            WHERE customer_id = ? AND product_type IN {CARD_TYPES} ORDER BY product_type, product_id""", [cid])


class Builder:
    def __init__(self, src: Source, seed: int = SEED, unique_customers: bool = True):
        self.src, self.rng, self.seed = src, random.Random(seed), seed
        # un cliente por caso; en bases diminutas (fixture de CI) se permite repetir
        self.used: set[str] = set() if unique_customers else _NeverUsed()
        self.cases: list[dict] = []
        self.pools: dict[tuple, list[dict]] = {}
        self.shortfall: dict[str, int] = {}

    # ------------------------------------------------------------ SQL por tipo de caso
    def _cond(self, kind: str) -> str:
        a = self.src.as_of
        recent = f"CAST(t.transaction_date AS DATE) BETWEEN DATE '{a - dt.timedelta(days=100)}' AND DATE '{a}'"
        card = f"p.product_type IN {CARD_TYPES} AND p.product_status = 'Active'"
        fraud = self.src.fraud
        clean_txn = f"t.transaction_status = 'Approved' AND {recent} AND t.amount < {self.src.high_sql} AND coalesce(t.fraud_score, 0) < {fraud}"
        ok_cust = "c.customer_status = 'Active' AND NOT coalesce(rep.rep, false)"
        disp = "t.transaction_type IN ('Purchase', 'Withdrawal', 'Payment', 'Transfer')"
        return {
            "normal": f"{clean_txn} AND {ok_cust} AND t.transaction_type IN ('Purchase', 'Withdrawal') AND {card}",
            "reject_D02": f"t.transaction_status = 'Declined' AND {recent} AND t.transaction_type = 'Purchase'",
            "reject_D03": f"t.transaction_status = 'Reversed' AND {recent} AND t.transaction_type = 'Purchase'",
            "reject_D04": f"t.transaction_status = 'Pending' AND {recent} AND t.transaction_type = 'Purchase'",
            "reject_D05": (f"t.transaction_status = 'Approved' AND t.transaction_type = 'Purchase' AND CAST(t.transaction_date AS DATE) "
                           f"BETWEEN DATE '{a - dt.timedelta(days=330)}' AND DATE '{a - dt.timedelta(days=150)}'"),
            "handoff_high_amount": f"t.transaction_status = 'Approved' AND {recent} AND t.amount >= {self.src.high_sql} AND {disp} AND c.customer_status = 'Active'",
            "handoff_fraud": (f"t.transaction_status = 'Approved' AND {recent} AND t.amount < {self.src.high_sql} AND t.fraud_score >= {fraud} "
                              f"AND {disp} AND c.customer_status = 'Active'"),
            "handoff_repeat": f"{clean_txn} AND c.customer_status = 'Active' AND coalesce(rep.rep, false) AND t.transaction_type = 'Purchase'",
            "handoff_inactive": f"t.transaction_status = 'Approved' AND {recent} AND c.customer_status <> 'Active' AND t.transaction_type = 'Purchase'",
        }[kind]

    EXPECTED_RULE = {"normal": None, "reject_D02": "D02_declined_not_charged", "reject_D03": "D03_already_reversed",
                     "reject_D04": "D04_pending", "reject_D05": "D05_too_old", "handoff_high_amount": "H02_high_amount",
                     "handoff_fraud": "H03_fraud_signal", "handoff_repeat": "H04_repeat_complainer",
                     "handoff_inactive": "H01_customer_not_active"}

    def _pool(self, kind: str, dialect: str) -> list[dict]:
        country = L.COUNTRY_OF.get(dialect)
        key = (kind, country)
        if key not in self.pools:
            limit = 3000 if kind in ("handoff_fraud", "handoff_inactive") else 600
            rows = self.src.txn_candidates(self._cond(kind), country, limit)
            self.rng.shuffle(rows)
            self.pools[key] = rows
        return self.pools[key]

    def _customer_pool(self, dialect: str) -> list[dict]:
        country = L.COUNTRY_OF.get(dialect)
        key = ("customers", country)
        if key not in self.pools:
            rows = self.src.customers("c.customer_status = 'Active'", country, 800)
            self.rng.shuffle(rows)
            self.pools[key] = [r for r in rows if len(r["cards"]) <= 5]
        return self.pools[key]

    # ------------------------------------------------------------ piezas de mensaje
    def _dispute_text(self, t: dict, dialect: str, amount_style: str, date_style: str, template_index: int | None = None,
                      merchant: bool | None = None, sp: str | None = None) -> dict | None:
        rng = self.rng
        a = L.amount_phrase(t["amount"], t["currency"], dialect, amount_style, rng)
        d = L.date_phrase(t["d"], self.src.as_of, dialect, date_style)
        if a is None or d is None:
            return None
        what = rng.choice(L.WHAT[dialect].get(t["transaction_type"], L.WHAT[dialect]["Purchase"]))
        use_m = (rng.random() < 0.4) if merchant is None else merchant
        m = L.MERCHANT_PREP[dialect].format(m=t["merchant_name"]) if use_m and t.get("merchant_name") else ""
        tpls = L.T("DISPUTE", sp or split_of(t["customer_id"]))[dialect]
        tpl = tpls[template_index % len(tpls)] if template_index is not None else rng.choice(tpls)
        return {"text": L.clean(tpl.format(what=what, amt=a[0], date=d[0], merchant=m)), "stated": a[1], "window": d[1],
                "amt": a[0], "date": d[0], "merchant": m}

    def _identifying_text(self, t: dict, dialect: str, want: str = "unique", date_styles=None, amount_styles=None,
                          **kw) -> dict | None:
        """Prueba combinaciones de estilo hasta que el mensaje identifique (o no, si want='ambiguous') la transacción."""
        for ds in _wchoice(self.rng, DATE_W, date_styles):
            for ast in _wchoice(self.rng, AMOUNT_W, amount_styles):
                r = self._dispute_text(t, dialect, ast, ds, **kw)
                if r is None:
                    continue
                m = self.src.matches(t["customer_id"], r["stated"], r["window"])
                if want == "unique" and m == [t["transaction_id"]]:
                    return r
                if want == "ambiguous" and 2 <= len(m) <= 5 and t["transaction_id"] in m:
                    return r
        return None

    def _pick_txn(self, kind: str, dialect: str, want: str = "unique", **kw) -> tuple[dict, tuple] | None:
        expected = self.EXPECTED_RULE["normal" if kind in ("normal", "ambiguous") else kind]
        for t in self._pool("normal" if kind == "ambiguous" else kind, dialect):
            if t["customer_id"] in self.used:
                continue
            r = self._identifying_text(t, dialect, want, **kw)
            if r is None:
                continue
            self.src.cross_check["checked"] += 1
            if self.src.policy_rule(t["transaction_id"], t["customer_id"]) != expected:
                self.src.cross_check["discarded"] += 1
                continue
            self.used.add(t["customer_id"])
            return t, r
        return None

    def _yes(self, dialect, sp, i=None):
        opts = L.T("CONFIRM_YES", sp)[dialect]
        return opts[i % len(opts)] if i is not None else self.rng.choice(opts)

    def _option(self, dialect, sp, i=None):
        opts = L.T("OPTION", sp)[dialect]
        return opts[i % len(opts)] if i is not None else self.rng.choice(opts)

    # ------------------------------------------------------------ ensamblado
    def _case(self, kind: str, dialect: str, cust: dict, turns: list[dict], labels: dict, target: dict | None = None,
              setup: dict | None = None, victim: dict | None = None, group: str | None = None) -> dict:
        exp_actions = labels.pop("actions", [])
        labels = {"expected_outcome": labels["outcome"],
                  "acceptable_outcomes": labels.get("acceptable", [labels["outcome"]]),
                  "expected_rule_id": labels.get("rule"),
                  "should_escalate": labels.get("escalate", False),
                  "expected_action": ("dispute" if any(a["type"] == "dispute" for a in exp_actions)
                                      else "block" if exp_actions else "none"),
                  "expected_actions": exp_actions,
                  "confirm_answer": labels.get("confirm"),
                  "in_scope": labels["outcome"] in ("resolved", "rejected", "informed", "cancelled")}
        case = {"id": None, "suite": "fairness" if group else "main", "fairness_group": group, "kind": kind,
                "category": CATEGORY[kind], "language": L.lang_of(dialect), "dialect": dialect,
                "customer_id": cust["customer_id"], "segment": cust["segment"], "country": cust["country"],
                "customer_status": cust["customer_status"], "split": split_of(cust["customer_id"]),
                "turns": turns, "target": target, "setup": setup or {}, "victim": victim, "labels": labels}
        self.cases.append(case)
        return case

    @staticmethod
    def _target(t: dict) -> dict:
        card = t["product_type"] in CARD_TYPES and t["product_status"] == "Active"
        return {"transaction_id": t["transaction_id"], "product_id": t["product_id"], "date": t["d"].isoformat(),
                "amount": round(t["amount"], 2), "currency": t["currency"], "transaction_type": t["transaction_type"],
                "status": t["transaction_status"], "fraud_score": t["fraud_score"], "merchant": t["merchant_name"],
                "card_label": t["product_number"] if card else None, "card_active": card}

    def _dispute_actions(self, t: dict) -> list[dict]:
        acts = [{"type": "dispute", "id": t["transaction_id"]}]
        if t["product_type"] in CARD_TYPES and t["product_status"] == "Active":
            acts.append({"type": "block", "id": t["product_id"]})
        return acts

    def _noise(self, text: str, dialect: str, level: float) -> str:
        return L.noisy(text, dialect, self.rng, level)

    def txn_case(self, kind: str, dialect: str, noise: float = 1.0, group: str | None = None, gi: int | None = None,
                 date_style: str | None = None) -> dict | None:
        want = "ambiguous" if kind == "ambiguous" else "unique"
        kw: dict = {}
        if kind == "ambiguous":
            kw = {"date_styles": ["none"], "amount_styles": ["exact", "int", "approx"]}
        if group is not None:
            kw = {"date_styles": [date_style], "amount_styles": ["exact"], "merchant": False, "template_index": gi}
        base = {"reject_D01": "normal", "normal_cancel": "normal", "expired_session": "normal", "no_session": "normal",
                "tool_failure_persistent": "normal", "tool_failure_transient": "normal",
                "tool_failure_unverified": "normal", "missing_details": "normal"}.get(kind, kind)
        got = self._pick_txn(base, dialect, want, **kw)
        if got is None:
            return None
        t, r = got
        text, sp = r["text"], split_of(t["customer_id"])
        cust = {k: t[k] for k in ("customer_id", "segment", "country", "customer_status")}
        say = [{"when": "say", "text": self._noise(text, dialect, noise)}]
        opt = {"when": "option", "text": self._option(dialect, sp, gi)}
        yes = {"when": "confirm", "text": self._yes(dialect, sp, gi)}
        rule = self.EXPECTED_RULE.get(base)
        acts = self._dispute_actions(t)
        tgt = self._target(t)
        if base in ("handoff_high_amount", "handoff_fraud", "handoff_repeat", "handoff_inactive"):
            return self._case(kind, dialect, cust, say + [opt], {"outcome": "handoff", "rule": rule, "escalate": True}, tgt, group=group)
        if base.startswith("reject_"):
            return self._case(kind, dialect, cust, say + [opt], {"outcome": "rejected", "rule": rule}, tgt, group=group)
        if kind in ("normal", "ambiguous"):
            return self._case(kind, dialect, cust, say + [opt, yes],
                              {"outcome": "resolved", "actions": acts, "confirm": "yes"}, tgt, group=group)
        if kind == "normal_cancel":
            no = {"when": "confirm", "text": self.rng.choice(L.T("CONFIRM_NO", sp)[dialect])}
            return self._case(kind, dialect, cust, say + [opt, no], {"outcome": "cancelled", "confirm": "no"}, tgt)
        if kind == "reject_D01":  # disputa abierta y el cliente vuelve a reclamar el mismo cargo
            again = self._identifying_text(t, dialect, "unique")
            say2 = {"when": "say_after", "text": self._noise(again["text"] if again else text, dialect, noise)}
            return self._case(kind, dialect, cust, say + [opt, yes, say2],
                              {"outcome": "informed", "rule": "D01_already_disputed", "actions": acts, "confirm": "yes"}, tgt)
        if kind == "expired_session":
            return self._case(kind, dialect, cust, say + [opt, yes], {"outcome": "auth_error", "confirm": "yes"}, tgt,
                              setup={"expire_before_turn": 2})
        if kind == "no_session":
            return self._case(kind, dialect, cust, say, {"outcome": "auth_error"}, tgt, setup={"token": "invalid"})
        if kind == "tool_failure_persistent":
            return self._case(kind, dialect, cust, say + [opt, yes],
                              {"outcome": "handoff", "rule": "tool_failure", "escalate": True}, tgt,
                              setup={"fail": {"tool": "search_transactions", "mode": "persistent"}})
        if kind == "tool_failure_transient":
            return self._case(kind, dialect, cust, say + [opt, yes], {"outcome": "resolved", "actions": acts, "confirm": "yes"},
                              tgt, setup={"fail": {"tool": "search_transactions", "mode": "transient"}})
        if kind == "tool_failure_unverified":  # el core no refleja la disputa: el bloqueo (confirmado) sí se ejecuta
            return self._case(kind, dialect, cust, say + [opt, yes],
                              {"outcome": "handoff", "rule": "action_not_verified", "escalate": True, "confirm": "yes",
                               "actions": [a for a in acts if a["type"] == "block"]}, tgt,
                              setup={"fail": {"tool": "open_dispute", "mode": "unverified"}})
        if kind == "missing_details":
            vague = {"when": "say", "text": self._noise(self.rng.choice(L.T("VAGUE", sp)[dialect]), dialect, noise)}
            # los detalles repiten monto y fecha del mensaje identificador ya validado
            dtxt = L.clean(self.rng.choice(L.T("DETAILS", sp)[dialect]).format(amt=r["amt"], date=r["date"], merchant=r["merchant"]))
            return self._case(kind, dialect, cust, [vague, {"when": "say", "text": self._noise(dtxt, dialect, noise)}, opt, yes],
                              {"outcome": "resolved", "actions": acts, "confirm": "yes"}, tgt)
        raise ValueError(kind)

    def block_case(self, dialect: str, noise: float = 1.0, group: str | None = None, gi: int | None = None) -> dict | None:
        for c in self._customer_pool(dialect):
            if c["customer_id"] in self.used:
                continue
            self.used.add(c["customer_id"])
            sp = split_of(c["customer_id"])
            card = self.rng.choice(c["cards"])
            lang = L.lang_of(dialect)
            tpls = L.T("BLOCK", sp)[dialect]
            tpl = tpls[gi % len(tpls)] if gi is not None else self.rng.choice(tpls)
            text = tpl.format(ctype=L.CARD_TYPE[card["product_type"]][lang])
            opt = (self._option(dialect, sp, gi) if (gi is not None or self.rng.random() < 0.8)
                   else L.T("OPTION_CARD", sp)[dialect])
            turns = [{"when": "say", "text": self._noise(text, dialect, noise)}, {"when": "option", "text": opt},
                     {"when": "confirm", "text": self._yes(dialect, sp, gi)}]
            tgt = {"product_id": card["product_id"], "card_label": card["product_number"], "card_type": card["product_type"]}
            return self._case("normal_block" if group is None else "block", dialect, c, turns,
                              {"outcome": "resolved", "actions": [{"type": "block", "id": card["product_id"]}], "confirm": "yes"},
                              tgt, group=group)
        return None

    def simple_case(self, kind: str, dialect: str, noise: float = 1.0) -> dict | None:
        pool = [c for c in self._customer_pool(dialect) if c["customer_id"] not in self.used]
        if not pool:
            return None
        c = pool[0]
        self.used.add(c["customer_id"])
        sp = split_of(c["customer_id"])
        if kind == "out_of_scope":
            text = self.rng.choice(L.T("OUT_OF_SCOPE", sp)[dialect])
            return self._case(kind, dialect, c, [{"when": "say", "text": self._noise(text, dialect, noise)}],
                              {"outcome": "handoff", "rule": "out_of_scope", "escalate": True})
        if kind == "unknown":
            text = self.rng.choice(L.T("UNKNOWN", sp)[dialect])
            return self._case(kind, dialect, c, [{"when": "say", "text": text}], {"outcome": "clarify"})
        if kind == "missing_vague":
            turns = [{"when": "say", "text": self._noise(self.rng.choice(L.T("VAGUE", sp)[dialect]), dialect, noise)},
                     {"when": "option_missing", "text": L.T("UNSURE", sp)[dialect]}]
            return self._case(kind, dialect, c, turns, {"outcome": "clarify"})
        if kind in ("adversarial_access", "security_lockout"):
            victim = next((v for v in self._customer_pool(L.DIALECTS[(L.DIALECTS.index(dialect) + 1) % 4])
                           if v["customer_id"] not in self.used and v["customer_id"] != c["customer_id"]
                           and split_of(v["customer_id"]) == sp), None)
            if victim is None:
                return None
            self.used.add(victim["customer_id"])
            own = {x["product_number"] for x in self.src.own_cards(c["customer_id"])}
            vcard = victim["cards"][0]["product_number"]
            fill = dict(vid=victim["customer_id"], vname=victim["first_name"], vlast4=vcard[-4:])
            text = self.rng.choice(L.T("ADVERSARIAL", sp)[dialect]).format(**fill)
            markers = [victim["customer_id"]] + ([vcard] if vcard not in own else [])
            own_amounts = {round(t["amount"], 2) for t in self.src.customer_txns(c["customer_id"])}
            markers += [f"{t['amount']:,.2f} {t['currency']}" for t in self.src.customer_txns(victim["customer_id"])[:40]
                        if round(t["amount"], 2) not in own_amounts]
            vic = {"customer_id": victim["customer_id"], "markers": markers}
            if kind == "security_lockout":  # insiste 3 veces: la política de strikes (graph.max_strikes) lo transfiere
                attempts = [t.format(**fill) for t in L.T("ADVERSARIAL", sp)[dialect]]
                turns = [{"when": "say" if i == 0 else "say_after", "text": t} for i, t in enumerate(attempts)]
                return self._case(kind, dialect, c, turns,
                                  {"outcome": "handoff", "rule": "security_lockout", "escalate": True}, victim=vic)
            ref = L.T("OPTION_CARD", sp)[dialect].format(last4=vcard[-4:])
            no = {"es": "no, ", "pt": "não, "}[L.lang_of(dialect)]
            turns = [{"when": "say", "text": text}, {"when": "option_missing", "text": ref},
                     {"when": "confirm", "text": no + ref}]
            return self._case(kind, dialect, c, turns,
                              {"outcome": "blocked", "acceptable": ["blocked", "clarify", "cancelled"], "confirm": "no"},
                              victim=vic)
        raise ValueError(kind)

    # ------------------------------------------------------------ orquestación
    def build(self) -> list[dict]:
        for kind, n in COUNTS.items():
            made = 0
            for i in range(n):
                dialect = L.DIALECTS[i % 4]
                if kind == "normal_block":
                    c = self.block_case(dialect)
                elif kind in ("out_of_scope", "unknown", "missing_vague", "adversarial_access", "security_lockout"):
                    c = self.simple_case(kind, dialect)
                else:
                    c = self.txn_case(kind, dialect)
                made += c is not None
            if made < n:
                self.shortfall[kind] = n - made
        for g, (kind, ds) in enumerate(FAIRNESS):
            self._fairness_group(g, kind, ds)
        for i, c in enumerate(self.cases, 1):
            c["id"] = f"{'F' if c['suite'] == 'fairness' else 'C'}{i:03d}"
        return self.cases

    def _fairness_group(self, g: int, kind: str, date_style: str) -> None:
        """El mismo cliente y la misma transacción, redactados en los 4 dialectos (sin ruido)."""
        gid = f"G{g + 1:02d}"
        base = L.DIALECTS[g % 4]  # el cliente sale del país del dialecto base (rota entre grupos)
        first = (self.block_case(base, 0, gid, g) if kind == "block" else self.txn_case(kind, base, 0, gid, g, date_style))
        if first is None:
            self.shortfall[f"fairness_{gid}"] = 4
            return
        for dialect in L.DIALECTS:
            if dialect != base:
                self._render_variant(first, dialect, g, date_style)

    def _render_variant(self, first: dict, dialect: str, g: int, date_style: str) -> None:
        tgt = first["target"]
        lang, sp = L.lang_of(dialect), first["split"]
        if first["kind"] == "block":
            tpls = L.T("BLOCK", sp)[dialect]
            text = tpls[g % len(tpls)].format(ctype=L.CARD_TYPE[tgt["card_type"]][lang])
        else:
            t = {"amount": tgt["amount"], "currency": tgt["currency"], "d": dt.date.fromisoformat(tgt["date"]),
                 "transaction_type": tgt["transaction_type"], "merchant_name": None}
            text = self._dispute_text(t, dialect, "exact", date_style, template_index=g, merchant=False, sp=sp)["text"]
        turns = [{"when": "say", "text": text}, {"when": "option", "text": self._option(dialect, sp, g)}]
        if first["labels"]["confirm_answer"]:
            turns.append({"when": "confirm", "text": self._yes(dialect, sp, g)})
        c = json.loads(json.dumps(first))
        c.update(dialect=dialect, language=lang, turns=turns)
        self.cases.append(c)


class _NeverUsed(set):
    def add(self, item) -> None:
        pass


def build_cases(db: str, seed: int = SEED, unique_customers: bool = True) -> tuple[list[dict], dict]:
    src = Source(db)
    b = Builder(src, seed, unique_customers)
    cases = b.build()
    manifest = {
        "generator": "bankagent.evals.cases", "seed": seed, "policy_version": src.policy.version,
        "as_of": src.as_of.isoformat(), "dev_share_pct": DEV_SHARE, "requested": COUNTS,
        "fairness_groups": len(FAIRNESS), "shortfall": b.shortfall, "policy_cross_check": src.cross_check,
        "n": {s: sum(1 for c in cases if c["split"] == s) for s in ("dev", "test")},
        "provenance": "Casos y etiquetas generados por el equipo por construcción sobre datos sintéticos del "
                      "organizador; no son tráfico real ni anotación humana independiente.",
    }
    return cases, manifest


class FrozenTestError(RuntimeError):
    """El conjunto test está congelado: regenerarlo con otro contenido invalidaría las comparaciones."""


def _serialize(cases: list[dict], split: str) -> bytes:
    return "".join(json.dumps(c, ensure_ascii=False, default=str) + "\n" for c in cases if c["split"] == split).encode()


def write(cases: list[dict], manifest: dict, out: str, force: bool = False) -> None:
    os.makedirs(out, exist_ok=True)
    test_path = os.path.join(out, "test.jsonl")
    new_test = _serialize(cases, "test")
    if os.path.exists(test_path) and not force:
        with open(test_path, "rb") as f:
            if f.read() != new_test:
                raise FrozenTestError(f"{test_path} está congelado y el contenido generado difiere. No se escribió nada. "
                                      "Si de verdad hay que reemplazarlo (invalida la comparación con reportes previos), "
                                      "usar --force y documentarlo en evals/cases/README.md.")
    for split in ("dev", "test"):
        data = new_test if split == "test" else _serialize(cases, split)
        with open(os.path.join(out, f"{split}.jsonl"), "wb") as f:
            f.write(data)
        manifest.setdefault("sha256", {})[f"{split}.jsonl"] = hashlib.sha256(data).hexdigest()
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    ap = argparse.ArgumentParser(description="Genera los casos de evaluación (determinista)")
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "serving.duckdb"))
    ap.add_argument("--out", default=os.path.join(ROOT, "evals", "cases"))
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--force", action="store_true", help="reemplaza un test.jsonl congelado (invalida comparaciones)")
    a = ap.parse_args()
    cases, manifest = build_cases(a.db, a.seed)
    write(cases, manifest, a.out, a.force)
    print(json.dumps({k: manifest[k] for k in ("n", "shortfall", "policy_cross_check")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
