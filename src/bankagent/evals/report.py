"""Reporte Markdown de la evaluación (lo genera `python -m bankagent.evals.run`)."""
from __future__ import annotations

import math
from collections import Counter

from . import metrics as M

FIELDS = [("language", "Idioma"), ("dialect", "Dialecto"), ("country", "País del cliente"), ("segment", "Segmento")]


def _p(x, digits: int = 1) -> str:
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.{digits}f}%"


def _frac(k: int, n: int) -> str:
    return f"{k}/{n} ({_p(k / n) if n else '—'})"


def _ms(x) -> str:
    return "—" if x is None else f"{x:,.0f} ms"


def _usd(x, measured: bool, zero_note: str = "") -> str:
    if not measured:
        return "no medido"
    if x is None:
        return "no definido (0 resoluciones)"
    return f"US$ {x:.4f}{zero_note}"


def _vr(v: dict, n: int) -> str:
    """Valor entre corridas: media y rango."""
    if v["min"] == v["max"]:
        return f"{v['min']}/{n} en todas las corridas"
    return f"media {v['mean']:.1f}/{n} (rango {v['min']}–{v['max']}, σ={v['stdev']:.2f})"


def _interp(turn: dict) -> str:
    u = turn.get("understanding") or {}
    if not u:
        return f"(sin router: {turn.get('outcome')})"
    slots = ", ".join(f"{k}={v}" for k, v in (u.get("slots") or {}).items())
    return f"{u.get('intent')}@{u.get('confidence')}" + (f" ({slots})" if slots else "")


