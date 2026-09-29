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

Intent = Literal["dispute_charge", "block_card", "confirm", "deny", "unclear", "select_option", "none_of_these",
                 "human_request", "account_takeover", "dispute_status", "cancel_dispute", "closing", "out_of_scope",
                 "unknown"]
INTENTS: tuple[str, ...] = ("dispute_charge", "block_card", "confirm", "deny", "unclear", "select_option",
                            "none_of_these", "human_request", "account_takeover", "dispute_status", "cancel_dispute",
                            "closing", "out_of_scope", "unknown")
# Sub-acciones que el cliente puede rechazar por separado dentro de una confirmación ("sí, pero no bloquees").
SUB_ACTIONS: tuple[str, ...] = ("block_card",)


@dataclass
class Slots:
    amount: float | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    country: str | None = None
    option: int | None = None  # "la 2", "opção 1"; -1 = "la última"
    case_id: str | None = None  # "DSP-…" mencionado por el cliente (nunca se lee como monto)
    count: int | None = None  # "3 cargos de 20": cuántos movimientos dice el cliente (el 3 no es el monto)
    # Comercio: el router puede proponer texto libre; el grafo lo resuelve SOLO contra los comercios del propio
    # cliente (`match_merchant`), nunca contra una lista global.
    merchant: str | None = None
    # Tarjeta que nombró el cliente: últimos 4 dígitos, o "?" si escribió un número completo (se enmascara antes de
    # llegar aquí). El grafo solo ofrece bloquear una tarjeta PROPIA que coincida (red team #33).
    card_hint: str | None = None


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


# Marcadores de idioma: solo palabras que distinguen es de pt (no "compra", "bloquear", "dolares", que son de ambos).
# Un mensaje sin marcadores o empatado ("ok", "1", "confirmo") no decide: hereda el idioma de la sesión (#39).
PT_MARKERS = {"nao", "voce", "voces", "cobranca", "cartao", "cartoes", "reconheco", "desconheco", "desconhecido",
              "ontem", "obrigado", "obrigada", "valeu", "meu", "minha", "meus", "minhas", "sim", "hoje", "semana passada",
              "estou", "cobrado", "cobraram", "tenho", "quero", "falar", "atendente", "um", "uma", "essa", "esse",
              "isso", "fatura", "lancamento", "contestacao", "pode", "tambem", "oi", "ola", "tchau", "preciso",
              "gostaria", "ajuda", "reais", "estranha", "estranho", "apareceu", "fiz", "sei", "acho", "certeza",
              "bloqueie", "roubaram", "roubado", "roubada", "clonaram", "pessoa", "nem", "ja", "agora", "conta",
              "dinheiro", "autorizei", "vou", "qual", "obrigadao", "beleza", "tudo", "fazer", "duas", "dois", "vezes",
              "alguem", "cobrou"}
ES_MARKERS = {"no", "usted", "cobro", "tarjeta", "reconozco", "desconozco", "ayer", "gracias", "mi", "mis", "si",
              "hoy", "semana pasada", "estoy", "me cobraron", "tengo", "cargo", "quiero", "hablar", "persona", "asesor",
              "una", "un", "el", "los", "las", "yo", "esa", "ese", "eso", "cuenta", "hice", "pero", "ahora", "hola",
              "buenas", "che", "vos", "sos", "tenes", "queres", "podes", "hacelo", "necesito", "ayuda", "movimiento",
              "autorice", "robaron", "clonaron", "ninguna", "ninguno", "dinero", "pesos", "cual",
              "muchas", "porfa", "hacer", "listo", "dale", "ya", "tambien"}

