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

Intent = Literal["dispute_charge", "block_card", "confirm", "deny", "unclear", "select_option", "out_of_scope", "unknown"]
INTENTS: tuple[str, ...] = ("dispute_charge", "block_card", "confirm", "deny", "unclear", "select_option", "out_of_scope",
                            "unknown")
# Sub-acciones que el cliente puede rechazar por separado dentro de una confirmación ("sí, pero no bloquees").
SUB_ACTIONS: tuple[str, ...] = ("block_card",)


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
    # Con awaiting="confirmation": sub-acciones que el cliente rechazó explícitamente (ej. ["block_card"]).
    # Un `confirm` con denials autoriza SOLO lo no rechazado; el grafo nunca actúa ante `unclear`.
    sub_action_denials: list[str] = field(default_factory=list)


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

# ---------------------------------------------------------------- confirmación tri-estado (#38)
# Por qué tablas y no "contiene sí": una confirmación mal leída ejecuta una acción que el cliente no pidió.
# Orden de lectura: (1) rechazos de sub-acción ("no bloquees") se sacan primero, así su "no" no cuenta como
# negación de todo; (2) se sacan las re-afirmaciones del reclamo ("no la reconozco"), cuyo "no" responde a
# otra pregunta; (3) con lo que queda: duda -> unclear; sí y no a la vez -> unclear; solo sí -> confirm;
# solo no -> deny. Todo lo demás es unclear: el grafo re-pregunta una vez y luego deriva a un humano.
SUB_ACTION_DENIALS: dict[str, list[str]] = {
    "block_card": [
        "no bloquees", "no la bloquees", "no me bloquees", "no bloquee", "no la bloquee", "no bloqueen",
        "no bloquear", "no la bloquear", "no quiero bloquear", "no quiero que bloquees", "no quiero que la bloquees",
        "no hace falta bloquear", "no hace falta el bloqueo", "no es necesario bloquear", "sin bloquear",
        "sin bloqueo", "sin el bloqueo", "no bloquees nada", "la tarjeta no", "la tarjeta dejala", "no me la bloquees",
        "no la bloquees che", "no bloquees la tarjeta", "no bloqueis",
        "nao bloqueie", "nao bloquear", "nao bloqueia", "nao quero bloquear", "nao precisa bloquear",
        "sem bloquear", "sem bloqueio", "o cartao nao", "nao bloqueie o cartao", "nao bloqueia o cartao",
    ],
}
# Frases que eligen SOLO la acción principal: son a la vez un sí (disputa) y un no (bloqueo).
ONLY_MAIN_ACTION = ["solo la disputa", "nada mas la disputa", "unicamente la disputa", "solamente la disputa",
                    "solo abrir la disputa", "solo abri la disputa", "solo abre la disputa", "solo el reclamo",
                    "solo disputa", "la disputa nada mas", "so a contestacao", "somente a contestacao",
                    "apenas a contestacao", "so contestar", "so a disputa", "apenas contestar"]
BOTH_ACTIONS = ["ambas", "ambos", "las dos", "los dos", "as duas", "os dois", "las dos cosas", "as duas coisas",
                "ambas cosas", "hace las dos", "haz las dos", "pode fazer as duas"]
AFFIRM = ["si", "sim", "claro", "dale", "ok", "okay", "okey", "confirmo", "confirmado", "confirma", "de acuerdo",
          "correcto", "adelante", "hacelo", "hazlo", "hacerlo", "de una", "listo", "procede", "proceda", "abrela",
          "abrila", "abrelo", "abre la disputa", "abri la disputa", "abrir la disputa", "por favor", "porfa",
          "afirmativo", "exacto", "perfecto", "obvio", "por supuesto", "claro que si", "vamos", "andale", "orale",
          "simon", "va", "sale", "vale", "yes", "yep", "bueno", "quiero", "si quiero", "si por favor", "dale nomas",
          "isso", "com certeza", "pode", "pode sim", "pode fazer", "pode abrir", "manda ver", "bora", "fechado",
          "beleza", "ta bom", "esta bem", "tudo bem", "certo", "confirmar", "abre", "abra", "quero", "sim quero",
          "e isso", "isso mesmo", "claro que sim", "por favor faca", "faca", "faz", "faz isso"]
DENY = ["no", "nao", "nop", "nope", "nel", "cancelar", "cancela", "cancelalo", "mejor no", "melhor nao", "nem pensar",
        "de ninguna manera", "para nada", "ninguna", "ninguno", "nenhuma", "nenhum", "negativo", "no quiero",
        "nao quero", "todavia no", "ainda nao", "dejalo", "deja asi", "olvidalo", "no gracias", "nao obrigado",
        "nao obrigada", "de jeito nenhum", "jamas", "nunca", "no hagas nada", "nao faca nada", "no la abras",
        "no abras", "nao abra", "ni loca", "ni loco", "ni en pedo", "ni a palos"]
HEDGE = ["no se", "nose", "nao sei", "sei la", "creo", "creo que si", "tal vez", "talvez", "quizas", "quiza", "capaz",
         "puede ser", "pode ser", "no estoy seguro", "no estoy segura", "no estoy muy seguro", "nao tenho certeza",
         "nao estou seguro", "nao estou segura", "acho", "acho que sim", "sera", "mmm", "hmm", "mm", "depende",
         "no entiendo", "nao entendi", "a lo mejor", "mas o menos", "mais ou menos", "no se si", "espera", "espere",
         "dejame pensar", "deixa eu pensar", "ni idea", "vou pensar", "lo pienso", "lo voy a pensar", "no se que",
         "no estoy convencido", "no estoy convencida",
         # "solo bloquea" pide una combinación que no se ofreció (bloqueo sin disputa): se re-pregunta
         "solo bloquea", "solo bloquear", "solo bloquea la tarjeta", "solo el bloqueo", "so bloquear",
         "so o bloqueio", "apenas bloquear"]