def render(ctx: dict) -> str:
    """ctx: meta, cases (test main), fair_cases, systems: {name: {describe, runs: [[scores]], results_run1, fair_runs}}"""
    meta, cases, out = ctx["meta"], ctx["cases"], []
    w = out.append
    names = list(ctx["systems"])
    w("# Evaluación offline: línea base contra agente")
    w("")
    w(f"> Generado por `{meta['command']}` · commit `{meta['git_sha']}` · {meta['generated_at']}. "
      "No editar a mano: volver a correr el comando.")
    w("")
    w("> **Qué es esto:** una medición OFFLINE sobre casos generados por el equipo con un cliente SIMULADO por "
      "guion, contra datos sintéticos del organizador. No es tráfico real ni una prueba con usuarios.")
    w("")

    # ------------------------------------------------------------ resumen
    w("## 1. Resumen")
    w("")
    w(f"Conjunto **test** reservado: **{len(cases)} casos** (principal) + **{len(ctx['fair_cases'])}** variantes de "
      f"equidad ({len({c['fairness_group'] for c in ctx['fair_cases']})} grupos × 4 dialectos). "
      f"{meta['repeats']} corrida(s) por sistema. Valores de la corrida 1; la variabilidad está en la sección 5.")
    w("")
    w("| Métrica (test, n={}) | ".format(len(cases)) + " | ".join(f"`{s}`" for s in names) + " |")
    w("|---|" + "---|" * len(names))
    aggs = {s: M.aggregate(ctx["systems"][s]["runs"][0]) for s in names}
    rows = [
        ("Resolución automática segura / casos en alcance", lambda a: _frac(a["sar"], a["in_scope"])),
        ("Resolución automática segura / intentos de automatización", lambda a: _frac(a["sar"], a["attempted"])),
        ("Resultado correcto (todos los casos)", lambda a: _frac(a["correct"], a["n"])),
        ("Contención (sin transferencia)", lambda a: _frac(a["contained"], a["n"])),
        ("… de la cual con resultado incorrecto", lambda a: _frac(a["contained_incorrect"], a["contained"])),
        ("Transferencias correctas / debían transferirse", lambda a: _frac(a["correct_transfers"], a["should_escalate"])),
        ("Transferencias útiles (paquete completo) / correctas", lambda a: _frac(a["useful_transfers"], a["correct_transfers"])),
        ("Transferencias faltantes", lambda a: _frac(a["missed_transfers"], a["should_escalate"])),
        ("Transferencias innecesarias", lambda a: _frac(a["unnecessary_transfers"], a["not_should_escalate"])),
        ("Casos con resultado inseguro (cota sup. 95%)", lambda a: f"{_frac(a['unsafe_any'], a['n'])} (≤ {_p(a['unsafe_upper95'])})"),
        ("Casos con alguna respuesta en otro idioma", lambda a: _frac(a["wrong_language_cases"], a["n"])),
        ("Latencia por caso p50 / p95", lambda a: f"{_ms(a['latency_case_p50'])} / {_ms(a['latency_case_p95'])}"),
        ("Costo por caso procesado", lambda a: _usd(a["cost_per_case_usd"], a["cost_measured"])),
        ("Costo por resolución automática segura", lambda a: _usd(a["cost_per_sar_usd"], a["cost_measured"])),
    ]
    for label, fn in rows:
        w(f"| {label} | " + " | ".join(fn(aggs[s]) for s in names) + " |")
    fair = {s: M.fairness(ctx["fair_cases"], ctx["systems"][s]["fair_runs"][0]) for s in names}
    w("| Acuerdo de decisión entre dialectos (grupos) | " + " | ".join(
        _frac(fair[s]["agree"], fair[s]["groups"]) for s in names) + " |")
    w("")
    w("| Sistema | Qué es |")
    w("|---|---|")
    for s in names:
        w(f"| `{s}` | {ctx['systems'][s]['describe'].get('description', '—')} |")
    w("")
    if {"b0", "b1"} & set(names):
        w("> B0 y B1 son líneas base ingenuas **para dar escala**, no alternativas propuestas: B0 muestra el piso de "
          "contención (todo a humano, seguro); B1 muestra qué resultados inseguros aparecen sin política ni confirmación. "
          "El LLM está apagado (sin API paga); el router por embeddings (#42) y el LLM se agregan con `--system embeddings` / "
          "`--system llm` sobre este mismo test congelado.")
        w("")

    # ------------------------------------------------------------ carga
    w("## 2. Carga de trabajo y calidad de etiquetas")
    w("")
    man = meta["manifest"]
    w(f"- **Origen:** {man['provenance']}")
    w(f"- **Construcción:** generador determinista `bankagent.evals.cases` (semilla {man['seed']}), clientes y "
      f"transacciones reales de `serving.duckdb` (as_of {man['as_of']}), mensajes con plantillas escritas a mano por "
      "dialecto (es-MX, es-CO, es-AR con voseo, pt-BR), montos en formato local, fechas relativas y errores de tipeo.")
    w("- **Etiquetas:** derivadas de la especificación `config/policy.yaml` aplicada a los atributos crudos de la "
      "transacción/cliente elegidos. Verificación cruzada con el motor de política: "
      f"{man['policy_cross_check']['checked']} candidatos revisados, {man['policy_cross_check']['discarded']} descartados "
      "por discrepancia. Cada mensaje identifica a su transacción (monto ±10% dentro de la ventana de fecha que afirma).")
    w("- **Limitaciones de las etiquetas:** un solo proceso de etiquetado (sin segundo anotador ni acuerdo "
      "inter-anotador); el cliente simulado responde siempre igual; el portugués lo escribió un equipo "
      "hispanohablante; los datos son sintéticos (no hay clientes brasileños: los casos pt-BR usan clientes de MX/CO/AR).")
    w(f"- **División:** dev/test por `customer_id` (hash; {man['dev_share_pct']}% dev); ningún cliente en ambas. "
      "Además, **la redacción también está dividida**: dev usa las plantillas v1 y test las v2, escritas después de "
      "ajustar la línea base con dev. Solo se reporta **test**. "
      f"**Test congelado:** `evals/cases/test.jsonl` sha256 `{meta.get('cases_sha256', man['sha256']['test.jsonl'])[:16]}…`"
      f"{'' if meta.get('cases_sha_ok', True) else ' (⚠ NO coincide con el manifiesto)'}; el generador se niega a "
      "reescribirlo, así las mejoras posteriores del router se miden sin fuga.")
    w("")
    cat = Counter(c["category"] for c in cases)
    w("| Categoría | n | Resultado esperado |")
    w("|---|---|---|")
    exp_by_cat: dict[str, Counter] = {}
    for c in cases:
        exp_by_cat.setdefault(c["category"], Counter())[c["labels"]["expected_outcome"]] += 1
    for k, v in sorted(cat.items(), key=lambda kv: -kv[1]):
        w(f"| {k} | {v} | {', '.join(f'{o} ({n})' for o, n in exp_by_cat[k].most_common())} |")
    w("")
    for field, label in FIELDS:
        cnt = Counter(str(c[field]) for c in cases)
        w(f"- **{label}:** " + ", ".join(f"{k} {v}" for k, v in sorted(cnt.items())))
    ins = sum(c["labels"]["in_scope"] for c in cases)
    esc = sum(c["labels"]["should_escalate"] for c in cases)
    w(f"- **En alcance** (pueden terminar sin humano): {ins} · **deben transferirse:** {esc} · "
      f"**turnos de usuario por caso (guion):** {sum(len(c['turns']) for c in cases) / len(cases):.1f} en promedio")
    w("")

    # ------------------------------------------------------------ sistema
    w("## 3. Sistemas y versiones")
    w("")
    w("| Campo | " + " | ".join(f"`{s}`" for s in names) + " |")
    w("|---|" + "---|" * len(names))
    keys = sorted({k for s in names for k in ctx["systems"][s]["describe"]})
    for k in keys:
        w(f"| {k} | " + " | ".join(str(ctx["systems"][s]["describe"].get(k, "—")) for s in names) + " |")
    w(f"| política | " + " | ".join(meta["policy_version"] for _ in names) + " |")
    w("")
    w(f"Commit `{meta['git_sha']}`{' (con cambios locales sin commitear)' if meta.get('dirty') else ''} · "
      f"Python {meta['python']} · langgraph {meta['langgraph']} · base `{meta['db_name']}` · {meta['repeats']} corrida(s).")
    w("")

    # ------------------------------------------------------------ métricas
    for s in names:
        a = aggs[s]
        w(f"## 4. Métricas detalladas · `{s}`")
        w("")
        w("### Resolución automática segura")
        w(f"- Sobre todos los casos en alcance: **{_frac(a['sar'], a['in_scope'])}**.")
        w(f"- Sobre los casos en alcance donde se intentó automatizar (no se transfirieron): **{_frac(a['sar'], a['attempted'])}**.")
        w("- Definición: el caso termina en el resultado que dicta la política (outcome, regla y acciones idénticos a "
          "la etiqueta), sin humano y sin ningún indicador inseguro.")
        w("")
        w("### Contención")
        w(f"- Terminan sin transferencia: **{_frac(a['contained'], a['n'])}**; de esos, correctos {a['contained_correct']} "
          f"e incorrectos {a['contained_incorrect']}. La contención sola no prueba que el caso se haya resuelto.")
        w("")
        w("### Calidad del escalamiento")
        w(f"- Correctas: {_frac(a['correct_transfers'], a['should_escalate'])} de los casos que debían transferirse; útiles "
          f"(motivo correcto, mensajes del cliente, pendientes y, en reglas H, la transacción verificada y la regla): "
          f"{_frac(a['useful_transfers'], a['correct_transfers'])}.")
        w(f"- Faltantes: **{_frac(a['missed_transfers'], a['should_escalate'])}** · innecesarias: "
          f"**{_frac(a['unnecessary_transfers'], a['not_should_escalate'])}** (sobre casos que no debían transferirse).")
        w("")
        w("### Resultados inseguros")
        w("| Tipo | Casos | Cota sup. 95% |")
        w("|---|---|---|")
        for k, desc in M.UNSAFE_TYPES.items():
            v = a["unsafe_by_type"][k]
            w(f"| {desc} | {_frac(v, a['n'])} | ≤ {_p(M.upper_bound(v, a['n']))} |")
        w(f"| **Cualquiera** | **{_frac(a['unsafe_any'], a['n'])}** | ≤ {_p(a['unsafe_upper95'])} |")
        w("")
        adv = [c["id"] for c in cases if c["category"] == "adversarial_access"]
        leak_adv = sum(1 for sc in ctx["systems"][s]["runs"][0] if sc["case_id"] in adv and "divulgacion" in sc["unsafe"])
        w(f"- Divulgación en casos adversariales (piden datos de otro cliente): {_frac(leak_adv, len(adv))}.")
        w("- Cero observado no es riesgo cero: con n casos, la cota superior al 95% es ≈ 3/n (regla de tres). "
          "Las verificaciones son deterministas: acciones leídas del almacén ops, tarjetas `****NNNN` e IDs de cliente "
          "ajenos en la respuesta, marcadores de la víctima en respuesta y paquete.")
        w("")
        w("### Eficiencia operativa (medición offline, máquina local)")
        w(f"- Latencia de punta a punta por caso (suma de turnos del agente, sin tiempo del cliente): p50 "
          f"{_ms(a['latency_case_p50'])} · p95 {_ms(a['latency_case_p95'])}. Por turno: p50 {_ms(a['latency_turn_p50'])} "
          f"· p95 {_ms(a['latency_turn_p95'])}.")
        zero = " (sin llamadas a modelos)" if a["cost_measured"] and not ctx["systems"][s]["describe"].get("uses_model") else ""
        w(f"- Costo total {_usd(a['cost_total_usd'], a['cost_measured'], zero)} · por caso procesado "
          f"{_usd(a['cost_per_case_usd'], a['cost_measured'])} · por resolución automática segura "
          f"{_usd(a['cost_per_sar_usd'], a['cost_measured'])}. Solo cómputo de inferencia; no incluye infraestructura.")
        w("")

    # ------------------------------------------------------------ variabilidad
    w("## 5. Variabilidad entre corridas")
    w("")
    for s in names:
        runs = ctx["systems"][s]["runs"]
        v = M.variability(runs)
        n = len(cases)
        w(f"**`{s}`** · {len(runs)} corrida(s) completas del conjunto test:")
        w("")
        w(f"- Correctos: {_vr(v['correct'], n)} · resolución automática segura: {_vr(v['sar'], aggs[s]['in_scope'])} · "
          f"contención: {_vr(v['contained'], n)} · transferencias: {_vr(v['escalated'], n)} · inseguros: {_vr(v['unsafe_any'], n)}.")
        uns = v["unstable_cases"]
        w(f"- Casos cuya decisión (resultado, regla, acciones) cambió entre corridas: **{len(uns)}**"
          + (f": {', '.join(uns[:20])}" if uns else "") + ".")
        lat = [M.aggregate(r)["latency_case_p95"] for r in runs]
        w(f"- p95 de latencia por caso en cada corrida: {', '.join(_ms(x) for x in lat)}.")
        w("")

    # ------------------------------------------------------------ desgloses
    w("## 6. Resultados por idioma, dialecto, país y segmento")
    w("")
    w(f"⚠ = n < {M.SMALL_N}: muestra pequeña, los intervalos son anchos y las diferencias pueden ser ruido. "
      "El segmento lo autoriza el propio dataset (Basic/Plus/Premium/Student); no se usan atributos sensibles.")
    w("")
    for s in names:
        sc = ctx["systems"][s]["runs"][0]
        for field, label in FIELDS:
            w(f"**{label}** · `{s}`")
            w("")
            w("| Grupo | n | Correctos (IC 95%) | RAS / en alcance | Contención | Transf. faltantes | Transf. innecesarias | Inseguros | Respuesta en otro idioma |")
            w("|---|---|---|---|---|---|---|---|---|")
            for r in M.breakdown(cases, sc, field):
                lo, hi = r["correct_ci"]
                w(f"| {r['group']}{' ⚠' if r['small_n'] else ''} | {r['n']} | {_p(r['correct_rate'])} ({_p(lo, 0)}–{_p(hi, 0)}) | "
                  f"{_frac(r['sar'], r['in_scope'])} | {_frac(r['contained'], r['n'])} | {r['missed_transfers']}/{r['should_escalate']} | "
                  f"{r['unnecessary_transfers']}/{r['not_should_escalate']} | {r['unsafe_any']} | {r['wrong_language_cases']} |")
            w("")
        w(f"**Disparidades (brecha ≥ 10 pp en correctos) · `{s}`**")
        w("")
        any_d = False
        for field, label in FIELDS:
            d = M.disparities(cases, sc, field)
            if d:
                any_d = True
                cats = ", ".join(f"{k} ({v})" for k, v in d["worst_fail_categories"])
                w(f"- {label}: `{d['worst']}` {_p(d['worst_rate'])} contra `{d['best']}` {_p(d['best_rate'])} "
                  f"(brecha {_p(d['gap'])}). Fallas del grupo más bajo por categoría: {cats}.")
        if not any_d:
            w("- Ninguna brecha ≥ 10 pp.")
        w("- Cómo leerlas: el segmento y el país **no son entradas** del router ni de la política (la política usa "
          "estado del cliente, monto, fraude, antigüedad y reclamos previos). Una brecha por segmento o país refleja la "
          "mezcla de categorías y el n pequeño. Las brechas por **dialecto/idioma** sí pueden venir del router "
          "(palabras clave y formatos); la prueba controlada está en la sección 7.")
        w("")

    # ------------------------------------------------------------ equidad
    w("## 7. Equidad por dialecto (issue #13)")
    w("")
    w("El mismo cliente y la misma transacción, redactados en es-MX, es-CO, es-AR (voseo) y pt-BR, sin ruido de tipeo. "
      "Se espera la misma decisión: resultado, regla y acciones. Solo cambia la redacción.")
    w("")
    for s in names:
        f = fair[s]
        w(f"**`{s}`**: acuerdo en **{_frac(f['agree'], f['groups'])}** grupos (n pequeño ⚠).")
        w("")
        w("| Dialecto | Variantes con decisión correcta |")
        w("|---|---|")
        for d, (k, n) in f["per_dialect"].items():
            w(f"| {d} | {_frac(k, n)} |")
        w("")
        dis = [r for r in f["rows"] if not r["agree"]]
        if dis:
            w("Grupos con desacuerdo:")
            w("")
            w("| Grupo | Tipo | " + " | ".join(sorted(dis[0]["decisions"])) + " |")
            w("|---|---|" + "---|" * len(dis[0]["decisions"]))
            for r in dis:
                w(f"| {r['group']} | {r['kind']} | " + " | ".join(
                    f"{'✔' if r['correct'][d] else '✘'} `{r['decisions'][d].split('|')[0]}`" for d in sorted(r["decisions"])) + " |")
            w("")
        fc = {c["id"]: c for c in ctx["fair_cases"]}
        bad = [(fc[sc["case_id"]], sc) for sc in ctx["systems"][s]["fair_runs"][0] if not sc["correct"]]
        if bad:
            w("Variantes falladas (mensaje → motivo):")
            w("")
            for c, sc in bad[:25]:
                w(f"- `{c['id']}` {c['fairness_group']} {c['dialect']}: “{c['turns'][0]['text']}” → {'; '.join(sc['reasons'])}")
            w("")

    # ------------------------------------------------------------ confusión
    w("## 8. Matriz de confusión: resultado esperado × obtenido (corrida 1)")
    w("")
    for s in names:
        res = ctx["systems"][s]["results_run1"]
        conf = M.confusion(cases, list(zip(ctx["systems"][s]["runs"][0], res)))
        cols = sorted({o for row in conf.values() for o in row})
        w(f"**`{s}`**")
        w("")
        w("| esperado \\ obtenido | " + " | ".join(cols) + " | total |")
        w("|---|" + "---|" * (len(cols) + 1))
        for e in sorted(conf):
            w(f"| **{e}** | " + " | ".join(str(conf[e].get(o, 0) or "·") for o in cols) + f" | {sum(conf[e].values())} |")
        w("")

    # ------------------------------------------------------------ fallas
    w("## 9. Fallas (corrida 1)")
    w("")
    for s in names:
        sc = ctx["systems"][s]["runs"][0]
        res = {r["case_id"]: r for r in ctx["systems"][s]["results_run1"]}
        byid = {c["id"]: c for c in cases}
        fails = [x for x in sc if not x["correct"]]
        cap = 40
        w(f"**`{s}`: {len(fails)} de {len(sc)} casos fallan.** Por categoría: " + ", ".join(
            f"{k} {v}/{cat[k]}" for k, v in Counter(byid[x['case_id']]["category"] for x in fails).most_common()) + ".")
        w("")
        w("| Caso | Categoría | Dialecto | Primer mensaje | Router en el turno 1 | Último turno del cliente → router | Motivo |")
        w("|---|---|---|---|---|---|---|")
        for x in fails[:cap]:
            c, r = byid[x["case_id"]], res[x["case_id"]]
            msg = c["turns"][0]["text"].replace("|", "/")
            last = r["turns"][-1] if len(r["turns"]) > 1 else None
            tail = f"“{last['text']}” → {_interp(last)}" if last else "—"
            w(f"| {c['id']} | {c['category']} | {c['dialect']} | {msg} | {_interp(r['turns'][0]) if r['turns'] else '—'} | "
              f"{tail} | {'; '.join(x['reasons'])} |")
        if len(fails) > cap:
            w(f"| … | {len(fails) - cap} fallas más en `data/evals/results.json` | | | | | |")
        w("")

    # ------------------------------------------------------------ humano
    w("## 10. Referencia: operación humana histórica")
    w("")
    h = ctx.get("human")
    if not h:
        w("No disponible en esta corrida (se necesita `data/bank.duckdb` con las tablas raw del organizador).")
    else:
        w("> Operación humana histórica según los **datos sintéticos del organizador**. **No es comparable 1:1**: "
          "son llamadas de todo tipo de queja (no solo cargos no reconocidos), con otra mezcla de casos, otro canal y "
          "otras definiciones de 'resuelto'. Se muestra como contexto, no como línea base del experimento.")
        w("")
        w(f"- Contactos con `reason_category = 'Queja'`: **{h['n']:,}** ({h['from']} a {h['to']}).")
        w(f"- Resolución en el primer contacto (`was_resolved`): **{_p(h['fcr'])}** · escalados: **{_p(h['escalated'])}** · "
          f"requieren seguimiento: {_p(h['followup'])}.")
        w(f"- Duración mediana {h['dur_p50']:.0f} s (p95 {h['dur_p95']:.0f} s) · espera mediana {h['wait_p50']:.0f} s.")
        if h.get("pqr_n"):
            w(f"- PQR 'Cargo no reconocido': {h['pqr_n']:,} casos · SLA incumplido {_p(h['pqr_sla'])} · "
              f"mediana de resolución {h['pqr_days']:.0f} días (entre los que tienen resolución registrada, {_p(h['pqr_resolved'])}).")
        w(f"- Por acento detectado (FCR): " + ", ".join(f"{k} {_p(v)} (n={n:,})" for k, v, n in h["by_accent"]) + ".")
    w("")

    # ------------------------------------------------------------ clasificación de la evidencia
    w("## 11. Qué es medición, qué es simulación y qué es proyección")
    w("")
    w("| Tipo | Qué incluye |")
    w("|---|---|")
    w("| Medición offline | Resultados, reglas, acciones escritas en ops, latencias y costo del agente sobre el conjunto test |")
    w("| Simulación | El cliente (respuestas de guion a '¿cuál?' y '¿confirmas?'), las fallas de herramientas inyectadas, "
      "la expiración de sesión forzada, las sesiones del IdP simulado |")
    w("| Proyección | **No se incluye.** No se proyectan ahorros ni volúmenes: los datos son sintéticos y el cliente es simulado |")
    w("")
    w("## 12. Limitaciones")
    w("")
    w(f"- n de test = {len(cases)}; por dialecto ≈ {len(cases) // 4} y por segmento aún menos: los desgloses son "
      "indicativos. Las brechas pequeñas no son concluyentes.")
    w("- Las etiquetas las generó el mismo equipo que construyó el sistema (riesgo de sesgo de diseño). Para no "
      "contaminar test, el RuleRouter se ajustó solo con dev y **test usa una redacción distinta (plantillas v2) escrita "
      "después del ajuste**; aun así, el mismo equipo escribió ambas y comparten estilo.")
    w("- El cliente simulado es cooperativo y consistente; usuarios reales cambian de tema, se enojan o dan datos erróneos.")
    w("- Latencias medidas en una laptop con DuckDB local; no representan producción. Costo de la línea base = 0 por "
      "construcción (no llama a modelos).")
    w("")
    return "\n".join(out) + "\n"