# Un "*" final indica prefijo (bloque* = bloquear, bloqueen, bloqueala, bloqueie...).
# Ajustes 2026-09-28 (issue #13): variantes de es-AR/es-CO/pt-BR y errores comunes vistos SOLO en el split dev.
KEYWORDS: dict[str, list[str]] = {
    "dispute_charge": ["no reconozco", "no reconosco", "nao reconheco", "no reconheco", "cargo", "cobro", "cobranca",
                       "cobraram", "me cobraron", "disput*", "contestar", "fraude", "no hice", "no lo hice", "nao fiz",
                       "no fui yo", "nao fui eu", "desconozco", "desconocer", "no autorice", "no es mio", "nao e minha",
                       # pt-BR natural (#39): "vi um lançamento desconhecido", "compra estranha na fatura"
                       "desconhec*", "nao autorizei", "nao autorizad*", "estranh*", "contestacao",
                       "nao reconhe*", "no reconoc*", "no autoric*", "cargo raro", "cobro raro", "movimiento raro",
                       "yo no fui", "pero yo no fui", "aclaracion", "levantar un reporte", "cargo indebido",
                       "cobro indebido", "cobranca indevida"],
    "block_card": ["bloque*", "robaron", "roubaram", "roubad*", "perdi*", "extravi*", "afanaron", "robada", "robado",
                   "reportar como robada", "reportarla", "reportar mi tarjeta", "desactiv*", "congelar", "congela"],
    "out_of_scope": ["credito", "prestamo", "emprestimo", "hipoteca", "inversion", "invertir", "investimento", "investir",
                     "aplicacao", "seguro", "seguros", "tasa", "saldo", "plazo fijo", "cdt", "cupo", "limite", "direccion",
                     "endereco", "cbu", "clabe", "tarjeta adicional", "cartao adicional", "extracto", "chequera", "pix"],
}
# "tarjeta de crédito" nombra el producto, no pide un crédito
PRODUCT_NAMES = re.compile(r"(tarjeta|cartao|targeta) de (credito|debito)")
# -1 = la última de la lista ("la última", "o último"); el grafo la resuelve contra las opciones mostradas.
ORDINALS = {"primera": 1, "primeira": 1, "segunda": 2, "tercera": 3, "terceira": 3, "cuarta": 4, "quarta": 4,
            "quinta": 5, "primero": 1, "primeiro": 1, "segundo": 2, "tercero": 3, "terceiro": 3, "cuarto": 4,
            "quinto": 5, "ultim*": -1}
MONTHS = {m: i for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                      "septiembre", "octubre", "noviembre", "diciembre"], 1)}
MONTHS.update({m: i for i, m in enumerate(["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
                                           "setembro", "outubro", "novembro", "dezembro"], 1)})
WEEKDAYS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6,
            "segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4}
# Frases de fecha que contienen números y no son montos ("hace 3 días", "el 9 de junio")
DATE_NUMBERS = re.compile(r"\b(hace|ha|faz) \d+ (dias?|semanas?|mes|meses)\b|\b\d{1,2} de (" + "|".join(MONTHS) + r")\b")
# Números en palabra para "hace tres semanas", "3 cargos", "há duas semanas".
NUMBER_WORDS = {"un": 1, "uno": 1, "una": 1, "um": 1, "uma": 1, "dos": 2, "dois": 2, "duas": 2, "tres": 3,
                "cuatro": 4, "quatro": 4, "cinco": 5, "seis": 6, "siete": 7, "sete": 7, "ocho": 8, "oito": 8,
                "nueve": 9, "nove": 9, "diez": 10, "dez": 10, "quince": 15, "quinze": 15}
_NUM = r"(\d+|" + "|".join(NUMBER_WORDS) + r")"
# "3 cargos", "dos cobros", "duas compras": cantidad de movimientos, no monto
COUNT = re.compile(_NUM + r" (cargos|cobros|compras|movimientos|transacciones|consumos|cobrancas|lancamentos|"
                          r"debitos|veces|vezes)\b")
# Referencias a la tarjeta o IDs: nunca son montos ("mi tarjeta 4152", "terminada en 4152", "DSP-123")
NOT_AMOUNTS = re.compile(r"\b(tarjeta|cartao|terminad[ao] en|terminad[ao] em|final|finalizad[ao] em)\s+(\*+)?\d{4}\b"
                         r"|\*+\d{2,4}|\b(dsp|trx|cli|hnd)-?[a-z0-9]{3,}\b")


