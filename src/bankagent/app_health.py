"""Healthcheck de la demo web, sin dependencias (sirve para el HEALTHCHECK de Docker: la imagen slim no trae curl).

    python -m bankagent.app_health                               # http://127.0.0.1:$PORT/healthz
    python -m bankagent.app_health --url http://host:8000 --ready  # /readyz (base + política)

Sale con código 0 si está sano y 1 si no.
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.request


def check(url: str, ready: bool = False, timeout: float = 5.0) -> bool:
    path = "/readyz" if ready else "/healthz"
    with urllib.request.urlopen(url.rstrip("/") + path, timeout=timeout) as r:  # noqa: S310 (URL local)
        return r.status == 200


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bankagent.app_health")
    ap.add_argument("--url", default=f"http://127.0.0.1:{os.environ.get('PORT', '8000')}")
    ap.add_argument("--ready", action="store_true", help="consulta /readyz en lugar de /healthz")
    a = ap.parse_args(argv)
    try:
        ok = check(a.url, a.ready)
    except Exception as e:  # noqa: BLE001 - cualquier falla = no sano
        print(f"unhealthy: {type(e).__name__}")
        return 1
    print("ok" if ok else "unhealthy")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
