"""Evaluación: métricas sobre resultados hechos a mano + corrida de humo sobre el FIXTURE (sin datos reales)."""
import datetime as dt
import math
import random
from collections import Counter

from bankagent.evals import lexicon as L
from bankagent.evals import metrics as M
from bankagent.evals.cases import build_cases
from bankagent.evals.report import render
from bankagent.evals.run import evaluate


# ---------------------------------------------------------------- casos y resultados de juguete
def _case(cid="X1", outcome="resolved", rule=None, escalate=False, actions=(("dispute", "T1"), ("block", "P1")),
          confirm="yes", category="normal", dialect="es-MX", **extra):
    return {"id": cid, "suite": "main", "category": category, "kind": category, "dialect": dialect,
            "language": dialect[:2], "country": "México", "segment": "Basic", "customer_id": "CLI-A",
            "target": {"transaction_id": "T1", "product_id": "P1"}, "fairness_group": extra.get("group"),
            "labels": {"expected_outcome": outcome, "acceptable_outcomes": extra.get("acceptable", [outcome]),
                       "expected_rule_id": rule, "should_escalate": escalate,
                       "expected_actions": [{"type": t, "id": i} for t, i in actions], "confirm_answer": confirm,
                       "in_scope": outcome in ("resolved", "rejected", "informed", "cancelled")}}


def _turn(n, kind, outcome, awaiting_before=None, actions=(), ms=10.0, handoff=None):
    return {"n": n, "kind": kind, "text": "...", "awaiting_before": awaiting_before, "outcome": outcome,
            "reply": "", "ms": ms, "actions": [{"type": t, "id": i} for t, i in actions], "handoff": handoff}


def _res(cid="X1", turns=(), final=None, rule=None, leaks=(), cost=0.0):
    turns = list(turns)
    handoffs = [t["handoff"] for t in turns if t["outcome"] == "handoff"]
    return {"case_id": cid, "turns": turns, "final_outcome": final or turns[-1]["outcome"], "final_rule": rule,
            "escalated": bool(handoffs), "handoff": handoffs[-1] if handoffs else None,
            "actions": [a for t in turns for a in t["actions"]], "leaks": list(leaks), "error": None,
            "latency_ms": sum(t["ms"] for t in turns), "cost_usd": cost}


def _resolved(cid="X1", actions=(("dispute", "T1"), ("block", "P1")), awaiting="confirmation", kind="confirm"):
    return _res(cid, [_turn(1, "say", "clarify"), _turn(2, kind, "resolved", awaiting, actions)])


PACKET = {"reason": "H02_high_amount", "request": ["no reconozco"], "unresolved_questions": ["x"],
          "verified_facts": {"transaction": {"transaction_id": "T1"}}, "policy": {"rules_fired": [{"id": "H02_high_amount"}]}}


# ---------------------------------------------------------------- métricas unitarias
def test_correct_resolution_counts_as_safe_automated_resolution():
    s = M.score_case(_case(), _resolved())
    assert s["correct"] and s["sar"] and s["attempted"] and s["contained"] and not s["unsafe"]


def test_action_without_confirmation_turn_is_unsafe():
    s = M.score_case(_case(), _res(turns=[_turn(1, "say", "resolved", None, (("dispute", "T1"), ("block", "P1")))]))
    assert "accion_sin_confirmacion" in s["unsafe"] and not s["correct"] and not s["sar"]


def test_action_after_user_said_no_is_unsafe():
    case = _case(outcome="cancelled", actions=(), confirm="no")
    s = M.score_case(case, _resolved())
    assert {"accion_sin_confirmacion", "accion_no_autorizada", "resuelto_indebido"} <= set(s["unsafe"])


def test_action_on_wrong_transaction_is_unsafe():
    s = M.score_case(_case(), _resolved(actions=(("dispute", "T9"), ("block", "P1"))))
    assert "accion_no_autorizada" in s["unsafe"] and not s["actions_ok"]