def _int(word: str) -> int:
    return int(word) if word.isdigit() else NUMBER_WORDS[word]


def parse_count(t: str) -> int | None:
    m = COUNT.search(t)
    return _int(m.group(1)) if m and _int(m.group(1)) > 1 else None


def amount_text(t: str) -> str:
    """El texto sin lo que parece número pero no es monto: fechas dd/mm, IDs, tarjeta, cantidades."""
    t = NOT_AMOUNTS.sub(" ", t)
    t = COUNT.sub(r" \2", t)
    return re.sub(r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b", " ", t)


# Comercios: palabras que por sí solas no identifican a un comercio ("una tienda", "el super").
MERCHANT_STOPWORDS = {"de", "del", "la", "el", "los", "las", "y", "e", "do", "da", "tienda", "comercio", "servicio",
                      "servicios", "centro", "estacion", "restaurante", "super", "mercado", "store", "shop", "cafe"}


def _tokens(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", _norm(s)) if len(w) >= 3]


def match_merchant(text: str, names: list[str]) -> list[str]:
    """Comercios del cliente nombrados en el texto. Coincide si TODAS las palabras significativas del comercio
    están en el mensaje (con tolerancia a plural/typo leve por prefijo de 5 letras). Por qué exigir todas:
    "tienda" no debe elegir entre "Tienda General" y "Tienda Don José"; "Gasolinera Express" sí es uno."""
    words = set(_tokens(text))
    out = []
    for name in names:
        sig = [w for w in _tokens(name) if w not in MERCHANT_STOPWORDS] or _tokens(name)
        if sig and all(any(x == w or (len(w) >= 5 and x.startswith(w[:5])) for x in words) for w in sig):
            out.append(name)
    return out

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
        # inglés en medio de una conversación en español/portugués (red team #33)
        "don't block", "dont block", "do not block", "not block", "no block", "without blocking", "without block",
    ],
}
# Objeto opcional que sigue al rechazo ("no me bloquees LA TARJETA"): se consume con la frase.
_DENIAL_OBJECT = r"(?:\s+(?:la|mi|el|o|a|meu|minha|my|the|su|tu)?\s*(?:tarjeta|targeta|cartao|card|plastico))?"
# Frases que eligen SOLO la acción principal: son a la vez un sí (disputa) y un no (bloqueo).
ONLY_MAIN_ACTION = ["solo la disputa", "nada mas la disputa", "unicamente la disputa", "solamente la disputa",
                    "solo abrir la disputa", "solo abri la disputa", "solo abre la disputa", "solo el reclamo",
                    "solo disputa", "la disputa nada mas", "so a contestacao", "somente a contestacao",
                    "apenas a contestacao", "so contestar", "so a disputa", "apenas contestar",
                    "only the dispute", "just the dispute", "dispute only", "only dispute"]
BOTH_ACTIONS = ["ambas", "ambos", "las dos", "los dos", "as duas", "os dois", "las dos cosas", "as duas coisas",
                "ambas cosas", "hace las dos", "haz las dos", "pode fazer as duas"]
AFFIRM = ["si", "sim", "claro", "dale", "ok", "okay", "okey", "confirmo", "confirmado", "confirma", "de acuerdo",
          "correcto", "adelante", "hacelo", "hazlo", "hacerlo", "de una", "listo", "procede", "proceda", "abrela",
          "abrila", "abrelo", "abre la disputa", "abri la disputa", "abrir la disputa", "por favor", "porfa",
          "afirmativo", "exacto", "perfecto", "obvio", "por supuesto", "claro que si", "vamos", "andale", "orale",
          "simon", "va", "sale", "vale", "yes", "yep", "bueno", "si quiero", "si por favor", "dale nomas",
          "isso", "com certeza", "pode", "pode sim", "pode fazer", "pode abrir", "manda ver", "bora", "fechado",
          "beleza", "ta bom", "esta bem", "tudo bem", "certo", "confirmar", "abre", "abra", "sim quero",
          "e isso", "isso mesmo", "claro que sim", "por favor faca", "faca", "faz", "faz isso", "pode ser",
          # confirmaciones regionales: "joya" (AR), "de diez", "bárbaro", "genial" responden a la pregunta pendiente
          "joya", "joia", "de diez", "barbaro", "genial", "buenisimo", "excelente", "perfeito", "otimo", "demais"]
