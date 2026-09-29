"""Genera reports/intent_router.md a partir de los resultados de train_intent.py (no editar el .md a mano)."""
from __future__ import annotations

from collections import Counter

import numpy as np

from bankagent.intent_model import LABELS

ROUTES = ("dispute", "block", "handoff", "clarify")
ROUTE_ES = {"dispute": "disputa", "block": "bloqueo", "handoff": "handoff", "clarify": "aclarar"}
SPLIT_ES = {"test": "test (autor C)", "test_style": "test de estilo no visto (autor D)"}


def pct(x: float, d: int = 1) -> str:
    return f"{100 * x:.{d}f}%"


def ci(res_split: dict, key: str, as_pct: bool = False) -> str:
    lo, hi = res_split["ci95"][key]
    return f"[{pct(lo)}, {pct(hi)}]" if as_pct else f"[{lo:.3f}, {hi:.3f}]"


def table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def confusion_md(m: list[list[int]], labels) -> str:
    short = [lab.replace("_", " ") for lab in labels]
    return table(["verdad \\ predicción"] + short, [[short[i]] + row for i, row in enumerate(m)])


def seeds_md(seeds: list[dict], key: str) -> str:
    v = np.array([s[key] for s in seeds])
    return f"{v.mean():.3f} ± {v.std(ddof=1):.3f}"


