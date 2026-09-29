"""Clasificador de intención aprendido: representación (encoder) + cabeza lineal calibrada + abstención.

Solo inferencia y numpy: el entrenamiento (scikit-learn) vive en `scripts/train_intent.py`, que escribe los
artefactos en `models/intent_router/` (ver ADR 0007). Encoders disponibles:
- `char`   : TF-IDF de n-gramas de caracteres, aprendido del corpus (pesa KB, sin dependencias extra).
- `m2v`    : embeddings estáticos model2vec (`pip install -e ".[ml]"`).
- `onnx`   : sentence transformer en ONNX con onnxruntime + tokenizers (`pip install -e ".[ml]"`).
- `concat` : concatenación de dos encoders (cada bloque ya normalizado L2).
Los encoders pesados se importan y cargan de forma perezosa: importar este módulo no requiere nada más que numpy.
"""
from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

# Etiquetas que aprende el modelo. Las que el grafo todavía no conoce se traducen con COMPAT.
LABELS: tuple[str, ...] = ("dispute_charge", "block_card", "account_takeover", "human_request",
                           "out_of_scope", "closing", "unknown")
# Traducción al contrato actual del grafo (`understanding.INTENTS`): lo que cambia es la ruta, no la etiqueta.
# human_request y account_takeover -> handoff (vía out_of_scope); closing -> clarify (vía unknown).
COMPAT: dict[str, str] = {"human_request": "out_of_scope", "account_takeover": "out_of_scope", "closing": "unknown"}
# Ruta que toma el grafo para cada intención: es el espacio donde se miden los costos de error.
ROUTE: dict[str, str] = {"dispute_charge": "dispute", "block_card": "block", "account_takeover": "handoff",
                         "human_request": "handoff", "out_of_scope": "handoff", "closing": "clarify",
                         "unknown": "clarify"}
ACTION_ROUTES = ("dispute", "block")  # rutas que consultan herramientas y proponen una acción al cliente

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "models" / "intent_router"


# ---------------------------------------------------------------------------------------------- texto
def normalize(text: str) -> str:
    """Minúsculas, sin tildes, dígitos -> 0, letras repetidas acotadas ("nooooo" -> "noo"), espacios simples."""
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\d", "0", t)
    t = re.sub(r"(.)\1{2,}", r"\1\1", t)
    return re.sub(r"\s+", " ", t).strip()


def char_ngrams(text: str, n_min: int = 2, n_max: int = 5) -> list[str]:
    """N-gramas de caracteres dentro de cada palabra con bordes (como `char_wb` de scikit-learn)."""
    out: list[str] = []
    for w in normalize(text).split():
        w = f" {w} "
        for n in range(n_min, n_max + 1):
            if len(w) < n:
                break
            out.extend(w[i:i + n] for i in range(len(w) - n + 1))
    return out


# ---------------------------------------------------------------------------------------------- encoders
class Encoder(Protocol):
    name: str

    def encode(self, texts: list[str]) -> np.ndarray: ...


def _l2(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=1, keepdims=True)
    return x / np.where(n == 0, 1.0, n)


class CharNgramEncoder:
    """TF-IDF sublineal de n-gramas de caracteres + L2. El vocabulario y el idf salen del entrenamiento."""

    def __init__(self, vocab: dict[str, int], idf: np.ndarray, n_min: int = 2, n_max: int = 5):
        self.vocab, self.idf, self.n_min, self.n_max = vocab, np.asarray(idf, dtype=np.float32), n_min, n_max
        self.name = f"char{n_min}-{n_max}"
        self.dim = len(vocab)

    def encode(self, texts: list[str]) -> np.ndarray:
        x = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for g in char_ngrams(t, self.n_min, self.n_max):
                j = self.vocab.get(g)
                if j is not None:
                    x[i, j] += 1.0
        nz = x > 0
        x[nz] = 1.0 + np.log(x[nz])
        return _l2(x * self.idf)

    def spec(self) -> dict:
        return {"type": "char", "n_min": self.n_min, "n_max": self.n_max, "dim": self.dim}


