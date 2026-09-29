"""Log estructurado de la traza: una línea JSON por nodo ejecutado.

Apagado por defecto. Se activa con la variable de entorno BANKAGENT_LOG_JSON=1 y escribe en el logger
`bankagent.trace` (stderr si nadie configuró handlers). Pensado para que un colector (CloudWatch, Loki,
Datadog...) lo ingiera sin parsers: las métricas de docs/operations.md salen de estos campos.

Qué NO se loguea: el texto del cliente, el token de sesión ni los argumentos de las herramientas. La entrada
de traza ya viene sin ellos (nodo, ms, siguiente nodo, detalle, herramienta/ok/intento/ms/error).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time

logger = logging.getLogger("bankagent.trace")
# Telemetría del modelo (llm.telemetry): alimenta fallback LLM->reglas, latencia, tokens y costo.
LLM_FIELDS = ("component", "provider", "model", "prompt_version", "attempts", "errors", "fallback",
              "input_tokens", "output_tokens", "cost_usd", "latency_ms")


def enabled() -> bool:
    return os.environ.get("BANKAGENT_LOG_JSON", "") not in ("", "0", "false", "False")


def emit(entry: dict) -> None:
    """Emite una entrada de traza del grafo como una línea JSON (no hace nada si está apagado)."""
    if not enabled():
        return
    if not logger.handlers and not logging.getLogger().handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    tools = entry.get("tools") or []
    llm = entry.get("llm")
    if llm:  # solo campos operativos; `violations` puede citar texto del modelo: se loguea la cantidad
        llm = {**{k: llm.get(k) for k in LLM_FIELDS if k in llm}, "violations": len(llm.get("violations") or [])}
    logger.info(json.dumps({
        "ts": round(time.time(), 3), "event": "node", "service": "bankagent", "pid": os.getpid(),
        **{k: entry.get(k) for k in ("turn", "node", "ms", "next", "detail")},
        "tools": tools,
        "tool_errors": sum(1 for c in tools if not c.get("ok")),
        "retries": sum(1 for c in tools if c.get("attempt", 1) > 1),
        **({"llm": llm} if llm else {}),
    }, ensure_ascii=False, default=str))
