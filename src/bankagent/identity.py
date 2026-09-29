"""Servicio de identidad SIMULADO (sandbox).

Representa al IdP del banco: el cliente se autentica fuera de la conversación (app/OTP) y el canal
recibe un token opaco con expiración. Un número de documento o de cliente escrito en el chat NUNCA
autentica: las herramientas solo aceptan este token.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass


class AuthError(Exception):
    """Sesión inexistente, expirada o sin permiso. El grafo la convierte en respuesta segura."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code  # session_missing | session_expired | forbidden


@dataclass(frozen=True)
class Session:
    token: str
    customer_id: str
    expires_at: float


class IdentityService:
    def __init__(self, ttl_seconds: int = 900, clock=time.time):
        self.ttl = ttl_seconds
        self.clock = clock
        self._sessions: dict[str, Session] = {}

    def login(self, customer_id: str) -> str:
        """Simula un login exitoso (en producción: IdP + MFA). Devuelve el token del canal."""
        token = secrets.token_urlsafe(24)
        self._sessions[token] = Session(token, customer_id, self.clock() + self.ttl)
        return token

    def resolve(self, token: str | None) -> Session:
        s = self._sessions.get(token or "")
        if s is None:
            raise AuthError("session_missing")
        if self.clock() >= s.expires_at:
            raise AuthError("session_expired")
        return s

    def seconds_left(self, token: str) -> float:
        """Vida restante del token (0 si no existe o venció). No lanza: sirve para mostrar el estado."""
        s = self._sessions.get(token)
        return max(0.0, s.expires_at - self.clock()) if s else 0.0

    def revoke(self, token: str) -> None:
        """Cierra la sesión (logout): el token deja de existir."""
        self._sessions.pop(token, None)

    def expire(self, token: str) -> None:
        """Solo para pruebas: fuerza la expiración de una sesión."""
        s = self._sessions[token]
        self._sessions[token] = Session(s.token, s.customer_id, self.clock() - 1)
