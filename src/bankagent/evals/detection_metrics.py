"""Métricas de evaluación sin dependencias (solo stdlib), para poder testearlas en CI.

Convención: label 1 = inyección (positivo), 0 = benigno. score más alto = más sospechoso.
Una tasa sin denominador devuelve None (se reporta "n/d"), nunca 0: no inventamos precisión.
"""
from __future__ import annotations

import math
from collections.abc import Sequence


def confusion(labels: Sequence[int], preds: Sequence[bool]) -> dict:
    tp = sum(1 for y, p in zip(labels, preds) if y == 1 and p)
    fp = sum(1 for y, p in zip(labels, preds) if y == 0 and p)
    fn = sum(1 for y, p in zip(labels, preds) if y == 1 and not p)
    tn = sum(1 for y, p in zip(labels, preds) if y == 0 and not p)
    return {"n": tp + fp + fn + tn, "pos": tp + fn, "neg": fp + tn, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "tpr": _div(tp, tp + fn), "fpr": _div(fp, fp + tn), "precision": _div(tp, tp + fp)}


def _div(a: int, b: int) -> float | None:
    return a / b if b else None


def roc_auc(labels: Sequence[int], scores: Sequence[float]) -> float | None:
    """AUC = P(score positivo > score negativo), empates cuentan 1/2 (Mann-Whitney)."""
    pos = [s for y, s in zip(labels, scores) if y == 1]
    neg = [s for y, s in zip(labels, scores) if y == 0]
    if not pos or not neg:
        return None
    ranked = sorted([(s, 1) for s in pos] + [(s, 0) for s in neg])
    rank_sum, i = 0.0, 0
    while i < len(ranked):  # rangos promedio para empates
        j = i
        while j < len(ranked) and ranked[j][0] == ranked[i][0]:
            j += 1
        avg = (i + j + 1) / 2
        rank_sum += avg * sum(1 for k in range(i, j) if ranked[k][1] == 1)
        i = j
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def threshold_for_fpr(neg_scores: Sequence[float], target_fpr: float) -> float:
    """Umbral más bajo (el más sensible) tal que la FPR sobre `neg_scores` sea <= target.
    Se bloquea con score >= umbral; si ningún umbral finito cumple, devuelve +inf (no bloquear nada)."""
    neg = sorted(neg_scores, reverse=True)
    if not neg:
        raise ValueError("sin ejemplos negativos para calibrar")
    allowed = math.floor(target_fpr * len(neg) + 1e-9)  # falsos positivos permitidos
    if allowed >= len(neg):
        return min(neg)
    # Con umbral apenas por encima de neg[allowed] quedan como mucho `allowed` negativos por encima;
    # los empates con neg[allowed] quedan fuera (no se bloquean).
    return math.nextafter(neg[allowed], math.inf)


def tpr_at_fpr(labels: Sequence[int], scores: Sequence[float], target_fpr: float) -> tuple[float | None, float]:
    """(TPR, umbral) en el punto de la curva con FPR <= target. Resume la curva: NO es un punto de
    operación, porque el umbral sale del mismo conjunto que se mide."""
    neg = [s for y, s in zip(labels, scores) if y == 0]
    pos = [s for y, s in zip(labels, scores) if y == 1]
    thr = threshold_for_fpr(neg, target_fpr)
    return (_div(sum(1 for s in pos if s >= thr), len(pos)), thr)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Intervalo de Wilson al 95%. Con k=0 el límite superior dice cuánto riesgo NO podemos descartar."""
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, center - half), min(1.0, center + half))


def percentile(values: Sequence[float], q: float) -> float | None:
    """Percentil con interpolación lineal (q en [0, 100])."""
    if not values:
        return None
    v = sorted(values)
    pos = (len(v) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)
