# Agente de disputas de cargos no reconocidos

Factored AI & Data Hackathon 2026 · Flujo elegido: **intake de cargos no reconocidos / cobros indebidos + bloqueo de tarjeta**.

> El modelo interpreta y redacta; **el código decide y actúa**. Permisos en las herramientas, política en un YAML
> versionado, toda acción con confirmación y verificada, handoff con contexto completo.

- **Para el jurado — cada punto del enunciado con su evidencia:** [`docs/rubric-evidence.md`](docs/rubric-evidence.md)
- Arquitectura y diagramas: [`docs/architecture.md`](docs/architecture.md)
- Por qué este flujo (datos): [`reports/EDA_findings.md`](reports/EDA_findings.md)
- Evaluación offline (línea base, métricas de la rúbrica, equidad por dialecto): [`reports/eval.md`](reports/eval.md)
- Modelo de amenazas (OWASP Top 10 LLM 2025): [`docs/threat-model.md`](docs/threat-model.md)
- Propiedades demostradas (I1–I8 con Hypothesis sobre conversaciones aleatorias + verificación estática de todos los caminos del grafo): [`docs/threat-model.md#propiedades-demostradas`](docs/threat-model.md#propiedades-demostradas) · caminos: [`docs/graph-paths.md`](docs/graph-paths.md)
- Guion de la demo con clientes reales verificados: [`docs/demo-script.md`](docs/demo-script.md)
- **Demo web** (FastAPI + React, un contenedor): sección [Demo web](#demo-web) · decisión en [ADR 0008](docs/adr/0008-frontend-web.md)
- Operación: topología de producción, capacidad medida, monitoreo, runbook y trabajo restante: [`docs/operations.md`](docs/operations.md)

## Por qué este flujo (resumen del EDA)
- Las **quejas** son el 17% de los contactos y tienen el peor FCR (43.6% contra 91.5% en transaccionales), el doble de duración y 63% de seguimiento.
- En PQR, **"Cargo no reconocido" + "Cobro indebido" = 36%** de los casos; el 20% incumple SLA y la mediana de resolución es de 16 días.

## Replay de quejas históricas (simulación)
Quejas reales de "Cargo no reconocido" / "Cobro indebido" convertidas en conversaciones con un cliente simulado y
pasadas por el agente (reglas + plantillas), cada una juzgada a su fecha de creación; el modo sombra compara la decisión
de la política con el desenlace histórico. Resultados, supuestos y limitaciones: [`reports/replay.md`](reports/replay.md).
```bash
python -m bankagent.evals.replay --db data/serving_full.duckdb --history-db data/bank.duckdb --n 1000 --seed 7
```

## Pitch
- Presentación (6 slides, con notas del orador): [`docs/pitch/deck.pptx`](docs/pitch/deck.pptx) · versión para revisar: [`docs/pitch/deck.md`](docs/pitch/deck.md)
- Guion del video (3:50, es + pt) con lista de tomas y checklist de grabación: [`docs/pitch/video_script.md`](docs/pitch/video_script.md)
- Gráficos: [`docs/pitch/charts/`](docs/pitch/charts/)

```bash
pip install -e ".[pitch]"
PYTHONPATH=src python scripts/make_charts.py            # agregados desde data/bank.duckdb (o --from-cache sin datos; --diagrams para los Mermaid)
PYTHONPATH=src python scripts/make_deck.py              # deck.pptx + deck.md; lista las métricas [[PENDIENTE]] de docs/pitch/metrics.yaml
```

## Estructura
```
config/contracts.yaml   contratos de datos (tipos, dominios, FKs, advertencias)
config/policy.yaml      política SINTÉTICA de disputas (reglas con ID, versionada)
src/bankagent/
  pipeline.py           raw -> serving: contrato, cuarentena, upsert incremental, linaje
  identity.py           sesiones simuladas con expiración (el IdP del banco)
  tools.py              herramientas bancarias: permisos por sesión, acciones verificadas
  policy.py             motor de reglas (expresiones restringidas, sin eval libre)
  guard.py              detección de inyección (interfaz: regex / clasificador ONNX) + enmascarado de PII
  audit.py              log de auditoría JSONL con cadena de hashes (`python -m bankagent.audit verify`)
  evals/                evaluación de inyección: detección (datasets públicos) y daño (agente real)
  understanding.py      interfaz Router + RuleRouter (línea base es/pt)
  responses.py          redacción por plantillas es/pt (línea base)
  llm.py                cliente LLM agnóstico de proveedor (Anthropic + Fake para tests)
  llm_router.py         LLMRouter: salida estructurada validada, cae a reglas ante cualquier falla
  llm_writer.py         LLMWriter + verify_reply: tono/dialecto sin agregar datos, cae a plantillas
  factory.py            build_agent(db, router="rules|llm", writer="templates|llm")
  graph.py              grafo LangGraph con transiciones declaradas y traza
  graph_check.py        verificación estática de EDGES: caminos, alcanzabilidad, predecesores de `act`
  chat.py               chat de consola
  api/                  API FastAPI de la demo web: sesión por cookie, escenarios, turnos con traza, SPA
  evals/                casos reservados (generador), runner con cliente simulado, métricas y reporte
  evals/human_kit.py    evaluación humana de handoffs (build / score / check) + verificador de completitud
  evals/replay.py       replay de quejas históricas por el agente + modo sombra (SIMULACIÓN) -> reports/replay.md
evals/cases/            casos dev/test en JSONL + manifiesto (generados por el equipo, ver su README)
evals/human/            tarjetas de handoff, planillas ciegas por evaluador y RUBRIC.md (clave en _key/)
evals/fixtures/         fixtures del equipo: portugués traducido y mensajes bancarios (con procedencia)
tests/                  fixture de prueba etiquetado + tests de flujo, seguridad, pipeline, evaluación y equidad
scripts/                descarga S3, EDA y demo (select_demo_customers / verify_demo / export_openapi)
web/                    SPA React 19 + TypeScript + Vite (ver web/README.md)
Dockerfile              imagen única: build de web/ + runtime Python con la API
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
verificados) + **consola del asesor humano**, que se abre sola con cada handoff. Siempre en modo reglas + plantillas
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
BANKAGENT_ROUTER=embeddings uvicorn bankagent.api.main:app   # demo web con el router aprendido (por defecto: rules)
pip install -e ".[ml-train]" && PYTHONPATH=src python scripts/train_intent.py   # re-entrenar y regenerar el reporte
```
Sobre el mismo test congelado, contra RuleRouter, la variante que se despliega (lite) obtiene:
- **Intención** (corpus propio, split por autor, n=306): macro-F1 0.868 [0.83, 0.90] contra 0.548. Los mensajes
  que disparan una acción equivocada bajan de 18.6% a 2.6%.
- **Punta a punta** (`evals/cases/test`, 115 casos): 106/115 resultados correctos contra 102/115, y 2 transferencias
  faltantes contra 7. En los dos sistemas hubo 0 resultados inseguros.
- **Costo en el deploy:** +10 MB de RSS y unos +6 ms por turno.

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
- [x] EDA y elección del flujo
- [x] Pipeline con contratos, cuarentena, upsert incremental y linaje
- [x] Herramientas con permisos por sesión, política, guard, grafo, línea base es/pt
- [x] Tests: flujos normal/ambiguo/handoff, sesión expirada, acceso ajeno, inyección directa e indirecta, señuelo, reintentos, métricas de evaluación, equidad por dialecto y evaluación de humo sobre el fixture
- [x] Router y writer con LLM (salida estructurada, reintentos acotados, fallback a la línea base) y verificador determinista de respuestas
- [x] Evaluación: casos reservados (dev/test por cliente y por redacción), runner con métricas de la rúbrica, equidad por dialecto
- [x] Inyección con datasets públicos: detección (regex vs. clasificador) y daño de punta a punta ([reporte](reports/injection_eval.md), [ADR 0005](docs/adr/0005-deteccion-inyeccion.md))
- [x] Componente aprendido en el camino crítico: router de intención local. Se evaluó contra RuleRouter a nivel intención y de punta a punta ([ADR 0009](docs/adr/0009-router-aprendido.md))
- [ ] Evaluación: agente con LLM contra la línea base sobre los mismos casos (LLM apagado: sin API paga)
- [x] Log de auditoría con cadena de hashes, límite de intentos, modelo de amenazas
- [x] Interfaz web (FastAPI + React) en un contenedor, construido y probado en CI
- [ ] Deploy público y video
