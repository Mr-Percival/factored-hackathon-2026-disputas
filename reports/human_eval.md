# Evaluación humana de paquetes de handoff

Generado por `python -m bankagent.evals.human_kit score`. Rúbrica e instrucciones: [`evals/human/RUBRIC.md`](../evals/human/RUBRIC.md). Clave: `evals/human/_key/answer_key.json` (semilla 11, política `2026-09-29.1`, base `demo.duckdb`).

Método: medias con IC 95% por bootstrap remuestreando paquetes (2000 réplicas); acuerdo con α de Krippendorff ordinal para (a)–(d) y κ de Fleiss / Cohen para (e), solo sobre paquetes reales. Umbrales de α: ≥ 0.80 fiable, ≥ 0.667 provisional. Los controles son copias degradadas de paquetes reales (sin hechos, regla equivocada, sin preguntas, sin pedido, monto inconsistente) y miden la atención de cada evaluador.

## Resultados reales

**Pendiente:** las planillas (4) todavía no tienen calificaciones. Este reporte se regenera al correr `score` con las planillas completas.

## ⚠️ Dry run: calificaciones SINTÉTICAS (no son resultados)

> Generadas al azar por `dry_run_ratings` (semilla 7) con 4 evaluadores ficticios de atención distinta, solo para probar el pipeline de punta a punta. **No citar estos números como evaluación.**

### Simulación

Evaluadores: **4** (A, B, C, D) · paquetes calificados: **35** de 35 (30 reales + 5 controles) · calificaciones: 140.

**Medias por ítem (paquetes reales; IC 95% bootstrap por paquete)**

| Ítem | n | Media | IC 95% | % ≥ 4 | Acuerdo α ordinal |
|---|---|---|---|---|---|
| (a) Entiendo qué pide el cliente sin volver a preguntar | 120 | 4.18 | [4.02, 4.35] | 85% | 0.207 (insuficiente) |
| (b) Los hechos verificados son suficientes y correctos para decidir | 120 | 3.95 | [3.75, 4.17] | 72% | 0.400 (insuficiente) |
| (c) Está claro por qué se derivó (regla) | 120 | 4.23 | [4.08, 4.40] | 85% | 0.217 (insuficiente) |
| (d) Las preguntas abiertas son útiles/accionables | 120 | 3.24 | [3.08, 3.43] | 36% | 0.162 (insuficiente) |

**(e) Falta algo crítico:** 12% de 120 respuestas dicen que sí. Acuerdo: κ de Fleiss -0.041 (n=30 paquetes con todos los evaluadores), κ de Cohen medio por pares -0.033, α nominal -0.033.

**Ítems más débiles:** (d) Las preguntas abiertas son útiles/accionables (3.24), (b) Los hechos verificados son suficientes y correctos para decidir (3.95)

**Por motivo de handoff (medias)**

| Motivo | Paquetes | (a) | (b) | (c) | (d) | (e) % falta |
|---|---|---|---|---|---|---|
| `H01_customer_not_active` | 5 | 4.00 | 3.75 | 3.90 | 3.05 | 10% |
| `H02_high_amount` | 7 | 4.29 | 4.21 | 4.46 | 3.36 | 14% |
| `H03_fraud_signal` | 2 | 4.12 | 4.12 | 4.25 | 3.62 | 0% |
| `H04_repeat_complainer` | 4 | 4.31 | 4.19 | 4.56 | 3.50 | 25% |
| `action_not_verified` | 2 | 4.38 | 4.25 | 4.88 | 3.62 | 0% |
| `no_active_card` | 2 | 4.12 | 3.75 | 3.88 | 3.00 | 0% |
| `out_of_scope` | 3 | 4.50 | 3.58 | 4.08 | 3.00 | 25% |
| `security_lockout` | 2 | 3.75 | 3.62 | 4.00 | 3.00 | 0% |
| `tool_failure` | 3 | 4.00 | 3.75 | 3.92 | 3.00 | 17% |

**Controles de atención:** tasa de detección 70% (detectado = ítem objetivo ≤ 2 o marcó que falta algo crítico). Por evaluador: A 60%, B 80%, C 60%, D 80%.

- `P05` · defecto `sin_hechos` (ítem b_hechos): 3/4
- `P07` · defecto `monto_inconsistente` (ítem b_hechos): 3/4
- `P12` · defecto `regla_equivocada` (ítem c_motivo): 2/4
- `P29` · defecto `sin_preguntas` (ítem d_preguntas): 4/4
- `P34` · defecto `sin_pedido` (ítem a_pedido): 2/4

**Paquetes reales peor calificados**

- `P17` `H01_customer_not_active`: media 3.19, ítem más bajo d_preguntas, 0/4 marcan que falta algo. sin comentarios
- `P18` `H01_customer_not_active`: media 3.19, ítem más bajo d_preguntas, 1/4 marcan que falta algo. “(sintético) comentario de prueba”
- `P32` `security_lockout`: media 3.31, ítem más bajo b_hechos, 0/4 marcan que falta algo. sin comentarios
- `P10` `tool_failure`: media 3.38, ítem más bajo d_preguntas, 1/4 marcan que falta algo. “(sintético) comentario de prueba”
- `P13` `H02_high_amount`: media 3.44, ítem más bajo a_pedido, 0/4 marcan que falta algo. sin comentarios

**Humanos vs. verificador determinista** (mayoría de (e) vs. `check`; n=35): acuerdo 94% · ambos completo 30 · ambos incompleto 3 · solo humanos marcan 0 · solo verificador marca 2.

