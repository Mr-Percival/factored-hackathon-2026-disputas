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
