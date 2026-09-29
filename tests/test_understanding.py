"""RuleRouter: formatos locales de monto y fecha, voseo/pt-BR y respuestas cortas (ajustes del issue #13, vistos en dev)."""
import datetime as dt

import pytest

from bankagent.understanding import RuleRouter, _norm, parse_amount, parse_dates

TODAY = dt.date(2026, 6, 17)  # miércoles
R = RuleRouter()


@pytest.mark.parametrize("text,amount", [
    ("me cobraron $1,200.50", 1200.50), ("un cargo de $ 1.200,50", 1200.50), ("45 mil pesos", 45000),
    ("1,2 millones", 1_200_000), ("23 lucas", 23000), ("el 9 de junio me cobraron $1.079.980", 1_079_980),
    ("hace 6 dias me cobraron $ 847.744", 847_744), ("un cargo de 77 el 13/06", 77),
])
def test_amounts_in_local_formats_and_dates_are_not_amounts(text, amount):
    assert parse_amount(_norm(text)) == amount


@pytest.mark.parametrize("text,day", [
    ("antier", dt.date(2026, 6, 15)), ("anteontem", dt.date(2026, 6, 15)), ("hace 3 días", dt.date(2026, 6, 14)),
    ("há 3 dias", dt.date(2026, 6, 14)), ("el 9 de junio", dt.date(2026, 6, 9)), ("no dia 2 de março", dt.date(2026, 3, 2)),
    ("el 20 de agosto", dt.date(2025, 8, 20)),  # sin año y en el futuro -> año anterior
    ("el 18/09", dt.date(2025, 9, 18)), ("el martes", dt.date(2026, 6, 16)), ("na sexta", dt.date(2026, 6, 12)),
])
def test_relative_and_textual_dates(text, day):
    assert parse_dates(_norm(text), TODAY) == (day, day)


@pytest.mark.parametrize("text,intent", [
    ("Não reconheço uma cobrança", "dispute_charge"), ("quiero desconocer un consumo de 5.000", "dispute_charge"),
    ("quiero disputar una transferencia", "dispute_charge"), ("Por favor bloqueen mi tarjeta de crédito", "block_card"),
    ("me robaron la tarjeta, bloqueala", "block_card"), ("quiero hacer un plazo fijo", "out_of_scope"),
])
def test_dialect_intents(text, intent):
    assert R.understand(text, TODAY, None).intent == intent


@pytest.mark.parametrize("text,awaiting,intent,option", [
    ("va", "confirmation", "confirm", None), ("de una", "confirmation", "confirm", None),
    ("no, dejá", "confirmation", "deny", None), ("la segunda", "option", "select_option", 2),
    ("a primeira", "option", "select_option", 1),
])
def test_short_answers(text, awaiting, intent, option):
    u = R.understand(text, TODAY, awaiting)
    assert u.intent == intent and u.slots.option == option


# #57: el mismo "sí, pero sin bloqueo" en cada tratamiento. "no me bloquee" (usted, es-CO) era "unclear" y ese grupo
# de dialecto no terminaba igual que los otros tres (con ambos routers: la confirmación la decide RuleRouter).
@pytest.mark.parametrize("text", ["Sí, pero no bloquees la tarjeta",                     # tú (es-MX)
                                  "Sí, pero no me bloquee la tarjeta, por favor",       # usted (es-CO)
                                  "Sí, pero no me bloqueen la tarjeta",                 # ustedes
                                  "Sí, pero no me bloqueés la tarjeta que la uso",      # vos (es-AR)
                                  "Sim, mas não bloqueia o cartão",                     # você (pt-BR)
                                  "Sim, mas não me bloqueie o cartão"])
def test_partial_consent_in_every_form_of_address(text):
    u = R.understand(text, TODAY, "confirmation")
    assert u.intent == "confirm" and u.sub_action_denials == ["block_card"]


def test_card_last_four_is_an_option_not_an_amount():
    u = R.understand("la que termina en 3718", TODAY, "option")
    assert u.intent == "select_option" and u.slots.last4 == "3718" and u.slots.amount is None
    assert R.understand("o final 4279", TODAY, "option").slots.last4 == "4279"