def write_report(res: dict, data: dict, tests: dict) -> str:
    meta, sel, lat = res["meta"], res["selection"], res["latency"]
    chosen = meta["candidate"]
    cs = sel[chosen]
    T, S = res["splits"]["test"], res["splits"]["test_style"]
    L = []
    w = L.append
    w("# Router de intención aprendido vs. RuleRouter\n")
    w("> Generado por `scripts/train_intent.py` — no editar a mano. Decisión y justificación: "
      "[ADR 0007](../docs/adr/0007-router-aprendido.md). Corpus y guía: [`corpus/intent/`](../corpus/intent/).\n")
    w(f"**Modelo elegido:** `{chosen}` → `{meta['model_id']}` · regresión logística (C={cs['C']}, clases balanceadas) · "
      f"temperatura T={cs['T']:.2f} · umbral de abstención τ={cs['tau']:.2f} ({cs['why']}). "
      f"Artefactos: `models/intent_router/` ({res['artifact_mb']} MB), corpus sha256 `{meta['corpus_sha256'][:12]}…`.\n")

    w("## Resumen\n")
    rows = []
    for name, R in (("test", T), ("test_style", S)):
        lr, rr = R["learned"], R["rules"]
        rows += [
            [SPLIT_ES[name], "n (familias)", f"{R['n']} ({R['families']})", ""],
            ["", "macro-F1 por ruta (IC 95%)", f"{rr['route_macro_f1']:.3f} {ci(R, 'rules.route_macro_f1')}",
             f"**{lr['route_macro_f1']:.3f}** {ci(R, 'learned.route_macro_f1')}"],
            ["", "Δ macro-F1 ruta aprendido − reglas (IC 95%)", "", f"{lr['route_macro_f1'] - rr['route_macro_f1']:+.3f} {ci(R, 'diff.route_macro_f1')}"],
            ["", "macro-F1 7 etiquetas", f"{rr['macro_f1']:.3f}¹", f"{lr['macro_f1']:.3f}"],
            ["", "mensajes con acción equivocada", f"{pct(rr['wrong_action_rate'])} ({rr['wrong_action']})",
             f"{pct(lr['wrong_action_rate'])} ({lr['wrong_action']})"],
            ["", "handoff pedido → se inició disputa", rr["handoff_to_dispute"], lr["handoff_to_dispute"]],
            ["", "costo esperado por mensaje (IC 95%)", f"{rr['cost_per_msg']:.3f} {ci(R, 'rules.cost_per_msg')}",
             f"{lr['cost_per_msg']:.3f} {ci(R, 'learned.cost_per_msg')}"],
            ["", "cobertura (sin aclarar por baja confianza)", pct(rr["coverage"]), pct(lr["coverage"])],
            ["", "5 semillas (85% familias): macro-F1 ruta", "—", seeds_md(R["seeds"], "route_macro_f1")],
        ]
    lp, lr_ = lat[chosen], lat["rules"]
    rows += [["CPU, 1 mensaje", "latencia p50 / p95", f"{lr_['p50_ms']:.2f} / {lr_['p95_ms']:.2f} ms",
              f"{lp['p50_ms']:.2f} / {lp['p95_ms']:.2f} ms (+ reglas para slots)"],
             ["", "tamaño en disco", "0 MB", f"{res['artifact_mb']} MB artefactos + {lp['model_mb']} MB modelo preentrenado"]]
    w(table(["split", "métrica", "RuleRouter (línea base)", "Aprendido"], rows))
    w("\n¹ RuleRouter no tiene `human_request`, `account_takeover` ni `closing`: en 7 etiquetas pierde por construcción. "
      "La comparación justa es **por ruta** (lo que hace el grafo: disputa / bloqueo / handoff / aclarar), donde "
      "`human_request` y `account_takeover` = handoff (vía `out_of_scope`) y `closing` = aclarar, igual que el "
      "mapeo `COMPAT` que usa el router en producción. RuleRouter se evalúa como lo usa el grafo: confianza < 0.6 → aclarar.\n")
    w("Acción equivocada = el grafo arranca disputa o bloqueo cuando la ruta correcta era otra. Costo por ruta "
      "(verdad→predicción): handoff→disputa 3; disputa↔bloqueo 2; aclarar→acción 2; handoff→bloqueo 2; cualquier "
      "→handoff 1; cualquier →aclarar 0.5 (un turno más). IC por bootstrap de familias (2000 réplicas).\n")

    w("## Datos y etiquetas\n")
    cnt = {s: Counter(r["intent"] for r in rows_) for s, rows_ in (("train", data["train"]), *tests.items())}
    w(table(["etiqueta"] + [f"{s} (n={sum(c.values())})" for s, c in cnt.items()],
            [[lab] + [cnt[s][lab] for s in cnt] for lab in LABELS]))
    dcnt = {s: Counter(r["dialect"] for r in rows_) for s, rows_ in (("train", data["train"]), *tests.items())}
    w("\n" + table(["dialecto"] + list(dcnt), [[d] + [dcnt[s][d] for s in dcnt] for d in ("es-MX", "es-CO", "es-AR", "pt-BR", "mix")]))
    w("\n- **Procedencia:** enunciados escritos por el equipo con asistentes de IA, cada autor en una sesión aislada que "
      "solo leyó la [guía de etiquetado](../corpus/intent/GUIA_ETIQUETADO.md) (ni las reglas, ni los otros archivos). "
      "Autores A, B, E → train; C → test; D → test de estilo no visto (voz a texto, telegráfico, formal). "
      "No hay texto de clientes ni del dataset del organizador (ADR 0003).")
    ag = res.get("agreement") or {}
    if ag:
        w("- **Validez de etiquetas:** una segunda anotación ciega (solo el texto + la guía) sobre todo el test y una "
          "muestra de train; los desacuerdos los resolvió un tercer adjudicador (o se descartaron por ambiguos):")
        w("\n" + table(["split", "n", "acuerdo", "κ de Cohen", "desacuerdos", "reetiquetados", "descartados", "queda autor"],
                       [[s, a["n"], pct(a["agreement"]), f"{a['kappa']:.3f}", a["disagreements"], a["relabeled"],
                         a["dropped"], a["kept_author"]] for s, a in ag.items()]) + "\n")
    lk = res["leak_excluded"]
    w(f"- **Fuga:** split por autor (familias de paráfrasis nunca cruzan); vocabulario de n-gramas ajustado dentro de "
      f"cada fold; test excluido de toda selección; casi-duplicados de train (Jaccard de trigramas ≥ 0.8) sacados "
      f"del test: {len(lk['test'])} en test, {len(lk['test_style'])} en estilo. Hashes congelados en "
      f"`corpus/intent/MANIFEST.json` ({res['manifest']['frozen_at']}) antes de entrenar; el script aborta si cambian.\n")

    w("## Selección del componente (solo validación cruzada por autor sobre train)\n")
    w("Tres folds: se entrena con dos autores y se valida con el tercero (que el modelo nunca vio). Todo lo que se "
      "elige —encoder, C, temperatura, umbral— sale de acá; el test se evalúa una sola vez al final.\n")
    rows = []
    for c, s in sel.items():
        la = lat[c]
        rows.append([f"**{c}**" if c == chosen else c, f"{s['macro_f1']:.3f}", f"{s['route_macro_f1']:.3f}", s["C"],
                     f"{s['T']:.2f}", f"{s['ece_raw']:.3f} → {s['ece_cal']:.3f}", f"{s['tau']:.2f}",
                     pct(s["at_tau"]["coverage"]), pct(s["at_tau"]["wrong_action_rate"]),
                     f"{la['p50_ms']:.2f} / {la['p95_ms']:.2f}", la["model_mb"], la["load_s"]])
    dr = res["dev_rules"]
    rows.append(["RuleRouter", "—", f"{dr['route_macro_f1']:.3f}", "", "", "", "", "", pct(dr["wrong_action_rate"]),
                 f"{lat['rules']['p50_ms']:.2f} / {lat['rules']['p95_ms']:.2f}", 0, 0])
    w(table(["candidato", "macro-F1 (7)", "macro-F1 ruta", "C", "T", "ECE cruda → calibrada", "τ", "cobertura",
             "acción equivocada", "p50 / p95 ms", "MB modelo", "carga s"], rows))
    w("\nRegla de decisión (fijada antes de mirar el test): mayor macro-F1 de 7 etiquetas en validación; si otro candidato "
      "queda a menos de 0.01, gana el más liviano (tamaño de la imagen y latencia). `char` = TF-IDF de n-gramas de "
      "caracteres 2–5 aprendido del corpus; `m2v` = model2vec potion-multilingual-128M; `minilm` = "
      "paraphrase-multilingual-MiniLM-L12-v2 (ONNX cuantizado); `e5` = multilingual-e5-small (ONNX int8).\n")
    w("![Cobertura vs acción equivocada](figures/intent_coverage.png)\n")

    for name, R in (("test", T), ("test_style", S)):
        lr, rr = R["learned"], R["rules"]
        w(f"## Resultados — {SPLIT_ES[name]}\n")
        w(f"n={R['n']}, {R['families']} familias. Aprendido: ECE {lr['ece']:.3f}; sin abstención macro-F1 "
          f"{lr['macro_f1_no_abstention']:.3f}, acción equivocada {pct(lr['route_no_abstention']['wrong_action_rate'])}.\n")
        w("### Por etiqueta\n")
        w(table(["etiqueta", "soporte", "P reglas", "R reglas", "F1 reglas", "P aprendido", "R aprendido", "F1 aprendido"],
                [[lab, lr["per_label"][lab]["support"], *(f"{rr['per_label'][lab][k]:.2f}" for k in ("precision", "recall", "f1")),
                  *(f"{lr['per_label'][lab][k]:.2f}" for k in ("precision", "recall", "f1"))] for lab in LABELS]))
        w("\n### Matriz de confusión por ruta\n")
        w("Aprendido:\n\n" + confusion_md(R["route_confusion"]["learned"], [ROUTE_ES[r] for r in ROUTES]))
        w("\nRuleRouter:\n\n" + confusion_md(R["route_confusion"]["rules"], [ROUTE_ES[r] for r in ROUTES]))
        w("\n<details><summary>Matriz de confusión de 7 etiquetas (aprendido)</summary>\n\n"
          + confusion_md(lr["confusion"], LABELS) + "\n\n</details>\n")
        w("### Por dialecto, estilo y negativos difíciles (exactitud por ruta)\n")
        rows = []
        for key, lab in (("dialect", "dialecto"), ("style", "estilo"), ("hard_negative", "negativo difícil")):
            for g, v in R["by"][key].items():
                if v["n"] >= 5:
                    rows.append([lab, g, v["n"], pct(v["rules_acc"]), pct(v["learned_acc"])])
        w(table(["corte", "grupo", "n", "RuleRouter", "Aprendido"], rows))
        w("\n### Variabilidad (5 semillas, 85% de las familias de train cada una)\n")
        w(table(["semilla", "macro-F1 (7)", "macro-F1 ruta", "acción equivocada", "costo/msg"],
                [[s["seed"], f"{s['macro_f1']:.3f}", f"{s['route_macro_f1']:.3f}", pct(s["wrong_action_rate"]),
                  f"{s['cost_per_msg']:.3f}"] for s in R["seeds"]]))
        w("\n### Errores\n")
        errs = R["errors"]
        from bankagent.intent_model import ROUTE
        le = [e for e in errs if ROUTE[e["learned"]] != ROUTE[e["true"]]]
        re_ = [e for e in errs if ROUTE[e["rules"]] != ROUTE[e["true"]]]
        pairs = Counter(f"{e['true']} → {e['learned']}" for e in le)
        w(f"Aprendido falla la ruta en {len(le)} mensajes; RuleRouter en {len(re_)}; ambos en "
          f"{sum(1 for e in le if ROUTE[e['rules']] != ROUTE[e['true']])}. Pares más frecuentes del aprendido: "
          + ", ".join(f"{k} ({v})" for k, v in pairs.most_common(6)) + ".\n")
        worst = sorted(le, key=lambda e: -e["p"])[:12]
        w(table(["id", "dialecto", "texto", "verdad", "aprendido (p)", "reglas"],
                [[e["id"], e["dialect"], e["text"].replace("|", "/")[:110], e["true"], f"{e['learned']} ({e['p']})", e["rules"]]
                 for e in worst]))
        w("\n<details><summary>Aciertos del aprendido donde RuleRouter falla (muestra)</summary>\n")
        wins = [e for e in errs if ROUTE[e["learned"]] == ROUTE[e["true"]] and ROUTE[e["rules"]] != ROUTE[e["true"]]]
        w(table(["id", "texto", "verdad", "reglas"], [[e["id"], e["text"].replace("|", "/")[:110], e["true"], e["rules"]] for e in wins[:15]]))
        w("\n</details>\n")
    w("## Calibración\n")
    w(f"Temperatura ajustada por NLL en las predicciones fuera de fold (T={cs['T']:.2f}); ECE en validación "
      f"{cs['ece_raw']:.3f} → {cs['ece_cal']:.3f}; en test {T['learned']['ece']:.3f}; en estilo no visto {S['learned']['ece']:.3f} (10 bins).\n")
    w("![Diagrama de confiabilidad](figures/intent_reliability.png)\n")
    w("## Reproducir\n")
    w("```bash\npip install -e \".[ml,ml-train]\"\nPYTHONPATH=src python scripts/train_intent.py   # ~minutos en CPU; "
      "descarga los modelos preentrenados a la caché de Hugging Face la primera vez\n```\n")
    e = res["env"]
    w(f"Medido en Python {e['python']} · {e['machine']} · {e['processor']} · numpy {meta['numpy']} · scikit-learn {meta['sklearn']}. "
      "La latencia es de un mensaje a la vez tras un calentamiento (sin lotes), igual que en el grafo.\n")
    return "\n".join(L) + "\n"
