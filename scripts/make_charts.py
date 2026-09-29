"""Gráficos del pitch (issue #16): un comando, PNG + SVG en docs/pitch/charts/.

    PYTHONPATH=src python scripts/make_charts.py                       # agrega desde data/bank.duckdb
    PYTHONPATH=src python scripts/make_charts.py --from-cache          # sin datos: usa docs/pitch/chart_data.json
    PYTHONPATH=src python scripts/make_charts.py --diagrams             # además renderiza los Mermaid de docs/

- Solo se guardan AGREGADOS (conteos y porcentajes) en `chart_data.json`; ninguna fila del dataset.
- Cada título es la conclusión del gráfico (no una etiqueta) y se calcula desde los agregados.
- Paleta: una serie resaltada (azul) contra contexto gris; segunda serie naranja. Validada para daltonismo
  (azul/naranja, ΔE CVD 24.7). La identidad nunca va solo por color: hay etiquetas directas.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "pitch", "charts")
CACHE = os.path.join(ROOT, "docs", "pitch", "chart_data.json")
SOURCE = "Fuente: datos sintéticos del organizador (LATAM Bank)"

# --- tokens de color (fondo claro) ------------------------------------------------------------
SURFACE = "#ffffff"
INK = "#0b0b0b"
INK_2 = "#52514e"
INK_3 = "#8a8984"
GRID = "#e6e5e1"
CONTEXT = "#c9c8c2"  # barras de contexto
BLUE = "#2a78d6"  # serie resaltada / recall
ORANGE = "#eb6834"  # segunda serie / precisión
RED = "#c62f2e"  # solo para el umbral provisional descartado (con etiqueta)

plt.rcParams.update({
    "font.family": ["Arial", "DejaVu Sans"],
    "font.size": 13,
    "axes.edgecolor": GRID,
    "axes.labelcolor": INK_2,
    "xtick.color": INK_2,
    "ytick.color": INK_2,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "svg.fonttype": "none",
})

# Diferencias entre las dos entregas del bucket (data/ vs data_backup_20260831/).
# Viene de reports/snapshot_diff.md (scripts/compare_snapshots.py, PR #18): el backup no está en bank.duckdb.
SNAPSHOT = {"customers_ids_only_in_one": 145_975, "customers_total": 150_000,
            "complaints_changed": 67_095, "complaints_total": 67_095}


# ------------------------------------------------------------------ agregados
def aggregate(db: str) -> dict:
    import duckdb

    con = duckdb.connect(db, read_only=True)
    q = lambda sql: con.execute(sql).fetchall()  # noqa: E731

    demand = [dict(zip(["category", "n", "fcr", "followup", "median_duration_s"], r)) for r in q("""
        SELECT reason_category, count(*),
               avg(CASE WHEN lower(CAST(was_resolved AS VARCHAR)) = 'true' THEN 1.0 ELSE 0 END),
               avg(CASE WHEN lower(CAST(requires_followup AS VARCHAR)) = 'true' THEN 1.0 ELSE 0 END),
               median(try_cast(duration_seconds AS DOUBLE))
        FROM raw_call_center_interactions GROUP BY 1 ORDER BY 2 DESC""")]

    pqr = [dict(zip(["subcategory", "n", "sla_breach", "median_days", "unresolved"], r)) for r in q("""
        SELECT coalesce(subcategory, '(sin subcategoría)'), count(*),
               avg(CASE WHEN lower(CAST(sla_breached AS VARCHAR)) = 'true' THEN 1.0 ELSE 0 END),
               median(try_cast(resolution_days AS DOUBLE)),
               avg(CASE WHEN resolution_date IS NULL THEN 1.0 ELSE 0 END)
        FROM raw_complaints GROUP BY 1 ORDER BY 2 DESC""")]

    t_total, t_distinct = q("SELECT count(*), count(DISTINCT customer_text) FROM raw_call_transcripts")[0]
    mx_total, mx_mxn = q("""SELECT count(*), count(*) FILTER (WHERE currency = 'MXN') FROM raw_transactions
                            WHERE transaction_country IN ('México', 'Mexico')""")[0]
    nulls = dict(zip(["merchant_name", "amount_usd", "fraud_score"], q("""
        SELECT avg(CASE WHEN merchant_name IS NULL THEN 1.0 ELSE 0 END),
               avg(CASE WHEN amount_usd IS NULL THEN 1.0 ELSE 0 END),
               avg(CASE WHEN fraud_score IS NULL THEN 1.0 ELSE 0 END) FROM raw_transactions""")[0]))
    nulls["origin_interaction_id"] = q(
        "SELECT avg(CASE WHEN origin_interaction_id IS NULL THEN 1.0 ELSE 0 END) FROM raw_complaints")[0][0]

    # Umbral de fraude: histograma por score entero -> curvas acumuladas (mismo split que calibrate_fraud.py).
    fraud = {}
    for name, where in [("dev", "process_date < '2026-01-01'"), ("test", "process_date >= '2026-01-01'")]:
        rows = q(f"""SELECT floor(try_cast(fraud_score AS DOUBLE))::INT s, count(*) n,
                            count(*) FILTER (WHERE lower(is_fraud) = 'true') pos
                     FROM raw_transactions WHERE fraud_score IS NOT NULL AND {where} GROUP BY 1 ORDER BY 1""")
        fraud[name] = [{"score": s, "n": n, "pos": p} for s, n, p in rows]

    return {"demand": demand, "pqr": pqr,
            "quality": {"transcripts": t_total, "distinct_customer_texts": t_distinct,
                        "mx_transactions": mx_total, "mx_in_mxn": mx_mxn, "nulls": nulls, "snapshot": SNAPSHOT},
            "fraud": fraud, "chosen_threshold": 30, "provisional_threshold": 60}


def fraud_curve(hist: list[dict]) -> list[dict]:
    """Para cada umbral t (score >= t): recall, precisión y % derivado."""
    n_all = sum(h["n"] for h in hist)
    pos_all = sum(h["pos"] for h in hist)
    out = []
    for t in range(0, 101):
        n = sum(h["n"] for h in hist if h["score"] >= t)
        p = sum(h["pos"] for h in hist if h["score"] >= t)
        out.append({"t": t, "recall": p / pos_all, "precision": p / n if n else float("nan"),
                    "flagged": n / n_all})
    return out


# ------------------------------------------------------------------ utilidades de dibujo
def _title(fig, title: str, subtitle: str | None = None):
    fig.text(0.02, 0.965, title, fontsize=19, fontweight="bold", color=INK, va="top", ha="left")
    if subtitle:
        fig.text(0.02, 0.905, subtitle, fontsize=13, color=INK_2, va="top", ha="left")


def _source(fig, extra: str = ""):
    fig.text(0.02, 0.02, SOURCE + (f" · {extra}" if extra else ""), fontsize=10, color=INK_3, ha="left")


def _save(fig, name: str, svg: bool):
    os.makedirs(OUT, exist_ok=True)
    fig.savefig(os.path.join(OUT, f"{name}.png"), dpi=200)
    if svg:
        fig.savefig(os.path.join(OUT, f"{name}.svg"))
    plt.close(fig)
    print(f"  docs/pitch/charts/{name}.png")


def _pct(x: float, d: int = 0) -> str:
    return f"{100 * x:.{d}f}%"


# ------------------------------------------------------------------ 1. demanda y calidad por motivo
def chart_demand(d: dict, svg: bool) -> str:
    rows = d["demand"]
    total = sum(r["n"] for r in rows)
    rows = sorted(rows, key=lambda r: r["n"])  # mayor arriba en barh
    cats = [r["category"] for r in rows]
    q = next(r for r in rows if r["category"] == "Queja")
    tr = next(r for r in rows if r["category"] == "Transaccional")
    title = (f"Las quejas son el {_pct(q['n'] / total)} de los contactos y solo el "
             f"{_pct(q['fcr'], 1)} se resuelve al primer contacto")
    subtitle = (f"FCR {_pct(q['fcr'], 1)} vs {_pct(tr['fcr'], 1)} en transaccionales · "
                f"{_pct(q['followup'])} requiere seguimiento · duración ×{q['median_duration_s'] / tr['median_duration_s']:.1f}")
    panels = [("% de contactos", [r["n"] / total for r in rows], lambda v: _pct(v)),
              ("Resuelto al 1er contacto (FCR)", [r["fcr"] for r in rows], lambda v: _pct(v)),
              ("Requiere seguimiento", [r["followup"] for r in rows], lambda v: _pct(v)),
              ("Duración mediana", [r["median_duration_s"] for r in rows], lambda v: f"{v / 60:.1f} min")]
    fig, axes = plt.subplots(1, 4, figsize=(16, 7), sharey=True)
    fig.subplots_adjust(left=0.12, right=0.98, top=0.76, bottom=0.1, wspace=0.18)
    colors = [BLUE if c == "Queja" else CONTEXT for c in cats]
    for ax, (label, vals, fmt) in zip(axes, panels):
        ax.barh(cats, vals, color=colors, height=0.68, edgecolor=SURFACE, linewidth=2)
        ax.set_title(label, fontsize=13, color=INK, loc="left", pad=10, fontweight="bold")
        ax.set_xticks([])
        ax.spines["bottom"].set_visible(False)
        ax.tick_params(axis="y", length=0, labelsize=13)
        m = max(vals)
        ax.set_xlim(0, m * 1.35)
        for i, v in enumerate(vals):
            is_q = cats[i] == "Queja"
            ax.text(v + m * 0.03, i, fmt(v), va="center", fontsize=12.5 if is_q else 11.5,
                    color=INK if is_q else INK_2, fontweight="bold" if is_q else "normal")
    for lbl in axes[0].get_yticklabels():
        if lbl.get_text() == "Queja":
            lbl.set_fontweight("bold")
            lbl.set_color(INK)
    _title(fig, title, subtitle)
    _source(fig, f"{total:,} interacciones del call center".replace(",", "."))
    _save(fig, "01_demanda_quejas", svg)
    return title


# ------------------------------------------------------------------ 2. PQR por subcategoría
DISPUTES = {"Cargo no reconocido", "Cobro indebido"}


def chart_pqr(d: dict, svg: bool) -> str:
    rows = [dict(r, subcategory=r["subcategory"].replace("\ufffd", "ó")) for r in d["pqr"]]
    total = sum(r["n"] for r in rows)
    disp = [r for r in rows if r["subcategory"] in DISPUTES]
    share = sum(r["n"] for r in disp) / total
    sla = sum(r["sla_breach"] * r["n"] for r in disp) / sum(r["n"] for r in disp)
    med = max(r["median_days"] for r in disp)
    title = f"Cargo no reconocido + cobro indebido = {_pct(share, 1)} de los PQR; 1 de cada {round(1 / sla)} incumple el SLA"
    subtitle = ("SLA y días de resolución son iguales en todas las subcategorías (dato sintético): "
                "el dolor está en el volumen, y es el flujo que se puede automatizar sin mover dinero")
    rows = sorted(rows, key=lambda r: (r["subcategory"].startswith("("), -r["n"]), reverse=True)
    cats = [r["subcategory"] for r in rows]
    vals = [r["n"] / total for r in rows]
    fig, ax = plt.subplots(figsize=(16, 7))
    fig.subplots_adjust(left=0.2, right=0.66, top=0.76, bottom=0.12)
    colors = [BLUE if c in DISPUTES else CONTEXT for c in cats]
    ax.barh(cats, vals, color=colors, height=0.68, edgecolor=SURFACE, linewidth=2)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="y", length=0, labelsize=13)
    ax.set_xlim(0, max(vals) * 1.25)
    for i, (r, v) in enumerate(zip(rows, vals)):
        hl = r["subcategory"] in DISPUTES
        ax.text(v + max(vals) * 0.02, i, f"{_pct(v)}  ({r['n']:,})".replace(",", "."), va="center",
                fontsize=12, color=INK if hl else INK_2, fontweight="bold" if hl else "normal")
    for lbl in ax.get_yticklabels():
        if lbl.get_text() in DISPUTES:
            lbl.set_fontweight("bold")
            lbl.set_color(INK)
    # tabla a la derecha: SLA incumplido y mediana de días (texto, no un segundo eje)
    x_sla, x_days, x_unres = 0.72, 0.83, 0.93
    top_y = ax.transData.transform((0, len(rows) - 1))[1]
    for x, h in [(x_sla, "SLA\nincumplido"), (x_days, "Mediana\n(días)"), (x_unres, "Sin\nresolución")]:
        fig.text(x, 0.8, h, fontsize=12, color=INK, fontweight="bold", ha="center", va="bottom")
    for i, r in enumerate(rows):
        y = fig.transFigure.inverted().transform(ax.transData.transform((0, i)))[1]
        hl = r["subcategory"] in DISPUTES
        kw = dict(fontsize=12.5, ha="center", va="center", color=INK if hl else INK_2,
                  fontweight="bold" if hl else "normal")
        fig.text(x_sla, y, _pct(r["sla_breach"]), **kw)
        fig.text(x_days, y, f"{r['median_days']:.0f}", **kw)
        fig.text(x_unres, y, _pct(r["unresolved"]), **kw)
    del top_y
    _title(fig, title, subtitle)
    _source(fig, f"{total:,} casos PQR · mediana sobre casos con resolución registrada".replace(",", "."))
    _save(fig, "02_pqr_subcategorias", svg)
    return title


# ------------------------------------------------------------------ 3. calidad de datos -> decisiones
def chart_quality(d: dict, svg: bool) -> str:
    qd = d["quality"]
    s = qd["snapshot"]
    items = [
        (f"{qd['distinct_customer_texts']}",
         f"textos de cliente distintos en {qd['transcripts']:,} transcripciones;\nel texto no depende del motivo".replace(",", "."),
         "No entrenamos intención con transcripciones.\nComponente aprendido: inyección con datasets públicos (ADR 0003)"),
        (_pct(1 - qd["mx_in_mxn"] / qd["mx_transactions"]) if qd["mx_transactions"] else "—",
         f"de las transacciones en México sin MXN\n(todo en USD; país como «México» y «Mexico»)",
         "Advertencia de contrato `mexico_without_mxn`;\nnormalizamos el país y mostramos la moneda registrada"),
        (_pct(qd["nulls"]["merchant_name"]),
         "de transacciones sin comercio\n(y " + _pct(qd["nulls"]["amount_usd"]) + " sin monto en USD)",
         "El agente identifica el cargo por monto y fecha;\nsi hay varias candidatas, pregunta"),
        (_pct(qd["nulls"]["fraud_score"]),
         "de transacciones sin fraud_score:\nla regla de fraude H03 no las ve",
         "Riesgo residual documentado; lo cubren H02/H04\ny el analista que recibe la disputa (ADR 0006)"),
        (_pct(qd["nulls"]["origin_interaction_id"]),
         "de quejas sin vínculo a la llamada de origen\n(origin_interaction_id nulo)",
         "No medimos la prevalencia de fraude entre cargos\ndisputados; lo decimos en vez de inventarlo"),
        (_pct(s["customers_ids_only_in_one"] / s["customers_total"]),
         "de IDs de cliente cambian entre las dos\nentregas del bucket (data/ vs backup)",
         "Huella por entrega, comparador de snapshots y\nupsert idempotente con linaje por corrida"),
    ]
    title = "Los datos tienen límites reales; cada uno cambió una decisión de diseño"
    fig = plt.figure(figsize=(16, 9))
    _title(fig, title, "Se reportan, no se ocultan: contrato, cuarentena y linaje en cada corrida del pipeline")
    top, row_h = 0.8, 0.118
    fig.text(0.02, top + 0.015, "Hallazgo", fontsize=12, color=INK_3, fontweight="bold")
    fig.text(0.60, top + 0.015, "Decisión que tomamos", fontsize=12, color=INK_3, fontweight="bold")
    for i, (big, finding, decision) in enumerate(items):
        y = top - (i + 0.5) * row_h
        if i:
            fig.add_artist(plt.Line2D([0.02, 0.98], [top - i * row_h] * 2, color=GRID, lw=1))
        fig.text(0.02, y, big, fontsize=30, fontweight="bold", color=BLUE, va="center")
        fig.text(0.16, y, finding, fontsize=13, color=INK, va="center", linespacing=1.35)
        fig.text(0.575, y, "→", fontsize=20, color=INK_3, va="center")
        fig.text(0.60, y, decision, fontsize=13, color=INK_2, va="center", linespacing=1.35)
    _source(fig, "entregas comparadas en reports/snapshot_diff.md")
    _save(fig, "03_calidad_datos", svg)
    return title


# ------------------------------------------------------------------ 4. umbral de fraude
def chart_fraud(d: dict, svg: bool) -> str:
    dev, test = fraud_curve(d["fraud"]["dev"]), fraud_curve(d["fraud"]["test"])
    ch, pv = d["chosen_threshold"], d["provisional_threshold"]
    tc, dp = test[ch], dev[pv]
    title = (f"Umbral {ch} (no {pv}): recall {_pct(tc['recall'])} en test derivando solo el "
             f"{_pct(tc['flagged'], 2)} de las transacciones")
    subtitle = (f"Elegido en dev (<2026) con presupuesto de derivación ≤ 2%, medido una sola vez en test (2026). "
                f"Con {pv}, el recall en dev era {_pct(dp['recall'])}")
    ts = [r["t"] for r in dev]
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(16, 9), sharex=True, gridspec_kw={"height_ratios": [2.3, 1]})
    fig.subplots_adjust(left=0.08, right=0.96, top=0.8, bottom=0.1, hspace=0.12)
    for curve, ls, split in [(dev, "-", "dev"), (test, "--", "test")]:
        ax.plot(ts, [r["recall"] for r in curve], color=BLUE, lw=2.4, ls=ls)
        ax.plot(ts, [r["precision"] for r in curve], color=ORANGE, lw=2.4, ls=ls)
        ax2.plot(ts, [r["flagged"] for r in curve], color=INK_2, lw=2, ls=ls)
    # etiquetas directas junto a cada línea (dev y test comparten color; el trazo las distingue)
    ax.text(80, 0.93, "Precisión", color=INK, fontsize=13, fontweight="bold", va="top")
    ax.text(80, dev[80]["recall"] + 0.1, "Recall", color=INK, fontsize=13, fontweight="bold", va="bottom")
    for a in (ax, ax2):
        a.axvline(ch, color=BLUE, lw=1.5)
        a.axvline(pv, color=INK_3, lw=1.5, ls=":")
        a.grid(axis="y", color=GRID, lw=1)
        a.tick_params(length=0)
    ax.set_ylim(0, 1.05)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1])
    ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.text(ch + 1.5, 0.9, f"Elegido: {ch}\ntest: recall {_pct(tc['recall'])} · precisión {_pct(tc['precision'])}",
            color=INK, fontsize=12.5, fontweight="bold", va="top")
    ax.text(pv + 1, 0.62, f"Provisional: {pv}\ndev: recall {_pct(dp['recall'])}", color=INK_2, fontsize=12, va="top")
    ax2.set_ylim(0, 1.05)
    ax2.set_yticks([0, 0.5, 1])
    ax2.set_yticklabels(["0%", "50%", "100%"])
    ax2.set_ylabel("% derivado\na analista", fontsize=12)
    ax2.set_xlabel("Umbral de fraud_score (se deriva si score ≥ umbral)", fontsize=12)
    ax2.set_xlim(0, 100)
    ax2.text(ch + 1.5, 0.55, f"umbral 25 → {_pct(dev[25]['flagged'], 1)} derivado (inviable)\n"
             f"umbral {ch} → {_pct(dev[ch]['flagged'], 2)} derivado (dev)", color=INK_2, fontsize=12, ha="left", va="center")
    fig.text(0.08, 0.815, "── dev (<2026)    - - test (2026)", fontsize=12, color=INK_2)
    _title(fig, title, subtitle)
    _source(fig, "fraud_score del core (no lo entrenamos) · el quiebre en ~30 es un artefacto del generador")
    _save(fig, "04_umbral_fraude", svg)
    return title


# ------------------------------------------------------------------ diagramas Mermaid (opcional)
def render_diagrams() -> list[str]:
    """Extrae los bloques Mermaid de docs/architecture.md y los renderiza con mermaid-cli (npx)."""
    npx = shutil.which("npx")
    if not npx:
        print("  (sin npx: se omiten los diagramas)")
        return []
    src = open(os.path.join(ROOT, "docs", "architecture.md"), encoding="utf-8").read()
    blocks = re.findall(r"```mermaid\n(.*?)```", src, re.S)
    names = ["arq_4_capas", "arq_grafo", "arq_secuencia", "arq_datos", "arq_confianza"]
    chrome = next((p for p in [os.environ.get("PUPPETEER_EXECUTABLE_PATH", ""),
                               r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                               "/usr/bin/google-chrome", "/usr/bin/chromium"] if p and os.path.exists(p)), None)
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        cfg = os.path.join(tmp, "pp.json")
        json.dump({"executablePath": chrome} if chrome else {}, open(cfg, "w"))
        for name, body in zip(names, blocks):
            mmd = os.path.join(tmp, f"{name}.mmd")
            open(mmd, "w", encoding="utf-8").write(body)
            dst = os.path.join(OUT, f"{name}.png")
            r = subprocess.run([npx, "-y", "@mermaid-js/mermaid-cli", "-i", mmd, "-o", dst, "-p", cfg,
                                "-b", "white", "-s", "3", "-t", "neutral"],
                               capture_output=True, text=True, env={**os.environ, "PUPPETEER_SKIP_DOWNLOAD": "1"})
            if r.returncode == 0:
                out.append(dst)
                print(f"  docs/pitch/charts/{name}.png")
            else:
                print(f"  (falló {name}: {r.stderr.strip()[:200]})")
    return out


def main():
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "bank.duckdb"))
    ap.add_argument("--from-cache", action="store_true", help="no consulta la base; usa chart_data.json")
    ap.add_argument("--diagrams", action="store_true", help="renderiza los Mermaid de docs/architecture.md")
    ap.add_argument("--no-svg", action="store_true")
    a = ap.parse_args()

    if not a.from_cache and os.path.exists(a.db):
        print(f"Agregando desde {a.db} ...")
        data = aggregate(a.db)
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, default=float)
    else:
        print(f"Usando agregados en caché: {CACHE}")
        with open(CACHE, encoding="utf-8") as f:
            data = json.load(f)

    svg = not a.no_svg
    titles = {"01_demanda_quejas": chart_demand(data, svg), "02_pqr_subcategorias": chart_pqr(data, svg),
              "03_calidad_datos": chart_quality(data, svg), "04_umbral_fraude": chart_fraud(data, svg)}
    with open(os.path.join(OUT, "titles.json"), "w", encoding="utf-8") as f:
        json.dump(titles, f, ensure_ascii=False, indent=1)
    if a.diagrams:
        render_diagrams()


if __name__ == "__main__":
    main()
