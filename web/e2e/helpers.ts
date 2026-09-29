import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, type TestInfo } from "@playwright/test";

/** Etiquetas de axe-core que cubren WCAG 2.0, 2.1 y 2.2 niveles A y AA. */
export const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];

/**
 * Corre axe sobre la página y falla si hay violaciones serias o críticas. Todas las violaciones (incluidas las
 * moderadas/menores) se adjuntan al reporte de Playwright como evidencia.
 */
export async function expectNoSeriousA11yViolations(page: Page, testInfo: TestInfo, state: string) {
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  await testInfo.attach(`axe-${state}.json`, {
    body: JSON.stringify(
      {
        state,
        url: page.url(),
        violations: results.violations,
        passes: results.passes.length,
        incomplete: results.incomplete.length,
      },
      null,
      2,
    ),
    contentType: "application/json",
  });
  const blocking = results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => ({
      id: v.id,
      impact: v.impact,
      help: v.help,
      targets: v.nodes.map((n) => n.target.join(" ")).slice(0, 5),
    }));
  expect(blocking, `violaciones serias/críticas en "${state}"`).toEqual([]);
}

/** Abre la SPA y espera a que cargue los escenarios (el pie confirma que la base es el fixture). */
export async function openDemo(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("contentinfo")).toContainText("base: fixture de prueba");
}

/** Elige un escenario (login simulado + conversación nueva) desde el panel de escenarios. */
export async function startScenario(page: Page, title: string | RegExp) {
  await page.getByRole("region", { name: "Escenarios" }).getByRole("button", { name: title }).click();
  await expect(page.getByRole("textbox", { name: "Mensaje para el agente" })).toBeEnabled();
}

/** Escribe como el cliente y envía con Enter; espera la respuesta del agente. */
export async function say(page: Page, text: string) {
  const agentReplies = page.locator('ol[aria-label="Mensajes de la conversación"] > li', {
    has: page.getByText("Agente:", { exact: true }),
  });
  const before = await agentReplies.count();
  const composer = page.getByRole("textbox", { name: "Mensaje para el agente" });
  await composer.fill(text);
  await composer.press("Enter");
  await expect(agentReplies).toHaveCount(before + 1);
}
