"""Log JSON por nodo: apagado por defecto, una línea por nodo, sin texto del cliente ni token."""
import json
import logging

import pytest

from bankagent import observability


@pytest.fixture
def capture():
    records: list[str] = []

    class H(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    h = H()
    observability.logger.addHandler(h)
    observability.logger.setLevel(logging.INFO)
    yield records
    observability.logger.removeHandler(h)


def test_off_by_default(env, capture, monkeypatch):
    monkeypatch.delenv("BANKAGENT_LOG_JSON", raising=False)
    env.agent.chat(env.thread(), env.login("CLI-ANA"), "No reconozco un cargo de 77 dólares")
    assert capture == []


def test_one_json_line_per_node_without_pii(env, capture, monkeypatch):
    monkeypatch.setenv("BANKAGENT_LOG_JSON", "1")
    tok = env.login("CLI-ANA")
    text = "No reconozco un cargo de 77 dólares, mi tarjeta es 4111 1111 1111 1111"
    r = env.agent.chat(env.thread(), tok, text)
    lines = [json.loads(x) for x in capture]
    assert [x["node"] for x in lines] == [e["node"] for e in r["trace"]]
    ft = next(x for x in lines if x["node"] == "find_transaction")
    assert ft["tools"][0]["tool"] == "search_transactions" and ft["tool_errors"] == 0 and ft["ms"] >= 0
    raw = "\n".join(capture)
    assert tok not in raw and "4111 1111" not in raw and "reconozco" not in raw


def test_llm_telemetry_is_logged_for_fallback_rate(env, capture, monkeypatch):
    from bankagent.graph import Agent
    from bankagent.llm_router import LLMRouter
    from bankagent.policy import PolicyEngine

    monkeypatch.setenv("BANKAGENT_LOG_JSON", "1")
    agent = Agent(env.tools, PolicyEngine(), router=LLMRouter(None))  # sin cliente: cae a reglas
    agent.chat(env.thread(), env.login("CLI-ANA"), "No reconozco un cargo de 77 dólares")
    und = next(json.loads(x) for x in capture if json.loads(x)["node"] == "understand")
    assert und["llm"]["component"] == "router" and und["llm"]["fallback"] == "no_client"
    assert set(und["llm"]) <= set(observability.LLM_FIELDS) | {"violations"}
