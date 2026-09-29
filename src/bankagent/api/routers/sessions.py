"""Login SIMULADO (el IdP del banco) y controles de la demo sobre la sesión.

El token del agente queda en el servidor. El navegador recibe solo un id de sesión opaco en una cookie
HttpOnly + SameSite=Strict (+ Secure bajo https), limitada al path /api.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from ..deps import RuntimeDep, SessionDep, clear_session_cookie, client_ip, set_session_cookie, COOKIE
from ..runtime import BrowserSession, Runtime
from ..schemas import ErrorResponse, SessionCreate, SessionInfo

router = APIRouter(prefix="/sessions", tags=["sesiones"])


def _info(rt: Runtime, s: BrowserSession) -> SessionInfo:
    left = rt.expires_in(s)
    return SessionInfo(customer_id=s.customer_id, expires_in_s=left, expired=left <= 0)


@router.post("", response_model=SessionInfo, status_code=status.HTTP_201_CREATED,
             summary="Login simulado con un cliente de demo",
             responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 429: {"model": ErrorResponse}})
def create_session(body: SessionCreate, request: Request, response: Response, rt: RuntimeDep) -> SessionInfo:
    if not rt.session_limiter.allow("ip:" + client_ip(request)):
        raise HTTPException(429, detail="rate_limited")
    if not rt.settings.allow_any_customer and body.customer_id not in rt.allowlist:
        raise HTTPException(403, detail="customer_not_allowed")
    if not rt.customer_exists(body.customer_id):
        raise HTTPException(404, detail="customer_not_found")
    old = request.cookies.get(COOKIE)
    if old:
        rt.logout(old)  # una sesión por navegador: el login nuevo invalida la anterior
    s = rt.login(body.customer_id)
    set_session_cookie(response, request, rt, s.sid)
    return _info(rt, s)


@router.get("/current", response_model=SessionInfo, summary="Estado de la sesión actual",
            responses={401: {"model": ErrorResponse}})
def current_session(s: SessionDep, rt: RuntimeDep) -> SessionInfo:
    return _info(rt, s)


@router.post("/expire", response_model=SessionInfo, summary="Control de demo: vence el token del agente",
             responses={401: {"model": ErrorResponse}})
def expire_session(s: SessionDep, rt: RuntimeDep) -> SessionInfo:
    rt.expire(s)
    return _info(rt, s)


@router.delete("/current", status_code=status.HTTP_204_NO_CONTENT, summary="Cerrar sesión")
def delete_session(request: Request, rt: RuntimeDep) -> Response:
    sid = request.cookies.get(COOKIE)
    if sid:
        rt.logout(sid)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, request, rt)
    return response
