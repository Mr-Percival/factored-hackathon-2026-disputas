"""Conjuntos etiquetados para evaluar la detección de inyección.

Todo se descarga a una revisión FIJA del Hub (reproducible) y queda en la caché de Hugging Face,
fuera del repo. Los fixtures del equipo (portugués y dominio bancario) sí viven en el repo porque
son pequeños, los escribimos nosotros y están marcados como tales.

Roles:
- dev  : solo para elegir umbrales. Nunca se reportan resultados finales sobre él.
- test : se reporta. Ninguna decisión (umbral, patrón, modelo) se toma mirando estos datos.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from ..pipeline import ROOT

FIXTURES = os.path.join(ROOT, "evals", "fixtures")

DEEPSET = ("deepset/prompt-injections", "4f61ecb038e9c3fb77e21034b22511b523772cdd", "Apache-2.0")
EDITH = ("edithngalame/prompt-injection-en-es", "bb574ea97a6862ef2e01aa52bfcab4327c9519e5", "mixta por fila (Apache-2.0 / MIT / CC-BY-SA-3.0)")
DEEPSET_FILES = {"train": "data/train-00000-of-00001-9564e8b05b4757ab.parquet",
                 "test": "data/test-00000-of-00001-701d16158af87368.parquet"}
EDITH_SPLITS = ("train", "validation", "test", "test_heldout", "test_native_es", "test_other_lang", "eval_handwritten")

# (nombre, rol). edith/train solo se usa para detectar fuga, nunca para medir.
SETS = [
    ("edith/validation", "dev"),
    ("deepset/test", "test"),
    ("edith/test", "test"),
    ("edith/test_heldout", "test"),
    ("edith/test_native_es", "test"),
    ("edith/test_other_lang", "test"),
    ("edith/eval_handwritten", "test"),
    ("team/pt_translation", "test"),
    ("team/banking_domain", "test"),
]

_DE = re.compile(r"\b(und|der|die|das|ich|nicht|ist|wie|ein|eine|mit|für|sind|auf|zu)\b|[äöüß]", re.I)


@dataclass
class Row:
    set: str
    id: str
    text: str
    label: int
    lang: str
    family: str = ""
    origin: str = ""
    license: str = ""
    leak: str = ""  # por qué la fila podría haber sido vista en entrenamiento ("" = limpia)


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def guess_lang_deepset(text: str) -> str:
    """deepset no trae idioma: es inglés o alemán. Heurística por palabras funcionales (se declara)."""
    return "de" if len(_DE.findall(text)) >= 2 else "en"


def _parquet(repo: str, rev: str, filename: str):
    import pandas as pd
    from huggingface_hub import hf_hub_download

    return pd.read_parquet(hf_hub_download(repo, filename, repo_type="dataset", revision=rev))


def _jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_all() -> tuple[list[Row], dict]:
    """Devuelve las filas de todos los conjuntos (dev + test) y metadatos para el reporte."""
    edith = {s: _parquet(EDITH[0], EDITH[1], f"data/{s}-00000-of-00001.parquet") for s in EDITH_SPLITS}
    deepset_test = _parquet(DEEPSET[0], DEEPSET[1], DEEPSET_FILES["test"])
    edith_train = {norm(t) for t in edith["train"]["text"]}

    rows: list[Row] = []
    for i, r in enumerate(deepset_test.itertuples()):
        # El dataset EN-ES re-dividió deepset: parte de su test está en el train de EN-ES (y por lo
        # tanto en el entrenamiento del mDeBERTa). Esas filas no cuentan para comparar detectores.
        leak = "en edith/train (entrenamiento de mdeberta-en-es)" if norm(r.text) in edith_train else ""
        rows.append(Row("deepset/test", f"deepset-test-{i}", r.text, int(r.label), guess_lang_deepset(r.text),
                        "deepset", DEEPSET[0], DEEPSET[2], leak))
    for split in EDITH_SPLITS[1:]:
        for i, r in enumerate(edith[split].itertuples()):
            # protectai-v2 declara jackhhao/jailbreak-classification entre sus datos de entrenamiento.
            leak = "origen jackhhao (entrenamiento de protectai-v2)" if str(r.origin).startswith("jackhhao") else ""
            rows.append(Row(f"edith/{split}", f"edith-{split}-{i}", r.text, int(r.label), r.lang, r.family,
                            r.origin, r.license, leak))
    for name, file in (("team/pt_translation", "pt_team_translation.jsonl"), ("team/banking_domain", "banking_domain.jsonl")):
        for r in _jsonl(os.path.join(FIXTURES, file)):
            rows.append(Row(name, r["id"], r["text"], int(r["label"]), r["lang"], r.get("family", ""),
                            r.get("source", "equipo"), "equipo (este repo)"))
    meta = {"deepset": DEEPSET, "edith": EDITH, "edith_train_rows": len(edith["train"])}
    return rows, meta


def role(set_name: str) -> str:
    return dict(SETS)[set_name]
