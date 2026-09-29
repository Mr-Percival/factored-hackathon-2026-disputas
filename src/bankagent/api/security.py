"""Controles HTTP transversales (middlewares ASGI puros, sin dependencias extra).

Referencias: OWASP Secure Headers Project, OWASP ASVS 4.0 (V3 sesiones, V12/V13 API, V14 config),
MDN Content-Security-Policy.

- Cabeceras seguras en TODAS las respuestas (API, SPA y errores).
- CSP estricta: sin scripts ni estilos inline (la SPA de Vite no los necesita). La única excepción es
  /api/docs (Swagger UI trae script inline y recursos de jsDelivr); se puede apagar con BANKAGENT_DOCS=0.
- Límite de tamaño del cuerpo: 413 antes de que el JSON llegue a Pydantic, también con cuerpos chunked.
- Verificación de Origin en métodos que cambian estado (defensa en profundidad además de SameSite=Strict).
"""
from __future__ import annotations

import json
import secrets

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
DOCS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
DOCS_PATHS = ("/api/docs", "/api/redoc")

BASE_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "permissions-policy": "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), "
                          "microphone=(), payment=(), usb=(), interest-cohort=()",
}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _error(status: int, code: str, message: str) -> tuple[dict, bytes]:
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    start = {"type": "http.response.start", "status": status,
             "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]}
    return start, body


async def _send_error(send: Send, status: int, code: str, message: str) -> None:
    start, body = _error(status, code, message)
    await send(start)
    await send({"type": "http.response.body", "body": body})


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, hsts: bool = True):
        self.app, self.hsts = app, hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        is_docs = path.startswith(DOCS_PATHS)
        https = scope.get("scheme") == "https"
        request_id = secrets.token_hex(8)

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in (b"server",)]
                present = {k.lower() for k, _ in headers}
                extra = dict(BASE_HEADERS)
                extra["content-security-policy"] = DOCS_CSP if is_docs else CSP
                extra["x-request-id"] = request_id
                if path.startswith("/api/") or path in ("/healthz", "/readyz"):
                    extra.setdefault("cache-control", "no-store")
                if https and self.hsts:
                    extra["strict-transport-security"] = "max-age=31536000; includeSubDomains"
                for k, v in extra.items():
                    if k.encode() not in present:
                        headers.append((k.encode(), v.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, wrapped)


class BodySizeLimitMiddleware:
    """413 si el cuerpo supera `max_bytes`, por Content-Length o contando lo recibido (chunked)."""

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    too_big = int(v) > self.max_bytes
                except ValueError:
                    too_big = True
                if too_big:
                    return await _send_error(send, 413, "payload_too_large", "El cuerpo de la petición es demasiado grande.")
        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > self.max_bytes:
                    raise _TooLarge()
            return msg

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:
                await _send_error(send, 413, "payload_too_large", "El cuerpo de la petición es demasiado grande.")


class _TooLarge(Exception):
    pass


class OriginCheckMiddleware:
    """Rechaza (403) métodos que cambian estado si el navegador declara un Origin ajeno.

    Sin cabecera Origin (curl, tests) se deja pasar: la cookie SameSite=Strict ya impide que otro sitio
    la envíe. Orígenes permitidos: el propio host y los configurados para CORS en desarrollo.
    """

    def __init__(self, app: ASGIApp, allowed: tuple[str, ...] = ()):
        self.app, self.allowed = app, set(allowed)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("method") in UNSAFE_METHODS:
            headers = dict(scope.get("headers", []))
            origin = headers.get(b"origin", b"").decode("latin-1")
            if origin and origin != "null":
                host = headers.get(b"host", b"").decode("latin-1")
                same = origin in (f"http://{host}", f"https://{host}")
                if not same and origin not in self.allowed:
                    return await _send_error(send, 403, "forbidden_origin", "Origen no permitido.")
            elif origin == "null":
                return await _send_error(send, 403, "forbidden_origin", "Origen no permitido.")
        await self.app(scope, receive, send)
