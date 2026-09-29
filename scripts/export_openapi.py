"""Exporta el esquema OpenAPI de la API a web/src/api/openapi.json (fuente de los tipos del frontend).

    python scripts/export_openapi.py          # escribe el archivo
    python scripts/export_openapi.py --check  # falla (código 1) si el archivo commiteado está desactualizado

Después: `cd web && npm run gen:api` regenera `src/api/schema.d.ts` con openapi-typescript.
`tests/test_api.py::test_committed_openapi_matches_the_app` corre el mismo chequeo en CI.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
OUT = os.path.join(ROOT, "web", "src", "api", "openapi.json")


def render() -> str:
    from bankagent.api.config import Settings
    from bankagent.api.main import create_app

    schema = create_app(Settings(web_dist=os.devnull)).openapi()  # sin lifespan: no construye la base
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    text = render()
    if a.check:
        with open(OUT, encoding="utf-8") as f:
            ok = f.read() == text
        print("openapi.json al día" if ok else "openapi.json DESACTUALIZADO: corre python scripts/export_openapi.py")
        return 0 if ok else 1
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"escrito {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
