"""Cliente LLM agnóstico de proveedor.

El resto del agente solo conoce `LLMClient.complete_json(...)`: pide un JSON que cumpla un esquema y
devuelve (dict, LLMUsage). Agregar otro proveedor = una clase nueva con ese método.

- `AnthropicClient`: SDK oficial `anthropic` con salida estructurada (`output_config.format`).
  La key sale de ANTHROPIC_API_KEY; nunca se registra ni se incluye en la traza.
- `FakeLLMClient`: respuestas guionadas para los tests (CI corre sin red ni key) y captura de lo que
  se habría enviado, para poder afirmar que no sale PII.

Los errores se normalizan a `LLMError(kind)` para que el llamador decida reintento / camino alternativo
sin depender de las excepciones de cada SDK.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-5-5"

# USD por millón de tokens (entrada, salida). Solo para estimar costo en la traza; actualizar si cambia.
PRICES: dict[str, tuple[float, float]] = {
    HAIKU: (1.0, 5.0),
    "claude-haiku-4-5": (1.0, 5.0),
    SONNET: (2.0, 10.0),
}


class LLMError(Exception):
    """kind: timeout | connection | rate_limit | server | auth | bad_request | refusal | truncated |
    invalid_json | schema | no_key | unavailable."""

    RETRYABLE = {"connection", "rate_limit", "server", "invalid_json", "schema", "truncated"}

    def __init__(self, kind: str, message: str = ""):
        super().__init__(f"{kind}: {message}" if message else kind)
        self.kind = kind

    @property
    def retryable(self) -> bool:
        return self.kind in self.RETRYABLE


@dataclass
class LLMUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0

    @property
    def cost_usd(self) -> float:
        pin, pout = PRICES.get(self.model, (0.0, 0.0))
        return round((self.input_tokens * pin + self.output_tokens * pout) / 1_000_000, 6)


class LLMClient(Protocol):
    provider: str

    def complete_json(self, system: str, messages: list[dict], schema: dict, model: str,
                      max_tokens: int = 512, timeout: float = 8.0) -> tuple[dict, LLMUsage]: ...


# ---------------------------------------------------------------------------------------------- Anthropic
class AnthropicClient:
    """Salida estructurada con JSON schema. Reintentos del SDK en 0: los reintentos son nuestros y acotados."""

    provider = "anthropic"

    def __init__(self, api_key: str | None = None):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("no_key", "ANTHROPIC_API_KEY no está definida")
        try:
            import anthropic  # dependencia opcional: pip install -e ".[llm]"
        except ImportError as e:  # pragma: no cover - depende del entorno
            raise LLMError("unavailable", "falta el paquete 'anthropic' (extra [llm])") from e
        self._sdk = anthropic
        self._client = anthropic.Anthropic(api_key=key, max_retries=0)

    def __repr__(self) -> str:  # nunca exponer la key en logs / trazas
        return "AnthropicClient(key=***)"

    def complete_json(self, system: str, messages: list[dict], schema: dict, model: str,
                      max_tokens: int = 512, timeout: float = 8.0) -> tuple[dict, LLMUsage]:
        a = self._sdk
        t0 = time.perf_counter()
        try:
            resp = self._client.with_options(timeout=timeout).messages.create(
                model=model, max_tokens=max_tokens, system=system, messages=messages,
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except a.APITimeoutError as e:
            raise LLMError("timeout") from e
        except a.APIConnectionError as e:
            raise LLMError("connection") from e
        except a.RateLimitError as e:
            raise LLMError("rate_limit") from e
        except (a.AuthenticationError, a.PermissionDeniedError) as e:
            raise LLMError("auth") from e
        except a.BadRequestError as e:
            raise LLMError("bad_request", getattr(e, "message", "")[:200]) from e
        except a.APIStatusError as e:
            raise LLMError("server" if e.status_code >= 500 else "bad_request", str(e.status_code)) from e
        usage = LLMUsage(model, resp.usage.input_tokens, resp.usage.output_tokens,
                         round((time.perf_counter() - t0) * 1000, 1))
        if resp.stop_reason == "refusal":
            raise LLMError("refusal")
        if resp.stop_reason == "max_tokens":
            raise LLMError("truncated")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return parse_json(text), usage


def parse_json(text: str) -> dict:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        raise LLMError("invalid_json", str(e)[:120]) from e
    if not isinstance(data, dict):
        raise LLMError("invalid_json", "no es un objeto")
    return data


# ---------------------------------------------------------------------------------------------- Fake
@dataclass
class FakeLLMClient:
    """Cada elemento de `script` es: dict (respuesta), str (texto crudo a parsear), LLMError (se lanza) o
    callable(request) -> cualquiera de los anteriores. Cuando se acaba el guion, repite el último."""

    script: list[Any] = field(default_factory=list)
    provider: str = "fake"
    requests: list[dict] = field(default_factory=list)

    def complete_json(self, system: str, messages: list[dict], schema: dict, model: str,
                      max_tokens: int = 512, timeout: float = 8.0) -> tuple[dict, LLMUsage]:
        req = {"system": system, "messages": messages, "schema": schema, "model": model}
        self.requests.append(req)
        if not self.script:
            raise LLMError("unavailable", "guion vacío")
        item = self.script[min(len(self.requests) - 1, len(self.script) - 1)]
        if callable(item) and not isinstance(item, LLMError):
            item = item(req)
        if isinstance(item, LLMError):
            raise item
        usage = LLMUsage(model, input_tokens=len(system + json.dumps(messages)) // 4, output_tokens=40, latency_ms=1.0)
        return (parse_json(item) if isinstance(item, str) else dict(item)), usage

    def sent_text(self) -> str:
        """Todo lo que habría salido hacia el proveedor (para afirmar ausencia de PII)."""
        return "\n".join(r["system"] + json.dumps(r["messages"], ensure_ascii=False) for r in self.requests)


# ---------------------------------------------------------------------------------------------- esquema
def validate(obj: Any, schema: dict, path: str = "$") -> None:
    """Validador mínimo (type/enum/anyOf/properties/required/additionalProperties/minimum/maximum).
    Se valida SIEMPRE en código aunque el proveedor prometa salida estructurada: cambiar de proveedor
    no debe cambiar las garantías."""
    if "anyOf" in schema:
        for sub in schema["anyOf"]:
            try:
                validate(obj, sub, path)
                return
            except LLMError:
                continue
        raise LLMError("schema", f"{path}: no coincide con ninguna alternativa")
    types = {"object": dict, "string": str, "integer": int, "number": (int, float), "boolean": bool,
             "null": type(None), "array": list}
    t = schema.get("type")
    if t:
        ok = isinstance(obj, types[t]) and not (t in ("integer", "number") and isinstance(obj, bool))
        if not ok:
            raise LLMError("schema", f"{path}: se esperaba {t}")
    if "enum" in schema and obj not in schema["enum"]:
        raise LLMError("schema", f"{path}: valor fuera del enum")
    if t in ("integer", "number"):
        if "minimum" in schema and obj < schema["minimum"]:
            raise LLMError("schema", f"{path}: menor que el mínimo")
        if "maximum" in schema and obj > schema["maximum"]:
            raise LLMError("schema", f"{path}: mayor que el máximo")
    if t == "object":
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in obj:
                raise LLMError("schema", f"{path}.{k}: falta")
        if schema.get("additionalProperties") is False and set(obj) - set(props):
            raise LLMError("schema", f"{path}: propiedades no permitidas {sorted(set(obj) - set(props))}")
        for k, sub in props.items():
            if k in obj:
                validate(obj[k], sub, f"{path}.{k}")


def api_schema(schema: dict) -> dict:
    """Quita restricciones numéricas que la salida estructurada no soporta (se validan en código)."""
    if isinstance(schema, dict):
        return {k: api_schema(v) for k, v in schema.items() if k not in ("minimum", "maximum")}
    if isinstance(schema, list):
        return [api_schema(v) for v in schema]
    return schema


def call_with_retries(call: Callable[[], tuple[dict, LLMUsage]], check: Callable[[dict], Any],
                      max_retries: int) -> tuple[Any, list[LLMUsage], list[str]]:
    """`call` habla con el proveedor; `check` valida/convierte la salida (lanza LLMError si no sirve).
    Reintentos acotados solo para errores transitorios o salida inválida. Un timeout NO se reintenta:
    ya consumió el presupuesto de latencia y la línea base responde al instante.
    Los tokens de intentos descartados también se cuentan (se pagaron)."""
    usages: list[LLMUsage] = []
    errors: list[str] = []
    for attempt in range(max_retries + 1):
        try:
            data, usage = call()
            usages.append(usage)
            return check(data), usages, errors
        except LLMError as e:
            errors.append(e.kind)
            if not e.retryable or attempt == max_retries:
                raise LLMAttemptsExhausted(e.kind, usages, errors) from e
    raise AssertionError("inalcanzable")


class LLMAttemptsExhausted(LLMError):
    def __init__(self, kind: str, usages: list[LLMUsage], errors: list[str]):
        super().__init__(kind)
        self.usages, self.errors = usages, errors


def telemetry(component: str, provider: str, model: str, prompt_version: str, usages: list[LLMUsage],
              errors: list[str], fallback: str | None, latency_ms: float, **extra) -> dict:
    """Registro que va a la traza: suficiente para que el harness de evaluación calcule costo y latencia."""
    return {"component": component, "provider": provider, "model": model, "prompt_version": prompt_version,
            "attempts": len(errors) + (0 if fallback else 1),
            "errors": errors, "fallback": fallback,
            "input_tokens": sum(u.input_tokens for u in usages), "output_tokens": sum(u.output_tokens for u in usages),
            "cost_usd": round(sum(u.cost_usd for u in usages), 6), "latency_ms": round(latency_ms, 1), **extra}
