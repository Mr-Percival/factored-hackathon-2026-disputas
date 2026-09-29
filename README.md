# Agente de disputas de cargos no reconocidos

Factored AI & Data Hackathon 2026 · Flujo elegido: **intake de cargos no reconocidos / cobros indebidos + bloqueo de tarjeta**.

> El modelo interpreta y redacta; **el código decide y actúa**. Permisos en las herramientas, política en un YAML
> versionado, toda acción con confirmación y verificada, handoff con contexto completo.

- **Para el jurado — cada punto del enunciado con su evidencia:** [`docs/rubric-evidence.md`](docs/rubric-evidence.md)
- Arquitectura y diagramas: [`docs/architecture.md`](docs/architecture.md)
- Por qué este flujo (datos): [`reports/EDA_findings.md`](reports/EDA_findings.md)
- Modelo de amenazas (OWASP Top 10 LLM 2025): [`docs/threat-model.md`](docs/threat-model.md)
- Guion de la demo con clientes reales verificados: [`docs/demo-script.md`](docs/demo-script.md)
- Operación: topología de producción, capacidad medida, monitoreo, runbook y trabajo restante: [`docs/operations.md`](docs/operations.md)

## Por qué este flujo (resumen del EDA)
- Las **quejas** son el 17% de los contactos y tienen el peor FCR (43.6% contra 91.5% en transaccionales), el doble de duración y 63% de seguimiento.
- En PQR, **"Cargo no reconocido" + "Cobro indebido" = 36%** de los casos; el 20% incumple SLA y la mediana de resolución es de 16 días.

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
  guard.py              detección de inyección + enmascarado de PII
  audit.py              log de auditoría JSONL con cadena de hashes (`python -m bankagent.audit verify`)
  understanding.py      interfaz Router + RuleRouter (línea base es/pt)
  responses.py          redacción por plantillas es/pt (línea base)
  llm.py                cliente LLM agnóstico de proveedor (Anthropic + Fake para tests)
  llm_router.py         LLMRouter: salida estructurada validada, cae a reglas ante cualquier falla
  llm_writer.py         LLMWriter + verify_reply: tono/dialecto sin agregar datos, cae a plantillas
  factory.py            build_agent(db, router="rules|llm", writer="templates|llm")
  graph.py              grafo LangGraph con transiciones declaradas y traza
  chat.py               chat de consola
tests/                  fixture de prueba etiquetado + tests de flujo, seguridad y pipeline
scripts/                descarga S3, EDA y demo (select_demo_customers / verify_demo)
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
```

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

## Estado
- [x] EDA y elección del flujo
- [x] Pipeline con contratos, cuarentena, upsert incremental y linaje
- [x] Herramientas con permisos por sesión, política, guard, grafo, línea base es/pt
- [x] 25 tests: flujos normal/ambiguo/handoff, sesión expirada, acceso ajeno, inyección directa e indirecta, señuelo, reintentos
- [x] Router y writer con LLM (salida estructurada, reintentos acotados, fallback a la línea base) y verificador determinista de respuestas
- [ ] Evaluación: línea base contra agente sobre casos reservados; inyección con datasets públicos
- [x] Log de auditoría con cadena de hashes, límite de intentos, modelo de amenazas
- [ ] Interfaz web, deploy, slides y video