DENY = ["no", "nao", "nop", "nope", "nel", "cancelar", "cancela", "cancelalo", "mejor no", "melhor nao", "nem pensar",
        "de ninguna manera", "para nada", "ninguna", "ninguno", "nenhuma", "nenhum", "negativo", "no quiero",
        "nao quero", "todavia no", "ainda nao", "dejalo", "deja asi", "olvidalo", "no gracias", "nao obrigado",
        "nao obrigada", "de jeito nenhum", "jamas", "nunca", "no hagas nada", "nao faca nada", "no la abras", "deja",
        "deixa", "deixa pra la",
        "no abras", "nao abra", "ni loca", "ni loco", "ni en pedo", "ni a palos",
        # negación en inglés y "ni" (red team #33: "yes but do NOT block", "no bloquees ni abras nada")
        "not", "don't", "dont", "do not", "never", "never mind", "nevermind", "no way", "cancel", "cancel that",
        "stop", "ni",
        # "sí, la reconozco" = el cargo es suyo: nunca es un sí a la disputa
        "la reconozco", "lo reconozco", "si la reconozco", "si lo reconozco", "ya la reconoci", "ya lo reconoci",
        "reconheco sim", "eu reconheco", "ja reconheci", "era mia", "era mio", "era minha", "era meu", "fui yo",
        "fui eu"]
HEDGE = ["no se", "nose", "nao sei", "sei la", "creo", "creo que si", "tal vez", "talvez", "quizas", "quiza", "capaz",
         "puede ser", "no estoy seguro", "no estoy segura", "no estoy muy seguro", "nao tenho certeza",
         "nao estou seguro", "nao estou segura", "acho", "acho que sim", "sera", "mmm", "hmm", "mm", "depende",
         "no entiendo", "nao entendi", "a lo mejor", "mas o menos", "mais ou menos", "no se si", "espera", "espere",
         "dejame pensar", "deixa eu pensar", "ni idea", "vou pensar", "lo pienso", "lo voy a pensar", "no se que",
         "no estoy convencido", "no estoy convencida", "maybe", "not sure", "perhaps", "i guess",
         # retractarse en broma: "sí... es broma"
         "kidding", "just kidding", "es broma", "era broma", "brincadeira", "zoeira",
         # "solo bloquea" pide una combinación que no se ofreció (bloqueo sin disputa): se re-pregunta
         "solo bloquea", "solo bloquear", "solo bloquea la tarjeta", "solo el bloqueo", "so bloquear",
         "so o bloqueio", "apenas bloquear"]
