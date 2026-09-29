"""Mensajes del cliente SIMULADO para el replay (texto generado por el equipo, no tráfico real).

El dataset no tiene texto libre de las quejas (las descripciones son plantillas), así que cada queja se
convierte en un mensaje como lo escribiría un cliente: menciona monto, fecha y país (si el cargo fue en el
extranjero), nunca IDs. Dialecto según el país del cliente:
    México -> es-MX · Colombia -> es-CO · Argentina -> es-AR (voseo) · pt-BR = TRADUCCIÓN hecha por el equipo
    para una submuestra (el dataset no trae portugués).
El formato del monto sigue la convención local ("$1,250.00" en MX; "$1.250.000" en CO/AR; "US$ 1.250,00" en pt).
Todas las elecciones salen de un `random.Random` sembrado: el mismo seed produce los mismos mensajes.
"""
from __future__ import annotations

import datetime as dt
import math
import random

DIALECTS = {"México": "es-MX", "Colombia": "es-CO", "Argentina": "es-AR"}
LOCAL_CURRENCY = {"México": "USD", "Colombia": "COP", "Argentina": "ARS"}  # en el dataset México opera en USD
COUNTRY_ES = {"Brazil": "Brasil", "USA": "Estados Unidos", "Spain": "España", "México": "México",
              "Colombia": "Colombia", "Argentina": "Argentina"}
COUNTRY_PT = {"Brazil": "no Brasil", "USA": "nos Estados Unidos", "Spain": "na Espanha", "México": "no México",
              "Colombia": "na Colômbia", "Argentina": "na Argentina"}
STYLES = (("amount_date", 0.5), ("amount_only", 0.25), ("date_only", 0.25))

OPENINGS = {
    ("es-MX", "Cargo no reconocido"): ["Hola, me aparece un cargo {amt}{where} {when} que no reconozco. ¿Me ayudan?",
                                       "Buenas tardes, tengo un cargo {amt}{where} {when} que yo no hice."],
    ("es-MX", "Cobro indebido"): ["Hola, me hicieron un cobro {amt}{where} {when} que no me corresponde.",
                                  "Buenas tardes, tengo un cobro {amt}{where} {when} que no reconozco, ¿me ayudan a revisarlo?"],
    ("es-CO", "Cargo no reconocido"): ["Buenas, me salió un cargo {amt}{where} {when} que no reconozco, ¿me colaboran?",
                                       "Hola, tengo un cobro {amt}{where} {when} que yo no hice."],
    ("es-CO", "Cobro indebido"): ["Buenas, tengo un cobro {amt}{where} {when} que no me corresponde, ¿me colaboran por favor?",
                                  "Hola, me aparece un cobro {amt}{where} {when} que no reconozco."],
    ("es-AR", "Cargo no reconocido"): ["Hola, me aparece un cargo {amt}{where} {when} que no reconozco. ¿Me podés ayudar?",
                                       "Che, tengo un cobro {amt}{where} {when} que no hice yo. Fijate por favor."],
    ("es-AR", "Cobro indebido"): ["Hola, tengo un cobro {amt}{where} {when} que no corresponde. ¿Lo podés revisar?",
                                  "Buenas, me figura un cargo {amt}{where} {when} que no reconozco, fijate por favor."],
    ("pt-BR", "Cargo no reconocido"): ["Oi, apareceu uma cobrança {amt}{where} {when} que eu não reconheço. Podem me ajudar?",
                                       "Olá, tem uma cobrança {amt}{where} {when} que eu não fiz."],
    ("pt-BR", "Cobro indebido"): ["Oi, tem uma cobrança {amt}{where} {when} que é indevida, não reconheço.",
                                  "Olá, apareceu uma cobrança {amt}{where} {when} que eu não reconheço."],
}
DETAIL = {  # respuesta a un pedido de aclaración: monto exacto + fecha completa (siempre > 40 caracteres)
    "es-MX": "Es un cargo de {amt}{where} del {date}, no lo reconozco.",
    "es-CO": "Es un cobro de {amt}{where} del {date}, no lo reconozco.",
    "es-AR": "Es un cargo de {amt}{where} del {date}, no lo reconozco, fijate.",
    "pt-BR": "É uma cobrança de {amt}{where} do dia {date}, não reconheço.",
}
OPTION = {"es-MX": "La {n}", "es-CO": "Es la {n}", "es-AR": "La {n}, esa es", "pt-BR": "A {n}"}
CONFIRM = {"es-MX": "Sí, confirmo", "es-CO": "Sí, de acuerdo", "es-AR": "Sí, dale", "pt-BR": "Sim, confirmo"}
DENY_WRONG = {"es-MX": "No, ese no es", "es-CO": "No, ese no es", "es-AR": "No, ese no es", "pt-BR": "Não, não é essa"}


def lang_of(dialect: str) -> str:
    return "pt" if dialect.startswith("pt") else "es"


def _group(n: int, sep: str) -> str:
    return f"{n:,}".replace(",", sep)


