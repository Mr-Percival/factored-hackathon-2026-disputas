"""Healthcheck de la demo web.

    python -m bankagent.app_health                       # offline: base + agente responden un turno
    python -m bankagent.app_health --url http://localhost:8501   # servidor: /_stcore/health de Streamlit

Sale con código 0 si está sano y 1 si no (sirve para HEALTHCHECK de Docker o el check de la plataforma).
"""
from __future__ import annotations

import argparse
import sys
import urllib.request


def check_server(url: str, timeout: float = 5.0) -> bool:
    with urllib.request.urlopen(url.rstrip("/") + "/_stcore/health", timeout=timeout) as r:
        return r.status == 200 and r.read().decode().strip() == "ok"


def check_agent() -> bool:
    from . import ui

    db, _ = ui.resolve_db_path()
    s = ui.new_session(db, ui.SCENARIOS[0].customer_id)
    return bool(s.send("hola").get("reply"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="URL base del servidor Streamlit")
    a = ap.parse_args()
    try:
        ok = check_server(a.url) if a.url else check_agent()
    except Exception as e:  # cualquier falla = no sano
        print(f"unhealthy: {e}")
        return 1
    print("ok" if ok else "unhealthy")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
