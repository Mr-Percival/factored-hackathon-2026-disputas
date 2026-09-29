"""Entendimiento del mensaje: intención + idioma + datos (slots).

`Router` es la interfaz; hay que poder cambiar la implementación sin tocar el grafo:
- RuleRouter  : reglas y palabras clave (LÍNEA BASE, sin red, determinista)
- JevRouter   : modelo de decisión Jev (pendiente)
- ClaudeRouter: LLM con salida estructurada (pendiente)
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


class Router(Protocol):
    def understand(self, text: str, today: dt.date, awaiting: str | None) -> Understanding: ...


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


PT_MARKERS = {"nao", "voce", "cobranca", "cartao", "reconheco", "ontem", "obrigado", "obrigada", "compra", "meu",
              "minha", "bloquear", "sim", "hoje", "semana passada", "estou", "fui", "cobrado", "cobraram", "tenho"}
ES_MARKERS = {"no", "usted", "cobro", "tarjeta", "reconozco", "ayer", "gracias", "mi", "bloquear", "si", "hoy",
              "semana pasada", "estoy", "me cobraron", "tengo", "cargo"}

# Un "*" final indica prefijo (bloque* = bloquear, bloqueen, bloqueala, bloqueie...).
# Ajustes 2026-09-28 (issue #13): variantes de es-AR/es-CO/pt-BR y errores comunes vistos SOLO en el split dev.
KEYWORDS: dict[str, list[str]] = {
    "dispute_charge": ["no reconozco", "no reconosco", "nao reconheco", "no reconheco", "cargo", "cobro", "cobranca",
                       "cobraram", "me cobraron", "disput*", "contestar", "fraude", "no hice", "no lo hice", "nao fiz",
                       "no fui yo", "nao fui eu", "desconozco", "desconocer", "no autorice", "no es mio", "nao e minha"],
    "block_card": ["bloque*", "robaron", "roubaram", "roubad*", "perdi*", "extravi*", "afanaron"],
    "confirm": ["si", "sim", "confirmo", "de acuerdo", "dale", "ok", "correcto", "pode", "claro", "va", "orale",
                "adelante", "listo", "de una", "obvio", "isso", "beleza", "hazlo", "procede"],
    "deny": ["no", "nao", "cancelar", "mejor no", "melhor nao", "nel", "deja", "dejalo", "deixa"],
    "out_of_scope": ["credito", "prestamo", "emprestimo", "hipoteca", "inversion", "invertir", "investimento", "investir",
                     "aplicacao", "seguro", "tasa", "saldo", "plazo fijo", "cdt", "cupo", "limite", "direccion", "endereco"],
}
# "tarjeta de crédito" nombra el producto, no pide un crédito
PRODUCT_NAMES = re.compile(r"(tarjeta|cartao|targeta) de (credito|debito)")
ORDINALS = {"primera": 1, "primeira": 1, "segunda": 2, "tercera": 3, "terceira": 3, "cuarta": 4, "quarta": 4,
            "quinta": 5}
MONTHS = {m: i for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                      "septiembre", "octubre", "noviembre", "diciembre"], 1)}
MONTHS.update({m: i for i, m in enumerate(["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
                                           "setembro", "outubro", "novembro", "dezembro"], 1)})
WEEKDAYS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6,
            "segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4}
# Frases de fecha que contienen números y no son montos ("hace 3 días", "el 9 de junio")
DATE_NUMBERS = re.compile(r"\b(hace|ha) \d+ dias?\b|\b\d{1,2} de (" + "|".join(MONTHS) + r")\b")

COUNTRIES = {"brasil": "Brazil", "brazil": "Brazil", "mexico": "México", "colombia": "Colombia", "argentina": "Argentina",
             "espana": "Spain", "estados unidos": "USA", "eeuu": "USA", "eua": "USA"}


def detect_language(text: str) -> Literal["es", "pt"]:
    t = _norm(text)
    words = set(re.findall(r"[a-z]+", t))
    pt = sum(1 for m in PT_MARKERS if (m in t if " " in m else m in words))
    es = sum(1 for m in ES_MARKERS if (m in t if " " in m else m in words))
    return "pt" if pt > es else "es"


def _has(t: str, kw: str) -> bool:
    if kw.endswith("*"):
        return re.search(rf"(?<![a-z]){re.escape(kw[:-1])}[a-z]*", t) is not None
    return re.search(rf"(?<![a-z]){re.escape(kw)}(?![a-z])", t) is not None


def parse_amount(t: str) -> float | None:
    t = DATE_NUMBERS.sub(" ", t)
    m = re.search(r"(?:\$|usd|mxn|cop|ars|r\$)?\s*(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
                  r"(\s*(?:mil\b|lucas\b|millon\w*|milh\w*))?", t)
    if not m:
        return None
    raw, dec = m.group(1), ""
    mult = m.group(2)
    if mult and re.fullmatch(r"\d+[.,]\d", raw):  # "1,2 millones"
        raw, dec = raw[:-2], raw[-1]
    else:
        # "1.200" / "1,200" son miles; "350,50" / "1.200,50" terminan en decimales
        tail = re.fullmatch(r"(.+?)[.,](\d{1,2})", raw)
        if tail and not re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw):
            raw, dec = tail.group(1), tail.group(2)
    value = float(re.sub(r"[.,]", "", raw) + (f".{dec}" if dec else ""))
    if mult:
        value *= 1_000_000 if mult.strip().startswith(("millon", "milh")) else 1000
    return value


def _past(day: dt.date, today: dt.date) -> dt.date:
    """Una fecha sin año que caería en el futuro se refiere al año anterior."""
    return day.replace(year=day.year - 1) if day > today else day


def parse_dates(t: str, today: dt.date) -> tuple[dt.date | None, dt.date | None]:
    if _has(t, "hoy") or _has(t, "hoje"):
        return today, today
    if _has(t, "ayer") or _has(t, "ontem"):
        d = today - dt.timedelta(days=1)
        return d, d
    if any(_has(t, k) for k in ("antier", "anteayer", "anteontem", "antes de ayer")):
        d = today - dt.timedelta(days=2)
        return d, d
    m = re.search(r"\b(?:hace|ha) (\d+) dias?\b", t)
    if m:
        d = today - dt.timedelta(days=int(m.group(1)))
        return d, d
    m = re.search(r"\b(\d{1,2}) de (" + "|".join(MONTHS) + r")\b", t)
    if m:
        try:
            d = _past(dt.date(today.year, MONTHS[m.group(2)], int(m.group(1))), today)
            return d, d
        except ValueError:
            return None, None
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
            day = dt.date(y, mo, d) if m.group(3) else _past(dt.date(y, mo, d), today)
            return day, day
        except ValueError:
            return None, None
    m = re.search(r"\b(?:el|na|no) (" + "|".join(WEEKDAYS) + r")\b", t)
    if m:  # "el martes" = el último martes antes de hoy
        back = (today.weekday() - WEEKDAYS[m.group(1)]) % 7 or 7
        d = today - dt.timedelta(days=back)
        return d, d
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
            o = next((v for k, v in ORDINALS.items() if _has(t, k)), None)
            if o and len(t) <= 40:
                return Understanding("select_option", 0.9, lang, Slots(option=o))
        if awaiting == "confirmation":
            if any(_has(t, k) for k in KEYWORDS["deny"]) and not any(_has(t, k) for k in ("si", "sim")):
                return Understanding("deny", 0.9, lang)
            if any(_has(t, k) for k in KEYWORDS["confirm"]):
                return Understanding("confirm", 0.9, lang)

        slots.amount = parse_amount(re.sub(r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b", " ", t))
        slots.date_from, slots.date_to = parse_dates(t, today)
        slots.country = next((v for k, v in COUNTRIES.items() if _has(t, k)), None)

        scored = PRODUCT_NAMES.sub(" ", t)
        scores = {i: sum(_has(scored, k) for k in KEYWORDS[i]) for i in ("dispute_charge", "block_card", "out_of_scope")}
        best = max(scores, key=scores.get)
        if scores[best] == 0:
            return Understanding("unknown", 0.2, lang, slots)
        ties = sum(1 for v in scores.values() if v == scores[best])
        conf = 0.85 if ties == 1 else 0.5
        return Understanding(best, conf, lang, slots)
