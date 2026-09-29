"""Carga CSV crudos a una base DuckDB (data/bank.duckdb) como tablas raw_*. Todo como texto-inferido; se registra archivo origen."""
import duckdb, glob, os
con = duckdb.connect("data/bank.duckdb")
for t in sorted(os.listdir("data/raw")):
    name = t.removesuffix(".csv")
    pat = f"data/raw/{t}" if t.endswith(".csv") else f"data/raw/{t}/**/*.csv"
    con.execute(f"""CREATE OR REPLACE TABLE raw_{name} AS
        SELECT * FROM read_csv('{pat}', union_by_name=true, filename=true, all_varchar=true, header=true)""")
    n, c = con.execute(f"SELECT count(*), (SELECT count(*) FROM pragma_table_info('raw_{name}')) FROM raw_{name}").fetchone()
    print(f"{name:28s} rows={n:>9,} cols={c}")
