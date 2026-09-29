"""Kit de evaluación humana de handoffs (#32): estadísticos de acuerdo, build, planillas ciegas, score y completitud.
Todo sobre el FIXTURE (sin datos reales ni red)."""
import copy
import csv
import glob
import json
import os

import pytest

from bankagent.evals import agreement as ag
from bankagent.evals import human_kit as hk
from bankagent.evals.completeness import check_packet, is_complete
from bankagent.policy import PolicyEngine
from bankagent.responses import handoff_summary

N = None


# ------------------------------------------------------------------ acuerdo: valores calculados a mano / publicados
def test_krippendorff_alpha_hand_computed_toy():
    # 2 evaluadores, 3 unidades: (1,1) (2,3) (3,3). Coincidencias o11=2, o23=o32=1, o33=2; n1=2, n2=1, n3=3, n=6.
    # Ordinal: δ²(1,2)=2.25, δ²(1,3)=12.25, δ²(2,3)=4 -> Do=8/6, De=180/30=6 -> α = 1 - (8/6)/6 = 7/9.
    # Nominal: Do=2/6, De=2·(2+6+3)/30=22/30 -> α = 1 - (1/3)/(22/30) = 6/11.
    units = [(1, 1), (2, 3), (3, 3)]
    assert ag.krippendorff_alpha(units, "ordinal") == pytest.approx(7 / 9)
    assert ag.krippendorff_alpha(units, "nominal") == pytest.approx(6 / 11)


def test_krippendorff_alpha_published_example_with_missing_data():
    # Krippendorff (2011), "Computing Krippendorff's Alpha-Reliability": 4 observadores, 12 unidades, faltantes.
    a = [1, 2, 3, 3, 2, 1, 4, 1, 2, N, N, N]
    b = [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, N, 3]
    c = [N, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, N]
    d = [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, N]
    units = list(zip(a, b, c, d))
    assert ag.krippendorff_alpha(units, "nominal") == pytest.approx(0.743, abs=5e-4)
    assert ag.krippendorff_alpha(units, "ordinal") == pytest.approx(0.815, abs=5e-4)
    assert ag.krippendorff_alpha(units, "interval") == pytest.approx(0.849, abs=5e-4)
    assert ag.krippendorff_alpha([(3, 3), (3, 3)], "ordinal") is None  # sin variación: no computable


def test_fleiss_and_cohen_kappa():
    # Ejemplo clásico de Fleiss (10 sujetos, 14 evaluadores, 5 categorías): κ = 0.210
    table = [[0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6], [0, 3, 9, 2, 0], [2, 2, 8, 1, 1],
             [7, 7, 0, 0, 0], [3, 2, 6, 3, 0], [2, 5, 3, 2, 2], [6, 5, 2, 1, 0], [0, 2, 2, 3, 7]]
    assert ag.fleiss_kappa(table) == pytest.approx(0.210, abs=5e-4)
    # Cohen a mano: po = 4/6, pe = .5·.5 + .5·.5 = .5 -> κ = (2/3 - 1/2) / (1/2) = 1/3
    assert ag.cohen_kappa([1, 1, 0, 0, 1, 0], [1, 0, 0, 0, 1, 1]) == pytest.approx(1 / 3)
    assert ag.mean_pairwise_cohen({"A": {"p1": 1, "p2": 0}, "B": {"p1": 1, "p2": 0}}) == pytest.approx(1.0)


def test_bootstrap_ci_is_deterministic_and_contains_mean():
    groups = [[4, 5], [3, 3], [5, 4], [2, 3]]
    m, lo, hi = ag.bootstrap_mean_ci(groups, seed=1)
    assert m == pytest.approx(29 / 8) and lo <= m <= hi
    assert ag.bootstrap_mean_ci(groups, seed=1) == (m, lo, hi)


# ------------------------------------------------------------------ build sobre el fixture
@pytest.fixture(scope="module")
def kit(serving_db, tmp_path_factory):
    out = tmp_path_factory.mktemp("kit")
    return hk.build(serving_db, n=10, seed=3, n_controls=3, out=str(out), log=lambda *_: None), out