class Model2VecEncoder:
    """Embeddings estáticos (model2vec): tokenizar + promedio de vectores. Sin torch, CPU, ~ms por mensaje."""

    def __init__(self, model_id: str, revision: str | None = None):
        self.model_id, self.revision = model_id, revision
        self.name = f"m2v:{model_id.split('/')[-1]}"
        self._model = None

    def load(self):
        if self._model is None:
            from model2vec import StaticModel  # dependencia opcional (grupo `ml`)
            path = _snapshot(self.model_id, self.revision, ["model.safetensors", "tokenizer.json", "config.json"])
            self._model = StaticModel.from_pretrained(path)
        return self._model

    def encode(self, texts: list[str]) -> np.ndarray:
        return _l2(np.asarray(self.load().encode(list(texts)), dtype=np.float32))

    def spec(self) -> dict:
        return {"type": "m2v", "model_id": self.model_id, "revision": self.revision}


class OnnxEncoder:
    """Sentence transformer exportado a ONNX: onnxruntime + tokenizers, promedio con máscara + L2.

    Sin torch ni sentence-transformers: ~60 MB de dependencias + el modelo. 1 hilo (latencia reproducible y
    sin competir con el resto del proceso)."""

    def __init__(self, model_id: str, revision: str | None = None, model_file: str = "model.onnx",
                 prefix: str = "", max_len: int = 128, threads: int = 1):
        self.model_id, self.revision, self.model_file = model_id, revision, model_file
        self.prefix, self.max_len, self.threads = prefix, max_len, threads
        self.name = f"onnx:{model_id.split('/')[-1]}"
        self._sess = self._tok = None

    def load(self):
        if self._sess is None:
            import onnxruntime as ort  # dependencia opcional (grupo `ml`)
            from tokenizers import Tokenizer
            path = Path(_snapshot(self.model_id, self.revision, [self.model_file, "tokenizer.json", "config.json"]))
            tok = Tokenizer.from_file(str(path / "tokenizer.json"))
            tok.enable_truncation(self.max_len)
            tok.enable_padding(pad_id=tok.token_to_id("<pad>") or 0, pad_token="<pad>")
            so = ort.SessionOptions()
            so.intra_op_num_threads = so.inter_op_num_threads = self.threads
            self._sess = ort.InferenceSession(str(path / self.model_file), so, providers=["CPUExecutionProvider"])
            self._inputs = {i.name for i in self._sess.get_inputs()}
            self._tok = tok
        return self._sess

    def encode(self, texts: list[str]) -> np.ndarray:
        sess = self.load()
        out = []
        for i in range(0, len(texts), 32):
            enc = self._tok.encode_batch([self.prefix + t for t in texts[i:i + 32]])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            h = sess.run(None, feed)[0]
            m = mask[..., None].astype(np.float32)
            out.append((h * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None))
        return _l2(np.vstack(out).astype(np.float32))

    def spec(self) -> dict:
        return {"type": "onnx", "model_id": self.model_id, "revision": self.revision, "model_file": self.model_file,
                "prefix": self.prefix, "max_len": self.max_len}


class ConcatEncoder:
    def __init__(self, parts: list):
        self.parts = parts
        self.name = "+".join(p.name for p in parts)

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.hstack([p.encode(texts) for p in self.parts])

    def load(self):
        for p in self.parts:
            getattr(p, "load", lambda: None)()

    def spec(self) -> dict:
        return {"type": "concat", "parts": [p.spec() for p in self.parts]}


def _snapshot(model_id: str, revision: str | None, patterns: list[str]) -> str:
    """Ruta local del modelo: usa la caché de Hugging Face; descarga solo si falta (y si hay red)."""
    from huggingface_hub import snapshot_download
    try:
        return snapshot_download(model_id, revision=revision, allow_patterns=patterns, local_files_only=True)
    except Exception:  # noqa: BLE001 - no está en caché: intentar descargar (falla sin red -> fallback del router)
        return snapshot_download(model_id, revision=revision, allow_patterns=patterns)


# ---------------------------------------------------------------------------------------------- modelo
@dataclass
class Prediction:
    label: str        # etiqueta más probable (antes de abstenerse)
    p: float          # probabilidad calibrada de esa etiqueta
    abstained: bool   # p < umbral elegido en validación
    probs: dict[str, float]


