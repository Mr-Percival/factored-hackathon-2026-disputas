"""Replay de quejas históricas + modo sombra (SIMULACIÓN offline, no medición de producción).

    python -m bankagent.evals.replay --db data/serving_full.duckdb --history-db data/bank.duckdb --n 1000 --seed 7

1. Marco: quejas con subcategoría "Cargo no reconocido" o "Cobro indebido". Muestra estratificada por
   país x segmento x case_type (asignación proporcional, restos mayores).
2. Emparejamiento: cada queja -> transacción más plausible (reglas en `matching.py`). Sin match = hallazgo:
   en operación iría a un humano; no se conversa.
3. Conversación: mensaje del cliente simulado (`messages.py`) por un agente NUEVO por caso
   (`build_agent(router="rules", writer="templates")`), login simulado, y un cliente que confirma si le
   muestran SU cargo, elige la opción correcta si le dan varias y, si no aparece, da el detalle exacto una vez.
4. Punto en el tiempo: cada queja se juzga A SU FECHA DE CREACIÓN: `PolicyEngine(as_of=creation_date)` (D05 y
   las fechas relativas "ayer"/"semana pasada"), búsqueda de movimientos acotada a esa fecha e historial de
   reclamos (H04) solo con quejas hasta esa fecha (`PointInTimeTools`).
5. Modo sombra: la decisión de política sobre la transacción emparejada contra el desenlace histórico.

`--history-db` (data/bank.duckdb, tablas raw del EDA) aporta monto reclamado, prioridad, estado, SLA,
compensación y la duración de llamadas "Queja". Sin ella, el replay corre igual y omite esas secciones.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import glob
import json
import os
import random
import subprocess
import time
from collections import Counter

import duckdb

from ..factory import build_agent
from ..graph import DISPUTABLE_TYPES
from ..identity import IdentityService
from ..policy import POLICY, PolicyEngine, _compile
from ..tools import BankTools
from . import stats
from .matching import AMOUNT_TOL, RULES, WINDOW_DAYS, candidate_pool, match_complaint, pool_class
from .messages import CONFIRM, DENY_WRONG, DIALECTS, lang_of, render_detail, render_opening, render_option

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SUBCATEGORIES = ("Cargo no reconocido", "Cobro indebido")
STRATA = ("country", "segment", "case_type")
TERMINAL = {"resolved", "rejected", "informed", "handoff", "blocked", "auth_error"}
MAX_TURNS = 6
CLAIM_CONTROL_K = 20
WINDOWS = (7, 15, 30, 60)
HIST_GROUP = {"Resolved": "resuelta", "Closed": "resuelta", "Rejected": "rechazada", "Escalated": "escalada",
              "Open": "abierta", "In Process": "abierta"}


# ---------------------------------------------------------------- herramientas "a la fecha de la queja"
class PointInTimeTools(BankTools):
    """BankTools que ve el mundo como era en `as_of` (la creación de la queja). Solo para el replay:
    - search_transactions no devuelve movimientos posteriores a `as_of`;
    - dispute_history calcula H04 con las quejas del cliente hasta `as_of` (en producción usa todas)."""

    as_of: dt.datetime | None = None

    def search_transactions(self, token, date_from=None, date_to=None, amount_min=None, amount_max=None,
                            merchant=None, country=None, limit=10):
        if self.as_of is None:
            return super().search_transactions(token, date_from, date_to, amount_min, amount_max, merchant, country, limit)
        cap = self.as_of.date()
        date_to = min(date_to, cap) if date_to else cap
        # se piden de más porque el día de la queja puede tener movimientos posteriores a la hora de creación
        rows = super().search_transactions(token, date_from, date_to, amount_min, amount_max, merchant, country, limit + 10)
        return [r for r in rows if r["transaction_date"] <= self.as_of][:limit]

    def dispute_history(self, token):
        if self.as_of is None:
            return super().dispute_history(token)

        def fn():
            cid = self.identity.resolve(token).customer_id
            return self.history_as_of(cid, self.as_of)
        return self._run("dispute_history", {}, fn)

    def history_as_of(self, customer_id: str, as_of: dt.datetime) -> dict:
        r = self._ro_c.execute("""SELECT count(*) FILTER (WHERE creation_date >= ?::TIMESTAMP - INTERVAL 90 DAY AND creation_date < ?),
                coalesce(bool_or(is_repeat_complainer) FILTER (WHERE creation_date <= ?), false)
                FROM complaints WHERE customer_id = ?""", [as_of, as_of, as_of, customer_id]).fetchone()
        open_disputes = [x[0] for x in self._ops_c.execute("SELECT transaction_id FROM disputes WHERE customer_id = ?", [customer_id]).fetchall()]
        return {"complaints_last_90d": r[0] or 0, "is_repeat_complainer": bool(r[1]), "open_dispute_transactions": open_disputes}

    def reset_ops(self) -> None:
        """Cada caso empieza sin disputas ni bloqueos de casos anteriores (casos independientes)."""
        self._ops_c.execute("DELETE FROM disputes")
        self._ops_c.execute("DELETE FROM card_blocks")


# ---------------------------------------------------------------- marco y muestra
def load_frame(con) -> list[dict]:
    cur = con.execute(f"""SELECT k.complaint_id, k.creation_date, k.customer_id, k.case_type, k.subcategory,
            k.affected_product_id, k.status, k.is_repeat_complainer, c.country, c.segment, c.customer_status
        FROM complaints k JOIN customers c USING (customer_id)
        WHERE k.subcategory IN {SUBCATEGORIES} ORDER BY k.complaint_id""")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def stratified_sample(frame: list[dict], n: int, seed: int, keys: tuple[str, ...] = STRATA) -> list[dict]:
    """Asignación proporcional por estrato con restos mayores (suma exacta n); dentro del estrato, al azar."""
    if n >= len(frame):
        return list(frame)
    strata: dict[tuple, list[dict]] = {}
    for r in frame:
        strata.setdefault(tuple(r[k] for k in keys), []).append(r)
    total = len(frame)
    quota = {s: n * len(rows) / total for s, rows in strata.items()}
    alloc = {s: int(q) for s, q in quota.items()}
    rest = n - sum(alloc.values())
    for s in sorted(quota, key=lambda s: (-(quota[s] - alloc[s]), str(s)))[:rest]:
        alloc[s] += 1
    rng = random.Random(seed)
    out = []
    for s in sorted(strata, key=str):
        rows = sorted(strata[s], key=lambda r: r["complaint_id"])
        out.extend(rng.sample(rows, alloc[s]))
    return sorted(out, key=lambda r: (r["creation_date"], r["complaint_id"]))


def load_history(history_db: str | None, ids: list[str]) -> dict[str, dict]:
    if not history_db or not os.path.exists(history_db):
        return {}
    con = duckdb.connect(history_db, read_only=True)
    try:
        cur = con.execute("""SELECT complaint_id, TRY_CAST(claimed_amount AS DOUBLE) claimed_amount, currency, priority,
                status hist_status, reception_channel, sla_breached = 'True' sla_breached,
                TRY_CAST(resolution_days AS DOUBLE) resolution_days,
                TRY_CAST(compensation_granted AS DOUBLE) compensation_granted,
                date_diff('minute', TRY_CAST(creation_date AS TIMESTAMP), TRY_CAST(first_response_date AS TIMESTAMP)) / 60.0 first_response_h
            FROM raw_complaints WHERE complaint_id IN (SELECT unnest(?))""", [ids])
        cols = [d[0] for d in cur.description]
        return {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}
    finally:
        con.close()


def call_center_aht(history_db: str | None) -> dict | None:
    if not history_db or not os.path.exists(history_db):
        return None
    con = duckdb.connect(history_db, read_only=True)
    try:
        r = con.execute("""SELECT count(*), quantile_cont(TRY_CAST(duration_seconds AS DOUBLE), [0.25, 0.5, 0.75]),
                avg((requires_followup = 'True')::INT), avg((was_resolved = 'True')::INT)
            FROM raw_call_center_interactions WHERE reason_category = 'Queja'""").fetchone()
        return {"n": r[0], "p25": r[1][0], "p50": r[1][1], "p75": r[1][2], "followup": r[2], "fcr": r[3]}
    finally:
        con.close()


def frame_stats(con, frame: list[dict]) -> dict:
    """Números del marco completo (no de la muestra): cobertura por ventana y calidad de los campos de enlace."""
    by = {k: Counter(r[k] for r in frame) for k in ("country", "segment", "case_type", "subcategory")}
    with_product = [r for r in frame if r["affected_product_id"]]
    own = con.execute(f"""SELECT count(*) FROM complaints k JOIN products p ON p.product_id = k.affected_product_id
        WHERE k.subcategory IN {SUBCATEGORIES} AND p.customer_id = k.customer_id""").fetchone()[0]
    types = tuple(sorted(DISPUTABLE_TYPES))
    filt = ", ".join(f"count(*) FILTER (WHERE gap <= {w}) n{w}" for w in WINDOWS)
    rows = con.execute(f"""WITH k AS (SELECT complaint_id, customer_id, creation_date FROM complaints WHERE subcategory IN {SUBCATEGORIES}),
        j AS (SELECT k.complaint_id, date_diff('second', t.transaction_date, k.creation_date) / 86400.0 gap
              FROM k JOIN transactions t ON t.customer_id = k.customer_id AND t.transaction_date <= k.creation_date
                   AND t.transaction_date >= k.creation_date - INTERVAL {max(WINDOWS)} DAY
              WHERE t.transaction_type IN {types})
        SELECT {", ".join(f"n{w}" for w in WINDOWS)} FROM k LEFT JOIN (SELECT complaint_id, {filt} FROM j GROUP BY 1) USING (complaint_id)""").fetchall()
    windows = {}
    for i, w in enumerate(WINDOWS):
        c = Counter(pool_class(r[i] or 0) for r in rows)
        windows[w] = {cls: c.get(cls, 0) for cls in ("0", "1", "2-5", ">5")}
    no_txn = con.execute(f"""SELECT count(*) FROM complaints k WHERE subcategory IN {SUBCATEGORIES}
        AND NOT EXISTS (SELECT 1 FROM transactions t WHERE t.customer_id = k.customer_id)""").fetchone()[0]
    dates = con.execute(f"SELECT min(creation_date), max(creation_date) FROM complaints WHERE subcategory IN {SUBCATEGORIES}").fetchone()
    last_year = con.execute(f"""SELECT count(*) FROM complaints WHERE subcategory IN {SUBCATEGORIES}
        AND creation_date > (SELECT max(creation_date) FROM complaints) - INTERVAL 365 DAY""").fetchone()[0]
    return {"n": len(frame), "by": {k: dict(v.most_common()) for k, v in by.items()},
            "with_product": len(with_product), "product_owned": own, "customers_without_txn": no_txn,
            "windows": windows, "date_min": str(dates[0]), "date_max": str(dates[1]), "last_365d": last_year}


# ---------------------------------------------------------------- simulación de una conversación
def customer_txns(tools: BankTools, customer_id: str, created: dt.datetime, window_days: int) -> list[dict]:
    return tools._rows("""WITH own AS MATERIALIZED (SELECT * FROM transactions WHERE customer_id = ?)
        SELECT * FROM own WHERE transaction_date <= ? AND transaction_date >= ?::TIMESTAMP - INTERVAL (?) DAY""",
                       [customer_id, created, created, window_days])


def simulate(agent, token: str, thread: str, case: dict, dialect: str, rng: random.Random) -> dict:
    """Conduce la conversación con el cliente simulado. Devuelve la clase final y la telemetría."""
    target = case["txn"]["transaction_id"]
    msg, meta = render_opening(case, dialect, rng)
    detail_sent, turn_ms, clarify, asked_confirmation, stop = False, [], 0, False, None
    last: dict = {}
    transcript: list[dict] = []  # solo va al detalle por caso (data/), nunca al reporte
    for _ in range(MAX_TURNS):
        t0 = time.perf_counter()
        last = agent.chat(thread, token, msg)
        turn_ms.append((time.perf_counter() - t0) * 1000)
        u = last.get("understanding") or {}
        transcript.append({"user": msg, "outcome": last.get("outcome"), "awaiting": last.get("awaiting"),
                           "intent": u.get("intent"), "confidence": u.get("confidence"),
                           "n_candidates": len(last.get("candidates") or []), "reply": last.get("reply")})
        if last.get("outcome") in TERMINAL:
            break
        awaiting = last.get("awaiting")
        if awaiting == "confirmation":
            asked_confirmation = True
            pending = (last.get("pending_action") or {}).get("transaction_id")
            msg = CONFIRM[dialect] if pending == target else DENY_WRONG[dialect]
            continue
        clarify += 1  # pidió datos u opciones (o canceló tras un "no, ese no es")
        if awaiting == "option":
            ids = [c.get("transaction_id") for c in last.get("candidates") or []]
            if target in ids:
                msg = render_option(ids.index(target) + 1, dialect)
                continue
        if detail_sent:
            stop = "not_identified"
            break
        msg, detail_sent = render_detail(case, dialect, rng), True
    else:
        stop = "not_identified"  # tope de turnos

    outcome = last.get("outcome")
    txn_id = (last.get("txn") or {}).get("transaction_id")
    rules = (last.get("decision") or {}).get("rules") or []
    rule = rules[0]["id"] if rules else None
    ar = last.get("action_result") or {}
    verified = bool(ar.get("dispute") and ar["dispute"]["verified"] and (ar.get("block") is None or ar["block"]["verified"]))
    fail = None
    if stop:
        final = "not_identified"
        t = transcript[-1]
        if t["intent"] == "unknown" or (t["confidence"] or 0) < agent.min_confidence:
            fail = "router_sin_confianza"  # el router no reconoció el pedido (el agente respondió "¿qué cargo?")
        elif t["outcome"] == "cancelled":
            fail = "propuso_otro_cargo"
        elif t["awaiting"] == "option":
            fail = "no_esta_entre_opciones"
        else:
            fail = "busqueda_sin_resultados"
    elif outcome in ("resolved", "rejected", "informed", "handoff") and txn_id and txn_id != target:
        final = "wrong_txn"
    elif outcome == "resolved":
        final = "auto_resolved" if verified and asked_confirmation else "other:resolved_unverified"
    elif outcome in ("rejected", "informed"):
        final = f"{outcome}:{rule}"
    elif outcome == "handoff":
        final = f"handoff:{(last.get('handoff') or {}).get('reason')}"
    else:
        final = f"other:{outcome}"
    return {"final_class": final, "turns": len(turn_ms), "clarify_turns": clarify, "turn_ms": turn_ms,
            "confirmation_asked": asked_confirmation, "verified": verified, "agent_rule": rule,
            "dispute_opened": bool(ar.get("dispute")), "card_blocked": bool(ar.get("block")), "transcript": transcript,
            "fail_reason": fail, **meta}


# ---------------------------------------------------------------- variantes de política (sensibilidad)
def policy_variant(fraud_threshold: float | None = None, high_scale: float = 1.0, path: str = POLICY) -> PolicyEngine:
    """Copia de la política con otro umbral de H03 y/o H02 escalado. Solo para el análisis de sensibilidad."""
    e = PolicyEngine(path)
    cfg = copy.deepcopy(e.cfg)
    cfg["dispute"]["high_amount"] = {k: v * high_scale for k, v in cfg["dispute"]["high_amount"].items()}
    for r in cfg["dispute"]["rules"]:
        if r["id"].startswith("H03") and fraud_threshold is not None:
            r["when"] = f"txn.fraud_score is not None and txn.fraud_score >= {fraud_threshold}"
    e.cfg, e.rules = cfg, [(r, _compile(r["when"])) for r in cfg["dispute"]["rules"]]
    return e


def direct_decision(engine: PolicyEngine, as_of: dt.datetime, txn: dict, customer: dict, history: dict):
    engine.as_of = as_of.date()
    return engine.decide_dispute(txn, customer, history)


# ---------------------------------------------------------------- orquestación
def run(db: str, n: int, seed: int, history_db: str | None = None, pt_share: float = 0.2,
        window_days: int = WINDOW_DAYS, out_md: str | None = None, out_json: str | None = None,
        cases_jsonl: str | None = None, frame: list[dict] | None = None) -> dict:
    t_start = time.perf_counter()
    tools = PointInTimeTools(db, IdentityService(ttl_seconds=3600))
    con = tools._ro_c
    frame = frame if frame is not None else load_frame(con)
    fstats = frame_stats(con, frame)
    sample = stratified_sample(frame, n, seed)
    hist = load_history(history_db, [r["complaint_id"] for r in sample])
    rng = random.Random(seed)
    base_policy = PolicyEngine()
    sens = {(thr, sc): policy_variant(thr, sc) for thr in (20, 30, 40, 50) for sc in (0.5, 1.0, 2.0)}

    results, pt_results, claim_pairs = [], [], []
    claims = sorted((h for h in hist.values() if h.get("claimed_amount") is not None), key=lambda h: h["complaint_id"])
    claim_rng = random.Random(seed + 1)
    for c in sample:
        h = hist.get(c["complaint_id"], {})
        complaint = {**c, "claimed_amount": h.get("claimed_amount"), "currency": h.get("currency")}
        created = c["creation_date"]
        txns = customer_txns(tools, c["customer_id"], created, max(window_days, max(WINDOWS)))
        m = match_complaint(complaint, txns, window_days)
        pools = {w: len([t for t in txns if t["transaction_type"] in DISPUTABLE_TYPES
                         and t["transaction_date"] >= created - dt.timedelta(days=w)]) for w in WINDOWS}
        base = {"case_id": c["complaint_id"], "country": c["country"], "segment": c["segment"], "case_type": c["case_type"],
                "subcategory": c["subcategory"], "customer_status": c["customer_status"], "match_rule": m.rule,
                "pool_size": m.pool_size, "pool_class": pool_class(m.pool_size), "pools": pools, "match_notes": m.notes,
                "creation_date": created.isoformat(), **{k: h.get(k) for k in (
                    "priority", "hist_status", "sla_breached", "resolution_days", "compensation_granted",
                    "first_response_h", "claimed_amount", "currency", "reception_channel")}}
        base["hist_group"] = HIST_GROUP.get(h.get("hist_status")) if h else None
        # ¿el monto reclamado informa? R1 con su monto vs con montos de OTRAS quejas al azar (control, K sorteos)
        if complaint["claimed_amount"] is not None:
            ctrl = sum(match_complaint({**complaint, "claimed_amount": o["claimed_amount"], "currency": o["currency"]},
                                       txns, window_days).rule == "R1_amount"
                       for o in claim_rng.sample(claims, min(CLAIM_CONTROL_K, len(claims))))
            claim_pairs.append((m.rule == "R1_amount", ctrl / min(CLAIM_CONTROL_K, len(claims))))
        if m.txn is None:
            results.append({**base, "lang": "es", "dialect": DIALECTS[c["country"]], "final_class": "unmatched",
                            "final_group": "unmatched", "turns": 0, "clarify_turns": 0, "turn_ms": [], "safe": False})
            continue

        customer = {"customer_id": c["customer_id"], "customer_status": c["customer_status"], "segment": c["segment"],
                    "country": c["country"]}
        hist_pit = tools.history_as_of(c["customer_id"], created)
        hist_pit["open_dispute_transactions"] = []
        d = direct_decision(base_policy, created, m.txn, customer, hist_pit)
        tools.as_of = None
        h04_prod = BankTools.dispute_history(tools, tools.identity.login(c["customer_id"]))["is_repeat_complainer"]
        # sensibilidad de la regla: "la más reciente de cualquier estado" (sin preferir Approved)
        alt = candidate_pool(complaint, txns, window_days)[0]
        d_alt = direct_decision(base_policy, created, alt, customer, hist_pit)
        base.update({"direct_outcome_alt": d_alt.outcome, "direct_rule_alt": d_alt.deciding_rule.id if d_alt.deciding_rule else None,
                     "alt_same_txn": alt["transaction_id"] == m.txn["transaction_id"]})
        base.update({"direct_outcome": d.outcome, "direct_rule": d.deciding_rule.id if d.deciding_rule else None,
                     "direct_hits": [x.id for x in d.hits], "h04_pit": hist_pit["is_repeat_complainer"], "h04_prod": h04_prod,
                     "txn_status": m.txn["transaction_status"], "txn_type": m.txn["transaction_type"],
                     "txn_age_days": (created.date() - m.txn["transaction_date"].date()).days,
                     "sensitivity": {f"{thr}|{sc}": direct_decision(e, created, m.txn, customer, hist_pit).outcome
                                     for (thr, sc), e in sens.items()}})
        case = {"subcategory": c["subcategory"], "creation_date": created, "customer_country": c["country"], "txn": m.txn}
        variants = [DIALECTS[c["country"]]] + (["pt-BR"] if rng.random() < pt_share else [])
        for dialect in variants:
            tools.reset_ops()
            tools.as_of = created
            agent = build_agent(tools, router="rules", writer="templates", policy=PolicyEngine(as_of=created))
            token = tools.identity.login(c["customer_id"])
            sim = simulate(agent, token, f"{c['complaint_id']}:{dialect}", case, dialect, rng)
            sim["final_group"] = stats.group_of(sim["final_class"])
            # segura = abrió y verificó la disputa sobre el cargo correcto, con confirmación, y la política
            # evaluada por separado sobre ese cargo también dice que era automatizable
            sim["safe"] = sim["final_class"] == "auto_resolved" and d.outcome == "auto_with_confirmation"
            row = {**base, "lang": lang_of(dialect), **sim}
            (results if dialect != "pt-BR" else pt_results).append(row)
        tools.as_of = None

    summary = {"meta": _meta(db, n, seed, history_db, pt_share, window_days, time.perf_counter() - t_start),
               "frame": fstats, "sample_n": len(sample),
               "aht": call_center_aht(history_db), "claim_control": claim_pairs}
    summary.update(analyze(results, pt_results, fstats, summary["aht"], claim_pairs))
    if cases_jsonl:
        os.makedirs(os.path.dirname(os.path.abspath(cases_jsonl)), exist_ok=True)
        with open(cases_jsonl, "w", encoding="utf-8") as f:
            for r in results + pt_results:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    if out_json:
        with open(out_json, "w", encoding="utf-8", newline="\n") as f:
            json.dump({k: v for k, v in summary.items() if k not in ("claim_control",)}, f, indent=2,
                      ensure_ascii=False, default=str)
    if out_md:
        from .report import render_markdown
        with open(out_md, "w", encoding="utf-8", newline="\n") as f:
            f.write(render_markdown(summary))
    summary["results"], summary["pt_results"] = results, pt_results
    return summary


def analyze(results: list[dict], pt_results: list[dict], fstats: dict, aht: dict | None, claim_pairs: list) -> dict:
    matched = [r for r in results if r["final_group"] != "unmatched"]
    out = {"metrics": stats.aggregate(results),
           "coverage": {rule: stats.rate(sum(1 for r in results if r["match_rule"] == rule), len(results)) for rule in RULES},
           "pool_classes": dict(Counter(r["pool_class"] for r in results)),
           "breakdowns": {k: stats.breakdown(results, k) for k in ("country", "segment", "case_type", "subcategory",
                                                                   "match_rule", "pool_class", "style")},
           "pt": _paired(results, pt_results),
           "direct": {"outcomes": dict(Counter(r["direct_outcome"] for r in matched)),
                      "rules": dict(Counter(r["direct_rule"] or "ninguna (automatizable)" for r in matched)),
                      "hits": dict(Counter(h for r in matched for h in r["direct_hits"])),
                      "txn_status": dict(Counter(r["txn_status"] for r in matched)),
                      "h04_diff": sum(1 for r in matched if r["h04_pit"] != r["h04_prod"]),
                      "h04_prod_only": sum(1 for r in matched if r["h04_prod"] and not r["h04_pit"]),
                      "age_max": max((r["txn_age_days"] for r in matched), default=None),
                      "alt_rules": dict(Counter(r["direct_rule_alt"] or "ninguna (automatizable)" for r in matched)),
                      "alt_outcomes": dict(Counter(r["direct_outcome_alt"] for r in matched)),
                      "alt_same_txn": sum(1 for r in matched if r["alt_same_txn"])},
           "sensitivity": _sensitivity(matched),
           "not_identified_reasons": dict(Counter(r["fail_reason"] for r in results + pt_results if r.get("fail_reason"))),
           "not_identified_reasons_by_lang": {lang: dict(Counter(r["fail_reason"] for r in rs if r.get("fail_reason")))
                                              for lang, rs in (("es", results), ("pt", pt_results))},
           "claim": {"n": len(claim_pairs), "own": sum(a for a, _ in claim_pairs), "control": sum(b for _, b in claim_pairs),
                     "control_k": CLAIM_CONTROL_K}}
    hist = [r for r in results if r.get("hist_status")]
    if hist:
        out["historical"] = _historical(results)
        out["shadow"] = _shadow(matched)
    if aht:
        out["projection"] = _projection(out["metrics"], fstats, aht)
    return out


def _paired(es: list[dict], pt: list[dict]) -> dict:
    by_id = {r["case_id"]: r for r in es}
    pairs = [(by_id[r["case_id"]], r) for r in pt if r["case_id"] in by_id]
    same_group = sum(1 for a, b in pairs if a["final_group"] == b["final_group"])
    same_class = sum(1 for a, b in pairs if a["final_class"] == b["final_class"])
    return {"n": len(pairs), "same_group": stats.rate(same_group, len(pairs)), "same_class": stats.rate(same_class, len(pairs)),
            "metrics_pt": stats.aggregate(pt) if pt else None,
            "metrics_es_same_cases": stats.aggregate([a for a, _ in pairs]) if pairs else None,
            "diffs": dict(Counter(f"{a['final_class']} -> {b['final_class']}" for a, b in pairs if a["final_class"] != b["final_class"]))}


def _sensitivity(matched: list[dict]) -> list[dict]:
    rows = []
    for key in (matched[0]["sensitivity"] if matched else {}):
        thr, sc = key.split("|")
        c = Counter(r["sensitivity"][key] for r in matched)
        rows.append({"fraud_threshold": float(thr), "high_scale": float(sc), "n": len(matched),
                     "handoff": c.get("handoff", 0), "auto": c.get("auto_with_confirmation", 0),
                     "reject": c.get("reject", 0) + c.get("inform", 0)})
    return rows


def _historical(results: list[dict]) -> dict:
    def summary(rows):
        rd = [r["resolution_days"] for r in rows if r.get("resolution_days") is not None]
        fr = [r["first_response_h"] for r in rows if r.get("first_response_h") is not None]
        comp = [r["compensation_granted"] for r in rows if r.get("compensation_granted") is not None]
        return {"n": len(rows), "status": dict(Counter(r["hist_status"] for r in rows).most_common()),
                "sla": stats.rate(sum(1 for r in rows if r.get("sla_breached")), len(rows)),
                "resolution_days": {"n": len(rd), "p50": stats.quantile(rd, .5), "p75": stats.quantile(rd, .75)},
                "first_response_h": {"n": len(fr), "p50": stats.quantile(fr, .5), "p75": stats.quantile(fr, .75)},
                "compensation": stats.rate(len(comp), len(rows)),
                "compensation_p50": stats.quantile(comp, .5)}
    rows = [r for r in results if r.get("hist_status")]
    return {"all": summary(rows), "by_group": {g: summary([r for r in rows if r["final_group"] == g])
                                               for g in sorted({r["final_group"] for r in rows})}}


def _shadow(matched: list[dict]) -> dict:
    rows = [r for r in matched if r.get("hist_status")]
    ours = [{"auto_with_confirmation": "auto", "handoff": "handoff", "reject": "rechazo", "inform": "informa"}[r["direct_outcome"]]
            for r in rows]
    theirs = [r["hist_group"] for r in rows]
    ra, cb, m = stats.crosstab(ours, theirs)
    v = stats.cramers_v(ours, theirs)
    out = {"n": len(rows), "matrix": {"rows": ra, "cols": cb, "m": m}, "cramers_v": v,
           "cramers_p": stats.permutation_p(stats.cramers_v, ours, theirs)}

    def kap(a, b):
        return stats.kappa(a, b)["kappa"]

    pairs = {
        "handoff_vs_escalada_o_prioridad_alta": ([r["direct_outcome"] == "handoff" for r in rows],
                                                 [r["hist_status"] == "Escalated" or r.get("priority") in ("High", "Critical") for r in rows]),
        "auto_vs_resuelta": ([r["direct_outcome"] == "auto_with_confirmation" for r in rows],
                             [r["hist_group"] == "resuelta" for r in rows]),
        "rechazo_vs_rechazada": ([r["direct_outcome"] in ("reject", "inform") for r in rows],
                                 [r["hist_status"] == "Rejected" for r in rows]),
        "H02_vs_compensacion": (["H02_high_amount" in r["direct_hits"] for r in rows],
                                [r.get("compensation_granted") is not None for r in rows]),
        "H03_vs_prioridad_critica": (["H03_fraud_signal" in r["direct_hits"] for r in rows],
                                     [r.get("priority") == "Critical" for r in rows]),
    }
    out["binary"] = {name: {**stats.kappa(a, b), "perm_p": stats.permutation_p(kap, a, b)} for name, (a, b) in pairs.items()}
    return out


def _projection(metrics: dict, fstats: dict, aht: dict) -> dict:
    s = metrics["safe_auto_of_all"]
    vol = fstats["last_365d"]
    lo = vol * s["lo"] * aht["p25"] / 3600
    hi = vol * s["hi"] * aht["p75"] * (1 + aht["followup"]) / 3600
    mid = vol * s["p"] * aht["p50"] / 3600
    return {"volume_365d": vol, "share": s, "aht": aht, "hours_low": lo, "hours_mid": mid, "hours_high": hi}


def _meta(db, n, seed, history_db, pt_share, window_days, elapsed) -> dict:
    def git(*a):
        try:
            return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:  # noqa: BLE001 (sin git el replay igual corre)
            return None
    manifest = latest_manifest(db)
    return {"generated_at": dt.datetime.now().isoformat(timespec="seconds"), "db": os.path.basename(db),
            "history_db": os.path.basename(history_db) if history_db else None, "n": n, "seed": seed,
            "pt_share": pt_share, "window_days": window_days, "amount_tol": AMOUNT_TOL, "max_turns": MAX_TURNS,
            "git_sha": git("rev-parse", "--short", "HEAD"), "git_dirty": bool(git("status", "--porcelain", "--", "src", "config")),
            "policy_version": PolicyEngine().version, "policy_as_of_yaml": str(PolicyEngine().as_of),
            "manifest_run": manifest.get("run_id") if manifest else None,
            "fingerprint": {t: s.get("source_fingerprint") for t, s in (manifest or {}).get("tables", {}).items()},
            "elapsed_s": round(elapsed, 1),
            "command": f"python -m bankagent.evals.replay --db {os.path.basename(db)} --n {n} --seed {seed}"
                       + (f" --history-db {os.path.basename(history_db)}" if history_db else "")}


def latest_manifest(db: str) -> dict | None:
    """Última corrida del pipeline sobre esta base que registró la huella de la entrega."""
    runs = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(db)), "runs", "*.json")), reverse=True)
    for p in runs:
        with open(p, encoding="utf-8") as f:
            m = json.load(f)
        same = os.path.normcase(os.path.abspath(m.get("out_db", ""))) == os.path.normcase(os.path.abspath(db))
        if same and all("source_fingerprint" in s for s in m.get("tables", {}).values()):
            return m
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "serving.duckdb"))
    ap.add_argument("--history-db", default=None, help="data/bank.duckdb (tablas raw_*): monto reclamado y desenlace histórico")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--pt-share", type=float, default=0.2, help="fracción de casos emparejados que también se corre en pt-BR")
    ap.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    ap.add_argument("--out", default=os.path.join(ROOT, "reports", "replay.md"))
    ap.add_argument("--json", default=os.path.join(ROOT, "reports", "replay_results.json"))
    ap.add_argument("--cases", default=os.path.join(ROOT, "data", "replay", "cases.jsonl"),
                    help="detalle por caso (tiene IDs del dataset: queda en data/, fuera del repo)")
    a = ap.parse_args()
    s = run(a.db, a.n, a.seed, a.history_db, a.pt_share, a.window_days, a.out, a.json, a.cases)
    m = s["metrics"]
    print(f"n={m['n']} intentados={m['attempted']['p']:.1%} auto seguro={m['safe_auto_of_all']['p']:.1%} "
          f"handoff={m['groups']['handoff']['p']:.1%} sin match={m['groups']['unmatched']['p']:.1%} "
          f"-> {a.out} ({s['meta']['elapsed_s']} s)")


if __name__ == "__main__":
    main()
