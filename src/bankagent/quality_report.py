"""Reporte de calidad legible a partir de la base serving y de los manifiestos de corrida.

    python -m bankagent.quality_report [--db data/serving.duckdb] [--out reports/data_quality.md]

Incluye: carga por corrida (linaje), cuarentena por check, advertencias del contrato,
completitud contra el diccionario del organizador, frescura y nulos de columnas opcionales.
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import duckdb

from .pipeline import LOAD_ORDER, ROOT, load_contracts

# Filas documentadas en LATAM_Bank_Complete_Data_Dictionary (v1.0.0)
DOCUMENTED_ROWS = {"customers": 150_000, "products": 400_000, "transactions": 5_000_000, "complaints": 80_000}
FRESHNESS_MAX_LAG_DAYS = 2


def build(db: str) -> str:
    contracts = load_contracts()
    contracts.pop("normalize", None)
    con = duckdb.connect(db, read_only=True)
    runs_dir = os.path.join(os.path.dirname(os.path.abspath(db)), "runs")
    runs = [json.load(open(p, encoding="utf-8")) for p in sorted(glob.glob(os.path.join(runs_dir, "*.json")))]
    runs = [r for r in runs if r.get("out_db") == os.path.abspath(db)]
    out = ["# Reporte de calidad de datos", "",
           f"Base: `{os.path.relpath(db, ROOT)}` · corridas registradas: {len(runs)}", ""]

    out += ["## Completitud y cuarentena", "",
            "| Tabla | Filas cargadas | Documentadas | Completitud | En cuarentena |", "|---|---|---|---|---|"]
    for t in LOAD_ORDER:
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        q = con.execute(f"SELECT count(*) FROM quarantine_{t}").fetchone()[0]
        doc = DOCUMENTED_ROWS[t]
        out.append(f"| {t} | {n:,} | {doc:,} | {100 * n / doc:.1f}% | {q:,} |")

    out += ["", "## Checks fallidos (cuarentena)", ""]
    rows = []
    for t in LOAD_ORDER:
        for checks, n in con.execute(f"SELECT _failed_checks, count(*) FROM quarantine_{t} GROUP BY 1 ORDER BY 2 DESC").fetchall():
            rows.append(f"| {t} | `{checks}` | {n:,} |")
    out += (["| Tabla | Checks | Filas |", "|---|---|---|"] + rows) if rows else ["Ninguna fila violó el contrato."]

    out += ["", "## Advertencias del contrato (no bloquean la carga)", "", "| Tabla | Advertencia | Filas | % |", "|---|---|---|---|"]
    for t in LOAD_ORDER:
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for w in contracts[t].get("warnings", []):
            k = con.execute(f"SELECT count(*) FROM {t} WHERE {w['sql']}").fetchone()[0]
            out.append(f"| {t} | `{w['name']}` | {k:,} | {100 * k / max(n, 1):.1f}% |")

    out += ["", "## Frescura", "", f"Política: alerta si la última partición tiene más de {FRESHNESS_MAX_LAG_DAYS} días de atraso "
            "respecto de la fecha de referencia (`as_of` en `config/policy.yaml`).", "",
            "| Tabla | Última partición |", "|---|---|"]
    for t in LOAD_ORDER:
        pk = contracts[t].get("partition_key")
        if pk:
            out.append(f"| {t} | {con.execute(f'SELECT max({pk}) FROM {t}').fetchone()[0]} |")

    out += ["", "## Nulos en columnas opcionales", "", "| Tabla | Columna | % nulos |", "|---|---|---|"]
    for t in LOAD_ORDER:
        for c, spec in contracts[t]["columns"].items():
            if not spec.get("required"):
                pct = con.execute(f'SELECT 100.0 * count(*) FILTER (WHERE "{c}" IS NULL) / count(*) FROM {t}').fetchone()[0]
                out.append(f"| {t} | {c} | {pct:.1f}% |")

    out += ["", "## Linaje: corridas", "", "| run_id | Tabla | Archivos nuevos | Filas in | Cargadas | Cuarentena | Duplicados en lote |",
            "|---|---|---|---|---|---|---|"]
    for r in runs:
        for t, s in r["tables"].items():
            if s["files_new"]:
                out.append(f"| {r['run_id']} | {t} | {s['files_new']:,} | {s['rows_in']:,} | {s['rows_loaded']:,} | "
                           f"{s['rows_quarantined']:,} | {s.get('duplicates_in_batch', 0):,} |")
    if runs:
        last = runs[-1]
        out += ["", f"Normalizaciones aplicadas: `{last.get('normalizations')}`", "",
                "Huella de la entrega en la última corrida (cambia si el organizador regenera los datos): " +
                ", ".join(f"{t}=`{s.get('source_fingerprint', '-')}`" for t, s in last["tables"].items())]
    con.close()
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "serving.duckdb"))
    ap.add_argument("--out", default=os.path.join(ROOT, "reports", "data_quality.md"))
    a = ap.parse_args()
    md = build(a.db)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
