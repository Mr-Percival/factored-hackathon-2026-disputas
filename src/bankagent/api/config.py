"""Configuración de la API, solo desde variables de entorno (12-factor). Sin secretos por defecto.

| Variable | Default | Uso |
|---|---|---|
| BANKAGENT_DB | (vacío) | base serving DuckDB (solo lectura). Vacío: se construye la base de demo del fixture |
| BANKAGENT_SCENARIOS | (auto) | escenarios y allowlist del login simulado. Auto: con BANKAGENT_DB, docs/demo/demo_customers.json (clientes reales, #28); sin él, config/demo_scenarios.json (fixture) |
| BANKAGENT_ALLOW_ANY_CUSTOMER | 0 | 1 = login con cualquier customer_id existente (solo uso local con datos reales) |
| BANKAGENT_AUDIT_PATH | (vacío) | log de auditoría JSONL con cadena de hashes |
| BANKAGENT_CORS_ORIGINS | (vacío) | orígenes extra permitidos, separados por coma (dev: http://localhost:5173) |
| BANKAGENT_COOKIE_SECURE | auto | 1/0 fuerza el atributo Secure; auto = según el esquema de la petición |
| BANKAGENT_RATE_LIMIT_PER_MIN | 30 | mensajes por minuto por sesión (o IP) |
| BANKAGENT_ROUTER | embeddings | intención: `embeddings` (router aprendido lite, ADR 0009) o `rules`. Si el modelo no carga, cada turno responde RuleRouter y dice `rules(fallback:model_unavailable)` |
| BANKAGENT_WEB_DIST | web/dist | SPA compilada que sirve FastAPI en producción |
| BANKAGENT_DOCS | 1 | 0 = sin /api/docs ni /api/openapi.json |
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from ..policy import ROOT

FIXTURE_SCENARIOS = os.path.join(ROOT, "config", "demo_scenarios.json")
DEMO_SCENARIOS = os.path.join(ROOT, "docs", "demo", "demo_customers.json")
DEFAULT_WEB_DIST = os.path.join(ROOT, "web", "dist")


def _flag(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    db_path: str | None = None
    scenarios_path: str | None = None  # None = automático (ver `scenarios_file`)
    allow_any_customer: bool = False
    audit_path: str | None = None
    cors_origins: tuple[str, ...] = ()
    cookie_secure: bool | None = None  # None = automático según https
    rate_limit_per_min: int = 30
    session_rate_limit_per_min: int = 30  # cada clic en un escenario es un login: holgura para la demo en vivo
    max_body_bytes: int = 16 * 1024
    session_ttl_s: int = 30 * 60  # sesión del navegador (el token del agente dura 15 min); luego se libera todo
    max_sessions: int = 200  # cada sesión tiene su agente y su almacén ops; al tope, 429
    max_conversations_per_session: int = 50
    web_dist: str = DEFAULT_WEB_DIST
    docs: bool = True

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Settings":
        e = os.environ if env is None else env
        secure = e.get("BANKAGENT_COOKIE_SECURE", "auto").strip().lower()
        return cls(
            db_path=e.get("BANKAGENT_DB") or None,
            scenarios_path=e.get("BANKAGENT_SCENARIOS") or None,
            allow_any_customer=_flag(e.get("BANKAGENT_ALLOW_ANY_CUSTOMER"), False),
            audit_path=e.get("BANKAGENT_AUDIT_PATH") or None,
            cors_origins=tuple(o.strip() for o in (e.get("BANKAGENT_CORS_ORIGINS") or "").split(",") if o.strip()),
            cookie_secure=None if secure in ("", "auto") else _flag(secure, False),
            rate_limit_per_min=int(e.get("BANKAGENT_RATE_LIMIT_PER_MIN") or 30),
            web_dist=e.get("BANKAGENT_WEB_DIST") or DEFAULT_WEB_DIST,
            docs=_flag(e.get("BANKAGENT_DOCS"), True),
        )

    @property
    def scenarios_file(self) -> str:
        """Escenarios coherentes con la base: los del fixture para la base del fixture y los de clientes reales
        (docs/demo/demo_customers.json, #28) cuando se apunta a una base del organizador."""
        if self.scenarios_path:
            return self.scenarios_path
        if self.db_path and os.path.exists(DEMO_SCENARIOS):
            return DEMO_SCENARIOS
        return FIXTURE_SCENARIOS
