"""Construcción del agente por nombre, para la UI, el chat y el harness de evaluación.

    build_agent("data/serving.duckdb", router="llm", writer="llm")

Sin key del proveedor el agente igual funciona: los componentes LLM caen a reglas/plantillas y la traza
lo dice (`fallback: no_client`). Modelos configurables por entorno para comparar en la evaluación.
"""
from __future__ import annotations

import os

from .graph import Agent
from .identity import IdentityService
from .llm import HAIKU, AnthropicClient, LLMClient, LLMError
from .llm_router import LLMRouter
from .llm_writer import LLMWriter
from .policy import PolicyEngine
from .responses import TemplateWriter
from .tools import BankTools
from .understanding import RuleRouter

ROUTERS = ("rules", "llm")
WRITERS = ("templates", "llm")


def make_llm_client(provider: str | None = None) -> LLMClient | None:
    """Único punto que conoce a los proveedores. Otro proveedor = otra rama aquí + su clase en llm.py."""
    provider = provider or os.environ.get("BANKAGENT_LLM_PROVIDER", "anthropic")
    if provider == "anthropic":
        try:
            return AnthropicClient()
        except LLMError:  # sin key o sin paquete: el agente sigue con la línea base
            return None
    raise ValueError(f"Proveedor LLM desconocido: {provider}")


def build_agent(db: str | BankTools, router: str = "rules", writer: str = "templates", *,
                identity: IdentityService | None = None, policy: PolicyEngine | None = None,
                llm_client: LLMClient | None = None, router_model: str | None = None,
                writer_model: str | None = None, **agent_kwargs) -> Agent:
    if router not in ROUTERS or writer not in WRITERS:
        raise ValueError(f"router ∈ {ROUTERS}, writer ∈ {WRITERS}")
    tools = db if isinstance(db, BankTools) else BankTools(db, identity or IdentityService())
    client = llm_client
    if client is None and "llm" in (router, writer):
        client = make_llm_client()
    r = RuleRouter() if router == "rules" else LLMRouter(
        client, model=router_model or os.environ.get("BANKAGENT_ROUTER_MODEL", HAIKU))
    w = TemplateWriter() if writer == "templates" else LLMWriter(
        client, model=writer_model or os.environ.get("BANKAGENT_WRITER_MODEL", HAIKU))
    return Agent(tools, policy or PolicyEngine(), router=r, writer=w, **agent_kwargs)
