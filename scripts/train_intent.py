"""Entrena y evalúa el router de intención aprendido contra RuleRouter (ADR 0007, issue #42).

    pip install -e ".[ml,ml-train]"
    PYTHONPATH=src python scripts/train_intent.py --freeze        # una sola vez: congela hashes del test
    PYTHONPATH=src python scripts/train_intent.py --stage dev     # selección: solo validación cruzada por autor
    PYTHONPATH=src python scripts/train_intent.py                 # todo: selección + test + reporte + artefactos

Protocolo (el orden importa para no filtrar el test):
1. Corpus del equipo en corpus/intent/{train,test,test_style}/author_X.jsonl. El split es por AUTOR (decidido
   antes de escribir): A, B, E entrenan; C es el test; D es el test de "estilo no visto". Una familia de
   paráfrasis pertenece a un solo autor, así que nunca cruza splits. Los hashes del test se congelan en
   corpus/intent/MANIFEST.json antes de ajustar nada y el script se niega a correr si cambiaron.
2. Selección (encoder, C, temperatura, umbral) SOLO con validación cruzada dejando un autor afuera sobre
   train: cada fold ve un autor que no vio al entrenar, igual que el test. El vocabulario de n-gramas se
   ajusta dentro de cada fold.
3. Modelo final con los tres autores de train; se evalúa una vez sobre test y test_style, contra RuleRouter.
4. Variabilidad: 5 semillas que re-entrenan con 85% de las familias; IC 95% por bootstrap de familias.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bankagent.intent_model import (ACTION_ROUTES, LABELS, ROUTE, CharNgramEncoder, IntentModel,  # noqa: E402
                                    Model2VecEncoder, OnnxEncoder, char_ngrams, ece)
from bankagent.understanding import RuleRouter  # noqa: E402

CORPUS = ROOT / "corpus" / "intent"
MANIFEST = CORPUS / "MANIFEST.json"
MODEL_DIR = ROOT / "models" / "intent_router"
REPORT = ROOT / "reports" / "intent_router.md"
RESULTS = ROOT / "reports" / "intent_router.json"
FIG_DIR = ROOT / "reports" / "figures"
TODAY = dt.date(2026, 6, 30)
DIALECTS = ("es-MX", "es-CO", "es-AR", "pt-BR", "mix")
ROUTES = ("dispute", "block", "handoff", "clarify")
# Costo de un error por ruta (fila = verdad, columna = predicción). Toda acción pide confirmación, por eso
# el máximo es acotado; el peor caso es arrancar una disputa cuando el cliente pidió un humano o reporta
# robo de cuenta (se ignora el pedido y se demora al equipo de seguridad). Pedir aclaración cuesta un turno.
COST = {"dispute": {"dispute": 0, "block": 2, "handoff": 1, "clarify": 0.5},
        "block": {"dispute": 2, "block": 0, "handoff": 1, "clarify": 0.5},
        "handoff": {"dispute": 3, "block": 2, "handoff": 0, "clarify": 0.5},
        "clarify": {"dispute": 2, "block": 2, "handoff": 1, "clarify": 0}}
TARGET_WRONG_ACTION = 0.01  # objetivo preregistrado (#42): ≤ 1% de mensajes disparan una acción equivocada
C_GRID = (0.3, 1.0, 3.0, 10.0, 30.0)
SEEDS = (0, 1, 2, 3, 4)
M2V = ("minishlab/potion-multilingual-128M", "73908c3438cf03b6a01bcb9611d62b23d0726f08")
# paraphrase-multilingual-MiniLM-L12-v2 exportado a ONNX y cuantizado (int8) por Qdrant; e5-small int8 oficial
MINILM = ("qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q", "faf4aa4225822f3bc6376869cb1164e8e3feedd0",
          "model_optimized.onnx")
E5 = ("intfloat/multilingual-e5-small", "614241f622f53c4eeff9890bdc4f31cfecc418b3", "onnx/model_qint8_avx512_vnni.onnx")
CANDIDATES = ("char", "m2v", "minilm", "e5", "char+m2v", "char+minilm")
SCRATCH = ROOT / ".cache" / "intent_emb"  # caché de embeddings (gitignored)


# ============================================================================== corpus
def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()  # independiente de CRLF/LF


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def adjudication() -> dict[str, dict]:
    """Resolución de desacuerdos entre la etiqueta del autor y la segunda anotación ciega (review/)."""
    return {r["id"]: r for r in read_jsonl(CORPUS / "review" / "adjudication.jsonl")}


def load_corpus() -> dict[str, list[dict]]:
    adj = adjudication()
    out: dict[str, list[dict]] = {}
    for split in ("train", "test", "test_style"):
        rows, seen = [], set()
        for f in sorted((CORPUS / split).glob("author_*.jsonl")):
            author = f.stem.split("_")[1]
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines()):
                if not line.strip():
                    continue
                r = json.loads(line)
                rid = f"{author}-{i + 1:04d}"
                assert r["intent"] in LABELS, (f.name, i, r["intent"])
                assert r["dialect"] in DIALECTS, (f.name, i, r["dialect"])
                author_label = r["intent"]
                if rid in adj:
                    if adj[rid]["final"] == "DROP":  # ambiguo aun con la guía: fuera del corpus
                        continue
                    r["intent"] = adj[rid]["final"]
                key = " ".join(char_ngrams(r["text"], 3, 3))
                if key in seen:  # duplicado exacto (normalizado) dentro del split
                    continue
                seen.add(key)
                rows.append({**r, "author": author, "id": rid, "split": split, "author_label": author_label,
                             "family": f"{author}:{r['family']}", "hard_negative": bool(r.get("hard_negative"))})
        out[split] = rows
    return out


def agreement() -> dict:
    """Acuerdo entre anotadores (autor vs. segunda anotación ciega), antes de adjudicar. Kappa de Cohen."""
    first = {}
    for split in ("train", "test", "test_style"):
        for f in sorted((CORPUS / split).glob("author_*.jsonl")):
            a = f.stem.split("_")[1]
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines()):
                if line.strip():
                    first[f"{a}-{i + 1:04d}"] = (split, json.loads(line)["intent"])
    adj = adjudication()
    out = {}
    for who in ("second", "third"):  # 2.ª: todo el test + muestra de train; 3.ª: submuestra de 160 del test
        other = {r["id"]: r["intent"] for r in read_jsonl(CORPUS / "review" / f"{who}_annotator.jsonl")}
        for split in ("train", "test", "test_style"):
            ids = [k for k in other if first[k][0] == split]
            if not ids:
                continue
            y1, y2 = [first[k][1] for k in ids], [other[k] for k in ids]
            po = float(np.mean([a == b for a, b in zip(y1, y2)]))
            c1, c2 = Counter(y1), Counter(y2)
            pe = sum(c1[lab] * c2[lab] for lab in LABELS) / len(ids) ** 2
            dis = [k for k in ids if first[k][1] != other[k]]
            out[f"{split} · {who}"] = {
                "n": len(ids), "agreement": po, "kappa": (po - pe) / (1 - pe), "disagreements": len(dis),
                "relabeled": sum(1 for k in dis if adj.get(k, {}).get("final") not in (None, "DROP", first[k][1])),
                "dropped": sum(1 for k in dis if adj.get(k, {}).get("final") == "DROP"),
                "kept_author": sum(1 for k in dis if adj.get(k, {}).get("final") in (None, first[k][1]))}
    return out


def near_duplicates(train: list[dict], other: list[dict], thr: float = 0.8) -> set[str]:
    """Ids de `other` casi idénticos a algún texto de train (Jaccard de trigramas ≥ thr): se excluyen del test."""
    tr = [set(char_ngrams(r["text"], 3, 3)) for r in train]
    bad = set()
    for r in other:
        g = set(char_ngrams(r["text"], 3, 3))
        if any(len(g & t) / max(1, len(g | t)) >= thr for t in tr):
            bad.add(r["id"])
    return bad


def freeze() -> None:
    files = sorted(p for s in ("test", "test_style", "review") for p in (CORPUS / s).glob("*.jsonl"))
    man = {"frozen_at": dt.datetime.now().isoformat(timespec="seconds"),
           "note": "Hashes del test congelados antes de cualquier ajuste. train_intent.py se niega a correr si cambian.",
           "test_files": {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p) for p in files}}
    MANIFEST.write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    print(f"congelado: {MANIFEST}")


def check_frozen() -> dict:
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for rel, h in man["test_files"].items():
        if sha256(ROOT / rel) != h:
            raise SystemExit(f"{rel} cambió después de congelarse: el test ya no es ciego. Abortando.")
    return man


# ============================================================================== representaciones
def fit_char(texts: list[str], n_min: int = 2, n_max: int = 5, min_df: int = 2) -> CharNgramEncoder:
    df = Counter()
    for t in texts:
        df.update(set(char_ngrams(t, n_min, n_max)))
    grams = sorted(g for g, c in df.items() if c >= min_df)
    n = len(texts)
    idf = np.array([np.log((1 + n) / (1 + df[g])) + 1 for g in grams], dtype=np.float32)
    return CharNgramEncoder({g: i for i, g in enumerate(grams)}, idf, n_min, n_max)


def make_pretrained(name: str):
    if name == "m2v":
        return Model2VecEncoder(*M2V)
    if name == "minilm":
        return OnnxEncoder(*MINILM)
    if name == "e5":
        return OnnxEncoder(*E5, prefix="query: ")
    raise ValueError(name)


class EmbCache:
    """Embeddings de encoders preentrenados (no dependen del fold): se calculan una vez por texto."""

    def __init__(self):
        self.enc, self.vecs, self.load_s = {}, {}, {}

    def get(self, name: str, texts: list[str]) -> np.ndarray:
        if name not in self.enc:
            e = make_pretrained(name)
            t0 = time.perf_counter()
            e.load()
            self.load_s[name] = time.perf_counter() - t0
            self.enc[name] = e
        store = self.vecs.setdefault(name, {})
        missing = [t for t in dict.fromkeys(texts) if t not in store]
        if missing:
            for t, v in zip(missing, self.enc[name].encode(missing)):
                store[t] = v
        return np.stack([store[t] for t in texts])


def features(cand: str, train_texts: list[str], texts: list[str], cache: EmbCache):
    """(X, encoder_para_inferencia). `char` se ajusta con train_texts (dentro del fold)."""
    parts, blocks = cand.split("+"), []
    char = fit_char(train_texts) if "char" in parts else None
    for p in parts:
        blocks.append(char.encode(texts) if p == "char" else cache.get(p, texts))
    return np.hstack(blocks), char


def fit_lr(X: np.ndarray, y: list[str], C: float, seed: int = 0):
    from sklearn.linear_model import LogisticRegression
    clf = LogisticRegression(C=C, class_weight="balanced", max_iter=5000, random_state=seed)
    clf.fit(X, y)
    order = [list(clf.classes_).index(lab) for lab in LABELS]
    return clf.coef_[order].T.astype(np.float32), clf.intercept_[order].astype(np.float32)


def softmax(z: np.ndarray, T: float = 1.0) -> np.ndarray:
    z = z / T
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


# ============================================================================== métricas
def prf(y: list[str], p: list[str], labels) -> dict:
    out = {}
    for lab in labels:
        tp = sum(a == lab and b == lab for a, b in zip(y, p))
        fp = sum(a != lab and b == lab for a, b in zip(y, p))
        fn = sum(a == lab and b != lab for a, b in zip(y, p))
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        out[lab] = {"precision": pr, "recall": rc, "f1": 2 * pr * rc / (pr + rc) if pr + rc else 0.0,
                    "support": tp + fn}
    return out


def macro_f1(y, p, labels) -> float:
    per = prf(y, p, labels)
    present = [lab for lab in labels if per[lab]["support"] > 0]
    return float(np.mean([per[lab]["f1"] for lab in present]))


def confusion(y, p, labels) -> list[list[int]]:
    idx = {lab: i for i, lab in enumerate(labels)}
    m = [[0] * len(labels) for _ in labels]
    for a, b in zip(y, p):
        m[idx[a]][idx[b]] += 1
    return m


def route_metrics(y_lab: list[str], p_lab: list[str]) -> dict:
    yr, pr = [ROUTE[a] for a in y_lab], [ROUTE[b] for b in p_lab]
    n = len(yr)
    wrong_action = sum(b in ACTION_ROUTES and a != b for a, b in zip(yr, pr))
    return {"n": n, "route_macro_f1": macro_f1(yr, pr, ROUTES), "route_accuracy": float(np.mean([a == b for a, b in zip(yr, pr)])),
            "wrong_action_rate": wrong_action / n, "wrong_action": wrong_action,
            "cost_per_msg": float(np.mean([COST[a][b] for a, b in zip(yr, pr)])),
            "clarify_rate": float(np.mean([b == "clarify" for b in pr])),
            "handoff_to_dispute": sum(a == "handoff" and b == "dispute" for a, b in zip(yr, pr))}


def label_preds(probs: np.ndarray, tau: float) -> list[str]:
    return ["unknown" if row.max() < tau else LABELS[int(row.argmax())] for row in probs]


def fit_temperature(logits: np.ndarray, y_idx: np.ndarray) -> float:
    grid = np.exp(np.linspace(np.log(0.05), np.log(10), 400))
    nll = [-np.log(softmax(logits, T)[np.arange(len(y_idx)), y_idx] + 1e-12).mean() for T in grid]
    return float(grid[int(np.argmin(nll))])


def coverage_curve(probs: np.ndarray, y_lab: list[str]) -> list[dict]:
    out = []
    for tau in np.round(np.arange(0.0, 1.0, 0.01), 2):
        pl = label_preds(probs, tau)
        acc = probs.max(axis=1) >= tau
        rm = route_metrics(y_lab, pl)
        sel = [a == b for a, b, k in zip(y_lab, pl, acc) if k]
        out.append({"tau": float(tau), "coverage": float(acc.mean()), "selective_acc": float(np.mean(sel)) if sel else 1.0,
                    **{k: rm[k] for k in ("wrong_action_rate", "cost_per_msg", "route_macro_f1")}})
    return out


def pick_threshold(curve: list[dict]) -> tuple[float, str]:
    ok = [c for c in curve if c["wrong_action_rate"] <= TARGET_WRONG_ACTION]
    if ok:
        best = max(ok, key=lambda c: (c["coverage"], -c["tau"]))
        return best["tau"], f"máxima cobertura con acción equivocada ≤ {TARGET_WRONG_ACTION:.0%} en validación"
    best = min(curve, key=lambda c: c["cost_per_msg"])
    return best["tau"], "objetivo inalcanzable en validación: mínimo costo esperado"


def bootstrap(rows: list[dict], preds: dict[str, list[str]], reps: int = 2000, seed: int = 0) -> dict:
    """IC 95% por bootstrap de FAMILIAS (las paráfrasis de una familia no son independientes)."""
    rng = np.random.default_rng(seed)
    fam = defaultdict(list)
    for i, r in enumerate(rows):
        fam[r["family"]].append(i)
    keys = list(fam)
    stats = defaultdict(list)
    for _ in range(reps):
        idx = [i for k in rng.choice(keys, len(keys)) for i in fam[k]]
        y = [rows[i]["intent"] for i in idx]
        vals = {}
        for name, p in preds.items():
            rm = route_metrics(y, [p[i] for i in idx])
            vals[name] = rm
            stats[f"{name}.route_macro_f1"].append(rm["route_macro_f1"])
            stats[f"{name}.wrong_action_rate"].append(rm["wrong_action_rate"])
            stats[f"{name}.cost_per_msg"].append(rm["cost_per_msg"])
        if "learned" in vals and "rules" in vals:
            stats["diff.route_macro_f1"].append(vals["learned"]["route_macro_f1"] - vals["rules"]["route_macro_f1"])
            stats["diff.cost_per_msg"].append(vals["learned"]["cost_per_msg"] - vals["rules"]["cost_per_msg"])
    return {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] for k, v in stats.items()}


# ============================================================================== baseline
def rules_predict(texts: list[str], min_conf: float = 0.6) -> tuple[list[str], list[float], list[float]]:
    """RuleRouter como lo usa el grafo: confianza < min_confidence (0.6) -> aclarar (unknown)."""
    rr, labs, confs, ms = RuleRouter(), [], [], []
    for t in texts:
        t0 = time.perf_counter()
        u = rr.understand(t, TODAY, None)
        ms.append((time.perf_counter() - t0) * 1000)
        labs.append(u.intent if u.confidence >= min_conf else "unknown")
        confs.append(u.confidence)
    return labs, confs, ms


# ============================================================================== selección (solo train)
def cv_select(train: list[dict], cache: EmbCache, candidates=CANDIDATES) -> dict:
    authors = sorted({r["author"] for r in train})
    texts, y = [r["text"] for r in train], [r["intent"] for r in train]
    y_idx = np.array([LABELS.index(v) for v in y])
    results = {}
    for cand in candidates:
        for C in C_GRID:
            logits = np.zeros((len(train), len(LABELS)), dtype=np.float32)
            for a in authors:
                tr = [i for i, r in enumerate(train) if r["author"] != a]
                va = [i for i, r in enumerate(train) if r["author"] == a]
                Xtr, char = features(cand, [texts[i] for i in tr], [texts[i] for i in tr], cache)
                Xva, _ = features(cand, [texts[i] for i in tr], [texts[i] for i in va], cache)
                W, b = fit_lr(Xtr, [y[i] for i in tr], C)
                logits[va] = Xva @ W + b
            pred = [LABELS[k] for k in logits.argmax(axis=1)]
            results[(cand, C)] = {"logits": logits, "macro_f1": macro_f1(y, pred, LABELS),
                                  "route_macro_f1": route_metrics(y, pred)["route_macro_f1"]}
            print(f"  cv {cand:12s} C={C:<5} macroF1={results[(cand, C)]['macro_f1']:.3f} "
                  f"rutaF1={results[(cand, C)]['route_macro_f1']:.3f}", flush=True)
    per_cand = {}
    for cand in candidates:
        bestC = max(C_GRID, key=lambda C: results[(cand, C)]["macro_f1"])
        r = results[(cand, bestC)]
        T = fit_temperature(r["logits"], y_idx)
        probs = softmax(r["logits"], T)
        correct = probs.argmax(axis=1) == y_idx
        per_cand[cand] = {"C": bestC, "macro_f1": r["macro_f1"], "route_macro_f1": r["route_macro_f1"], "T": T,
                          "ece_raw": ece(softmax(r["logits"]), correct), "ece_cal": ece(probs, correct),
                          "probs": probs}
    return per_cand


# ============================================================================== latencia y tamaño
def dir_size_mb(paths: list[Path]) -> float:
    return round(sum(p.stat().st_size for p in paths if p.is_file()) / 1e6, 1)


def pretrained_size_mb(name: str) -> float:
    """Bytes que hay que llevar a la imagen: pesos + tokenizer + config (lo que carga el encoder)."""
    from bankagent.intent_model import _snapshot
    repo, rev, weights = {"m2v": (*M2V, "model.safetensors"), "minilm": MINILM, "e5": E5}[name]
    files = [weights, "tokenizer.json", "config.json"]
    base = Path(_snapshot(repo, rev, files))
    return round(sum((base / f).stat().st_size for f in files if (base / f).exists()) / 1e6, 1)


def latency(fn, texts: list[str]) -> dict:
    fn(texts[0])
    ms = []
    for t in texts:
        t0 = time.perf_counter()
        fn(t)
        ms.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": round(float(np.percentile(ms, 50)), 3), "p95_ms": round(float(np.percentile(ms, 95)), 3)}


# ============================================================================== figuras
def figures(curves: dict, rel: dict, rules_point: dict, tau: float) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    blue, orange, ink, muted = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e"
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": muted, "axes.labelcolor": ink, "xtick.color": muted,
                         "ytick.color": muted, "axes.spines.top": False, "axes.spines.right": False})
    out = []
    fig, ax = plt.subplots(figsize=(6.4, 4))
    for split, style in (("dev", "--"), ("test", "-")):
        c = curves[split]
        ax.plot([x["coverage"] for x in c], [x["wrong_action_rate"] * 100 for x in c], style, color=blue, lw=2,
                label=f"aprendido ({'validación cruzada' if split == 'dev' else 'test'})")
    for split in ("dev", "test"):
        pt = next(x for x in curves[split] if abs(x["tau"] - tau) < 1e-9)
        ax.plot(pt["coverage"], pt["wrong_action_rate"] * 100, "o", ms=8, color=blue, mec="white", mew=2)
    ax.plot(rules_point["coverage"], rules_point["wrong_action_rate"] * 100, "s", ms=9, color=orange, mec="white",
            mew=2, label="RuleRouter (test)")
    ax.axhline(TARGET_WRONG_ACTION * 100, color=muted, lw=1, ls=":")
    ax.text(0.02, TARGET_WRONG_ACTION * 100 + 0.2, f"objetivo {TARGET_WRONG_ACTION:.0%}", color=muted, fontsize=9)
    ax.set_xlabel("Cobertura (mensajes sin abstención)")
    ax.set_ylabel("Mensajes con acción equivocada (%)")
    ax.set_title(f"Cobertura vs. acción equivocada (umbral τ={tau:.2f} marcado)", color=ink, fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    p = FIG_DIR / "intent_coverage.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    out.append(p)
    fig, ax = plt.subplots(figsize=(5, 4.2))
    ax.plot([0, 1], [0, 1], ":", color=muted, lw=1)
    for split, style in (("dev", "--"), ("test", "-")):
        b = [x for x in rel[split] if x["n"] > 0]
        ax.plot([x["conf"] for x in b], [x["acc"] for x in b], style, marker="o", ms=5, color=blue, lw=2,
                label=f"aprendido ({'validación' if split == 'dev' else 'test'})")
    ax.set_xlabel("Confianza calibrada (máx. p)")
    ax.set_ylabel("Exactitud observada")
    ax.set_title("Diagrama de confiabilidad", color=ink, fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    p = FIG_DIR / "intent_reliability.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    out.append(p)
    return [str(x.relative_to(ROOT)).replace("\\", "/") for x in out]


def reliability(probs: np.ndarray, y_idx: np.ndarray, bins: int = 10) -> list[dict]:
    conf, pred = probs.max(axis=1), probs.argmax(axis=1)
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        out.append({"lo": float(lo), "hi": float(hi), "n": int(m.sum()),
                    "conf": float(conf[m].mean()) if m.any() else None,
                    "acc": float((pred[m] == y_idx[m]).mean()) if m.any() else None})
    return out


# ============================================================================== main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true", help="congela los hashes del test (una sola vez)")
    ap.add_argument("--stage", choices=["dev", "all"], default="all")
    ap.add_argument("--candidates", default=",".join(CANDIDATES))
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if a.freeze:
        freeze()
        return
    if a.stage == "dev" and not MANIFEST.exists():  # la selección no toca el test: se puede correr antes de congelar
        man = {}
    else:
        man = check_frozen()
    np.random.seed(0)
    data = load_corpus()
    train = data["train"]
    leak = {s: near_duplicates(train, data[s]) for s in ("test", "test_style")}
    tests = {s: [r for r in data[s] if r["id"] not in leak[s]] for s in ("test", "test_style")}
    print(f"train={len(train)} test={len(tests['test'])} test_style={len(tests['test_style'])} "
          f"(excluidos por casi-duplicado: {[len(v) for v in leak.values()]})")
    cache = EmbCache()
    cands = [c for c in a.candidates.split(",") if c]
    print("== selección: validación cruzada dejando un autor afuera (solo train)")
    sel = cv_select(train, cache, cands)
    y_train = [r["intent"] for r in train]
    y_idx_train = np.array([LABELS.index(v) for v in y_train])
    dev_rules, _, _ = rules_predict([r["text"] for r in train])
    dev_rules_rm = route_metrics(y_train, dev_rules)
    table = []
    for cand, s in sel.items():
        curve = coverage_curve(s["probs"], y_train)
        tau, why = pick_threshold(curve)
        pt = next(x for x in curve if abs(x["tau"] - tau) < 1e-9)
        s.update(curve=curve, tau=tau, why=why, at_tau=pt)
        table.append((cand, s))
        print(f"  {cand:12s} C={s['C']} macroF1={s['macro_f1']:.3f} rutaF1={s['route_macro_f1']:.3f} T={s['T']:.2f} "
              f"ECE {s['ece_raw']:.3f}->{s['ece_cal']:.3f} τ={tau:.2f} cobertura={pt['coverage']:.2f} "
              f"acción_mal={pt['wrong_action_rate']:.3f} costo={pt['cost_per_msg']:.3f}")
    print(f"  rules        rutaF1={dev_rules_rm['route_macro_f1']:.3f} acción_mal={dev_rules_rm['wrong_action_rate']:.3f} "
          f"costo={dev_rules_rm['cost_per_msg']:.3f}")
    # latencia y tamaño de cada candidato (sobre textos de train: no mira el test)
    sample = [r["text"] for r in train[:200]]
    lat = {}
    for cand, s in table:
        char = fit_char([r["text"] for r in train]) if "char" in cand else None
        parts = cand.split("+")
        encs = [char if p == "char" else cache.enc.get(p) or make_pretrained(p) for p in parts]

        def enc_one(t, encs=encs):
            return np.hstack([e.encode([t]) for e in encs])
        size = sum(pretrained_size_mb(p) for p in parts if p != "char")
        lat[cand] = {**latency(enc_one, sample), "model_mb": size,
                     "load_s": round(sum(cache.load_s.get(p, 0.0) for p in parts), 2)}
        print(f"  {cand:12s} latencia {lat[cand]}")
    lat["rules"] = {**latency(lambda t: RuleRouter().understand(t, TODAY, None), sample), "model_mb": 0.0, "load_s": 0.0}
    # Regla de decisión (preregistrada en ADR 0007): mayor macro-F1 en validación; si dos candidatos están a
    # menos de 0.01, gana el más liviano (tamaño de imagen del deploy y latencia).
    best_f1 = max(s["macro_f1"] for _, s in table)
    close = [(c, s) for c, s in table if s["macro_f1"] >= best_f1 - 0.01]
    chosen, cs = min(close, key=lambda cs_: (lat[cs_[0]]["model_mb"], lat[cs_[0]]["p50_ms"]))
    print(f"== elegido: {chosen} (C={cs['C']}, T={cs['T']:.2f}, τ={cs['tau']:.2f})")
    if a.stage == "dev":
        return

    # ------------------------------------------------------------------ modelo final + test (una sola vez)
    tr_texts = [r["text"] for r in train]
    Xtr, char = features(chosen, tr_texts, tr_texts, cache)
    W, b = fit_lr(Xtr, y_train, cs["C"])
    parts = chosen.split("+")
    from bankagent.intent_model import ConcatEncoder
    encs = [char if p == "char" else cache.enc[p] for p in parts]
    encoder = encs[0] if len(encs) == 1 else ConcatEncoder(encs)
    corpus_hash = hashlib.sha256(b"".join(sha256(p).encode() for p in sorted((CORPUS / "train").glob("*.jsonl")))).hexdigest()
    model_id = {"char": "char2-5-tfidf", "m2v": f"{M2V[0]}@{M2V[1][:8]}", "minilm": f"{MINILM[0]}@{MINILM[1][:8]}",
                "e5": f"{E5[0]}@{E5[1][:8]}"}
    meta = {"version": "intent-v1", "model_id": "+".join(model_id[p] for p in parts), "candidate": chosen,
            "C": cs["C"], "corpus_sha256": corpus_hash, "train_authors": sorted({r["author"] for r in train}),
            "n_train": len(train), "trained_by": "scripts/train_intent.py", "target_wrong_action": TARGET_WRONG_ACTION,
            "threshold_rule": cs["why"], "sklearn": __import__("sklearn").__version__, "numpy": np.__version__}
    model = IntentModel(encoder, W, b, LABELS, cs["T"], cs["tau"], meta)
    # reproducibilidad del artefacto: lo que se guarda (W en float16) debe predecir igual que lo entrenado
    model.save(MODEL_DIR)
    from bankagent.intent_model import load_intent_model
    reloaded = load_intent_model(MODEL_DIR)
    res: dict = {"meta": meta, "manifest": man, "agreement": agreement(), "leak_excluded": {k: sorted(v) for k, v in leak.items()},
                 "selection": {c: {k: v for k, v in s.items() if k not in ("probs", "curve")} for c, s in table},
                 "latency": lat, "dev_rules": dev_rules_rm, "splits": {}}
    curves = {"dev": cs["curve"]}
    rel = {"dev": reliability(cs["probs"], y_idx_train)}
    for split, rows in tests.items():
        texts, y = [r["text"] for r in rows], [r["intent"] for r in rows]
        y_idx = np.array([LABELS.index(v) for v in y])
        probs = reloaded.predict_proba(texts)
        assert np.allclose(probs, model.predict_proba(texts), atol=2e-3), "artefacto guardado != modelo entrenado"
        learned = label_preds(probs, cs["tau"])
        learned_noabs = label_preds(probs, 0.0)
        rules, rules_conf, _ = rules_predict(texts)
        correct = probs.argmax(axis=1) == y_idx
        seeds = []
        for sd in SEEDS:  # variabilidad: re-entrenar con 85% de las familias de train
            rng = np.random.default_rng(sd)
            fams = sorted({r["family"] for r in train})
            keep = set(rng.choice(fams, int(0.85 * len(fams)), replace=False))
            sub = [r for r in train if r["family"] in keep]
            Xs, _ = features(chosen, [r["text"] for r in sub], [r["text"] for r in sub], cache)
            Xt, _ = features(chosen, [r["text"] for r in sub], texts, cache)
            Ws, bs = fit_lr(Xs, [r["intent"] for r in sub], cs["C"], sd)
            ps = label_preds(softmax(Xt @ Ws + bs, cs["T"]), cs["tau"])
            seeds.append({"seed": sd, "macro_f1": macro_f1(y, ps, LABELS), **route_metrics(y, ps)})
        by = {}
        for key in ("dialect", "style", "hard_negative"):
            groups = defaultdict(list)
            for i, r in enumerate(rows):
                g = r.get(key)
                g = str(g).split(",")[0].strip() if key == "style" else g
                groups[str(g)].append(i)
            by[key] = {g: {"n": len(ix),
                           "learned_acc": float(np.mean([ROUTE[learned[i]] == ROUTE[y[i]] for i in ix])),
                           "rules_acc": float(np.mean([ROUTE[rules[i]] == ROUTE[y[i]] for i in ix]))}
                       for g, ix in sorted(groups.items())}
        errors = [{"id": r["id"], "text": r["text"], "dialect": r["dialect"], "true": y[i], "learned": learned[i],
                   "p": round(float(probs[i].max()), 3), "rules": rules[i]}
                  for i, r in enumerate(rows) if ROUTE[learned[i]] != ROUTE[y[i]] or ROUTE[rules[i]] != ROUTE[y[i]]]
        res["splits"][split] = {
            "n": len(rows), "families": len({r["family"] for r in rows}),
            "counts": dict(Counter(y)),
            "learned": {"macro_f1": macro_f1(y, learned, LABELS), "per_label": prf(y, learned, LABELS),
                        "confusion": confusion(y, learned, LABELS), **route_metrics(y, learned),
                        "coverage": float((probs.max(axis=1) >= cs["tau"]).mean()),
                        "ece": ece(probs, correct), "macro_f1_no_abstention": macro_f1(y, learned_noabs, LABELS),
                        "route_no_abstention": route_metrics(y, learned_noabs)},
            "rules": {"macro_f1": macro_f1(y, rules, LABELS), "per_label": prf(y, rules, LABELS),
                      "confusion": confusion(y, rules, LABELS), **route_metrics(y, rules),
                      "coverage": float(np.mean([c >= 0.6 for c in rules_conf]))},
            "route_confusion": {"learned": confusion([ROUTE[v] for v in y], [ROUTE[v] for v in learned], ROUTES),
                                "rules": confusion([ROUTE[v] for v in y], [ROUTE[v] for v in rules], ROUTES)},
            "seeds": seeds, "ci95": bootstrap(rows, {"learned": learned, "rules": rules}),
            "by": by, "errors": errors}
        curves[split] = coverage_curve(probs, y)
        rel[split] = reliability(probs, y_idx)
        L, R = res["splits"][split]["learned"], res["splits"][split]["rules"]
        print(f"== {split}: n={len(rows)} aprendido macroF1={L['macro_f1']:.3f} rutaF1={L['route_macro_f1']:.3f} "
              f"acción_mal={L['wrong_action_rate']:.3f} costo={L['cost_per_msg']:.3f} | reglas rutaF1={R['route_macro_f1']:.3f} "
              f"acción_mal={R['wrong_action_rate']:.3f} costo={R['cost_per_msg']:.3f}")
    res["curves"] = {k: v for k, v in curves.items()}
    res["reliability"] = rel
    tR = res["splits"]["test"]["rules"]
    res["figures"] = figures(curves, rel, {"coverage": tR["coverage"], "wrong_action_rate": tR["wrong_action_rate"]}, cs["tau"])
    res["artifact_mb"] = dir_size_mb(list(MODEL_DIR.glob("*")))
    res["env"] = {"python": platform.python_version(), "machine": platform.machine(), "processor": platform.processor()}
    RESULTS.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    from intent_report import write_report  # noqa: E402 (mismo directorio)
    REPORT.write_text(write_report(res, data, tests), encoding="utf-8")
    print(f"-> {REPORT}\n-> {RESULTS}\n-> {MODEL_DIR} ({res['artifact_mb']} MB)")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
