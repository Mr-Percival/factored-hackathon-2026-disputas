"""Prueba de carga / capacidad del agente (línea base de reglas, SIN LLM) sobre la base serving real.

    python scripts/loadtest.py                                   # barrido 1,4,8,16,32 hilos, 20 s por nivel
    python scripts/loadtest.py --concurrency 1,8 --seconds 10 --db data/serving.duckdb --out reports/capacity_results.json
    python scripts/loadtest.py --mode processes --concurrency 1,4,8   # réplicas en procesos (escalado horizontal)

Cada trabajador simula conversaciones completas de clientes reales de la base, con una mezcla de:
  disputa por monto (40%) · disputa ambigua -> elige opción -> confirma (25%) · bloqueo de tarjeta (20%) ·
  fuera de alcance (15%); ~20% en portugués. El trabajador responde a lo que pide el agente
  ("¿cuál?" -> "la 1"; "¿confirmas?" -> "sí"), igual que un cliente.

Mide por nivel de concurrencia: turnos/s, latencia por turno (p50/p95/p99), latencia por nodo y por herramienta
(desde la traza del grafo), tasa de error (excepciones no controladas), outcomes y memoria pico del proceso.

Modos:
  threads   (por defecto) un solo Agent/BankTools compartido por N hilos: así correría UN proceso del servicio.
  processes N procesos, cada uno con su Agent (= N réplicas sin estado leyendo la misma base de solo lectura).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import multiprocessing as mp
import os
import platform
import random
import statistics
import sys
import threading
import time
import traceback
import uuid
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import duckdb  # noqa: E402

from bankagent.graph import DISPUTABLE_TYPES, Agent  # noqa: E402
from bankagent.identity import IdentityService  # noqa: E402
from bankagent.policy import PolicyEngine  # noqa: E402
from bankagent.tools import BankTools  # noqa: E402

MIX = [("dispute_amount", 0.40), ("dispute_ambiguous", 0.25), ("block_card", 0.20), ("out_of_scope", 0.15)]
OPENERS = {
    "es": {"dispute_amount": "No reconozco un cargo de {amount}", "dispute_ambiguous": "Me cobraron algo que no reconozco",
           "block_card": "Quiero bloquear mi tarjeta", "out_of_scope": "Quiero pedir un préstamo hipotecario"},
    "pt": {"dispute_amount": "Não reconheço uma cobrança de {amount}", "dispute_ambiguous": "Tenho uma cobrança que não reconheço",
           "block_card": "Quero bloquear meu cartão", "out_of_scope": "Quero pedir um empréstimo"},
}
FOLLOW = {"es": {"option": "la 1", "confirmation": "sí"}, "pt": {"option": "a 1", "confirmation": "sim"}}
MAX_TURNS = 4


# ---------------------------------------------------------------------------- insumos
def sample_customers(db: str, n: int, as_of: dt.date, seed: int) -> list[dict]:
    """Clientes reales con una transacción disputable reciente (para 'disputa por monto')."""
    con = duckdb.connect(db, read_only=True)
    types = ", ".join(f"'{t}'" for t in sorted(DISPUTABLE_TYPES))
    rows = con.execute(f"""SELECT customer_id, amount FROM (SELECT customer_id, amount FROM transactions
        WHERE transaction_type IN ({types}) AND transaction_date >= ?::DATE - INTERVAL 90 DAY)
        USING SAMPLE reservoir({int(n)} ROWS) REPEATABLE ({int(seed)})""", [as_of]).fetchall()
    con.close()
    return [{"customer_id": c, "amount": float(a)} for c, a in rows]


def pick_scenario(rng: random.Random) -> str:
    x, acc = rng.random(), 0.0
    for name, p in MIX:
        acc += p
        if x < acc:
            return name
    return MIX[-1][0]


# ---------------------------------------------------------------------------- trabajador
class Stats:
    def __init__(self):
        self.turn_ms: list[float] = []
        self.overhead_ms: list[float] = []  # turno - suma de nodos: LangGraph, checkpointer, espera del GIL
        self.cpu_s = 0.0
        self.node_ms: dict[str, list[float]] = defaultdict(list)
        self.tool_ms: dict[str, list[float]] = defaultdict(list)
        self.outcomes: Counter = Counter()
        self.scenarios: Counter = Counter()
        self.errors: Counter = Counter()
        self.retries = 0
        self.conversations = 0

    def merge(self, o: "Stats"):
        self.turn_ms += o.turn_ms
        self.overhead_ms += o.overhead_ms
        self.cpu_s += o.cpu_s
        for k, v in o.node_ms.items():
            self.node_ms[k] += v
        for k, v in o.tool_ms.items():
            self.tool_ms[k] += v
        self.outcomes.update(o.outcomes); self.scenarios.update(o.scenarios); self.errors.update(o.errors)
        self.retries += o.retries; self.conversations += o.conversations


def conversation(agent: Agent, identity: IdentityService, cust: dict, rng: random.Random, st: Stats):
    scenario = pick_scenario(rng)
    lang = "pt" if rng.random() < 0.2 else "es"
    token, thread = identity.login(cust["customer_id"]), uuid.uuid4().hex
    text = OPENERS[lang][scenario].format(amount=f"{cust['amount']:.2f}")
    st.scenarios[scenario] += 1
    for _ in range(MAX_TURNS):
        t0 = time.perf_counter()
        try:
            r = agent.chat(thread, token, text)
        except Exception as e:  # noqa: BLE001 - una excepción no controlada ES el error que medimos
            st.errors[f"{type(e).__name__}: {str(e)[:80]}"] += 1
            return
        ms = (time.perf_counter() - t0) * 1000
        st.turn_ms.append(ms)
        st.outcomes[r["outcome"]] += 1
        entries = [e for e in r["trace"] if e["turn"] == r["turn"]]
        st.overhead_ms.append(ms - sum(e["ms"] for e in entries))
        for e in entries:
            st.node_ms[e["node"]].append(e["ms"])
            for c in e["tools"]:
                if c.get("ms") is not None:
                    st.tool_ms[c["tool"]].append(c["ms"])
                if c.get("attempt", 1) > 1:
                    st.retries += 1
        awaiting = agent.graph.get_state({"configurable": {"thread_id": thread}}).values.get("awaiting")
        if awaiting not in FOLLOW[lang]:
            break
        text = FOLLOW[lang][awaiting]
    st.conversations += 1


def run_worker(agent, identity, customers, seed, deadline, st: Stats):
    rng = random.Random(seed)
    while time.perf_counter() < deadline:
        conversation(agent, identity, rng.choice(customers), rng, st)


def build_agent(db: str) -> tuple[Agent, IdentityService]:
    identity = IdentityService(ttl_seconds=3600)
    return Agent(BankTools(db, identity), PolicyEngine()), identity


def _proc_main(args):
    db, customers, seed, seconds, warmup = args
    agent, identity = build_agent(db)
    st = Stats()
    run_worker(agent, identity, customers, seed, time.perf_counter() + warmup, Stats())
    c0 = time.process_time()
    run_worker(agent, identity, customers, seed + 1, time.perf_counter() + seconds, st)
    st.cpu_s = time.process_time() - c0
    return st, peak_rss_mb()


# ---------------------------------------------------------------------------- medición
def peak_rss_mb() -> float | None:
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
            k32 = ctypes.WinDLL("kernel32")
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
            k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
            return pmc.PeakWorkingSetSize / 2**20
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: KiB
    except Exception:  # noqa: BLE001
        return None


def pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))], 2)


def summarize(st: Stats, level: int, seconds: float, rss: float | None) -> dict:
    turns = len(st.turn_ms)
    attempts = turns + sum(st.errors.values())
    lat = lambda xs: {"n": len(xs), "p50": pct(xs, 50), "p95": pct(xs, 95), "p99": pct(xs, 99),  # noqa: E731
                      "mean": round(statistics.fmean(xs), 2) if xs else None}
    return {
        "concurrency": level, "seconds": seconds, "conversations": st.conversations, "turns": turns,
        "turns_per_s": round(turns / seconds, 1), "turn_ms": lat(st.turn_ms),
        "overhead_ms": lat(st.overhead_ms),
        # CPU del proceso por turno: techo teórico por núcleo = 1000 / cpu_ms_per_turn (menos sensible al ruido)
        "cpu_ms_per_turn": round(st.cpu_s * 1000 / turns, 2) if turns else None,
        "error_rate": round(sum(st.errors.values()) / attempts, 4) if attempts else 0.0,
        "errors": dict(st.errors.most_common(5)), "tool_retries": st.retries,
        "outcomes": dict(st.outcomes), "scenarios": dict(st.scenarios),
        "node_ms": {k: lat(v) for k, v in sorted(st.node_ms.items())},
        "tool_ms": {k: lat(v) for k, v in sorted(st.tool_ms.items())},
        "peak_rss_mb": round(rss, 1) if rss else None,
    }


def run_level(mode: str, db: str, customers: list[dict], level: int, seconds: float, warmup: float, seed: int,
              shared: tuple | None) -> dict:
    if mode == "processes":
        with mp.get_context("spawn").Pool(level) as pool:
            res = pool.map(_proc_main, [(db, customers, seed + 100 * i, seconds, warmup) for i in range(level)])
        st = Stats()
        for s, _ in res:
            st.merge(s)
        rss = sum(r for _, r in res if r)  # suma de réplicas
        return summarize(st, level, seconds, rss)

    agent, identity = shared
    if warmup:
        run_worker(agent, identity, customers, seed, time.perf_counter() + warmup, Stats())
    stats = [Stats() for _ in range(level)]
    deadline = time.perf_counter() + seconds
    ths = [threading.Thread(target=run_worker, args=(agent, identity, customers, seed + i, deadline, stats[i]))
           for i in range(level)]
    t0, c0 = time.perf_counter(), time.process_time()
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    elapsed = time.perf_counter() - t0
    st = Stats()
    for s in stats:
        st.merge(s)
    st.cpu_s = time.process_time() - c0
    return summarize(st, level, round(elapsed, 2), peak_rss_mb())


def machine() -> dict:
    return {"platform": platform.platform(), "python": platform.python_version(), "cpu": platform.processor(),
            "logical_cpus": os.cpu_count(), "duckdb": duckdb.__version__}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "serving.duckdb"))
    ap.add_argument("--concurrency", default="1,4,8,16,32")
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--warmup", type=float, default=2)
    ap.add_argument("--customers", type=int, default=2000)
    ap.add_argument("--mode", choices=("threads", "processes"), default="threads")
    ap.add_argument("--seed", type=int, default=19)
    ap.add_argument("--label", default="")
    ap.add_argument("--out", default=None, help="JSON con resultados (se agrega al archivo si ya existe)")
    a = ap.parse_args()

    policy = PolicyEngine()
    customers = sample_customers(a.db, a.customers, policy.as_of, a.seed)
    print(f"db={a.db} mode={a.mode} customers={len(customers)} seconds/level={a.seconds}", flush=True)
    shared = build_agent(a.db) if a.mode == "threads" else None
    results = []
    for level in [int(x) for x in a.concurrency.split(",")]:
        try:
            r = run_level(a.mode, a.db, customers, level, a.seconds, a.warmup, a.seed, shared)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            continue
        results.append(r)
        slow = max(r["node_ms"].items(), key=lambda kv: kv[1]["p95"] or 0)
        print(f"c={level:3d} turns/s={r['turns_per_s']:7.1f} p50={r['turn_ms']['p50']} p95={r['turn_ms']['p95']} "
              f"p99={r['turn_ms']['p99']} ms err={r['error_rate']:.2%} cpu/turn={r['cpu_ms_per_turn']} ms "
              f"overhead_p50={r['overhead_ms']['p50']} ms rss={r['peak_rss_mb']} MB "
              f"slowest_node={slow[0]}(p95 {slow[1]['p95']} ms)", flush=True)
    doc = {"label": a.label or a.mode, "mode": a.mode, "db": os.path.basename(a.db),
           "at": dt.datetime.now().isoformat(timespec="seconds"), "machine": machine(), "results": results}
    if a.out:
        prev = []
        if os.path.exists(a.out):
            with open(a.out, encoding="utf-8") as f:
                prev = json.load(f)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(prev + [doc], f, indent=1, ensure_ascii=False)
    else:
        print(json.dumps(doc, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
