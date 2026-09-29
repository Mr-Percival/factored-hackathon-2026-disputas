# Agente de disputas de cargos no reconocidos

Factored AI & Data Hackathon 2026 · Flujo elegido: **intake de cargos no reconocidos / cobros indebidos + bloqueo de tarjeta**.

Un agente en español y portugués que atiende el reclamo de punta a punta: encuentra el cargo, aplica una política
versionada, pide confirmación por acción, abre la disputa y bloquea la tarjeta **solo si la verificación lo confirma**,
y si no debe resolver pasa el caso a un humano con el paquete completo. **El modelo interpreta; el código decide y actúa.**

| Para el jurado | |
|---|---|
| Demo en vivo | **[https://agente-disputas.onrender.com](https://agente-disputas.onrender.com)** (Render, plan gratis; si tarda ~1 min es el arranque en frío) |
| Cada punto del enunciado con su evidencia | [`docs/rubric-evidence.md`](docs/rubric-evidence.md) |
| Arquitectura y diagramas | [`docs/architecture.md`](docs/architecture.md) · decisiones: [`docs/adr/`](docs/adr/README.md) |
| Deck (6 slides + notas) | [`docs/pitch/deck.pdf`](docs/pitch/deck.pdf) · [`deck.pptx`](docs/pitch/deck.pptx) · [`deck.md`](docs/pitch/deck.md) |
| Video (3:50) | [[PENDIENTE: video]] · guion: [`docs/pitch/video_script.md`](docs/pitch/video_script.md) |
| Guion de la demo (clientes reales, verificado) | [`docs/demo-script.md`](docs/demo-script.md) |
| Seguridad y operación | [`docs/threat-model.md`](docs/threat-model.md) · [`docs/operations.md`](docs/operations.md) |

## Resultados clave

Todo es **medición offline** sobre datos sintéticos del organizador, con casos y clientes simulados generados por el
equipo, salvo donde dice SIMULACIÓN. El sistema de la demo es el **router aprendido** (`embeddings`, lite) + reglas +
plantillas, **sin LLM** (implementado pero apagado: sin API paga).

| Qué | Resultado | Fuente |
|---|---|---|
| Agente de la demo en el test congelado (115 casos + 44 variantes de dialecto, 3 corridas) | **109/115** resultados correctos · resolución automática segura **55/57** · **0/115** inseguros (cota 95% ≤ 2.6%) · 0/38 transferencias faltantes | [`reports/eval_router.md`](reports/eval_router.md) |
| Línea base de reglas (`RuleRouter`, mismo test) | 104/115 correctos · 51/57 · 0/115 inseguros · 7/38 transferencias faltantes | [`reports/eval_router.md`](reports/eval_router.md) |
| Líneas base ingenuas (escala) | B1, automatiza sin política ni confirmación: **82/115 inseguros** · B0, todo a humano: 0/57 resueltos | [`reports/eval.md`](reports/eval.md) |
| Componente aprendido: intención (corpus propio, split por autor, n=306) | macro-F1 **0.877** [0.83, 0.91] vs 0.548 de reglas · mensajes con acción equivocada 1.6% vs 18.6% | [`reports/intent_router.md`](reports/intent_router.md) · [ADR 0009](docs/adr/0009-router-aprendido.md) |
| Inyección con datasets públicos | daño **0/2.531** aun con el guard apagado · detección: regex por defecto; el clasificador (AUC 0.97) queda opt-in por 20/58 falsas alarmas en mensajes bancarios | [`reports/injection_eval.md`](reports/injection_eval.md) · [ADR 0005](docs/adr/0005-deteccion-inyeccion.md) |
| Red team adaptativo del equipo | 3 rondas, 308 ataques: cada ronda encontró daño real (40/110, 34/99, 30/99) que se corrigió en la raíz → **0/308** con ambos routers | [`reports/redteam.md`](reports/redteam.md) |
| Invariantes (I1–I8) y caminos del grafo | Hypothesis sobre conversaciones aleatorias (perfil `ci`: 200 conversaciones, 0 violaciones) + los 19 caminos START→END verificados estáticamente | [`docs/threat-model.md`](docs/threat-model.md#propiedades-demostradas) · [`docs/graph-paths.md`](docs/graph-paths.md) |
| Equidad por dialecto (MX · CO · AR · pt-BR) | 10/11 grupos con la misma decisión | [`reports/eval_router.md`](reports/eval_router.md) |
| Replay de 1.000 quejas históricas | **SIMULACIÓN:** 33.3% [30.4–36.3%] resueltas solas y seguras; 0 acciones inseguras | [`reports/replay.md`](reports/replay.md) |
| Capacidad (una réplica, sin LLM) | ~61 turnos/s, p95 233 ms por turno, costo de modelo $0 | [`reports/capacity.md`](reports/capacity.md) |
| Evaluación humana de handoffs | kit listo (4 evaluadores, 35 paquetes); **calificaciones pendientes** | [`reports/human_eval.md`](reports/human_eval.md) |

> **Cómo leer el test.** Es la **segunda** medición sobre el mismo test congelado (la primera: `embeddings` 106/115,
> `rules` 102/115); las correcciones entre ambas se guiaron solo por dev, la demo y frases propias. En #54 hubo además
> una fuga leve **declarada**: arreglos genéricos después de ver números agregados de test
> ([`evals/cases/README.md`](evals/cases/README.md)). No es un test ciego para estas versiones; un test v3 escrito
> por otra persona lo sería.

## Por qué este flujo (resumen del EDA)
- Las **quejas** son el 17% de los contactos y tienen el peor FCR (43.6% contra 91.5% en transaccionales), el doble de duración y 63% de seguimiento.
- En PQR, **"Cargo no reconocido" + "Cobro indebido" = 36%** de los casos; el 20% incumple SLA y la mediana de resolución es de 16 días.
- Detalle: [`reports/EDA_findings.md`](reports/EDA_findings.md) · decisión: [ADR 0001](docs/adr/0001-flujo-disputas.md).

## Qué entiende el agente (y qué no)
La intención la decide el router aprendido; montos, fechas, país, opción elegida y el "sí" de cada acción los extrae
`RuleRouter` con reglas. Cuando no alcanza, **pregunta en vez de adivinar** y, tras tres aclaraciones, pasa a un humano.

| Funciona bien | Qué hace |
|---|---|
| «Hola, me llegó un cargo de 151 dólares que no reconozco» | busca por monto ±10%, pide confirmar disputa y bloqueo por separado |
| «me aparece un cobro de 242.000 pesos que yo no hice» · «la 1» | varias candidatas: muestra la lista y espera la elección |
| «Oi, não reconheço uma cobrança de 496 dólares no Brasil» | portugués, «no Brasil» como filtro de país |
| «sí, ambas» · «solo la disputa» · «sí, pero no bloquees la tarjeta» | consentimiento por acción |
| «quiero hablar con un asesor» · «me hackearon la cuenta» · «¿en qué va mi disputa?» | humano · seguridad con prioridad · estado de la disputa |

| Límites conocidos | Qué pasa |
|---|---|
| Sin monto, fecha, comercio ni país («no reconozco un cargo») | pide un dato antes de listar |
| Respuestas con condiciones o dudas («sí, al ratito», «creo que sí») | no actúa: re-pregunta una vez y luego pasa a un asesor |
| Sarcasmo hecho solo de palabras de sí («sí, claro») | se toma como sí (riesgo residual 1 de [`reports/redteam.md`](reports/redteam.md); en producción: step-up/MFA antes de actuar) |
| Errores de tipeo fuertes (`hise`, `reconosco`) y otros temas bancarios (préstamos, saldos) | aclaración o handoff `out_of_scope` |

Las sesiones de demo duran 15 minutos y viven en memoria: un reinicio del servidor las borra.

## Pitch
- Deck (6 slides con notas del orador): [`docs/pitch/deck.pdf`](docs/pitch/deck.pdf) · [`deck.pptx`](docs/pitch/deck.pptx) · fuente revisable [`docs/pitch/deck.md`](docs/pitch/deck.md)
- Guion del video (3:50, es + pt) con lista de tomas y checklist de grabación: [`docs/pitch/video_script.md`](docs/pitch/video_script.md)
- Preguntas del jurado (44, con evidencia, límite y repregunta): [`docs/pitch/qa.md`](docs/pitch/qa.md) · hoja de una página (12 números, pitch, plan B de la demo): [`docs/pitch/cheatsheet.md`](docs/pitch/cheatsheet.md)
- Gráficos: [`docs/pitch/charts/`](docs/pitch/charts/) · métricas del deck, cada una con su fuente: [`docs/pitch/metrics.yaml`](docs/pitch/metrics.yaml)

```bash
pip install -e ".[pitch]"
PYTHONPATH=src python scripts/make_charts.py            # agregados desde data/bank.duckdb (o --from-cache sin datos; --diagrams para los Mermaid)
PYTHONPATH=src python scripts/make_deck.py              # deck.pptx + deck.md (cuenta los tests con pytest --collect-only)
python scripts/make_deck_pdf.py --shots                 # deck.html + deck.pdf + captura por slide (Chrome/Edge headless)
python scripts/check_docs.py                            # enlaces y referencias a tests de la documentación (CI)
```

## Replay de quejas históricas (simulación)
Quejas reales de "Cargo no reconocido" / "Cobro indebido" convertidas en conversaciones con un cliente simulado y
pasadas por el agente (reglas + plantillas), cada una juzgada a su fecha de creación; el modo sombra compara la decisión
de la política con el desenlace histórico. Resultados, supuestos y limitaciones: [`reports/replay.md`](reports/replay.md).
```bash
python -m bankagent.evals.replay --db data/serving_full.duckdb --history-db data/bank.duckdb --n 1000 --seed 7
```

## Estructura
```
config/contracts.yaml      contratos de datos (tipos, dominios, FKs, advertencias)
config/policy.yaml         política SINTÉTICA de disputas (reglas con ID, versionada)
config/demo_scenarios.json escenarios de la demo sobre el fixture (sin datos del organizador)
src/bankagent/
  pipeline.py              raw -> serving: contrato, cuarentena, upsert incremental, linaje
  identity.py              sesiones simuladas con expiración (el IdP del banco)
  tools.py                 herramientas bancarias: permisos por sesión, acciones verificadas
  policy.py                motor de reglas (expresiones restringidas, sin eval libre)
  guard.py                 normalización, detección de inyección (regex / clasificador ONNX) y enmascarado de PII
  audit.py                 log de auditoría JSONL con cadena de hashes (`python -m bankagent.audit verify`)
  understanding.py         interfaz Router + RuleRouter (línea base es/pt: slots, idioma, consentimiento)
  intent_model.py          clasificador de intención: n-gramas de caracteres + regresión logística calibrada + abstención
  embedding_router.py      HybridRouter: intención aprendida + slots de RuleRouter (ADR 0009)
  responses.py             redacción por plantillas es/pt (línea base)
  llm.py · llm_router.py · llm_writer.py   cliente LLM, router y writer con fallback y verificador (apagados)
  factory.py               build_agent(db, router="rules|embeddings|embeddings_full|llm", writer="templates|llm")
  graph.py                 grafo LangGraph con transiciones declaradas (EDGES) y traza
  graph_check.py           verificación estática de EDGES -> docs/graph-paths.md
  handoff.py               paquete de handoff versionado (handoff/v1)
  observability.py         log estructurado de la traza (una línea JSON por nodo)
  chat.py                  chat de consola (/trace, /handoff, /expire)
  api/                     API FastAPI de la demo web: sesión por cookie, escenarios, turnos con traza, SPA
  evals/                   casos reservados, runner, métricas, inyección, red team, replay, kit humano
models/intent_router_lite/ artefactos del router que se despliega (0.2 MB) · intent_router_full/ solo offline
corpus/intent/             corpus de intención del equipo (train / test por autor / test de estilo) + guía de etiquetado
evals/cases/               casos dev/test en JSONL + manifiesto (test congelado por hash, ver su README)
evals/redteam/             corpus del red team adaptativo (3 rondas, 308 ataques)
evals/human/               tarjetas de handoff, planillas ciegas por evaluador y RUBRIC.md (clave en _key/)
evals/fixtures/            portugués traducido y mensajes bancarios del equipo (con procedencia)
tests/                     pytest: flujos, seguridad, propiedades, API, evaluación, red team (sin datos ni API keys)
scripts/                   S3, EDA, demo, entrenamiento del router, deck, ci_guard.py, check_docs.py
web/                       SPA React 19 + TypeScript + Vite (ver web/README.md)
Dockerfile · docker/       imagen única: build de web/ + runtime Python con la API (base de demo opcional)
.github/workflows/         ci.yml (tests, guardia, web, e2e, imagen) · deploy.yml (GHCR -> Render) · keepalive.yml
docs/                      arquitectura, ADRs, modelo de amenazas, operación, guion de demo, pitch
reports/                   reportes generados (evaluación, inyección, red team, replay, capacidad, EDA)
```

## Setup reproducible
```bash
python -m venv .venv && .venv/Scripts/activate        # Linux/mac: source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                             # corre sin datos reales ni API keys (fixture)

# Datos reales (credenciales del organizador en .env, NUNCA en el repo)
cp .env.example .env                                  # completar
python scripts/s3_download.py
python -m bankagent.pipeline                          # -> data/serving.duckdb + data/runs/<run>.json

# Base liviana para el deploy (~5 MB): clientes del guion de demo + muestra determinista. Ver docs/demo-script.md
python scripts/select_demo_customers.py                                       # -> docs/demo/demo_customers.json
python -m bankagent.pipeline --out data/demo/demo.duckdb --sample-customers 500 --include-customers docs/demo/demo_customers.json
python scripts/verify_demo.py --db data/demo/demo.duckdb                      # 14/14 escenarios o código 1

python -m bankagent.chat --customer CLI-XXXXXXXX

# Evaluación offline sobre el conjunto reservado -> reports/eval.md
python -m bankagent.evals.cases --db data/serving.duckdb        # verifica evals/cases (test congelado, determinista)
python -m bankagent.evals.run --db data/serving.duckdb --system b0 --system b1 --system rules --repeats 3

# Evaluación de inyección (#8, #9): descarga datasets y modelos a revisión fija (caché de HF, fuera del repo)
pip install -e ".[security-eval]"
python -m bankagent.evals.injection                   # -> reports/injection_eval.md
BANKAGENT_INJECTION_DETECTOR=combined python -m bankagent.chat --customer CLI-XXXXXXXX   # guard regex OR clasificador
```

## Demo web
Tres paneles: **escenarios** (login simulado y guion de un clic por turno), **chat** y **"Por qué respondió así"**
(qué entendió el router, traza del grafo con herramientas e intentos, reglas de la política con su versión, hechos
verificados) + **consola del asesor humano**, que se abre sola con cada handoff. Router aprendido + plantillas por defecto
(sin LLM, sin costo). En pantallas angostas los paneles pasan a pestañas. Detalle del frontend: [`web/README.md`](web/README.md).

```bash
# Desarrollo: API con recarga + Vite con proxy (un solo origen para la cookie)
pip install -e ".[dev,api]"
uvicorn bankagent.api.main:app --reload                 # :8000 (sin BANKAGENT_DB: base del fixture)
cd web && npm ci && npm run dev                          # http://localhost:5173

# Con la base de demo de clientes reales (los escenarios pasan a ser docs/demo/demo_customers.json)
BANKAGENT_DB=data/demo/demo.duckdb uvicorn bankagent.api.main:app

# Producción: un contenedor con API + SPA (opcional: cp data/demo/demo.duckdb docker/demo-db/ antes del build)
docker build -t bankagent-web . && docker run --rm -p 8000:8000 bankagent-web   # http://localhost:8000
```

| Endpoint | Qué hace |
|---|---|
| `GET /api/scenarios` | escenarios de demo desde JSON (se cambian sin tocar código) |
| `POST /api/sessions` `{customer_id}` | login simulado restringido a la allowlist de escenarios; cookie HttpOnly + SameSite=Strict |
| `POST /api/conversations` · `POST /api/conversations/{id}/messages` `{text}` | nueva conversación · turno: respuesta, resultado, qué entendió, decisión, handoff y traza |
| `POST /api/sessions/expire` | control de demo: vence el token del agente |
| `GET /healthz` · `GET /readyz` | liveness · base alcanzable y política cargada |
| `GET /api/docs` | OpenAPI (Swagger UI) |

Configuración por entorno (todas opcionales, ver `src/bankagent/api/config.py`): `BANKAGENT_DB`, `BANKAGENT_SCENARIOS`,
`BANKAGENT_ALLOW_ANY_CUSTOMER=1` (solo local con datos reales), `BANKAGENT_AUDIT_PATH`, `BANKAGENT_CORS_ORIGINS` (solo
dev), `BANKAGENT_COOKIE_SECURE`, `BANKAGENT_RATE_LIMIT_PER_MIN`, `BANKAGENT_DOCS=0`. El token del agente nunca sale del
servidor; el navegador solo tiene un id opaco. Corre con **un worker** porque el estado de la conversación vive en
memoria ([ADR 0008](docs/adr/0008-frontend-web.md)).

## Evaluación humana de los handoffs
Kit para que 4 personas califiquen ~35 paquetes de handoff en menos de 30 minutos cada una. Rúbrica, anclajes e
instrucciones en [`evals/human/RUBRIC.md`](evals/human/RUBRIC.md).
```bash
PYTHONPATH=src python -m bankagent.evals.human_kit build --db data/demo/demo.duckdb --n 30 --seed 11   # regenera el kit
PYTHONPATH=src python -m bankagent.evals.human_kit score "evals/human/sheets/*.csv"                    # -> reports/human_eval.md
PYTHONPATH=src python -m bankagent.evals.human_kit check --db data/demo/demo.duckdb                   # -> reports/handoff_completeness.md
```
`check` es la contraparte automática: campos presentes y no vacíos, y la política re-evaluada con los hechos del
paquete tiene que reproducir las reglas disparadas. Los 5 controles degradados del kit tienen que fallar.

## Router aprendido
La intención del mensaje la puede decidir un **modelo local entrenado por el equipo** en vez de las palabras clave.
El modelo usa n-gramas de caracteres, regresión logística calibrada y abstención. Los slots, el idioma y el
consentimiento siguen saliendo de `RuleRouter`. Corre sin API paga, pesa 0.2 MB y solo necesita numpy.
[ADR 0009](docs/adr/0009-router-aprendido.md) · [evaluación a nivel intención](reports/intent_router.md) ·
[evaluación de punta a punta](reports/eval_router.md).
```bash
pip install -e ".[ml]"                                 # numpy
python -m bankagent.chat --customer CLI-XXXXXXXX --router embeddings   # /trace: embed:char, p, abstención
uvicorn bankagent.api.main:app                         # demo web: router aprendido por defecto (BANKAGENT_ROUTER=rules = línea base)
python scripts/verify_demo.py --db data/demo/demo.duckdb --router embeddings   # y --router rules: ambos 14/14
pip install -e ".[ml-train]" && PYTHONPATH=src python scripts/train_intent.py   # re-entrenar y regenerar el reporte
```
Sobre el mismo test congelado, contra RuleRouter, la variante que se despliega (lite) obtiene:
- **Intención** (corpus propio, split por autor, n=306): macro-F1 0.877 [0.83, 0.91] contra 0.548. Los mensajes
  que disparan una acción equivocada bajan de 18.6% a 1.6%.
- **Punta a punta** (`evals/cases/test`, 115 casos; segunda medición, tras correcciones guiadas solo por dev y la
  demo): 109/115 resultados correctos contra 104/115, 0 transferencias faltantes contra 7 y 0 contenciones con
  resultado incorrecto contra 10. En los dos sistemas hubo 0 resultados inseguros.
- **Costo en la API** (base de la demo, 1 worker): mismo RSS (99 MB listo, 184 MB tras 40 turnos) y turno HTTP p50
  19 ms con los dos routers.

La variante con MiniLM (`--router embeddings_full`) es mejor, pero ocupa ~700 MB de RAM y no entra en el deploy
gratuito, así que solo se usa offline. Si el modelo no carga, responde RuleRouter y la traza lo dice.

## Cómo activar el LLM
El agente funciona completo sin LLM (reglas + plantillas). Para activar el router y/o el writer con modelo:
```bash
pip install -e ".[llm]"                               # agrega el SDK de Anthropic
export ANTHROPIC_API_KEY=...                          # en .env o en el entorno; nunca en el repo
python -m bankagent.chat --customer CLI-XXXXXXXX --router llm --writer llm
# /trace muestra por turno: modelo@versión de prompt, latencia, tokens, costo estimado y si hubo fallback
```
Desde código (UI, evaluación): `build_agent("data/serving.duckdb", router="llm", writer="llm")`.
Modelos por defecto: Claude Haiku 4.5 en ambos (`BANKAGENT_ROUTER_MODEL` / `BANKAGENT_WRITER_MODEL` para
cambiarlos). Sin key, los componentes LLM caen a la línea base y la traza lo registra (`fallback: no_client`).
Qué se envía al proveedor y por qué: [ADR 0004](docs/adr/0004-llm-acotado-router-writer.md).

## Qué es real, qué es sintético
| Insumo | Origen |
|---|---|
| Dataset LATAM Bank | Sintético, provisto por el organizador |
| `config/policy.yaml` | Sintético, creado por el equipo (no es la política de ningún banco) |
| Identidad y herramientas | Sandbox simulado por el equipo |
| `tests/fixture_data.py` | Fixture de prueba creado a mano por el equipo |
| `evals/cases/*.jsonl` | Casos y etiquetas generados por el equipo por construcción; no son tráfico real |

## Estado
- [x] EDA y elección del flujo; pipeline con contratos, cuarentena, upsert incremental y linaje
- [x] Herramientas con permisos por sesión, política versionada, guard, grafo con transiciones declaradas, línea base es/pt
- [x] Consentimiento por acción, conversación libre (pedir humano, toma de cuenta, estado de la disputa) y handoff versionado
- [x] Componente aprendido en el camino crítico: router de intención local, evaluado contra RuleRouter a nivel intención y de punta a punta; la demo lo usa por defecto con fallback visible a reglas ([ADR 0009](docs/adr/0009-router-aprendido.md))
- [x] Evaluación offline: test congelado, líneas base B0/B1, métricas de la rúbrica, equidad por dialecto, variabilidad entre corridas
- [x] Inyección con datasets públicos (detección y daño) y red team adaptativo de 3 rondas con cada ataque como regresión
- [x] Propiedades I1–I8 con Hypothesis y verificación estática de todos los caminos del grafo
- [x] Replay de quejas históricas (simulación), prueba de capacidad, log de auditoría con cadena de hashes, modelo de amenazas
- [x] Router y writer con LLM implementados (salida estructurada, fallback, verificador determinista); **apagados** en la demo y sin evaluar contra la línea base: no hay API paga
- [x] Interfaz web (FastAPI + React) en un contenedor, construida y probada en CI; pipeline de deploy (GitHub Actions → GHCR privado → Render)
- [x] 681 tests (`pytest --collect-only -q`, 2026-09-29) en CI (`pytest -q`, sin datos reales ni API keys) + `scripts/ci_guard.py` + `scripts/check_docs.py`
- [ ] Link público de la demo (deploy en Render)
- [ ] Video del pitch
- [ ] Calificaciones humanas de los handoffs (kit listo, [`reports/human_eval.md`](reports/human_eval.md))
