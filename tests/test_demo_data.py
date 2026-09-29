"""Guion de demo: el JSON commiteado no lleva PII y el verificador detecta divergencias (sobre el FIXTURE)."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from demo_scenarios import DEFAULT_SCENARIOS, fraud_threshold, run_scenario  # noqa: E402

SAFE_CUSTOMER_KEYS = {"customer_id", "country", "status", "repeat_complainer"}


def test_committed_demo_json_is_consistent_and_has_no_pii():
    with open(DEFAULT_SCENARIOS, encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["missing_scenarios"] == []
    assert set(doc["customer_ids"]) == {s["customer_id"] for s in doc["scenarios"]}
    for s in doc["scenarios"]:
        assert set(s["customer"]) <= SAFE_CUSTOMER_KEYS
        assert all("say" in t or t.get("action") == "expire_session" for t in s["turns"])
    raw = json.dumps(doc, ensure_ascii=False)
    assert "first_name" not in raw and "document_number" not in raw


def test_fraud_threshold_is_read_from_policy_yaml(tmp_path):
    from bankagent.policy import POLICY
    with open(POLICY, encoding="utf-8") as f:
        text = f.read()
    t = fraud_threshold(POLICY)
    p = tmp_path / "policy.yaml"
    p.write_text(text.replace(f"fraud_score >= {t:g}", "fraud_score >= 42"), encoding="utf-8")
    assert fraud_threshold(str(p)) == 42


def test_run_scenario_passes_and_detects_divergence(serving_db):
    sc = {"id": "t", "customer_id": "CLI-ANA", "turns": [
        {"say": "no reconozco un cargo de 350", "expect": {"outcome": "clarify", "candidate_ids": ["T-ANA-1", "T-ANA-5"]}},
        {"action": "expire_session"},
        {"say": "la 1", "expect": {"outcome": "auth_error", "reply_contains": "expiró"}},
    ]}
    ok, log = run_scenario(serving_db, sc)
    assert ok, log
    sc["turns"][0]["expect"]["outcome"] = "resolved"
    ok, log = run_scenario(serving_db, sc)
    assert not ok and "outcome" in log[0]["problems"][0]