class IntentModel:
    """encoder -> logits lineales -> softmax(logits / T) -> abstención si max p < threshold."""

    def __init__(self, encoder, W: np.ndarray, b: np.ndarray, labels: tuple[str, ...], temperature: float = 1.0,
                 threshold: float = 0.0, meta: dict | None = None):
        self.encoder, self.W, self.b = encoder, np.asarray(W, dtype=np.float32), np.asarray(b, dtype=np.float32)
        self.labels, self.temperature, self.threshold = tuple(labels), float(temperature), float(threshold)
        self.meta = meta or {}

    @property
    def model_id(self) -> str:
        return self.meta.get("model_id", self.encoder.name)

    def logits(self, texts: list[str]) -> np.ndarray:
        return self.encoder.encode(texts) @ self.W + self.b

    def predict_proba(self, texts: list[str]) -> np.ndarray:
        z = self.logits(texts) / self.temperature
        z = z - z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)

    def predict(self, text: str) -> Prediction:
        p = self.predict_proba([text])[0]
        k = int(p.argmax())
        return Prediction(self.labels[k], float(p[k]), bool(p[k] < self.threshold),
                          {lab: round(float(v), 4) for lab, v in zip(self.labels, p)})

    def warmup(self) -> None:
        getattr(self.encoder, "load", lambda: None)()
        self.predict("hola")

    # --------------------------------------------------------------------------- persistencia
    def save(self, out_dir: str | Path, extra_meta: dict | None = None) -> None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        arrays = {"W": self.W.astype(np.float16), "b": self.b}
        char = _find_char(self.encoder)
        if char is not None:
            arrays["idf"] = char.idf.astype(np.float16)
            vocab = sorted(char.vocab, key=char.vocab.get)
            (out / "char_vocab.json").write_text(json.dumps(vocab, ensure_ascii=False), encoding="utf-8")
        np.savez_compressed(out / "head.npz", **arrays)
        meta = {**self.meta, **(extra_meta or {}), "labels": list(self.labels), "temperature": self.temperature,
                "threshold": self.threshold, "encoder": self.encoder.spec()}
        (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _find_char(enc) -> CharNgramEncoder | None:
    if isinstance(enc, CharNgramEncoder):
        return enc
    for p in getattr(enc, "parts", []):
        if isinstance(p, CharNgramEncoder):
            return p
    return None


def build_encoder(spec: dict, char: CharNgramEncoder | None = None):
    kind = spec["type"]
    if kind == "char":
        if char is None:
            raise ValueError("encoder char sin vocabulario")
        return char
    if kind == "m2v":
        return Model2VecEncoder(spec["model_id"], spec.get("revision"))
    if kind == "onnx":
        return OnnxEncoder(spec["model_id"], spec.get("revision"), spec.get("model_file", "model.onnx"),
                           spec.get("prefix", ""), spec.get("max_len", 128))
    if kind == "concat":
        return ConcatEncoder([build_encoder(p, char) for p in spec["parts"]])
    raise ValueError(f"encoder desconocido: {kind}")


def load_intent_model(model_dir: str | Path = DEFAULT_DIR) -> IntentModel:
    """Carga artefactos. Lanza excepción si faltan: el router lo convierte en fallback a reglas."""
    d = Path(model_dir)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    arr = np.load(d / "head.npz")
    char = None
    if (d / "char_vocab.json").exists():
        vocab = json.loads((d / "char_vocab.json").read_text(encoding="utf-8"))
        spec = _char_spec(meta["encoder"])
        char = CharNgramEncoder({g: i for i, g in enumerate(vocab)}, arr["idf"].astype(np.float32),
                                spec["n_min"], spec["n_max"])
    enc = build_encoder(meta["encoder"], char)
    return IntentModel(enc, arr["W"].astype(np.float32), arr["b"], tuple(meta["labels"]), meta["temperature"],
                       meta["threshold"], meta)


def _char_spec(spec: dict) -> dict:
    if spec["type"] == "char":
        return spec
    return next(p for p in spec.get("parts", []) if p["type"] == "char")


def timed(fn, *a, **k):
    t0 = time.perf_counter()
    out = fn(*a, **k)
    return out, (time.perf_counter() - t0) * 1000


def ece(probs: np.ndarray, correct: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error (bins de igual ancho sobre la confianza máxima)."""
    conf = probs.max(axis=1) if probs.ndim == 2 else probs
    edges = np.linspace(0, 1, bins + 1)
    total, n = 0.0, len(conf)
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi) if lo > 0 else (conf >= lo) & (conf <= hi)
        if m.any():
            total += m.sum() / n * abs(correct[m].mean() - conf[m].mean())
    return float(total) if not math.isnan(total) else 0.0
