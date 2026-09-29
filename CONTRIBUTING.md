# Cómo trabajamos

Equipo de 4 · entrega el **5 de octubre de 2026**. Objetivo: cambios pequeños, siempre con tests verdes y decisiones escritas.

## Flujo de trabajo
1. **Toma un issue** y asígnatelo. Si algo no tiene issue, créalo antes de empezar.
2. **Rama desde `main`:** `tipo/descripcion-corta`, por ejemplo `feat/llm-router`, `fix/guard-pt`, `docs/threat-model`.
3. **Commits** con [Conventional Commits](https://www.conventionalcommits.org/es/): `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.
4. **PR hacia `main`** con la plantilla completa. Se necesita **1 aprobación** y la **CI en verde**. Squash merge.
5. Los PR deben ser chicos (menos de ~400 líneas). Si crece, pártelo.

## Definición de terminado
- [ ] `pytest -q` pasa en local y en CI.
- [ ] Si cambió un comportamiento, hay un test que lo prueba.
- [ ] Si se tomó una decisión de diseño, hay un ADR en `docs/adr/`.
- [ ] Si cambió un flujo o una frontera, `docs/architecture.md` sigue siendo cierto.
- [ ] No hay secretos, datos de clientes ni PDFs en el diff.

## Reglas del diseño (no se negocian en un PR)
- **El modelo no decide la política ni llama herramientas directamente.** La política vive en `config/policy.yaml`.
- **Las herramientas derivan el cliente del token de sesión**, nunca de un parámetro que venga de la conversación.
- **Toda acción requiere confirmación y se verifica** releyendo el estado antes de reportarla.
- Una transición nueva del grafo se declara en `EDGES` (`src/bankagent/graph.py`).
- Los componentes con modelo (router, writer, clasificadores) implementan una interfaz y **tienen una línea base sin modelo** contra la que se evalúan.

## Secretos y datos
- Las credenciales van en `.env` (plantilla: `.env.example`). Nunca en código, notebooks, issues ni PRs.
- El dataset es sintético, pero **no se sube**: se descarga con `scripts/s3_download.py`.
- Antes de enviar texto a un proveedor externo (LLM u otro modelo), pasa por `guard.redact`.

## Documentación
| Qué | Dónde |
|---|---|
| Cómo correr el proyecto | `README.md` |
| Cómo funciona (diagramas) | `docs/architecture.md` |
| Por qué se decidió algo | `docs/adr/NNNN-titulo.md` (plantilla en `docs/adr/0000-template.md`) |
| Hallazgos de datos | `reports/EDA_findings.md` |
| Comentarios en el código | Solo el *por qué*, no el *qué* |

## Setup
Ver `README.md` → *Setup reproducible*. Los tests corren **sin datos reales ni API keys**.

## Demo web (`web/` + `src/bankagent/api/`)
```bash
pip install -e ".[dev,api]"          # FastAPI, uvicorn, httpx (TestClient)
cd web && npm ci                     # Node 22+; se commitea package-lock.json, nunca node_modules/ ni dist/
npm run lint && npm run format:check && npm run typecheck && npm run test && npm run build   # lo mismo que la CI
```
- **Cambió un contrato de la API** (`src/bankagent/api/schemas.py`): `python scripts/export_openapi.py` y
  `cd web && npm run gen:api`, y commitear `web/src/api/openapi.json` + `schema.d.ts`. Un test lo exige.
- La respuesta del agente se pinta como **texto plano**: no usar `dangerouslySetInnerHTML` ni Markdown activo.
- Nada de scripts ni estilos inline en `index.html` (la CSP es `script-src 'self'`).
- Componentes accesibles primero: Radix/shadcn para widgets, consultas por rol en los tests (Testing Library).
- La API no loguea texto del cliente ni devuelve el token del agente; los errores son genéricos.
