"""Corrida ÚNICA del test v3 ciego (evals/cases/test_v3_blind.jsonl) contra el sistema actual.

    python -m bankagent.evals.blind --db data/serving.duckdb [--router embeddings --router rules]

El test lo escribió un autor aislado que solo leyó config/policy.yaml y consultó la base (ver su README). Se
verifica el hash congelado antes de correr; si no coincide, aborta. No se ajusta nada con estos resultados:
el reporte (reports/eval_blind_v3.md) separa el acierto crudo contra las etiquetas del autor y un análisis de
desacuerdos, que no cambia el número crudo.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import os
import subprocess

from ..factory import build_agent
from ..identity import IdentityService
from ..pipeline import ROOT
from ..tools import BankTools

CASES = os.path.join(ROOT, "evals", "cases", "test_v3_blind.jsonl")
FROZEN_SHA256 = "cec03e517347e3143d25b44fe7f1bf75b103669a44ba5869983865f23c52d20d"


def _actions(tools: BankTools, customer_id: str) -> set[str]:
    d = tools._ops_c.execute(f"SELECT count(*) FROM {tools._t_disputes} WHERE customer_id = ?", [customer_id]).fetchone()[0]
    b = tools._ops_c.execute(f"SELECT count(*) FROM {tools._t_blocks} WHERE customer_id = ?", [customer_id]).fetchone()[0]
    return ({"dispute"} if d else set()) | ({"block"} if b else set())


def _expected_actions(label: str) -> set[str]:
    return {"dispute": {"dispute"}, "block": {"block"}, "both": {"dispute", "block"}}.get(label, set())


def run_case(case: dict, db: str, router: str) -> dict:
    identity = IdentityService()
    tools = BankTools(db, identity)
    agent = build_agent(tools, router=router, writer="templates", identity=identity)
    token, thread = identity.login(case["customer_id"]), f"v3-{case['id']}"
    turns, before = [], set()
    for t in case["turns"]:
        out = agent.chat(thread, token, t["user"])
        now = _actions(tools, case["customer_id"])
        new = now - before
        before = now
        got_rule = ((out.get("handoff") or {}).get("reason")
                    or ((out.get("decision") or {}).get("rules") or [{}])[0].get("id"))
        turns.append({"expect_outcome": t["expect_outcome"], "got_outcome": out.get("outcome"),
                      "expect_rule": t.get("expect_rule"), "got_rule": got_rule,
                      "expect_action": _expected_actions(t.get("expect_action", "none")), "got_action": new,
                      "lang": out.get("lang")})
    final = turns[-1]
    unsafe = any(tt["got_action"] - tt["expect_action"] for tt in turns)  # acción que el autor no esperaba
    outcome_ok = all(tt["got_outcome"] == tt["expect_outcome"] for tt in turns)
    rule_ok = all(tt["expect_rule"] in (None, tt["got_rule"]) for tt in turns)
    actions_ok = all(tt["got_action"] == tt["expect_action"] for tt in turns)
    return {"id": case["id"], "category": case["category"], "dialect": case["dialect"], "turns": turns,
            "correct": outcome_ok and rule_ok and actions_ok, "final_outcome_ok": final["got_outcome"] == final["expect_outcome"],
            "actions_ok": actions_ok, "unsafe_extra_action": unsafe,
            "wrong_lang": any(tt["lang"] and tt["lang"] != case["language"] for tt in turns)}


def _wilson(k: int, n: int) -> str:
    if not n:
        return "—"
    z, p = 1.96, k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return f"[{100 * max(0, c - h):.0f}–{100 * min(1, c + h):.0f}%]"


def report(results: dict[str, list[dict]], sha: str, db: str) -> str:
    git = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    n = len(next(iter(results.values())))
    L = ["# Test v3 ciego: medición única", "",
         f"- Casos: **{n}** (`evals/cases/test_v3_blind.jsonl`, sha256 `{sha[:12]}…`, congelado en git antes de correr).",
         "- Autor: aislado; solo leyó `config/policy.yaml` y consultó la base. Nunca vio código, tests ni casos previos.",
         f"- Sistema: commit `{git}` · writer `templates` · sin LLM · base `{os.path.basename(db)}` · "
         f"fecha {dt.date.today().isoformat()}.",
         "- **Corrida única.** No se ajustó nada con estos resultados. Las etiquetas son del autor ciego y se reportan "
         "tal cual; el análisis de desacuerdos (abajo) no cambia el número crudo.", "",
         "## Resultado crudo contra las etiquetas del autor", "",
         "| Router | Caso correcto (todos los turnos) | Resultado final correcto | Acciones exactas | "
         "Acción no esperada | Otro idioma |", "|---|---|---|---|---|---|"]
    for r, rs in results.items():
        c = sum(x["correct"] for x in rs); f = sum(x["final_outcome_ok"] for x in rs)
        a = sum(x["actions_ok"] for x in rs); u = sum(x["unsafe_extra_action"] for x in rs)
        w = sum(x["wrong_lang"] for x in rs)
        L.append(f"| `{r}` | {c}/{n} ({100 * c / n:.0f}%) {_wilson(c, n)} | {f}/{n} | {a}/{n} | {u}/{n} | {w}/{n} |")
    L += ["", "«Acción no esperada» = el sistema abrió una disputa o bloqueó una tarjeta en un turno donde el autor "
          "no la esperaba. Es la cota superior de acciones inseguras: incluye desacuerdos de etiqueta (ver abajo).", ""]
    for r, rs in results.items():
        L += [f"## Por categoría y dialecto · `{r}`", "", "| Grupo | n | Correctos |", "|---|---|---|"]
        for key in ("category", "dialect"):
            g = collections.defaultdict(list)
            for x in rs:
                g[x[key]].append(x["correct"])
            for k, v in sorted(g.items()):
                L.append(f"| {key}={k} | {len(v)} | {sum(v)}/{len(v)} |")
        L.append("")
        L += [f"### Desacuerdos · `{r}`", "", "| Caso | Categoría | Turno | Esperado (resultado · regla · acción) | "
              "Obtenido |", "|---|---|---|---|---|"]
        for x in rs:
            if x["correct"]:
                continue
            for i, t in enumerate(x["turns"], 1):
                if (t["got_outcome"] != t["expect_outcome"] or t["expect_rule"] not in (None, t["got_rule"])
                        or t["got_action"] != t["expect_action"]):
                    L.append(f"| {x['id']} | {x['category']} | {i} | {t['expect_outcome']} · {t['expect_rule'] or '—'} · "
                             f"{','.join(sorted(t['expect_action'])) or '—'} | {t['got_outcome']} · {t['got_rule'] or '—'} · "
                             f"{','.join(sorted(t['got_action'])) or '—'} |")
        L.append("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "serving.duckdb"))
    ap.add_argument("--router", action="append", default=None)
    ap.add_argument("--out", default=os.path.join(ROOT, "reports", "eval_blind_v3.md"))
    a = ap.parse_args()
    raw = open(CASES, "rb").read()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != FROZEN_SHA256:
        raise SystemExit(f"El test v3 cambió (sha256 {sha}): no se corre sobre un test modificado.")
    cases = [json.loads(l) for l in raw.decode("utf-8").splitlines() if l.strip()]
    results = {r: [run_case(c, a.db, r) for c in cases] for r in (a.router or ["embeddings", "rules"])}
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(report(results, sha, a.db))
    raw_out = os.path.join(ROOT, "data", "evals", "blind_v3_results.json")
    os.makedirs(os.path.dirname(raw_out), exist_ok=True)
    json.dump(results, open(raw_out, "w", encoding="utf-8"), ensure_ascii=False, default=list, indent=1)
    for r, rs in results.items():
        print(f"{r}: correctos {sum(x['correct'] for x in rs)}/{len(rs)} · acción no esperada "
              f"{sum(x['unsafe_extra_action'] for x in rs)}/{len(rs)}")
    print("->", a.out)


if __name__ == "__main__":
    main()
