"""Utilidades compartidas por select_demo_customers.py y verify_demo.py.

Un escenario de demo es un cliente REAL del dataset del organizador + los mensajes exactos por turno +
lo que se espera observar en cada turno. El juez es el agente real (Agent + BankTools + PolicyEngine):
un escenario solo se acepta, o se da por verificado, si el agente produce exactamente lo esperado.
"""
from __future__ import annotations

import glob
import hashlib
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from bankagent.factory import build_agent  # noqa: E402
from bankagent.identity import IdentityService  # noqa: E402
from bankagent.pipeline import load_contracts  # noqa: E402
from bankagent.policy import POLICY, PolicyEngine  # noqa: E402
from bankagent.tools import BankTools  # noqa: E402

DEFAULT_SCENARIOS = os.path.join(ROOT, "docs", "demo", "demo_customers.json")


def fraud_threshold(policy_path: str = POLICY) -> float:
    """Umbral de H03 leído del YAML (no se fija en el código: se recalibra)."""
    with open(policy_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    rule = next(r for r in cfg["dispute"]["rules"] if r["id"].startswith("H03"))
    m = re.search(r"fraud_score\s*>=\s*([0-9.]+)", rule["when"])
    if not m:
        raise ValueError(f"No se pudo leer el umbral de fraude de {rule['when']!r}")
    return float(m.group(1))


def source_fingerprint(raw_dir: str) -> dict:
    """Huella de la entrega por tabla: sha256 de (ruta relativa | tamaño) de los archivos que lee el pipeline.
    Misma fórmula que `source_fingerprint` del manifiesto del pipeline, para poder compararlas."""
    contracts = load_contracts()
    contracts.pop("normalize", None)
    out = {}
    for table, spec in contracts.items():
        files = sorted(glob.glob(os.path.join(raw_dir, spec["source"]), recursive=True))
        out[table] = {"files": len(files), "bytes": sum(os.path.getsize(f) for f in files),
                      "sha256_16": hashlib.sha256("\n".join(
                          f"{os.path.relpath(f, raw_dir).replace(os.sep, '/')}|{os.path.getsize(f)}" for f in files
                      ).encode()).hexdigest()[:16]}
    return out


def observe(r: dict) -> dict:
    """Lo observable de un turno, en la forma en que se escriben las expectativas."""
    decision = r.get("decision") or {}
    rules = decision.get("rules") or []
    ar = r.get("action_result") or {}
    verified = None
    if ar:
        parts = [x for x in (ar.get("dispute"), ar.get("block")) if x is not None]
        verified = bool(parts) and all(x["verified"] for x in parts) and ar.get("block") is not None
    return {
        "outcome": r.get("outcome"),
        "lang": r.get("lang"),
        "rule": rules[0]["id"] if rules else None,
        "rules_fired": [h["id"] for h in rules],
        "handoff_reason": (r.get("handoff") or {}).get("reason"),
        "txn_id": (r.get("txn") or {}).get("transaction_id"),
        "candidate_ids": [c["transaction_id"] for c in (r.get("candidates") or []) if "transaction_id" in c],
        "dispute_and_block_verified": verified,
        "actions_verified": sorted(k for k in ("dispute", "block") if (ar.get(k) or {}).get("verified")),
        "reply": r.get("reply") or "",
    }


def _check(expect: dict, got: dict) -> list[str]:
    bad = []
    for k, v in expect.items():
        if k == "reply_contains":
            if v not in got["reply"]:
                bad.append(f"reply sin {v!r}")
        elif got.get(k) != v:
            bad.append(f"{k}: esperado {v!r}, obtenido {got.get(k)!r}")
    return bad


def run_scenario(db: str, sc: dict, policy_path: str = POLICY, router: str = "rules") -> tuple[bool, list[dict]]:
    """Corre el escenario con un agente nuevo (ops en memoria: sin estado de otros escenarios).
    `router`: "rules" (línea base) o "embeddings" (router aprendido lite, extra ml)."""
    identity = IdentityService()
    tools = BankTools(db, identity)
    agent = build_agent(tools, router=router, policy=PolicyEngine(policy_path))
    token = identity.login(sc["customer_id"])
    log, ok = [], True
    try:
        for i, turn in enumerate(sc["turns"], 1):
            if turn.get("action") == "expire_session":
                identity.expire(token)
                log.append({"turn": i, "action": "expire_session", "ok": True, "problems": []})
                continue
            got = observe(agent.chat(sc["id"], token, turn["say"]))
            problems = _check(turn.get("expect", {}), got)
            ok &= not problems
            log.append({"turn": i, "say": turn["say"], "got": got, "ok": not problems, "problems": problems})
            if problems:
                break
    finally:
        tools._ro.close()
        tools._ops.close()
    return ok, log
