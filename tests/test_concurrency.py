"""Concurrencia: un mismo BankTools atendido por varios hilos (como un proceso del servicio).

Regresión del hallazgo de la prueba de carga (#19): con UNA conexión DuckDB compartida, un hilo podía
leer el resultado de la consulta de otro hilo (filas de OTRO cliente) o fallar con KeyError.
"""
import threading

import duckdb


def test_concurrent_reads_never_mix_customers(env, serving_db):
    con = duckdb.connect(serving_db, read_only=True)
    owned = {c: {r[0] for r in con.execute("SELECT transaction_id FROM transactions WHERE customer_id = ?", [c]).fetchall()}
             for c in ("CLI-ANA", "CLI-BETO", "CLI-CANARY")}
    con.close()
    tokens = {c: env.login(c) for c in owned}
    errors: list[str] = []

    def worker(cid: str):
        try:
            for _ in range(150):
                rows = env.tools.search_transactions(tokens[cid], limit=20)
                leaked = {r["transaction_id"] for r in rows} - owned[cid]
                if leaked:
                    errors.append(f"{cid} recibió {sorted(leaked)}")
                if env.tools.get_profile(tokens[cid])["customer_id"] != cid:
                    errors.append(f"{cid} recibió otro perfil")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{cid}: {type(e).__name__}: {e}")

    threads = [threading.Thread(target=worker, args=(c,)) for c in owned for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[:5]


def test_concurrent_conversations_complete(env):
    results: list[str] = []

    def worker():
        tok, th = env.login("CLI-ANA"), env.thread()
        r = env.agent.chat(th, tok, "quiero bloquear mi tarjeta")
        results.append(r["outcome"])

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == ["clarify"] * 8


def test_fork_ops_isolates_actions_per_demo_session(env):
    """Solo demo web: cada fork escribe en su schema; el almacén por defecto no cambia de comportamiento."""
    import pytest

    tok = env.login("CLI-ANA")
    a, b = env.tools.fork_ops("s_a"), env.tools.fork_ops("s_b")
    assert a.open_dispute(tok, "T-ANA-8", "x", confirmed=True)["verified"]
    assert a.dispute_history(tok)["open_dispute_transactions"] == ["T-ANA-8"]
    assert b.dispute_history(tok)["open_dispute_transactions"] == []
    assert env.tools.dispute_history(tok)["open_dispute_transactions"] == []
    assert env.tools._ops.execute("SELECT count(*) FROM disputes").fetchone()[0] == 0
    a.drop_ops()
    assert env.tools._ops.execute("SELECT count(*) FROM information_schema.schemata WHERE schema_name = 's_a'").fetchone()[0] == 0
    with pytest.raises(ValueError):
        env.tools.fork_ops("x; DROP TABLE disputes")
    with pytest.raises(ValueError):
        env.tools.drop_ops()
