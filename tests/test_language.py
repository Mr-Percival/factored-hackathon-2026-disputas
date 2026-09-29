"""Portugués natural, léxico es/pt e idioma de sesión pegajoso (#39).

Frases escritas por el equipo para esta prueba (es-MX, es-CO, es-AR voseo, pt-BR); NO salen del set de
evaluación reservado.
"""
import datetime as dt

import pytest

from bankagent.understanding import RuleRouter, detect_language, session_language

TODAY = dt.date(2026, 6, 17)
R = RuleRouter()

# (mensaje, intención, idioma)
INTENTS = [
    # pt-BR
    ("Não reconheço essa compra de 496 dólares", "dispute_charge", "pt"),
    ("não reconheço uma compra de US$ 496,13", "dispute_charge", "pt"),
    ("Apareceu uma compra estranha de 496 dólares na minha fatura", "dispute_charge", "pt"),
    ("vi um lançamento desconhecido de 80 dólares", "dispute_charge", "pt"),
    ("tem uma cobrança que eu não fiz", "dispute_charge", "pt"),
    ("não autorizei essa compra", "dispute_charge", "pt"),
    ("desconheço esse débito de 50 reais", "dispute_charge", "pt"),
    ("quero contestar uma cobrança de ontem", "dispute_charge", "pt"),
    ("me cobraram duas vezes no mercado", "dispute_charge", "pt"),
    ("fui roubado, bloqueia meu cartão", "block_card", "pt"),
    ("perdi meu cartão", "block_card", "pt"),
    ("roubaram minha carteira com o cartão", "block_card", "pt"),
    ("quero bloquear o cartão", "block_card", "pt"),
    ("quero um empréstimo", "out_of_scope", "pt"),
    # es-MX
    ("Hay un movimiento de 151 dólares que yo no autoricé", "dispute_charge", "es"),
    ("me salió un cargo raro de 300 pesos", "dispute_charge", "es"),
    ("pero yo no fui, no reconozco ese cobro", "dispute_charge", "es"),
    ("extravié la tarjeta", "block_card", "es"),
    ("perdí mi tarjeta, quiero bloquearla", "block_card", "es"),
    # es-CO
    ("me aparece un cobro que yo no hice", "dispute_charge", "es"),
    ("desconozco una compra de 80.000 pesos", "dispute_charge", "es"),
    ("me robaron la tarjeta, bloquéenla por favor", "block_card", "es"),
    # es-AR voseo
    ("che, tengo un cargo que no reconozco", "dispute_charge", "es"),
    ("me afanaron la tarjeta, bloqueala", "block_card", "es"),
    ("no reconozco un consumo, ¿me podés ayudar?", "dispute_charge", "es"),
]


@pytest.mark.parametrize("text,intent,lang", INTENTS)
def test_natural_phrases_reach_the_flow_in_the_right_language(text, intent, lang):
    u = R.understand(text, TODAY, None)
    assert (u.intent, u.language) == (intent, lang)


@pytest.mark.parametrize("text,awaiting,option", [
    ("la primera", "option", 1), ("la segunda", "option", 2), ("el primero", "option", 1), ("a segunda", "option", 2),
    ("o primeiro", "option", 1), ("a terceira", "option", 3), ("la última", "option", -1), ("o último", "option", -1),
    ("la 2", "option", 2), ("opção 1", "option", 1),
])
def test_ordinals_select_an_option(text, awaiting, option):
    u = R.understand(text, TODAY, awaiting)
    assert (u.intent, u.slots.option) == ("select_option", option)


@pytest.mark.parametrize("text", ["ok", "1", "confirmo", "la 2", "👍", "de acuerdo?"])
def test_short_messages_inherit_the_session_language(text):
    assert session_language("pt", text, detect_language(text)) == "pt"
    assert detect_language(text, prior="pt") in ("pt", "es")  # sin prior pt, "de acuerdo" puede ser es


@pytest.mark.parametrize("text,lang", [("não, obrigado", "pt"), ("no, gracias", "es"), ("quero falar com alguém", "pt"),
                                       ("quiero hablar con alguien", "es")])
def test_messages_with_evidence_switch_language(text, lang):
    prior = "es" if lang == "pt" else "pt"
    assert session_language(prior, text, detect_language(text)) == lang


def test_conversation_started_in_pt_stays_in_pt(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    r = env.agent.chat(th, tok, "me cobraram 350 dólares e não fui eu")
    assert r["lang"] == "pt" and r["awaiting"] == "option" and "Responda com o número" in r["reply"]
    r = env.agent.chat(th, tok, "1")
    assert r["lang"] == "pt" and "Confirma?" in r["reply"]
    r = env.agent.chat(th, tok, "ok")
    assert r["lang"] == "pt" and r["outcome"] == "resolved" and "Abri a contestação" in r["reply"]


def test_last_option(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    r = env.agent.chat(th, tok, "me cobraron 350 y no fui yo")
    last = r["candidates"][-1]["transaction_id"]
    r = env.agent.chat(th, tok, "la última")
    assert r["txn"]["transaction_id"] == last
