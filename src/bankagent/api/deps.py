"""Dependencias compartidas por los routers (patrón "Bigger Applications" de FastAPI)."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response

from .runtime import BrowserSession, Runtime

COOKIE = "bankagent_sid"


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


RuntimeDep = Annotated[Runtime, Depends(get_runtime)]


def client_ip(request: Request) -> str:
    """IP del cliente para las cuotas (logins por minuto, sesiones vivas por IP).

    Red team #33: con `uvicorn --proxy-headers --forwarded-allow-ips '*'` (docker/entrypoint.sh) `request.client`
    es la PRIMERA entrada de X-Forwarded-For, que escribe el cliente: inventándola se esquivaban las cuotas por IP.
    Con BANKAGENT_TRUSTED_PROXY_HOPS=N (N proxies propios delante) se toma la entrada N-ésima desde la DERECHA, la
    que agregó nuestro proxy y el cliente no controla. 0 (default fuera del contenedor) = conexión directa."""
    hops = request.app.state.runtime.settings.trusted_proxy_hops
    xff = [h.strip() for v in request.headers.getlist("x-forwarded-for") for h in v.split(",") if h.strip()]
    if hops > 0 and xff:
        return xff[-hops] if len(xff) >= hops else xff[0]
    return request.client.host if request.client else "unknown"


def require_session(request: Request, rt: RuntimeDep) -> BrowserSession:
    s = rt.get_session(request.cookies.get(COOKIE))
    if s is None:
        raise HTTPException(401, detail="session_required")
    return s


SessionDep = Annotated[BrowserSession, Depends(require_session)]


def cookie_secure(request: Request, rt: Runtime) -> bool:
    if rt.settings.cookie_secure is not None:
        return rt.settings.cookie_secure
    return request.url.scheme == "https"


def set_session_cookie(response: Response, request: Request, rt: Runtime, sid: str) -> None:
    response.set_cookie(COOKIE, sid, max_age=rt.settings.session_ttl_s, path="/api", httponly=True,
                        secure=cookie_secure(request, rt), samesite="strict")


def clear_session_cookie(response: Response, request: Request, rt: Runtime) -> None:
    response.delete_cookie(COOKIE, path="/api", httponly=True, secure=cookie_secure(request, rt), samesite="strict")
