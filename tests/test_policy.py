"""Motor de política: orden de reglas, fronteras de umbral y expresiones restringidas."""
import datetime as dt

import pytest

from bankagent.policy import PolicyEngine, _compile

ACTIVE = {"customer_status": "Active"}
CLEAN = {"is_repeat_complainer": False, "open_dispute_transactions": []}


def txn(**kw):
    base = {"transaction_id": "T1", "transaction_date": dt.datetime(2026, 6, 10), "transaction_status": "Approved",
            "amount": 100, "currency": "USD", "fraud_score": 10}
    return {**base, **kw}


@pytest.mark.parametrize("score,outcome", [(29.99, "auto_with_confirmation"), (30, "handoff"), (None, "auto_with_confirmation")])
def test_fraud_threshold_boundary(score, outcome):
    assert PolicyEngine().decide_dispute(txn(fraud_score=score), ACTIVE, CLEAN).outcome == outcome


def test_first_matching_rule_decides_but_all_hits_are_reported():
    d = PolicyEngine().decide_dispute(txn(transaction_status="Declined", amount=5000, fraud_score=90), ACTIVE, CLEAN)
    assert d.outcome == "reject" and d.deciding_rule.id == "D02_declined_not_charged"
    assert {"H02_high_amount", "H03_fraud_signal"} <= {h.id for h in d.hits}


def test_age_limit_uses_policy_as_of_date():
    # as_of = 2026-06-17 y el plazo es 120 días: el 17/02 está en plazo (120), el 16/02 no (121)
    assert PolicyEngine().decide_dispute(txn(transaction_date=dt.datetime(2026, 2, 17)), ACTIVE, CLEAN).outcome == "auto_with_confirmation"
    assert PolicyEngine().decide_dispute(txn(transaction_date=dt.datetime(2026, 2, 16)), ACTIVE, CLEAN).deciding_rule.id == "D05_too_old"


@pytest.mark.parametrize("expr", ["__import__('os').system('x')", "txn.amount.__class__", "open('f')", "[x for x in y]"])
def test_policy_expressions_cannot_call_or_introspect(expr):
    with pytest.raises((ValueError, SyntaxError)):
        _compile(expr)
