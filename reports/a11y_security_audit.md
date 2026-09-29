# Auditoría de accesibilidad y seguridad del navegador (demo web) · #35

> Qué se auditó, con qué, qué se encontró y qué se corrigió. Todo es reproducible: `cd web && npm run build && npm run e2e`
> (o el job `e2e` de la CI). Corre contra la SPA compilada servida por FastAPI sobre la **base del fixture** (datos
> inventados; sin datos del organizador ni API keys). Fecha: 2026-09-29.

## Herramientas

| Herramienta | Versión | Uso |
| --- | --- | --- |
| Playwright (`@playwright/test`) | 1.63.0 | Navegador real (Chromium 153, Chrome for Testing), recorrido con teclado, cookies y almacenamiento |
| axe-core (`@axe-core/playwright`) | 4.13.0 | Reglas `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22a`, `wcag22aa`. **Falla con violaciones `serious` o `critical`**; todas (incluidas moderadas/menores) quedan adjuntas al reporte de Playwright como JSON |
| pytest + TestClient | (requirements/ci.lock) | Cabeceras bajo **https** (HSTS, cookie `Secure`), que el e2e sobre http no puede ver |
| ESLint `jsx-a11y` (strict) | ya existente | Estático, en el job `web` |

Pruebas: [`web/e2e/a11y.spec.ts`](../web/e2e/a11y.spec.ts), [`web/e2e/security.spec.ts`](../web/e2e/security.spec.ts),
[`web/playwright.config.ts`](../web/playwright.config.ts), `tests/test_api.py::test_spa_security_headers_and_hsts_under_https`.
Tiempo: 12 pruebas en ~27 s locales (servidor incluido); el job completo de la CI apunta a < 4 min.

## Estados cubiertos por axe (14 escaneos)

| Estado | Escritorio 1440×900 claro | Escritorio oscuro | Móvil 390×844 claro | Móvil oscuro |
| --- | --- | --- | --- | --- |
| Página inicial (escenarios cargados) | ✓ | ✓ | ✓ | ✓ |
| Pestaña "Escenarios" (móvil) | — | — | ✓ | ✓ |
| Conversación **resuelta** (disputa de 77 USD confirmada) | ✓ | ✓ | — | — |
| Chat tras un **handoff** (móvil) | — | — | ✓ | ✓ |
| **Handoff** con la consola del asesor abierta y el JSON desplegado | ✓ | ✓ | ✓ | ✓ |

El tema se fija con `prefers-color-scheme` (el mismo juego de tokens que la clase `.dark`), así axe mide el contraste
real de cada tema.

Además, sin axe:

- **Solo teclado:** primer Tab → "Saltar al contenido" visible; Tab hasta un escenario → Enter; Tab al compositor,
  escribir y **Enter** envía; la respuesta nueva está en una región `aria-live="polite"` `aria-atomic` y el handoff
  se anuncia en otra, **sin mover el foco** del compositor; Tab a la pestaña de la consola del asesor, flechas a
  "Por qué respondió así" (traza del grafo) y Tab entra al panel. En cada parada se exige `:focus-visible` con
  contorno visible (WCAG 2.4.7) y se detecta trampa de foco (tope de 80 Tabs).
- **Reflow (WCAG 1.4.10):** a 390 px no hay desplazamiento horizontal ni elementos que salgan del viewport.

## Seguridad verificada desde el navegador

| Control | Cómo se prueba | Resultado |
| --- | --- | --- |
| CSP `script-src 'self'` y `style-src 'self'` (sin `unsafe-inline`), `object-src 'none'`, `base-uri 'none'`, `frame-ancestors 'none'` | Todas las respuestas que carga la página (HTML, assets con hash, `/api/*`) + 404 de API + ruta profunda de la SPA | ✓ |
| `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy` (cámara, micrófono, geolocalización…) | Ídem | ✓ |
| HSTS solo bajo https | e2e: ausente sobre http; pytest: `max-age=31536000; includeSubDomains` en `/`, assets y API con `https://` | ✓ |
| Sin cabecera `Server` | e2e (uvicorn con `--no-server-header`, como `docker/entrypoint.sh`) y smoke test del contenedor en la CI | ✓ |
| Cookie `bankagent_sid`: `HttpOnly`, `SameSite=Strict`, `Path=/api`, `Secure` bajo https | `context.cookies()` en Playwright; `Secure` en pytest con https | ✓ |
| Ningún token del agente en el navegador | `document.cookie` vacío; `localStorage` solo tiene `bankagent-theme` (`light`/`dark`); `sessionStorage` vacío; ninguna respuesta de `/api` trae campos `token`/`authorization`/`bearer` ni repite el id de sesión. (El valor exacto del token del servidor se compara en `tests/test_api.py::test_cookie_is_httponly_strict_and_token_never_leaves_the_server`) | ✓ |
| La UI pinta texto plano (OWASP LLM05) | Se envía `<img src=x onerror=…alert(1)><script>…</script>` como mensaje del cliente (también dentro de un mensaje que termina en handoff, así aparece en la consola del asesor y en el JSON): se ve literal, 0 `<img>`, 0 `<script>` inline, sin `alert`, sin efecto en `window`, sin violaciones de CSP | ✓ |

