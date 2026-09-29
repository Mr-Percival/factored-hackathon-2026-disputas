"""HybridRouter: intención con un modelo aprendido; slots, idioma y respuestas por contexto con RuleRouter.

    HybridRouter()                                   # modelo "lite" (n-gramas de caracteres, solo numpy)
    HybridRouter(model_dir=FULL_DIR)                 # char + MiniLM ONNX (evaluación offline)

División del trabajo (ADR 0009):
- Respuestas a una pregunta pendiente (confirm / deny / unclear / select_option / none_of_these) -> RuleRouter:
  dependen de la pregunta, no del texto aislado, y el consentimiento tri-estado tiene que ser auditable.
- Respuesta a "dime el monto, la fecha o el comercio" (`awaiting="details"`) con datos y sin pedido nuevo ->
  RuleRouter (el grafo sigue el reclamo anterior).
- Todo lo demás -> el modelo elige una de las intenciones de usuario (`intent_model.LABELS`) con probabilidad
  calibrada. Si no llega al umbral elegido en validación, se abstiene: `unknown` y el grafo pide aclaración.
- Slots (monto, fechas, país, comercio, caso, cantidad, opción) e idioma -> siempre RuleRouter.
- Si el modelo no carga (sin artefactos, sin paquete, sin caché) -> responde RuleRouter y `router` lo dice:
  `rules(fallback:model_unavailable)`; la traza guarda el error.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import replace
from pathlib import Path

from .intent_model import COMPAT, DEFAULT_DIR, IntentModel, load_intent_model
from .understanding import INTENTS, Router, RuleRouter, Understanding

CONTEXT_INTENTS = ("confirm", "deny", "unclear", "select_option", "none_of_these")


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
        return f"embed:{m.meta.get('candidate', m.model_id)}" if m else "embed"

    @property
    def model_id(self) -> str | None:  # para la descripción del sistema en la evaluación
        return self._model.model_id if self._model else None

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
        s = base.slots
        if awaiting == "details" and base.intent == "unknown" and (s.amount is not None or s.date_from or s.merchant):
            return replace(base, router=f"{self.name}(rules:details)")
        model = self.model()
        if model is None:
            return replace(base, router="rules(fallback:model_unavailable)",
                           llm=_telemetry(None, 0.0, fallback="model_unavailable", error=self._error))
        t0 = time.perf_counter()
        pred = model.predict(text)
        ms = (time.perf_counter() - t0) * 1000
        label = "unknown" if pred.abstained else pred.label
        intent = label if label in INTENTS else COMPAT.get(label, "unknown")
        tele = _telemetry(model, ms, label=pred.label, p=round(pred.p, 4), abstained=pred.abstained)
        backoff = rule_backoff(base, intent)
        if backoff:
            return replace(base, router=f"{self.name}(rules:{backoff})", llm={**tele, "backoff": backoff})
        return replace(base, intent=intent, confidence=pred.p, router=self.name, llm=tele)


ACTION_INTENTS = ("dispute_charge", "block_card")  # rutas que buscan movimientos/tarjetas y proponen una acción
RULE_EVIDENCE = 0.85  # confianza de RuleRouter con una sola intención ganadora (sin empate): hubo palabra clave


def rule_backoff(base: Understanding, model_intent: str) -> str | None:
    """Cuándo responde la regla aunque se consultó el modelo (#57): el modelo se ABSTIENE y RuleRouter tiene una
    intención inequívoca que NO es de acción (fuera de alcance, pedido de humano, toma de cuenta, estado o retiro de
    una disputa, cierre). Abstenerse significa "no sé": en vez de pedir aclaración ("quero fazer um emprestimo",
    "quiero dar de baja un seguro" -> p≈0.5), se usa la evidencia léxica de la línea base.
    Hacia disputa/bloqueo NO se cede: en validación fuera de fold (train, dejando un autor afuera) ceder también esas
    subía los mensajes con acción equivocada de 1.0% a 3.9% (> objetivo preregistrado de 1%); así, 0 acciones nuevas."""
    if model_intent != "unknown" or base.confidence < RULE_EVIDENCE:
        return None
    if base.intent in ACTION_INTENTS or base.intent in ("unknown", "unclear"):
        return None
    return "abstain"


def _telemetry(model: IntentModel | None, ms: float, fallback: str | None = None, error: str | None = None,
               **extra) -> dict:
    """Mismo formato que la telemetría del LLM (observability.LLM_FIELDS): costo 0, sin tokens."""
    meta = model.meta if model else {}
    return {"component": "router", "provider": "local", "model": meta.get("model_id", "intent-model"),
            "prompt_version": meta.get("version", "-"), "attempts": 1 if model else 0,
            "errors": [error] if error else [], "fallback": fallback, "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0, "latency_ms": round(ms, 2), **extra}
