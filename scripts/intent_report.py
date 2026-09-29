"""Genera reports/intent_router.md a partir de los resultados de train_intent.py (no editar el .md a mano)."""
from __future__ import annotations

from collections import Counter

import numpy as np

from bankagent.intent_model import LABELS, ROUTE, ROUTES

ROUTE_ES = {"dispute": "disputa", "block": "bloqueo", "status": "estado", "handoff": "handoff", "close": "cierre",
            "clarify": "aclarar"}
SPLIT_ES = {"test": "test (autores C y G)", "test_style": "test de estilo no visto (autor D)"}
SYS_ES = {"rules": "RuleRouter (línea base)", "lite": "Aprendido lite (char) — se despliega",
          "full": "Aprendido full (char+MiniLM) — offline"}


def pct(x: float, d: int = 1) -> str:
    return f"{100 * x:.{d}f}%"


def table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def confusion_md(m: list[list[int]], labels) -> str:
    short = [lab.replace("_", " ") for lab in labels]
    return table(["verdad \\ predicción"] + short, [[short[i]] + row for i, row in enumerate(m)])


def ci(R: dict, key: str, as_pct: bool = False) -> str:
    if key not in R["ci95"]:
        return ""
    lo, hi = R["ci95"][key]
    return f"[{pct(lo)}, {pct(hi)}]" if as_pct else f"[{lo:.3f}, {hi:.3f}]"


def seeds_md(seeds: list[dict], key: str) -> str:
    v = np.array([s[key] for s in seeds])
    return f"{v.mean():.3f} ± {v.std(ddof=1):.3f}"