def _round_sig(x: float, sig: int = 2) -> float:
    if x <= 0:
        return x
    return round(x, sig - 1 - int(math.floor(math.log10(x))))


def fmt_amount(amount: float, currency: str, dialect: str, approx: bool = False) -> str:
    """Monto como lo escribe un cliente. `approx` redondea a 2 cifras significativas (error <= 5%, dentro de la
    tolerancia de ±10% con que busca el agente). Solo se usa para montos >= 100."""
    x = float(amount)
    if approx:
        x = _round_sig(x)
    whole, cents = int(x), round((x - int(x)) * 100)
    if cents == 100:
        whole, cents = whole + 1, 0
    if dialect == "es-MX":
        num = _group(whole, ",") + ("" if approx or (currency == "COP" and cents == 0) else f".{cents:02d}")
        body = f"${num}"
    else:
        num = _group(whole, ".") + ("" if approx or (currency in ("COP", "ARS") and cents == 0) else f",{cents:02d}")
        if dialect == "pt-BR":
            body = f"US$ {num}" if currency == "USD" else f"{currency} {num}"
        else:
            body = f"${num}" if currency != "USD" else f"US${num}"
    if dialect == "es-MX" and currency != "USD":
        body += f" {currency}"
    return body


def amount_phrase(amount: float, currency: str, dialect: str, approx: bool = False) -> str:
    """"de $1,250.00" / "de unos $1.300.000" / "de uns US$ 1.300": complemento de "un cargo ..."."""
    lead = {"es-MX": "de como ", "es-CO": "de unos ", "es-AR": "de unos ", "pt-BR": "de uns "}[dialect] if approx else "de "
    return lead + fmt_amount(amount, currency, dialect, approx)


def fmt_date(d: dt.date, dialect: str, with_year: bool) -> str:
    return d.strftime("%d/%m/%Y") if with_year else d.strftime("%d/%m")


def date_phrase(txn_day: dt.date, today: dt.date, dialect: str, relative: bool = True) -> str:
    """Fecha como la diría el cliente, relativa a la fecha de la queja cuando es natural (hoy/ayer/semana pasada:
    el router las resuelve contra `as_of`, que en el replay es la fecha de creación de la queja)."""
    pt = dialect == "pt-BR"
    gap = (today - txn_day).days
    if relative and gap == 0:
        return "hoje" if pt else "hoy"
    if relative and gap == 1:
        return "ontem" if pt else "ayer"
    if relative and 7 <= gap <= 14:
        return "na semana passada" if pt else "la semana pasada"
    d = fmt_date(txn_day, dialect, with_year=txn_day.year != today.year)
    return f"no dia {d}" if pt else f"del {d}"


def where_phrase(txn: dict, customer_country: str, dialect: str, rng: random.Random) -> str:
    country = txn.get("transaction_country")
    if country and country != customer_country:
        return " " + COUNTRY_PT.get(country, f"em {country}") if dialect == "pt-BR" else f" en {COUNTRY_ES.get(country, country)}"
    if txn.get("merchant_name") and rng.random() < 0.5:
        return (" em " if dialect == "pt-BR" else " en ") + txn["merchant_name"]
    return ""


def pick_style(rng: random.Random) -> str:
    r, acc = rng.random(), 0.0
    for style, p in STYLES:
        acc += p
        if r < acc:
            return style
    return STYLES[-1][0]


def render_opening(case: dict, dialect: str, rng: random.Random, style: str | None = None) -> tuple[str, dict]:
    """Primer mensaje. `case` necesita: subcategory, creation_date, customer_country y txn (la emparejada)."""
    txn, today = case["txn"], _day(case["creation_date"])
    style = style or pick_style(rng)
    approx = style != "date_only" and float(txn["amount"]) >= 100 and rng.random() < 0.4
    tmpl = rng.choice(OPENINGS[(dialect, case["subcategory"])])
    amt = amount_phrase(txn["amount"], txn["currency"], dialect, approx) if style != "date_only" else ""
    when = date_phrase(_day(txn["transaction_date"]), today, dialect, relative=True) if style != "amount_only" else ""
    where = where_phrase(txn, case["customer_country"], dialect, rng)
    text = " ".join(tmpl.format(amt=amt, where=where, when=when).split())  # colapsa espacios de huecos vacíos
    text = text.replace(" ,", ",").replace(" .", ".").replace(" ?", "?")
    return text, {"style": style, "approx_amount": approx, "dialect": dialect}


def render_detail(case: dict, dialect: str, rng: random.Random) -> str:
    txn = case["txn"]
    return DETAIL[dialect].format(amt=fmt_amount(txn["amount"], txn["currency"], dialect),
                                  where=where_phrase(txn, case["customer_country"], dialect, rng),
                                  date=fmt_date(_day(txn["transaction_date"]), dialect, with_year=True))


def render_option(n: int, dialect: str) -> str:
    return OPTION[dialect].format(n=n)


def _day(x) -> dt.date:
    return x.date() if isinstance(x, dt.datetime) else x
