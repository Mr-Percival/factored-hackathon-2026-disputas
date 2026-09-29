# Hoja de una página para la final

> Imprimir o tener abierta. Respuestas largas: [`qa.md`](qa.md). Todo número de acá sale del archivo citado.

## El pitch en 3 frases
1. Disputar un cargo es el peor momento del servicio: las quejas se resuelven al primer contacto solo el 43.6% de las
   veces, y cargo no reconocido + cobro indebido son el 36.5% de los PQR.
2. Construimos un agente en español y portugués que encuentra el cargo, aplica una política versionada, pide
   confirmación por acción, abre la disputa y bloquea la tarjeta solo si la verificación lo confirma, y si no, pasa el
   caso a un humano con el paquete completo.
3. **El modelo interpreta; el código decide y actúa**: por eso, en el test congelado, 0/115 resultados inseguros
   contra 82/115 de automatizar sin política.

## Arquitectura en 30 segundos
Un solo agente en LangGraph con pasos declarados: **guard** (normaliza, detecta inyección, enmascara PII) →
**entender** (router de intención aprendido local de 0.2 MB que se abstiene si duda; montos, fechas y el "sí" los leen
reglas) → **buscar** la transacción (pregunta si hay varias) → **decidir** con `policy.yaml` (reglas con ID) →
**actuar** con confirmación y verificación, o **handoff** → **responder** con plantillas es/pt. Las herramientas
sacan el cliente del token de sesión, nunca del texto. El LLM (router y writer) está implementado detrás de las mismas
interfaces, pero apagado. Diagrama: `docs/pitch/charts/arq_4_capas.png` · grafo: `docs/pitch/charts/arq_grafo.png`.

## Los 12 números
| # | Número | Qué es | Fuente |
|---|---|---|---|
| 1 | **43.6%** vs 91.5% | FCR de quejas vs transaccionales | [`reports/EDA_findings.md`](../../reports/EDA_findings.md) §1 |
| 2 | **36.5%** (24.491) | PQR de cargo no reconocido + cobro indebido | [`reports/replay.md`](../../reports/replay.md) §1 · EDA §1 |
| 3 | **42** | textos de cliente distintos en 171k transcripciones → no entrenamos con ellos | EDA §2.1 · [ADR 0003](../adr/0003-sin-modelo-entrenado-en-datos-del-banco.md) |
| 4 | **109/115** vs 104/115 | resultados correctos: agente de la demo vs reglas (segunda medición, fuga leve declarada) | [`reports/eval_router.md`](../../reports/eval_router.md) §1 |
| 5 | **55/57** | resoluciones automáticas seguras sobre casos en alcance (reglas: 51/57) | eval_router §1 |
| 6 | **0/115** (≤ 2.6%) | inseguros, con cota 95% por regla de tres; 0/38 transferencias faltantes (reglas: 7/38) | eval_router §1 y §4 |
| 7 | **82/115** | inseguros de B1, automatizar sin política ni confirmación | [`reports/eval.md`](../../reports/eval.md) |
| 8 | **0.877** vs 0.548 | macro-F1 de intención, router aprendido vs reglas (split por autor, n=306); acción equivocada 1.6% vs 18.6% | [`reports/intent_router.md`](../../reports/intent_router.md) |
| 9 | **0/2.531** | ataques de inyección públicos con daño, aun con el guard apagado (clasificador AUC 0.97, pero 20/58 falsas alarmas bancarias → regex por defecto) | [`reports/injection_eval.md`](../../reports/injection_eval.md) · [ADR 0005](../adr/0005-deteccion-inyeccion.md) |
| 10 | **0/308** | red team propio tras 3 rondas (antes de cada arreglo: 40/110 · 34/99 · 30/99) | [`reports/redteam.md`](../../reports/redteam.md) |
| 11 | **30** | umbral de fraude: recall 72.4%, precisión 79.0%, deriva 0.08% (test 2026); 60 perdía 6 de 10 | [`reports/fraud_threshold.md`](../../reports/fraud_threshold.md) · [ADR 0006](../adr/0006-umbral-fraude.md) |
| 12 | **p95 233 ms** · ~61 turnos/s | una réplica, sin LLM, costo de modelo $0 | [`reports/capacity.md`](../../reports/capacity.md) §2.C |

De reserva: 10/11 grupos de dialecto con la misma decisión · 33.3% [30.4–36.3%] resueltas solas en el replay
(**SIMULACIÓN**) · 681 tests en CI · 19 caminos del grafo verificados · 20% de transacciones sin `fraud_score`.

## Tres frases para no equivocarse
- "Es la **segunda** medición sobre el test congelado, con una fuga leve declarada; la medición ciega es un test v3."
- "Cero observado no es riesgo cero: con 115 casos, la cota es 2.6%."
- "El LLM está implementado y apagado: **no medimos** su costo ni su latencia; solo hay estimaciones rotuladas."

## Si la demo en vivo falla
Plan completo: [`docs/demo-script.md`](../demo-script.md#3-plan-b-si-algo-falla-en-vivo). En orden:
1. **Una escena no da lo esperado:** no depurar en vivo; pasar a la escena de reserva equivalente (handoff H02 ↔ H04 ↔
   H01, política D02 ↔ D05).
2. **"Tu sesión expiró":** pasaron más de 15 min desde el login; hacer login de nuevo y repetir el turno 1.
3. **El link del deploy no carga:** demo local por consola sobre la misma base:
   `python -m bankagent.chat --customer <ID> --db data/demo/demo.duckdb` (`/trace`, `/handoff`, `/expire`).
4. **Falla todo:** video pregrabado con las mismas escenas; si tampoco hay video, abrir
   [`deck.pdf`](deck.pdf) en la slide 3 y mostrar las capturas `docs/pitch/screens/escena1.png`,
   `docs/pitch/screens/escena2.png` y `docs/pitch/screens/escena3.png` (normal, ambiguo, handoff en pt + ataque).
   Contarlo igual: "así se ve la traza, las reglas y el paquete del asesor".

Antes de salir: `python scripts/verify_demo.py --db data/demo/demo.duckdb --raw data/raw` → 14/14 OK.
