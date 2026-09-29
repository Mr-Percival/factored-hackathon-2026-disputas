"""Replay de quejas (#30): as_of de la política, regla de emparejamiento, mensajes, agregación y corrida sobre el fixture."""
import datetime as dt
import random

import pytest

from bankagent.evals import stats
from bankagent.evals.matching import candidate_pool, match_complaint, pool_class
from bankagent.evals.messages import (DIALECTS, fmt_amount, lang_of, render_detail, render_opening, render_option)
from bankagent.evals.replay import PointInTimeTools, run, simulate, stratified_sample
from bankagent.factory import build_agent
from bankagent.identity import IdentityService
from bankagent.policy import PolicyEngine
from bankagent.understanding import RuleRouter

ACTIVE = {"customer_status": "Active"}
CLEAN = {"is_repeat_complainer": False, "open_dispute_transactions": []}


# ---------------------------------------------------------------- política a la fecha de la queja
def test_policy_as_of_override_moves_the_age_limit():
    txn = {"transaction_id": "T1", "transaction_date": dt.datetime(2024, 3, 1), "transaction_status": "Approved",
           "amount": 10, "currency": "USD", "fraud_score": 1}
    assert PolicyEngine().decide_dispute(txn, ACTIVE, CLEAN).deciding_rule.id == "D05_too_old"  # as_of del YAML
    for as_of in (dt.date(2024, 3, 20), dt.datetime(2024, 3, 20, 18, 30), "2024-03-20"):
        e = PolicyEngine(as_of=as_of)
        assert e.as_of == dt.date(2024, 3, 20)
        assert e.decide_dispute(txn, ACTIVE, CLEAN).outcome == "auto_with_confirmation"
    assert PolicyEngine().as_of == dt.date(2026, 6, 17)  # sin override no cambia nada


# ---------------------------------------------------------------- regla de emparejamiento
def _t(tid, day, amount=100.0, typ="Purchase", status="Approved", cur="USD", cust="C1", hour=12):
    return {"transaction_id": tid, "transaction_date": dt.datetime(2025, 1, day, hour), "amount": amount,
            "transaction_type": typ, "transaction_status": status, "currency": cur, "customer_id": cust}


def _c(sub="Cargo no reconocido", claimed=None, cur=None, day=20):
    return {"customer_id": "C1", "creation_date": dt.datetime(2025, 1, day, 15), "subcategory": sub,
            "claimed_amount": claimed, "currency": cur}


def test_pool_excludes_other_customers_deposits_future_and_old():
    txns = [_t("ok", 10), _t("other", 11, cust="C2"), _t("dep", 12, typ="Deposit"), _t("later", 20, hour=16),
            _t("same_day_before", 20, hour=9)]
    assert [t["transaction_id"] for t in candidate_pool(_c(), txns)] == ["same_day_before", "ok"]
    assert candidate_pool(_c(), txns, window_days=5) == [txns[4]]


def test_r1_amount_needs_same_currency_and_tolerance():
    txns = [_t("near", 5, amount=505), _t("recent", 18, amount=900), _t("cop", 19, amount=500, cur="COP")]
    assert match_complaint(_c(claimed=500, cur="USD"), txns).txn["transaction_id"] == "near"
    m = match_complaint(_c(claimed=500, cur="ARS"), txns)  # ninguna en ARS: cae a R2 y lo anota
    assert m.rule == "R2_type_approved" and "claimed_currency_mismatch" in m.notes
    assert match_complaint(_c(claimed=700, cur="USD"), txns).rule == "R2_type_approved"  # 505 y 900 fuera de ±10%


def test_fallback_order_r2_r3_r4_and_unmatched():
    txns = [_t("adj", 15, typ="Adjustment"), _t("pur", 10), _t("tr", 18, typ="Transfer"),
            _t("declined", 19, status="Declined")]
    assert match_complaint(_c("Cobro indebido"), txns).txn["transaction_id"] == "adj"      # tipo esperado del cobro
    assert match_complaint(_c("Cargo no reconocido"), txns).txn["transaction_id"] == "pur"  # Purchase aunque haya más recientes
    m = match_complaint(_c(), [_t("tr", 18, typ="Transfer"), _t("declined", 19, status="Declined")])
    assert (m.rule, m.txn["transaction_id"], m.pool_size) == ("R3_any_approved", "tr", 2)
    m = match_complaint(_c(), [_t("declined", 19, status="Declined")])
    assert m.rule == "R4_any_status"
    assert match_complaint(_c(), [_t("old", 1)], window_days=10).rule == "unmatched"
    assert [pool_class(k) for k in (0, 1, 3, 9)] == ["0", "1", "2-5", ">5"]


