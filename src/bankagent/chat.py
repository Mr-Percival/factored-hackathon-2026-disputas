"""Chat de consola para probar el agente a mano.

    python -m bankagent.chat --customer CLI-XXXX [--db data/serving.duckdb]

Comandos: /trace (traza del último turno) · /handoff (paquete) · /expire (vence la sesión) · /salir
"""
from __future__ import annotations

import argparse
import json
import os
import uuid

from .graph import Agent
from .identity import IdentityService
from .pipeline import ROOT
from .policy import PolicyEngine
from .tools import BankTools


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--customer", required=True, help="cliente con el que se simula el login en la app")
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "serving.duckdb"))
    a = ap.parse_args()
    identity = IdentityService()
    agent = Agent(BankTools(a.db, identity), PolicyEngine())
    token, thread, last = identity.login(a.customer), uuid.uuid4().hex, {}
    print(f"Sesión simulada para {a.customer}. Escribe tu mensaje (es / pt).")
    while True:
        try:
            text = input("\ncliente> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text in ("/salir", "/exit"):
            break
        if text == "/expire":
            identity.expire(token); print("(sesión vencida)"); continue
        if text == "/trace":
            turn = last.get("turn")
            for e in last.get("trace", []):
                if e["turn"] == turn:
                    print(f"  {e['node']:17s} {e['ms']:7.2f} ms -> {e['next']:17s} {e['detail'] or ''} {[c['tool'] for c in e['tools']]}")
            continue
        if text == "/handoff":
            print(json.dumps(last.get("handoff"), indent=2, ensure_ascii=False, default=str)); continue
        last = agent.chat(thread, token, text)
        print(f"agente> {last['reply']}\n        [{last['outcome']}]")


if __name__ == "__main__":
    main()
