// Tomas de UI del video pitch (docs/pitch/video_script.md, escenas 1–3 + reserva de sesión vencida).
// Cada test es una toma: abre la demo, elige el escenario, escribe como una persona y se detiene en los momentos
// clave con subtítulos en español. Guarda <MEDIA_DIR>/video/<toma>.webm y <MEDIA_DIR>/stills/<toma>_*.png.
// Los títulos, mensajes y textos esperados salen de docs/demo/demo_customers.json (la misma fuente que la demo).
// Regenerar: npx playwright test -c playwright.media.config.ts   (ver docs/pitch/footage.md)
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page, type TestInfo } from "@playwright/test";

import {
  caption,
  clickAndWaitReply,
  hideCaption,
  installOverlay,
  zoomApp,
  lastReply,
  showClick,
  spotlight,
  still,
  typeAndSend,
} from "./overlay";

interface Turn {
  say?: string;
  action?: string;
  expect?: { reply_contains?: string };
}
interface DemoScenario {
  id: string;
  title: string;
  customer_id: string;
  turns: Turn[];
}

const here = path.dirname(fileURLToPath(import.meta.url));
const customersPath =
  process.env.DEMO_CUSTOMERS ?? path.resolve(here, "..", "..", "docs", "demo", "demo_customers.json");
const scenarios = (JSON.parse(readFileSync(customersPath, "utf8")) as { scenarios: DemoScenario[] })
  .scenarios;

function scenario(id: string) {
  const s = scenarios.find((x) => x.id === id);
  if (!s) throw new Error(`Escenario ${id} no está en ${customersPath}`);
  const says = s.turns
    .filter((t) => t.say)
    .map((t) => ({ text: t.say ?? "", contains: t.expect?.reply_contains }));
  const say = (i: number) => {
    const t = says[i];
    if (!t) throw new Error(`Escenario ${id} no tiene el mensaje ${String(i + 1)}`);
    return t;
  };
  return { ...s, say };
}

/** Espera el texto del JSON en la respuesta, si el JSON lo define. */
async function expectReply(page: Page, contains: string | undefined) {
  if (contains) await expect(lastReply(page)).toContainText(contains);
}

// El config pone outputDir = <MEDIA_DIR>/playwright-output: de ahí sale MEDIA_DIR sin duplicar la lógica.
const mediaDir = (info: TestInfo) => path.dirname(info.project.outputDir);
const stillsDir = (info: TestInfo) => path.join(mediaDir(info), "stills");
const cssZoom = Number(process.env.MEDIA_CSS_ZOOM ?? 1.2); // 1.2 ≈ zoom del navegador del checklist; 1 = sin zoom

const pause = (page: Page, ms: number) => page.waitForTimeout(ms);
const insight = (page: Page) => page.getByRole("region", { name: "Explicación y consola del asesor" });
const section = (page: Page, heading: string) =>
  insight(page)
    .locator("section")
    .filter({ has: page.getByRole("heading", { name: heading }) });

// Despierta el servicio (cold start del plan gratuito) antes de grabar, para que el video no muestre la espera.
test.beforeAll(async ({ request }) => {
  test.setTimeout(240_000);
  for (let i = 0; i < 8; i++) {
    const ok = await request
      .get("/readyz", { timeout: 60_000 })
      .then((r) => r.ok())
      .catch(() => false);
    if (ok) return;
    await new Promise((r) => setTimeout(r, 5_000));
  }
  throw new Error("La demo no respondió /readyz: revisar DEMO_URL o levantar el servidor local");
});

const started = new Map<string, number>();

test.beforeEach(async ({ page }, info) => {
  await zoomApp(page, cssZoom);
  for (let i = 0; ; i++) {
    try {
      await page.goto("/", { waitUntil: "networkidle" });
      break;
    } catch (e) {
      if (i >= 2) throw e;
    }
  }
  await expect(page.getByRole("region", { name: "Escenarios" })).toBeVisible();
  await installOverlay(page);
  started.set(info.title, Date.now());
});

// Guarda el video con un nombre estable y registra la duración aproximada en manifest.json.
test.afterEach(async ({ page }, info) => {
  const video = page.video();
  await page.close();
  if (!video || info.status !== "passed") return;
  const name = info.title.split(" ")[0] ?? "toma";
  const dir = path.join(mediaDir(info), "video");
  mkdirSync(dir, { recursive: true });
  await video.saveAs(path.join(dir, `${name}.webm`));
  const manifestPath = path.join(mediaDir(info), "manifest.json");
  let manifest: Record<string, unknown> = {};
  try {
    manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Record<string, unknown>;
  } catch {
    // primera toma
  }
  manifest[name] = {
    title: info.title,
    seconds: Math.round((Date.now() - (started.get(info.title) ?? Date.now())) / 1000),
    base_url: info.project.use.baseURL,
    recorded_at: new Date().toISOString(),
  };
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
});