# "no la reconozco" repite el reclamo: su "no" no contesta la pregunta de confirmación.
RESTATEMENTS = [r"no (la |lo |le )?reconozco", r"no (la |lo )?hice", r"yo no (la |lo )?hice", r"no fui yo",
                r"yo no fui", r"nao (a |o )?reconheco", r"nao fui eu", r"nao (a |o )?fiz", r"eu nao fiz",
                r"no (la |lo )?autorice", r"nao autorizei", r"no es mia", r"no es mio", r"nao e minha", r"nao e meu"]
_CONFIRM_LEXICON = [(p, label) for label, words in (("hedge", HEDGE), ("yes", AFFIRM), ("no", DENY)) for p in words]


def _strip(t: str, phrases: list[str]) -> tuple[str, bool]:
    """Saca las frases (regex) del texto, la más larga primero ("no bloquees la tarjeta" antes que "no")."""
    hit = False
    for p in sorted(phrases, key=len, reverse=True):
        t, n = re.subn(rf"(?<![a-z]){p}(?![a-z])", " ", t)
        hit |= n > 0
    return t, hit


def _scan(t: str) -> set[str]:
    """Etiquetas (hedge/yes/no) presentes. La frase más larga gana y se consume: "no quiero" es un no, no un
    "quiero"; "no se" es duda, no un "no"; "claro que si" es un sí."""
    found = set()
    for phrase, label in sorted(_CONFIRM_LEXICON, key=lambda x: len(x[0]), reverse=True):
        t, n = re.subn(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", " ", t)
        if n:
            found.add(label)
    return found


def classify_confirmation(t: str) -> tuple[str | None, list[str]]:
    """Texto normalizado -> (confirm | deny | unclear | None, sub-acciones rechazadas).
    None = el mensaje no contiene ninguna señal de respuesta (el router sigue con las otras intenciones)."""
    rest, denials = t, []
    for action, phrases in SUB_ACTION_DENIALS.items():
        rest, hit = _strip(rest, [re.escape(x) for x in phrases])
        if hit:
            denials.append(action)
    rest, only_main = _strip(rest, [re.escape(x) for x in ONLY_MAIN_ACTION])
    if only_main and "block_card" not in denials:
        denials.append("block_card")
    rest, both = _strip(rest, [re.escape(x) for x in BOTH_ACTIONS])
    rest, restated = _strip(rest, RESTATEMENTS)
    labels = _scan(rest)
    yes = "yes" in labels or only_main or both
    no = "no" in labels
    if "hedge" in labels or "?" in rest:
        return "unclear", denials
    if yes and no:
        # "no, no la reconozco, ábrela": el "no" acompaña al reclamo repetido y el pedido es explícito
        return ("confirm" if restated else "unclear"), denials
    if yes:
        return "confirm", denials
    if no:
        # "no, no bloquees" / "no, no la reconozco": la acción principal sigue sin respuesta clara
        return ("unclear" if denials or restated else "deny"), denials
    if denials or restated:
        return "unclear", denials  # rechazó una parte o repitió el reclamo, pero no contestó por la principal
    return None, []


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


# "otro/outra/también": el cliente habla de OTRO movimiento, no contesta la pregunta pendiente.
OTHER_ITEM = ["otro", "otra", "outro", "outra", "tambien", "mais um", "mais uma", "ademas", "alem disso"]


def _is_new_request(t: str, slots: Slots, confirmation: str | None) -> bool:
    """Con una confirmación pendiente, ¿el mensaje es un pedido nuevo? Solo si nombra un reclamo Y (habla de
    otro movimiento o trae datos nuevos sin contestar sí/no). "sí, no reconozco ese cargo" contesta; "no
    reconozco otro cargo de 1200" es nuevo."""
    if not any(_has(t, k) for k in KEYWORDS["dispute_charge"] + KEYWORDS["block_card"]):
        return False
    if any(_has(t, k) for k in OTHER_ITEM):
        return True
    has_data = slots.amount is not None or slots.date_from is not None or slots.country is not None
    return has_data and confirmation not in ("confirm", "deny")


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
        # "no reconozco otro cargo de 50" no es un "no": es un pedido nuevo que descarta la acción pendiente.
        slots.amount = parse_amount(re.sub(r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b", " ", t))
        slots.date_from, slots.date_to = parse_dates(t, today)
        slots.country = next((v for k, v in COUNTRIES.items() if _has(t, k)), None)
        if awaiting == "confirmation":
            state, denials = classify_confirmation(t)
            if state and not _is_new_request(t, slots, state):
                return Understanding(state, 0.9, lang, sub_action_denials=denials)

        scored = PRODUCT_NAMES.sub(" ", t)
        scores = {i: sum(_has(scored, k) for k in KEYWORDS[i]) for i in ("dispute_charge", "block_card", "out_of_scope")}
        best = max(scores, key=scores.get)
        if scores[best] == 0:
            return Understanding("unknown", 0.2, lang, slots)
        ties = sum(1 for v in scores.values() if v == scores[best])
        conf = 0.85 if ties == 1 else 0.5
        return Understanding(best, conf, lang, slots)
