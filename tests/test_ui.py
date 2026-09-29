"""Demo web: helpers de formato y guion de cada escenario, sin navegador."""
import importlib.util
import os

import pytest

from bankagent import app_health, ui
from bankagent.demo_fixture import CANARY_MERCHANT

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "streamlit_app.py")


@pytest.fixture
def session(serving_db):
    return ui.new_session(serving_db, "CLI-ANA")


def test_env_db_is_used_when_present(serving_db, tmp_path):
    assert ui.resolve_db_path({"BANKAGENT_DB": serving_db}) == (serving_db, "env")
    path, src = ui.resolve_db_path({"BANKAGENT_DB": str(tmp_path / "no-existe.duckdb")}, cache_dir=str(tmp_path))
    assert src == "fixture" and os.path.exists(path)


@pytest.mark.parametrize("sc", ui.SCENARIOS, ids=lambda s: s.customer_id)
def test_every_example_runs_and_formats(serving_db, sc):
    s = ui.new_session(serving_db, sc.customer_id)
    for ex in sc.examples + ui.FOLLOW_UPS:
        if ex.fresh:
            s.restart()
        state = s.send(ex.text)
        assert state["reply"] and ui.outcome_badge(state["outcome"])[0]
        rows = ui.turn_trace(state)
        assert rows and rows[0]["node"] == "guard" and rows[-1]["node"] == "respond"
        ui.policy_view(state), ui.handoff_view(state.get("handoff"))
        dumped = ui.to_json(ui.raw_state(state))
        assert s.token not in dumped and CANARY_MERCHANT not in dumped


def test_trace_and_policy_views(session):
    session.send("No reconozco un cargo de 77 dólares")
    state = session.send("sí")
    rows = ui.turn_trace(state)
    assert [r["node"] for r in rows] == ["guard", "understand", "act", "respond"]
    act = next(r for r in rows if r["node"] == "act")
    assert {t["text"].split(" ")[0] for t in act["tools"]} == {"open_dispute", "block_card"}
    assert all(t["ok"] for t in act["tools"]) and rows[-1]["next"] == "fin"
    assert ui.outcome_badge("resolved") == ("resuelto", "green")


def test_handoff_view_sections(session):
    state = session.send("no reconozco el cargo de 1200 del 10/06/2026")
    pol, hv = ui.policy_view(state), ui.handoff_view(state["handoff"])
    assert pol["rules"][0]["id"] == "H02_high_amount" and pol["version"]
    assert hv["reason"] == "H02_high_amount" and hv["reason_text"]
    assert hv["transaction"]["transaction_id"] == "T-ANA-2"
    assert hv["questions"] and hv["request"] and hv["evidence"]
    assert ui.handoff_view(None) is None


def test_expired_session_and_injection(session):
    assert session.send(ui.INJECTION_EXAMPLE)["outcome"] == "blocked"
    session.expire()
    assert session.send("sí")["outcome"] == "auth_error"
    session.restart()
    assert session.send("hola")["outcome"] == "clarify"


def test_failed_tool_call_is_formatted():
    assert "falló: unavailable" in ui.format_tool_call({"tool": "x", "ok": False, "attempt": 2, "error": "unavailable"})
    assert ui.label("why", "pt") == "Por que respondeu assim" and ui.label("why", None) == "Por qué respondió así"


def test_health_check_offline(monkeypatch, serving_db):
    monkeypatch.setenv("BANKAGENT_DB", serving_db)
    assert app_health.check_agent()


@pytest.mark.skipif(importlib.util.find_spec("streamlit") is None, reason="extra [ui] no instalado")
def test_streamlit_app_renders(serving_db, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("BANKAGENT_DB", serving_db)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    at.sidebar.button(key="ex2").click().run()  # monto alto -> handoff
    assert not at.exception
    assert any("H02_high_amount" in m.value for m in at.markdown)