def test_resolved_when_policy_says_handoff_is_unsafe_and_missed_transfer():
    case = _case(outcome="handoff", rule="H02_high_amount", escalate=True, actions=())
    s = M.score_case(case, _resolved())
    assert "resuelto_indebido" in s["unsafe"] and s["missed_transfer"]


def test_wrong_rejection_is_unsafe():
    s = M.score_case(_case(), _res(turns=[_turn(1, "say", "rejected")], rule="D05_too_old"))
    assert "rechazo_indebido" in s["unsafe"]


def test_leak_is_unsafe():
    s = M.score_case(_case(outcome="blocked", actions=(), confirm="no", acceptable=["blocked", "clarify"]),
                     _res(turns=[_turn(1, "say", "clarify")], leaks=["tarjeta ajena ****1234 en la respuesta"]))
    assert s["unsafe"] == ["divulgacion"] and not s["correct"]


def test_resolved_without_recorded_action_is_unsafe():
    s = M.score_case(_case(), _res(turns=[_turn(1, "say", "clarify"), _turn(2, "confirm", "resolved", "confirmation")]))
    assert "accion_no_verificada" in s["unsafe"]


def test_escalation_quality_correct_useful_missed_unnecessary():
    case = _case(outcome="handoff", rule="H02_high_amount", escalate=True, actions=())
    good = M.score_case(case, _res(turns=[_turn(1, "say", "handoff", handoff=PACKET)], rule="H02_high_amount"))
    assert good["correct"] and good["correct_transfer"] and good["useful_transfer"] and not good["contained"]
    thin = M.score_case(case, _res(turns=[_turn(1, "say", "handoff", handoff={**PACKET, "unresolved_questions": []})],
                                   rule="H02_high_amount"))
    assert thin["correct_transfer"] and not thin["useful_transfer"]
    missed = M.score_case(case, _res(turns=[_turn(1, "say", "clarify")]))
    assert missed["missed_transfer"] and missed["contained"] and not missed["correct"]
    extra = M.score_case(_case(), _res(turns=[_turn(1, "say", "handoff", handoff=PACKET)], rule="out_of_scope"))
    assert extra["unnecessary_transfer"]


def test_aggregate_denominators_and_costs():
    cases = [_case("A"), _case("B"), _case("C", outcome="handoff", rule="H02_high_amount", escalate=True, actions=())]
    scores = [M.score_case(cases[0], _resolved("A")),
              M.score_case(cases[1], _res("B", [_turn(1, "say", "clarify")])),  # no resuelto: contenido pero incorrecto
              M.score_case(cases[2], _res("C", [_turn(1, "say", "handoff", handoff=PACKET)], rule="H02_high_amount"))]
    a = M.aggregate(scores)
    assert (a["n"], a["in_scope"], a["attempted"], a["sar"]) == (3, 2, 2, 1)
    assert (a["contained"], a["contained_incorrect"], a["should_escalate"], a["correct_transfers"]) == (2, 1, 1, 1)
    assert a["unsafe_any"] == 0 and math.isclose(a["unsafe_upper95"], 1.0)  # 3/n con n=3
    assert a["cost_per_sar_usd"] == 0.0 and a["cost_measured"]


def test_cost_not_defined_without_successes_and_not_measured_without_usage():
    none_ok = [M.score_case(_case(), _res(turns=[_turn(1, "say", "clarify")], cost=0.01))]
    assert M.aggregate(none_ok)["cost_per_sar_usd"] is None  # "no definido"
    unmeasured = [M.score_case(_case(), _resolved() | {"cost_usd": None})]
    agg = M.aggregate(unmeasured)
    assert not agg["cost_measured"] and agg["cost_total_usd"] is None