async function pickScenario(page: Page, title: string) {
  const button = page.getByRole("region", { name: "Escenarios" }).getByRole("button", { name: title });
  await showClick(page, button);
  await expect(page.getByRole("textbox", { name: "Mensaje para el agente" })).toBeEnabled();
  await pause(page, 600);
}

test("escena1_normal_mx · disputa normal + bloqueo (es-MX)", async ({ page }, info) => {
  const s = scenario("normal_mx");
  await caption(page, "Escena 1 · Disputa normal con bloqueo", `Cliente real de México · ${s.customer_id}`);
  await pause(page, 2500);
  await pickScenario(page, s.title);

  await caption(page, "El cliente no reconoce un cargo de 151 dólares");
  await typeAndSend(page, s.say(0).text);
  await expectReply(page, s.say(0).contains);

  await caption(page, "Busca solo entre SUS transacciones: encuentra el cargo en Gasolinera Express");
  await spotlight(page, lastReply(page));
  await pause(page, 4500);

  await caption(page, "«Por qué respondió así»: router aprendido, nodos del grafo y herramientas");
  await spotlight(page, section(page, "Traza del grafo"));
  await pause(page, 4500);
  await caption(page, "Política: ninguna regla bloquea · ofrece disputa y bloqueo por separado");
  await spotlight(page, section(page, "Política"));
  await pause(page, 3500);
  await still(page, stillsDir(info), "escena1_normal_mx_1_oferta");

  await spotlight(page, null);
  await caption(page, `Responde «${s.say(1).text}»`);
  await typeAndSend(page, s.say(1).text);
  await expectReply(page, s.say(1).contains);
  await expect(lastReply(page)).toContainText("DSP-");

  await caption(page, "Disputa abierta y tarjeta bloqueada", "Resultado: Resuelto");
  await spotlight(page, lastReply(page));
  await pause(page, 4000);
  await caption(
    page,
    "open_dispute y block_card: ambas ok y verificadas",
    "El número DSP-… lo devolvió la verificación, no lo escribió un modelo",
  );
  const tools = section(page, "Traza del grafo")
    .getByRole("list", { name: /Herramientas de/ })
    .last();
  await spotlight(page, tools);
  await pause(page, 5000);
  await still(page, stillsDir(info), "escena1_normal_mx_2_resuelto", true);
  await hideCaption(page);
  await spotlight(page, null);
  await pause(page, 800);
});

test("escena2_ambiguo_co · cargo ambiguo, elige «la 1» (es-CO)", async ({ page }, info) => {
  const s = scenario("ambiguous_co");
  await caption(page, "Escena 2 · Cargo ambiguo", `Cliente real de Colombia · ${s.customer_id}`);
  await pause(page, 1800);
  await pickScenario(page, s.title);

  await caption(page, "«242.000 pesos»: se entiende en miles, al estilo colombiano");
  await typeAndSend(page, s.say(0).text);
  await expectReply(page, s.say(0).contains);
  await expect(lastReply(page).getByRole("group", { name: "Opciones" })).toBeVisible();

  await caption(page, "Coincide con dos cargos: el agente no adivina, muestra las opciones");
  await spotlight(page, lastReply(page));
  await pause(page, 4000);
  await caption(page, "Traza: find_transaction devuelve 2 candidatas");
  await spotlight(page, section(page, "Traza del grafo"));
  await pause(page, 3000);
  await still(page, stillsDir(info), "escena2_ambiguo_co_1_opciones");

  await spotlight(page, null);
  await caption(page, `Solo sigue cuando el cliente elige: «${s.say(1).text}»`);
  const suggested = page
    .getByRole("group", { name: "Mensajes sugeridos" })
    .getByRole("button", { name: s.say(1).text, exact: true });
  await clickAndWaitReply(page, suggested);
  await expectReply(page, s.say(1).contains);

  await caption(page, "Eligió Mercado Central: ahora pide confirmar la disputa y el bloqueo");
  await spotlight(page, lastReply(page));
  await pause(page, 4500);
  await still(page, stillsDir(info), "escena2_ambiguo_co_2_eligio", true);
  await hideCaption(page);
  await spotlight(page, null);
  await pause(page, 800);
});

