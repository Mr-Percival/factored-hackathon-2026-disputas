"""Corre la evaluación y escribe el reporte.

    python -m bankagent.evals.run --db data/serving.duckdb --system rules --repeats 3
    python -m bankagent.evals.run --system rules --system llm          # comparación sobre los mismos casos

Casos: `evals/cases/<split>.jsonl` (se generan con `python -m bankagent.evals.cases`).
Salidas: `reports/eval.md` (se versiona) y `data/evals/results.json` (detalle por caso y turno; no se versiona).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import sys

import duckdb

from ..pipeline import ROOT
from ..policy import PolicyEngine
from . import metrics as M
from .cases import load
from .report import render
from .runner import get_system, run_case


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def human_baseline(path: str) -> dict | None:
    """Referencia histórica de la operación humana (tablas raw del organizador). None si no está la base."""
    if not path or not os.path.exists(path):
        return None
    con = duckdb.connect(path, read_only=True)
    try:
        r = con.execute("""SELECT count(*), avg((was_resolved = 'True')::INT), avg((was_escalated = 'True')::INT),
                avg((requires_followup = 'True')::INT), median(duration_seconds::DOUBLE),
                quantile_cont(duration_seconds::DOUBLE, 0.95), median(wait_time_seconds::DOUBLE),
                min(interaction_date)[:10], max(interaction_date)[:10]
            FROM raw_call_center_interactions WHERE reason_category = 'Queja'""").fetchone()
        acc = con.execute("""SELECT coalesce(customer_detected_accent, 'sin dato'), avg((was_resolved = 'True')::INT), count(*)
            FROM raw_call_center_interactions WHERE reason_category = 'Queja' GROUP BY 1 ORDER BY 1""").fetchall()
        p = con.execute("""SELECT count(*), avg((sla_breached = 'True')::INT),
                median(resolution_days::DOUBLE) FILTER (WHERE resolution_days IS NOT NULL),
                avg((resolution_days IS NOT NULL)::INT)
            FROM raw_complaints WHERE subcategory = 'Cargo no reconocido'""").fetchone()
    except duckdb.Error:
        return None
    finally:
        con.close()
    return {"n": r[0], "fcr": r[1], "escalated": r[2], "followup": r[3], "dur_p50": r[4], "dur_p95": r[5],
            "wait_p50": r[6], "from": r[7], "to": r[8], "by_accent": acc,
            "pqr_n": p[0], "pqr_sla": p[1], "pqr_days": p[2] or 0, "pqr_resolved": p[3]}


def evaluate(db: str, cases: list[dict], systems: list[str], repeats: int = 1, progress: bool = False) -> dict:
    """Corre cada sistema `repeats` veces sobre los casos. Devuelve puntajes y resultados por corrida."""
    main = [c for c in cases if c["suite"] == "main"]
    fair = [c for c in cases if c["suite"] == "fairness"]
    out = {}
    for name in systems:
        factory = get_system(name)
        runs, fair_runs, results = [], [], []
        for k in range(1, repeats + 1):
            rs = []
            for i, c in enumerate(main + fair, 1):
                rs.append(run_case(c, db, factory, run=k))
                if progress and i % 50 == 0:
                    print(f"  {name} corrida {k}: {i}/{len(main) + len(fair)}", file=sys.stderr)
            by = {c["id"]: c for c in cases}
            scores = [M.score_case(by[r["case_id"]], r) for r in rs]
            runs.append([s for s, c in zip(scores, main + fair) if c["suite"] == "main"])
            fair_runs.append([s for s, c in zip(scores, main + fair) if c["suite"] == "fairness"])
            results.append(rs)
        out[factory().name] = {"describe": factory().describe(), "runs": runs, "fair_runs": fair_runs,
                     "results_run1": [r for r, c in zip(results[0], main + fair) if c["suite"] == "main"],
                     "all_results": results}
    return {"cases": main, "fair_cases": fair, "systems": out}


def main():
    ap = argparse.ArgumentParser(description="Evaluación offline sobre casos reservados")
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "serving.duckdb"))
    ap.add_argument("--cases", default=os.path.join(ROOT, "evals", "cases"))
    ap.add_argument("--split", default="test", choices=["test", "dev"])
    ap.add_argument("--system", action="append", help="nombre en SYSTEMS o paquete.modulo:fabrica (repetible)")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", default=os.path.join(ROOT, "reports", "eval.md"))
    ap.add_argument("--results", default=os.path.join(ROOT, "data", "evals", "results.json"))
    ap.add_argument("--human-db", default=os.path.join(ROOT, "data", "bank.duckdb"))
    a = ap.parse_args()
    systems = a.system or ["rules"]
    cases_path = os.path.join(a.cases, f"{a.split}.jsonl")
    cases = load(cases_path)
    with open(os.path.join(a.cases, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    with open(cases_path, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    if sha != manifest["sha256"][f"{a.split}.jsonl"]:
        print(f"ATENCIÓN: {cases_path} no coincide con el hash del manifiesto (¿se editó a mano?)", file=sys.stderr)
    ctx = evaluate(a.db, cases, systems, a.repeats, progress=True)
    import langgraph  # noqa: F401  (versión para el reporte)
    from importlib.metadata import version
    cmd = f"python -m bankagent.evals.run --split {a.split} --repeats {a.repeats} " + " ".join(f"--system {s}" for s in systems)
    ctx["meta"] = {
        "command": cmd, "git_sha": _git("rev-parse", "--short", "HEAD") or "desconocido",
        "dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "repeats": a.repeats, "manifest": manifest,
        "policy_version": PolicyEngine().version, "python": platform.python_version(),
        "langgraph": version("langgraph"), "db_name": os.path.basename(a.db), "cases_sha256": sha,
        "cases_sha_ok": sha == manifest["sha256"][f"{a.split}.jsonl"],
    }
    ctx["human"] = human_baseline(a.human_db)
    if a.split != "test":
        ctx["meta"]["command"] += "  (SPLIT DEV: no reportar)"
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(render(ctx))
    os.makedirs(os.path.dirname(os.path.abspath(a.results)), exist_ok=True)
    with open(a.results, "w", encoding="utf-8") as f:
        json.dump({"meta": ctx["meta"], "systems": {s: {"describe": v["describe"], "results": v["all_results"]}
                                                    for s, v in ctx["systems"].items()}}, f, ensure_ascii=False, default=str)
    for s, v in ctx["systems"].items():
        agg = M.aggregate(v["runs"][0])
        print(f"{s}: correctos {agg['correct']}/{agg['n']} · RAS {agg['sar']}/{agg['in_scope']} · "
              f"inseguros {agg['unsafe_any']} · reporte {a.out}")


if __name__ == "__main__":
    main()
