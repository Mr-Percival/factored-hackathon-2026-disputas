"""Compara dos entregas crudas del organizador (p. ej. data_backup_20260831/ vs data/).

    python scripts/compare_snapshots.py data/raw_backup data/raw > reports/snapshot_diff.md

Por tabla: columnas agregadas/quitadas (evolución de esquema), filas, IDs solo en A / solo en B,
IDs comunes con contenido distinto (qué columnas cambian) y rango de particiones.
"""
import os
import sys

import duckdb

TABLES = {"customers": ("customers.csv", "customer_id", None),
          "products": ("products.csv", "product_id", None),
          "transactions": ("transactions/**/*.csv", "transaction_id", "process_date"),
          "complaints": ("complaints/**/*.csv", "complaint_id", "process_date")}


def load(con, alias, root, pattern):
    path = os.path.join(root, pattern).replace("\\", "/")
    con.execute(f"CREATE OR REPLACE TABLE {alias} AS SELECT * EXCLUDE (filename), filename AS _file "
                f"FROM read_csv('{path}', all_varchar=true, union_by_name=true, filename=true, hive_partitioning=false)")
    return [c for (c,) in con.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{alias}'").fetchall() if c != "_file"]


def main(a_root, b_root):
    con = duckdb.connect()
    print(f"# Diferencias entre entregas\n\n- **A (anterior):** `{a_root}`\n- **B (actual):** `{b_root}`\n")
    for t, (pattern, pk, part) in TABLES.items():
        ca, cb = load(con, "a", a_root, pattern), load(con, "b", b_root, pattern)
        common = [c for c in ca if c in cb and c != pk]
        na, nb = (con.execute(f"SELECT count(*), count(DISTINCT {pk}) FROM {x}").fetchone() for x in ("a", "b"))
        only_a = con.execute(f"SELECT count(*) FROM (SELECT DISTINCT {pk} FROM a EXCEPT SELECT DISTINCT {pk} FROM b)").fetchone()[0]
        only_b = con.execute(f"SELECT count(*) FROM (SELECT DISTINCT {pk} FROM b EXCEPT SELECT DISTINCT {pk} FROM a)").fetchone()[0]
        diff_cols = " OR ".join(f'a."{c}" IS DISTINCT FROM b."{c}"' for c in common)
        changed = con.execute(f"SELECT count(*) FROM a JOIN b USING ({pk}) WHERE {diff_cols}").fetchone()[0]
        per_col = con.execute("SELECT " + ", ".join(
            f'count(*) FILTER (WHERE a."{c}" IS DISTINCT FROM b."{c}") AS "{c}"' for c in common) +
            f" FROM a JOIN b USING ({pk})").df().T.reset_index()
        per_col.columns = ["columna", "filas_distintas"]
        per_col = per_col[per_col.filas_distintas > 0].sort_values("filas_distintas", ascending=False)
        print(f"## {t}\n")
        print("| | A | B |\n|---|---|---|")
        print(f"| filas | {na[0]:,} | {nb[0]:,} |\n| IDs distintos | {na[1]:,} | {nb[1]:,} |")
        if part:
            ra, rb = (con.execute(f"SELECT min({part}), max({part}), count(DISTINCT _file) FROM {x}").fetchone() for x in ("a", "b"))
            print(f"| particiones | {ra[0]} → {ra[1]} ({ra[2]} archivos) | {rb[0]} → {rb[1]} ({rb[2]} archivos) |")
        print(f"\n- Columnas solo en A: {sorted(set(ca) - set(cb)) or '—'}")
        print(f"- Columnas solo en B: {sorted(set(cb) - set(ca)) or '—'}")
        print(f"- IDs solo en A: {only_a:,} · IDs solo en B: {only_b:,} · IDs comunes con contenido distinto: {changed:,}")
        if len(per_col):
            print("\n| columna que cambia | filas |\n|---|---|")
            for _, r in per_col.head(12).iterrows():
                print(f"| {r.columna} | {int(r.filas_distintas):,} |")
        print()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
