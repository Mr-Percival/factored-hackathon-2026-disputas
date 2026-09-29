"""Ejecuta un caso contra un sistema (router + writer) con un cliente SIMULADO por guion.

- Cada caso corre con un Agent, un almacén de operaciones y una sesión nuevos (sin estado compartido).
- El "cliente" responde según el guion del caso: si el agente pregunta cuál transacción/tarjeta, elige
  la objetivo (si aparece en las opciones); si pide confirmación, responde lo que dice la etiqueta.
  Es una SIMULACIÓN de conversación, no tráfico real.
- Las acciones se leen del almacén ops (disputas y bloqueos realmente escritos), no de la respuesta.

Sistemas: `SYSTEMS` mapea un nombre a una fábrica (`--system b0|b1|rules|embeddings|llm|llm_router`).
Un router nuevo que implemente `Router` se agrega con una línea:
    SYSTEMS["embeddings"] = lambda: System("embeddings", EmbeddingsRouter(...), TemplateWriter(), uses_model=False)
o se pasa `--system paquete.modulo:fabrica` (o `ruta/archivo.py:fabrica`) al runner.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from ..graph import Agent
from ..identity import IdentityService
from ..policy import PolicyEngine
from ..responses import TemplateWriter
from ..tools import BankTools, ToolError
from ..understanding import RuleRouter
from .lexicon import ORDINAL

MAX_TURNS = 8
TERMINAL = {"resolved", "handoff", "rejected", "informed", "cancelled", "blocked", "auth_error"}
CARD_RX = re.compile(r"\*{4}\d{4}")
CLI_RX = re.compile(r"\bCLI-[A-Z0-9]{6,}\b")


@dataclass
class System:
    name: str
    router: object
    writer: object
    uses_model: bool = False
    meta: dict = field(default_factory=dict)
    # fábrica del agente a partir de (tools, policy); None = el Agent del grafo con router y writer
    build: Callable | None = None

    def make_agent(self, tools: BankTools, policy: PolicyEngine):
        if self.build:
            return self.build(tools, policy)
        return Agent(tools, policy, router=self.router, writer=self.writer)

    def describe(self) -> dict:
        info = {"system": self.name, "router": getattr(self.router, "name", type(self.router).__name__),
                "writer": getattr(self.writer, "name", type(self.writer).__name__), "uses_model": self.uses_model}
        for part in ("router", "writer"):
            obj = getattr(self, part)
            for attr in ("model", "prompt_version"):
                val = getattr(obj, attr, None) or getattr(sys.modules.get(type(obj).__module__), attr.upper(), None)
                if val:
                    info[f"{part}_{attr}"] = val
        return {**info, **self.meta}


def _llm_system(router: bool, writer: bool) -> System:
    """Router y/o writer con LLM (issues #6/#7). Sin key del proveedor NO se evalúa: caería a la línea base y
    el reporte mezclaría sistemas."""
    from ..factory import make_llm_client
    from ..llm_router import LLMRouter
    from ..llm_writer import LLMWriter
    client = make_llm_client()
    if client is None:
        raise RuntimeError("Sin cliente LLM (falta la key del proveedor): no se evalúa el sistema con LLM")
    name = "llm" if router and writer else "llm_router" if router else "llm_writer"
    return System(name, LLMRouter(client) if router else RuleRouter(), LLMWriter(client) if writer else TemplateWriter(),
                  uses_model=True)


def _b0() -> System:
    from .baselines import TransferAllRouter
    return System("b0", TransferAllRouter(), TemplateWriter(),
                  meta={"description": "B0: transfiere a humano todo pedido no trivial (mismo grafo)"})


def _b1() -> System:
    from .baselines import NaiveAutomationAgent
    return System("b1", RuleRouter(), TemplateWriter(), build=NaiveAutomationAgent,
                  meta={"description": "B1: automatización ingenua, sin política ni confirmación"})


def _embeddings() -> System:
    """Router aprendido por embeddings (#42). Cuando exista, completar aquí la importación."""
    try:
        from ..embeddings_router import EmbeddingsRouter  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError("El router por embeddings (#42) todavía no está en el repo") from e
    return System("embeddings", EmbeddingsRouter(), TemplateWriter(),
                  meta={"description": "Agente con router por embeddings + plantillas"})


SYSTEMS: dict[str, Callable[[], System]] = {
    "b0": _b0,
    "b1": _b1,
    "rules": lambda: System("rules", RuleRouter(), TemplateWriter(), uses_model=False,
                            meta={"description": "Agente v1: grafo + RuleRouter + plantillas (política y confirmación)"}),
    "embeddings": _embeddings,
    "llm": lambda: _llm_system(router=True, writer=True),
    "llm_router": lambda: _llm_system(router=True, writer=False),
}


def get_system(name: str) -> Callable[[], System]:
    if name in SYSTEMS:
        return SYSTEMS[name]
    if ":" in name:  # paquete.modulo:fabrica o ruta/archivo.py:fabrica -> System o (router, writer)
        mod, attr = name.rsplit(":", 1)
        if mod.endswith(".py"):
            spec = importlib.util.spec_from_file_location(os.path.splitext(os.path.basename(mod))[0], mod)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module  # dataclasses necesita el módulo registrado
            spec.loader.exec_module(module)
        else:
            module = importlib.import_module(mod)
        fn = getattr(module, attr)

        def factory():
            out = fn()
            return out if isinstance(out, System) else System(name, *out, uses_model=True)
        return factory
    raise KeyError(f"Sistema desconocido: {name}. Disponibles: {sorted(SYSTEMS)}")


# ---------------------------------------------------------------- fallas inyectadas
def _inject(tools: BankTools, fail: dict | None) -> None:
    if not fail:
        return
    real = getattr(tools, fail["tool"])
    calls = {"n": 0}
    if fail["mode"] == "persistent":
        def fn(*a, **k):
            raise ToolError("unavailable")
    elif fail["mode"] == "transient":
        def fn(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ToolError("unavailable")
            return real(*a, **k)
    elif fail["mode"] == "unverified":  # el core acepta la llamada pero no refleja el cambio
        def fn(token, transaction_id, reason, confirmed):
            return {"case_id": "DSP-NOVERIF", "transaction_id": transaction_id, "status": "Unknown", "verified": False}
    else:
        raise ValueError(fail["mode"])
    setattr(tools, fail["tool"], fn)


def _snapshot(tools: BankTools) -> set[tuple]:
    d = tools._ops.execute("SELECT 'dispute', transaction_id, customer_id FROM disputes").fetchall()
    b = tools._ops.execute("SELECT 'block', product_id, customer_id FROM card_blocks").fetchall()
    return set(d) | set(b)


# ---------------------------------------------------------------- cliente simulado
class ScriptedUser:
    def __init__(self, case: dict):
        self.case = case
        # "say": mensajes que el cliente envía mientras el caso sigue abierto; "say_after": vuelve a escribir
        # aunque el caso ya terminó (p. ej. reclama otra vez el mismo cargo)
        self.queue = [(t["when"], t["text"]) for t in case["turns"] if t["when"] in ("say", "say_after")]
        self.handlers = {t["when"]: t["text"] for t in case["turns"] if t["when"] not in ("say", "say_after")}
        self.uses = {"option": 0, "confirm": 0, "option_missing": 0}
        tgt = case.get("target") or {}
        self.target_key = tgt.get("transaction_id") or tgt.get("product_id")

    def _fill_option(self, template: str, n: int, cand: dict) -> str:
        lang = self.case["language"]
        return template.format(n=n, ordinal=ORDINAL[lang][n - 1], last4=(cand.get("product_number") or "")[-4:],
                               merchant=cand.get("merchant_name") or "")

    def next(self, i: int, state: dict) -> tuple[str, str] | None:
        if i == 0:
            return self.queue.pop(0)
        if state.get("outcome") == "auth_error":
            return None
        aw = state.get("awaiting")
        if state.get("outcome") in TERMINAL and not aw:
            return self.queue.pop(0) if self.queue and self.queue[0][0] == "say_after" else None
        if aw == "confirmation" and "confirm" in self.handlers and self.uses["confirm"] < 2:
            self.uses["confirm"] += 1
            return "confirm", self.handlers["confirm"]
        if aw == "option":
            cands = state.get("candidates") or []
            idx = next((j for j, c in enumerate(cands, 1)
                        if self.target_key and self.target_key in (c.get("transaction_id"), c.get("product_id"))), None)
            if idx and "option" in self.handlers and self.uses["option"] < 2:
                self.uses["option"] += 1
                return "option", self._fill_option(self.handlers["option"], idx, cands[idx - 1])
            if self.queue:
                return self.queue.pop(0)
            if "option_missing" in self.handlers and self.uses["option_missing"] < 1:
                self.uses["option_missing"] += 1
                return "option_missing", self.handlers["option_missing"]
            return None
        if self.queue:
            return self.queue.pop(0)
        return None


# ---------------------------------------------------------------- ejecución de un caso
def _usage(entries: list[dict], state: dict) -> dict | None:
    """Uso de modelo si el sistema lo expone (`trace[].llm` del grafo, o `usage`); None si no hay datos."""
    found = [e[k] for e in entries for k in ("llm", "usage") if isinstance(e.get(k), dict)]
    if isinstance(state.get("usage"), dict):
        found.append(state["usage"])
    if not found:
        return None
    keys = ("input_tokens", "output_tokens", "cost_usd")
    return {k: sum(float(u.get(k) or 0) for u in found) for k in keys}


def _leaks(case: dict, state: dict, own_labels: set[str]) -> list[str]:
    out = []
    reply = state.get("reply") or ""
    for lab in CARD_RX.findall(reply):
        if lab not in own_labels:
            out.append(f"tarjeta ajena {lab} en la respuesta")
    for cid in CLI_RX.findall(reply):
        if cid != case["customer_id"]:
            out.append(f"id de otro cliente {cid} en la respuesta")
    packet = str(state.get("handoff") or "")
    for m in (case.get("victim") or {}).get("markers", []):
        if m in reply or m in packet:
            out.append(f"dato de la víctima '{m}' expuesto")
    txn = state.get("txn") or {}
    if txn.get("customer_id") and txn["customer_id"] != case["customer_id"]:
        out.append("transacción de otro cliente en el estado")
    ptx = ((state.get("handoff") or {}).get("verified_facts") or {}).get("transaction") or {}
    if ptx.get("customer_id") and ptx["customer_id"] != case["customer_id"]:
        out.append("transacción de otro cliente en el paquete de handoff")
    return out


def run_case(case: dict, db: str, factory: Callable[[], System], run: int = 1) -> dict:
    system = factory()
    identity = IdentityService(ttl_seconds=900)
    tools = BankTools(db, identity)
    agent = system.make_agent(tools, PolicyEngine())
    cid = case["customer_id"]
    setup = case.get("setup") or {}
    token = "token-invalido" if setup.get("token") == "invalid" else identity.login(cid)
    _inject(tools, setup.get("fail"))
    own = {r[0] for r in tools._ro.execute("SELECT product_number FROM products WHERE customer_id = ?", [cid]).fetchall()}
    user, thread = ScriptedUser(case), f"{case['id']}-{uuid.uuid4().hex[:8]}"
    state: dict = {}
    turns, leaks, error = [], [], None
    usage_total: dict | None = None
    try:
        for i in range(MAX_TURNS):
            msg = user.next(i, state)
            if msg is None:
                break
            kind, text = msg
            if setup.get("expire_before_turn") == i + 1 and token in identity._sessions:
                identity.expire(token)
            before, awaiting_before = _snapshot(tools), state.get("awaiting")
            t0 = time.perf_counter()
            state = agent.chat(thread, token, text)
            ms = (time.perf_counter() - t0) * 1000
            new = sorted(_snapshot(tools) - before)
            entries = [e for e in state.get("trace", []) if e.get("turn") == state.get("turn")]
            u = _usage(entries, state)
            if u:
                usage_total = {k: (usage_total or {}).get(k, 0) + v for k, v in u.items()}
            und = state.get("understanding") or {}
            dec = state.get("decision") or {}
            turns.append({
                "n": i + 1, "kind": kind, "text": text, "awaiting_before": awaiting_before,
                "outcome": state.get("outcome"), "reply": state.get("reply"), "ms": round(ms, 2),
                "node_ms": round(sum(e["ms"] for e in entries), 2),
                "actions": [{"type": a[0], "id": a[1], "customer_id": a[2]} for a in new],
                "understanding": {"intent": und.get("intent"), "confidence": und.get("confidence"),
                                  "language": und.get("language"),
                                  "slots": {k: v for k, v in (und.get("slots") or {}).items() if v is not None}} if und else None,
                "decision_rule": (dec.get("rules") or [{}])[0].get("id") if dec else None,
                "handoff": state.get("handoff"),
                "candidates": [c.get("transaction_id") or c.get("product_id") for c in state.get("candidates") or []]
                if state.get("awaiting") == "option" else [],
            })
            leaks += _leaks(case, state, own)
    except Exception as e:  # un caso que rompe el agente es una falla que se reporta, no aborta la corrida
        error = f"{type(e).__name__}: {e}"
    last = turns[-1] if turns else {}
    final = "error" if error else last.get("outcome")
    rule = None
    if final == "handoff":
        rule = (last.get("handoff") or {}).get("reason")
    elif final in ("rejected", "informed"):
        rule = last.get("decision_rule")
    handoffs = [t["handoff"] for t in turns if t["outcome"] == "handoff"]
    return {
        "case_id": case["id"], "run": run, "system": system.name, "turns": turns, "final_outcome": final,
        "final_rule": rule, "escalated": bool(handoffs), "handoff": handoffs[-1] if handoffs else None,
        "actions": [a for t in turns for a in t["actions"]], "leaks": sorted(set(leaks)), "error": error,
        "latency_ms": round(sum(t["ms"] for t in turns), 2),
        "cost_usd": (usage_total or {}).get("cost_usd") if usage_total else (0.0 if not system.uses_model else None),
        "usage": usage_total,
    }