test("escena3a_fraude_pt · señal de fraude → analista (pt-BR)", async ({ page }, info) => {
  const s = scenario("fraud_pt");
  await caption(page, "Escena 3 · El cliente escribe en portugués", `Señal de fraude · ${s.customer_id}`);
  await pause(page, 1500);
  await pickScenario(page, s.title);

  await caption(page, `«${s.say(0).text}»`);
  await typeAndSend(page, s.say(0).text, 45);
  await expectReply(page, s.say(0).contains);
  const advisor = page.getByRole("tab", { name: /Consola del asesor/ });
  await expect(advisor).toHaveAttribute("aria-selected", "true");

  await caption(page, "Responde en portugués y deriva a un analista de fraude");
  await spotlight(page, lastReply(page));
  await pause(page, 3000);

  await caption(page, "Consola del asesor: se abre sola con el paquete del handoff");
  const reason = insight(page).locator('section[aria-labelledby="advisor-reason"]');
  await spotlight(page, reason);
  await pause(page, 3000);
  await caption(page, "Transacción verificada: fraud_score 95 · leída de las herramientas, no del texto");
  await spotlight(page, insight(page).getByText("Transacción verificada").locator(".."));
  await pause(page, 3000);
  await caption(page, "Regla H03: score ≥ 30 → analista con transacción, regla y traza");
  const rules = insight(page).locator('section[aria-labelledby="advisor-rules"]');
  await spotlight(page, rules);
  await pause(page, 3500);
  await still(page, stillsDir(info), "escena3a_fraude_pt_handoff", true);
  await caption(page, "El asesor no vuelve a preguntar nada");
  await spotlight(page, null);
  await pause(page, 2000);
  await hideCaption(page);
  await pause(page, 400);
});

test("escena3b_inyeccion · intento de inyección bloqueado", async ({ page }, info) => {
  const s = scenario("injection");
  await caption(page, "Escena 3b · Intento de inyección", "Alguien intenta cambiar las reglas");
  await pause(page, 1500);
  await pickScenario(page, s.title);

  await typeAndSend(page, s.say(0).text, 40);
  await expectReply(page, s.say(0).contains);
  await expect(lastReply(page)).toContainText(/Bloquead/i);

  await caption(page, "El guard lo bloquea antes de llegar al router", "Resultado: Bloqueado");
  await spotlight(page, lastReply(page));
  await pause(page, 3000);
  await caption(page, "Traza: se detiene en guard · ninguna herramienta llamada");
  await spotlight(page, section(page, "Traza del grafo"));
  await pause(page, 3500);
  await still(page, stillsDir(info), "escena3b_inyeccion_bloqueado", true);
  await caption(page, "Aunque pasara, no hay con qué hacer daño: el cliente sale del token, no del texto");
  await spotlight(page, null);
  await pause(page, 3500);
  await hideCaption(page);
  await pause(page, 400);
});

test("escena5_sesion_vencida · sesión vencida a mitad de la conversación", async ({ page }, info) => {
  const s = scenario("expired_session");
  await caption(page, "Reserva · Sesión vencida a mitad de la conversación", s.customer_id);
  await pause(page, 1800);
  await pickScenario(page, s.title);

  await typeAndSend(page, s.say(0).text, 45);
  await expectReply(page, s.say(0).contains);
  await caption(page, "El agente ofrece dos opciones…");
  await spotlight(page, lastReply(page));
  await pause(page, 2500);

  await spotlight(page, null);
  await caption(page, "…y la sesión vence (15 min en producción; aquí, con el botón)");
  await showClick(page, page.getByRole("button", { name: "Vencer sesión" }));
  await expect(page.getByText("sesión vencida").first()).toBeVisible();
  await pause(page, 1500);

  await caption(page, `El cliente responde «${s.say(1).text}»`);
  await typeAndSend(page, s.say(1).text);
  await expectReply(page, s.say(1).contains);

  await caption(page, "La sesión se valida en cada turno: ninguna herramienta responde");
  await spotlight(page, lastReply(page));
  await pause(page, 3500);
  await spotlight(page, section(page, "Traza del grafo"));
  await pause(page, 3000);
  await still(page, stillsDir(info), "escena5_sesion_vencida", true);
  await hideCaption(page);
  await spotlight(page, null);
  await pause(page, 800);
});