def write_report(res: dict, data: dict, tests: dict) -> str:
    metas, sel, lat = res["meta"], res["selection"], res["latency"]
    systems = [n for n in ("lite", "full") if n in metas]
    names = ["rules"] + systems
    L: list[str] = []
    w = L.append
    w("# Router de intención aprendido vs. RuleRouter\n")
    w("> Generado por `scripts/train_intent.py` — no editar a mano. Decisión y justificación: "
      "[ADR 0009](../docs/adr/0009-router-aprendido.md). Corpus, guía y anotaciones: [`corpus/intent/`](../corpus/intent/).\n")
    for n in systems:
        m = metas[n]
        w(f"- **{SYS_ES[n]}:** `{m['model_id']}` + regresión logística (C={m['C']}, clases balanceadas), temperatura "
          f"T={m['T']:.2f}, umbral de abstención τ={m['tau']:.2f} ({m['threshold_rule']}). Artefactos "
          f"`models/intent_router_{n}/` ({m['artifact_mb']} MB).")
    w(f"- Corpus de train sha256 `{metas[systems[0]]['corpus_sha256'][:16]}…`; test congelado en "
      f"`corpus/intent/MANIFEST.json` ({res['manifest'].get('frozen_at', '—')}).\n")

    w("## Resumen\n")
    rows = []
    for split, R in res["splits"].items():
        S = R["systems"]
        rows.append([f"**{SPLIT_ES[split]}**", f"n={R['n']} ({R['families']} familias)"] + [""] * len(names))
        rows.append(["", "macro-F1, 9 intenciones (IC 95%)"] + [f"{S[n]['macro_f1']:.3f} {ci(R, n + '.macro_f1')}" for n in names])
        rows.append(["", "Δ macro-F1 vs. reglas (IC 95%)", "—"]
                    + [f"{S[n]['macro_f1'] - S['rules']['macro_f1']:+.3f} {ci(R, f'diff_{n}.macro_f1')}" for n in systems])
        rows.append(["", "macro-F1 por ruta del grafo"] + [f"{S[n]['route_macro_f1']:.3f}" for n in names])
        rows.append(["", "mensajes con acción equivocada"]
                    + [f"{pct(S[n]['wrong_action_rate'])} ({S[n]['wrong_action']})" for n in names])
        rows.append(["", "handoff pedido → se inició disputa"] + [S[n]["handoff_to_dispute"] for n in names])
        rows.append(["", "costo esperado por mensaje (IC 95%)"]
                    + [f"{S[n]['cost_per_msg']:.3f} {ci(R, n + '.cost_per_msg')}" for n in names])
        rows.append(["", "cobertura (sin aclarar por baja confianza)"] + [pct(S[n]["coverage"]) for n in names])
        rows.append(["", "5 semillas (85% de familias): macro-F1", "—"] + [seeds_md(R["seeds"][n], "macro_f1") for n in systems])
    cand = {n: metas[n]["candidate"] for n in systems}
    rows.append(["**CPU, 1 hilo**", "latencia de clasificación p50 / p95 (HybridRouter = esto + reglas)"]
                + [f"{lat['rules']['p50_ms']:.2f} / {lat['rules']['p95_ms']:.2f} ms"]
                + [f"{lat[cand[n]]['p50_ms']:.2f} / {lat[cand[n]]['p95_ms']:.2f} ms" for n in systems])
    rows.append(["", "en disco"] + ["0 MB"] + [f"{metas[n]['artifact_mb']} MB + {lat[cand[n]]['model_mb']} MB preentrenado"
                                               for n in systems])
    w(table(["split", "métrica"] + [SYS_ES[n] for n in names], rows))
    w("\n- Las 9 etiquetas son las intenciones de usuario que el grafo ya maneja (#54); RuleRouter las cubre todas, así "
      "que la comparación es directa. RuleRouter se evalúa como lo usa el grafo: confianza < 0.6 → aclarar (`unknown`).")
    w("- **Acción equivocada** = el grafo propone una disputa o un bloqueo cuando la ruta correcta era otra (todas las "
      "acciones piden confirmación, así que es el error más caro que el router puede provocar).")
    w("- **Costo** (`intent_model.error_cost`): aclarar 0.5 · handoff innecesario 1 · handoff a la cola equivocada 0.5 "
      "(1 si era toma de cuenta) · consultar estado sin pedirlo 1 · cerrar con un pedido abierto 1.5 · proponer "
      "disputa/bloqueo indebido 2, o 3 si el cliente pedía un humano, reportaba robo de cuenta o retiraba un reclamo.")
    w("- IC 95% por bootstrap de **familias** de paráfrasis (2000 réplicas): las paráfrasis de una misma idea no son "
      "independientes.\n")

    w("## Datos y etiquetas\n")
    splits = (("train", data["train"]), *tests.items())
    cnt = {s: Counter(r["intent"] for r in rows_) for s, rows_ in splits}
    w(table(["intención"] + [f"{s} (n={sum(c.values())})" for s, c in cnt.items()],
            [[lab] + [cnt[s][lab] for s in cnt] for lab in LABELS]))
    dcnt = {s: Counter(r["dialect"] for r in rows_) for s, rows_ in splits}
    w("\n" + table(["dialecto"] + list(dcnt), [[d] + [dcnt[s][d] for s in dcnt] for d in ("es-MX", "es-CO", "es-AR", "pt-BR", "mix")]))
    w("\n- **Procedencia:** enunciados escritos por el equipo con asistentes de IA, un autor por sesión aislada que "
      "solo leyó la [guía de etiquetado](../corpus/intent/GUIA_ETIQUETADO.md) (ni las reglas ni otros archivos del "
      "corpus). Split **por autor, fijado antes de escribir**: A, B, E, F → train; C, G → test; D → test de estilo no "
      "visto (voz a texto, telegráfico, formal). F y G se sumaron en la v2 de la guía para las intenciones nuevas de "
      "#54 (`dispute_status`, `cancel_dispute`); los archivos anteriores no se tocaron y una revisión completa no "
      "encontró enunciados viejos que cambiaran de etiqueta (`review/schema_v2_relabel.jsonl` vacío). "
      "No hay texto de clientes ni del dataset del organizador (ADR 0003).")
    ag = res.get("agreement") or {}
    if ag:
        w("- **Validez de etiquetas:** anotaciones ciegas (solo el texto + la guía) comparadas con la etiqueta del "
          "autor antes de adjudicar; los desacuerdos se resolvieron en `review/adjudication.jsonl` (o se descartaron "
          "por ambiguos). El acuerdo es muy alto: el corpus es *limpio* (ver Limitaciones).")
        w("\n" + table(["split · anotador", "n", "acuerdo", "κ de Cohen", "desacuerdos", "reetiquetados", "descartados"],
                       [[s, a["n"], pct(a["agreement"]), f"{a['kappa']:.3f}", a["disagreements"], a["relabeled"],
                         a["dropped"]] for s, a in ag.items()]) + "\n")
    lk = res["leak_excluded"]
    w(f"- **Fuga:** familias de paráfrasis y autores nunca cruzan splits; el vocabulario de n-gramas y la temperatura "
      f"se ajustan dentro de cada fold; el test no participa de ninguna selección; casi-duplicados de train "
      f"(Jaccard de trigramas ≥ 0.8, en general saludos o cierres cortos) se sacan del test: {len(lk['test'])} en "
      f"test, {len(lk['test_style'])} en estilo. El script aborta si los hashes congelados del test cambian.\n")

    w("## Selección del componente (solo validación cruzada por autor sobre train)\n")
    w("Cada fold entrena con todos los autores de train menos uno y valida con el que quedó afuera (un autor que el "
      "modelo nunca vio, como en el test). Encoder, C, temperatura y umbral salen de acá; el test se evalúa una sola "
      "vez al final. Latencia: un mensaje a la vez tras calentar, 1 hilo.\n")
    rows = []
    for c, s in sel.items():
        la = lat[c]
        tag = " ← full" if c == res["chosen"] else ""
        tag += " ← lite" if c == "char" else ""
        rows.append([f"`{c}`{tag}", f"{s['macro_f1']:.3f}", s["C"], f"{s['T']:.2f}",
                     f"{s['ece_raw']:.3f} → {s['ece_cal']:.3f}", f"{s['tau']:.2f}", pct(s["at_tau"]["coverage"]),
                     pct(s["at_tau"]["wrong_action_rate"]), f"{s['at_tau']['cost_per_msg']:.3f}",
                     f"{la['p50_ms']:.2f} / {la['p95_ms']:.2f}", la["model_mb"]])
    dr = res["dev_rules"]
    rows.append(["RuleRouter", "—", "", "", "", "", "", pct(dr["wrong_action_rate"]), f"{dr['cost_per_msg']:.3f}",
                 f"{lat['rules']['p50_ms']:.2f} / {lat['rules']['p95_ms']:.2f}", 0])
    w(table(["candidato", "macro-F1", "C", "T", "ECE cruda → calibrada", "τ", "cobertura", "acción equivocada",
             "costo/msg", "p50 / p95 ms", "MB preentrenado"], rows))
    w("\n`char` = TF-IDF de n-gramas de caracteres 2–5 aprendido del corpus; `m2v` = model2vec "
      "potion-multilingual-128M; `minilm` = paraphrase-multilingual-MiniLM-L12-v2 (ONNX int8); `e5` = "
      "multilingual-e5-small (ONNX int8). Regla fijada antes de mirar el test: **full** = mayor macro-F1 en validación "
      "(si otro queda a menos de 0.01, el más liviano). **lite** = `char`, el único que entra en el deploy gratuito "
      "(512 MB de RAM, 0.1 CPU) sin onnxruntime ni un modelo de 250 MB. Umbral τ: máxima cobertura con acción "
      "equivocada ≤ 1% en validación.\n")
    w("![Cobertura vs acción equivocada](figures/intent_coverage.png)\n")

    for split, R in res["splits"].items():
        S = R["systems"]
        w(f"## Resultados — {SPLIT_ES[split]}\n")
        w(table(["", *[SYS_ES[n] for n in systems]],
                [["ECE (10 bins)", *[f"{S[n]['ece']:.3f}" for n in systems]],
                 ["macro-F1 sin abstención", *[f"{S[n]['macro_f1_no_abstention']:.3f}" for n in systems]],
                 ["acción equivocada sin abstención", *[pct(S[n]['route_no_abstention']['wrong_action_rate']) for n in systems]]]))
        w("\n### Por intención (precisión / recall / F1)\n")
        w(table(["intención", "soporte", *[f"{n} P/R/F1" for n in names]],
                [[lab, S["rules"]["per_label"][lab]["support"],
                  *(" / ".join(f"{S[n]['per_label'][lab][k]:.2f}" for k in ("precision", "recall", "f1")) for n in names)]
                 for lab in LABELS]))
        w("\n### Confusión por ruta del grafo\n")
        for n in names:
            w(f"{SYS_ES[n]}:\n\n" + confusion_md(R["route_confusion"][n], [ROUTE_ES[r] for r in ROUTES]) + "\n")
        w("<details><summary>Matriz de confusión de 9 intenciones (lite)</summary>\n\n"
          + confusion_md(S[systems[0]]["confusion"], LABELS) + "\n\n</details>\n")
        w("### Exactitud por autor, dialecto, estilo y negativos difíciles\n")
        rows = []
        for key, lab in (("author", "autor"), ("dialect", "dialecto"), ("style", "estilo"), ("hard_negative", "negativo difícil")):
            for g, v in R["by"][key].items():
                if v["n"] >= 5:
                    rows.append([lab, g, v["n"], *(pct(v[n]) for n in names)])
        w(table(["corte", "grupo", "n", *names], rows))
        w("\n### Errores\n")
        errs = R["errors"]
        for n in systems:
            mine = [e for e in errs if e[n] != e["true"]]
            pairs = Counter(f"{e['true']} → {e[n]}" for e in mine)
            both = sum(1 for e in mine if e["rules"] != e["true"])
            w(f"**{n}**: {len(mine)} errores ({both} también de reglas). Pares más frecuentes: "
              + ", ".join(f"{k} ({v})" for k, v in pairs.most_common(6)) + ".\n")
        n0 = systems[0]
        worst = sorted([e for e in errs if e[n0] != e["true"]], key=lambda e: -e[f"p_{n0}"])[:12]
        w(f"Errores más confiados de **{n0}** (los más peligrosos: la abstención no los frena):\n")
        w(table(["id", "dialecto", "texto", "verdad", f"{n0} (p)", "reglas"],
                [[e["id"], e["dialect"], e["text"].replace("|", "/")[:110], e["true"], f"{e[n0]} ({e[f'p_{n0}']})",
                  e["rules"]] for e in worst]))
        wins = [e for e in errs if e[n0] == e["true"] and e["rules"] != e["true"]]
        loss = [e for e in errs if e[n0] != e["true"] and e["rules"] == e["true"]]
        w(f"\n<details><summary>{n0} acierta y reglas fallan ({len(wins)}) · reglas aciertan y {n0} falla ({len(loss)})</summary>\n")
        w(table(["id", "texto", "verdad", "reglas", n0],
                [[e["id"], e["text"].replace("|", "/")[:100], e["true"], e["rules"], e[n0]] for e in wins[:12] + loss[:12]]))
        w("\n</details>\n")
    w("## Calibración\n")
    w("Temperatura ajustada por NLL en las predicciones fuera de fold; ECE con 10 bins de igual ancho.\n")
    w(table(["sistema", "ECE validación cruda → calibrada", *[f"ECE {s}" for s in res["splits"]]],
            [[n, f"{sel[cand[n]]['ece_raw']:.3f} → {sel[cand[n]]['ece_cal']:.3f}",
              *[f"{res['splits'][s]['systems'][n]['ece']:.3f}" for s in res["splits"]]] for n in systems]))
    w("\n![Diagrama de confiabilidad](figures/intent_reliability.png)\n")
    w("## Limitaciones\n")
    w("- El corpus lo escribieron asistentes de IA siguiendo una guía: es más limpio y prototípico que el tráfico real "
      "(de ahí el acuerdo casi perfecto entre anotadores). Los números absolutos son optimistas; el test de estilo no "
      "visto y la evaluación de punta a punta (`reports/eval.md`) son la referencia más realista.")
    w("- RuleRouter se ajustó en #54 con el split dev de `evals/cases` y con frases propias, no con este corpus; aun "
      "así, nadie ajustó las reglas mirando el test C/D/G.")
    w("- La guía da precedencia a disputa sobre pedido de humano (\"quiero hablar con alguien por un cargo que no "
      "hice\" = `dispute_charge`); RuleRouter hace lo contrario a propósito (#54). Esos casos cuentan como error de "
      "reglas aunque sean una decisión de diseño: son pocos (fila *disputa → handoff* de su matriz por ruta).")
    w("- `dispute_status` y `cancel_dispute` tienen un solo autor de train (F): es donde más se abstiene el modelo "
      "(pasa a aclarar, no a una acción). Más autores para esas dos intenciones es la mejora más barata.")
    w("- El mejor C quedó en el borde de la grilla (30) para todos los candidatos; no se amplió después de ver el test.")
    w("- n chico por intención (≈20–60 en test): por eso los IC por bootstrap de familias.\n")
    w("## Reproducir\n")
    w("```bash\npip install -e \".[ml,ml-train]\"\nPYTHONPATH=src python scripts/train_intent.py   # CPU, minutos; "
      "baja los modelos preentrenados a la caché de Hugging Face la primera vez\n```\n")
    e = res["env"]
    m = metas[systems[0]]
    w(f"Python {e['python']} · {e['machine']} · {e['processor']} · numpy {m['numpy']} · scikit-learn {m['sklearn']}.\n")
    return "\n".join(L) + "\n"
