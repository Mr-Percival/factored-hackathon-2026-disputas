# Demo web (`web/`)

SPA en **React 19 + TypeScript (strict) + Vite** que habla con la API FastAPI (`src/bankagent/api/`). En producción la
sirve el mismo proceso FastAPI (un contenedor, mismo origen); en desarrollo, Vite con proxy a uvicorn.

```bash
# terminal 1 (raíz del repo)
pip install -e ".[dev,api]"
uvicorn bankagent.api.main:app --reload            # :8000 · sin BANKAGENT_DB usa el fixture

# terminal 2
cd web
npm ci
npm run dev                                          # http://localhost:5173 (proxy /api -> :8000)
```

| Comando                           | Qué hace                                                                                                       |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `npm run dev`                     | Vite en :5173 con proxy de `/api`, `/healthz`, `/readyz` a `VITE_API_TARGET` (default `http://127.0.0.1:8000`) |
| `npm run lint`                    | ESLint (typescript-eslint _strict type-checked_, React Hooks, jsx-a11y _strict_), sin warnings                 |
| `npm run format` / `format:check` | Prettier                                                                                                       |
| `npm run typecheck`               | `tsc -b` en modo estricto (`noUncheckedIndexedAccess`, etc.)                                                   |
| `npm run test`                    | Vitest + Testing Library (jsdom) con una API falsa tipada                                                      |
| `npm run build`                   | `dist/` (lo sirve FastAPI)                                                                                     |
| `npm run gen:api`                 | Regenera `src/api/schema.d.ts` desde `src/api/openapi.json`                                                    |

## Contrato con la API

Los tipos **no se escriben a mano**: `python scripts/export_openapi.py` exporta el OpenAPI de FastAPI a
`src/api/openapi.json` y `npm run gen:api` genera `src/api/schema.d.ts` con openapi-typescript. `src/api/types.ts` es
el único lugar que nombra esos tipos. Si el backend cambia un contrato sin regenerar, falla
`tests/test_api.py::test_committed_openapi_matches_the_app` (Python) o `npm run typecheck` (web).

## Estructura

```
src/api/          cliente HTTP tipado (errores -> ApiError), tipos generados
src/state/        useDemo: TanStack Query para el estado del servidor + reducer para la transcripción
src/components/   ScenarioPanel · ChatPanel · InsightPanel (WhyPanel + AdvisorConsole) · ui/ (shadcn/ui)
src/lib/          outcomes (etiqueta + ícono + tono por resultado), tema, utilidades
src/test/         setup de Vitest y respuestas de ejemplo con la forma del contrato
```

## Decisiones de UI (y de dónde salen)

- **Accesibilidad (WCAG 2.2 AA):** foco visible en todo control; el resultado de cada turno lleva ícono + texto (el
  color nunca es la única señal, 1.4.1); contraste ≥ 4.5:1 en claro y oscuro; "Saltar al contenido"; respeta
  `prefers-reduced-motion`.
- **Chat:** la última respuesta del agente se anuncia en una región `aria-live="polite"` (no toda la lista, para no
  repetir); Enter envía y Shift+Enter agrega línea (sin cortar la composición de un IME); contador de caracteres
  ligado con `aria-describedby`; los errores de la API aparecen en un `role="alert"` que se puede cerrar.
- **Pestañas:** Radix Tabs (patrón _Tabs_ del WAI-ARIA APG: flechas para moverse). En pantallas < 1024 px la demo pasa
  de 3 columnas a pestañas; con un handoff la consola del asesor se abre sola y se anuncia sin robar el foco.
- **Seguridad:** la respuesta se pinta como **texto plano** (nunca HTML/Markdown: OWASP LLM05). El navegador no ve
  ningún token: la sesión es una cookie HttpOnly. La CSP de producción es `script-src 'self'` sin `unsafe-inline`,
  por eso el tema oscuro sale de CSS (`prefers-color-scheme` + clase en `<html>`) y no de un script inline.
- **Resiliencia:** si el servidor se reinició y ya no conoce la conversación o la sesión, la UI lo explica y abre una
  nueva en vez de mostrar un error. Resultados, motivos y campos de handoff desconocidos se muestran genéricos.

## Referencias

- Vite: <https://vite.dev/guide/> y configuración de proxy <https://vite.dev/config/server-options#server-proxy>
- React: <https://react.dev/> ("You Might Not Need an Effect", `useSyncExternalStore`)
- TanStack Query: <https://tanstack.com/query/latest/docs/framework/react/overview>
- shadcn/ui: <https://ui.shadcn.com/> · Radix UI Primitives: <https://www.radix-ui.com/primitives>
- Tailwind CSS v4: <https://tailwindcss.com/docs>
- WAI-ARIA Authoring Practices Guide: <https://www.w3.org/WAI/ARIA/apg/> (Tabs, live regions)
- WCAG 2.2: <https://www.w3.org/TR/WCAG22/>
- Nielsen Norman Group, heurísticas de usabilidad: <https://www.nngroup.com/articles/ten-usability-heuristics/>
  (visibilidad del estado, prevención de errores, ayuda para recuperarse)
- Testing Library (consultas por rol, como un usuario): <https://testing-library.com/docs/queries/about/#priority>
- openapi-typescript: <https://openapi-ts.dev/>
- OWASP Secure Headers Project: <https://owasp.org/www-project-secure-headers/> · OWASP ASVS:
  <https://owasp.org/www-project-application-security-verification-standard/>
