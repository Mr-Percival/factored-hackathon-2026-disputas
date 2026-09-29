"""Render de reports/replay.md a partir del resumen de `replay.run` (todo texto sale de los números)."""
from __future__ import annotations

import math

from .matching import AMOUNT_TOL, PREFERRED_TYPES, WINDOW_DAYS
from .replay import MAX_TURNS, WINDOWS

GROUP_ES = {"auto_resolved": "Resolución automática segura (disputa abierta y verificada)",
            "handoff": "Derivado a humano (handoff)", "rejected": "Rechazada por política (D02–D05)",
            "informed": "Informada (D01: ya disputada)", "not_identified": "Cargo no identificado en la conversación",
            "wrong_txn": "Decisión sobre una transacción distinta a la emparejada",
            "other": "Otro", "unmatched": "Sin transacción plausible (iría a un humano, no se conversa)"}
REASON_ES = {"router_sin_confianza": "El router no reconoció el pedido (confianza < 0,6)",
             "busqueda_sin_resultados": "La búsqueda no encontró el cargo con los datos dados",
             "no_esta_entre_opciones": "El cargo no estaba entre las opciones mostradas",
             "propuso_otro_cargo": "El agente propuso otro cargo y el cliente lo rechazó"}
RULE_ES = {"R1_amount": "R1 · monto reclamado ±10%", "R2_type_approved": "R2 · más reciente Approved del tipo esperado",
           "R3_any_approved": "R3 · más reciente Approved (cualquier tipo)", "R4_any_status": "R4 · más reciente (cualquier estado)",
           "unmatched": "Sin match"}


def pct(x: float, d: int = 1) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.{d}f}%"


def ci(r: dict) -> str:
    return f"{pct(r['p'])} [{pct(r['lo'])}–{pct(r['hi'])}]" if r["n"] else "–"


def num(x, d: int = 0) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{x:,.{d}f}".replace(",", " ")


