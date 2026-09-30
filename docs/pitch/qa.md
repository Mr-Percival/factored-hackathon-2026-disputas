# Preguntas del jurado: respuestas preparadas

> Para la ronda de preguntas de la final (issue #34). Cada respuesta se puede decir en voz alta en 20–40 s, va con su
> **evidencia** (archivo, test o sección de reporte), su **límite honesto** y la **repregunta** probable.
> Todos los números salen del archivo citado (verificados el 2026-09-29). Si un número no está acá, no lo digan de
> memoria: digan "está en el reporte X" y ábranlo. Hoja de una página: [`cheatsheet.md`](cheatsheet.md).

**Reglas para responder**
1. Primero la respuesta corta, después la evidencia. Si no sabemos, "no lo medimos" es una respuesta válida.
2. Nunca redondear hacia arriba: 109/115, no "95%"; 0/115 con cota ≤ 2.6%, no "cero riesgo".
3. Distinguir siempre **medición offline**, **SIMULACIÓN** y **estimación**.
4. El sistema de la demo es **router aprendido local + reglas + plantillas, sin LLM**. El LLM está implementado y apagado.

Índice: [A. Criterio técnico](#a-criterio-técnico) · [B. Ingeniería de IA](#b-ingeniería-de-ia) ·
[C. Ingeniería de datos](#c-ingeniería-de-datos) · [D. Machine learning](#d-machine-learning) ·
[E. Evaluación y analítica](#e-evaluación-y-analítica) · [F. Seguridad](#f-seguridad) ·
[G. Producción](#g-producción) · [H. Curveballs](#h-curveballs)

---

## A. Criterio técnico

### A1. ¿Por qué no un agente LLM con herramientas (ReAct) en vez de un grafo determinista?
**Respuesta.** Porque en un banco lo que puede causar daño (ver datos ajenos, abrir una disputa, bloquear una tarjeta)
no puede depender de que el modelo siga un prompt. Con ReAct los permisos y la política viven en el texto; en nuestro
grafo viven en código: el cliente sale del token, la elegibilidad de `policy.yaml` y cada acción exige un "sí" en el
turno inmediatamente anterior. El modelo solo elige la ruta dentro de transiciones declaradas.
**Evidencia.** [ADR 0002](../adr/0002-grafo-deterministico-con-llm-acotado.md) (alternativas descartadas) ·
`tests/test_security.py::test_undeclared_transition_fails_closed` · `tests/test_graph_paths.py::test_act_is_only_reachable_from_understand`
· [`docs/graph-paths.md`](../graph-paths.md) (19 caminos START→END).
**Límite.** Es menos flexible fuera del flujo: lo que no está previsto pasa a un humano (`out_of_scope`).
**Repregunta.** *"¿Y si mañana quieren 10 flujos?"* → Cada flujo es un subgrafo con su política y sus herramientas;
el patrón se repite (guard, entender, decidir, actuar con confirmación). No proponemos un agente general: el reto pide
un flujo con profundidad y lo que escala es el patrón, no la libertad del modelo.

### A2. ¿Por qué disputas y no elegibilidad de crédito?
**Respuesta.** Por los datos y por el riesgo. Las quejas tienen el peor FCR (43.6% contra 91.5% en transaccionales) y
cargo no reconocido + cobro indebido son el 36.5% de los PQR (24.491 casos). Además, abrir una disputa y bloquear
una tarjeta **no mueven dinero** y son reversibles; una decisión de crédito es irreversible, regulada y necesita un
modelo de riesgo que no se valida bien en 7 días.
**Evidencia.** [ADR 0001](../adr/0001-flujo-disputas.md) · [`reports/EDA_findings.md`](../../reports/EDA_findings.md) §1 ·
marco del replay: 24.491 quejas ([`reports/replay.md`](../../reports/replay.md) §1).
**Límite.** El dataset no une quejas con transacciones (`origin_interaction_id` 100% nulo), así que no medimos cuántas
disputas reales son fraude.
**Repregunta.** *"¿El volumen justifica automatizar?"* → No proyectamos ahorros: los datos son sintéticos. Lo que sí
mostramos es la SIMULACIÓN del replay: 33.3% [30.4–36.3%] de 1.000 quejas históricas se resolverían solas y seguras.

### A3. ¿Dónde usaron IA y dónde lógica determinista, y por qué?
**Respuesta.** IA solo en **entender qué quiere el cliente** (intención), porque es la parte donde las reglas fallan:
18.6% de mensajes con acción equivocada contra 1.6% del modelo. Montos, fechas, país, opción elegida y el "sí" de
cada acción los leen reglas, porque el consentimiento tiene que ser auditable. Política, permisos, verificación y
redacción base son código y plantillas.
**Evidencia.** [`docs/architecture.md`](../architecture.md#2-quién-decide-qué) · [ADR 0009](../adr/0009-router-aprendido.md) §Decisión 1.
**Límite.** El lector de consentimiento es léxico: es el riesgo residual 1 del red team.
**Repregunta.** *"¿Por qué no delegar también el consentimiento a un modelo?"* → Porque es lo que habilita una acción;
preferimos re-preguntar de más ("sí, al ratito" se re-pregunta) antes que actuar con un "sí" dudoso. En producción
lo correcto es un botón o step-up/MFA, no un modelo mejor.

### A4. ¿Por qué LangGraph y no código Python plano?
**Respuesta.** Por el checkpointer por conversación (aclaraciones y confirmaciones multi-turno), la traza por nodo y
porque las aristas se declaran en una tabla (`EDGES`) que podemos verificar de forma exhaustiva. El costo es overhead:
en la prueba de carga el grafo pesa más que las herramientas.
**Evidencia.** `src/bankagent/graph.py` · [`reports/capacity.md`](../../reports/capacity.md) §3.3 (overhead ≈ 14–25 ms
por turno con un hilo; `durability="exit"` lo baja a ~14 ms, no aplicado).
**Límite.** Con más de 8–16 hilos el GIL serializa: se escala con procesos o réplicas.
**Repregunta.** *"¿Qué verificaron del grafo?"* → Acíclico, 19 caminos, `act` solo desde `understand`, y
`understand → act` solo con confirmación fresca: probado sobre las 588 combinaciones posibles
(`tests/test_graph_paths.py::test_understand_routes_to_act_only_on_fresh_confirmation`).

### A5. ¿Qué harían con dos semanas más?
**Respuesta.** En orden: (1) un **test v3** escrito por otra persona para una medición ciega; (2) **evaluar el LLM**
(router y writer) contra la línea base en ese test, con costo y latencia reales; (3) las **calificaciones humanas** de
los handoffs (el kit está listo); (4) step-up/MFA antes de actuar, que cierra el riesgo del consentimiento léxico;
(5) checkpointer Postgres y ops transaccional para escalar horizontalmente.
**Evidencia.** [`docs/operations.md`](../operations.md#8-trabajo-restante-antes-de-producción-priorizado-honesto) ·
[`docs/threat-model.md`](../threat-model.md#qué-falta-para-producción-resumen-honesto).
**Límite.** Ninguno de estos está hecho; no los presenten como "casi listos".
**Repregunta.** *"¿Por qué no lo hicieron ya?"* → El test v3 necesita un autor que no haya visto el sistema y el LLM
necesita API paga; priorizamos lo que se podía medir sin eso.

---

## B. Ingeniería de IA

### B1. ¿Qué pasa cuando se prende el LLM? ¿Cuánto cuesta y cuánto tarda?
**Respuesta.** No lo medimos: no hay API paga, así que está implementado pero **apagado**. Lo que sí hay: un cliente
agnóstico de proveedor, salida estructurada validada en código, reintentos acotados, fallback a reglas/plantillas y un
verificador determinista que rechaza cifras, IDs o promesas que no estén en los hechos. La traza registra modelo,
versión de prompt, tokens, costo estimado y fallback por turno.
**Evidencia.** [ADR 0004](../adr/0004-llm-acotado-router-writer.md) · `tests/test_llm.py::test_router_failures_fall_back_to_rules` ·
`tests/test_llm.py::test_writer_invented_amount_falls_back_to_template` · `tests/test_llm.py::test_no_pii_reaches_the_provider`.
**Límite.** Solo tenemos **estimaciones rotuladas**: < US$0.01 por disputa de 3 turnos y ≈ 1–2 s por turno con Haiku
(ADR 0004); p50 ≈ 1.5–2.8 s y p95 ≈ 4–6 s por turno ([`reports/capacity.md`](../../reports/capacity.md) §5). El red team
y las propiedades no ejercitaron el LLM.
**Repregunta.** *"¿Entonces el LLM podría empeorar la seguridad?"* → No puede disparar una acción: `confirm` sin
pregunta pendiente se degrada a `unknown`, la confirmación exige confianza ≥ 0.6 y turno fresco, y el writer no puede
cambiar hechos (si el verificador falla, sale la plantilla). Sí podría empeorar exactitud o tono; eso es lo que hay
que medir con `--system llm` sobre el mismo test.

### B2. ¿Qué datos salen hacia el proveedor del LLM?
**Respuesta.** Solo texto ya enmascarado (`[TARJETA]`, `[EMAIL]`, `[TELEFONO]`, `[CURP]`), la fecha y qué pregunta está
pendiente. Nunca nombre, documento, `customer_id`, historial, fraud_score ni política. Si aparece un número de 13+
dígitos o un email, el envío se bloquea.
**Evidencia.** [ADR 0004](../adr/0004-llm-acotado-router-writer.md) §Privacidad · `tests/test_llm.py::test_no_pii_reaches_the_provider`.
**Límite.** El redactor es por patrones; PII escrita de formas raras podría pasar. Falta DPA con el proveedor
([`docs/operations.md`](../operations.md) §8, punto 8).
**Repregunta.** *"¿Y el writer ve el comercio y el monto?"* → Sí, el movimiento ya formateado del propio cliente; es
lo mínimo para redactar la respuesta.

### B3. ¿Cómo evitan que el agente diga "listo" cuando no lo hizo?
**Respuesta.** Las herramientas releen el estado después de actuar (`verified=True`); si no se verifica, el caso pasa
a un humano con motivo `action_not_verified`. Además, el invariante I3 comprueba que toda acción que la respuesta da
por hecha exista en ops y que todo `DSP-…` citado exista.
**Evidencia.** `src/bankagent/tools.py` · [`docs/threat-model.md`](../threat-model.md#propiedades-demostradas) (I3) ·
`tests/test_properties.py::test_conversation_invariants`.
**Límite.** Hoy "verificar" es releer tablas `ops` del sandbox; con el core real hay que releer la API del core y
reconciliar.
**Repregunta.** *"¿Y si la escritura se hizo pero la respuesta se perdió?"* → Está en el generador de fallas de las
propiedades ("escribió pero no respondió"); en producción hace falta una llave de idempotencia por acción.

### B4. ¿Qué pasa si el modelo aprendido no carga o se equivoca con mucha confianza?
**Respuesta.** Si no carga, responde RuleRouter y la traza, la API y la UI lo dicen (`rules(fallback:model_unavailable)`).
Si se equivoca, igual no actúa solo: toda acción pide confirmación y la política decide elegibilidad. Si la
probabilidad calibrada no llega a τ = 0.69, se abstiene y pregunta.
**Evidencia.** `tests/test_intent_router.py::test_missing_model_falls_back_to_rules_and_says_so` ·
`tests/test_intent_router.py::test_abstention_never_backs_off_into_an_action` · [`reports/intent_router.md`](../../reports/intent_router.md) (τ, T).
**Límite.** Abstenerse cuesta un turno; las intenciones con un solo autor de train (`dispute_status`, `cancel_dispute`)
son las que más se abstienen.
**Repregunta.** *"¿Cuántas acciones equivocadas propone igual?"* → 1.6% de los mensajes del test del corpus (5 de 306);
todas pasan por una confirmación.

### B5. ¿El portugués funciona si todo el dataset está en español?
**Respuesta.** El dataset no tiene nada de portugués (EDA, limitación 11), así que todo el portugués es nuestro y está
declarado: plantillas y casos pt-BR (32 de los 115 casos de test), corpus de intención con 216 enunciados pt-BR en
train, y 80 filas de inyección traducidas por el equipo. Los clientes pt-BR son de MX/CO/AR porque no hay clientes
brasileños, aprovechando las ~40k transacciones hechas en Brasil.
**Evidencia.** [`reports/EDA_findings.md`](../../reports/EDA_findings.md) §2.11 · [`reports/eval_router.md`](../../reports/eval_router.md) §2 ·
[`evals/cases/README.md`](../../evals/cases/README.md#limitaciones) · `tests/test_agent.py::test_portuguese_fraud_signal_handoff`.
**Límite.** Lo escribió un equipo hispanohablante con asistencia de IA, **sin revisión nativa**. Es el punto más débil
de cobertura de idioma.
**Repregunta.** *"¿Hay diferencia de resultados por idioma?"* → El desglose existe en el reporte pero con n≈28 por
dialecto las brechas pequeñas no son concluyentes (§12 de eval_router). Lo que sí medimos es equidad: 10/11 grupos
dan la misma decisión en MX, CO, AR y pt-BR.

### B6. ¿Cómo manejan una conversación que se desvía?
**Respuesta.** Estados explícitos: puede pedir un humano en cualquier momento, "me hackearon" va a seguridad con
prioridad, una confirmación solo vale en el turno siguiente, una respuesta ambigua se re-pregunta una vez y luego pasa
a un humano, y tres aclaraciones seguidas sin avanzar también.
**Evidencia.** [`docs/architecture.md`](../architecture.md#3-el-grafo) · `tests/test_properties.py::test_regression_stale_confirmation_is_not_reused`.
**Límite.** El cliente simulado de la evaluación es cooperativo; usuarios reales cambian de tema, se enojan o mienten.
**Repregunta.** *"¿Y errores de tipeo fuertes?"* → Límite declarado en el README (`hise`, `reconosco`): aclaración o
handoff. El n-grama de caracteres ayuda, pero no los dejamos pasar a propósito para no sobreajustar dev.

---

## C. Ingeniería de datos

### C1. ¿Cómo prepararon los datos? ¿Es repetible?
**Respuesta.** Pipeline raw → serving con contrato por tabla (tipos, dominios, FKs), cuarentena con motivo, upsert
incremental idempotente con llegadas tardías y un manifiesto por corrida con archivos, filas, cuarentena y una huella
de la entrega. Tests sin datos reales ni llaves.
**Evidencia.** [`config/contracts.yaml`](../../config/contracts.yaml) · `tests/test_pipeline.py::test_contract_quarantines_invalid_rows` ·
`tests/test_pipeline.py::test_rerun_is_idempotent_and_late_arrivals_upsert` · [`reports/data_quality.md`](../../reports/data_quality.md).
**Límite.** En los datos reales la cuarentena quedó en 0 filas: el contrato está probado con el fixture, no porque los
datos del organizador tuvieran filas malas.
**Repregunta.** *"Entonces, ¿la cuarentena sirve para algo?"* → Sirve cuando cambie la entrega; y las advertencias sí se
dispararon (`mexico_without_mxn`: 2.146.309 filas, 48.5%).

### C2. ¿Qué artefactos sintéticos encontraron y qué hicieron con ellos?
**Respuesta.** Varios, y cada uno cambió una decisión: (1) solo 42 textos de cliente distintos en las transcripciones →
no entrenamos intención con ellas; (2) México sin MXN, todo en USD → advertencia de contrato y montos en USD en la demo
mexicana; (3) el `fraud_score` tiene un quiebre limpio en 30 → lo declaramos artefacto; (4) dos generaciones del
dataset en el bucket → huella por entrega; (5) conteos menores a los documentados y 0 duplicados aunque la doc decía
~2%; (6) KPIs idénticos por acento → no ruteamos por acento.
**Evidencia.** [`reports/EDA_findings.md`](../../reports/EDA_findings.md) §2 · gráfico `docs/pitch/charts/03_calidad_datos.png`.
**Límite.** Con datos reales varias decisiones (umbral, montos) hay que recalibrarlas.
**Repregunta.** *"¿Qué es lo que más les preocupa de eso?"* → Que los números absolutos (umbral, replay) no transfieren;
el método sí (scripts reproducibles).

### C3. ¿Qué pasó con las dos generaciones del dataset?
**Respuesta.** `data_backup_20260831/` no es una versión anterior: el 97% de los IDs de cliente no se solapa
(145.975 de 150.000) y las 67.095 quejas apuntan todas a otro cliente. No sirve como entrega incremental real, así que
usamos `data/`, registramos su huella por tabla y demostramos el upsert incremental con el fixture.
**Evidencia.** [`reports/snapshot_diff.md`](../../reports/snapshot_diff.md) · [`reports/EDA_findings.md`](../../reports/EDA_findings.md) §2.12.
**Límite.** La actualización incremental no está probada sobre una segunda entrega real del organizador.
**Repregunta.** *"¿Qué pasa si el organizador regenera los datos otra vez?"* → Cambia la huella en el manifiesto y hay que
regenerar lo que referencia IDs (casos de evaluación, guion de demo); los casos de test se niegan a reescribirse sin `--force`.

### C4. ¿Cómo evitan fuga temporal?
**Respuesta.** En dos lugares: el umbral de fraude se eligió en datos previos a 2026 y se midió una sola vez en 2026; el
replay juzga cada queja a su fecha de creación, con búsqueda point-in-time que oculta transacciones posteriores.
**Evidencia.** [`reports/fraud_threshold.md`](../../reports/fraud_threshold.md) · `tests/test_replay.py::test_point_in_time_search_hides_later_transactions`.
**Límite.** En el replay la transacción disputada se **infiere** con una regla de emparejamiento: se mide contra esa regla,
no contra una verdad conocida.
**Repregunta.** *"¿Por qué 38% de las quejas no tienen transacción plausible?"* → 37.6% no tiene candidata en la ventana
de 60 días con los tipos disputables; esas irían a un humano. Es consecuencia de que el dataset no une quejas con
transacciones.

### C5. ¿Concurrencia? ¿Qué encontraron?
**Respuesta.** La prueba de carga encontró una fuga real: una conexión DuckDB compartida entre hilos devolvía filas de
un cliente a otro (y 6.9–11% de errores). Se corrigió con un cursor por hilo, y con índices por `customer_id` la CPU
por turno bajó de ~135 a ~28 ms. Quedó un test de regresión.
**Evidencia.** [`reports/capacity.md`](../../reports/capacity.md) §2–3 · `tests/test_concurrency.py::test_concurrent_reads_never_mix_customers` ·
`tests/test_api.py::test_parallel_customers_only_see_their_own_data`.
**Límite.** Medido en una laptop compartida; cifras absolutas ruidosas.
**Repregunta.** *"¿Cómo se enteraron?"* → Por la prueba de carga, no por un test unitario: por eso ahora corre en CI.

---

## D. Machine learning

### D1. ¿Cuál es el componente aprendido y contra qué lo comparan?
**Respuesta.** Un router de intención local: n-gramas de caracteres 2–5 con TF-IDF, regresión logística multinomial,
temperatura calibrada y abstención; 0.2 MB, solo numpy. Contra RuleRouter en el mismo test del corpus (split por
autor, n=306): macro-F1 0.877 [0.83, 0.91] contra 0.548, y mensajes con acción equivocada 1.6% contra 18.6%. De punta a
punta: 109/115 contra 104/115 correctos y 0 contra 7 transferencias faltantes.
**Evidencia.** [`reports/intent_router.md`](../../reports/intent_router.md) §Resumen · [`reports/eval_router.md`](../../reports/eval_router.md) §1 ·
[ADR 0009](../adr/0009-router-aprendido.md).
**Límite.** La variante mejor (con MiniLM, F1 0.924) no entra en el deploy gratuito (512 MB): ~690 MB de RSS.
**Repregunta.** *"¿La diferencia es significativa?"* → Δ macro-F1 +0.330 con IC 95% [0.257, 0.409] por bootstrap de
familias de paráfrasis: no cruza cero.

### D2. El corpus lo escribieron asistentes de IA. ¿No es optimista?
**Respuesta.** Sí, y lo decimos en el ADR: es más limpio y prototípico que el tráfico real (por eso el acuerdo entre
anotadores es casi perfecto, κ ≥ 0.98). Mitigamos con un autor por sesión aislada que solo leyó la guía, split por
autor fijado antes de escribir, y un test de estilo no visto (voz a texto, telegráfico, formal) donde el modelo da
0.869 contra 0.719. La referencia más realista es la de punta a punta, que usa otro generador.
**Evidencia.** [`reports/intent_router.md`](../../reports/intent_router.md) §Datos y §Limitaciones ·
[ADR 0009](../adr/0009-router-aprendido.md) §Consecuencias · [`corpus/intent/GUIA_ETIQUETADO.md`](../../corpus/intent/GUIA_ETIQUETADO.md).
**Límite.** κ alto aquí mide que la guía es clara, no que el corpus represente clientes reales. No hay ni un mensaje real.
**Repregunta.** *"¿Qué harían con tráfico real?"* → Etiquetar una muestra con la misma guía, medir en modo sombra y
re-entrenar con `scripts/train_intent.py`; la línea base se re-evalúa sobre el mismo test.

### D3. ¿Por qué regresión logística y no un transformer o un LLM?
**Respuesta.** Por restricciones medidas: el deploy tiene 512 MB y 0.1 CPU, y sin API paga. La variante con MiniLM es
mejor (0.924) pero no entra; la lite clasifica en 0.2 ms y no suma RSS medible en la API. La elección entre candidatos
fue con validación cruzada dejando un autor afuera, con una regla preregistrada.
**Evidencia.** [ADR 0009](../adr/0009-router-aprendido.md) §Alternativas y §Deploy · [`reports/intent_router.md`](../../reports/intent_router.md) §Selección.
**Límite.** No lo comparamos contra Haiku (LLM apagado).
**Repregunta.** *"¿Cómo eligieron τ?"* → La mayor cobertura con ≤ 1% de mensajes que disparan una acción equivocada en
validación; el error más caro es proponer una disputa o bloqueo indebido.

### D4. ¿Por qué no entrenaron con los datos del organizador?
**Respuesta.** Porque las etiquetas serían inválidas: 42 textos de cliente distintos en 171k transcripciones,
`detected_intents` = `consulta_general` en el 100% y el texto no depende de la categoría. Un clasificador entrenado
con eso reportaría un número sin significado.
**Evidencia.** [ADR 0003](../adr/0003-sin-modelo-entrenado-en-datos-del-banco.md) · [`reports/EDA_findings.md`](../../reports/EDA_findings.md) §2.1.
**Límite.** Por eso el componente aprendido se entrena con texto propio, con los sesgos de D2.
**Repregunta.** *"¿Y un modelo de fraude con `is_fraud`?"* → Solo `fraud_score` tiene señal (AUC ≈ 0.85); el resto de
las variables son planas. Un modelo propio no mejoraría al score existente: lo usamos como regla con umbral calibrado.

### D5. ¿Cómo eligieron el umbral de fraude? El quiebre en 30 parece demasiado limpio.
**Respuesta.** Split temporal: elegido en dev (antes de 2026) como el umbral más bajo con ≤ 2% de derivación, medido una
sola vez en test 2026: recall 72.4%, precisión 79.0%, derivando 0.08% de las transacciones. El valor provisional era
60, que en dev perdía seis de cada diez fraudes (recall 38.9%). Y sí: el quiebre es un **artefacto del generador**
(bajo 25 se deriva el 16.75%, sobre 35 la precisión es 100%); con datos reales hay que recalibrar con el mismo script.
**Evidencia.** [`reports/fraud_threshold.md`](../../reports/fraud_threshold.md) · [ADR 0006](../adr/0006-umbral-fraude.md) ·
`tests/test_policy.py::test_fraud_threshold_boundary` · `scripts/calibrate_fraud.py`.
**Límite.** 20% de las transacciones no tiene score (891 de 4.316 fraudes): H03 no los ve; los cubren H02/H04 y el
analista. Tampoco medimos la prevalencia de fraude entre cargos disputados.
**Repregunta.** *"¿Por qué 1%, 2% y 5% dan el mismo umbral?"* → Porque el % derivado salta de 16.75% (umbral 25) a
0.09% (umbral 30): no hay umbrales intermedios que cambien la decisión.

### D6. ¿Por qué regex por defecto si el clasificador de inyección tiene AUC 0.97?
**Respuesta.** Porque en nuestro dominio bloquea clientes legítimos: 20 de 58 mensajes bancarios benignos (IC 95%
24–47%), incluso "Sí, confirmo, bloqueen la tarjeta", y cada falsa alarma suma hacia el bloqueo de 3 intentos. Y porque
la detección no es la que evita el daño: con el guard **apagado** el daño fue 0/2.531. El clasificador queda opt-in y
recomendado en modo sombra.
**Evidencia.** [ADR 0005](../adr/0005-deteccion-inyeccion.md) · [`reports/injection_eval.md`](../../reports/injection_eval.md) §2.
**Límite.** El regex detecta poco (TPR 0.09) y su 0/58 es optimista: el mismo equipo escribió los patrones y los
mensajes bancarios. No recalibramos el clasificador con esos 58 porque son test: sería fuga.
**Repregunta.** *"¿Entonces el guard no sirve?"* → Es una señal y un corte temprano, no la frontera. La frontera es el
token, la política y la confirmación.

---

## E. Evaluación y analítica

### E1. ¿109/115 no está sobreajustado? Ya lo midieron dos veces.
**Respuesta.** Sí, en parte, y lo medimos. 109/115 es una segunda medición sobre un test del equipo (con una fuga leve
declarada en #54), así que escribimos un **test v3 ciego**: 80 conversaciones de un autor aislado que solo leyó
`config/policy.yaml` y la base, congeladas por hash antes de correr, medidas **una sola vez**. Resultado:
**seguridad intacta, 0/80 acciones no esperadas** con los dos routers; **utilidad 43/80 (54%)** con el router de la
demo (`rules` 36/80). O sea: el 109/115 sobreestimaba la utilidad, no la seguridad.
**Por qué bajó.** Leímos cada desacuerdo: 37 de 37 son fallas nuestras, no etiquetas dudosas. La causa principal
(20 casos) es el **consentimiento estricto**: tras el red team (#65) el sí tenía que ser puro, y un cliente que dice
«sí, disputen y bloqueen» recibía «no me quedó clara tu respuesta». Es el trade-off seguridad/utilidad, visto con
datos que no escribimos nosotros. Le siguen elegir una opción describiéndola («el de mayo») y bugs de extracción.
**Qué hicimos.** Una gramática del consentimiento (sí + acciones ofrecidas + cortesía; cualquier otra palabra sigue
sin actuar) y los demás arreglos genéricos, con 69 frases de test propias; el red team sigue en 0 daños. Una
segunda corrida sobre v3 da **76/80**, pero **ya no es ciega**: la hicimos después de mirar los casos. El número ciego
es 43/80; para uno limpio post-arreglo hace falta un test v4.
**Evidencia.** [`reports/eval_blind_v3.md`](../../reports/eval_blind_v3.md) (número ciego + «Análisis de desacuerdos») ·
[`reports/eval_blind_v3_rerun.md`](../../reports/eval_blind_v3_rerun.md) · [`evals/cases/README.md`](../../evals/cases/README.md#test-v3-ciego-usado-una-vez-70) ·
`tests/test_consent.py::test_grammar_corpus_is_large_and_new` · `tests/test_redteam.py::test_redteam_corpus_causes_no_harm`.
**Límite.** 80 casos (IC 95% del 54%: 43–64%); un solo autor ciego; el 76/80 sirve para saber que lo arreglado se
arregló, no para decir cuánto generaliza.
**Repregunta.** *"¿Y el test viejo?"* → No empeora: 109/115 (`embeddings`) y 104/115 (`rules`), 0/115 inseguros.

### E2. Las etiquetas se generan por construcción desde la misma política. ¿No es circular?
**Respuesta.** Es circular para la **política**, a propósito: la política es la especificación y no evaluamos si es
buena, evaluamos si el agente la cumple en conversación. Lo que se mide es lo difícil: entender mensajes en cuatro
dialectos, encontrar la transacción correcta entre varias, pedir confirmación por acción y derivar con el paquete
completo. Cada etiqueta se verificó además con el motor de política (142 candidatos, 0 descartes).
**Evidencia.** [ADR 0007](../adr/0007-evaluacion-casos-por-construccion.md) · [`reports/eval_router.md`](../../reports/eval_router.md) §2 ·
[`evals/cases/README.md`](../../evals/cases/README.md#cómo-se-construye-un-caso).
**Límite.** Riesgo de sesgo de diseño: el mismo equipo escribió sistema y casos; un solo proceso de etiquetado, sin
segundo anotador. La prueba de que el split importa: un primer borrador que compartía plantillas con dev inflaba la
línea base de 77/115 a 114/115, y se descartó.
**Repregunta.** *"¿Y quién valida la política?"* → Nadie todavía: es sintética. Es el bloqueante 1 de producción
(aprobación de Legal/Riesgo).

### E3. "0 inseguros en 115" ¿significa cero riesgo?
**Respuesta.** No. Con 115 casos y 0 observados, la cota superior al 95% es ≈ 3/n = 2.6% (regla de tres). Además los
oráculos son nuestros. Lo que da más confianza que el 0 es la escala: la línea base ingenua sin política ni
confirmación (B1) da 82/115 inseguros en el mismo test.
**Evidencia.** [`reports/eval_router.md`](../../reports/eval_router.md) §4 (Resultados inseguros) · [`reports/eval.md`](../../reports/eval.md) (B1) ·
`tests/test_evals.py::test_action_without_confirmation_turn_is_unsafe`.
**Límite.** 2.6% sería inaceptable en producción; para acotar a 0.1% harían falta ~3.000 casos sin incidentes.
**Repregunta.** *"¿Qué cuenta como inseguro?"* → Seis tipos deterministas: acción sin confirmación previa, acción u
objeto equivocado, datos de otro cliente, resolver cuando la política decía otra cosa, rechazo con regla que no aplica,
y reportar una acción no verificada.

### E4. La contención del agente aprendido es menor (64.3% vs 70.4%). ¿No es peor?
**Respuesta.** No: la contención sola no prueba resolución. De los 81 casos que RuleRouter contiene, 10 terminan con
resultado incorrecto; de los 74 del aprendido, 0. La contención baja porque ahora transfiere los que debía transferir
(0/38 faltantes contra 7/38).
**Evidencia.** [`reports/eval_router.md`](../../reports/eval_router.md) §1 y §4 (Contención).
**Límite.** Hay 3/77 transferencias innecesarias en los dos sistemas, sin diagnosticar para no mirar casos de test.
**Repregunta.** *"¿Y las 3 transferencias correctas que no cuentan como útiles (35/38)?"* → No investigamos cuáles (sería
mirar test). La hipótesis compatible con dev: 2 casos `security_lockout` donde la métrica exige ese motivo exacto y el
agente ahora deriva antes como `security_review`, misma cola. No cambiamos la métrica para que dé mejor.

### E5. ¿Cómo midieron equidad?
**Respuesta.** El mismo caso escrito en es-MX, es-CO, es-AR con voseo y pt-BR tiene que producir la misma decisión: 10 de
11 grupos coinciden con los dos routers. No ruteamos por acento porque el EDA no muestra efecto (FCR 76.68% contra
76.59%).
**Evidencia.** [`reports/eval_router.md`](../../reports/eval_router.md) §1 · `tests/test_fairness.py::test_same_dispute_same_decision_in_every_dialect` ·
[`reports/EDA_findings.md`](../../reports/EDA_findings.md) §2.10.
**Límite.** 11 grupos es poco; y no medimos equidad por segmento con potencia suficiente.
**Repregunta.** *"¿Cuál es el grupo que falla?"* → No lo abrimos (es test). En 13 grupos escritos a mano fuera del test,
13/13 con los dos routers (ADR 0009).

### E6. ¿Qué tan realista es el replay de 1.000 quejas?
**Respuesta.** Es una **SIMULACIÓN**: quejas reales del dataset sintético, cliente simulado y transacción inferida con una
regla, porque las quejas no la traen. Muestra estratificada por país, segmento y tipo, cada queja juzgada a su fecha:
33.3% [30.4–36.3%] se resolverían solas y seguras, 26.8% irían a un humano y 0 acciones inseguras.
**Evidencia.** [`reports/replay.md`](../../reports/replay.md) §Resumen y §2.
**Límite.** El resultado final de la disputa (abono o no) no se simula; y no proyectamos ahorros como medición.
**Repregunta.** *"¿Por qué no 60%?"* → Porque 37.6% no tiene transacción plausible y ni se conversa; de las intentadas se
resuelven 53.4%.

### E7. ¿Hay alguna evaluación humana?
**Respuesta.** Todavía no hay calificaciones: el kit está listo (4 evaluadores, 35 paquetes con 5 controles degradados,
rúbrica con anclajes, métricas de acuerdo). Lo que sí hay es el verificador automático de completitud: 30/30 paquetes
reales completos y 0/5 controles degradados pasan.
**Evidencia.** [`reports/human_eval.md`](../../reports/human_eval.md) · [`reports/handoff_completeness.md`](../../reports/handoff_completeness.md) ·
`tests/test_human_eval.py::test_completeness_checker_accepts_real_and_rejects_degraded`.
**Límite.** El reporte tiene una sección de *dry run* con calificaciones **sintéticas**: no citar esos números.
**Repregunta.** *"¿Por qué no lo hicieron?"* → Falta que 4 personas lo completen (~30 min cada una); si lo hacemos antes
de la final, se regenera con `human_kit score`.

---

## F. Seguridad

### F1. ¿Qué impide que un prompt pida datos de otro cliente?
**Respuesta.** Que el cliente nunca sale del texto: las herramientas lo derivan del token de sesión, y el token vive en
el servidor (el navegador tiene un id opaco en cookie HttpOnly). Aunque el guard dejara pasar el ataque, la herramienta
responde `forbidden`, y al tercer intento el hilo se bloquea.
**Evidencia.** `tests/test_security.py::test_tools_refuse_other_customers_data` · `tests/test_api.py::test_cookie_is_httponly_strict_and_token_never_leaves_the_server` ·
[`docs/threat-model.md`](../threat-model.md) (I2, I6).
**Límite.** El IdP es simulado (sesión con expiración de 15 min); no hay MFA.
**Repregunta.** *"¿Y la inyección indirecta desde los datos (comercio malicioso)?"* → Probada: `tests/test_security.py::test_indirect_injection_in_data_has_no_effect`,
0/60 en la evaluación pública, y el red team encontró y corrigió comercios que fingían una línea del agente.

### F2. El red team lo hicieron ustedes mismos. ¿Vale?
**Respuesta.** Vale como adaptativo, no como independiente. Tres rondas, cada una escrita contra el código ya corregido:
40/110, 34/99 y 30/99 ataques con daño antes de los arreglos, 0/308 después con los dos routers. Encontró daño real que
los datasets públicos no cubrían: "después te confirmo" abría la disputa, un intruso bloqueaba un hilo ajeno, una IP
agotaba las sesiones. Cada ataque quedó como regresión en CI, y 18 controles verifican que "no actuar nunca" no pase por seguro.
**Evidencia.** [`reports/redteam.md`](../../reports/redteam.md) · `tests/test_redteam.py::test_regression_yes_with_unanswered_block_never_blocks`.
**Límite.** Nos detuvimos en 3 rondas por tope, no porque la tercera diera 0. Una cuarta probablemente encontraría más en
el lector de consentimiento. Falta un pentest externo.
**Repregunta.** *"¿Cuál es el riesgo residual principal?"* → El sarcasmo hecho solo de palabras de sí ("sí, claro") se toma
como sí. Mitigación de producción: step-up/MFA o botón antes de actuar.

### F3. ¿Qué es "propiedades demostradas"?
**Respuesta.** Además de casos, verificamos invariantes (I1–I8) después de cada turno de conversaciones aleatorias con
Hypothesis: nada se escribe sin un "sí" fresco del mismo cliente, nada ajeno aparece en respuesta, paquete o traza, la
sesión vencida no toca herramientas, etc. Encontró bugs reales (confirmación vieja reutilizada, hilo compartido entre
clientes) que quedaron como regresiones.
**Evidencia.** [`docs/threat-model.md`](../threat-model.md#propiedades-demostradas) · `tests/test_properties.py::test_conversation_invariants` ·
`tests/test_properties.py::test_regression_thread_is_bound_to_its_customer`.
**Límite.** Perfil `ci`: 200 conversaciones con 0 violaciones; la corrida `deep` (5.000) no está publicada. Cero
violaciones acota lo que el generador sabe producir; no ejercita el LLM.
**Repregunta.** *"¿Y el grafo?"* → Ese sí es exhaustivo, pero solo sobre `EDGES` y el enrutamiento de `understand`, no sobre
el contenido de las respuestas.

### F4. ¿Los logs son auditables?
**Respuesta.** Log JSONL con cadena de hashes; `python -m bankagent.audit verify` detecta manipulación, y los PAN/emails no
quedan en conversación, traza ni auditoría (I8). La explicación de cada decisión son IDs de regla más hechos
verificados, no razonamiento oculto.
**Evidencia.** `tests/test_audit.py::test_tampering_is_detected` · `src/bankagent/audit.py`.
**Límite.** Un archivo local con cadena de hashes detecta edición, pero no impide borrar todo: en producción, WORM y
anclaje externo del último hash.
**Repregunta.** *"¿Qué retención?"* → Supuestos en [`docs/operations.md`](../operations.md#5-retención-de-datos-supuestos-a-validar-con-legalcompliance), a validar con Compliance.

---

## G. Producción

### G1. El estado vive en memoria y hay un solo worker. ¿Cómo escala?
**Respuesta.** Hoy es a propósito: `InMemorySaver` y sesiones en memoria, por eso un worker. En producción las réplicas son
sin estado: checkpointer Postgres con TTL, sesiones del IdP y ops transaccional compartido. El código del agente no
cambia; cambian los adaptadores. La prueba de carga de réplicas en procesos (sin estado compartido) llegó a ~98 turnos/s
con 8 réplicas en la laptop.
**Evidencia.** [ADR 0008](../adr/0008-frontend-web.md) §Consecuencias · [`docs/operations.md`](../operations.md#1-topología) ·
[`reports/capacity.md`](../../reports/capacity.md) §2.D y §4.
**Límite.** No probamos el checkpointer Postgres; el rate limit es en memoria y por réplica. Un reinicio borra las
conversaciones en curso.
**Repregunta.** *"¿Cuál es la capacidad de una réplica?"* → ~61 turnos/s con p95 233 ms, sin LLM, en una laptop compartida
(§2.C). Con LLM el límite pasa a ser la cuota del proveedor.

### G2. Cada sesión de demo tiene su propio agente y su propio ops. ¿Eso no es trampa?
**Respuesta.** Es solo para la demo, y está escrito así: cada juez debe poder ver el flujo completo aunque otro ya haya
disputado el mismo cargo (si no, la regla D01 "ya existe una disputa" rompería la demo). Cada login cuesta ~15 ms y
~0.1 MB, con tope de 200 sesiones y TTL de 30 min. En producción el ops es único y transaccional porque una disputa
abierta debe verse desde todos los canales.
**Evidencia.** [`docs/operations.md`](../operations.md#hoy-hackathon) · [ADR 0008](../adr/0008-frontend-web.md) §Decisión 5.
**Límite.** Por eso la demo no prueba concurrencia sobre el mismo ops; eso lo prueba `tests/test_concurrency.py`.
**Repregunta.** *"¿Y la idempotencia?"* → Hoy es "leer y luego insertar"; en producción, llave de idempotencia por acción.

### G3. ¿Cómo lo correrían en un banco real?
**Respuesta.** Mismo agente, otros adaptadores: IdP del banco (OIDC) con MFA y step-up antes de bloquear o disputar;
gateway con TLS, WAF y rate limit global; checkpointer Postgres; ops como APIs del core con llave de idempotencia;
auditoría en WORM con anclaje externo; secretos en KMS; cola durable de handoff al CRM. Y antes que todo: política
real aprobada por Legal/Riesgo, recalibrar el umbral con datos reales y un pentest del agente con LLM.
**Evidencia.** [`docs/operations.md`](../operations.md#producción-propuesta) (diagrama y tabla demo vs producción) ·
[`docs/threat-model.md`](../threat-model.md#qué-falta-para-producción-resumen-honesto).
**Límite.** Nada de esto está implementado; es diseño.
**Repregunta.** *"¿Qué es lo primero que cambiarían?"* → El IdP con step-up: cierra el riesgo residual del consentimiento
léxico y reemplaza la sesión simulada.

### G4. ¿Cómo es el CI/CD y cómo protegen los datos del organizador?
**Respuesta.** CI: tests (681, sin datos ni llaves), guardia de regresión con los dos routers (0 inseguros, handoffs
completos, piso de exactitud), web, e2e con Playwright e imagen Docker. Deploy: un runner efímero baja los datos con
secretos, construye la base de demo, verifica los 14 escenarios y publica en GHCR privado; los datos nunca pasan por el repo.
**Evidencia.** [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) · [`.github/workflows/deploy.yml`](../../.github/workflows/deploy.yml) ·
`scripts/ci_guard.py` · [`docs/operations.md`](../operations.md#deploy-de-la-demo-render).
**Límite.** Plan gratis de Render (512 MB, 0.1 CPU, se duerme); falta escaneo de imagen e imágenes base por digest.
**Repregunta.** *"¿Dependencias?"* → Locks con hash y acciones de GitHub fijadas por SHA (`tests/test_supply_chain.py`).

### G5. ¿Qué monitorearían?
**Respuesta.** Por turno: resultado, reglas disparadas, router que respondió (incluido fallback), latencia por nodo y por
herramienta. Alertas sobre tasa de handoff, fallback del router, acciones no verificadas, bloqueos por seguridad y
deriva de intenciones y equidad por dialecto.
**Evidencia.** [`docs/operations.md`](../operations.md#3-monitoreo) · `src/bankagent/observability.py`.
**Límite.** Las métricas y alertas están diseñadas; lo implementado es el log estructurado de la traza (el evento
por turno y la tasa de error de la API figuran como "por implementar").
**Repregunta.** *"¿Cuál sería su SLO principal?"* → Latencia p95 < 3 s por turno con LLM (alerta si > 5 s por 10 min), y
una alerta con cualquier `action_not_verified` > 0, que se revisa a mano en el core.

---

## H. Curveballs

### H1. ¿Cómo usaron asistentes de IA para construir esto y cómo controlaron la calidad?
**Respuesta.** Mucho, y lo decimos. Usamos Claude Code con subagentes, cada uno en un worktree aislado y una rama por
issue, y todo entró por PR (squash merge) con la CI en verde. **Ojo, dicho con honestidad:** `CONTRIBUTING.md` pide
una aprobación humana por PR, pero por el plazo la mayoría de los PRs los integró el agente orquestador con la CI en
verde, bajo autorización explícita del líder del equipo; no hubo revisión línea a línea de cada PR por otra persona.
Por eso los controles no dependen de confiar en el asistente ni en una revisión humana: CI con tests sin datos ni
llaves, la guardia de regresión con los dos routers, `check_docs.py` que falla si un documento cita un archivo o test
que no existe, y sets de test **congelados por hash** que el generador se niega a reescribir. También usamos
asistentes para escribir el corpus de intención (un autor por sesión aislada) y la traducción al portugués, y eso está
declarado como limitación.
**Evidencia.** [`CONTRIBUTING.md`](../../CONTRIBUTING.md) · `scripts/check_docs.py` · `scripts/ci_guard.py` ·
`tests/test_evals.py::test_frozen_test_set_is_not_overwritten` · [`reports/intent_router.md`](../../reports/intent_router.md) §Datos (procedencia).
**Límite.** Asistentes que escriben código y casos comparten sesgos; por eso el test v3 lo tiene que escribir una
persona que no haya visto el sistema. La revisión humana por PR fue la excepción, no la regla: en un equipo real
activaríamos la protección de rama (1 aprobación obligatoria) y no integraría el agente. La responsabilidad de cada
decisión es del equipo.
**Repregunta.** *"¿Qué hicieron ustedes, entonces?"* → Elegir el flujo y las restricciones, escribir los issues con
criterios de aceptación, revisar los resultados clave (reportes, demos, hallazgos del jurado simulado), decidir los trade-offs de los ADR y declarar las limitaciones. Tengan a mano
un ejemplo concreto de revisión que haya cambiado algo (p. ej. el primer borrador de test 114/115 que se descartó).

### H2. ¿Por qué deberíamos creer cualquier número si todo es sintético?
**Respuesta.** No hay que creerlos como números de producción. Lo que defendemos es el **método**: comparación contra
líneas base en el mismo test, splits que no fugan, cotas en vez de ceros, simulación rotulada y cada límite escrito.
Con datos reales se vuelven a correr los mismos scripts.
**Evidencia.** README §Resultados clave ("medición offline") · [`reports/eval_router.md`](../../reports/eval_router.md) §11.
**Límite.** Ningún número está validado con clientes reales.
**Repregunta.** *"¿Qué número cambiaría más con datos reales?"* → El umbral de fraude (quiebre artificial) y la exactitud
de intención (corpus limpio).

### H3. Su EDA decía que el componente aprendido iba a ser un ranking de transacciones. ¿Qué pasó?
**Respuesta.** Cambiamos de plan con evidencia: la revisión interna tipo jurado marcó que no había nada aprendido en el
camino crítico, y la parte donde las reglas fallaban más era la intención (18.6% de acciones equivocadas), no el
ranking. La búsqueda de la transacción quedó por reglas (monto ±10%, ventana de fecha) y pregunta si hay varias candidatas.
**Evidencia.** [ADR 0009](../adr/0009-router-aprendido.md) §Contexto · [`reports/EDA_findings.md`](../../reports/EDA_findings.md) §3 (plan original).
**Límite.** El ranking aprendido no se evaluó.
**Repregunta.** *"¿La búsqueda por reglas falla?"* → En el replay, 0% de decisiones sobre una transacción distinta a la
emparejada (0/1.000), pero se mide contra una regla de emparejamiento, no contra la verdad.

### H4. ¿Qué pasa si el cliente dice "sí, claro" con sarcasmo?
**Respuesta.** Se toma como sí: es un riesgo residual declarado. El "sí puro" cierra muchos huecos ("sí, al ratito", "sí,
pero…" se re-preguntan), pero un sí hecho solo de palabras afirmativas es indetectable por texto. Por eso la mitigación
es de producto: step-up/MFA o un botón antes de actuar. Y la acción es reversible: una disputa se puede retirar.
**Evidencia.** [`reports/redteam.md`](../../reports/redteam.md) §Riesgos residuales 1 · README §Límites conocidos.
**Límite.** El consentimiento depende de dos listas (`AFFIRM`, `FILLERS`); agregar una palabra ambigua reabre el hueco.
**Repregunta.** *"¿Un LLM no lo detectaría?"* → Quizás, pero no lo medimos; y no queremos que una acción dependa de
interpretar sarcasmo.

### H5. ¿Qué es lo que menos les gusta del sistema?
**Respuesta.** Tres cosas: que el test ya no es ciego (segunda medición y fuga leve), que el consentimiento es léxico, y
que el LLM está apagado y sin evaluar. Las tres tienen un plan concreto: test v3, step-up, y `--system llm` sobre el mismo test.
**Evidencia.** README §Cómo leer el test · [`docs/rubric-evidence.md`](../rubric-evidence.md#límites-declarados-lo-que-no-hacemos-o-no-pudimos-medir).
**Límite.** —
**Repregunta.** *"¿Y el portugués?"* → Cuarto: sin revisión nativa.

### H6. ¿Por qué el agente no promete un reembolso? Eso es lo que el cliente quiere oír.
**Respuesta.** Porque abrir una disputa no es resolverla: el resultado depende del análisis del banco. El verificador del
writer rechaza palabras de promesa (reembolso, abono, plazos) que no estén en el texto fijo de la plantilla.
**Evidencia.** [ADR 0004](../adr/0004-llm-acotado-router-writer.md) §Decisión 3.
**Límite.** El verificador es conservador y puede rechazar paráfrasis válidas; se cae a la plantilla.
**Repregunta.** *"¿Y los plazos regulatorios?"* → Dependen del país; son parte de la política real que falta aprobar.

### H7. ¿Qué pasa si se cae la demo en vivo?
**Respuesta interna (no para el jurado).** No depurar en vivo: pasar a la escena de reserva, luego a la demo local por
consola (`python -m bankagent.chat --customer <ID> --db data/demo/demo.duckdb`), y si todo falla, al video o a las
capturas del deck. Detalle en [`docs/demo-script.md`](../demo-script.md#3-plan-b-si-algo-falla-en-vivo) y en la
[hoja de una página](cheatsheet.md#si-la-demo-en-vivo-falla).
