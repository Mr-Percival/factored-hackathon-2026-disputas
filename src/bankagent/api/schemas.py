"""Contratos HTTP (Pydantic v2). Son la fuente del esquema OpenAPI del que salen los tipos del frontend.

Regla: ningún modelo de respuesta incluye el token del agente. El navegador solo conoce un id de sesión
opaco en una cookie HttpOnly.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Outcome = Literal["resolved", "clarify", "informed", "rejected", "handoff", "cancelled", "blocked", "auth_error"]
Lang = Literal["es", "pt"]
CUSTOMER_ID_PATTERN = r"^[A-Za-z0-9_-]{1,40}$"
MAX_MESSAGE_CHARS = 1000


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------- escenarios
class Example(_Model):
    label: str
    text: str
    tag: str | None = None


class Scenario(_Model):
    customer_id: str
    name: str
    description: str
    examples: list[Example]


class ScenarioFile(_Model):
    """Formato de `config/demo_scenarios.json` (validado al arrancar)."""
    model_config = ConfigDict(extra="ignore")
    version: str
    disclaimer: str
    scenarios: list[Scenario] = Field(min_length=1)
    quick_replies: list[Example] = []


class ScenariosResponse(_Model):
    version: str
    disclaimer: str
    data_source: Literal["fixture", "env"]
    allow_any_customer: bool
    scenarios: list[Scenario]
    quick_replies: list[Example]


# ---------------------------------------------------------------------- sesión y conversación
class SessionCreate(_Model):
    customer_id: str = Field(pattern=CUSTOMER_ID_PATTERN, description="Cliente con el que se simula el login en la app")


class SessionInfo(_Model):
    customer_id: str
    expires_in_s: int = Field(description="Segundos de vida del token del agente (0 = vencido)")
    expired: bool


class ConversationCreated(_Model):
    conversation_id: str


class MessageIn(_Model):
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("blank")
        return v.strip()


# ---------------------------------------------------------------------- resultado de un turno
class ToolCall(_Model):
    tool: str
    ok: bool
    attempt: int = 1
    ms: float | None = None
    error: str | None = None


class TraceStep(_Model):
    node: str
    next: str
    ms: float
    detail: str | None = None
    tools: list[ToolCall]
    llm: dict[str, Any] | None = None


class Rule(_Model):
    id: str
    outcome: str
    explain: str


class Decision(_Model):
    outcome: str
    policy_version: str
    rules: list[Rule]
    facts: dict[str, Any]


class Candidate(_Model):
    index: int
    kind: Literal["transaction", "card"]
    label: str


class PendingAction(_Model):
    type: Literal["open_dispute", "block_card"]
    card_label: str | None = None


class Evidence(_Model):
    turn: int
    node: str
    tools: list[str]


class HandoffPolicy(_Model):
    version: str | None = None
    rules_fired: list[Rule]


class Handoff(_Model):
    reason: str
    reason_text: str
    language: str
    created_at: str
    request: list[str]
    verified_facts: dict[str, Any]
    policy: HandoffPolicy
    actions_taken: list[ToolCall]
    evidence: list[Evidence]
    unresolved_questions: list[str]


class TurnResult(_Model):
    conversation_id: str
    turn: int
    reply: str
    outcome: Outcome
    lang: Lang
    awaiting: Literal["option", "confirmation"] | None = None
    candidates: list[Candidate]
    pending_action: PendingAction | None = None
    decision: Decision | None = None
    handoff: Handoff | None = None
    trace: list[TraceStep]
    trace_total_ms: float


# ---------------------------------------------------------------------- salud y errores
class Health(_Model):
    status: Literal["ok"]


class Ready(_Model):
    status: Literal["ready", "not_ready"]
    policy_version: str | None = None
    data_source: Literal["fixture", "env"] | None = None


class ErrorBody(_Model):
    code: str
    message: str
    fields: list[str] | None = None


class ErrorResponse(_Model):
    error: ErrorBody