# ---------------------------------------------------------------- mensajes del cliente simulado
@pytest.mark.parametrize("country", sorted(DIALECTS))
@pytest.mark.parametrize("pt", [False, True])
def test_messages_are_understood_by_the_router_and_carry_no_ids(country, pt):
    dialect = "pt-BR" if pt else DIALECTS[country]
    router, rng = RuleRouter(), random.Random(3)
    txn = {"transaction_id": "TXN-SECRET-1", "amount": 1250.37, "currency": "USD", "merchant_name": "Uber",
           "transaction_date": dt.datetime(2025, 1, 12, 10), "transaction_country": "Brazil"}
    case = {"subcategory": "Cargo no reconocido", "creation_date": dt.datetime(2025, 1, 20, 9), "customer_country": country,
            "txn": txn}
    for style in ("amount_date", "amount_only", "date_only"):
        text, meta = render_opening(case, dialect, rng, style)
        u = router.understand(text, dt.date(2025, 1, 20), None)
        assert "TXN" not in text and "CLI-" not in text
        assert (u.intent, u.language, u.slots.country) == ("dispute_charge", lang_of(dialect), "Brazil")
        if style != "date_only":
            assert abs(u.slots.amount - 1250.37) <= 0.06 * 1250.37
        if style != "amount_only":
            assert u.slots.date_from <= dt.date(2025, 1, 12) <= u.slots.date_to  # "la semana pasada" o fecha explícita
    detail = render_detail(case, dialect, rng)
    u = router.understand(detail, dt.date(2025, 1, 20), "option")  # detalle largo: no se confunde con "la opción 1"
    assert u.intent == "dispute_charge" and u.slots.amount == pytest.approx(1250.37) and u.slots.date_from == dt.date(2025, 1, 12)
    assert router.understand(render_option(2, dialect), dt.date(2025, 1, 20), "option").slots.option == 2


def test_amount_formats_follow_local_convention():
    assert fmt_amount(1250.5, "USD", "es-MX") == "$1,250.50"
    assert fmt_amount(1250000, "COP", "es-CO") == "$1.250.000"
    assert fmt_amount(88306.28, "ARS", "es-AR") == "$88.306,28"
    assert fmt_amount(1250.5, "USD", "pt-BR") == "US$ 1.250,50"
    assert fmt_amount(1249.0, "USD", "es-AR", approx=True) == "US$1.200"
    voseo = render_opening({"subcategory": "Cargo no reconocido", "creation_date": dt.datetime(2025, 1, 20),
                            "customer_country": "Argentina", "txn": {"amount": 10, "currency": "ARS", "transaction_country": "Argentina",
                                                                     "transaction_date": dt.datetime(2025, 1, 19)}},
                           "es-AR", random.Random(0))[0]
    assert "podés" in voseo or "Fijate" in voseo or "fijate" in voseo


# ---------------------------------------------------------------- agregación y acuerdo
def _r(cls, turns=2, ms=(10.0, 20.0), safe=None, **kw):
    return {"final_class": cls, "final_group": stats.group_of(cls), "turns": turns, "clarify_turns": 1 if turns > 2 else 0,
            "turn_ms": list(ms), "safe": cls == "auto_resolved" if safe is None else safe, **kw}


def test_aggregate_counts_rates_and_latency():
    rs = [_r("auto_resolved", country="MX"), _r("auto_resolved", turns=3, ms=(10, 20, 30), country="MX"),
          _r("handoff:H02_high_amount", country="CO"), _r("rejected:D02_declined_not_charged", country="CO"),
          _r("unmatched", turns=0, ms=(), safe=False, country="AR")]
    m = stats.aggregate(rs)
    assert m["n"] == 5 and m["attempted"]["k"] == 4 and m["safe_auto_of_all"]["k"] == 2
    assert m["safe_auto_of_attempted"]["p"] == 0.5
    assert m["handoff_by_rule"]["H02_high_amount"]["k"] == 1 and m["reject_by_rule"]["D02_declined_not_charged"]["k"] == 1
    assert m["groups"]["unmatched"]["k"] == 1 and m["groups"]["not_identified"]["k"] == 0 and m["unsafe"]["k"] == 0
    assert m["latency_turn_ms"]["n"] == 9 and m["latency_turn_ms"]["p50"] == 20
    assert m["turns"]["max"] == 3 and m["clarify"]["share_with_any"]["k"] == 1
    by = {r["value"]: r for r in stats.breakdown(rs, "country")}
    assert by["MX"]["safe"]["p"] == 1.0 and by["AR"]["unmatched"] == 1.0
    lo, hi = stats.wilson(2, 5)
    assert lo < 0.4 < hi


def test_agreement_statistics():
    a = [True, True, False, False] * 25
    assert stats.kappa(a, a)["kappa"] == pytest.approx(1.0)
    assert stats.kappa(a, [not x for x in a])["kappa"] == pytest.approx(-1.0)
    rng = random.Random(1)
    noise = [rng.random() < 0.5 for _ in a]
    assert abs(stats.kappa(a, noise)["kappa"]) < 0.3
    labels = ["x", "y"] * 50
    assert stats.cramers_v(labels, labels) == pytest.approx(1.0)
    assert stats.permutation_p(stats.cramers_v, labels, labels, n_perm=200) < 0.05


