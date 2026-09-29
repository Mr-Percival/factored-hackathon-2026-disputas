"""Pipeline raw -> serving.

    python -m bankagent.pipeline --raw data/raw --out data/serving.duckdb [--sample-customers 500]

Tres ideas, nada más:
1. Contrato por tabla (config/contracts.yaml): tipos, obligatorios, dominios, FKs.
   Las filas que violan el contrato van a quarantine_<tabla> con el motivo; no se descartan en silencio.
2. Carga incremental por archivo: el manifiesto guarda qué archivos ya se procesaron.
   Un archivo nuevo (incluida una partición de un día viejo = llegada tardía) se procesa y se hace
   upsert por clave primaria; re-ejecutar el pipeline no duplica nada (idempotente).
3. Lineage: cada corrida escribe reports/runs/<run_id>.json con archivos, filas in/out,
   cuarentena, advertencias y normalizaciones aplicadas.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import uuid

import duckdb
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONTRACTS = os.path.join(ROOT, "config", "contracts.yaml")
LOAD_ORDER = ["customers", "products", "transactions", "complaints"]  # padres antes que hijos (FKs)


def load_contracts(path: str = CONTRACTS) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _file_id(path: str) -> str:
    st = os.stat(path)
    return hashlib.sha1(f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:16]


def _create_table(con, table: str, spec: dict, prefix: str = "", pk: bool = True):
    cols = ", ".join(f'"{c}" {s["type"]}' for c, s in spec["columns"].items())
    key = f', PRIMARY KEY ("{spec["primary_key"]}")' if pk else ""
    con.execute(f"CREATE TABLE IF NOT EXISTS {prefix}{table} ({cols}{key})")


def _staging_select(table: str, spec: dict, norm: dict) -> str:
    """Proyecta, normaliza y castea. try_cast devuelve NULL si falla; el contrato lo detecta."""
    aliases = norm.get("country_aliases", {})
    out = []
    for c, s in spec["columns"].items():
        expr = f'NULLIF(trim("{c}"), \'\')'
        if c.endswith("country") and aliases:
            cases = " ".join(f"WHEN {_sql_str(k)} THEN {_sql_str(v)}" for k, v in aliases.items())
            expr = f"CASE {expr} {cases} ELSE {expr} END"
        if "mask_last" in s:
            n = s["mask_last"]
            expr = f"'****' || right({expr}, {n})"
        out.append(f'try_cast({expr} AS {s["type"]}) AS "{c}"')
        out.append(f'{expr} AS "__raw_{c}"')
    return ", ".join(out)


def _violations(table: str, spec: dict) -> list[tuple[str, str]]:
    """(nombre_check, condición SQL que marca la fila como inválida)."""
    checks = []
    for c, s in spec["columns"].items():
        if s.get("required"):
            checks.append((f"{c}.required", f'"{c}" IS NULL'))
        checks.append((f"{c}.type", f'"{c}" IS NULL AND "__raw_{c}" IS NOT NULL'))
        if "allowed" in s:
            vals = ", ".join(_sql_str(v) for v in s["allowed"])
            checks.append((f"{c}.allowed", f'"{c}" IS NOT NULL AND "{c}" NOT IN ({vals})'))
        if "fk" in s:
            ref_t, ref_c = s["fk"].split(".")
            checks.append((f"{c}.fk", f'"{c}" IS NOT NULL AND "{c}" NOT IN (SELECT "{ref_c}" FROM {ref_t})'))
    return checks


def run(raw_dir: str, out_db: str, sample_customers: int | None = None, contracts_path: str = CONTRACTS) -> dict:
    contracts = load_contracts(contracts_path)
    norm = contracts.pop("normalize", {})
    con = duckdb.connect(out_db)
    con.execute("CREATE TABLE IF NOT EXISTS _processed_files (file_id VARCHAR PRIMARY KEY, path VARCHAR, table_name VARCHAR, run_id VARCHAR)")
    run_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    report = {"run_id": run_id, "started_at": dt.datetime.now().isoformat(), "raw_dir": os.path.abspath(raw_dir),
              "out_db": os.path.abspath(out_db),
              "sample_customers": sample_customers, "normalizations": norm, "tables": {}}

    for table in LOAD_ORDER:
        spec = contracts[table]
        _create_table(con, table, spec)
        _create_table(con, table, spec, prefix="quarantine_", pk=False)
        con.execute(f"ALTER TABLE quarantine_{table} ADD COLUMN IF NOT EXISTS _failed_checks VARCHAR")
        con.execute(f"ALTER TABLE quarantine_{table} ADD COLUMN IF NOT EXISTS _run_id VARCHAR")

        files = sorted(glob.glob(os.path.join(raw_dir, spec["source"]), recursive=True))
        # Huella de la entrega: si el organizador regenera los datos (ya pasó: ver reports/snapshot_diff.md),
        # cambia la huella y cualquier artefacto que referencie IDs (casos de eval, guion de demo) debe regenerarse.
        fingerprint = hashlib.sha256("\n".join(
            f"{os.path.relpath(f, raw_dir).replace(os.sep, '/')}|{os.path.getsize(f)}" for f in files).encode()).hexdigest()[:16]
        done = {r[0] for r in con.execute("SELECT file_id FROM _processed_files WHERE table_name = ?", [table]).fetchall()}
        new_files = [f for f in files if _file_id(f) not in done]
        stats = {"files_total": len(files), "files_new": len(new_files), "source_fingerprint": fingerprint,
                 "rows_in": 0, "rows_loaded": 0,
                 "rows_quarantined": 0, "failed_checks": {}, "warnings": {}}
        if not new_files:
            report["tables"][table] = stats
            continue

        file_list = "[" + ", ".join(_sql_str(f.replace("\\", "/")) for f in new_files) + "]"
        con.execute(f"""CREATE OR REPLACE TEMP TABLE _stg AS
            SELECT {_staging_select(table, spec, norm)}
            FROM read_csv({file_list}, all_varchar=true, header=true, union_by_name=true, hive_partitioning=false)""")
        if sample_customers and table == "customers":
            con.execute(f"DELETE FROM _stg WHERE customer_id NOT IN (SELECT customer_id FROM _stg ORDER BY hash(customer_id) LIMIT {int(sample_customers)})")
        elif sample_customers and "customer_id" in spec["columns"]:
            con.execute("DELETE FROM _stg WHERE customer_id NOT IN (SELECT customer_id FROM customers)")
        stats["rows_in"] = con.execute("SELECT count(*) FROM _stg").fetchone()[0]

        checks = _violations(table, spec)
        fail_expr = "concat_ws(',', " + ", ".join(f"CASE WHEN {cond} THEN {_sql_str(name)} END" for name, cond in checks) + ")"
        con.execute(f"ALTER TABLE _stg ADD COLUMN _failed VARCHAR")
        con.execute(f"UPDATE _stg SET _failed = NULLIF({fail_expr}, '')")
        for name, n in con.execute("SELECT c, count(*) FROM (SELECT unnest(string_split(_failed, ',')) c FROM _stg WHERE _failed IS NOT NULL) GROUP BY 1").fetchall():
            stats["failed_checks"][name] = n

        cols = ", ".join(f'"{c}"' for c in spec["columns"])
        con.execute(f"INSERT INTO quarantine_{table} SELECT {cols}, _failed, {_sql_str(run_id)} FROM _stg WHERE _failed IS NOT NULL")
        stats["rows_quarantined"] = con.execute("SELECT count(*) FROM _stg WHERE _failed IS NOT NULL").fetchone()[0]

        # Duplicados dentro del lote: gana la versión más reciente (updated_at o partición), luego la última leída.
        order = spec.get("updated_at") or spec.get("partition_key")
        order_sql = f'"{order}" DESC NULLS LAST' if order else "1"
        pk = spec["primary_key"]
        con.execute(f"""INSERT OR REPLACE INTO {table}
            SELECT {cols} FROM _stg WHERE _failed IS NULL
            QUALIFY row_number() OVER (PARTITION BY "{pk}" ORDER BY {order_sql}) = 1""")
        stats["rows_loaded"] = stats["rows_in"] - stats["rows_quarantined"]
        stats["duplicates_in_batch"] = con.execute(f'SELECT count(*) - count(DISTINCT "{pk}") FROM _stg WHERE _failed IS NULL').fetchone()[0]

        for w in spec.get("warnings", []):
            stats["warnings"][w["name"]] = con.execute(f"SELECT count(*) FROM _stg WHERE _failed IS NULL AND ({w['sql']})").fetchone()[0]

        con.executemany("INSERT OR IGNORE INTO _processed_files VALUES (?, ?, ?, ?)",
                        [(_file_id(f), f, table, run_id) for f in new_files])
        stats["rows_total_after"] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if spec.get("partition_key"):
            stats["max_partition"] = str(con.execute(f'SELECT max("{spec["partition_key"]}") FROM {table}').fetchone()[0])
        report["tables"][table] = stats

    report["finished_at"] = dt.datetime.now().isoformat()
    con.close()
    runs_dir = os.path.join(os.path.dirname(os.path.abspath(out_db)), "runs")
    os.makedirs(runs_dir, exist_ok=True)
    with open(os.path.join(runs_dir, f"{run_id}.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=os.path.join(ROOT, "data", "raw"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "serving.duckdb"))
    ap.add_argument("--sample-customers", type=int, default=None)
    a = ap.parse_args()
    rep = run(a.raw, a.out, a.sample_customers)
    for t, s in rep["tables"].items():
        print(f"{t:14s} new_files={s['files_new']:5d} in={s['rows_in']:>9,} loaded={s['rows_loaded']:>9,} "
              f"quarantined={s['rows_quarantined']:>6,} warnings={s['warnings']}")
    print("run:", rep["run_id"])


if __name__ == "__main__":
    main()