## Hallazgos: antes → después

"Antes" es `origin/main` con las mismas pruebas; "después", esta rama.

| # | Hallazgo | Severidad | Dónde | Antes | Después | Corrección |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `scrollable-region-focusable`: el `<pre>` del paquete JSON del handoff se desplaza pero no se alcanza con teclado (WCAG 2.1.1) | axe **serious** | Consola del asesor (claro y oscuro) | 2 escaneos fallan (1 nodo c/u) | 0 | `<pre tabIndex=0 role="region" aria-label>`; por el mismo motivo el historial del chat es una región enfocable con nombre |
| 2 | El primer Tab de la página no llegaba a "Saltar al contenido": saltaba a las pestañas del panel derecho (WCAG 2.4.1 / 2.4.3). `scrollIntoView` del chat movía el punto de partida de la navegación secuencial | Teclado (bloqueante) | Carga inicial | Falla | Pasa | El chat desplaza su propio contenedor (`scrollTop`) en vez de `scrollIntoView` |
| 3 | Desborde horizontal de 27 px a 390 px: la pestaña "Consola del asesor" + contador de casos no se partía (`whitespace-nowrap`) (WCAG 1.4.10) | Reflow | Móvil, tras un handoff | Falla | 0 px | `TabsTrigger` con `min-w-0`, texto que puede partirse y padding compacto en pantallas chicas |
| 4 | En móvil, al abrir "Por qué" después de un handoff la consola del asesor no se abría (el panel se monta después del evento y arrancaba en "Por qué respondió así"), contra lo que promete la UI | Funcional / a11y | Móvil | Falla | Pasa | `InsightPanel` arranca en la consola si ya hay un handoff |
| — | Violaciones axe moderadas/menores | — | 14 estados | 0 | 0 | — |
| — | Contraste de color (`color-contrast`, WCAG 1.4.3) | — | 14 estados, ambos temas | 0 | 0 | Ya verificado en los tokens de `web/src/index.css` |

Sin hallazgos de seguridad en la SPA: todas las comprobaciones de la tabla anterior pasaron ya en `origin/main`. Se
sumó la verificación de la cabecera `Server` al smoke test del contenedor (antes solo se miraba la CSP) y la de HSTS
+ set completo de cabeceras para la SPA bajo https en pytest.

## Riesgo residual y lo que no se hizo

- **Sin prueba manual con lectores de pantalla** (NVDA, JAWS, VoiceOver, TalkBack). axe detecta ~30–50 % de los
  problemas WCAG; la verificación de las regiones vivas es estructural (existen, son `polite`/`atomic` y cambian),
  no de lo que efectivamente se lee.
- Solo Chromium. Firefox y WebKit (Safari) no se corren para mantener el job corto.
- Sin prueba de zoom a 200 %/400 % ni de espaciado de texto (1.4.4, 1.4.12) más allá del reflow a 390 px; tampoco
  de modos de alto contraste forzado de Windows.
- Los criterios que axe marca como "incompletos" (requieren revisión humana, p. ej. contraste sobre fondos mixtos)
  no se revisaron uno a uno.
- `/api/docs` (Swagger UI) relaja la CSP y queda fuera de esta auditoría; se apaga con `BANKAGENT_DOCS=0`.
- El e2e corre sobre http en `127.0.0.1`; `Secure` y HSTS se prueban con TestClient (https simulado), no con TLS real
  detrás del proxy de la plataforma.
