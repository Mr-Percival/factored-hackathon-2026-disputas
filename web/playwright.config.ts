// E2E de accesibilidad y seguridad (#35): Playwright + axe-core contra la SPA compilada que sirve FastAPI,
// sobre la base del FIXTURE (datos inventados; sin datos del organizador ni API keys).
//   npm run build && npm run e2e        (E2E_PYTHON=ruta/al/python si `python` no es el del proyecto)
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const PORT = Number(process.env.E2E_PORT ?? 8765);
const python = process.env.E2E_PYTHON ?? "python";

export default defineConfig({
  testDir: "./e2e",
  // Un solo servidor con límites por IP: en serie es determinista y aun así tarda menos de un minuto.
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: `http://127.0.0.1:${String(PORT)}`,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: `"${python}" -m uvicorn bankagent.api.main:app --host 127.0.0.1 --port ${String(PORT)} --no-server-header`, // mismas banderas que docker/entrypoint.sh
    cwd: root,
    url: `http://127.0.0.1:${String(PORT)}/readyz`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      PYTHONPATH: path.join(root, "src"),
      BANKAGENT_DB: "", // vacío = base de demo construida desde el fixture
      BANKAGENT_SCENARIOS: path.join(root, "config", "demo_scenarios.json"),
      BANKAGENT_WEB_DIST: path.join(here, "dist"),
      BANKAGENT_RATE_LIMIT_PER_MIN: "600",
    },
  },
});
