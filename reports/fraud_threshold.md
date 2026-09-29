# Calibración del umbral de fraude (regla H03)

- Dev: `process_date < 2026-01-01` (n=2,991,420, fraudes=2,946) · Test: `>= 2026-01-01` (n=548,431, fraudes=479)
- `fraud_score` nulo en 20.0% de las transacciones; 891 de 4,316 fraudes no tienen score → la regla H03 no puede verlos (riesgo residual documentado).

## Curva en dev

| Umbral | % derivado | Precisión | Recall |
|---|---|---|---|
| 10 | 66.67% | 0.13% | 90.5% |
| 15 | 50.04% | 0.17% | 84.8% |
| 20 | 33.36% | 0.23% | 79.2% |
| 25 | 16.75% | 0.43% | 73.7% |
| 30 | 0.09% | 79.67% | 68.8% |
| 35 | 0.06% | 100.00% | 63.5% |
| 40 | 0.06% | 100.00% | 58.1% |
| 45 | 0.05% | 100.00% | 52.7% |
| 50 | 0.05% | 100.00% | 48.1% |
| 55 | 0.04% | 100.00% | 43.4% |
| 60 | 0.04% | 100.00% | 38.9% |
| 65 | 0.03% | 100.00% | 34.3% |
| 70 | 0.03% | 100.00% | 29.1% |
| 75 | 0.02% | 100.00% | 25.0% |
| 80 | 0.02% | 100.00% | 19.4% |
| 85 | 0.01% | 100.00% | 14.5% |
| 90 | 0.01% | 100.00% | 9.8% |
| 95 | 0.01% | 100.00% | 5.3% |

## Umbral por presupuesto de derivación (elegido en dev, medido en test)

| Presupuesto | Umbral (dev) | % derivado test | Precisión test | Recall test |
|---|---|---|---|---|
| 1% | 30 | 0.08% | 79.04% | 72.4% |
| 2% **← elegido** | 30 | 0.08% | 79.04% | 72.4% |
| 5% | 30 | 0.08% | 79.04% | 72.4% |

**Umbral elegido: 30** (presupuesto 2% de derivación).

## Lectura

- La curva tiene un quiebre abrupto: bajo ~30 casi todo es legítimo y sobre ~35 la precisión es 100%. Ninguna transacción legítima supera ese score, lo que es un **artefacto del generador sintético**; con datos reales la separación sería gradual y el umbral debería recalibrarse.
- Los presupuestos de 1%, 2% y 5% eligen el mismo umbral porque el % derivado salta de 16.75% (umbral 25) a 0.09% (umbral 30).
- El 20% de las transacciones no tiene score. Un fraude sin score no activa H03; lo cubren las otras reglas (monto alto, reclamante recurrente) y el analista que recibe la disputa.
- En el flujo real la regla solo se evalúa sobre cargos que el cliente **ya** disputa, donde la prevalencia de fraude es mayor. Este dataset no permite medirlo: no hay vínculo entre disputa y transacción.
