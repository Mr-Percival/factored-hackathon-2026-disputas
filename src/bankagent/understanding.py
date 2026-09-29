"""Entendimiento del mensaje: intención + idioma + datos (slots).

`Router` es la interfaz; hay que poder cambiar la implementación sin tocar el grafo:
- RuleRouter  : reglas y palabras clave (LÍNEA BASE, sin red, determinista)
- JevRouter   : modelo de decisión Jev (pendiente)
- LLMRouter   : LLM con salida estructurada (`llm_router.py`), cae a RuleRouter ante cualquier falla
Todas devuelven el mismo `Understanding`; el grafo decide qué hacer según `confidence`.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal, Protocol

Intent = Literal["dispute_charge", "block_card", "confirm", "deny", "select_option", "out_of_scope", "unknown"]
INTENTS: tuple[str, ...] = ("dispute_charge", "block_card", "confirm", "deny", "select_option", "out_of_scope", "unknown")


@dataclass
class Slots:
    amount: float | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    country: str | None = None
    option: int | None = None  # "la 2", "opção 1"


@dataclass
class Understanding:
    intent: Intent
    confidence: float
    language: Literal["es", "pt"]
    slots: Slots = field(default_factory=Slots)
    router: str = "rules"
    llm: dict | None = None  # telemetría del modelo (versión, tokens, latencia, costo) si hubo llamada


class Router(Protocol):
    def understand(self, text: str, today: dt.date, awaiting: str | None) -> Understanding: ...


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


PT_MARKERS = {"nao", "voce", "cobranca", "cartao", "reconheco", "ontem", "obrigado", "obrigada", "compra", "meu",
              "minha", "bloquear", "sim", "hoje", "semana passada", "estou", "fui", "cobrado", "cobraram", "tenho"}
ES_MARKERS = {"no", "usted", "cobro", "tarjeta", "reconozco", "ayer", "gracias", "mi", "bloquear", "si", "hoy",
              "semana pasada", "estoy", "me cobraron", "tengo", "cargo"}

KEYWORDS: dict[str, list[str]] = {
    "dispute_charge": ["no reconozco", "no reconheco", "cargo", "cobro", "cobranca", "cobraram", "me cobraron",
                       "disputa", "contestar", "fraude", "no hice", "nao fiz", "no fui yo", "nao fui eu", "desconozco"],
    "block_card": ["bloquear", "bloqueia", "bloquea", "robaron", "roubaram", "perdi", "extravi"],
    "confirm": ["si", "sim", "confirmo", "de acuerdo", "dale", "ok", "correcto", "pode", "claro"],
    "deny": ["no", "nao", "cancelar", "mejor no", "melhor nao"],
    "out_of_scope": ["credito", "prestamo", "emprestimo", "hipoteca", "inversion", "investimento", "seguro", "tasa"],
}

COUNTRIES = {"brasil": "Brazil", "brazil": "Brazil", "mexico": "México", "colombia": "Colombia", "argentina": "Argentina",
             "espana": "Spain", "estados unidos": "USA", "eeuu": "USA", "eua": "USA"}


def detect_language(text: str) -> Literal["es", "pt"]:
    t = _norm(text)
    words = set(re.findall(r"[a-z]+", t))
    pt = sum(1 for m in PT_MARKERS if (m in t if " " in m else m in words))
    es = sum(1 for m in ES_MARKERS if (m in t if " " in m else m in words))
    return "pt" if pt > es else "es"


def _has(t: str, kw: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(kw)}(?![a-z])", t) is not None


def parse_amount(t: str) -> float | None:
    m = re.search(r"(?:\$|usd|mxn|cop|ars|r\$)?\s*(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)", t)
    if not m:
        return None
    raw, dec = m.group(1), ""
    # "1.200" / "1,200" son miles; "350,50" / "1.200,50" terminan en decimales
    tail = re.fullmatch(r"(.+?)[.,](\d{1,2})", raw)
    if tail and not re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw):
        raw, dec = tail.group(1), tail.group(2)
    return float(re.sub(r"[.,]", "", raw) + (f".{dec}" if dec else ""))


def parse_dates(t: str, today: dt.date) -> tuple[dt.date | None, dt.date | None]:
    if _has(t, "hoy") or _has(t, "hoje"):
        return today, today
    if _has(t, "ayer") or _has(t, "ontem"):
        d = today - dt.timedelta(days=1)
        return d, d
    if "semana pasada" in t or "semana passada" in t:
        return today - dt.timedelta(days=14), today - dt.timedelta(days=7)
    if "este mes" in t or "este mes" in t or "esse mes" in t:
        return today.replace(day=1), today
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else today.year
        y = y + 2000 if y < 100 else y
        try:
            day = dt.date(y, mo, d)
            return day, day
        except ValueError:
            return None, None
    return None, None


class RuleRouter:
    """Línea base: palabras clave es/pt + expresiones regulares. Confianza = claridad de la coincidencia."""

    name = "rules"

    def understand(self, text: str, today: dt.date, awaiting: str | None) -> Understanding:
        t = _norm(text)
        lang = detect_language(text)
        slots = Slots()
        # Respuestas cortas a una pregunta pendiente del agente
        if awaiting == "option":
            m = re.search(r"\b([1-9])\b", t)
            if m and len(t) <= 40:
                return Understanding("select_option", 0.95, lang, Slots(option=int(m.group(1))))
        # "no reconozco otro cargo de 50" no es un "no": es un pedido nuevo que descarta la acción pendiente.
        words = len(re.findall(r"[a-z0-9]+", t))
        new_request = words > 3 and any(_has(t, k) for k in KEYWORDS["dispute_charge"] + KEYWORDS["block_card"])
        if awaiting == "confirmation" and not new_request:
            if any(_has(t, k) for k in KEYWORDS["deny"]) and not any(_has(t, k) for k in ("si", "sim")):
                return Understanding("deny", 0.9, lang)
            if any(_has(t, k) for k in KEYWORDS["confirm"]):
                return Understanding("confirm", 0.9, lang)

        slots.amount = parse_amount(re.sub(r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b", " ", t))
        slots.date_from, slots.date_to = parse_dates(t, today)
        slots.country = next((v for k, v in COUNTRIES.items() if _has(t, k)), None)

        scores = {i: sum(_has(t, k) for k in KEYWORDS[i]) for i in ("dispute_charge", "block_card", "out_of_scope")}
        best = max(scores, key=scores.get)
        if scores[best] == 0:
            return Understanding("unknown", 0.2, lang, slots)
        ties = sum(1 for v in scores.values() if v == scores[best])
        conf = 0.85 if ties == 1 else 0.5
        return Understanding(best, conf, lang, slots)
