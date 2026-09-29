"""Extracción de datos del mensaje: fechas, montos, cantidades, IDs, comercio y orden de candidatas (#41).

Frases escritas por el equipo para esta prueba (casos del issue + equivalentes pt-BR); NO salen del set de
evaluación reservado.
"""
import datetime as dt

import pytest

from bankagent.graph import rank_candidates
from bankagent.understanding import RuleRouter, match_merchant

TODAY = dt.date(2026, 6, 17)
R = RuleRouter()
D = dt.date


@pytest.mark.parametrize("text,amount,date_from,date_to,count", [
    ("no reconozco un cargo del 18 de mayo", None, D(2026, 5, 18), D(2026, 5, 18), None),
    ("não reconheço uma compra de 18 de maio", None, D(2026, 5, 18), D(2026, 5, 18), None),
    ("no reconozco un cargo de 1200 pesos del 5 de junio", 1200, D(2026, 6, 5), D(2026, 6, 5), None),
    ("cobrança de 1200 reais do dia 5 de junho", 1200, D(2026, 6, 5), D(2026, 6, 5), None),
    ("me hicieron un cargo hace tres semanas", None, D(2026, 5, 23), D(2026, 5, 31), None),
    ("me cobraram há duas semanas", None, D(2026, 5, 30), D(2026, 6, 7), None),
    ("hace 2 semanas me cobraron 40", 40, D(2026, 5, 30), D(2026, 6, 7), None),
    ("no reconozco un cargo de 2 millones de pesos", 2_000_000, None, None, None),
    ("uma cobrança de 2 milhões", 2_000_000, None, None, None),
    ("me cobraron 2 palos", 2_000_000, None, None, None),
    ("un cargo de 20k", 20_000, None, None, None),
    ("no reconozco 3 cargos de 20 dólares", 20, None, None, 3),
    ("não reconheço duas compras de 15 dólares", 15, None, None, 2),
    ("mi tarjeta 4152 cobro de 30", 30, None, None, None),
    ("un cargo de 50 con la tarjeta terminada en 4152", 50, None, None, None),
    ("no reconozco el cargo TRX-88812 de 45 dólares", 45, None, None, None),
    ("no reconozco un cargo en mayo", None, D(2026, 5, 1), D(2026, 5, 31), None),
    ("não reconheço uma compra em maio", None, D(2026, 5, 1), D(2026, 5, 31), None),
    ("el mes pasado me cobraron algo raro", None, D(2026, 5, 1), D(2026, 5, 31), None),
    ("a cobrança foi no mês passado", None, D(2026, 5, 1), D(2026, 5, 31), None),
])
def test_slots(text, amount, date_from, date_to, count):
    s = R.understand(text, TODAY, None).slots
    assert (s.amount, s.date_from, s.date_to, s.count) == (amount, date_from, date_to, count)


def test_case_id_is_not_an_amount():
    s = R.understand("¿en qué va mi disputa DSP-123?", TODAY, None).slots
    assert s.amount is None and s.case_id == "DSP-123"


NAMES = ["Gasolinera Express", "Cine Premium", "Tienda General", "Tienda Don José", "Amazon", "Centro Comercial"]


@pytest.mark.parametrize("text,expected", [
    ("no reconozco el cargo de Gasolinera Express", ["Gasolinera Express"]),
    ("un cobro de la gasolinera express que no hice", ["Gasolinera Express"]),
    ("me cobraron en amazon", ["Amazon"]),
    ("não reconheço a compra no Cine Premium", ["Cine Premium"]),
    ("una compra en una tienda", []),       # "tienda" sola no elige entre dos comercios
    ("no reconozco un cargo de 50", []),
])
def test_merchant_matches_only_the_customers_own_merchants(text, expected):
    assert match_merchant(text, NAMES) == expected


def test_candidates_are_ranked_by_policy_window_then_amount_then_recency():
    t = lambda tid, amount, d: {"transaction_id": tid, "amount": amount, "transaction_date": dt.datetime(*d)}  # noqa: E731
    found = [t("old_exact", 100, (2025, 1, 1)), t("recent_far", 109, (2026, 6, 10)), t("recent_close", 101, (2026, 5, 1))]
    assert [x["transaction_id"] for x in rank_candidates(found, 100, TODAY, 120)] == \
        ["recent_close", "recent_far", "old_exact"]


def test_merchant_alone_finds_the_charge(env):
    r = env.agent.chat(env.thread(), env.login("CLI-ANA"), "no reconozco el cargo de Liverpool")
    assert r["txn"]["transaction_id"] == "T-ANA-2"


def test_without_any_detail_it_asks_before_listing(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    r = env.agent.chat(th, tok, "no reconozco un cargo")
    assert r["outcome"] == "clarify" and not r.get("candidates") and "monto" in r["reply"]
    r = env.agent.chat(th, tok, "de 77 dólares")  # el dato llega en el turno siguiente
    assert r["txn"]["transaction_id"] == "T-ANA-8" and "Confirmas" in r["reply"]
