// Accesibilidad automatizada (#35): axe-core con WCAG 2.2 A/AA en los estados clave de la demo, en tema claro y
// oscuro y en ancho de móvil, más un recorrido solo con teclado. Falla con violaciones serias o críticas.
import { expect, test } from "@playwright/test";

import { expectNoSeriousA11yViolations, openDemo, say, startScenario } from "./helpers";

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`axe · escritorio · tema ${colorScheme}`, () => {
    test.use({ colorScheme });

    test("página inicial", async ({ page }, testInfo) => {
      await openDemo(page);
      await expectNoSeriousA11yViolations(page, testInfo, `inicial-${colorScheme}`);
    });

    test("conversación resuelta", async ({ page }, testInfo) => {
      await openDemo(page);
      await startScenario(page, /Disputa normal con bloqueo/);
      await say(page, "No reconozco un cargo de 77 dólares");
      await say(page, "sí");
      await expect(page.getByRole("heading", { name: /Resultado del turno 2/ })).toBeVisible();
      await expect(
        page.getByRole("region", { name: "Explicación y consola del asesor" }).getByText("Resuelto"),
      ).toBeVisible();
      await expectNoSeriousA11yViolations(page, testInfo, `resuelta-${colorScheme}`);
    });

    test("handoff con la consola del asesor abierta", async ({ page }, testInfo) => {
      await openDemo(page);
      await startScenario(page, /Monto alto: handoff/);
      await say(page, "no reconozco el cargo de 1200 del 10/06/2026");
      await expect(page.getByRole("tab", { name: /Consola del asesor/ })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      await expect(page.getByRole("heading", { name: /Motivo:/ })).toBeVisible();
      // El paquete JSON también se revisa desplegado.
      await page.getByText("Paquete completo (JSON)").click();
      await expectNoSeriousA11yViolations(page, testInfo, `handoff-${colorScheme}`);
    });
  });
}

test.describe("axe · móvil 390×844", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  for (const colorScheme of ["light", "dark"] as const) {
    test(`pestañas y handoff · tema ${colorScheme}`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme });
      await openDemo(page);
      await expect(page.getByRole("tablist", { name: "Secciones de la demo" })).toBeVisible();
      await expectNoSeriousA11yViolations(page, testInfo, `movil-inicial-${colorScheme}`);

      await page.getByRole("tab", { name: "Escenarios" }).click();
      await expectNoSeriousA11yViolations(page, testInfo, `movil-escenarios-${colorScheme}`);
      await page
        .getByRole("region", { name: "Escenarios" })
        .getByRole("button", { name: /Monto alto: handoff/ })
        .click();
      await page.getByRole("tab", { name: "Chat" }).click();
      await expect(page.getByRole("textbox", { name: "Mensaje para el agente" })).toBeEnabled();
      await say(page, "no reconozco el cargo de 1200 del 10/06/2026");
      await expectNoSeriousA11yViolations(page, testInfo, `movil-chat-${colorScheme}`);

      // Montada después del handoff, la sección "Por qué" también abre la consola del asesor.
      await page.getByRole("tab", { name: "Por qué", exact: true }).click();
      await expect(page.getByRole("heading", { name: /Motivo:/ })).toBeVisible();
      await expectNoSeriousA11yViolations(page, testInfo, `movil-asesor-${colorScheme}`);

      // Sin desplazamiento horizontal de la página (WCAG 1.4.10 Reflow).
      const overflow = await page.evaluate(() => {
        const vw = document.documentElement.clientWidth;
        const wide = [...document.querySelectorAll("body *")]
          .filter((el) => el.getBoundingClientRect().right > vw + 1)
          .map((el) => el.tagName.toLowerCase() + "." + (el.getAttribute("class") ?? "").slice(0, 60));
        return { extra: document.documentElement.scrollWidth - vw, wide: wide.slice(0, 5) };
      });
      expect(overflow).toEqual({ extra: 0, wide: [] });
    });
  }
});

test.describe("solo teclado", () => {
  test("escenario → mensaje con Enter → traza → consola del asesor", async ({ page }) => {
    await openDemo(page);

    // El primer Tab lleva al enlace "Saltar al contenido", que es visible al recibir el foco.
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Saltar al contenido" });
    await expect(skip).toBeFocused();
    await expect(skip).toBeInViewport();

    // Tab hasta el escenario de monto alto (sin mouse).
    const target = page
      .getByRole("region", { name: "Escenarios" })
      .getByRole("button", { name: /Monto alto: handoff/ });
    await tabUntil(page, target);
    await expectVisibleFocus(page);
    await page.keyboard.press("Enter");

    // Tab hasta el compositor, escribir y enviar con Enter.
    const composer = page.getByRole("textbox", { name: "Mensaje para el agente" });
    await expect(composer).toBeEnabled();
    await tabUntil(page, composer);
    await expectVisibleFocus(page);
    await page.keyboard.type("no reconozco el cargo de 1200 del 10/06/2026");
    await page.keyboard.press("Enter");

    // La respuesta nueva del agente se anuncia en una región aria-live (sin robar el foco).
    const live = page.locator('[aria-live="polite"]', { hasText: /^Agente: / });
    await expect(live).toHaveCount(1);
    await expect(live).toHaveAttribute("aria-atomic", "true");
    await expect(
      page.locator('[aria-live="polite"]', { hasText: /derivado a un asesor humano/ }),
    ).toHaveCount(1);
    await expect(composer).toBeFocused();

    // Tab hasta la pestaña de la consola del asesor (abierta sola por el handoff) y luego la traza con flechas.
    const advisorTab = page.getByRole("tab", { name: /Consola del asesor/ });
    await tabUntil(page, advisorTab);
    await expectVisibleFocus(page);
    await expect(advisorTab).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("ArrowLeft");
    const whyTab = page.getByRole("tab", { name: "Por qué respondió así" });
    await expect(whyTab).toBeFocused();
    await expect(whyTab).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("heading", { name: /Traza del grafo/ })).toBeVisible();
    // Tab entra al panel de la traza (Radix hace el tabpanel enfocable).
    await page.keyboard.press("Tab");
    await expect(page.getByRole("tabpanel", { name: "Por qué respondió así" })).toBeFocused();
    await expectVisibleFocus(page);

    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("ArrowRight");
    await expect(advisorTab).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("tabpanel", { name: /Consola del asesor/ })).toBeFocused();
    await expect(page.getByRole("heading", { name: /Motivo:/ })).toBeVisible();
  });
});

/** Presiona Tab hasta que `target` tiene el foco (máximo 80 pasos: si no llega, hay una trampa o falta orden). */
async function tabUntil(page: import("@playwright/test").Page, target: import("@playwright/test").Locator) {
  for (let i = 0; i < 80; i++) {
    if (await target.evaluate((el) => el === document.activeElement)) return;
    await page.keyboard.press("Tab");
  }
  await expect(target).toBeFocused();
}

/** El elemento con foco muestra un indicador visible (outline o box-shadow), WCAG 2.4.7. */
async function expectVisibleFocus(page: import("@playwright/test").Page) {
  const style = await page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return null;
    const cs = getComputedStyle(el);
    return {
      matches: el.matches(":focus-visible"),
      outline: cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) >= 1,
      shadow: cs.boxShadow !== "none",
    };
  });
  expect(style, "hay un elemento con foco").not.toBeNull();
  expect(style?.matches, ":focus-visible activo con teclado").toBe(true);
  expect(style?.outline === true || style?.shadow === true, "indicador de foco visible").toBe(true);
}