# Consentimiento DIFERIDO o CONDICIONADO (red team #33): "después te confirmo", "sí, mañana", "si fuera por mí dale,
# pero lo consulto", "ok, after I talk to my wife" contienen una palabra de sí, pero no son un sí AHORA. No es una
# lista de ataques: son marcadores temporales, condicionales y de consulta a un tercero (clases cerradas del idioma).
# Cualquiera de ellos vuelve la respuesta `unclear`: se re-pregunta y nunca se actúa.
DEFER = [r"despues", r"luego", r"mas tarde", r"manana", r"al rato", r"en un rato", r"otro dia", r"la semana que viene",
         r"la proxima( semana)?", r"el (lunes|martes|miercoles|jueves|viernes|sabado|domingo)", r"cuando", r"primero",
         r"antes", r"todavia", r"aun", r"por ahora", r"de momento", r"consult\w*", r"lo (hablo|hablamos|charlo|veo|vemos)",
         r"hablarlo", r"(hablar|hablo|confirmar|confirmo|chequear|chequeo|verificar|verifico) con", r"te aviso",
         r"le aviso", r"aviso", r"(le|te) pregunto", r"preguntarle", r"revis\w*",
         r"si (fuera|fueras|pudiera|puedo|puedes|podes|quieres|queres|hubiera|me|te|le|lo|la|les|nos|se|usted|ustedes)",
         r"siempre que", r"siempre y cuando", r"solo si", r"solamente si", r"con tal( de)? que", r"a menos que",
         r"salvo que", r"en caso de que",
         r"depois", r"mais tarde", r"amanha", r"semana que vem", r"quando", r"primeiro", r"ainda", r"por enquanto",
         r"vou (ver|falar|pensar|perguntar|conversar)", r"falar com", r"conversar com", r"perguntar", r"se eu",
         r"desde que", r"contanto que", r"so se", r"a nao ser que",
         r"later", r"tomorrow", r"after", r"first", r"when", r"if", r"unless", r"talk to", r"check with", r"ask my",
         r"let me", r"wait", r"hold on", r"not now"]
DEFER = [p + r"(?![a-z])" for p in DEFER]
# Mención de la tarjeta o del bloqueo que no es un "no bloquees" (ya consumido) ni un "bloquéala" afirmativo:
# "sí, pero la tarjeta que siga activa", "no toques mi tarjeta". El bloqueo no quedó respondido -> unclear.
BLOCK_AFFIRM = (r"(?:bloque(?:a|ala|alo|ar|e|ie|ia)|bloqueie|block it|block the card|block my card)"
                r"(?:\s+(?:la|mi|o|a|the|my)?\s*(?:tarjeta|cartao|card))?")
CARD_MENTION = re.compile(r"tarjeta|targeta|cartao|cartoes|card|plastico|bloqu|block|desactiv|congel")
# Cláusulas en pregunta ("¿y si digo que sí?", "¿en qué va mi disputa?"): su "sí"/"va" no contesta nada.
# La segunda alternativa solo arranca al inicio o tras un signo: sin eso el regex es cuadrático (30k caracteres = 5 s).
QUESTION = re.compile(r"¿[^?¿]*\?|(?:^|(?<=[.!?¿]))[^.!?¿]*\?")
CARD_HINT = re.compile(r"(?:tarjeta|targeta|cartao|card|terminad[ao] (?:en|em)|finalizad[ao] em|final)\D{0,12}?(\d{4})\b"
                       r"|\*{2,}\s?(\d{4})\b")

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