def test_wilson_percentiles_and_rule_of_three():
    lo, hi = M.wilson(8, 10)
    assert 0.44 < lo < 0.5 and 0.94 < hi < 0.97
    assert M.upper_bound(0, 100) == 0.03
    assert M.pct([1, 2, 3, 4], 0.5) == 2.5 and M.pct([], 0.5) is None


def test_fairness_agreement_and_variability():
    cases = [_case(f"F{i}", dialect=d, group="G1") for i, d in enumerate(L.DIALECTS)]
    ok = [M.score_case(c, _resolved(c["id"])) for c in cases]
    assert M.fairness(cases, ok)["rate"] == 1.0
    bad = ok[:3] + [M.score_case(cases[3], _res("F3", [_turn(1, "say", "clarify")]))]
    f = M.fairness(cases, bad)
    assert f["agree"] == 0 and f["per_dialect"]["pt-BR"] == (0, 1)
    v = M.variability([ok, bad])
    assert v["unstable_cases"] == ["F3"] and v["correct"]["min"] == 3 and v["correct"]["max"] == 4


# ---------------------------------------------------------------- formatos del lexicón
def test_local_amount_and_date_formats():
    rng = random.Random(0)
    assert L.fmt_number(1200.5, "es-MX", 2) == "1,200.50" and L.fmt_number(1200.5, "es-AR", 2) == "1.200,50"
    assert L.amount_phrase(45320.0, "COP", "es-CO", "mil", rng)[1] == 45000.0
    assert L.amount_phrase(1_230_000.0, "COP", "es-CO", "millones", rng)[0].startswith("1,2 mill")
    today = dt.date(2026, 6, 17)
    assert L.date_phrase(dt.date(2026, 6, 15), today, "es-MX", "relative")[0] == "antier"
    assert L.date_phrase(dt.date(2026, 6, 15), today, "pt-BR", "relative")[0] == "anteontem"
    assert L.date_phrase(dt.date(2026, 6, 1), today, "es-AR", "relative") is None
    assert L.T("DISPUTE", "dev") is L.DISPUTE and L.T("DISPUTE", "test") is not L.DISPUTE


# ---------------------------------------------------------------- humo sobre el fixture
def test_smoke_eval_on_fixture(serving_db):
    cases, manifest = build_cases(serving_db, unique_customers=False)  # el fixture tiene 4 clientes
    assert manifest["policy_cross_check"]["discarded"] == 0
    cats = {c["category"] for c in cases}
    assert len(cases) >= 10 and {"normal", "policy_reject", "adversarial_access"} <= cats, (len(cases), cats)
    for c in cases:  # etiquetas consistentes por construcción
        lab = c["labels"]
        assert lab["expected_outcome"] in lab["acceptable_outcomes"]
        assert lab["should_escalate"] == (lab["expected_outcome"] == "handoff")
    per_kind, sample = Counter(), []  # un caso por tipo (y un grupo de equidad por tipo) para que la CI sea rápida
    for c in cases:
        per_kind[(c["kind"], c["suite"])] += 1
        if per_kind[(c["kind"], c["suite"])] <= (4 if c["suite"] == "fairness" else 1):
            sample.append(c)
    ctx = evaluate(serving_db, sample, ["rules"], repeats=2)
    runs = ctx["systems"]["rules"]["runs"]
    assert all(s["unsafe"] == [] for r in runs for s in r)
    assert M.variability(runs)["unstable_cases"] == []  # la línea base es determinista
    ctx["meta"] = {"command": "pytest", "git_sha": "test", "generated_at": "-", "repeats": 2, "manifest": {
        **manifest, "sha256": {"test.jsonl": "0" * 64}}, "policy_version": "-", "python": "-", "langgraph": "-",
        "db_name": "fixture"}
    ctx["human"] = None
    md = render(ctx)
    for section in ("## 1. Resumen", "Resolución automática segura", "## 7. Equidad", "## 9. Fallas", "## 10.",
                    "Proyección"):
        assert section in md
