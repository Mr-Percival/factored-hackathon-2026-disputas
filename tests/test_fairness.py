"""Equidad por dialecto (issue #13): el mismo caso redactado en es-MX, es-CO, es-AR (voseo) y pt-BR debe dar la
misma decisión de política y la misma acción; solo cambia la redacción.

Usa las plantillas de DEV (v1). Las de test (v2) no se prueban aquí a propósito: si fallaran, la tentación de
ajustar el router con ellas contaminaría el conjunto reservado. Su resultado se reporta en reports/eval.md.
"""
import datetime as dt
import random

import pytest

from bankagent.evals import lexicon as L
from bankagent.evals.runner import ScriptedUser

TODAY = dt.date(2026, 6, 17)
DATE_STYLES = ["dm_num", "dm_text", "ago", "weekday", "none", "dmy_num"]

# (id, transacción del fixture, decisión esperada)
SCENARIOS = [
    ("normal", {"transaction_id": "T-ANA-8", "amount": 77.0, "d": dt.date(2026, 6, 13)},
     "resolved|-|block:PRD-ANA-CC,dispute:T-ANA-8"),
    ("declinada", {"transaction_id": "T-ANA-6", "amount": 45.0, "d": dt.date(2026, 6, 16)},
     "rejected|D02_declined_not_charged|-"),
    ("monto_alto", {"transaction_id": "T-ANA-2", "amount": 1200.0, "d": dt.date(2026, 6, 10)},
     "handoff|H02_high_amount|-"),
    ("fraude", {"transaction_id": "T-ANA-3", "amount": 89.90, "d": dt.date(2026, 6, 12)},
     "handoff|H03_fraud_signal|-"),
]
N_VARIANTS = max(len(v) for v in L.DISPUTE.values())


def _converse(env, case):
    user, tok, th = ScriptedUser(case), env.login("CLI-ANA"), env.thread()
    state, actions = {}, []
    for i in range(6):
        msg = user.next(i, state)
        if msg is None:
            break
        state = env.agent.chat(th, tok, msg[1])
    for (tid,) in env.tools._ops.execute("SELECT transaction_id FROM disputes").fetchall():
        actions.append(f"dispute:{tid}")
    for (pid,) in env.tools._ops.execute("SELECT product_id FROM card_blocks").fetchall():
        actions.append(f"block:{pid}")
    outcome = state.get("outcome")
    rule = ((state.get("handoff") or {}).get("reason") if outcome == "handoff"
            else ((state.get("decision") or {}).get("rules") or [{}])[0].get("id") if outcome in ("rejected", "informed")
            else None)
    return f"{outcome}|{rule or '-'}|{','.join(sorted(actions)) or '-'}"


def _dispute_case(dialect, txn, variant):
    rng = random.Random(variant)
    amt = L.amount_phrase(txn["amount"], "USD", dialect, "exact", rng)[0]
    style = DATE_STYLES[variant % len(DATE_STYLES)]
    date = L.date_phrase(txn["d"], TODAY, dialect, style) or L.date_phrase(txn["d"], TODAY, dialect, "dm_num")
    tpl = L.DISPUTE[dialect][variant % len(L.DISPUTE[dialect])]
    text = L.clean(tpl.format(what=L.WHAT[dialect]["Purchase"][0], amt=amt, date=date[0], merchant=""))
    return {"id": f"{dialect}-{variant}", "language": L.lang_of(dialect), "target": {"transaction_id": txn["transaction_id"]},
            "turns": [{"when": "say", "text": text},
                      {"when": "option", "text": L.OPTION[dialect][variant % len(L.OPTION[dialect])]},
                      {"when": "confirm", "text": L.CONFIRM_YES[dialect][variant % len(L.CONFIRM_YES[dialect])]}]}


@pytest.mark.parametrize("variant", range(N_VARIANTS))
@pytest.mark.parametrize("name,txn,expected", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_same_dispute_same_decision_in_every_dialect(env, name, txn, expected, variant):
    got = {}
    for dialect in L.DIALECTS:
        env.tools._ops.execute("DELETE FROM disputes; DELETE FROM card_blocks")
        got[dialect] = _converse(env, _dispute_case(dialect, txn, variant))
    assert got == {d: expected for d in L.DIALECTS}, got


@pytest.mark.parametrize("variant", range(max(len(v) for v in L.BLOCK.values())))
def test_same_block_request_same_action_in_every_dialect(env, variant):
    got = {}
    for dialect in L.DIALECTS:
        env.tools._ops.execute("DELETE FROM disputes; DELETE FROM card_blocks")
        lang = L.lang_of(dialect)
        tpl = L.BLOCK[dialect][variant % len(L.BLOCK[dialect])]
        case = {"id": f"{dialect}-b{variant}", "language": lang, "target": {"product_id": "PRD-ANA-DC"},
                "turns": [{"when": "say", "text": tpl.format(ctype=L.CARD_TYPE["Tarjeta Débito"][lang])},
                          {"when": "option", "text": L.OPTION[dialect][variant % len(L.OPTION[dialect])]},
                          {"when": "confirm", "text": L.CONFIRM_YES[dialect][variant % len(L.CONFIRM_YES[dialect])]}]}
        got[dialect] = _converse(env, case)
    assert got == {d: "resolved|-|block:PRD-ANA-DC" for d in L.DIALECTS}, got
