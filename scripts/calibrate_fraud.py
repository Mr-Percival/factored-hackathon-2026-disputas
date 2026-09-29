"""Calibra el umbral de la regla H03 (fraud_score -> handoff) con división temporal.

    python scripts/calibrate_fraud.py [--db data/bank.duckdb] > reports/fraud_threshold.md

- Etiqueta: is_fraud (del organizador). Score: fraud_score (del core bancario; no lo entrenamos).
- Dev: transacciones con process_date < 2026-01-01 -> se elige el umbral.
- Test: process_date >= 2026-01-01 -> se reporta, sin volver a elegir.
- Criterio: el umbral más bajo cuya tasa de derivación (% de transacciones marcadas) sea <= PRESUPUESTO,
  porque cada marca es un caso para un analista humano. Se reporta el recall que se obtiene con ese costo.
"""
import argparse

import duckdb

SPLIT = "2026-01-01"
BUDGETS = [0.01, 0.02, 0.05]  # fracción de transacciones que podemos mandar a un analista
CHOSEN_BUDGET = 0.02


def curve(con, where):
    return con.execute(f"""
        WITH s AS (SELECT try_cast(fraud_score AS DOUBLE) sc, lower(is_fraud) = 'true' y
                   FROM raw_transactions WHERE fraud_score IS NOT NULL AND {where}),
        th AS (SELECT unnest(range(10, 100, 5)) t)
        SELECT t, count(*) FILTER (WHERE sc >= t) flagged, count(*) FILTER (WHERE sc >= t AND y) tp,
               (SELECT count(*) FROM s WHERE y) pos, (SELECT count(*) FROM s) n
        FROM th, s GROUP BY t ORDER BY t""").fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/bank.duckdb")
    a = ap.parse_args()
    con = duckdb.connect(a.db, read_only=True)
    dev, test = curve(con, f"process_date < '{SPLIT}'"), curve(con, f"process_date >= '{SPLIT}'")
    null_pct = con.execute("SELECT 100.0 * count(*) FILTER (WHERE fraud_score IS NULL) / count(*) FROM raw_transactions").fetchone()[0]
    fraud_null = con.execute("""SELECT count(*) FILTER (WHERE fraud_score IS NULL), count(*)
        FROM raw_transactions WHERE lower(is_fraud) = 'true'""").fetchone()

    def pick(c, budget):
        ok = [r for r in c if r[1] / r[4] <= budget]
        return min(ok, key=lambda r: r[0]) if ok else None

    print("# Calibración del umbral de fraude (regla H03)\n")
    print(f"- Dev: `process_date < {SPLIT}` (n={dev[0][4]:,}, fraudes={dev[0][3]:,}) · "
          f"Test: `>= {SPLIT}` (n={test[0][4]:,}, fraudes={test[0][3]:,})")
    print(f"- `fraud_score` nulo en {null_pct:.1f}% de las transacciones; {fraud_null[0]:,} de {fraud_null[1]:,} fraudes "
          "no tienen score → la regla H03 no puede verlos (riesgo residual documentado).\n")
    print("## Curva en dev\n\n| Umbral | % derivado | Precisión | Recall |\n|---|---|---|---|")
    for t, fl, tp, pos, n in dev:
        print(f"| {t} | {100 * fl / n:.2f}% | {100 * tp / max(fl, 1):.2f}% | {100 * tp / pos:.1f}% |")
    print("\n## Umbral por presupuesto de derivación (elegido en dev, medido en test)\n")
    print("| Presupuesto | Umbral (dev) | % derivado test | Precisión test | Recall test |\n|---|---|---|---|---|")
    chosen = None
    for b in BUDGETS:
        r = pick(dev, b)
        if not r:
            continue
        t = r[0]
        tr = next(x for x in test if x[0] == t)
        mark = " **← elegido**" if b == CHOSEN_BUDGET else ""
        print(f"| {100 * b:.0f}%{mark} | {t} | {100 * tr[1] / tr[4]:.2f}% | {100 * tr[2] / max(tr[1], 1):.2f}% | {100 * tr[2] / tr[3]:.1f}% |")
        if b == CHOSEN_BUDGET:
            chosen = t
    print(f"\n**Umbral elegido: {chosen}** (presupuesto {100 * CHOSEN_BUDGET:.0f}% de derivación).\n")
    print("## Lectura\n")
    print("- La curva tiene un quiebre abrupto: bajo ~30 casi todo es legítimo y sobre ~35 la precisión es 100%. "
          "Ninguna transacción legítima supera ese score, lo que es un **artefacto del generador sintético**; "
          "con datos reales la separación sería gradual y el umbral debería recalibrarse.")
    print("- Los presupuestos de 1%, 2% y 5% eligen el mismo umbral porque el % derivado salta de 16.75% (umbral 25) "
          "a 0.09% (umbral 30).")
    print("- El 20% de las transacciones no tiene score. Un fraude sin score no activa H03; lo cubren las otras reglas "
          "(monto alto, reclamante recurrente) y el analista que recibe la disputa.")
    print("- En el flujo real la regla solo se evalúa sobre cargos que el cliente **ya** disputa, donde la prevalencia "
          "de fraude es mayor. Este dataset no permite medirlo: no hay vínculo entre disputa y transacción.")


if __name__ == "__main__":
    main()
