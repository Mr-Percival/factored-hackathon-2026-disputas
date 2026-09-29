"""Acuerdo entre evaluadores e intervalos, sin dependencias (pocas líneas, verificadas contra valores publicados).

- `krippendorff_alpha`: niveles nominal / ordinal / interval, admite datos faltantes (Krippendorff 2011,
  "Computing Krippendorff's Alpha-Reliability": matriz de coincidencias y métricas δ²).
- `fleiss_kappa`: N sujetos × categorías, mismo número de evaluadores por sujeto (Fleiss 1971).
- `cohen_kappa`: dos evaluadores; `mean_pairwise_cohen` promedia todos los pares.
- `bootstrap_mean_ci`: IC percentil remuestreando UNIDADES (paquetes), no calificaciones sueltas.

Los tests comparan con valores calculados a mano y con los ejemplos publicados (tests/test_human_eval.py).
"""
from __future__ import annotations

import itertools
import random
from collections import Counter, defaultdict
from typing import Hashable, Iterable, Sequence


def krippendorff_alpha(units: Iterable[Sequence], level: str = "ordinal") -> float | None:
    """`units`: por unidad, los valores de cada evaluador (None = faltante). Devuelve None si no es computable
    (menos de 2 valores apareables o sin variación esperada)."""
    coinc: dict[tuple, float] = defaultdict(float)
    for u in units:
        vals = [v for v in u if v is not None]
        m = len(vals)
        if m < 2:
            continue
        for i, j in itertools.permutations(range(m), 2):
            coinc[(vals[i], vals[j])] += 1 / (m - 1)
    if not coinc:
        return None
    cats = sorted({c for c, _ in coinc})
    n_c = {c: sum(v for (a, _), v in coinc.items() if a == c) for c in cats}
    n = sum(n_c.values())
    if n <= 1:
        return None

    def delta(c, k) -> float:
        if c == k:
            return 0.0
        if level == "nominal":
            return 1.0
        if level == "interval":
            return float(c - k) ** 2
        if level == "ordinal":
            lo, hi = sorted((c, k))
            s = sum(n_c[g] for g in cats if lo <= g <= hi)
            return (s - (n_c[lo] + n_c[hi]) / 2) ** 2
        raise ValueError(f"nivel desconocido: {level}")

    d_o = sum(v * delta(c, k) for (c, k), v in coinc.items()) / n
    d_e = sum(n_c[c] * n_c[k] * delta(c, k) for c in cats for k in cats) / (n * (n - 1))
    return None if d_e == 0 else 1 - d_o / d_e


def fleiss_kappa(table: Sequence[Sequence[int]]) -> float | None:
    """`table[i][j]`: cuántos evaluadores pusieron al sujeto i en la categoría j (misma suma por fila)."""
    if not table:
        return None
    n = sum(table[0])
    if n < 2 or any(sum(r) != n for r in table):
        raise ValueError("Fleiss requiere el mismo número (>=2) de evaluadores por sujeto")
    big_n = len(table)
    p_i = [(sum(x * x for x in r) - n) / (n * (n - 1)) for r in table]
    p_bar = sum(p_i) / big_n
    p_j = [sum(r[j] for r in table) / (big_n * n) for j in range(len(table[0]))]
    p_e = sum(p * p for p in p_j)
    return None if p_e == 1 else (p_bar - p_e) / (1 - p_e)


def cohen_kappa(a: Sequence[Hashable], b: Sequence[Hashable]) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return None
    n = len(pairs)
    p_o = sum(x == y for x, y in pairs) / n
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    p_e = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return None if p_e == 1 else (p_o - p_e) / (1 - p_e)


def mean_pairwise_cohen(by_rater: dict[str, dict[str, Hashable]]) -> float | None:
    """`by_rater[rater][unit] = valor`. Promedio de Cohen sobre todos los pares con unidades en común."""
    ks = []
    for r1, r2 in itertools.combinations(sorted(by_rater), 2):
        common = sorted(set(by_rater[r1]) & set(by_rater[r2]))
        k = cohen_kappa([by_rater[r1][u] for u in common], [by_rater[r2][u] for u in common])
        if k is not None:
            ks.append(k)
    return sum(ks) / len(ks) if ks else None


def bootstrap_mean_ci(groups: Sequence[Sequence[float]], reps: int = 2000, seed: int = 0,
                      level: float = 0.95) -> tuple[float, float, float] | None:
    """Media de todas las calificaciones e IC percentil remuestreando grupos (un grupo = un paquete)."""
    groups = [list(g) for g in groups if g]
    if not groups:
        return None
    flat = [x for g in groups for x in g]
    mean = sum(flat) / len(flat)
    rng = random.Random(seed)
    stats = []
    for _ in range(reps):
        sample = [x for g in (rng.choice(groups) for _ in groups) for x in g]
        stats.append(sum(sample) / len(sample))
    stats.sort()
    lo = stats[int((1 - level) / 2 * reps)]
    hi = stats[min(reps - 1, int((1 + level) / 2 * reps))]
    return mean, lo, hi


def interpret_alpha(a: float | None) -> str:
    """Umbrales de Krippendorff (2004): >= 0.800 fiable; >= 0.667 conclusiones provisionales."""
    if a is None:
        return "no computable"
    return "fiable" if a >= 0.8 else "provisional" if a >= 0.667 else "insuficiente"
