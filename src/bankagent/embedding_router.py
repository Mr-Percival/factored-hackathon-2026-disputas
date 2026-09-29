"""HybridRouter: intención con un modelo aprendido; slots y respuestas cortas con RuleRouter.

    HybridRouter(intent_model=None, slot_extractor=RuleRouter())

División del trabajo (ADR 0007):
- Respuestas a una pregunta pendiente (`awaiting`: confirmación u opción) -> RuleRouter decide
  confirm/deny/select_option: dependen del contexto, no del texto aislado, y el modelo no las aprende.
- Todo lo demás -> el modelo clasifica la intención con probabilidad calibrada. Si la probabilidad no
  llega al umbral elegido en validación, se abstiene: `unknown` y el grafo pide aclaración.
- Slots (monto, fechas, país, opción…) e idioma -> siempre RuleRouter (deterministas y auditables).
- Si el modelo no carga (sin artefactos, sin paquete, sin caché y sin red) -> responde RuleRouter y
  `router` lo dice: `rules(fallback:model_unavailable)`.
Etiquetas que el grafo todavía no conoce se traducen con `intent_model.COMPAT` (p. ej. human_request ->
out_of_scope, que termina en handoff) salvo que ya estén en `understanding.INTENTS`.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import replace
from pathlib import Path

from .intent_model import COMPAT, DEFAULT_DIR, IntentModel, load_intent_model
from .understanding import INTENTS, Router, RuleRouter, Understanding

CONTEXT_INTENTS = ("confirm", "deny", "select_option")


class HybridRouter:
    def __init__(self, intent_model: IntentModel | None = None, slot_extractor: Router | None = None,
                 model_dir: str | Path = DEFAULT_DIR):
        self.slots = slot_extractor or RuleRouter()
        self.model_dir = Path(model_dir)
        self._model, self._error = intent_model, None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        m = self._model
        return f"embed:{m.model_id}" if m else "embed"

    def model(self) -> IntentModel | None:
        """Carga perezosa (una vez, segura entre hilos). None si no se pudo: el error queda en la traza."""
        if self._model is None and self._error is None:
            with self._lock:
                if self._model is None and self._error is None:
                    try:
                        m = load_intent_model(self.model_dir)
                        m.warmup()
                        self._model = m
                    except Exception as e:  # noqa: BLE001 - cualquier falla de carga = línea base
                        self._error = f"{type(e).__name__}: {e}"[:200]
        return self._model

    def understand(self, text: str, today: dt.date, awaiting: str | None) -> Understanding:
        base = self.slots.understand(text, today, awaiting)
        if awaiting and base.intent in CONTEXT_INTENTS:
            return replace(base, router=f"{self.name}(rules:context)")
        model = self.model()
        if model is None:
            return replace(base, router="rules(fallback:model_unavailable)",
                           llm=_telemetry(None, 0.0, fallback="model_unavailable", error=self._error))
        t0 = time.perf_counter()
        pred = model.predict(text)
        ms = (time.perf_counter() - t0) * 1000
        label = "unknown" if pred.abstained else pred.label
        intent = label if label in INTENTS else COMPAT.get(label, "unknown")
        return Understanding(intent, pred.p, base.language, base.slots, router=self.name,
                             llm=_telemetry(model, ms, label=pred.label, p=pred.p, abstained=pred.abstained))


def _telemetry(model: IntentModel | None, ms: float, fallback: str | None = None, error: str | None = None,
               **extra) -> dict:
    """Mismo formato que la telemetría del LLM (observability.LLM_FIELDS): costo 0, sin tokens."""
    meta = model.meta if model else {}
    return {"component": "router", "provider": "local", "model": meta.get("model_id", "intent-model"),
            "prompt_version": meta.get("version", "-"), "attempts": 1 if model else 0,
            "errors": [error] if error else [], "fallback": fallback, "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0, "latency_ms": round(ms, 2), **extra}
