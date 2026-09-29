"""Despliega la demo web en un Hugging Face Space (Docker). Reproducible: cualquiera del equipo con acceso lo corre.

    hf auth login                                   # una vez, token con permiso de escritura (nunca en el repo)
    python scripts/deploy_hf.py [--space mrpercival/agente-disputas] [--db data/demo/demo.duckdb] [--dry-run]

Qué sube: solo el contexto que usa el Dockerfile (pyproject, src/, config/, docker/, web/ sin node_modules ni dist,
docs/demo/demo_customers.json) + la base de demo horneada en docker/demo-db/demo.duckdb + un README con la
cabecera que exige Spaces (sdk: docker, app_port). Nada de data/ crudo, .env, PDFs, reports ni tests.
El Space construye la misma imagen que la CI (job `image`).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INCLUDE_PREFIXES = ("src/", "config/", "docker/", "web/")
INCLUDE_FILES = ("pyproject.toml", "Dockerfile", ".dockerignore", "docs/demo/demo_customers.json")
EXCLUDE_PARTS = ("node_modules/", "web/dist/", "__pycache__/", ".duckdb.wal")

SPACE_README = """---
title: Agente de disputas de cargos no reconocidos
emoji: 🏦
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
short_description: Factored AI & Data Hackathon 2026 — disputas es/pt
---

# Agente de disputas de cargos no reconocidos (demo)

Sandbox del **Factored AI & Data Hackathon 2026**: un agente que atiende cargos no reconocidos y cobros
indebidos en español y portugués. El modelo interpreta y redacta; **el código decide y actúa** (permisos por
sesión, política versionada, confirmación y verificación de cada acción, handoff con contexto completo).

- Datos **sintéticos** del organizador · política **sintética** · no mueve dinero.
- Modo reglas (sin LLM): cero costo por conversación.
- Cada sesión de demo es independiente: elegí un escenario a la izquierda o escribí libremente.

Código fuente, evaluación y documentación: repositorio del equipo en GitHub.
"""


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines()
            if (f.startswith(INCLUDE_PREFIXES) or f in INCLUDE_FILES) and not any(x in f for x in EXCLUDE_PARTS)]


def stage(db: str) -> str:
    tmp = tempfile.mkdtemp(prefix="hf-space-")
    for f in tracked_files():
        dst = os.path.join(tmp, f)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, f), dst)
    if not os.path.exists(db):
        raise SystemExit(f"No existe la base de demo {db}: construirla con el pipeline (ver README, #28).")
    os.makedirs(os.path.join(tmp, "docker", "demo-db"), exist_ok=True)
    shutil.copy2(db, os.path.join(tmp, "docker", "demo-db", "demo.duckdb"))
    with open(os.path.join(tmp, "README.md"), "w", encoding="utf-8") as f:
        f.write(SPACE_README)
    return tmp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default="mrpercival/agente-disputas")
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "demo", "demo.duckdb"))
    ap.add_argument("--dry-run", action="store_true", help="solo arma el contexto y lista lo que subiría")
    a = ap.parse_args()
    tmp = stage(a.db)
    files = [os.path.relpath(os.path.join(d, f), tmp).replace(os.sep, "/") for d, _, fs in os.walk(tmp) for f in fs]
    size = sum(os.path.getsize(os.path.join(tmp, f)) for f in files) / 1e6
    print(f"{len(files)} archivos · {size:.1f} MB · {tmp}")
    if a.dry_run:
        print("\n".join(sorted(files)[:40]), "\n...")
        return
    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(a.space, repo_type="space", space_sdk="docker", exist_ok=True, private=False)
    api.upload_folder(folder_path=tmp, repo_id=a.space, repo_type="space", delete_patterns=["*"],
                      commit_message=f"deploy {subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()}")
    print(f"-> https://huggingface.co/spaces/{a.space}  (la app: https://{a.space.replace('/', '-')}.hf.space)")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
