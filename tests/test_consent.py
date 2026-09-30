"""Consentimiento por acción y confirmación tri-estado (#38).

Frases escritas por el equipo para esta prueba (es-MX, es-CO, es-AR con voseo, pt-BR); NO salen del set de
evaluación reservado. Regla de oro: ante una respuesta ambigua el agente nunca actúa.
"""
import datetime as dt
import re

import pytest

from bankagent.responses import T
from bankagent.understanding import RuleRouter

TODAY = dt.date(2026, 6, 17)

# (mensaje, intención esperada, sub-acciones rechazadas)
CONFIRMATIONS = [
    # sí simple, por dialecto
    ("sí", "confirm", []), ("si", "confirm", []), ("sí, confirmo", "confirm", []), ("dale", "confirm", []),
    ("ok", "confirm", []), ("de acuerdo", "confirm", []), ("claro", "confirm", []), ("órale, sí", "confirm", []),
    ("sale", "confirm", []), ("va", "confirm", []), ("listo", "confirm", []), ("de una", "confirm", []),
    ("hacelo", "confirm", []), ("dale, abrila", "confirm", ["block_card"]), ("sí, hacelo nomás", "confirm", []),
    ("hazlo por favor", "confirm", []), ("sí, ambas", "confirm", []), ("las dos", "confirm", []),
    ("sim", "confirm", []), ("isso", "confirm", []), ("com certeza", "confirm", []), ("pode sim", "confirm", []),
    ("sim, as duas", "confirm", []), ("beleza, pode fazer", "confirm", []), ("claro que sim", "confirm", []),
    ("sí, no reconozco ese cargo", "confirm", []), ("no, no la reconozco, ábrela", "confirm", ["block_card"]),
    ("sim, não fui eu", "confirm", []),
    # sí con rechazo explícito del bloqueo
    ("sí, pero no bloquees la tarjeta que la uso para todo", "confirm", ["block_card"]),
    ("solo la disputa", "confirm", ["block_card"]), ("sin bloquear, solo la disputa", "confirm", ["block_card"]),
    ("dale, pero no me bloquees la tarjeta", "confirm", ["block_card"]),
    ("sí, abrí la disputa pero sin bloqueo", "confirm", ["block_card"]),
    ("sí, la tarjeta no", "confirm", ["block_card"]),
    ("nada más la disputa porfa", "confirm", ["block_card"]),
    ("sim, mas não bloqueie o cartão", "confirm", ["block_card"]), ("só a contestação", "confirm", ["block_card"]),
    ("pode abrir, sem bloquear", "confirm", ["block_card"]), ("apenas a contestação", "confirm", ["block_card"]),
    # no
    ("no", "deny", []), ("No.", "deny", []), ("mejor no", "deny", []), ("mejor no, gracias", "deny", []),
    ("nel", "deny", []), ("no quiero", "deny", []), ("cancelá todo", "deny", []), ("ni loco", "deny", []),
    ("não", "deny", []), ("nem pensar", "deny", []), ("melhor não", "deny", []), ("não quero", "deny", []),
    ("de jeito nenhum", "deny", []),
    # dudas o respuestas mixtas: nunca se actúa
    ("no sé, creo que sí", "unclear", []), ("mmm no estoy seguro", "unclear", []), ("capaz", "unclear", []),
    ("tal vez", "unclear", []), ("puede ser", "unclear", []), ("¿sí?", "unclear", []), ("sí y no", "unclear", []),
    ("no sé qué hacer", "unclear", []), ("dejame pensar", "unclear", []), ("solo bloqueá la tarjeta", "unclear", []),
    ("não sei", "unclear", []), ("acho que sim", "unclear", []), ("talvez", "unclear", []), ("pode ser", "confirm", []),
    ("sei lá", "unclear", []), ("no bloquees la tarjeta", "unclear", ["block_card"]), ("joya", "confirm", []),
    ("sí, ¿cuánto demora?", "confirm", []),
    ("no, no la bloquees", "unclear", ["block_card"]), ("não bloqueie o cartão", "unclear", ["block_card"]),
    ("no, no la reconozco", "unclear", []),
]


@pytest.mark.parametrize("text,intent,denials", CONFIRMATIONS)
def test_confirmation_is_tri_state_with_sub_action_denials(text, intent, denials):
    u = RuleRouter().understand(text, TODAY, "confirmation")
    assert (u.intent, u.sub_action_denials) == (intent, denials)


def disputes(env):
    return env.tools._ops.execute("SELECT count(*) FROM disputes").fetchone()[0]


def blocks(env):
    return env.tools._ops.execute("SELECT count(*) FROM card_blocks").fetchone()[0]


