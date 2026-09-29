"""Contratos, cuarentena, normalización, idempotencia y llegadas tardías (sobre el FIXTURE de prueba)."""
import duckdb

from bankagent import pipeline
from fixture_data import write_fixture, write_late_batch


def _q(db, sql):
    con = duckdb.connect(db, read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_contract_quarantines_invalid_rows(serving_db):
    q = dict(_q(serving_db, "SELECT customer_id, _failed_checks FROM quarantine_customers"))
    assert q == {"CLI-BAD": "segment.allowed"}
    assert _q(serving_db, "SELECT product_id, _failed_checks FROM quarantine_products") == [("PRD-ORPHAN", "customer_id.fk")]
    assert _q(serving_db, "SELECT transaction_id, _failed_checks FROM quarantine_transactions") == [("T-BAD-1", "amount.required,amount.type")]


def test_normalization_and_masking(serving_db):
    assert _q(serving_db, "SELECT country FROM customers WHERE customer_id = 'CLI-ANA'") == [("México",)]
    numbers = [r[0] for r in _q(serving_db, "SELECT product_number FROM products")]
    assert all(n.startswith("****") and len(n) == 8 for n in numbers)


def test_pii_columns_not_loaded(serving_db):
    cols = {r[0] for r in _q(serving_db, "SELECT column_name FROM information_schema.columns WHERE table_name = 'customers'")}
    assert "document_number" not in cols


def test_rerun_is_idempotent_and_late_arrivals_upsert(tmp_path):
    raw, db = tmp_path / "raw", str(tmp_path / "s.duckdb")
    write_fixture(str(raw))
    first = pipeline.run(str(raw), db)
    n1 = _q(db, "SELECT count(*) FROM transactions")[0][0]

    again = pipeline.run(str(raw), db)  # sin archivos nuevos: no cambia nada
    assert again["tables"]["transactions"]["files_new"] == 0
    assert _q(db, "SELECT count(*) FROM transactions")[0][0] == n1

    write_late_batch(str(raw))  # llegada tardía + nueva versión de T-ANA-1
    late = pipeline.run(str(raw), db)
    assert late["tables"]["transactions"]["files_new"] == 1
    assert _q(db, "SELECT count(*) FROM transactions")[0][0] == n1 + 1  # solo T-ANA-10 es nueva
    assert _q(db, "SELECT transaction_status FROM transactions WHERE transaction_id = 'T-ANA-1'") == [("Reversed",)]
    assert first["tables"]["transactions"]["warnings"]["mexico_without_mxn"] > 0


def test_quality_report_covers_quarantine_warnings_and_lineage(serving_db):
    from bankagent.quality_report import build
    md = build(serving_db)
    assert "segment.allowed" in md and "customer_id.fk" in md      # cuarentena
    assert "mexico_without_mxn" in md                               # advertencias
    assert "| customers | 1 |" in md.replace(",", "")               # linaje: 1 archivo nuevo de customers


def test_include_customers_forces_ids_into_the_sample(tmp_path):
    """--include-customers: los IDs forzados entran siempre; la muestra por hash no cambia; hijos filtrados por FK."""
    raw = tmp_path / "raw"
    write_fixture(str(raw))
    base = str(tmp_path / "base.duckdb")
    pipeline.run(str(raw), base, sample_customers=1)
    sampled = {r[0] for r in _q(base, "SELECT customer_id FROM customers")}
    assert len(sampled) == 1
    forced = next(c for c in ("CLI-BETO", "CLI-CARLA") if c not in sampled)

    db = str(tmp_path / "demo.duckdb")
    rep = pipeline.run(str(raw), db, sample_customers=1, include_customers=[forced, "CLI-NO-EXISTE"])
    assert {r[0] for r in _q(db, "SELECT customer_id FROM customers")} == sampled | {forced}
    assert rep["include_customers"] == {"requested": 2, "found": 1}
    owners = {r[0] for r in _q(db, "SELECT customer_id FROM transactions UNION SELECT customer_id FROM products")}
    assert owners <= sampled | {forced} and forced in owners

    only = str(tmp_path / "only.duckdb")  # sin muestra: solo los forzados
    pipeline.run(str(raw), only, include_customers=["CLI-ANA"])
    assert _q(only, "SELECT customer_id FROM customers") == [("CLI-ANA",)]
    assert _q(only, "SELECT DISTINCT customer_id FROM transactions") == [("CLI-ANA",)]


def test_read_customer_ids_txt_and_json(tmp_path):
    txt = tmp_path / "ids.txt"
    txt.write_text("# demo\nCLI-ANA\n\nCLI-BETO  # recurrente\n", encoding="utf-8")
    assert pipeline.read_customer_ids(str(txt)) == ["CLI-ANA", "CLI-BETO"]
    js = tmp_path / "demo.json"
    js.write_text('{"customer_ids": ["CLI-ANA"], "scenarios": []}', encoding="utf-8")
    assert pipeline.read_customer_ids(str(js)) == ["CLI-ANA"]


def test_lookup_indexes_exist_and_survive_incremental_runs(tmp_path):
    raw, db = tmp_path / "raw", str(tmp_path / "s.duckdb")
    write_fixture(str(raw))
    pipeline.run(str(raw), db)
    write_late_batch(str(raw))  # upsert sobre tablas con índice
    pipeline.run(str(raw), db)
    idx = {r[0] for r in _q(db, "SELECT index_name FROM duckdb_indexes()")}
    assert idx == {f"idx_{t}_{c}" for t, c in pipeline.LOOKUP_INDEXES.items()}
    assert _q(db, "SELECT count(*) FROM transactions WHERE customer_id = 'CLI-ANA' AND transaction_id = 'T-ANA-10'") == [(1,)]
