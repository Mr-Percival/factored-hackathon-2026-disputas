"""Construcción del agente por nombre, para la UI, el chat y el harness de evaluación.

    build_agent("data/serving.duckdb", router="llm", writer="llm")
    build_agent("data/serving.duckdb", router="embeddings")   # router aprendido local, sin API (ADR 0009)

Sin key del proveedor el agente igual funciona: los componentes LLM caen a reglas/plantillas y la traza
lo dice (`fallback: no_client`). Modelos configurables por entorno para comparar en la evaluación.
"""
from __future__ import annotations

import os
import threading
from dataclasses import replace

from .graph import Agent
from .identity import IdentityService
from .llm import HAIKU, AnthropicClient, LLMClient, LLMError
from .llm_router import LLMRouter
from .llm_writer import LLMWriter
from .policy import PolicyEngine
from .responses import TemplateWriter
from .tools import BankTools
from .understanding import RuleRouter

# embeddings      = router aprendido "lite" (n-gramas de caracteres + regresión logística; solo numpy, pocos MB)
# embeddings_full = char + MiniLM ONNX (solo evaluación offline: ~250 MB de modelo + onnxruntime). ADR 0009.
ROUTERS = ("rules", "embeddings", "embeddings_full", "llm")
WRITERS = ("templates", "llm")
_SHARED: dict[str, object] = {}
_SHARED_LOCK = threading.Lock()


class _RulesFallback(RuleRouter):
    """Router aprendido pedido pero sin su dependencia (numpy): responde la línea base y la traza lo dice."""

    name = "rules(fallback:model_unavailable)"

    def understand(self, text, today, awaiting):
        return replace(super().understand(text, today, awaiting), router=self.name)


def shared_router(kind: str = "embeddings"):
    """Una instancia por proceso: la API crea un Agent por sesión y el modelo no debe cargarse cada vez.
    HybridRouter no guarda estado de la conversación, así que compartirlo entre sesiones e hilos es seguro."""
    with _SHARED_LOCK:
        if kind not in _SHARED:
            try:
                from .embedding_router import HybridRouter
                from .intent_model import DEFAULT_DIR, FULL_DIR
            except ImportError:  # sin numpy (instalación sin el extra `ml`)
                _SHARED[kind] = _RulesFallback()
            else:
                env = os.environ.get("BANKAGENT_INTENT_MODEL_DIR")
                _SHARED[kind] = HybridRouter(model_dir=env or (FULL_DIR if kind == "embeddings_full" else DEFAULT_DIR))
        return _SHARED[kind]


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
    if router == "rules":
        r = RuleRouter()
    elif router in ("embeddings", "embeddings_full"):
        r = shared_router(router)
    else:
        r = LLMRouter(client, model=router_model or os.environ.get("BANKAGENT_ROUTER_MODEL", HAIKU))
    w = TemplateWriter() if writer == "templates" else LLMWriter(
        client, model=writer_model or os.environ.get("BANKAGENT_WRITER_MODEL", HAIKU))
    return Agent(tools, policy or PolicyEngine(), router=r, writer=w, **agent_kwargs)
