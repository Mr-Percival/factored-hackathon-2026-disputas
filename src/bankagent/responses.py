"""Redacción de respuestas.

`TemplateWriter` (línea base) arma el texto solo con hechos del estado: no puede inventar cifras.
`LLMWriter` (`llm_writer.py`) mejora el tono y adapta el dialecto; su salida pasa por un verificador
determinista que compara cifras/fechas/IDs contra los hechos y, si falla, se usa la plantilla.
"""
from __future__ import annotations

from typing import Callable, Protocol

Country = Callable[[], "str | None"] | str | None


class Writer(Protocol):
    def write(self, key: str, lang: str, **facts) -> str: ...

    def rule_text(self, rule_id: str, explain_es: str, lang: str) -> str: ...

    def compose(self, key: str, lang: str, facts: dict, country: Country = None) -> tuple[str, dict | None]:
        """Texto final + telemetría del modelo (None si no hubo modelo). `country` puede ser una función
        (se evalúa solo si hace falta, para no consultar el perfil en cada turno)."""
        ...

T = {
    "es": {
        "session_missing": "Por seguridad necesito que inicies sesión en la app antes de continuar.",
        "session_expired": "Tu sesión expiró. Vuelve a autenticarte en la app y retomamos desde aquí.",
        "forbidden": "No puedo mostrar ni operar sobre información que no pertenece a tu sesión.",
        "blocked_input": "No puedo procesar esa solicitud. Si necesitas ayuda con un cargo que no reconoces, cuéntame el monto o la fecha.",
        "unknown": "Puedo ayudarte con cargos que no reconoces y con el bloqueo de tu tarjeta. ¿Qué cargo quieres revisar? Dime el monto, la fecha o el país.",
        "out_of_scope": "Ese tema no lo puedo resolver por este canal (solo atiendo cargos no reconocidos y bloqueo de tarjetas). Te comunico con un asesor.",
        "no_match": "No encontré movimientos con esos datos. ¿Me das el monto aproximado o la fecha del cargo?",
        "choose": "Encontré varios movimientos posibles. ¿Cuál es?\n{options}\nResponde con el número.",
        # Consentimiento por acción (#38): la disputa y el bloqueo se aceptan o rechazan por separado.
        "confirm_dispute": "Encontré el cargo: {txn}.\nPuedo abrir una disputa por este cargo y, además, bloquear preventivamente la tarjeta {card} para evitar nuevos cargos. ¿Confirmas? Responde «sí, ambas», «solo la disputa» o «no».",
        "confirm_dispute_no_card": "Encontré el cargo: {txn}.\nPuedo abrir una disputa por este cargo. ¿Confirmas? (sí / no)",
        "done_dispute": "Listo. Abrí la disputa {case_id} para el cargo {txn}{block}. Te contactaremos por la app con el resultado.",
        "block_suffix": " y bloqueé la tarjeta {card}",
        "block_declined_suffix": ". Como pediste, no bloqueé la tarjeta",
        "reask_consent": "No me quedó clara tu respuesta y no hago ningún cambio sin tu confirmación.",
        "block_excluded": "Entendido: no voy a bloquear la tarjeta.",
        "consent_unclear": "Como no me quedó clara tu respuesta, no hice ningún cambio. Le pasé tu caso a un asesor con toda la información para que lo confirme contigo.",
        "no_active_card": "No encontré una tarjeta activa para bloquear. Le pasé tu caso a un asesor para que lo revise contigo.",
        # conversación (#40)
        "customer_request": "Claro, te comunico con un asesor. Le pasé tu caso con lo que hablamos, para que no tengas que repetirlo.",
        "account_takeover": "Esto es urgente: pasé tu caso con prioridad alta al equipo de seguridad, que te contactará por un canal seguro. No compartas claves ni códigos con nadie.",
        "account_takeover_block": "Esto es urgente: pasé tu caso con prioridad alta al equipo de seguridad, que te contactará por un canal seguro. Mientras tanto puedo bloquear ya la tarjeta {card}. ¿Confirmas el bloqueo? (sí / no)",
        "account_takeover_choose": "Esto es urgente: pasé tu caso con prioridad alta al equipo de seguridad, que te contactará por un canal seguro. Mientras tanto puedo bloquear una de tus tarjetas. ¿Cuál?\n{options}\nResponde con el número.",
        "clarification_exhausted": "Perdón, no logré entender lo que necesitas y no quiero hacerte dar más vueltas. Le pasé la conversación a un asesor para que te ayude.",
        "dispute_status": "No encuentro esa disputa entre las que abriste por este canal. Le pasé tu consulta a un asesor para que revise su estado.",
        "dispute_status_found": "Tu disputa {case_id} está en estado {status} (abierta el {date}). Te avisaremos por la app cuando haya una resolución.",
        "cancel_dispute": "No puedo cancelar disputas por este canal. Le pasé tu pedido a un asesor para que lo gestione contigo.",
        "none_of_these": "Entendido, no es ninguna de esas. ¿Me das otro dato del cargo? Por ejemplo la fecha, el comercio o el monto aproximado.",
        "closing": "Con gusto. Si ves otro cargo que no reconoces, escríbeme por aquí.",
        "closing_pending": "Con gusto. No hice ningún cambio. Si ves otro cargo que no reconoces, escríbeme por aquí.",
        "cancelled": "Entendido, no hice ningún cambio. ¿Te ayudo con algo más?",
        "rule": "Revisé el cargo {txn}: {explain}",
        "handoff": "Revisé el cargo {txn}. {explain} Ya le pasé tu caso a un asesor con toda la información, no tendrás que repetirla.",
        "tool_failure": "Tengo un problema técnico para consultar tus movimientos. Para no hacerte esperar, te comunico con un asesor.",
        "block_confirm": "¿Confirmas que quieres bloquear la tarjeta {card}? (sí / no)",
        "block_done": "Listo, la tarjeta {card} quedó bloqueada.",
        "security_lockout": "Por seguridad pausé esta conversación y no puedo procesar más solicitudes por aquí. Un asesor revisará tu caso y te contactará por un canal seguro.",
    },
    "pt": {
        "session_missing": "Por segurança, preciso que você faça login no app antes de continuar.",
        "session_expired": "Sua sessão expirou. Faça login novamente no app e continuamos daqui.",
        "forbidden": "Não posso mostrar nem operar informações que não pertencem à sua sessão.",
        "blocked_input": "Não posso processar essa solicitação. Se precisar de ajuda com uma cobrança que não reconhece, me diga o valor ou a data.",
        "unknown": "Posso ajudar com cobranças que você não reconhece e com o bloqueio do seu cartão. Qual cobrança quer verificar? Diga o valor, a data ou o país.",
        "out_of_scope": "Não consigo resolver esse assunto por aqui (atendo apenas cobranças não reconhecidas e bloqueio de cartões). Vou transferir para um atendente.",
        "no_match": "Não encontrei movimentações com esses dados. Pode me dizer o valor aproximado ou a data da cobrança?",
        "choose": "Encontrei várias movimentações possíveis. Qual é?\n{options}\nResponda com o número.",
        "confirm_dispute": "Encontrei a cobrança: {txn}.\nPosso abrir uma contestação desta cobrança e, além disso, bloquear preventivamente o cartão {card} para evitar novas cobranças. Confirma? Responda «sim, as duas», «só a contestação» ou «não».",
        "confirm_dispute_no_card": "Encontrei a cobrança: {txn}.\nPosso abrir uma contestação desta cobrança. Confirma? (sim / não)",
        "done_dispute": "Pronto. Abri a contestação {case_id} para a cobrança {txn}{block}. Avisaremos o resultado pelo app.",
        "block_suffix": " e bloqueei o cartão {card}",
        "block_declined_suffix": ". Como você pediu, não bloqueei o cartão",
        "reask_consent": "Não entendi bem sua resposta e não faço nenhuma alteração sem a sua confirmação.",
        "block_excluded": "Entendido: não vou bloquear o cartão.",
        "consent_unclear": "Como sua resposta não ficou clara, não fiz nenhuma alteração. Passei seu caso para um atendente com todas as informações para confirmar com você.",
        "no_active_card": "Não encontrei um cartão ativo para bloquear. Passei seu caso para um atendente revisar com você.",
        "customer_request": "Claro, vou transferir para um atendente. Passei seu caso com o que conversamos, para você não precisar repetir.",
        "account_takeover": "Isso é urgente: passei seu caso com prioridade alta para a equipe de segurança, que vai entrar em contato por um canal seguro. Não compartilhe senhas nem códigos com ninguém.",
        "account_takeover_block": "Isso é urgente: passei seu caso com prioridade alta para a equipe de segurança, que vai entrar em contato por um canal seguro. Enquanto isso, posso bloquear agora o cartão {card}. Confirma o bloqueio? (sim / não)",
        "account_takeover_choose": "Isso é urgente: passei seu caso com prioridade alta para a equipe de segurança, que vai entrar em contato por um canal seguro. Enquanto isso, posso bloquear um dos seus cartões. Qual?\n{options}\nResponda com o número.",
        "clarification_exhausted": "Desculpe, não consegui entender o que você precisa e não quero fazer você dar mais voltas. Passei a conversa para um atendente ajudar você.",
        "dispute_status": "Não encontrei essa contestação entre as abertas por este canal. Passei sua consulta para um atendente verificar o status.",
        "dispute_status_found": "Sua contestação {case_id} está com status {status} (aberta em {date}). Avisaremos pelo app quando houver uma resolução.",
        "cancel_dispute": "Não consigo cancelar contestações por este canal. Passei seu pedido para um atendente cuidar disso com você.",
        "none_of_these": "Entendido, não é nenhuma dessas. Pode me dar outro dado da cobrança? Por exemplo a data, o estabelecimento ou o valor aproximado.",
        "closing": "Por nada. Se vir outra cobrança que não reconhece, é só me escrever por aqui.",
        "closing_pending": "Por nada. Não fiz nenhuma alteração. Se vir outra cobrança que não reconhece, é só me escrever por aqui.",
        "cancelled": "Entendido, não fiz nenhuma alteração. Posso ajudar em algo mais?",
        "rule": "Verifiquei a cobrança {txn}: {explain}",
        "handoff": "Verifiquei a cobrança {txn}. {explain} Já passei seu caso para um atendente com todas as informações, você não precisará repetir.",
        "tool_failure": "Estou com um problema técnico para consultar suas movimentações. Para você não esperar, vou transferir para um atendente.",
        "block_confirm": "Confirma que deseja bloquear o cartão {card}? (sim / não)",
        "block_done": "Pronto, o cartão {card} foi bloqueado.",
        "security_lockout": "Por segurança, pausei esta conversa e não posso processar mais solicitações por aqui. Um atendente vai revisar seu caso e entrará em contato por um canal seguro.",
    },
}