def test_yes_but_do_not_block_opens_only_the_dispute(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    r = env.agent.chat(th, tok, "No reconozco un cargo de 77 dólares")
    assert "solo la disputa" in r["reply"] and r["pending_action"]["block_card"]
    r = env.agent.chat(th, tok, "sí, pero no bloquees la tarjeta que la uso para todo")
    assert r["outcome"] == "resolved" and r["action_result"]["dispute"]["verified"]
    assert r["action_result"]["block"] is None and r["action_result"]["declined"] == ["block_card"]
    assert "no bloqueé la tarjeta" in r["reply"] and "bloqueé la tarjeta ****" not in r["reply"]
    assert (disputes(env), blocks(env)) == (1, 0)


def test_both_actions_need_an_explicit_yes(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    env.agent.chat(th, tok, "No reconozco un cargo de 77 dólares")
    r = env.agent.chat(th, tok, "sí, ambas")
    assert r["action_result"]["block"]["verified"] and (disputes(env), blocks(env)) == (1, 1)


def test_unclear_never_acts_reasks_once_then_hands_off(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    env.agent.chat(th, tok, "No reconozco un cargo de 77 dólares")
    r = env.agent.chat(th, tok, "no sé, creo que sí")
    assert r["outcome"] == "clarify" and r["awaiting"] == "confirmation"
    assert r["reply"].startswith(T["es"]["reask_consent"]) and "Confirmas" in r["reply"]
    r = env.agent.chat(th, tok, "mmm no estoy seguro")
    assert r["outcome"] == "handoff" and r["handoff"]["reason"] == "consent_unclear"
    assert r["awaiting"] is None and (disputes(env), blocks(env)) == (0, 0)


def test_partial_denial_narrows_the_offer_and_asks_again(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    env.agent.chat(th, tok, "No reconozco un cargo de 77 dólares")
    r = env.agent.chat(th, tok, "no bloquees la tarjeta")
    assert r["outcome"] == "clarify" and r["pending_action"]["block_card"] is None
    assert r["reply"].startswith(T["es"]["block_excluded"]) and "****" not in r["reply"]
    r = env.agent.chat(th, tok, "sí")
    assert r["outcome"] == "resolved" and (disputes(env), blocks(env)) == (1, 0)


def test_portuguese_only_the_dispute(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    env.agent.chat(th, tok, "Não reconheço uma cobrança de 77 dólares")
    r = env.agent.chat(th, tok, "sim, mas não bloqueie o cartão")
    assert r["outcome"] == "resolved" and "não bloqueei o cartão" in r["reply"]
    assert (disputes(env), blocks(env)) == (1, 0)


def test_no_card_offer_when_the_charge_is_on_an_account(env):
    """Retiro de una cuenta de ahorro: no hay tarjeta del producto -> solo se ofrece la disputa, sin "tarjeta -"."""
    tok, th = env.login("CLI-ANA"), env.thread()
    r = env.agent.chat(th, tok, "no reconozco un retiro de 610 dólares")
    assert r["pending_action"]["block_card"] is None and "tarjeta" not in r["reply"]
    assert "(sí / no)" in r["reply"]
    r = env.agent.chat(th, tok, "sí")
    assert r["outcome"] == "resolved" and r["action_result"]["block"] is None and blocks(env) == 0


def test_already_blocked_card_is_not_offered_again(env):
    tok = env.login("CLI-ANA")
    env.tools.block_card(tok, "PRD-ANA-CC", confirmed=True)
    r = env.agent.chat(env.thread(), tok, "No reconozco un cargo de 77 dólares")
    assert r["pending_action"]["block_card"] is None and "tarjeta" not in r["reply"]


def test_block_offer_is_declared_in_policy():
    from bankagent.policy import PolicyEngine
    p = PolicyEngine()
    assert p.offer_block({"product_status": "Active", "product_type": "Tarjeta Débito"}, {})
    assert not p.offer_block({"product_status": "Blocked", "product_type": "Tarjeta Débito"}, {})
    assert not p.offer_block(None, {})


@pytest.mark.parametrize("lang", ["es", "pt"])
def test_no_template_renders_a_dangling_card_dash(lang):
    """Ninguna plantilla muestra "tarjeta -" / "cartão -": las que llevan {card} solo se usan con tarjeta."""
    for key, tmpl in T[lang].items():
        assert not re.search(r"(tarjeta|cart[aã]o)\s*-", tmpl), key
        if "{card}" in tmpl:
            assert key in {"confirm_dispute", "block_suffix", "block_confirm", "block_done", "account_takeover_block"}, key


# ------------------------------------------------------------------ gramática del consentimiento (#71)
# Test v3 ciego: el sí PURO re-preguntaba respuestas naturales que repiten lo que se autoriza ("sí, ábranla y
# bloqueen la tarjeta"). Gramática: marcador afirmativo + mención de las acciones ofrecidas + cortesía; cualquier otra
# palabra sigue siendo `unclear`. Frases nuevas del equipo (es-MX, es-CO, es-AR, pt-BR); ninguna sale del test v3.
GRAMMAR = [
    # sí + las dos acciones nombradas -> las dos
    ("sí, abran la disputa y bloqueen la tarjeta", "confirm", []), ("sí, disputen y bloqueen", "confirm", []),
    ("dale, ambas cosas", "confirm", []), ("sim, pode abrir a contestação e bloquear o cartão", "confirm", []),
    ("órale, sí, la disputa y el bloqueo", "confirm", []), ("sí, las dos cosas por favor", "confirm", []),
    ("claro, abran el reclamo y también bloqueen la tarjeta", "confirm", []),
    ("sí señor, bloquéenme la tarjeta y abran el reclamo", "confirm", []), ("listo, disputa y bloqueo", "confirm", []),
    ("de una, abrí la disputa y bloqueá la tarjeta", "confirm", []), ("dale, bloqueala también", "confirm", []),
    ("joya, hacé las dos", "confirm", []), ("sí, a las dos", "confirm", []), ("sim, as duas coisas", "confirm", []),
    ("pode fazer as duas, por favor", "confirm", []), ("isso, contesta e bloqueia", "confirm", []),
    ("sim, bloqueia o cartão e abre a contestação", "confirm", []), ("beleza, pode bloquear e contestar", "confirm", []),
    ("sí, con las dos", "confirm", []), ("sí, adelante con ambas", "confirm", []),
    ("claro que sí, disputa y bloqueo de una vez", "confirm", []), ("sí, bloquéenla y ábranla", "confirm", []),
    ("sí, todo", "confirm", []), ("sim, tudo", "confirm", []), ("sí, bloquéenla por las dudas", "confirm", []),
    # sí que nombra SOLO la disputa -> el bloqueo no quedó autorizado (consentimiento por acción)
    ("sí, ábranla", "confirm", ["block_card"]), ("sí, pero solo la disputa", "confirm", ["block_card"]),
    ("sí, abran el reclamo", "confirm", ["block_card"]), ("dale, reclamalo", "confirm", ["block_card"]),
    ("sim, pode contestar", "confirm", ["block_card"]), ("sí, abrí el reclamo nomás", "confirm", ["block_card"]),
    ("sí, la disputa sí, el bloqueo no", "confirm", ["block_card"]),
    ("sí, abran la disputa; bloquear no hace falta", "confirm", ["block_card"]),
    ("sim, abre a contestação, o cartão não", "confirm", ["block_card"]),
    ("claro, reclámenlo, pero no bloqueen nada", "confirm", ["block_card"]),
    ("sim, só abrir a contestação", "confirm", ["block_card"]), ("sí, únicamente el reclamo", "confirm", ["block_card"]),
    ("dale, nada más el reclamo, la tarjeta dejala", "confirm", ["block_card"]),
    ("sí, abran la aclaración, bloqueo no", "confirm", ["block_card"]),
    ("sim, pode abrir; bloquear não precisa", "confirm", ["block_card"]),
    ("isso, contesta, mas sem bloquear", "confirm", ["block_card"]),
    ("sí, pero la tarjeta no me la bloqueen", "confirm", ["block_card"]),
    # nombra las acciones pero agrega condición, plazo, sarcasmo, a otra persona o lo hace él: nunca se actúa
    ("sí, ábranla mañana", "unclear", []), ("sí, yo la bloqueo después", "unclear", []),
    ("ya la bloqueé yo, solo abran la disputa", "unclear", ["block_card"]),
    ("sim, eu mesmo bloqueio o cartão", "unclear", []), ("sí, bloquéenla si vuelve a pasar", "unclear", []),
    ("dale, abrila cuando confirmes que fue fraude", "unclear", []), ("sí, disputa y bloqueo... es broma", "unclear", []),
    ("claro, bloquéala, como si eso sirviera de algo", "unclear", []), ("sim, contesta se for fraude mesmo", "unclear", []),
    ("sí, pero la disputa la abro yo en la sucursal", "unclear", []), ("sí, disputa no, solo bloqueo", "unclear", []),
    ("sí, bloqueen la tarjeta pero la disputa no", "unclear", []),
    ("sim, bloqueia, mas não abre a contestação", "unclear", []),
    ("sí, abran la disputa y de paso cancelen mi seguro", "unclear", []),
    ("sí, abran la disputa a nombre de mi hermano", "unclear", []),
    ("dale, abrila, pero que lo decida mi contador", "unclear", []),
    ("sí, ábranla y bloqueen la tarjeta de mi mamá", "unclear", []),
    ("sim, abre a contestação daqui a pouco", "unclear", []), ("sí, bloqueen todas mis tarjetas", "unclear", []),
    ("sí a la disputa, la tarjeta no la toquen", "unclear", ["block_card"]),
    ("no, ni disputa ni bloqueo", "deny", []),
]
NEVER_CONFIRM = ["¿abren la disputa y bloquean la tarjeta?", "sí, disputen el otro cargo también",
                 "sí, abran la disputa?", "¿y si la bloqueo yo?", "abran la disputa cuando mi esposo diga que sí",
                 "sí, bloqueen también la de débito"]  # otra tarjeta: pedido nuevo, no un sí a lo ofrecido


def test_grammar_corpus_is_large_and_new():
    import json
    import os

    from bankagent.pipeline import ROOT
    v3 = os.path.join(ROOT, "evals", "cases", "test_v3_blind.jsonl")
    seen = {t["user"].lower() for line in open(v3, encoding="utf-8") if line.strip()
            for t in json.loads(line)["turns"]}
    ours = {x[0].lower() for x in GRAMMAR} | {x.lower() for x in NEVER_CONFIRM}
    assert len(ours) >= 60 and not seen & ours


@pytest.mark.parametrize("text,intent,denials", GRAMMAR)
def test_consent_grammar_accepts_restated_actions_and_nothing_else(text, intent, denials):
    u = RuleRouter().understand(text, TODAY, "confirmation")
    assert (u.intent, u.sub_action_denials) == (intent, denials)


@pytest.mark.parametrize("text", NEVER_CONFIRM)
def test_questions_and_new_requests_are_never_consent(text):
    assert RuleRouter().understand(text, TODAY, "confirmation").intent != "confirm"


def test_restating_both_actions_opens_and_blocks(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    env.agent.chat(th, tok, "No reconozco un cargo de 77 dólares")
    r = env.agent.chat(th, tok, "sí, ábranme la disputa y bloquéenme la tarjeta, gracias")
    assert r["outcome"] == "resolved" and (disputes(env), blocks(env)) == (1, 1)


def test_naming_only_the_dispute_does_not_block(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    env.agent.chat(th, tok, "No reconozco un cargo de 77 dólares")
    r = env.agent.chat(th, tok, "dale, abran el reclamo")
    assert r["outcome"] == "resolved" and (disputes(env), blocks(env)) == (1, 0)
    assert "no bloqueé la tarjeta" in r["reply"]


def test_also_block_is_part_of_the_answer_not_a_new_request(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    env.agent.chat(th, tok, "No reconozco un cargo de 77 dólares")
    r = env.agent.chat(th, tok, "Sí, adelante con el reclamo. Y también bloquéenla")
    assert r["outcome"] == "resolved" and (disputes(env), blocks(env)) == (1, 1)


def test_explicit_human_request_wins_over_its_no(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    env.agent.chat(th, tok, "No reconozco un cargo de 77 dólares")
    r = env.agent.chat(th, tok, "no, mejor pásenme con un asesor")
    assert r["outcome"] == "handoff" and r["handoff"]["reason"] == "customer_request"
    assert (disputes(env), blocks(env)) == (0, 0)


# ------------------------------------------------------------------ elegir describiendo la opción (#71)
def test_choice_by_description_selects_among_the_shown_options(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    r = env.agent.chat(th, tok, "no reconozco un cargo de 345 dólares")
    assert r["awaiting"] == "option" and len(r["candidates"]) == 2
    r = env.agent.chat(th, tok, "el del 5 de junio")
    assert r["awaiting"] == "confirmation" and r["txn"]["transaction_id"] == "T-ANA-5"
    assert r["match_method"] == "customer_choice" and (disputes(env), blocks(env)) == (0, 0)


def test_choice_by_description_that_fits_two_options_does_not_guess(env):
    tok, th = env.login("CLI-ANA"), env.thread()
    env.agent.chat(th, tok, "no reconozco un cargo de 345 dólares")
    r = env.agent.chat(th, tok, "el de junio")
    assert r["awaiting"] != "confirmation" and not r.get("pending_action")


@pytest.mark.parametrize("text", ["ah no, ya me acordé, fui yo", "mejor no hagas nada", "deixa pra lá, era minha"])
def test_withdrawing_while_choosing_cancels(env, text):
    tok, th = env.login("CLI-ANA"), env.thread()
    env.agent.chat(th, tok, "no reconozco un cargo de 345 dólares")
    r = env.agent.chat(th, tok, text)
    assert r["outcome"] == "cancelled" and (disputes(env), blocks(env)) == (0, 0)


@pytest.mark.parametrize("text", ["no fui yo, es la 2", "no la reconozco", "não era minha"])
def test_restating_the_claim_while_choosing_is_not_withdrawing(text):
    assert RuleRouter().understand(text, TODAY, "option").intent != "deny"