def table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render_markdown(s: dict) -> str:
    m, meta, f = s["metrics"], s["meta"], s["frame"]
    n = m["n"]
    L: list[str] = []
    w = L.append
    w("# Replay de quejas históricas + modo sombra")
    w("")
    w("> **SIMULACIÓN OFFLINE — no es una medición de producción.** Quejas reales del dataset (sintético) del organizador, "
      "convertidas en conversaciones con un cliente **simulado** y pasadas por el agente real (reglas + plantillas, sin LLM). "
      "La transacción disputada se **infiere** con una regla (las quejas no la traen), así que el agente se mide contra esa "
      "regla, no contra una verdad conocida. Las proyecciones de negocio están aparte, en la sección 8, rotuladas **PROYECCIÓN**.")
    w("")
    w(f"Generado por `{meta['command']}` · commit `{meta['git_sha']}`{' (con cambios sin commit)' if meta['git_dirty'] else ''} · "
      f"política `{meta['policy_version']}` · {meta['generated_at'][:10]}. Detalle en la sección 10.")
    w("")

    # ------------------------------------------------------------ resumen
    w("## Resumen — SIMULACIÓN")
    w("")
    g = m["groups"]
    rows = [["Quejas en la muestra", num(n), "", ""],
            ["Con transacción plausible (automatización intentada)", ci(m["attempted"]), num(m["attempted"]["k"]), num(n)],
            ["**Resolución automática segura** (del total)", ci(m["safe_auto_of_all"]), num(m["safe_auto_of_all"]["k"]), num(n)],
            ["Resolución automática segura (de las intentadas)", ci(m["safe_auto_of_attempted"]), num(m["safe_auto_of_attempted"]["k"]),
             num(m["safe_auto_of_attempted"]["n"])]]
    for key in ("handoff", "rejected", "informed", "not_identified", "wrong_txn", "unmatched"):
        if key in g:
            rows.append([GROUP_ES[key], ci(g[key]), num(g[key]["k"]), num(n)])
    rows.append(["Acciones inseguras (otro cargo, sin confirmación o sin verificar)", ci(m["unsafe"]), num(m["unsafe"]["k"]), num(n)])
    rows.append(["Turnos del cliente por caso (p50 / p95)", f"{num(m['turns']['p50'])} / {num(m['turns']['p95'], 1)}", "",
                 num(m["attempted"]["k"])])
    rows.append(["Latencia por turno p50 / p95 (local, sin LLM)",
                 f"{num(m['latency_turn_ms']['p50'])} / {num(m['latency_turn_ms']['p95'])} ms", "", num(m["latency_turn_ms"]["n"])])
    w(table(["Métrica (SIMULACIÓN)", "Valor [IC 95% Wilson]", "k", "n"], rows))
    w("")
    w("Lectura: *resolución automática segura* = el agente encontró el cargo emparejado, pidió confirmación, abrió la disputa "
      "(y bloqueó la tarjeta si estaba activa), ambas acciones verificadas releyendo el estado, **y** la política evaluada por "
      "separado sobre ese cargo a la fecha de la queja dice `auto_with_confirmation`. Resolver = abrir la disputa en el primer "
      "contacto; el resultado final de la disputa (abono o no) no se simula.")
    w("")

    # ------------------------------------------------------------ 1 marco
    w("## 1. Marco muestral")
    w("")
    w(f"- **Marco:** todas las quejas con subcategoría *Cargo no reconocido* o *Cobro indebido* en la base serving: "
      f"**{num(f['n'])}** quejas, creadas entre {f['date_min'][:10]} y {f['date_max'][:10]}.")
    w(f"- **Muestra:** {num(s['sample_n'])} quejas, estratificada por país × segmento × case_type (asignación proporcional con "
      f"restos mayores; dentro de cada estrato, al azar con `seed={meta['seed']}`). Se incluyen las quejas sin transacción "
      "plausible: su proporción es un resultado.")
    w("")
    for key, title in (("country", "País"), ("segment", "Segmento"), ("case_type", "case_type"), ("subcategory", "Subcategoría")):
        samp = {}
        for r in s["breakdowns"][key]:
            samp[r["value"]] = r["n"]
        rows = [[k, num(v), pct(v / f["n"]), num(samp.get(k, 0)), pct(samp.get(k, 0) / n if n else float("nan"))]
                for k, v in f["by"][key].items()]
        w(table([title, "Marco", "% marco", "Muestra", "% muestra"], rows))
        w("")

    # ------------------------------------------------------------ 2 emparejamiento
    w("## 2. Regla de emparejamiento queja → transacción y cobertura")
    w("")
    w("Las quejas **no** traen la transacción (`origin_interaction_id` 100% nulo, descripción de plantilla). La regla, "
      "escalonada y documentada en `src/bankagent/evals/matching.py`:")
    w("")
    w(f"- **Conjunto de candidatas:** transacciones del mismo cliente, de tipo disputable (Purchase, Withdrawal, Payment, "
      f"Transfer, Adjustment; el mismo filtro que usa el agente) y con fecha en `[creation_date − {WINDOW_DAYS} días, creation_date]`.")
    w(f"- **R1:** `claimed_amount` presente, misma moneda y a ±{AMOUNT_TOL:.0%} → la de monto más cercano.")
    w(f"- **R2:** la más reciente *Approved* del tipo esperado (Cargo no reconocido: {'/'.join(PREFERRED_TYPES['Cargo no reconocido'])}; "
      f"Cobro indebido: {'/'.join(PREFERRED_TYPES['Cobro indebido'])}).")
    w("- **R3:** la más reciente *Approved* de cualquier tipo disputable. **R4:** la más reciente de cualquier estado.")
    w("- **Sin match:** no hay candidatas → en operación iría a un humano; no se simula conversación.")
    w("")
    rows = [[RULE_ES[k], ci(v), num(v["k"])] for k, v in s["coverage"].items()]
    w(table([f"Regla (muestra, n={n})", "% [IC 95%]", "k"], rows))
    w("")
    w(f"**Cobertura en el marco completo según la ventana** (n={num(f['n'])}; candidatas = transacciones disputables del cliente "
      "en la ventana; *1* = identificación directa, *2–5* = el agente mostraría opciones, *>5* = muy ambiguo):")
    w("")
    rows = []
    for win in WINDOWS:
        c = f["windows"][win] if win in f["windows"] else f["windows"][str(win)]
        tot = sum(c.values())
        rows.append([f"{win} días", pct(1 - c["0"] / tot), pct(c["0"] / tot), pct(c["1"] / tot), pct(c["2-5"] / tot), pct(c[">5"] / tot)])
    w(table(["Ventana", "Con ≥1 candidata", "0", "1", "2–5", ">5"], rows))
    w("")
    w("Hallazgos sobre los campos de enlace (marco completo):")
    w("")
    w(f"- `affected_product_id` está presente en {num(f['with_product'])} quejas ({pct(f['with_product'] / f['n'])}), pero "
      f"**pertenece al cliente de la queja en {num(f['product_owned'])}** de ellas. Es un campo aleatorio respecto del cliente, "
      "así que la regla no lo usa (exigirlo dejaría 0% de cobertura).")
    w(f"- {num(f['customers_without_txn'])} quejas ({pct(f['customers_without_txn'] / f['n'])}) son de clientes **sin ninguna "
      "transacción** en la base: nunca pueden emparejarse.")
    cl = s["claim"]
    if cl["n"]:
        w(f"- `claimed_amount` (en la muestra, {num(cl['n'])} quejas lo traen): R1 empareja {num(cl['own'])} "
          f"({pct(cl['own'] / cl['n'])}); con montos de **otras** quejas al azar (control, {cl['control_k']} sorteos por queja) "
          f"empareja en promedio {num(cl['control'], 1)} ({pct(cl['control'] / cl['n'])}). En el dataset el monto reclamado tiene "
          "la misma distribución (~0–5.000) en COP, ARS, USD y MXN, su moneda no depende del país del cliente y no hay "
          "transacciones en MXN: el monto reclamado **casi no aporta información** para encontrar el cargo, y los pocos R1 "
          "pueden ser coincidencias.")
    else:
        w("- `claimed_amount` no disponible (corrida sin `--history-db`): R1 no se evaluó.")
    w("")

    # ------------------------------------------------------------ 3 método
    w("## 3. Método de la simulación")
    w("")
    w("- **Agente:** `build_agent(db, router=\"rules\", writer=\"templates\")`, uno nuevo por caso y un hilo nuevo por "
      "conversación; login simulado (`IdentityService`), sin LLM ni red. Disputas y bloqueos se reinician entre casos.")
    w("- **A la fecha de la queja:** cada caso usa `PolicyEngine(as_of=creation_date)` (así D05 — 120 días — y las fechas "
      "relativas \"ayer\" / \"la semana pasada\" se resuelven contra el día de la queja, no contra el `as_of` del YAML, "
      f"{meta['policy_as_of_yaml']}). La búsqueda de movimientos no ve transacciones posteriores a la queja y H04 se calcula "
      "con las quejas del cliente hasta esa fecha (`PointInTimeTools`).")
    w("- **Mensaje del cliente (generado por el equipo):** menciona monto y/o fecha y el país si el cargo fue en el extranjero, "
      "nunca IDs; dialecto por país del cliente (MX, CO, AR con voseo). Estilos: monto + fecha (50%), solo monto (25%), "
      "solo fecha (25%); 40% de los montos ≥ 100 se dicen redondeados (\"unos $1.300\"). "
      f"Una submuestra ({pct(meta['pt_share'], 0)} de los casos emparejados) se corre también en **pt-BR: traducción hecha por el "
      "equipo** (el dataset no tiene portugués).")
    w("- **Cliente simulado:** confirma (\"sí\" / \"sim\") solo si el cargo propuesto es el emparejado (si no, dice \"no, ese no es\"); "
      "si le muestran opciones, elige la emparejada comparando IDs (simula que reconoce su cargo); si no aparece o le piden más "
      f"datos, da **una vez** el monto exacto y la fecha completa. Si aun así no aparece → *no identificado*. Tope de {MAX_TURNS} turnos.")
    w("")

    # ------------------------------------------------------------ 4 métricas
    w(f"## 4. Métricas — SIMULACIÓN (n={n}, una conversación por queja en su dialecto)")
    w("")
    rows = [[GROUP_ES.get(k, k), ci(v), num(v["k"])] for k, v in m["groups"].items()]
    w(table(["Resultado", "% del total [IC 95%]", "k"], rows))
    w("")
    if m["handoff_by_rule"]:
        rows = [[k, ci(v), num(v["k"])] for k, v in sorted(m["handoff_by_rule"].items(), key=lambda kv: -kv[1]["k"])]
        w(table(["Handoff por regla (primera que decide)", "% del total", "k"], rows))
        w("")
    if m["reject_by_rule"]:
        rows = [[k, ci(v), num(v["k"])] for k, v in sorted(m["reject_by_rule"].items(), key=lambda kv: -kv[1]["k"])]
        w(table(["Rechazo / informa por regla", "% del total", "k"], rows))
    else:
        w("**Rechazos por política (D01–D05): 0 casos.** Es consecuencia de la regla de emparejamiento, no del agente: R2/R3 "
          "prefieren un cargo *Approved* (D02–D04 no pueden disparar) y la ventana de "
          f"{WINDOW_DAYS} días es menor que el plazo de 120 (D05 no puede disparar). La sección 6 muestra la decisión con una "
          "regla alternativa que no prefiere *Approved*.")
    w("")
    nr = s.get("not_identified_reasons_by_lang") or {}
    if any(nr.values()):
        w("**Por qué no se identificó el cargo** (conversaciones que terminaron en *no identificado*):")
        w("")
        reasons = sorted({k for v in nr.values() for k in v})
        w(table(["Motivo", "es", "pt-BR"], [[REASON_ES.get(k, k), num(nr.get("es", {}).get(k, 0)), num(nr.get("pt", {}).get(k, 0))]
                                            for k in reasons]))
        w("")
        w("Al revisar las transcripciones de esos casos (`data/replay/cases.jsonl`) aparecen dos causas en el router de reglas "
          "(`understanding.py`), que son hallazgos del replay y no se corrigen en este cambio: (1) la lista de palabras clave de "
          "disputa tiene `\"no reconheco\"` en vez de `\"nao reconheco\"`, así que \"não reconheço\" no cuenta como pedido de "
          "disputa en portugués; (2) el comercio **\"Taxi Seguro\"** contiene `seguro`, palabra de *fuera de alcance*: si el "
          "mensaje tiene una sola palabra de disputa, empata, la confianza baja a 0,5 y el agente vuelve a preguntar.")
        w("")
    d = s["direct"]
    hits = ", ".join(f"{k}: {v}" for k, v in sorted(d["hits"].items()))
    w(f"Reglas que se cumplen sobre el cargo emparejado (pueden ser varias por caso): {hits or '–'}.")
    w("")
    c = m["clarify"]
    w(f"- **Aclaraciones:** {ci(c['share_with_any'])} de las conversaciones intentadas necesitaron al menos un turno de "
      f"aclaración (pedir datos u opciones); media {num(c['mean'], 2)} por caso.")
    w(f"- **Turnos del cliente:** media {num(m['turns']['mean'], 2)}, p50 {num(m['turns']['p50'])}, p95 {num(m['turns']['p95'], 1)}, "
      f"máx {num(m['turns']['max'])}.")
    w(f"- **Latencia** (proceso local, DuckDB con {num(f['n'])} quejas y la tabla completa de transacciones, sin LLM): por turno "
      f"p50 {num(m['latency_turn_ms']['p50'])} ms / p95 {num(m['latency_turn_ms']['p95'])} ms; por caso p50 "
      f"{num(m['latency_case_ms']['p50'])} ms / p95 {num(m['latency_case_ms']['p95'])} ms. No incluye red ni LLM; ver "
      "`reports/capacity.md` para carga concurrente.")
    w("")
    for key, title in (("country", "País"), ("segment", "Segmento"), ("case_type", "case_type"), ("subcategory", "Subcategoría"),
                       ("match_rule", "Regla de match"), ("pool_class", "Candidatas en la ventana"), ("style", "Estilo del mensaje")):
        rows = [[r["value"] if r["value"] is not None else "(sin conversación)", num(r["n"]), ci(r["safe"]), pct(r["handoff"]),
                 pct(r["rejected"]), pct(r["not_identified"]), pct(r["unmatched"])] for r in s["breakdowns"][key]]
        w(f"**Por {title.lower()}**")
        w("")
        w(table([title, "n", "Auto segura [IC 95%]", "Handoff", "Rechazo", "No identificado", "Sin match"], rows))
        w("")
    pt = s["pt"]
    if pt["n"]:
        mp, me = pt["metrics_pt"], pt["metrics_es_same_cases"]
        w(f"**Idioma (pares sobre los mismos casos, n={pt['n']}; pt-BR = traducción del equipo):**")
        w("")
        w(table(["", "es (dialecto del país)", "pt-BR"],
                [["Resolución automática segura", ci(me["safe_auto_of_all"]), ci(mp["safe_auto_of_all"])],
                 ["Handoff", ci(me["groups"]["handoff"]), ci(mp["groups"]["handoff"])],
                 ["No identificado", ci(me["groups"].get("not_identified", {"k": 0, "n": pt["n"], "p": 0, "lo": 0, "hi": 0})),
                  ci(mp["groups"].get("not_identified", {"k": 0, "n": pt["n"], "p": 0, "lo": 0, "hi": 0}))],
                 ["Turnos p50", num(me["turns"]["p50"]), num(mp["turns"]["p50"])]]))
        w("")
        w(f"Mismo resultado final en ambos idiomas: {ci(pt['same_class'])}.")
        if pt["diffs"]:
            w("Diferencias: " + "; ".join(f"`{k}` ({v})" for k, v in pt["diffs"].items()) + ".")
        w("")

    # ------------------------------------------------------------ 5 histórico
    if "historical" in s:
        h = s["historical"]
        a = h["all"]
        w("## 5. Comparación con la operación humana histórica — **no comparable 1:1**")
        w("")
        w("Mismas quejas de la muestra, desenlace registrado en el dataset. No es una comparación de igual a igual: el agente "
          "*abre* la disputa en el primer contacto; el histórico mide la *resolución completa* del caso por el back-office, que "
          "el replay no simula. Sirve para dimensionar el punto de partida, no para afirmar una mejora medida.")
        w("")
        w(table(["Operación histórica (mismas quejas)", "Valor", "n"],
                [["Estado: " + ", ".join(f"{k} {pct(v / a['n'])}" for k, v in a["status"].items()), "", num(a["n"])],
                 ["Incumplimiento de SLA", ci(a["sla"]), num(a["n"])],
                 ["Días de resolución p50 / p75 (solo con resolución registrada)",
                  f"{num(a['resolution_days']['p50'])} / {num(a['resolution_days']['p75'])}", num(a["resolution_days"]["n"])],
                 ["Horas hasta la primera respuesta p50 / p75", f"{num(a['first_response_h']['p50'], 1)} / {num(a['first_response_h']['p75'], 1)}",
                  num(a["first_response_h"]["n"])],
                 ["Con compensación otorgada", ci(a["compensation"]), num(a["n"])]]))
        w("")
        rows = [[GROUP_ES.get(k, k), num(v["n"]), pct(v["status"].get("Resolved", 0) / v["n"] + v["status"].get("Closed", 0) / v["n"]) if v["n"] else "–",
                 pct(v["sla"]["p"]), num(v["resolution_days"]["p50"]), pct(v["compensation"]["p"])]
                for k, v in h["by_group"].items()]
        w(table(["Resultado en la simulación", "n", "Hist. resuelta/cerrada", "Hist. SLA incumplido", "Hist. días p50", "Hist. compensación"], rows))
        w("")
        w(f"En la simulación el agente responde en segundos (p50 {num(m['latency_case_ms']['p50'])} ms de cómputo por caso) frente "
          f"a una primera respuesta humana de {num(a['first_response_h']['p50'], 1)} h (p50). Esa brecha es de **tiempo hasta la "
          "primera respuesta / apertura**, no de resolución, y es una simulación.")
        w("")

    # ------------------------------------------------------------ 6 sombra
    if "shadow" in s:
        sh = s["shadow"]
        w("## 6. Modo sombra: decisión de la política vs desenlace histórico")
        w("")
        w(f"Decisión de la política sobre el cargo emparejado (a la fecha de la queja, sin conversación) contra el estado "
          f"histórico agrupado (resuelta = Resolved/Closed; abierta = Open/In Process). n={sh['n']} quejas emparejadas.")
        w("")
        mt = sh["matrix"]
        rows = [[r] + [num(x) for x in mt["m"][i]] + [num(sum(mt["m"][i]))] for i, r in enumerate(mt["rows"])]
        rows.append(["**total**"] + [num(sum(col)) for col in zip(*mt["m"])] + [num(sh["n"])])
        w(table(["Política \\ Histórico"] + mt["cols"] + ["total"], rows))
        w("")
        w(f"Asociación: V de Cramér = {sh['cramers_v']:.3f} (permutación, p = {sh['cramers_p']:.3f}).")
        w("")
        rows = []
        for name, k in sh["binary"].items():
            rows.append([name.replace("_", " "), num(k["n"]), pct(k["p_a"]), pct(k["p_b"]), pct(k["p_o"]), pct(k["p_e"]),
                         f"{k['kappa']:.3f}", f"{k['perm_p']:.3f}"])
        w(table(["Par (política vs histórico)", "n", "% política", "% histórico", "Acuerdo obs.", "Acuerdo por azar", "κ Cohen",
                 "p (perm.)"], rows))
        w("")
        near_chance = abs(sh["cramers_v"]) < 0.1 and all(abs(k["kappa"]) < 0.1 for k in sh["binary"].values())
        if near_chance:
            w("**Interpretación:** el acuerdo es **indistinguible del azar** (κ ≈ 0 en todos los pares y V de Cramér baja). "
              "El desenlace histórico del dataset sintético no depende de los atributos que usa la política (estado del cliente, "
              "monto, fraud_score, reclamante recurrente), igual que otros campos del dataset son uniformes (ver "
              "`reports/EDA_findings.md`, limitación 9). Esto **no valida ni invalida** la política: dice que el histórico no "
              "sirve como etiqueta de \"decisión correcta\" y que cualquier afirmación de \"el agente coincide con los analistas\" "
              "sería falsa con estos datos.")
        else:
            w("**Interpretación:** hay pares con asociación distinta de cero; revisar los pares con p < 0,05 antes de "
              "interpretarlos (con varios pares, alguno puede salir significativo por azar).")
        w("")
        d = s["direct"]
        w("### Sensibilidad a la regla de emparejamiento")
        w("")
        tot = sum(d["alt_rules"].values())
        rows = [[k, num(d["rules"].get(k, 0)), num(d["alt_rules"].get(k, 0))] for k in sorted(set(d["rules"]) | set(d["alt_rules"]))]
        w(f"Decisión de la política con la regla principal vs con \"la más reciente de cualquier estado\" (misma transacción en "
          f"{num(d['alt_same_txn'])} de {num(tot)} casos):")
        w("")
        w(table(["Regla que decide", "Regla principal", "Alternativa"], rows))
        w("")
        w(f"H04 a la fecha de la queja vs con todas las quejas (semántica de producción): difieren en {num(d['h04_diff'])} "
          f"casos ({num(d['h04_prod_only'])} serían H04 solo por quejas **posteriores**).")
        w("")

    # ------------------------------------------------------------ 7 umbrales
    if s["sensitivity"]:
        w("## 7. Sensibilidad de umbrales H02 / H03 (solo política, sobre los cargos emparejados)")
        w("")
        w("Cuánto cambia la carga de analistas si se mueven los umbrales. `H02 ×` escala los montos altos por moneda de "
          "`config/policy.yaml`; `H03` es el `fraud_score` mínimo (hoy 30, ver `reports/fraud_threshold.md`).")
        w("")
        rows = [[f"{r['fraud_threshold']:.0f}", f"×{r['high_scale']:g}", pct(r["handoff"] / r["n"]), pct(r["auto"] / r["n"]),
                 num(r["n"])] for r in s["sensitivity"]]
        w(table(["H03 fraud_score ≥", "H02 monto", "Handoff", "Automatizable", "n"], rows))
        w("")

    # ------------------------------------------------------------ 8 proyección
    if "projection" in s:
        p = s["projection"]
        a = p["aht"]
        w("## 8. PROYECCIÓN de impacto (no medido; supuestos explícitos)")
        w("")
        w("> **PROYECCIÓN**, no resultado: combina la tasa simulada con volúmenes y duraciones del dataset sintético.")
        w("")
        w(f"- **Volumen:** {num(p['volume_365d'])} quejas de estas dos subcategorías en los últimos 365 días del dataset.")
        w(f"- **Tasa automatizable:** resolución automática segura de la simulación, {ci(p['share'])} (sobre el total, incluye sin match).")
        w(f"- **Tiempo de asesor por queja:** duración de las llamadas con `reason_category = Queja` (n={num(a['n'])}): p25 "
          f"{num(a['p25'])} s, p50 {num(a['p50'])} s, p75 {num(a['p75'])} s. {pct(a['followup'])} de esas llamadas requieren "
          "seguimiento; el escenario alto supone un contacto adicional de igual duración en esa proporción.")
        w("- **Supuestos:** una queja automatizada evita al menos un contacto de asesor; no se cuenta el trabajo de back-office "
          "(la disputa sigue requiriendo resolución), ni el costo del canal automático, ni efectos en satisfacción. Las quejas no "
          "se pueden unir a las llamadas (sin `origin_interaction_id`), así que \"un contacto por queja\" es un supuesto.")
        w("")
        w(table(["Escenario", "Supuesto", "Horas de asesor / año"],
                [["Bajo", "IC inferior de la tasa × p25 de duración × 1 contacto", num(p["hours_low"])],
                 ["Central", "tasa puntual × mediana × 1 contacto", num(p["hours_mid"])],
                 ["Alto", f"IC superior × p75 × (1 + {pct(a['followup'], 0)} seguimiento)", num(p["hours_high"])]]))
        w("")
        w(f"Rango proyectado: **{num(p['hours_low'])}–{num(p['hours_high'])} horas de asesor por año** para el volumen del dataset. "
          "No es un ahorro medido.")
        w("")

    # ------------------------------------------------------------ 9 limitaciones
    w("## 9. Limitaciones")
    w("")
    for t in [
        "**La transacción disputada es inferida.** No hay etiqueta; el agente se mide contra la regla de emparejamiento. Un "
        "cliente real podría estar reclamando otro cargo (o un cargo fuera de la ventana).",
        "**Cliente simulado cooperativo.** Siempre recuerda el monto/fecha exactos, reconoce su cargo entre las opciones y "
        "confirma. Los clientes reales se equivocan, cambian de tema o abandonan: la tasa real sería menor.",
        "**Mensajes generados por el equipo** con plantillas por dialecto; no hay texto real de clientes (las descripciones del "
        "dataset son plantillas y las transcripciones no dependen del motivo). La variante pt-BR es traducción del equipo.",
        "**Estado actual, no histórico:** `transaction_status` y `customer_status` son los de la última entrega. Un cargo hoy "
        "*Reversed* pudo estar *Approved* cuando se creó la queja (y quizás se reversó *por* la queja), y un cliente hoy "
        "inactivo (H01) pudo estar activo. El replay no puede reconstruir esos estados.",
        "**D05 no se ejerce:** con ventana de emparejamiento de "
        f"{WINDOW_DAYS} días, ningún cargo emparejado supera los 120 días del plazo. Evaluar a la fecha de la queja sí evita que "
        "las quejas de 2023–2025 se rechacen todas por antigüedad, que es lo que pasaría con el `as_of` fijo del YAML.",
        "**Datos sintéticos:** distribuciones uniformes e independencia entre campos (monto reclamado, producto afectado, "
        "desenlace). El modo sombra lo confirma; ninguna conclusión de acuerdo con el histórico es transferible a un banco real.",
        "**Latencia** medida en un solo proceso local con reglas y plantillas: no incluye red, LLM ni concurrencia.",
    ]:
        w(f"- {t}")
    w("")

    # ------------------------------------------------------------ 10 reproducibilidad
    w("## 10. Reproducibilidad")
    w("")
    fp = ", ".join(f"{k}=`{v}`" for k, v in meta["fingerprint"].items()) or "no encontrada (sin manifiesto del pipeline)"
    w(table(["", ""], [
        ["Comando", f"`{meta['command']}`"],
        ["Seed", meta["seed"]],
        ["Commit", f"`{meta['git_sha']}`" + (" (con cambios sin commit en src/ o config/)" if meta["git_dirty"] else "")],
        ["Política", f"`{meta['policy_version']}` (as_of del YAML {meta['policy_as_of_yaml']}; el replay usa la fecha de cada queja)"],
        ["Base", f"`{meta['db']}` · corrida del pipeline `{meta['manifest_run']}`"],
        ["Huella de la entrega", fp],
        ["Historial", f"`{meta['history_db']}` (tablas raw del EDA, solo lectura)" if meta["history_db"] else "no usado"],
        ["Parámetros", f"ventana {meta['window_days']} días, tolerancia de monto ±{meta['amount_tol']:.0%}, tope {meta['max_turns']} "
                       f"turnos, pt-BR {pct(meta['pt_share'], 0)}"],
        ["Duración de la corrida", f"{meta['elapsed_s']} s"],
    ]))
    w("")
    w("Los números de este reporte y `reports/replay_results.json` salen del mismo comando. El detalle por caso (con IDs del "
      "dataset) queda en `data/replay/cases.jsonl`, fuera del repositorio. Con el mismo seed, la misma base y el mismo commit, "
      "todo se reproduce salvo las latencias.")
    w("")
    return "\n".join(L)
