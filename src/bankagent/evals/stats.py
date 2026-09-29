"""Agregación de resultados del replay: tasas con IC, cuantiles, desgloses y acuerdo contra el histórico.

Funciones puras (sin base ni agente) para poder probarlas sobre listas chicas. Sin numpy/scipy: el acuerdo
se contrasta con una prueba de permutación sembrada en vez de una distribución asintótica.
"""
from __future__ import annotations

import math
import random
from collections import Counter

GROUPS = ("auto_resolved", "handoff", "rejected", "informed", "not_identified", "wrong_txn", "other", "unmatched")


def group_of(final_class: str) -> str:
    g = final_class.split(":", 1)[0]
    return g if g in GROUPS else "other"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "p": k / n if n else float("nan"), "lo": lo, "hi": hi}


def quantile(xs: list[float], q: float) -> float:
    """Cuantil con interpolación lineal (igual que numpy 'linear')."""
    if not xs:
        return float("nan")
    s = sorted(xs)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def aggregate(results: list[dict]) -> dict:
    """Métricas de la simulación sobre UNA conversación por queja (resultados del idioma principal)."""
    n = len(results)
    attempted = [r for r in results if r["final_group"] != "unmatched"]
    groups = Counter(r["final_group"] for r in results)
    by_class = Counter(r["final_class"] for r in results)
    safe = sum(1 for r in results if r.get("safe"))
    turns = [r["turns"] for r in attempted]
    clar = [r["clarify_turns"] for r in attempted]
    turn_ms = [ms for r in attempted for ms in r["turn_ms"]]
    case_ms = [sum(r["turn_ms"]) for r in attempted]
    return {
        "n": n,
        "attempted": rate(len(attempted), n),
        "safe_auto_of_all": rate(safe, n),
        "safe_auto_of_attempted": rate(safe, len(attempted)),
        "groups": {g: rate(groups.get(g, 0), n) for g in GROUPS
                   if groups.get(g, 0) or g in ("auto_resolved", "handoff", "rejected", "not_identified", "wrong_txn", "unmatched")},
        # acciones inseguras: decidir sobre otro cargo, o reportar una acción sin confirmación o sin verificación
        "unsafe": rate(sum(1 for r in results if r["final_class"] in ("wrong_txn", "other:resolved_unverified")
                           or (r.get("dispute_opened") and not r.get("confirmation_asked"))), n),
        "classes": dict(by_class.most_common()),
        "handoff_by_rule": {c.split(":", 1)[1]: rate(k, n) for c, k in by_class.items() if c.startswith("handoff:")},
        "reject_by_rule": {c.split(":", 1)[1]: rate(k, n) for c, k in by_class.items() if c.startswith(("rejected:", "informed:"))},
        "turns": {"mean": sum(turns) / len(turns) if turns else float("nan"), "p50": quantile(turns, .5), "p95": quantile(turns, .95),
                  "max": max(turns) if turns else float("nan")},
        "clarify": {"mean": sum(clar) / len(clar) if clar else float("nan"),
                    "share_with_any": rate(sum(1 for c in clar if c > 0), len(clar))},
        "latency_turn_ms": {"n": len(turn_ms), "p50": quantile(turn_ms, .5), "p95": quantile(turn_ms, .95)},
        "latency_case_ms": {"n": len(case_ms), "p50": quantile(case_ms, .5), "p95": quantile(case_ms, .95)},
    }


def breakdown(results: list[dict], key: str) -> list[dict]:
    rows = []
    for value in sorted({r.get(key) for r in results}, key=lambda v: (v is None, str(v))):
        sub = [r for r in results if r.get(key) == value]
        g = Counter(r["final_group"] for r in sub)
        rows.append({"value": value, "n": len(sub), "safe": rate(sum(1 for r in sub if r.get("safe")), len(sub)),
                     **{grp: g.get(grp, 0) / len(sub) for grp in ("handoff", "rejected", "not_identified", "unmatched")}})
    return rows


# ---------------------------------------------------------------- acuerdo con el histórico (modo sombra)
def crosstab(a: list, b: list) -> tuple[list, list, list[list[int]]]:
    ra, cb = sorted(set(a), key=str), sorted(set(b), key=str)
    m = [[0] * len(cb) for _ in ra]
    for x, y in zip(a, b):
        m[ra.index(x)][cb.index(y)] += 1
    return ra, cb, m


def cramers_v(a: list, b: list) -> float:
    ra, cb, m = crosstab(a, b)
    n = len(a)
    if n == 0 or len(ra) < 2 or len(cb) < 2:
        return 0.0
    rs, cs = [sum(r) for r in m], [sum(c) for c in zip(*m)]
    chi2 = sum((m[i][j] - rs[i] * cs[j] / n) ** 2 / (rs[i] * cs[j] / n)
               for i in range(len(ra)) for j in range(len(cb)) if rs[i] and cs[j])
    return math.sqrt(chi2 / (n * (min(len(ra), len(cb)) - 1)))


def kappa(a: list[bool], b: list[bool]) -> dict:
    """Acuerdo observado, esperado por azar (marginales) y kappa de Cohen para dos etiquetas binarias."""
    n = len(a)
    if n == 0:
        return {"n": 0, "p_o": float("nan"), "p_e": float("nan"), "kappa": float("nan")}
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return {"n": n, "p_o": po, "p_e": pe, "kappa": (po - pe) / (1 - pe) if pe < 1 else 0.0,
            "p_a": pa, "p_b": pb, "both": sum(1 for x, y in zip(a, b) if x and y)}


def permutation_p(stat, a: list, b: list, n_perm: int = 2000, seed: int = 7) -> float:
    """P(estadístico >= observado | independencia): se permutan las etiquetas históricas."""
    rng = random.Random(seed)
    obs = stat(a, b)
    bb = list(b)
    hits = 0
    for _ in range(n_perm):
        rng.shuffle(bb)
        if stat(a, bb) >= obs - 1e-12:
            hits += 1
    return (hits + 1) / (n_perm + 1)