# Explicaciones de reglas de política traducidas (la fuente de verdad es el id de regla)
RULE_PT = {
    "D01_already_disputed": "Já existe uma contestação aberta para esta transação.",
    "D02_declined_not_charged": "A transação foi recusada: não gerou cobrança.",
    "D03_already_reversed": "A transação já foi estornada.",
    "D04_pending": "A transação está pendente; poderá ser contestada quando for lançada.",
    "D05_too_old": "Passou o prazo de 120 dias para contestar.",
    "H01_customer_not_active": "Sua conta precisa de revisão por um atendente.",
    "H02_high_amount": "Por ser um valor alto, um analista precisa revisar a contestação.",
    "H03_fraud_signal": "Há sinais de fraude; vou transferir para um analista de fraude.",
    "H04_repeat_complainer": "Seu caso precisa de revisão por um atendente.",
}


def fmt_txn(t: dict) -> str:
    d = t["transaction_date"]
    date = d.strftime("%d/%m/%Y") if hasattr(d, "strftime") else str(d)[:10]
    where = t.get("merchant_name") or t.get("channel")
    place = f", {t['transaction_city']}" if t.get("transaction_city") else ""
    return f"{date} · {float(t['amount']):,.2f} {t['currency']} · {where} ({t['transaction_country']}{place})"


