import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { configDefaults } from "vitest/config";

// https://vite.dev/config/
// En desarrollo la SPA corre en :5173 y /api, /healthz y /readyz se reenvían a uvicorn (:8000), así el
// navegador ve un solo origen y la cookie SameSite=Strict funciona igual que en producción.
const API = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: API, changeOrigin: false },
      "/healthz": { target: API },
      "/readyz": { target: API },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    // Sin módulos inline: la CSP de producción es script-src 'self'.
    assetsInlineLimit: 0,
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    restoreMocks: true,
    // e2e/ es de Playwright (npm run e2e), no de Vitest.
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
});
