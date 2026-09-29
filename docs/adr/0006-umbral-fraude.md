# 0006 · Umbral de `fraud_score` para derivar a un analista (regla H03)

- **Estado:** aceptada
- **Fecha:** 2026-09-29

## Contexto
H03 manda a un analista humano las disputas cuyo `fraud_score` (score del core bancario, no entrenado por nosotros) supera un umbral. El valor provisional era 60, elegido sin datos. El EDA mostró que `fraud_score` separa bien (AUC ≈ 0.85) y que el resto de las variables no aporta señal.

## Decisión
**Umbral = 30**, elegido en dev (`process_date < 2026-01-01`) y medido una sola vez en test (2026), con el criterio "el umbral más bajo cuyo % derivado sea ≤ 2%". Cada marca es trabajo para un analista, así que el costo es el límite.

| Split | % derivado | Precisión | Recall |
|---|---|---|---|
| Test (n=548,431; 479 fraudes) | 0.08% | 79.0% | 72.4% |

Con 60, el recall en dev era 38.9%. Detalle y curva completa: [`reports/fraud_threshold.md`](../../reports/fraud_threshold.md) (`python scripts/calibrate_fraud.py`).

## Alternativas consideradas
| Opción | A favor | En contra |
|---|---|---|
| 60 (provisional) | Menos derivaciones | Pierde 6 de cada 10 fraudes con score |
| 25 | Recall 73.7% | Deriva el 16.75% de las transacciones: inviable |
| Modelo propio de fraude | "Componente aprendido" | Ninguna otra variable tiene señal (ADR 0003); no mejoraría al score existente |
| **30** | Mejor recall con costo mínimo | Depende de un quiebre artificial del generador sintético |

## Consecuencias
- La separación perfecta sobre ~35 es un artefacto sintético; con datos reales hay que recalibrar con el mismo script.
- Un 20% de las transacciones no tiene score (891 de 4,316 fraudes). H03 no los ve; los cubren H02/H04 y el analista que recibe la disputa.
- No se pudo medir la prevalencia de fraude *entre cargos disputados*, que es la población real de la regla, porque el dataset no vincula quejas con transacciones.
