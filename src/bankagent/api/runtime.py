"""Estado del proceso: sesiones del navegador, un agente por sesión y sus conversaciones.

Aislamiento por sesión (solo demo). Cada login crea un `Agent` propio cuyo `BankTools` comparte la conexión
de solo lectura a serving y la conexión ops, pero escribe disputas y bloqueos en un schema propio de la
sesión (`BankTools.fork_ops`). Así la demo es repetible para muchos jueces: una sesión nueva empieza limpia y
D01 ("ya existe una disputa") solo refleja lo hecho en esa misma sesión. Al cerrar o vencer la sesión se
borran su schema y su checkpointer. En producción el almacén ops es uno solo y transaccional (ADR 0008).

Concurrencia. FastAPI corre los endpoints síncronos en el pool de hilos de uvicorn y los turnos corren EN
PARALELO:
- Cada `BankTools` usa un cursor DuckDB por hilo (`threading.local`, #29) sobre las conexiones compartidas.
- Los turnos de UNA misma conversación se serializan con un lock por conversación (el checkpointer guarda el
  estado entre turnos: dos mensajes simultáneos del mismo hilo competirían por él).
- El almacén de sesiones (dicts de este módulo) se protege con `_store_lock`, que nunca envuelve un turno.
Regresión cubierta por `tests/test_api.py::test_parallel_customers_only_see_their_own_data`.

Mapa de identidades (el token del agente NUNCA sale de aquí):

    cookie (id de sesión opaco) -> BrowserSession{token del agente, customer_id, agente, conversaciones}
    conversation_id             -> id de sesión dueña
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from ..audit import AuditLog
from ..factory import build_agent
from ..graph import Agent
from ..identity import IdentityService
from ..policy import PolicyEngine
from ..tools import BankTools
from .config import Settings
from .schemas import ScenarioFile

MAX_TOOL_AUDIT = 200  # `BankTools.audit` es una lista en memoria: en un servidor se recorta


class TooManySessions(Exception):
    """Se alcanzó el tope de sesiones simultáneas (cada una tiene su agente y su almacén ops)."""


@dataclass
class BrowserSession:
    sid: str
    customer_id: str
    token: str
    created_at: float
    agent: Agent
    ip: str = ""
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
        self.scenarios_source = os.path.basename(settings.scenarios_file)
        raw = load_scenarios(settings.scenarios_file)
        self.scenarios, self.disclaimer, self.quick_replies = raw.to_api(), raw.disclaimer, raw.quick_replies
        self.allowlist = {s.customer_id for s in self.scenarios}
        self.db_path, self.data_source, self._tmp = resolve_db(settings)
        self.identity = IdentityService(clock=clock)
        self.policy = PolicyEngine()
        self.audit = AuditLog(settings.audit_path) if settings.audit_path else None
        # Dueño de las conexiones compartidas (serving de solo lectura + ops); las sesiones hacen fork_ops.
        self.tools = BankTools(self.db_path, self.identity)
        self._store_lock = threading.Lock()
        self.sessions: OrderedDict[str, BrowserSession] = OrderedDict()
        self.owners: dict[str, str] = {}
        self._turn_locks: dict[str, threading.Lock] = {}
        self.message_limiter = RateLimiter(settings.rate_limit_per_min)
        self.session_limiter = RateLimiter(settings.session_rate_limit_per_min)

    # ------------------------------------------------------------------ ciclo de vida
    def close(self) -> None:
        with self._store_lock:
            for sid in list(self.sessions):
                self._drop(sid)
        for conn in (self.tools._ro, self.tools._ops):
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - cierre best effort
                pass
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)

    def _scalar(self, sql: str, params: list | None = None):
        row = self.tools._ro_c.execute(sql, params or []).fetchone()  # cursor del hilo actual
        return row[0] if row else None

    def ready(self) -> bool:
        self._scalar("SELECT count(*) FROM customers")
        return bool(self.policy.version)

    def _new_agent(self) -> Agent:
        # LLM apagado a propósito (sin proveedores pagos). Por defecto el router aprendido local (ADR 0009, "Decisión de
        # demo"); BANKAGENT_ROUTER=rules vuelve a la línea base. Si el modelo no carga (sin artefacto o sin numpy),
        # cada turno responde RuleRouter y la traza/la UI lo dicen: `rules(fallback:model_unavailable)`.
        tools = self.tools.fork_ops("s_" + secrets.token_hex(8))
        router = os.environ.get("BANKAGENT_ROUTER", "embeddings")
        router = router if router in ("rules", "embeddings") else "rules"  # nunca LLM ni el modelo full en la demo
        return build_agent(tools, router=router, writer="templates", policy=self.policy, audit=self.audit)

    # ------------------------------------------------------------------ sesiones
    def customer_exists(self, customer_id: str) -> bool:
        return bool(self._scalar("SELECT count(*) FROM customers WHERE customer_id = ?", [customer_id]))

    def login(self, customer_id: str, replaces: str | None = None, ip: str = "") -> BrowserSession:
        """Nueva sesión con agente y almacén ops propios. `replaces`: sesión anterior del mismo navegador.
        `ip`: cuota de sesiones vivas por IP (`max_sessions_per_ip`); al pasarla se libera la más vieja de esa IP."""
        with self._store_lock:
            if replaces:
                self._drop(replaces)
            self._evict_expired()
            same_ip = [k for k, x in self.sessions.items() if x.ip == ip]  # en orden de creación
            for sid in same_ip[:max(0, len(same_ip) - self.settings.max_sessions_per_ip + 1)]:
                self._drop(sid)
            if len(self.sessions) >= self.settings.max_sessions:
                raise TooManySessions()
        agent = self._new_agent()  # fuera del lock: compila el grafo (~15 ms)
        with self._store_lock:
            token = self.identity.login(customer_id)
            s = BrowserSession(secrets.token_urlsafe(32), customer_id, token, self.clock(), agent, ip)
            self.sessions[s.sid] = s
            return s

    def get_session(self, sid: str | None) -> BrowserSession | None:
        if not sid:
            return None
        with self._store_lock:
            s = self.sessions.get(sid)
            if s and self._expired(s):
                self._drop(sid)
                return None
            return s

    def logout(self, sid: str) -> None:
        with self._store_lock:
            self._drop(sid)

    def expire(self, s: BrowserSession) -> None:
        with self._store_lock:
            self.identity.expire(s.token)

    def expires_in(self, s: BrowserSession) -> int:
        return int(self.identity.seconds_left(s.token))

    def _expired(self, s: BrowserSession) -> bool:
        return self.clock() - s.created_at > self.settings.session_ttl_s

    def _forget_conversation(self, s: BrowserSession, cid: str) -> None:
        self.owners.pop(cid, None)
        self._turn_locks.pop(cid, None)
        s.agent.graph.checkpointer.delete_thread(cid)

    def _drop(self, sid: str) -> None:
        """Libera todo lo de la sesión: conversaciones, schema ops (disputas/bloqueos) y token."""
        s = self.sessions.pop(sid, None)
        if not s:
            return
        for cid in s.conversations:
            self.owners.pop(cid, None)
            self._turn_locks.pop(cid, None)
        s.conversations.clear()
        try:
            s.agent.tools.drop_ops()
        except Exception:  # noqa: BLE001 - conexión ya cerrada al apagar
            pass
        self.identity.revoke(s.token)

    def _evict_expired(self) -> None:
        for sid in [k for k, s in self.sessions.items() if self._expired(s)]:
            self._drop(sid)

    # ------------------------------------------------------------------ conversaciones
    def new_conversation(self, s: BrowserSession) -> str:
        with self._store_lock:
            if len(s.conversations) >= self.settings.max_conversations_per_session:
                self._forget_conversation(s, s.conversations.pop(0))
            cid = "c_" + secrets.token_urlsafe(16)
            s.conversations.append(cid)
            self.owners[cid] = s.sid
            self._turn_locks[cid] = threading.Lock()
            return cid

    def owns(self, s: BrowserSession, conversation_id: str) -> bool:
        with self._store_lock:
            return self.owners.get(conversation_id) == s.sid

    def chat(self, s: BrowserSession, conversation_id: str, text: str) -> dict:
        with self._store_lock:
            turn_lock = self._turn_locks.get(conversation_id) or threading.Lock()
        with turn_lock:  # solo serializa turnos de ESTA conversación
            state = s.agent.chat(conversation_id, s.token, text)
        with self._store_lock:
            del s.agent.tools.audit[:-MAX_TOOL_AUDIT]
        return state