HANDOFF_LABELS = {  # motivos que no son reglas de política (las reglas traen su propio `explain`)
    "out_of_scope": "Solicitud fuera del alcance del canal automático.",
    "tool_failure": "Falla técnica persistente al consultar datos; no se pudo verificar.",
    "action_not_verified": "La acción se ejecutó pero no se pudo verificar en el sistema.",
    "security_lockout": "Conversación pausada por intentos bloqueados (seguridad).",
    "no_active_card": "El cliente pidió un bloqueo pero no tiene tarjetas activas.",
}


def handoff_summary(packet: dict) -> str:
    """Una línea para el asesor, armada SOLO con campos del paquete (determinista, sin modelo, en español).
    Motivo · transacción verificada · estado del cliente · acciones ya hechas."""
    reason = packet.get("reason") or "unspecified"
    rules = (packet.get("policy") or {}).get("rules_fired") or []
    hit = next((r for r in rules if r.get("id") == reason), None)
    parts = [f"{reason}: {hit['explain'] if hit else HANDOFF_LABELS.get(reason, 'Motivo no especificado.')}"]
    facts = packet.get("verified_facts") or {}
    t = facts.get("transaction")
    if t:
        d = t.get("transaction_date")
        date = d.strftime("%d/%m/%Y") if hasattr(d, "strftime") else "/".join(reversed(str(d)[:10].split("-")))
        where = t.get("merchant_name") or t.get("channel") or "-"
        place = ", ".join(x for x in (t.get("transaction_country"), t.get("transaction_city")) if x)
        parts.append(f"Cargo {t.get('transaction_id')} del {date} por {float(t.get('amount') or 0):,.2f} {t.get('currency')}"
                     f" ({t.get('transaction_type')}, {where}, {place}, estado {t.get('transaction_status')})")
    else:
        parts.append("Sin transacción identificada")
    if facts.get("customer_status"):
        rec = ", reclamante recurrente" if facts.get("is_repeat_complainer") else ""
        parts.append(f"Cliente {facts['customer_status']}/{facts.get('segment')}, "
                     f"{facts.get('complaints_last_90d', 0)} reclamos en 90 días{rec}")
    acts = packet.get("actions_taken") or []
    parts.append("Acciones: " + (", ".join(a["tool"] for a in acts) if acts else "ninguna"))
    return " · ".join(parts) + "."


def fmt_option(c: dict) -> str:
    if c.get("kind") == "card":
        return f"{c['product_type']} {c['product_number']} ({c['currency']})"
    return fmt_txn(c)


class TemplateWriter:
    name = "templates"

    def write(self, key: str, lang: str, **facts) -> str:
        return T[lang][key].format(**facts)

    def compose(self, key: str, lang: str, facts: dict, country: Country = None) -> tuple[str, dict | None]:
        return self.write(key, lang, **facts), None

    def rule_text(self, rule_id: str, explain_es: str, lang: str) -> str:
        return RULE_PT.get(rule_id, explain_es) if lang == "pt" else explain_es
