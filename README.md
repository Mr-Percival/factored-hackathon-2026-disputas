# Agente de disputas de cargos no reconocidos

Factored AI & Data Hackathon 2026 · Flujo elegido: **intake de cargos no reconocidos / cobros indebidos + bloqueo de tarjeta**.

> El modelo interpreta y redacta; **el código decide y actúa**. Permisos en las herramientas, política en un YAML
> versionado, toda acción con confirmación y verificada, handoff con contexto completo.

- Arquitectura y diagramas: [`docs/architecture.md`](docs/architecture.md)
- Por qué este flujo (datos): [`reports/EDA_findings.md`](reports/EDA_findings.md)

## Por qué este flujo (resumen del EDA)
- Las **quejas** son el 17% de los contactos y tienen el peor FCR (43.6% contra 91.5% en transaccionales), el doble de duración y 63% de seguimiento.
- En PQR, **"Cargo no reconocido" + "Cobro indebido" = 36%** de los casos; el 20% incumple SLA y la mediana de resolución es de 16 días.

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
  understanding.py      interfaz Router + RuleRouter (línea base es/pt)
  responses.py          redacción por plantillas es/pt (línea base)
  graph.py              grafo LangGraph con transiciones declaradas y traza
  chat.py               chat de consola
  demo_fixture.py       fixture etiquetado (tests y demo sin datos reales)
  ui.py                 formato de la demo web (traza, política, handoff)
app/streamlit_app.py    demo web
tests/                  fixture de prueba etiquetado + tests de flujo, seguridad y pipeline
scripts/                descarga S3 y EDA
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
python -m bankagent.pipeline --sample-customers 500 --out data/demo.duckdb   # base liviana para el deploy

python -m bankagent.chat --customer CLI-XXXXXXXX
```

## Demo web (Streamlit)
Chat + traza del turno ("Por qué respondió así": nodos, herramientas, reglas y hechos verificados) + consola del
asesor humano con el paquete de handoff. Sin `BANKAGENT_DB` arma al arrancar una base mínima desde el fixture
(`src/bankagent/demo_fixture.py`); con `BANKAGENT_DB=data/demo.duckdb` usa datos reales.
```bash
pip install -e ".[ui]"
streamlit run app/streamlit_app.py                     # http://localhost:8501
BANKAGENT_DB=data/demo.duckdb streamlit run app/streamlit_app.py

docker build -t bankagent-demo .
docker run --rm -p 8501:8501 bankagent-demo            # -e PORT=... para Render / HF Spaces
```
- **Healthcheck:** `GET /_stcore/health` → `ok` (endpoint nativo de Streamlit), o `python -m bankagent.app_health [--url http://localhost:8501]`.
- **Deploy:** Streamlit Community Cloud (usa `requirements.txt`, archivo `app/streamlit_app.py`), Hugging Face Spaces (Docker) o Render (Docker).
- La lógica de formato vive en `src/bankagent/ui.py` y se prueba sin navegador en `tests/test_ui.py`.

## Qué es real, qué es sintético
| Insumo | Origen |
|---|---|
| Dataset LATAM Bank | Sintético, provisto por el organizador |
| `config/policy.yaml` | Sintético, creado por el equipo (no es la política de ningún banco) |
| Identidad y herramientas | Sandbox simulado por el equipo |
| `src/bankagent/demo_fixture.py` | Fixture de prueba y demo creado a mano por el equipo |

## Estado
- [x] EDA y elección del flujo
- [x] Pipeline con contratos, cuarentena, upsert incremental y linaje
- [x] Herramientas con permisos por sesión, política, guard, grafo, línea base es/pt
- [x] 25 tests: flujos normal/ambiguo/handoff, sesión expirada, acceso ajeno, inyección directa e indirecta, señuelo, reintentos
- [ ] Router y writer con LLM, más un verificador de salida
- [ ] Evaluación: línea base contra agente sobre casos reservados; inyección con datasets públicos
- [ ] Log de auditoría con cadena de hashes, límite de intentos, modelo de amenazas
- [x] Interfaz web de demo (chat + traza + consola de handoff)
- [ ] Deploy, slides y video
