"""Estado del proceso: un agente, las sesiones del navegador y sus conversaciones.

Concurrencia: FastAPI corre los endpoints síncronos en un pool de hilos, pero las conexiones DuckDB de
`BankTools` (y su lista de auditoría) no son seguras para usarse desde varios hilos a la vez. Todas las
operaciones que tocan el agente, la identidad o la base pasan por `Runtime.lock`, así que los turnos se
serializan dentro del proceso. Un turno con reglas + plantillas tarda milisegundos, suficiente para la
demo. Para escalar: varias réplicas del contenedor (cada una con su estado) detrás de afinidad de sesión,
o un checkpointer y un almacén de sesiones compartidos (p. ej. Postgres/Redis).

Mapa de identidades (el token del agente NUNCA sale de aquí):

    cookie (id de sesión opaco) -> BrowserSession{token del agente, customer_id, conversaciones}
    conversation_id             -> id de sesión dueña
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from ..audit import AuditLog
from ..factory import build_agent
from ..graph import Agent
from ..identity import IdentityService
from .config import Settings
from .schemas import ScenarioFile



@dataclass
class BrowserSession:
    sid: str
    customer_id: str
    token: str
    created_at: float
    conversations: list[str] = field(default_factory=list)  # en orden de creación


class RateLimiter:
    """Ventana deslizante en memoria por clave (sesión o IP). Suficiente para una réplica; en producción
    el límite vive en el gateway o en un almacén compartido."""

    def __init__(self, limit: int, window_s: float = 60.0, clock=time.monotonic, max_keys: int = 10_000):
        self.limit, self.window, self.clock, self.max_keys = limit, window_s, clock, max_keys
        self._hits: OrderedDict[str, deque] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            q = self._hits.pop(key, None) or deque()
            while q and now - q[0] >= self.window:
                q.popleft()
            ok = len(q) < self.limit
            if ok:
                q.append(now)
            self._hits[key] = q
            while len(self._hits) > self.max_keys:
                self._hits.popitem(last=False)
            return ok


def load_scenarios(path: str) -> ScenarioFile:
    with open(path, encoding="utf-8") as f:
        return ScenarioFile.model_validate(json.load(f))


def resolve_db(settings: Settings) -> tuple[str, str, str | None]:
    """(ruta, origen, carpeta temporal a limpiar). Sin `BANKAGENT_DB` se construye la base del fixture."""
    if settings.db_path:
        if not os.path.exists(settings.db_path):
            raise FileNotFoundError("BANKAGENT_DB apunta a un archivo inexistente")
        return settings.db_path, "env", None
    from ..demo_fixture import build_demo_db

    tmp = tempfile.mkdtemp(prefix="bankagent-demo-")
    return build_demo_db(os.path.join(tmp, "demo.duckdb")), "fixture", tmp


class Runtime:
    def __init__(self, settings: Settings, clock=time.time):
        self.settings, self.clock = settings, clock
        self.scenarios = load_scenarios(settings.scenarios_path)
        self.allowlist = {s.customer_id for s in self.scenarios.scenarios}
        self.db_path, self.data_source, self._tmp = resolve_db(settings)
        self.identity = IdentityService(clock=clock)
        audit = AuditLog(settings.audit_path) if settings.audit_path else None
        # LLM apagado a propósito: reglas + plantillas (sin llamadas a proveedores pagos).
        self.agent: Agent = build_agent(self.db_path, router="rules", writer="templates",
                                        identity=self.identity, audit=audit)
        self.lock = threading.Lock()
        self.sessions: OrderedDict[str, BrowserSession] = OrderedDict()
        self.owners: dict[str, str] = {}
        self.message_limiter = RateLimiter(settings.rate_limit_per_min)
        self.session_limiter = RateLimiter(settings.session_rate_limit_per_min)

    # ------------------------------------------------------------------ ciclo de vida
    def close(self) -> None:
        with self.lock:
            for conn in (self.agent.tools._ro, self.agent.tools._ops):
                try:
                    conn.close()
                except Exception:  # noqa: BLE001 - cierre best effort
                    pass
        if self._tmp:
            import shutil

            shutil.rmtree(self._tmp, ignore_errors=True)

    def ready(self) -> bool:
        with self.lock:
            self.agent.tools._ro.execute("SELECT count(*) FROM customers").fetchone()
        return bool(self.agent.policy.version)

    # ------------------------------------------------------------------ sesiones
    def customer_exists(self, customer_id: str) -> bool:
        with self.lock:
            row = self.agent.tools._ro.execute(
                "SELECT count(*) FROM customers WHERE customer_id = ?", [customer_id]).fetchone()
        return bool(row and row[0])

    def login(self, customer_id: str) -> BrowserSession:
        with self.lock:
            self._evict()
            token = self.identity.login(customer_id)
            s = BrowserSession(secrets.token_urlsafe(32), customer_id, token, self.clock())
            self.sessions[s.sid] = s
            return s

    def get_session(self, sid: str | None) -> BrowserSession | None:
        if not sid:
            return None
        with self.lock:
            s = self.sessions.get(sid)
            if s and self.clock() - s.created_at > self.settings.session_ttl_s:
                self._drop(sid)
                return None
            return s

    def logout(self, sid: str) -> None:
        with self.lock:
            self._drop(sid)

    def expire(self, s: BrowserSession) -> None:
        with self.lock:
            self.identity.expire(s.token)

    def expires_in(self, s: BrowserSession) -> int:
        with self.lock:
            return int(self.identity.seconds_left(s.token))

    def _drop(self, sid: str) -> None:
        s = self.sessions.pop(sid, None)
        if not s:
            return
        for cid in s.conversations:
            self.owners.pop(cid, None)
            self.agent.graph.checkpointer.delete_thread(cid)  # libera la memoria del checkpointer
        self.identity.revoke(s.token)

    def _evict(self) -> None:
        now = self.clock()
        for sid in [k for k, s in self.sessions.items() if now - s.created_at > self.settings.session_ttl_s]:
            self._drop(sid)
        while len(self.sessions) >= self.settings.max_sessions:
            self._drop(next(iter(self.sessions)))

    # ------------------------------------------------------------------ conversaciones
    def new_conversation(self, s: BrowserSession) -> str:
        with self.lock:
            if len(s.conversations) >= self.settings.max_conversations_per_session:
                oldest = s.conversations.pop(0)
                self.owners.pop(oldest, None)
                self.agent.graph.checkpointer.delete_thread(oldest)
            cid = "c_" + secrets.token_urlsafe(16)
            s.conversations.append(cid)
            self.owners[cid] = s.sid
            return cid

    def owns(self, s: BrowserSession, conversation_id: str) -> bool:
        with self.lock:
            return self.owners.get(conversation_id) == s.sid

    def chat(self, s: BrowserSession, conversation_id: str, text: str) -> dict:
        with self.lock:
            state = self.agent.chat(conversation_id, s.token, text)
            # `BankTools.audit` es una lista en memoria que crecería sin límite en un servidor: la traza del
            # grafo (y el AuditLog opcional) ya registran cada llamada.
            del self.agent.tools.audit[:-200]
            return state
