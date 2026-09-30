// Grabación de las escenas del video pitch (docs/pitch/footage.md). NO es parte de CI ni de `npm run e2e`:
//   npx playwright test -c playwright.media.config.ts
// DEMO_URL elige la demo (por defecto el deploy en Render); MEDIA_DIR, dónde quedan videos y capturas
// (por defecto <repo>/data/media, ignorado por git).
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const mediaDir = process.env.MEDIA_DIR ?? path.resolve(here, "..", "data", "media");
const size = { width: 1920, height: 1080 };
// Ventana 1920×1080 tal cual: el video llena el cuadro. El texto se agranda con MEDIA_CSS_ZOOM (1.2 por defecto; lo aplica el overlay
// con CSS `zoom` sobre la app; no se usa deviceScaleFactor, que deja el video en una esquina del cuadro).
export default defineConfig({
  testDir: "./e2e-media",
  // En serie y sin reintentos en paralelo: el plan gratuito de Render no aguanta carga.
  fullyParallel: false,
  workers: 1,
  retries: 1,
  timeout: 180_000,
  expect: { timeout: 60_000 }, // el primer turno puede tardar si Render está despertando (cold start)
  outputDir: path.join(mediaDir, "playwright-output"),
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.DEMO_URL ?? "https://agente-disputas.onrender.com",
    viewport: size,
    deviceScaleFactor: 1,
    video: { mode: "on", size },
    // La CSP de la app (style-src 'self') bloquearía el overlay de subtítulos; solo en este navegador de grabación.
    bypassCSP: true,
    colorScheme: "light",
    locale: "es-CO",
    navigationTimeout: 120_000,
  },
});
