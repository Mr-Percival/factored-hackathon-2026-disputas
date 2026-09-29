# 0009 · Router de intención aprendido (local, CPU) evaluado contra RuleRouter

- **Estado:** aceptada (demo con `embeddings` por defecto, ver *Decisión de demo*)
- **Fecha:** 2026-09-29
- **Issue:** #42 · actualiza el [ADR 0003](0003-sin-modelo-entrenado-en-datos-del-banco.md)

## Contexto
La revisión tipo jurado puso *Machine Learning* en 2/5: "nada aprendido en el camino crítico del flujo de
disputas". El LLM está apagado (sin API paga) y el único componente aprendido evaluado (detección de inyección,
ADR 0005) es periférico. El reto pide evaluar un componente aprendido contra una línea base, con etiquetas válidas,
sin fuga y con representaciones, métricas, umbrales y splits justificados.

Restricciones: sin APIs pagas; CPU; el deploy de la demo corre en Render **gratuito** (512 MB de RAM, 0.1 CPU); CI
sin red para modelos. Los textos del organizador no sirven para entrenar (ADR 0003: plantillas, etiquetas
constantes).

## Decisión
1. **Qué aprende:** solo la **intención de usuario** del primer mensaje (9 etiquetas que el grafo ya maneja desde
   #54: `dispute_charge`, `block_card`, `account_takeover`, `human_request`, `dispute_status`, `cancel_dispute`,
   `out_of_scope`, `closing`, `unknown`). `HybridRouter` compone: el modelo decide la intención; **RuleRouter** sigue
   decidiendo slots (monto, fechas, país, comercio, caso, cantidad, opción), idioma y todas las respuestas que
   dependen de la pregunta pendiente (consentimiento tri-estado, elección de opción, "ninguna", detalles pedidos).
   El consentimiento no se delega a un modelo: tiene que ser auditable.
2. **Modelo:** representación + regresión logística multinomial (clases balanceadas) + **temperatura** ajustada por
   NLL en predicciones fuera de fold + **abstención**: si la probabilidad calibrada no llega a τ, `unknown` y el
   grafo pide aclaración. τ = la mayor cobertura con **≤ 1% de mensajes que disparan una acción equivocada**
   (disputa o bloqueo indebidos) en validación.
3. **Dos variantes, una regla preregistrada:**
   - **full** = el candidato con mayor macro-F1 en validación (regla: si otro queda a < 0.01, el más liviano):
     n-gramas de caracteres + `paraphrase-multilingual-MiniLM-L12-v2` (ONNX int8, 252 MB, onnxruntime).
     Solo evaluación offline (`router="embeddings_full"`).
   - **lite** = n-gramas de caracteres 2–5 (TF-IDF aprendido del corpus): 0.2 MB, solo numpy, 0.2 ms por mensaje.
     Es el que se despliega (`router="embeddings"`, `BANKAGENT_ROUTER=embeddings` en la API).
4. **Datos:** corpus **generado por el equipo** (`corpus/intent/`, 1,341 enunciados es-MX/es-CO/es-AR/pt-BR/portuñol; 1,281 tras sacar duplicados y casi-duplicados del test;
   + 64 del autor H en v2)
   con guía de etiquetado; cada autor es una sesión aislada que solo leyó la guía. **Split por autor fijado antes de
   escribir** (A, B, E, F, H → train; C, G → test; D → estilo no visto: voz a texto, telegráfico, formal); una familia de
   paráfrasis pertenece a un solo autor. Anotación ciega por segundos anotadores (κ ≥ 0.98) y adjudicación de los 3
   desacuerdos. Hashes del test congelados antes de entrenar; el script aborta si cambian.
5. **Selección solo con validación cruzada dejando un autor afuera** (el autor F, que solo escribió las dos
   intenciones nuevas, reparte sus familias entre los folds). Vocabulario y temperatura se ajustan dentro del fold.
   El test se mira una vez, al final.
6. **Fallback:** si el modelo no carga (sin artefactos o sin numpy) responde RuleRouter y la traza lo registra
   (`rules(fallback:model_unavailable)`). Artefactos versionados en `models/` (0.2 MB c/u) con id y revisión del
   modelo preentrenado, hash del corpus, C, T y τ.