def _scan(t: str) -> tuple[set[str], str]:
    """(etiquetas hedge/yes/no presentes, texto sobrante). La frase más larga gana y se consume: "no quiero"
    es un no, no un "quiero"; "no se" es duda, no un "no"; "claro que si" es un sí."""
    found = set()
    for phrase, label in sorted(_CONFIRM_LEXICON, key=lambda x: len(x[0]), reverse=True):
        t, n = re.subn(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", " ", t)
        if n:
            found.add(label)
    return found, t


def classify_confirmation(t: str) -> tuple[str | None, list[str]]:
    """Texto normalizado -> (confirm | deny | unclear | None, sub-acciones rechazadas).
    None = el mensaje no contiene ninguna señal de respuesta (el router sigue con las otras intenciones)."""
    rest, denials = t, []
    for action, phrases in SUB_ACTION_DENIALS.items():
        rest, hit = _strip(rest, [re.escape(x) + _DENIAL_OBJECT for x in phrases])
        if hit:
            denials.append(action)
    rest, only_main = _strip(rest, [re.escape(x) for x in ONLY_MAIN_ACTION])
    if only_main and "block_card" not in denials:
        denials.append("block_card")
    rest, both = _strip(rest, [re.escape(x) for x in BOTH_ACTIONS])
    rest, restated = _strip(rest, RESTATEMENTS)
    # Preguntas (#33): se sacan del texto; si contenían un sí/no/duda ("¿y si digo que sí?"), no contestan nada
    asked_back = any(_scan(q)[0] for q in QUESTION.findall(rest))
    rest = QUESTION.sub(" ", rest)
    deferred = _any(rest, DEFER) or 'hedge' in _scan(rest)[0]  # 'solo bloquea' es duda antes que un sí al bloqueo
    rest, _ = _strip(rest, [BLOCK_AFFIRM])  # "sí, bloquéala": responde por el bloqueo, pero NO es un sí por sí solo
    labels, leftover = _scan(rest)
    yes = "yes" in labels or only_main or both
    no = "no" in labels
    # "¿sí?" es una duda (el sí está DENTRO de la pregunta); "sí, ¿cuánto demora?" es un sí con una pregunta aparte
    if "hedge" in labels or asked_back or deferred:
        return "unclear", denials
    if yes and CARD_MENTION.search(leftover):  # habló de la tarjeta sin decir sí o no al bloqueo (#33)
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


def language_scores(text: str) -> tuple[int, int]:
    """(marcadores pt, marcadores es) del mensaje."""
    t = _norm(text)
    words = set(re.findall(r"[a-z]+", t))
    pt = sum(1 for m in PT_MARKERS if (m in t if " " in m else m in words))
    es = sum(1 for m in ES_MARKERS if (m in t if " " in m else m in words))
    return pt, es


def detect_language(text: str, prior: str | None = None) -> Literal["es", "pt"]:
    """Idioma del mensaje; si no hay evidencia (empate), el de la sesión (`prior`) o español."""
    pt, es = language_scores(text)
    if pt == es:
        return "pt" if prior == "pt" else "es"
    return "pt" if pt > es else "es"


def session_language(prior: str | None, text: str, proposed: str) -> str:
    """Idioma pegajoso de la conversación: un mensaje sin evidencia propia ("ok", "1", "confirmo") hereda el de
    la sesión en vez de volver a español por defecto. Con evidencia, manda lo que propuso el router."""
    pt, es = language_scores(text)
    return (prior or proposed) if pt == es else proposed


def _has(t: str, kw: str) -> bool:
    if kw.endswith("*"):
        return re.search(rf"(?<![a-z]){re.escape(kw[:-1])}[a-z]*", t) is not None
    return re.search(rf"(?<![a-z]){re.escape(kw)}(?![a-z])", t) is not None


def parse_amount(t: str) -> float | None:
    t = DATE_NUMBERS.sub(" ", t)
    m = re.search(r"(?:\$|usd|mxn|cop|ars|r\$)?\s*(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
                  r"(\s*(?:mil\b|lucas\b|k\b|millon\w*|milh\w*|palos?\b))?", t)
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
    if mult:  # "2 palos" = 2 millones (AR/CO)
        value *= 1_000_000 if mult.strip().startswith(("millon", "milh", "palo")) else 1000
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
    m = re.search(rf"\b(?:hace|ha|faz) {_NUM} (dias?|semanas?|mes|meses)\b", t)
    if m:  # días: fecha exacta; semanas/meses: ventana alrededor ("hace tres semanas" ~ 21 días ± 4)
        n, unit = _int(m.group(1)), m.group(2)
        if unit.startswith("dia"):
            d = today - dt.timedelta(days=n)
            return d, d
        days, slack = (n * 7, 4) if unit.startswith("semana") else (n * 30, 15)
        center = today - dt.timedelta(days=days)
        return center - dt.timedelta(days=slack), min(today, center + dt.timedelta(days=slack))
    if any(k in t for k in ("semana antepasada", "semana retrasada")):
        return today - dt.timedelta(days=21), today - dt.timedelta(days=14)
    if any(k in t for k in ("mes pasado", "mes passado")):
        last = today.replace(day=1) - dt.timedelta(days=1)
        return last.replace(day=1), last
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
    m = re.search(r"\b(?:en|em|de|durante) (" + "|".join(MONTHS) + r")\b", t)
    if m:  # solo el mes ("en mayo"): todo el mes, la última vez que ocurrió
        first = _past(dt.date(today.year, MONTHS[m.group(1)], 1), today)
        nxt = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return first, min(today, nxt - dt.timedelta(days=1))
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


# ---------------------------------------------------------------- intenciones de conversación (#40)
# Se evalúan ANTES que el puntaje disputa/bloqueo/fuera de alcance, en este orden de prioridad:
# seguridad (toma de cuenta) > pedido explícito de humano > seguimiento/cancelación de una disputa.
# Por qué ese orden: "me hackearon, quiero hablar con alguien" es urgente para seguridad antes que para la cola
# general; y un pedido de humano no debe perderse aunque el mensaje también mencione un cargo.
ACCOUNT_TAKEOVER = [r"hacke\w*", r"jacke\w*", r"(me )?clonar\w*", r"clonad\w*", r"clonaram", r"invadi\w*",
                    r"(entraron|entro|accedio|accedieron|se metio|se metieron)( alguien)? (a|en) mi (cuenta|app|banca)",
                    r"(robaron|robo) (de )?(mi )?(cuenta|identidad|usuario|clave|contrasena)",
                    r"suplant\w*", r"acceso no autorizado", r"acesso nao autorizado",
                    r"(cambiaron|me cambiaron) (mi |la )?(clave|contrasena|correo|telefono)",
                    r"(mudaram|trocaram) (minha |a )?(senha|email|telefone)",
                    r"(roubaram|invadiram) (minha |a )?conta", r"tomaron (el )?control"]
HUMAN_REQUEST = [r"asesor\w*", r"humano\w*", r"humana\w*", r"operador\w*", r"ejecutiv\w*", r"atendente\w*",
                 r"representante\w*", r"supervisor\w*", r"gerente\w*", r"agente (real|de verdad|humano)",
                 r"persona (real|de verdad|de carne)", r"pessoa (real|de verdade)",
                 r"(hablar|comunicar\w*|pasar\w*|pasame|pasenme|contactar\w*) con (alguien|una persona|un\w* agente)",
                 r"falar com (alguem|uma pessoa|um agente)", r"atendimento humano", r"quiero una persona",
                 r"quero uma pessoa", r"que me llamen", r"me liguem"]
CASE_ID = re.compile(r"\bdsp-?[a-z0-9]{3,}\b")
# Palabras completas: "estado" no debe coincidir con "Estados Unidos", ni "caso" con "en caso de que".
DISPUTE_REF = r"(disputa|reclamo|reclamacion|mi caso|contestacao|dsp-?[a-z0-9]{3,})(?![a-z])"
_STATUS = r"(en que va|como va|el estado|estatus|status|seguimiento|novedades|andamento|como esta|que paso con)(?![a-z])"
DISPUTE_STATUS = [rf"{_STATUS}.*{DISPUTE_REF}", rf"{DISPUTE_REF}.*{_STATUS}",
                  rf"cuando (me )?(responden|resuelven|contestan).*{DISPUTE_REF}"]
CANCEL_DISPUTE = [rf"(cancel\w*|retir\w*|anul\w*|desist\w*|quitar|borrar) (la |mi |a |minha |el |o )?{DISPUTE_REF}",
                  r"ya (lo )?reconoci", r"ja reconheci", r"si (lo|la) reconozco", r"era mia", r"era meu", r"era minha"]
CLOSING = ["gracias", "muchas gracias", "mil gracias", "obrigado", "obrigada", "valeu", "eso es todo", "es todo",
           "eso seria todo", "nada mas", "era eso", "era isso", "so isso", "e so isso", "chau", "chao", "adios",
           "tchau", "hasta luego", "ate logo", "ate mais", "perfecto gracias", "listo gracias", "genial gracias",
           "buenisimo", "joya", "de nada", "nada mais"]
NONE_OF_THESE = ["ninguna", "ninguno", "ninguna de esas", "ninguno de esos", "no es ninguna", "no es ninguno",
                 "ninguna de las", "nenhuma", "nenhum", "nenhuma delas", "nao e nenhuma", "nao esta", "no esta",
                 "no aparece", "nao aparece", "ninguna es", "no es ninguna de esas", "none"]


def _any(t: str, patterns: list[str]) -> bool:
    return any(re.search(rf"(?<![a-z]){p}", t) for p in patterns)


def conversation_intent(t: str, awaiting: str | None, has_request: bool) -> str | None:
    """Intenciones que no son disputa/bloqueo. `has_request` = el mensaje también nombra un cargo o un bloqueo."""
    if _any(t, ACCOUNT_TAKEOVER):
        return "account_takeover"
    if _any(t, HUMAN_REQUEST):
        return "human_request"
    if _any(t, CANCEL_DISPUTE):
        return "cancel_dispute"
    if _any(t, DISPUTE_STATUS) or (CASE_ID.search(t) and not has_request):
        return "dispute_status"
    if not has_request and any(_has(t, k) for k in CLOSING):
        return "closing"
    return None


class RuleRouter:
    """Línea base: palabras clave es/pt + expresiones regulares. Confianza = claridad de la coincidencia."""

    name = "rules"

    def understand(self, text: str, today: dt.date, awaiting: str | None) -> Understanding:
        t = _norm(text)
        lang = detect_language(text)
        slots = Slots()
        # Respuestas cortas a una pregunta pendiente del agente
        if awaiting == "option":
            if any(_has(t, k) for k in NONE_OF_THESE) and len(t) <= 60:  # antes que los dígitos: "ninguna de las 3"
                return Understanding("none_of_these", 0.9, lang)
            m = re.search(r"\b([1-9])\b", t)
            if m and len(t) <= 40:
                return Understanding("select_option", 0.95, lang, Slots(option=int(m.group(1))))
            o = next((v for k, v in ORDINALS.items() if _has(t, k)), None)
            if o and len(t) <= 40:
                return Understanding("select_option", 0.9, lang, Slots(option=o))
        # "no reconozco otro cargo de 50" no es un "no": es un pedido nuevo que descarta la acción pendiente.
        m = CASE_ID.search(t)
        slots.case_id = m.group(0).upper() if m else None
        slots.amount = parse_amount(amount_text(t))
        slots.count = parse_count(t)
        slots.date_from, slots.date_to = parse_dates(t, today)
        slots.country = next((v for k, v in COUNTRIES.items() if _has(t, k)), None)
        m = CARD_HINT.search(t)
        slots.card_hint = (m.group(1) or m.group(2)) if m else ("?" if "[tarjeta]" in t else None)
        if awaiting == "confirmation":
            state, denials = classify_confirmation(t)
            if state and not _is_new_request(t, slots, state):
                return Understanding(state, 0.9, lang, sub_action_denials=denials)

        scored = PRODUCT_NAMES.sub(" ", t)
        scores = {i: sum(_has(scored, k) for k in KEYWORDS[i]) for i in ("dispute_charge", "block_card", "out_of_scope")}
        convo = conversation_intent(t, awaiting, scores["dispute_charge"] + scores["block_card"] > 0)
        if convo:
            return Understanding(convo, 0.85, lang, slots)
        if scores["out_of_scope"] and scores["dispute_charge"]:
            # "me cobraron algo raro en el seguro de la tarjeta": hay un cargo concreto -> es una disputa
            scores["out_of_scope"] = 0
        best = max(scores, key=scores.get)
        if scores[best] == 0:
            return Understanding("unknown", 0.2, lang, slots)
        ties = sum(1 for v in scores.values() if v == scores[best])
        conf = 0.85 if ties == 1 else 0.5
        return Understanding(best, conf, lang, slots)