def test_stratified_sample_is_proportional_exact_and_seeded():
    frame = [{"complaint_id": f"K{i:03d}", "creation_date": dt.datetime(2025, 1, 1) + dt.timedelta(hours=i),
              "country": "MX" if i < 60 else "CO", "segment": "Basic", "case_type": "Complaint"} for i in range(100)]
    s = stratified_sample(frame, 10, seed=7)
    assert len(s) == 10 and sum(r["country"] == "MX" for r in s) == 6
    assert s == stratified_sample(frame, 10, seed=7) and s != stratified_sample(frame, 10, seed=8)


# ---------------------------------------------------------------- conversación sobre el fixture
def _pit(serving_db):
    return PointInTimeTools(serving_db, IdentityService())


def _run_case(tools, customer, created, txn_id, subcategory="Cargo no reconocido", country="México"):
    txn = tools._rows("SELECT * FROM transactions WHERE transaction_id = ?", [txn_id])[0]
    tools.reset_ops()
    tools.as_of = created
    agent = build_agent(tools, router="rules", writer="templates", policy=PolicyEngine(as_of=created))
    case = {"subcategory": subcategory, "creation_date": created, "customer_country": country, "txn": txn}
    out = simulate(agent, tools.identity.login(customer), f"{customer}:{created}", case, DIALECTS[country], random.Random(0))
    tools.as_of = None
    return out


def test_simulated_customer_gets_an_automatic_verified_dispute(serving_db):
    out = _run_case(_pit(serving_db), "CLI-ANA", dt.datetime(2026, 6, 16, 18), "T-ANA-1")
    assert out["final_class"] == "auto_resolved" and out["verified"] and out["confirmation_asked"]
    assert out["dispute_opened"] and out["turns"] >= 2


def test_point_in_time_history_changes_h04(serving_db):
    tools = _pit(serving_db)
    # CLI-BETO tiene una queja con is_repeat_complainer=True creada el 2026-05-20
    assert _run_case(tools, "CLI-BETO", dt.datetime(2026, 6, 12), "T-BETO-1", country="Colombia")["final_class"] \
        == "handoff:H04_repeat_complainer"
    assert tools.history_as_of("CLI-BETO", dt.datetime(2026, 5, 1))["is_repeat_complainer"] is False
    assert tools.history_as_of("CLI-BETO", dt.datetime(2026, 5, 21))["is_repeat_complainer"] is True


def test_point_in_time_search_hides_later_transactions(serving_db):
    tools = _pit(serving_db)
    token = tools.identity.login("CLI-ANA")
    tools.as_of = dt.datetime(2026, 6, 11)
    ids = {t["transaction_id"] for t in tools.search_transactions(token, limit=20)}
    assert "T-ANA-2" in ids and not ids & {"T-ANA-1", "T-ANA-3", "T-ANA-6"}


def test_run_on_fixture_writes_a_labeled_report(serving_db, tmp_path):
    frame = [{"complaint_id": cid, "creation_date": created, "customer_id": cust, "case_type": "Complaint",
              "subcategory": sub, "affected_product_id": None, "status": "Open", "is_repeat_complainer": False,
              "country": country, "segment": "Basic", "customer_status": "Active"}
             for cid, created, cust, sub, country in [
                 ("K1", dt.datetime(2026, 6, 16, 18), "CLI-ANA", "Cargo no reconocido", "México"),
                 ("K2", dt.datetime(2026, 6, 12), "CLI-BETO", "Cobro indebido", "Colombia"),
                 ("K3", dt.datetime(2026, 1, 1), "CLI-CARLA", "Cargo no reconocido", "Argentina")]]
    md = tmp_path / "replay.md"
    s = run(serving_db, n=10, seed=7, pt_share=1.0, frame=frame, out_md=str(md), out_json=str(tmp_path / "r.json"))
    m = s["metrics"]
    assert m["n"] == 3 and m["groups"]["unmatched"]["k"] == 1  # CARLA no tiene transacciones antes del 2026-01-01
    assert m["safe_auto_of_all"]["k"] == 1 and m["handoff_by_rule"]["H04_repeat_complainer"]["k"] == 1
    assert s["pt"]["n"] == 2 and s["pt"]["same_class"]["p"] == 1.0  # mismo resultado en es y pt-BR
    text = md.read_text(encoding="utf-8")
    assert "SIMULACIÓN" in text and "no comparable" not in text  # sin --history-db no hay comparación histórica
    assert "CLI-" not in text and "T-ANA" not in text  # el reporte no expone IDs
