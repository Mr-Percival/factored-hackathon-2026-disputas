// Overlay de grabación: subtítulos, un cursor visible y un recuadro de "foco". Se inyecta en la página del
// navegador de grabación (no toca el código de la app) y se oculta para las capturas limpias.
import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, type Locator, type Page } from "@playwright/test";

const CSS = `
#media-overlay { position: fixed; inset: 0; pointer-events: none; z-index: 2147483647; font-family: Inter, "Segoe UI", system-ui, sans-serif; }
#media-caption { position: absolute; left: 50%; bottom: 32px; transform: translateX(-50%); max-width: 1150px;
  padding: 14px 28px; border-radius: 14px; background: rgba(15, 23, 42, 0.86); color: #fff; font-size: 25px;
  line-height: 1.3; font-weight: 500; text-align: center; box-shadow: 0 8px 30px rgba(0,0,0,.35);
  opacity: 0; transition: opacity 300ms ease; }
#media-caption.on { opacity: 1; }
#media-caption small { display: block; margin-top: 4px; font-size: 17px; font-weight: 400; color: #cbd5e1; }
#media-spot { position: absolute; border: 4px solid #f59e0b; border-radius: 10px; box-shadow: 0 0 0 9999px rgba(15,23,42,.18);
  opacity: 0; transition: all 350ms ease; }
#media-spot.on { opacity: 1; }
#media-cursor { position: absolute; width: 26px; height: 26px; margin: -13px 0 0 -13px; border-radius: 50%;
  background: rgba(245, 158, 11, .55); border: 3px solid #b45309; left: 50%; top: 50%;
  transition: left 600ms ease, top 600ms ease, transform 120ms ease; }
#media-cursor.press { transform: scale(.7); }
`;

/** Inyecta (o reinyecta tras una navegación) el overlay. */
export async function installOverlay(page: Page) {
  await page.addStyleTag({ content: CSS });
  await page.evaluate(() => {
    if (document.getElementById("media-overlay")) return;
    const root = document.createElement("div");
    root.id = "media-overlay";
    root.setAttribute("aria-hidden", "true");
    for (const id of ["media-spot", "media-caption", "media-cursor"]) {
      const el = document.createElement("div");
      el.id = id;
      root.appendChild(el);
    }
    document.body.appendChild(root);
  });
}

/** Muestra un subtítulo (texto plano; `sub` es una segunda línea más chica). */
export async function caption(page: Page, text: string, sub?: string) {
  await page.evaluate(
    ([t, s]) => {
      const el = document.getElementById("media-caption");
      if (!el) return;
      el.textContent = t ?? "";
      if (s) {
        const small = document.createElement("small");
        small.textContent = s;
        el.appendChild(small);
      }
      el.classList.add("on");
    },
    [text, sub ?? ""],
  );
}

export async function hideCaption(page: Page) {
  await page.evaluate(() => document.getElementById("media-caption")?.classList.remove("on"));
}

/** Recuadra un elemento (se desplaza hasta él primero). `null` quita el recuadro. */
export async function spotlight(page: Page, target: Locator | null, pad = 8) {
  let box: { x: number; y: number; width: number; height: number } | null = null;
  if (target) {
    await target.scrollIntoViewIfNeeded();
    box = await target.boundingBox();
  }
  await page.evaluate(
    ([b, p]) => {
      const el = document.getElementById("media-spot");
      if (!el) return;
      if (!b) {
        el.classList.remove("on");
        return;
      }
      Object.assign(el.style, {
        left: `${b.x - p}px`,
        top: `${b.y - p}px`,
        width: `${b.width + 2 * p}px`,
        height: `${b.height + 2 * p}px`,
      });
      el.classList.add("on");
    },
    [box, pad] as const,
  );
}

async function moveCursor(page: Page, target: Locator) {
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  if (!box) return;
  await page.evaluate(
    ([x, y]) => {
      const el = document.getElementById("media-cursor");
      if (el) Object.assign(el.style, { left: `${x}px`, top: `${y}px` });
    },
    [box.x + box.width / 2, box.y + box.height / 2],
  );
  await page.waitForTimeout(700);
}

/** Clic "visible": el cursor del overlay viaja al elemento y hace un pulso. */
export async function showClick(page: Page, target: Locator) {
  await moveCursor(page, target);
  await page.evaluate(() => document.getElementById("media-cursor")?.classList.add("press"));
  await target.click();
  await page.waitForTimeout(150);
  await page.evaluate(() => document.getElementById("media-cursor")?.classList.remove("press"));
}

const agentReplies = (page: Page) =>
  page.locator('ol[aria-label="Mensajes de la conversación"] > li', {
    has: page.getByText("Agente:", { exact: true }),
  });

/** Última respuesta del agente en el chat. */
export const lastReply = (page: Page) => agentReplies(page).last();

/** Escribe como una persona (tecla por tecla), envía con Enter y espera la respuesta del agente. */
export async function typeAndSend(page: Page, text: string, delay = 55) {
  const before = await agentReplies(page).count();
  const composer = page.getByRole("textbox", { name: "Mensaje para el agente" });
  await moveCursor(page, composer);
  await composer.click();
  await composer.pressSequentially(text, { delay });
  await page.waitForTimeout(400);
  await composer.press("Enter");
  await expect(agentReplies(page)).toHaveCount(before + 1);
  await page.waitForTimeout(300); // que termine de pintar el panel de la derecha
}

/** Espera a que el agente responda después de un clic (opción, respuesta rápida). */
export async function clickAndWaitReply(page: Page, target: Locator) {
  const before = await agentReplies(page).count();
  await showClick(page, target);
  await expect(agentReplies(page)).toHaveCount(before + 1);
  await page.waitForTimeout(300);
}

/** Captura PNG limpia (sin subtítulo ni cursor, con o sin recuadro) en `dir/name.png`. */
export async function still(page: Page, dir: string, name: string, keepSpot = false) {
  mkdirSync(dir, { recursive: true });
  await page.evaluate((keep) => {
    for (const id of ["media-caption", "media-cursor", ...(keep ? [] : ["media-spot"])]) {
      const el = document.getElementById(id);
      if (el) el.style.visibility = "hidden";
    }
  }, keepSpot);
  await page.screenshot({ path: path.join(dir, `${name}.png`), animations: "disabled" });
  await page.evaluate(() => {
    for (const id of ["media-caption", "media-cursor", "media-spot"]) {
      const el = document.getElementById(id);
      if (el) el.style.visibility = "";
    }
  });
}
