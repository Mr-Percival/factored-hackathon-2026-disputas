# 0008 · Demo web: FastAPI + React en un contenedor, sesión por cookie opaca

- **Estado:** aceptada (reemplaza la demo Streamlit de #21)
- **Fecha:** 2026-09-28
- **Issue:** #25

## Contexto
La entrega pide una solución desplegada con link en vivo y una demo que haga visible la ingeniería: por qué respondió
así el agente (traza, reglas, hechos verificados) y qué recibe el asesor humano en un handoff. Los jueces van a
escribir libremente en el link. El equipo descartó Streamlit y pidió un frontend con prácticas reconocidas, con
accesibilidad, seguridad y simplicidad por encima del efecto visual.

Restricciones: 4 personas y una semana; LLM apagado (sin gasto: reglas + plantillas); el agente guarda el estado de
la conversación en memoria (`InMemorySaver`) y las acciones en un `ops` en memoria.

## Decisión
1. **Backend:** API FastAPI en `src/bankagent/api/` (estructura "Bigger Applications": `routers/`, `deps.py`,
   `schemas.py` con Pydantic v2 como contrato, OpenAPI en `/api/docs`). Sirve también la SPA compilada: **un solo
   contenedor y un solo origen**.
2. **Frontend:** React 19 + TypeScript estricto + Vite, componentes de shadcn/ui sobre Radix, Tailwind v4, TanStack
   Query para el estado del servidor. Tipos generados del OpenAPI (openapi-typescript) con un test que detecta deriva.
3. **Sesión:** `POST /api/sessions` simula el IdP y guarda el **token del agente en el servidor**. El navegador recibe
   solo un id opaco (`secrets.token_urlsafe(32)`) en una cookie `HttpOnly`, `SameSite=Strict`, `Secure` bajo https,
   `Path=/api`. Cada conversación queda ligada a la sesión que la creó; una ajena responde 404 (no revela existencia).
4. **Un worker uvicorn**, a propósito (Dockerfile + `docker/entrypoint.sh`).
5. **Aislamiento por sesión de demo (solo la API web):** cada login crea su propio `Agent` (checkpointer propio) y su
   propio almacén ops (disputas y bloqueos) como un schema DuckDB dentro de la conexión ops compartida
   (`BankTools.fork_ops`). La conexión de serving (solo lectura) también se comparte, con cursores por hilo. Así la
   demo es repetible para muchos jueces: una sesión nueva empieza limpia y D01 ("ya existe una disputa") solo refleja
   acciones de esa misma sesión. Al cerrar sesión, reemplazarla o vencer su TTL (30 min) se borran el schema y el
   agente. Hay un tope de 200 sesiones simultáneas (luego 429 `too_many_sessions`). Costo medido: ~15 ms y ~0,1 MB de agente
   por login (más las filas de la sesión). Un `:memory:` DuckDB por sesión costaba ~3,8 MB y se descartó.
   **Es una decisión de demo:** en producción el almacén ops es uno solo y transaccional (una disputa existe para
   todos los canales). La consola, la evaluación y los tests siguen usando el almacén por defecto (`ops_schema=None`),
   sin cambios de comportamiento.

## Alternativas consideradas
| Opción | A favor | En contra |
|---|---|---|
| Streamlit (#21) | Rápido de escribir, todo en Python | Rerun por interacción y estado en el servidor de Streamlit; poco control de accesibilidad (roles, live regions, foco), de cabeceras (CSP) y del modelo de sesión; el equipo lo descartó |
| Gradio / Chainlit | Chat listo | Mismo problema de control; la pieza diferencial (traza, consola del asesor) igual se construye a mano |
| Next.js / SSR | Ecosistema grande | Otro runtime (Node) en producción y más superficie; no hay SEO ni contenido por servidor que lo justifique |
| **React + Vite (SPA) servida por FastAPI** | Estático + una API tipada; un contenedor; CSP estricta posible; tests de UI con Testing Library | Dos toolchains (npm + pip) y un paso de build |
| Token del agente en `localStorage` / header `Authorization` | Simple, sin cookies | Legible por cualquier script (XSS → robo de sesión); la cookie HttpOnly no lo es |
| JWT firmado en la cookie | Sin estado en el servidor | Revocar/vencer exige lista negra; el estado del agente igual está en memoria. Id opaco + mapa en servidor es más simple y revocable |

## Modelo de seguridad del canal
- **Robo de sesión por XSS:** la cookie es HttpOnly; la respuesta del agente se pinta como texto (sin HTML/Markdown
  activo, OWASP LLM05); CSP `default-src 'self'; script-src 'self'` sin `unsafe-inline`, `frame-ancestors 'none'`,
  `object-src 'none'`, `base-uri 'none'`. La única excepción es `/api/docs` (Swagger UI), apagable con `BANKAGENT_DOCS=0`.
- **CSRF:** `SameSite=Strict` + verificación de `Origin` en métodos que cambian estado (403 si es ajeno) + cuerpos JSON.
  CORS cerrado por defecto; `BANKAGENT_CORS_ORIGINS` solo para desarrollo.
- **Abuso y consumo (LLM10):** mensaje ≤ 1.000 caracteres (422), cuerpo ≤ 16 KB (413, también chunked), 30
  mensajes/min por sesión y 30 logins/min por IP (429 con `Retry-After`), sesiones y conversaciones acotadas en número.
- **Fugas:** errores genéricos (sin stack trace ni eco del texto: el 422 por defecto de FastAPI devuelve el `input` y se
  reemplaza), sin cabecera `Server`, `Cache-Control: no-store` en la API, logs sin texto del cliente.
- **Login:** restringido a la allowlist de escenarios (`BANKAGENT_ALLOW_ANY_CUSTOMER=1` solo para uso local con datos
  reales). Sigue siendo un IdP simulado: sin MFA ni step-up (ver `threat-model.md`).
- **Concurrencia:** turnos en paralelo sobre los cursores por hilo de `BankTools` (#29); test HTTP con clientes en
  paralelo que verifica que nadie ve datos de otro (incluido el señuelo).

## Consecuencias
- **Un worker y estado en memoria:** un reinicio o un deploy borra sesiones y conversaciones pendientes. La SPA lo
  detecta (401/404) y lo explica ("la conversación se reinició") en vez de mostrar un error. Escalar horizontalmente
  exige checkpointer durable (p. ej. `langgraph-checkpoint-postgres`), sesiones y `ops` compartidos — trabajo listado
  en `docs/operations.md`, no en este PR.
- El rate limit es en memoria y por réplica; detrás de un proxy depende de `X-Forwarded-For` (`--proxy-headers`), que
  debe restringirse a la IP del proxy (`FORWARDED_ALLOW_IPS`) si el contenedor se expone directo.
- Contratos abiertos: resultados, motivos de handoff y acciones son `str` (valores conocidos documentados) y los campos
  nuevos del paquete de handoff pasan en `extra`, así los cambios del grafo (#38–#44) no rompen la API ni la UI.
- Dos toolchains en CI (job `web` + job `image` que construye y prueba el contenedor).

## Referencias
FastAPI "Bigger Applications" · OWASP Secure Headers Project · OWASP ASVS 4.0 (V3 sesiones, V13 API, V14 config) ·
OWASP Top 10 LLM 2025 (LLM05, LLM10) · MDN `Set-Cookie` / CSP · WAI-ARIA APG · WCAG 2.2 · react.dev · shadcn/ui · Radix.
