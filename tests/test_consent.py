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
    ("hacelo", "confirm", []), ("dale, abrila", "confirm", []), ("sí, hacelo nomás", "confirm", []),
    ("hazlo por favor", "confirm", []), ("sí, ambas", "confirm", []), ("las dos", "confirm", []),
    ("sim", "confirm", []), ("isso", "confirm", []), ("com certeza", "confirm", []), ("pode sim", "confirm", []),
    ("sim, as duas", "confirm", []), ("beleza, pode fazer", "confirm", []), ("claro que sim", "confirm", []),
    ("sí, no reconozco ese cargo", "confirm", []), ("no, no la reconozco, ábrela", "confirm", []),
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
    ("não sei", "unclear", []), ("acho que sim", "unclear", []), ("talvez", "unclear", []), ("pode ser", "unclear", []),
    ("sei lá", "unclear", []), ("no bloquees la tarjeta", "unclear", ["block_card"]),
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
            assert key in {"confirm_dispute", "block_suffix", "block_confirm", "block_done"}, key
