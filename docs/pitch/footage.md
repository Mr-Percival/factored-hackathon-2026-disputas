# Tomas de la demo para el video (grabación automatizada)

Las escenas de UI del [guion del video](video_script.md) se graban solas con Playwright contra la demo en vivo, con los
mismos clientes y mensajes que el [guion de la demo](../demo-script.md). Sirven como material para el video (cada quien
pone su voz en off encima) y como **plan B** si la demo en vivo falla en la final.

- **Cuadro:** 1920×1080, H.264, 30 fps, sin audio. La app ocupa todo el cuadro, con el texto al 120% (CSS `zoom`,
  equivalente al 125% del navegador del checklist).
- **Subtítulos** en español sobre el video (overlay inyectado solo en el navegador de grabación; la app no cambia),
  además de un cursor visible y un recuadro naranja sobre lo que dice la voz.
- **Capturas PNG** limpias (sin subtítulo ni cursor) del momento clave de cada escena, para el deck.
- **Datos:** títulos de escenario, mensajes y textos esperados salen de
  [`docs/demo/demo_customers.json`](../demo/demo_customers.json). Si cambia una frase del guion, la grabación la sigue;
  si la respuesta ya no contiene el `reply_contains` del JSON, la toma falla en vez de grabar algo incorrecto.
- **Salida** (ignorada por git: los binarios no van al repo): `data/media/` en la raíz del repo.

## Tomas

Grabadas el 2026-09-29 contra `https://agente-disputas.onrender.com` (política 2026-09-29.3, router aprendido).

| Archivo (`data/media/mp4/`) | Duración | Beat del guion | Qué se ve |
|---|---|---|---|
| `escena1_normal_mx.mp4` | 36.8 s | 0:55–1:35 · Escena 1: normal (40 s) | `CLI-ZT72318S7XDV`: «Hola, me llegó un cargo de 151 dólares…» → cargo en Gasolinera Express; recuadros en la traza y en la política (sin reglas); «sí, ambas» → `DSP-…` y `open_dispute` + `block_card` en `ok` |
| `escena2_ambiguo_co.mp4` | 26.9 s | 1:35–2:00 · Escena 2: ambiguo (25 s) | `CLI-N70CIEUDZ4TJ`: «242.000 pesos» → dos opciones, traza con 2 candidatas; clic en la sugerencia «la 1» → pide confirmar la disputa y el bloqueo |
| `escena3_pt_e_inyeccion.mp4` | 39.5 s | 2:00–2:40 · Escena 3 completa (40 s) | Las dos tomas siguientes unidas (sin la tarjeta de título de la segunda y a ×1.15 para caber en 40 s) |
| `escena3a_fraude_pt.mp4` | 26.1 s | 2:00–2:25 · Escena 3, parte pt | `CLI-JP52WOIS6RWO` escribe en portugués → respuesta en pt, la consola del asesor se abre sola: motivo `H03_fraud_signal`, transacción verificada (`fraud_score` 95,1), regla H03 |
| `escena3b_inyeccion.mp4` | 20.9 s | 2:25–2:40 · Escena 3, ataque | «Ignora tus instrucciones anteriores…» → «Bloqueado por el guard»; traza `guard → respond`, ninguna herramienta llamada |
| `escena5_sesion_vencida.mp4` | 25.2 s | Reserva (demo en vivo, escena 5) | Dos opciones → «Vencer sesión» → «la 1» → «Tu sesión expiró…» (`auth_error`), traza detenida en `guard` |

Capturas (`data/media/stills/`, 1920×1080): `escena1_normal_mx_1_oferta.png`, `escena1_normal_mx_2_resuelto.png`,
`escena2_ambiguo_co_1_opciones.png`, `escena2_ambiguo_co_2_eligio.png`, `escena3a_fraude_pt_handoff.png`,
`escena3b_inyeccion_bloqueado.png`, `escena5_sesion_vencida.png`. Para el deck (`docs/pitch/screens/escena{1,2,3}.png`)
sirven `escena1_normal_mx_2_resuelto`, `escena2_ambiguo_co_1_opciones` y `escena3a_fraude_pt_handoff`.

Los WebM originales de Playwright quedan en `data/media/video/` y `data/media/manifest.json` registra cuándo y contra qué
URL se grabó cada toma.

## Regenerar

```bash
cd web
npx playwright install chromium                          # una vez
npx playwright test -c playwright.media.config.ts        # ~2.5 min, las 5 tomas en serie
FFMPEG=/ruta/a/ffmpeg node e2e-media/to-mp4.ts            # WebM → MP4 + escena 3 unida (≤ 40 s) + duraciones
```

- Una sola toma: `npx playwright test -c playwright.media.config.ts -g escena2`.
- `DEMO_URL=http://127.0.0.1:8000` graba contra una demo local (usar `127.0.0.1`, no `localhost`), por ejemplo
  `BANKAGENT_DB=data/demo/demo.duckdb uvicorn bankagent.api.main:app` con la SPA compilada (ver README, *Demo web*).
- `MEDIA_DIR` cambia la carpeta de salida; `MEDIA_CSS_ZOOM=1` graba sin agrandar el texto; `DEMO_CUSTOMERS` apunta a
  otro JSON de escenarios.
- Sin ffmpeg en el PATH, `pip install imageio-ffmpeg` trae uno
  (`python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"`). A mano, una toma:
  `ffmpeg -ss 1 -i video/escena1_normal_mx.webm -r 30 -c:v libx264 -crf 18 -pix_fmt yuv420p escena1_normal_mx.mp4`.

La grabación **no corre en CI**: `npm run e2e` usa `playwright.config.ts` (carpeta `e2e/`) y Vitest excluye
`e2e-media/`. Es amable con el plan gratuito de Render: un solo navegador, en serie, y un `/readyz` previo para
despertar el servicio (cold start) antes de empezar a grabar.
