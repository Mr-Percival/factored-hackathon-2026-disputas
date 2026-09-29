"""Motor de política determinista.

Lee config/policy.yaml y decide sobre una disputa con hechos verificados (salida de herramientas).
Las condiciones `when` son expresiones restringidas: solo comparaciones, and/or/not, atributos,
índices y constantes (se valida el AST; no hay llamadas a funciones ni eval libre).
La decisión incluye TODAS las reglas que se cumplieron, así la explicación sale de reglas, no del modelo.
"""
from __future__ import annotations

import ast
import datetime as dt
import os
from dataclasses import dataclass, field
from types import SimpleNamespace

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POLICY = os.path.join(ROOT, "config", "policy.yaml")

_ALLOWED = (ast.Expression, ast.Compare, ast.BoolOp, ast.UnaryOp, ast.Not, ast.And, ast.Or, ast.Attribute,
            ast.Subscript, ast.Name, ast.Constant, ast.Load, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt,
            ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn)


def _compile(expr: str):
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ValueError(f"Expresión no permitida en política: {expr!r} ({type(node).__name__})")
        # Bloquea la introspección (__class__, __globals__...), vía clásica para escapar de un eval restringido.
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError(f"Atributo privado no permitido en política: {node.attr!r}")
    return compile(tree, "<policy>", "eval")


@dataclass
class RuleHit:
    id: str
    outcome: str
    explain: str


@dataclass
class Decision:
    outcome: str  # auto_with_confirmation | inform | reject | handoff
    policy_version: str
    hits: list[RuleHit] = field(default_factory=list)

    @property
    def deciding_rule(self) -> RuleHit | None:
        return self.hits[0] if self.hits else None


class PolicyEngine:
    def __init__(self, path: str = POLICY):
        with open(path, encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)
        self.version = self.cfg["version"]
        self.as_of = dt.date.fromisoformat(self.cfg["as_of"])
        self.rules = [(r, _compile(r["when"])) for r in self.cfg["dispute"]["rules"]]

    def requires_confirmation(self, action: str) -> bool:
        return self.cfg["actions"][action]["requires_confirmation"]

    def decide_dispute(self, txn: dict, customer: dict, history: dict) -> Decision:
        txn_date = txn["transaction_date"]
        txn_date = txn_date.date() if isinstance(txn_date, dt.datetime) else txn_date
        ctx = {
            "txn": SimpleNamespace(**{k: (float(v) if k in ("amount", "fraud_score") and v is not None else v)
                                      for k, v in txn.items()}),
            "customer": SimpleNamespace(**customer),
            "history": SimpleNamespace(**history),
            "txn_age_days": (self.as_of - txn_date).days,
            "txn_already_disputed": txn["transaction_id"] in history.get("open_dispute_transactions", []),
            "high_amount": self.cfg["dispute"]["high_amount"],
        }
        hits = [RuleHit(r["id"], r["outcome"], r["explain"])
                for r, code in self.rules if eval(code, {"__builtins__": {}}, ctx)]  # noqa: S307 (AST validado)
        # Prioridad: la primera regla que se cumple, en el orden del archivo.
        outcome = hits[0].outcome if hits else "auto_with_confirmation"
        return Decision(outcome, self.version, hits)
