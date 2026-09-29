"""Demo web del agente de disputas: chat + traza + consola de handoff.

    streamlit run app/streamlit_app.py

Base de datos: `BANKAGENT_DB` si existe; si no, una base mínima construida desde el fixture de demo.
Toda la lógica de formato vive en `bankagent.ui` (probada offline); aquí solo se pinta.
"""
from __future__ import annotations

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from bankagent import ui  # noqa: E402

st.set_page_config(page_title="Agente de disputas · demo", layout="wide")


@st.cache_resource(show_spinner="Preparando la base de demo…")
def demo_db() -> tuple[str, str]:
    return ui.resolve_db_path()


db_path, db_source = demo_db()

# ------------------------------------------------------------------ estado de la sesión del navegador
if "demo" not in st.session_state:
    st.session_state.demo = ui.new_session(db_path, ui.SCENARIOS[0].customer_id)
demo: ui.DemoSession = st.session_state.demo
pending: str | None = None
fresh = False

# ------------------------------------------------------------------ barra lateral
with st.sidebar:
    st.header("Demo")
    options = [s.customer_id for s in ui.SCENARIOS]
    if db_source == "env":
        options.append("otro")
    choice = st.radio("Cliente (login simulado en la app)", options,
                      format_func=lambda c: f"{ui.scenario(c).name} — {ui.scenario(c).description}"
                      if ui.scenario(c) else "Otro ID de cliente (base real)")
    customer = st.text_input("ID de cliente", "CLI-") if choice == "otro" else choice
    if customer != demo.customer_id and len(customer) > 4:
        demo.restart(customer)

    c1, c2 = st.columns(2)
    if c1.button("Nueva conversación", width="stretch"):
        demo.restart()
    if c2.button("Vencer sesión", width="stretch", help="Fuerza la expiración del token (demo de sesión vencida)"):
        demo.expire()
        st.toast("Sesión vencida: el próximo mensaje debe ser rechazado.")
    show_raw = st.toggle("Mostrar estado crudo (JSON)")

    sc = ui.scenario(demo.customer_id)
    if sc:
        st.subheader("Mensajes de ejemplo")
        st.caption("Cada ejemplo abre una conversación nueva.")
        for i, ex in enumerate(sc.examples):
            if st.button(ex.label, key=f"ex{i}", help=ex.text, width="stretch"):
                pending, fresh = ex.text, True
    st.subheader("Respuestas")
    cols = st.columns(len(ui.FOLLOW_UPS))
    for i, ex in enumerate(ui.FOLLOW_UPS):
        if cols[i].button(ex.label, key=f"fu{i}"):
            pending, fresh = ex.text, False
    st.caption(f"Base: {'real (BANKAGENT_DB)' if db_source == 'env' else 'fixture de demo'} · "
               f"sesión {demo.customer_id} · thread {demo.thread_id[:8]}")

typed = st.chat_input("Escribe como cliente (es / pt)…")
if typed:
    pending, fresh = typed, False
if pending:
    if fresh and demo.turns:
        demo.restart()
    demo.send(pending)

# ------------------------------------------------------------------ cuerpo
last = demo.turns[-1]["state"] if demo.turns else {}
lang = last.get("lang") or "es"
st.title("Agente de disputas de cargos no reconocidos")
st.caption("El modelo interpreta y redacta; el código decide y actúa.")

chat_col, why_col = st.columns([3, 2], gap="large")

with chat_col:
    if not demo.turns:
        st.info("Elige un ejemplo en la barra lateral o escribe un mensaje.")
    for t in demo.turns:
        with st.chat_message("user"):
            st.markdown(t["user"])
        with st.chat_message("assistant"):
            st.markdown(t["state"].get("reply") or "")
            text, color = ui.outcome_badge(t["state"].get("outcome"))
            st.badge(text, color=color)

with why_col:
    st.subheader(ui.label("why", lang))
    if not demo.turns:
        st.caption("Aquí aparece la traza del turno: nodos, herramientas, reglas y hechos.")
    else:
        idx = st.selectbox("Turno", range(len(demo.turns)), index=len(demo.turns) - 1,
                           format_func=lambda i: f"{i + 1}. {demo.turns[i]['user'][:40]}")
        state = demo.turns[idx]["state"]
        rows = ui.turn_trace(state)
        st.markdown(f"**Traza** · {len(rows)} pasos · {ui.trace_total_ms(rows)} ms")
        for r in rows:
            with st.container(border=True):
                st.markdown(f"**{r['node']}** → `{r['next']}` · {r['ms']} ms")
                if r["detail"]:
                    st.caption(r["detail"])
                for tool in r["tools"]:
                    st.markdown(f":{'green' if tool['ok'] else 'red'}[{tool['text']}]")

        pol = ui.policy_view(state)
        st.markdown("**Política**")
        if pol:
            st.markdown(f"Decisión `{pol['outcome']}` · versión `{pol['version']}`")
            for rule in pol["rules"] or [{"id": "—", "outcome": "auto", "explain": "Ninguna regla bloqueó la disputa."}]:
                st.markdown(f"- `{rule['id']}` ({rule['outcome']}): {rule['explain']}")
            st.markdown("**Hechos verificados** (leídos por las herramientas, no del texto del cliente)")
            st.json(pol["facts"], expanded=False)
        else:
            st.caption("En este turno no se evaluó la política.")
        if show_raw:
            st.markdown("**Estado crudo**")
            st.json(ui.to_json(ui.raw_state(state)), expanded=False)

# ------------------------------------------------------------------ consola del asesor
hv = ui.handoff_view(last.get("handoff"))
with st.expander(ui.label("console", lang), expanded=bool(hv)):
    if not hv:
        st.caption("Sin handoff en el último turno. Prueba “Monto alto → asesor” o “fraude en Brasil”.")
    else:
        st.markdown(f"### Motivo: `{hv['reason']}`")
        st.markdown(hv["reason_text"])
        st.caption(f"Idioma del cliente: {hv['language']} · creado {hv['created_at']}")
        a, b = st.columns(2)
        with a:
            st.markdown("**Lo que pidió el cliente** (PII enmascarada)")
            for m in hv["request"]:
                st.markdown(f"> {m}")
            st.markdown("**Transacción verificada**")
            st.json(hv["transaction"] or {}, expanded=True)
            st.markdown("**Hechos del cliente**")
            st.json(hv["customer_facts"], expanded=True)
        with b:
            st.markdown(f"**Reglas disparadas** · política `{hv['policy_version']}`")
            for rule in hv["rules"] or [{"id": hv["reason"], "outcome": "handoff", "explain": hv["reason_text"]}]:
                st.markdown(f"- `{rule['id']}` ({rule['outcome']}): {rule['explain']}")
            st.markdown("**Acciones ya tomadas**")
            st.markdown("\n".join(f"- {x}" for x in hv["actions"]) or "Ninguna: el agente no ejecutó acciones.")
            st.markdown("**Evidencia (herramientas consultadas)**")
            st.markdown("\n".join(f"- {x}" for x in hv["evidence"]) or "—")
            st.markdown("**Preguntas pendientes para el asesor**")
            st.markdown("\n".join(f"- {x}" for x in hv["questions"]))
        with st.popover("Paquete JSON"):
            st.code(ui.to_json(last["handoff"]), language="json")

st.divider()
st.caption(ui.DISCLAIMER)
