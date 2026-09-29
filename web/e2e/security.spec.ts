// Seguridad del navegador (#35): cabeceras seguras, flags de la cookie de sesión, ningún token en respuestas ni en
// el almacenamiento del navegador, y texto del chat pintado como texto plano (sin ejecución de HTML inyectado).
// HSTS y Secure bajo https se prueban en tests/test_api.py (aquí el servidor es http en 127.0.0.1).
import { expect, test, type Response } from "@playwright/test";

import { openDemo, say, startScenario } from "./helpers";

const XSS = '<img src=x onerror="window.__pwned=1;alert(1)"><script>window.__pwned=2</script>';

function directives(csp: string): Map<string, string[]> {
  return new Map(
    csp
      .split(";")
      .map((d) => d.trim().split(/\s+/))
      .filter((parts) => parts[0])
      .map(([name = "", ...values]) => [name, values]),
  );
}

test("cabeceras seguras en la SPA, sus assets y la API", async ({ page, request }) => {
  const seen: Response[] = [];
  page.on("response", (r) => {
    if (r.url().startsWith("http://127.0.0.1")) seen.push(r);
  });
  await openDemo(page);
  expect(seen.some((r) => new URL(r.url()).pathname === "/")).toBe(true);
  expect(seen.some((r) => r.url().includes("/assets/"))).toBe(true);
  expect(seen.some((r) => r.url().includes("/api/scenarios"))).toBe(true);

  for (const r of [...seen, await request.get("/api/nope"), await request.get("/deep/link")]) {
    const h = "allHeaders" in r ? await r.allHeaders() : r.headers();
    const where = new URL(r.url()).pathname;
    const csp = directives(h["content-security-policy"] ?? "");
    expect(csp.get("script-src"), `script-src en ${where}`).toEqual(["'self'"]);
    expect(csp.get("style-src"), `style-src en ${where}`).toEqual(["'self'"]);
    expect(csp.get("object-src")).toEqual(["'none'"]);
    expect(csp.get("base-uri")).toEqual(["'none'"]);
    expect(csp.get("frame-ancestors"), `frame-ancestors en ${where}`).toEqual(["'none'"]);
    expect(h["x-frame-options"]).toBe("DENY");
    expect(h["x-content-type-options"]).toBe("nosniff");
    expect(h["referrer-policy"]).toBe("no-referrer");
    expect(h["permissions-policy"]).toContain("camera=()");
    expect(h["permissions-policy"]).toContain("microphone=()");
    expect(h["permissions-policy"]).toContain("geolocation=()");
    expect(h["strict-transport-security"], "sin HSTS sobre http").toBeUndefined();
    expect(h.server, "sin cabecera Server").toBeUndefined();
    if (where.startsWith("/api/")) expect(h["cache-control"]).toBe("no-store");
  }
});

test("cookie de sesión HttpOnly + SameSite=Strict + Path=/api y ningún token en el navegador", async ({
  page,
  context,
}) => {
  const bodies: string[] = [];
  page.on("response", async (r) => {
    if (r.url().includes("/api/"))
      bodies.push((await r.text().catch(() => "")) + JSON.stringify(r.headers()));
  });
  await openDemo(page);
  await startScenario(page, /Monto alto: handoff/);
  await say(page, "no reconozco el cargo de 1200 del 10/06/2026");
  await page.getByRole("button", { name: /Cambiar a tema/ }).click(); // lo único que se guarda: el tema

  const cookies = await context.cookies();
  expect(cookies.map((c) => c.name)).toEqual(["bankagent_sid"]);
  const [sid] = cookies;
  expect(sid).toMatchObject({ httpOnly: true, sameSite: "Strict", path: "/api", secure: false });

  const browserSide = await page.evaluate(() => ({
    cookie: document.cookie,
    local: Object.fromEntries(Object.entries(localStorage)),
    session: Object.fromEntries(Object.entries(sessionStorage)),
  }));
  expect(browserSide.cookie, "JavaScript no ve la cookie").toBe("");
  expect(Object.keys(browserSide.local)).toEqual(["bankagent-theme"]);
  expect(browserSide.session).toEqual({});

  // Ninguna respuesta de la API expone un token (ni campos llamados token/authorization) ni repite la cookie.
  expect(bodies.length).toBeGreaterThan(3);
  for (const b of bodies) {
    expect(b).not.toMatch(/"(access_|agent_|session_)?token"\s*:/i);
    expect(b).not.toMatch(/authorization|bearer/i);
    expect(b).not.toContain(sid?.value ?? "<sin cookie>");
  }
  for (const v of Object.values(browserSide.local)) expect(v).toMatch(/^(light|dark)$/);
});

test("el texto del chat se pinta como texto plano: HTML inyectado no crea elementos ni se ejecuta", async ({
  page,
}) => {
  const dialogs: string[] = [];
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    void d.dismiss();
  });
  const cspViolations: string[] = [];
  await page.exposeFunction("__reportCsp", (v: string) => cspViolations.push(v));
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => {
      (window as unknown as { __reportCsp: (v: string) => void }).__reportCsp(e.violatedDirective);
    });
  });

  await openDemo(page);
  await startScenario(page, /Monto alto: handoff/);
  // Mensaje de cliente con HTML: aparece en el chat y, tras el handoff, en la consola del asesor.
  await say(page, `no reconozco el cargo de 1200 del 10/06/2026 ${XSS}`);
  await say(page, XSS);
  await expect(page.getByRole("heading", { name: /Motivo:/ })).toBeVisible();
  await page.getByText("Paquete completo (JSON)").click();

  const messages = page.getByRole("list", { name: "Mensajes de la conversación" });
  await expect(messages.getByText(XSS, { exact: true })).toBeVisible(); // el HTML se ve como texto literal
  const state = await page.evaluate(() => ({
    imgs: document.querySelectorAll("img").length,
    scripts: [...document.querySelectorAll("script")].filter((s) => !s.src).length,
    pwned: (window as unknown as { __pwned?: number }).__pwned ?? null,
  }));
  expect(state).toEqual({ imgs: 0, scripts: 0, pwned: null });
  expect(dialogs).toEqual([]);
  expect(cspViolations).toEqual([]); // ni siquiera se intentó ejecutar algo que la CSP tuviera que frenar
});
