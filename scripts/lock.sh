#!/usr/bin/env bash
# Regenera los lockfiles con hashes (#17). Requiere uv (`pip install uv`). Resuelve para la plataforma del
# runtime (Linux x86_64, Python 3.12: imagen python:3.12-slim y ubuntu-latest), sin importar desde dónde se corra.
#
#   bash scripts/lock.sh             # respeta las versiones ya fijadas si siguen cumpliendo pyproject.toml
#   bash scripts/lock.sh --upgrade   # sube todo a lo último compatible
#
# requirements/api.lock -> imagen Docker (extras api,ml)     requirements/ci.lock -> job `test` de la CI (dev,api,ml)
set -euo pipefail
cd "$(dirname "$0")/.."
UV="${UV:-uv}"
common=(--generate-hashes --python-version 3.12 --python-platform x86_64-unknown-linux-gnu
        --custom-compile-command "bash scripts/lock.sh" --quiet "$@")
"$UV" pip compile pyproject.toml --extra api --extra ml -o requirements/api.lock "${common[@]}"
"$UV" pip compile pyproject.toml --extra dev --extra api --extra ml -o requirements/ci.lock "${common[@]}"
echo "ok: requirements/api.lock requirements/ci.lock"
