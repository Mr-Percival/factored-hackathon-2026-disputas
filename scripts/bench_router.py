"""Memoria (RSS) y latencia por turno del agente con cada router, en un proceso limpio por router.

    PYTHONPATH=src python scripts/bench_router.py --db data/demo/demo.duckdb        # rules vs embeddings (lite)
    PYTHONPATH=src python scripts/bench_router.py --routers rules,embeddings,embeddings_full --threads 1

Pensado para el deploy gratuito (512 MB de RAM, 0.1 CPU): mide el proceso completo (import + base + agente),
no solo el modelo. Con 0.1 CPU la latencia real es ~10× la medida aquí en un núcleo completo.
Imprime una tabla Markdown y escribe reports/router_bench.json.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESSAGES = [  # primeros mensajes variados (es-MX/CO/AR, pt-BR); no salen de ningún conjunto de evaluación
    "No reconozco un cargo de 350 pesos de ayer", "me cobraron dos veces en el super", "perdí mi tarjeta",
    "quiero hablar con un asesor", "cuál es mi saldo?", "gracias, eso es todo", "hola",
    "Não reconheço uma cobrança de R$ 89,90", "me hackearon la cuenta y cambiaron la clave",
    "¿en qué va mi reclamo DSP-12345?", "che, me robaron la billetera, bloqueá la tarjeta",
    "quiero cancelar la disputa, ya reconocí el cargo", "tengo un cobro raro de netflix",
    "quero bloquear meu cartão", "necesito un préstamo", "no fui yo el que compró eso de 1.200",
]


def rss_mb() -> float:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return c.WorkingSetSize / 1e6
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1e3
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e3


def child(router: str, db: str, customer: str) -> dict:
    t0 = time.perf_counter()
    base = rss_mb()
    from bankagent.factory import build_agent
    from bankagent.identity import IdentityService
    identity = IdentityService()
    agent = build_agent(db, router=router, identity=identity)
    token = identity.login(customer)
    agent.chat("warm", token, "hola")  # carga perezosa del modelo en el primer turno
    ready_s, ready_rss = time.perf_counter() - t0, rss_mb()
    ms = []
    for rep in range(3):
        for i, m in enumerate(MESSAGES):
            t = time.perf_counter()
            agent.chat(f"t{rep}-{i}", token, m)
            ms.append((time.perf_counter() - t) * 1000)
    ms.sort()
    und = [e for e in agent.chat("probe", token, MESSAGES[0])["trace"] if e["node"] == "understand"][0]
    return {"router": router, "router_used": und["detail"], "rss_start_mb": round(base, 1),
            "rss_ready_mb": round(ready_rss, 1), "rss_end_mb": round(rss_mb(), 1), "ready_s": round(ready_s, 2),
            "turn_p50_ms": round(ms[len(ms) // 2], 2), "turn_p95_ms": round(ms[int(len(ms) * 0.95)], 2),
            "turns": len(ms)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "demo" / "demo.duckdb"))
    ap.add_argument("--customer", default="CLI-ZT72318S7XDV")
    ap.add_argument("--routers", default="rules,embeddings")
    ap.add_argument("--child", default=None)
    ap.add_argument("--threads", default="1", help="OMP/BLAS/ORT threads (el deploy tiene 0.1 CPU)")
    a = ap.parse_args()
    if a.child:
        print(json.dumps(child(a.child, a.db, a.customer)))
        return
    env = {**os.environ, "OMP_NUM_THREADS": a.threads, "OPENBLAS_NUM_THREADS": a.threads, "MKL_NUM_THREADS": a.threads,
           "PYTHONPATH": str(ROOT / "src")}
    rows = []
    for r in a.routers.split(","):
        out = subprocess.run([sys.executable, __file__, "--child", r, "--db", a.db, "--customer", a.customer],
                             capture_output=True, text=True, env=env, check=True)
        rows.append(json.loads(out.stdout.strip().splitlines()[-1]))
    print("| router | usado | RSS listo (MB) | RSS tras 48 turnos (MB) | listo en (s) | turno p50 / p95 (ms) |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['router']} | {r['router_used'].split('router=')[-1]} | {r['rss_ready_mb']} | {r['rss_end_mb']} | "
              f"{r['ready_s']} | {r['turn_p50_ms']} / {r['turn_p95_ms']} |")
    (ROOT / "reports" / "router_bench.json").write_text(json.dumps(
        {"db": Path(a.db).name, "platform": sys.platform, "python": sys.version.split()[0], "rows": rows},
        indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