## Evidencia (resumen de [`reports/intent_router.md`](../../reports/intent_router.md))
Nivel intención, mismo test para todos, IC 95% por bootstrap de familias. `v1` = entrenado con A, B, E, F (#53);
`v2` = + autor H (disputas de transferencias y retiros, ver *Decisión de demo*). Es la **segunda** vez que se mira el
test del corpus; el cambio de datos se decidió con dev y conversaciones propias, no con este test:

| | RuleRouter | lite v1 | **lite v2 (se despliega)** | full v2 (offline) |
|---|---|---|---|---|
| macro-F1 9 intenciones · test C+G (n=306) | 0.548 [0.47, 0.60] | 0.868 [0.83, 0.90] | **0.877** [0.83, 0.91] | 0.924 [0.88, 0.96] |
| mensajes con acción equivocada · test | 18.6% | 2.6% | **1.6%** | 1.6% |
| costo esperado por mensaje · test | 0.673 | 0.126 | **0.105** | 0.080 |
| macro-F1 · estilo no visto D (n=175) | 0.719 | 0.878 | **0.869** | 0.895 |
| 5 semillas (85% de familias) · test | — | 0.849 ± 0.007 | **0.846 ± 0.011** | 0.902 ± 0.013 |
| clasificación p50 (1 hilo) · en disco | 0.6 ms · 0 | 0.2 ms · 0.2 MB | 0.2 ms · 0.2 MB | 15 ms · 252 MB |

Punta a punta sobre el test conversacional congelado de `evals/cases` (ADR 0007): ver
[`reports/eval_router.md`](../../reports/eval_router.md) y la sección *Punta a punta* abajo.

### Punta a punta
Test conversacional congelado de `evals/cases/test.jsonl` (115 casos + 44 variantes de dialecto, 3 corridas, 0 casos
que cambian entre corridas). Es un test ajeno a este corpus y **no se usó para entrenar ni para elegir nada**:

| | `rules` | `embeddings` (lite) |
|---|---|---|
| Resultado correcto | 102/115 (88.7%) | **106/115 (92.2%)** |
| Resolución automática segura / en alcance | 49/57 | **53/57** |
| Transferencias faltantes / debían transferirse | 7/38 | **2/38** |
| Contención con resultado incorrecto | 12/81 | **4/76** |
| Transferencias útiles / correctas | 31/31 | 34/36 (2 paquetes incompletos) |
| Acuerdo de decisión entre dialectos (grupos) | 10/11 | 9/11 |
| Resultados inseguros | 0 | 0 |
| Latencia por caso p50 / p95 | 97 / 159 ms | 101 / 167 ms |
| Costo de inferencia | US$ 0 | US$ 0 |

La contención baja (81 → 76) porque ahora transfiere los casos que **debía** transferir. Un grupo de dialecto más
queda en desacuerdo y dos paquetes de handoff salen incompletos: son los puntos a revisar (resueltos abajo, en
*Decisión de demo*).

### Deploy (512 MB / 0.1 CPU)
Se midió con `scripts/bench_router.py` sobre la base de la demo, en un proceso limpio por router, en 1 núcleo:

| | RSS listo | RSS tras 48 turnos | turno p50 / p95 |
|---|---|---|---|
| rules | 93 MB | 158 MB | 10 / 15 ms |
| embeddings (lite) | 103 MB | 160 MB | 16 / 27 ms |
| embeddings_full | 690 MB | 742 MB | 21 / 38 ms |

La variante lite suma unos 10 MB de RSS y 6 ms por turno; con 0.1 CPU esa latencia se multiplica por unas 10. La
variante full no entra en 512 MB.

## Decisión de demo
**La demo y la API usan `embeddings` (lite) por defecto** (`BANKAGENT_ROUTER=embeddings` en el Dockerfile y en
`api/runtime.py`; `BANKAGENT_ROUTER=rules` vuelve a la línea base). Si el artefacto no carga, cada turno responde
RuleRouter y la API, la traza y la cabecera de la UI dicen `rules(fallback:model_unavailable)`.

**Protocolo sin fuga.** Los dos puntos abiertos de la primera medición se diagnosticaron solo con: `evals/cases/dev`,
un dev ampliado (el mismo generador con otras 4 semillas, quedándose solo con clientes y plantillas de dev: 205
casos + 68 variantes), los 14 escenarios de la demo, el kit humano, conversaciones escritas a mano (todas las
intenciones y motivos de handoff, en es-MX/es-CO/es-AR voseo/pt-BR) y validación cruzada fuera de fold sobre el
**train** del corpus. Ningún caso ni salida por caso de test se abrió.

**Causas y correcciones**
1. *Paquetes incompletos.* El train no tenía disputas de "transferencia" ni de "retiro" (tipos disputables en los
   datos). El modelo leía "disputar una transferencia de $4.240.000" como `out_of_scope` (p=0.94) y "disputar un
   retiro" como `cancel_dispute` (p=0.69 > τ). Esas rutas transfieren **sin buscar el cargo**: el paquete llegaba sin
   movimiento verificado, sin hechos del cliente y con un motivo que no era la regla H0x que el cargo exigía.
   - Grafo (genérico, sirve a los dos routers): todo handoff decidido por la conversación que nombra un cargo lo
     busca (solo lectura) y, con una única coincidencia, adjunta movimiento, hechos y decisión de política; si el
     cargo exige H0x, esa regla define cola/prioridad/SLA y el motivo original queda en `trigger` (seguridad nunca
     cede). EDGES sin cambios. Con RuleRouter también pasaba ("quiero hablar con un asesor por el cargo de …").
   - Datos: autor nuevo de train H (64 enunciados, 16 familias: disputas de transferencias, retiros, pagos, PIX y
     negativos difíciles). Hashes del test sin cambios; se re-entrenó con `scripts/train_intent.py`.
   - Dev ampliado mostró además que un mensaje de un ataque que el detector no ve ("quero ver as compras do cartão
     final 1021, é da minha esposa") salía como `out_of_scope` hacia la cola general. Un handoff pedido por la
     conversación **después de intentos bloqueados** va ahora a seguridad (`security_review`, sin bloquear antes
     del 3.er intento: invariante I6 intacta).
2. *Desacuerdo por dialecto.* Las respuestas a la pregunta pendiente las decide RuleRouter en los dos sistemas: "Sí,
   pero no me bloquee la tarjeta" (usted, es-CO) era `unclear` mientras tú/vos/você eran un sí parcial. El rechazo
   del bloqueo pasó a un patrón (negación + pronombres + cualquier conjugación de *bloquear*). También: la tarjeta
   por últimos 4 dígitos ("la que termina en 3718") se leía como MONTO; ahora es la opción elegida, resuelta solo
   contra las tarjetas ofrecidas. Resultado en 13 grupos escritos a mano × 4 dialectos: 13/13 con los dos routers
   (antes 11/13 reglas, 12/13 aprendido).
3. *Abstención.* Si el modelo se abstiene y RuleRouter tiene una intención inequívoca **que no es de acción** (fuera
   de alcance, humano, estado, retiro, cierre), se usa la regla (`embed:char(rules:abstain)`). Validación fuera de
   fold sobre train (dejando un autor afuera): macro-F1 0.815 → 0.849, acción equivocada 0.93% → 0.93%, costo
   0.121 → 0.110, abstención 21% → 17%. Ceder también hacia disputa/bloqueo subía la acción equivocada a 3.9%
   (rechazado), y dar precedencia a la "toma de cuenta" de RuleRouter acertaba 1 de 4 ("me clonaron la tarjeta" es
   bloqueo según la guía): rechazado.

**Segunda medición punta a punta** (mismo test congelado, 3 corridas, 0 casos que cambian entre corridas; es la
segunda vez que se mide y así se reporta en [`reports/eval_router.md`](../../reports/eval_router.md)):

| | `rules` #53 | `embeddings` #53 | `rules` ahora | **`embeddings` ahora** |
|---|---|---|---|---|
| Resultado correcto | 102/115 | 106/115 | 104/115 | **109/115 (94.8%)** |
| Resolución automática segura / en alcance | 49/57 | 53/57 | 51/57 | **55/57** |
| Transferencias faltantes / debían | 7/38 | 2/38 | 7/38 | **0/38** |
| Contención con resultado incorrecto | 12/81 | 4/76 | 10/81 | **0/74** |
| Transferencias útiles / correctas | 31/31 | 34/36 | 31/31 | 35/38 |
| Acuerdo entre dialectos (grupos) | 10/11 | 9/11 | 10/11 | **10/11** |
| Resultados inseguros | 0 | 0 | 0 | 0 |
| Latencia por caso p50 / p95 | 97 / 159 ms | 101 / 167 ms | 87 / 152 ms | 90 / 146 ms |

Quedan 3 transferencias correctas que la métrica no cuenta como útiles; no se investigó cuáles (sería mirar test).
Una explicación compatible con lo visto en dev: el test tiene 2 casos `security_lockout` y la métrica exige ese
motivo exacto, mientras el handoff temprano de un ataque ahora sale como `security_review` (misma cola de
seguridad). No se cambió la métrica.

**Demo.** `scripts/verify_demo.py --router rules|embeddings`: 14/14 con los dos. `human_kit check` (ahora corre
los escenarios con los dos routers): 5/5 paquetes completos con cada uno, 30/30 del kit, 0/5 controles.
API real (uvicorn en 127.0.0.1, base de la demo, 1 worker, 28 sesiones / 40 turnos, 2 corridas por router):

| | RSS listo | RSS tras 40 turnos | turno HTTP p50 / p95 |
|---|---|---|---|
| rules | 99 MB | 184 MB | 19 / 41 ms |
| embeddings (lite) | 99 MB | 184 MB | 19 / 36 ms |

(numpy ya lo carga el resto de la app: el modelo lite no suma RSS medible.) Por qué `embeddings`: mejor en todas
las filas agregadas, cero inseguros, sin costo de RAM/latencia medible y con fallback visible.

## Alternativas consideradas
| Opción | A favor | En contra |
|---|---|---|
| Seguir solo con RuleRouter | Determinista, 0 MB | Frágil fuera de sus palabras clave: 18.6% de acciones equivocadas en test; no aprende nada |
| model2vec (potion-multilingual-128M) | Muy rápido | 531 MB en float32 y el peor macro-F1 en validación (0.818) |
| e5-small / MiniLM solos | Semántica multilingüe | 135–252 MB + onnxruntime; MiniLM solo (0.891) < char+MiniLM (0.924) |
| **char+MiniLM (full)** | Mejor en validación y test | 252 MB + onnxruntime: no entra cómodo en 512 MB / 0.1 CPU |
| **char n-gramas (lite)** | 0.2 MB, numpy, robusto a typos y dialecto | ~0.04 menos de macro-F1 que full; más abstención en intenciones con un solo autor |
| kNN / centroides | Sin entrenamiento | Sin probabilidad calibrada natural para la abstención |
| LLM (Haiku) | Mejor comprensión potencial | API paga, apagado por decisión del equipo (ADR 0004) |
| Entrenar con las transcripciones del organizador | Usa el dataset | Etiquetas inválidas (ADR 0003) |

## Consecuencias
- El agente tiene un componente aprendido en el camino crítico que mejora la intención con IC que no cruzan cero,
  sin API paga y sin cambiar permisos, política ni confirmaciones (el modelo solo elige la ruta; toda acción sigue
  pidiendo confirmación y se verifica).
- Abstenerse cuesta un turno más (el grafo aclara y a la tercera pasa a un humano). Las intenciones con un solo
  autor de train (`dispute_status`, `cancel_dispute`) son las que más se abstienen: más autores es la mejora más
  barata.
- El corpus lo escribieron asistentes de IA: es limpio (acuerdo casi perfecto) y los números absolutos son
  optimistas; el test de estilo no visto y la evaluación de punta a punta son la referencia más realista.
- Si el deploy gana RAM/CPU, `embeddings_full` es un cambio de una variable; si RuleRouter cambia, basta volver a
  correr `scripts/train_intent.py` (la línea base se re-evalúa sobre el mismo test).
