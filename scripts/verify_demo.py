"""Verifica que cada escenario de la demo da el resultado esperado sobre una base dada.

    python scripts/verify_demo.py --db data/demo/demo.duckdb [--scenarios docs/demo/demo_customers.json]
                                  [--policy config/policy.yaml] [--raw data/raw]

Corre cada conversación con el agente real (sesión nueva, ops en memoria) y compara turno a turno.
Sale con código 1 si algún escenario diverge: correrlo antes de cada demo / deploy.
Con --raw compara además la huella de la entrega con la usada al seleccionar (solo advierte).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from demo_scenarios import DEFAULT_SCENARIOS, POLICY, run_scenario, source_fingerprint  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--scenarios", default=DEFAULT_SCENARIOS)
    ap.add_argument("--policy", default=POLICY)
    ap.add_argument("--raw", default=None, help="data/raw para comparar la huella de la entrega")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with open(a.scenarios, encoding="utf-8-sig") as f:
        doc = json.load(f)
    if a.raw:
        fp = source_fingerprint(a.raw)
        changed = [t for t, v in fp.items() if v["sha256_16"] != doc["dataset_fingerprint"].get(t, {}).get("sha256_16")]
        if changed:
            print(f"AVISO: la entrega cambió ({', '.join(changed)}): volver a correr scripts/select_demo_customers.py")

    failures = 0
    print(f"{'escenario':16s} {'cliente':18s} {'esperado':34s} {'obtenido':34s} ok")
    for sc in doc["scenarios"]:
        t0 = time.perf_counter()
        ok, log = run_scenario(a.db, sc, a.policy)
        last = next((x for x in reversed(log) if "got" in x), None)
        got = last["got"] if last else {}
        exp = f"{sc['expected']['outcome']} {sc['expected']['rule'] or ''}".strip()
        obs = f"{got.get('outcome')} {got.get('rule') or got.get('handoff_reason') or ''}".strip()
        print(f"{sc['id']:16s} {sc['customer_id']:18s} {exp:34s} {obs:34s} {'OK' if ok else 'FALLA'}"
              f"  ({(time.perf_counter() - t0) * 1000:.0f} ms)")
        if not ok:
            failures += 1
            bad = next(x for x in log if not x["ok"])
            print(f"    turno {bad['turn']} {bad.get('say')!r}: {'; '.join(bad['problems'])}")
    print(f"\n{len(doc['scenarios']) - failures}/{len(doc['scenarios'])} escenarios OK sobre {a.db}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
