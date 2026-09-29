"""Aplicación FastAPI: API de la demo + SPA compilada en un solo proceso (un contenedor).

    uvicorn bankagent.api.main:app --reload            # desarrollo (la SPA corre aparte con `npm run dev`)
    uvicorn bankagent.api.main:app --host 0.0.0.0      # producción: sirve también web/dist

El agente corre SIEMPRE con reglas + plantillas (sin LLM, sin costo ni llamadas externas).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings
from .routers import conversations, health, scenarios, sessions
from .runtime import Runtime
from .security import BodySizeLimitMiddleware, OriginCheckMiddleware, SecurityHeadersMiddleware

log = logging.getLogger("bankagent.api")

MESSAGES = {
    "session_required": "Inicia sesión con un cliente de demo.",
    "customer_not_allowed": "Ese cliente no está disponible en la demo.",
    "customer_not_found": "Cliente no encontrado.",
    "conversation_not_found": "Conversación no encontrada.",
    "rate_limited": "Demasiadas solicitudes. Espera un momento e intenta de nuevo.",
    "not_found": "Recurso no encontrado.",
    "method_not_allowed": "Método no permitido.",
    "validation_error": "La solicitud no es válida.",
    "internal_error": "Ocurrió un error inesperado. Intenta de nuevo.",
}
STATUS_CODES = {404: "not_found", 405: "method_not_allowed"}


def _error(status: int, code: str, fields: list[str] | None = None) -> JSONResponse:
    body: dict = {"code": code, "message": MESSAGES.get(code, MESSAGES["internal_error"])}
    if fields:
        body["fields"] = fields
    headers = {"retry-after": "60"} if status == 429 else None
    return JSONResponse({"error": body}, status_code=status, headers=headers)


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        code = exc.detail if isinstance(exc.detail, str) and exc.detail in MESSAGES else \
            STATUS_CODES.get(exc.status_code, "internal_error")
        return _error(exc.status_code, code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # El handler por defecto devuelve el `input` recibido: aquí solo la ubicación del campo, nunca el texto.
        fields = sorted({".".join(str(p) for p in e.get("loc", ()) if p != "body") for e in exc.errors()})
        return _error(422, "validation_error", [f for f in fields if f])

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        # Sin stack trace ni mensaje (podría contener datos): solo el tipo y la ruta.
        log.error("unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
        return _error(500, "internal_error")


def _mount_spa(app: FastAPI, dist: str) -> None:
    """Sirve la SPA compilada. Rutas desconocidas (fuera de /api) caen a index.html (router del cliente)."""
    index = os.path.join(dist, "index.html")
    if not os.path.isfile(index):
        log.info("SPA no encontrada en %s: solo API", dist)
        return
    root = os.path.realpath(dist)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(404)
        candidate = os.path.realpath(os.path.join(root, full_path))
        if full_path and candidate.startswith(root + os.sep) and os.path.isfile(candidate):
            immutable = full_path.startswith("assets/")  # nombres con hash de Vite
            return FileResponse(candidate, headers={
                "cache-control": "public, max-age=31536000, immutable" if immutable else "no-cache"})
        return FileResponse(index, headers={"cache-control": "no-cache"})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = Runtime(settings)
        try:
            yield
        finally:
            app.state.runtime.close()

    app = FastAPI(
        title="Agente de disputas · API de la demo",
        version="0.1.0",
        summary="Sandbox con datos sintéticos · política sintética · no mueve dinero",
        docs_url="/api/docs" if settings.docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.docs else None,
        lifespan=lifespan,
    )
    _install_error_handlers(app)

    api = APIRouter(prefix="/api")
    api.include_router(scenarios.router)
    api.include_router(sessions.router)
    api.include_router(conversations.router)
    app.include_router(api)
    app.include_router(health.router)
    _mount_spa(app, settings.web_dist)

    # Orden: el último agregado es el más externo. Las cabeceras seguras envuelven todo (incluso 413/403).
    if settings.cors_origins:  # solo en desarrollo; por defecto la SPA es del mismo origen y no hace falta CORS
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True,
                           allow_methods=["GET", "POST", "DELETE"], allow_headers=["content-type"])
    app.add_middleware(OriginCheckMiddleware, allowed=settings.cors_origins)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


app = create_app()
