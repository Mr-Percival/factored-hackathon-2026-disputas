"""Flujos del agente: normal, ambiguo, handoff, rechazo por política, portugués, fallas de herramienta."""
from bankagent.tools import ToolError


def say(env, thread, token, text):
    return env.agent.chat(thread, token, text)


def test_normal_path_dispute_and_block_with_confirmation(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    r = say(env, th, tok, "No reconozco un cargo de 77 dólares")
    assert r["outcome"] == "clarify" and "Confirmas" in r["reply"]
    assert not env.tools._ops.execute("SELECT count(*) FROM disputes").fetchone()[0]  # nada sin confirmar
    r = say(env, th, tok, "sí")
    assert r["outcome"] == "resolved"
    assert r["action_result"]["dispute"]["verified"] and r["action_result"]["block"]["verified"]
    assert r["action_result"]["dispute"]["case_id"] in r["reply"]


def test_ambiguous_asks_which_then_resolves(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    r = say(env, th, tok, "me cobraron 350 y no fui yo")
    assert r["outcome"] == "clarify" and len(r["candidates"]) == 2
    r = say(env, th, tok, "la 1")
    assert "Confirmas" in r["reply"]
    r = say(env, th, tok, "no")
    assert r["outcome"] == "cancelled"


def test_high_amount_goes_to_human_with_handoff_packet(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    r = say(env, th, tok, "no reconozco el cargo de 1200 del 10/06/2026")
    assert r["outcome"] == "handoff"
    p = r["handoff"]
    assert p["reason"] == "H02_high_amount"
    assert p["verified_facts"]["transaction"]["transaction_id"] == "T-ANA-2"
    assert p["policy"]["rules_fired"][0]["id"] == "H02_high_amount"
    assert p["unresolved_questions"] and p["request"]


def test_portuguese_fraud_signal_handoff(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    r = say(env, th, tok, "Não reconheço uma cobrança no Brasil")
    assert r["lang"] == "pt" and r["outcome"] == "handoff"
    assert r["handoff"]["reason"] == "H03_fraud_signal"
    assert "atendente" in r["reply"] or "analista" in r["reply"]


def test_policy_rejects_declined_and_old(env):
    tok = env.login("CLI-ANA")
    r = say(env, env.thread(), tok, "no reconozco un cobro de 45")
    assert r["outcome"] == "rejected" and r["decision"]["rules"][0]["id"] == "D02_declined_not_charged"
    r = say(env, env.thread(), tok, "no reconozco un cobro de 515")
    assert r["decision"]["rules"][0]["id"] == "D05_too_old"


def test_repeat_complainer_and_suspended_go_to_human(env):
    r = say(env, env.thread(), env.login("CLI-BETO"), "no reconozco un cargo de 200.000")
    assert r["handoff"]["reason"] == "H04_repeat_complainer"
    r = say(env, env.thread(), env.login("CLI-CARLA"), "no reconozco un cargo de 15.000")
    assert r["handoff"]["reason"] == "H01_customer_not_active"


def test_out_of_scope_and_unknown(env):
    tok = env.login("CLI-ANA")
    r = say(env, env.thread(), tok, "quiero un préstamo hipotecario")
    assert r["outcome"] == "handoff" and r["handoff"]["reason"] == "out_of_scope"
    r = say(env, env.thread(), tok, "hola")
    assert r["outcome"] == "clarify"


def test_block_card_only(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    r = say(env, th, tok, "perdí mi tarjeta, quiero bloquearla")
    assert r["awaiting"] == "option"  # Ana tiene dos tarjetas
    r = say(env, th, tok, "2")
    r = say(env, th, tok, "sí")
    assert r["outcome"] == "resolved" and r["action_result"]["block"]["verified"]


def test_transient_tool_failure_is_retried(env, monkeypatch):
    real, calls = env.tools.search_transactions, {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ToolError("unavailable")
        return real(*a, **k)

    monkeypatch.setattr(env.tools, "search_transactions", flaky)
    r = say(env, env.thread(), env.login("CLI-ANA"), "no reconozco un cargo de 77")
    assert "Confirmas" in r["reply"] and calls["n"] == 2


def test_persistent_tool_failure_hands_off(env, monkeypatch):
    def down(*a, **k):
        raise ToolError("unavailable")

    monkeypatch.setattr(env.tools, "search_transactions", down)
    r = say(env, env.thread(), env.login("CLI-ANA"), "no reconozco un cargo de 77")
    assert r["outcome"] == "handoff" and r["handoff"]["reason"] == "tool_failure"
    attempts = [c for e in r["trace"] for c in e["tools"] if c["tool"] == "search_transactions"]
    assert len(attempts) == 3  # 1 + 2 reintentos, acotado


def test_new_request_starting_with_no_does_not_cancel_as_deny(env):
    """#23: con una confirmación pendiente, 'no reconozco otro cargo…' inicia un flujo nuevo, no es un 'no'."""
    tok, th = env.login("CLI-ANA"), env.thread()
    say(env, th, tok, "No reconozco un cargo de 77 dólares")
    r = say(env, th, tok, "no reconozco otro cargo de 1200 del 10/06/2026")
    assert r["outcome"] == "handoff" and r["handoff"]["reason"] == "H02_high_amount"
    tok, th = env.login("CLI-ANA"), env.thread()
    say(env, th, tok, "Não reconheço uma cobrança de 77")
    r = say(env, th, tok, "não, não reconheço outra cobrança no Brasil")
    assert r["outcome"] == "handoff" and r["handoff"]["reason"] == "H03_fraud_signal"


def test_short_no_still_cancels(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    say(env, th, tok, "No reconozco un cargo de 77 dólares")
    r = say(env, th, tok, "mejor no, gracias")
    assert r["outcome"] == "cancelled"
    assert not env.tools._ops.execute("SELECT count(*) FROM disputes").fetchone()[0]