def test_kit_builds_cards_sheets_and_key(kit):
    k, out = kit
    kp = k["key"]["packets"]
    assert len(kp) == 13 and sum(v["is_control"] for v in kp.values()) == 3
    reasons = {v["reason"] for v in kp.values() if not v["is_control"]}
    # el fixture no tiene clientes sin tarjeta activa; el resto de los motivos debe aparecer
    assert {"out_of_scope", "tool_failure", "security_lockout", "action_not_verified"} <= reasons
    assert sum(v["reason"].startswith("H0") for v in kp.values()) >= 4  # H01–H04 (algunos usados como controles)
    assert {v["lang"] for v in kp.values()} == {"es", "pt"}
    for pid in kp:
        assert os.path.exists(out / "packets" / f"{pid}.md")
    assert sorted(g["packet_id"] for g in json.load(open(out / "packets" / "packets.json", encoding="utf-8"))) == sorted(kp)
    # los reales son completos para el verificador; los controles no
    assert all(v["deterministic_complete"] != v["is_control"] for v in kp.values())


def test_controls_are_blind_in_sheets_cards_and_bundles(kit):
    k, out = kit
    kp = k["key"]["packets"]
    for rater in hk.RATERS:
        with open(out / "sheets" / f"rater_{rater}.csv", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        assert tuple(rows[0].keys()) == hk.SHEET_COLUMNS  # ninguna columna delata controles ni motivo
        assert sorted(r["packet_id"] for r in rows) == sorted(kp)  # controles incluidos, una vez cada uno
        assert all(r[c] == "" for r in rows for c in hk.SHEET_COLUMNS[3:])
    visible = glob.glob(str(out / "sheets" / "*")) + glob.glob(str(out / "bundles" / "*")) + \
        glob.glob(str(out / "packets" / "*"))
    for path in visible:
        text = open(path, encoding="utf-8-sig").read().lower()
        for leak in ("control", "defect", "sin_hechos", "regla_equivocada", "sin_preguntas", "is_control"):
            assert leak not in text, (path, leak)
    assert not any("_key" in p for p in visible)


def test_order_is_randomized_per_rater_and_reproducible(kit, serving_db, tmp_path):
    k, _ = kit
    orders = k["orders"]
    assert len({tuple(o) for o in orders.values()}) == len(hk.RATERS)
    assert all(sorted(o) == sorted(orders["A"]) for o in orders.values())
    again = hk.build(serving_db, n=10, seed=3, n_controls=3, out=str(tmp_path), log=lambda *_: None)
    assert again["orders"] == orders
    assert {p: v["reason"] for p, v in again["key"]["packets"].items()} == {p: v["reason"] for p, v in k["key"]["packets"].items()}


# ------------------------------------------------------------------ score
def _fill(out, key, rater, fn):
    path = out / "sheets" / f"rater_{rater}.csv"
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r.update(fn(r["packet_id"], key["packets"][r["packet_id"]]))
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=hk.SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return str(path)


def test_score_pending_then_real_ratings(kit, tmp_path):
    k, out = kit
    key_path = str(out / "_key" / "answer_key.json")
    sheets = sorted(glob.glob(str(out / "sheets" / "*.csv")))
    text = hk.score(sheets, key_path, out=str(tmp_path / "empty.md"), dry_run=True)
    assert "**Pendiente:**" in text and "SINTÉTICAS (no son resultados)" in text

    def attentive(pid, v):  # detecta todos los controles
        r = {it: "4" for it in hk.ORDINAL_ITEMS} | {"e_falta_critico": "no"}
        if v["is_control"]:
            r[v["target_item"]], r["e_falta_critico"], r["e_que_falta"] = "1", "sí", "faltan datos"
        return r

    def careless(pid, v):  # pone 5 a todo
        return {it: "5" for it in hk.ORDINAL_ITEMS} | {"e_falta_critico": "no"}

    key = k["key"]
    paths = [_fill(out, key, "A", attentive), _fill(out, key, "B", careless)]
    m = hk.analyze(hk.read_sheets(paths)[0], key)
    assert m["n_raters"] == 2 and m["n_packets_real"] == 10 and m["n_ratings"] == 26
    assert m["controls"]["by_rater"] == {"A": 1.0, "B": 0.0} and m["controls"]["rate"] == 0.5
    assert m["items"]["a_pedido"]["mean"] == pytest.approx(4.5)  # controles excluidos de las medias
    assert m["vs_checker"]["n"] == 13
    text = hk.score(paths, key_path, out=str(tmp_path / "r.md"))
    assert "## Resultados reales" in text and "Dry run" not in text and "B 0%" in text


def test_read_sheets_flags_bad_values(tmp_path):
    p = tmp_path / "rater_Z.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(hk.SHEET_COLUMNS)
        w.writerow(["Z", 1, "P01", "7", "3", "", "", "tal vez", ""])
        w.writerow(["Z", 2, "P02", "", "", "", "", "", ""])  # sin calificar: se ignora
    rows, warns = hk.read_sheets([str(p)])
    assert len(rows) == 1 and rows[0]["a_pedido"] is None and rows[0]["b_hechos"] == 3
    assert len(warns) == 2


# ------------------------------------------------------------------ completitud y resumen
def _handoff(env, customer, text):
    return env.agent.chat(env.thread(), env.login(customer), text)["handoff"]


def test_completeness_checker_accepts_real_and_rejects_degraded(env):
    policy = PolicyEngine()
    p = _handoff(env, "CLI-ANA", "no reconozco el cargo de 1200 del 10/06/2026")
    assert p["reason"] == "H02_high_amount" and is_complete(p, policy)
    assert is_complete({**p, "priority": "alta", "reference_id": "HO-1"}, policy)  # campos nuevos (#44) no rompen
    expected = {"sin_hechos": "hechos_transaccion", "regla_equivocada": "reglas_reproducibles",
                "sin_preguntas": "preguntas_no_vacias", "sin_pedido": "pedido_no_vacio",
                "monto_inconsistente": "reglas_reproducibles"}
    for defect, check in expected.items():
        bad = hk._degrade(p, defect, policy)
        failed = [c for c, ok, _ in check_packet(bad, policy) if not ok]
        assert check in failed, (defect, failed)
    q = copy.deepcopy(p)
    del q["summary"]
    assert "campos_presentes" in [c for c, ok, _ in check_packet(q, policy) if not ok]
    oos = _handoff(env, "CLI-ANA", "quiero un préstamo hipotecario")
    assert is_complete(oos, policy)  # sin transacción es correcto para fuera de alcance


def test_handoff_summary_is_deterministic_one_line(env):
    p = _handoff(env, "CLI-BETO", "no reconozco un cargo de 200.000")
    assert p["summary"] == handoff_summary(p) and "\n" not in p["summary"]
    assert p["summary"].startswith("H04_repeat_complainer:") and "T-BETO-1" in p["summary"]
    assert "reclamante recurrente" in p["summary"] and "Acciones: ninguna" in p["summary"]
    oos = _handoff(env, "CLI-ANA", "quiero un préstamo hipotecario")
    assert "Sin transacción identificada" in oos["summary"]


def test_check_writes_report(kit, serving_db, tmp_path):
    k, out = kit
    res = hk.check(None, packets_json=str(out / "packets" / "packets.json"),
                   key_path=str(out / "_key" / "answer_key.json"), out=str(tmp_path / "c.md"))
    assert res["kit humano: paquetes reales"] == (10, 10)
    assert res["kit humano: controles degradados (se esperan incompletos)"] == (0, 3)
    text = open(tmp_path / "c.md", encoding="utf-8").read()
    assert "| kit humano: paquetes reales | 10 | 10 | 100.0% |" in text
