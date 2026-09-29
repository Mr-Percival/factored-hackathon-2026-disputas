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
