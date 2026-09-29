import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { RESTART_CONVERSATION } from "@/state/useDemo";
import { clarifyTurn, handoffTurn, scenarios, session } from "@/test/fixtures";
import { media } from "@/test/setup";

interface Reply {
  status?: number;
  body?: unknown;
}
type Handler = (body: unknown) => Reply;

/** Servidor falso: rutas de la API -> respuestas del contrato. Registra lo que envió la SPA. */
function fakeApi(routes: Record<string, Handler | Handler[]>) {
  const calls: { key: string; body: unknown }[] = [];
  const queues = new Map(Object.entries(routes).map(([k, v]) => [k, Array.isArray(v) ? [...v] : v]));
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
    const method = init?.method ?? "GET";
    const key = `${method} ${path.replace(/\/c_[\w-]+\//, "/{id}/")}`;
    const body: unknown = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ key, body });
    const entry = queues.get(key);
    const handler = Array.isArray(entry) ? (entry.length > 1 ? entry.shift() : entry[0]) : entry;
    const reply = handler
      ? handler(body)
      : { status: 404, body: { error: { code: "not_found", message: "no" } } };
    return Promise.resolve(
      new Response(reply.body === undefined ? null : JSON.stringify(reply.body), {
        status: reply.status ?? 200,
        headers: { "content-type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

const baseRoutes = {
  "GET /api/scenarios": () => ({ body: scenarios }),
  "POST /api/sessions": () => ({ status: 201, body: session }),
  "POST /api/conversations": [
    () => ({ status: 201, body: { conversation_id: "c_1" } }),
    () => ({ status: 201, body: { conversation_id: "c_2" } }),
  ],
};

function renderApp() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

async function startFirstScenario(user: ReturnType<typeof userEvent.setup>) {
  const panel = await screen.findByRole("region", { name: "Escenarios" });
  await user.click(within(panel).getByRole("button", { name: /Disputa normal con bloqueo/ }));
  await screen.findByText(/Sesión simulada como CLI-ANA/);
}

describe("demo web", () => {
  it("muestra escenarios, el aviso del sandbox y el modo sin LLM; el chat espera una sesión", async () => {
    fakeApi(baseRoutes);
    renderApp();
    expect(await screen.findAllByRole("button", { name: /Monto alto: handoff a analista/ })).not.toHaveLength(
      0,
    );
    expect(
      screen.getByText(/Sandbox con datos sintéticos · política sintética · no mueve dinero/),
    ).toBeInTheDocument();
    expect(screen.getByText("Sin LLM")).toBeInTheDocument(); // el router se conoce con el primer turno
    expect(
      screen.getByText(/cargos no reconocidos, cobros indebidos y bloqueo de tarjeta/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Mensaje para el agente")).toBeDisabled();
  });

  it("envía un mensaje con Enter y muestra la respuesta con su resultado (ícono + texto) y la traza", async () => {
    const calls = fakeApi({
      ...baseRoutes,
      "POST /api/conversations/{id}/messages": () => ({ body: clarifyTurn }),
    });
    const user = userEvent.setup();
    renderApp();
    await startFirstScenario(user);

    const input = screen.getByLabelText("Mensaje para el agente");
    await user.type(input, "No reconozco un cargo{Shift>}{Enter}{/Shift}de 77 dólares");
    expect(calls.filter((c) => c.key.includes("messages"))).toHaveLength(0); // Shift+Enter no envía
    await user.keyboard("{Enter}");

    const log = screen.getByRole("list", { name: "Mensajes de la conversación" });
    expect(await within(log).findByText(/¿Confirmas\?/)).toBeInTheDocument();
    expect(calls.find((c) => c.key.includes("messages"))?.body).toEqual({
      text: "No reconozco un cargo\nde 77 dólares",
    });
    expect(within(log).getByText("Aclaración")).toBeInTheDocument();
    expect(screen.getByText("Modo reglas (sin LLM)")).toBeInTheDocument(); // cabecera: router del último turno
    // la respuesta nueva se anuncia en la región viva
    expect(document.querySelector('[aria-live="polite"]')).toHaveTextContent(/Agente: Encontré el cargo/);
    // "Por qué respondió así": traza con herramientas fallidas/ok e intentos, y política
    const trace = screen.getByRole("list", { name: "Pasos del grafo en orden" });
    expect(
      within(trace)
        .getAllByRole("listitem")
        .filter((li) => li.parentElement === trace),
    ).toHaveLength(5);
    expect(within(trace).getByText("falló")).toBeInTheDocument();
    expect(within(trace).getByText(/intento 2/)).toBeInTheDocument();
    expect(screen.getByText(/Ninguna regla bloqueó ni derivó/)).toBeInTheDocument();
    expect(screen.getByText("2026-09-29.1")).toBeInTheDocument();
    // atajo contextual de confirmación
    expect(screen.getByRole("button", { name: "Sí, confirmo" })).toBeEnabled();
  });

  it("abre la consola del asesor cuando el caso pasa a un humano", async () => {
    fakeApi({ ...baseRoutes, "POST /api/conversations/{id}/messages": () => ({ body: handoffTurn }) });
    const user = userEvent.setup();
    renderApp();
    await startFirstScenario(user);
    await user.type(screen.getByLabelText("Mensaje para el agente"), "no reconozco el cargo de 1200{Enter}");

    const consoleTab = await screen.findByRole("tab", { name: /Consola del asesor/ });
    await waitFor(() => {
      expect(consoleTab).toHaveAttribute("aria-selected", "true");
    });
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText("H02_high_amount", { selector: "h3 code" })).toBeInTheDocument();
    expect(within(panel).getByText("Validar con el cliente si reconoce al comercio.")).toBeInTheDocument();
    expect(within(panel).getByText("T-ANA-2")).toBeInTheDocument();
    expect(within(panel).getByText("REF-123")).toBeInTheDocument(); // campos nuevos del paquete, genéricos
    expect(within(panel).getByText("Paquete completo (JSON)")).toBeInTheDocument();
  });

  it("reproduce el guion del escenario con un clic por turno", async () => {
    const calls = fakeApi({
      ...baseRoutes,
      "POST /api/conversations/{id}/messages": () => ({ body: clarifyTurn }),
    });
    const user = userEvent.setup();
    renderApp();
    await startFirstScenario(user);
    const suggestions = screen.getByRole("group", { name: "Mensajes sugeridos" });
    await user.click(
      within(suggestions).getByRole("button", { name: "No reconozco un cargo de 77 dólares" }),
    );
    await within(screen.getByRole("list", { name: "Mensajes de la conversación" })).findByText(
      /¿Confirmas\?/,
    );
    expect(calls.find((c) => c.key.includes("messages"))?.body).toEqual({
      text: "No reconozco un cargo de 77 dólares",
    });
    expect(
      within(suggestions).queryByRole("button", { name: "No reconozco un cargo de 77 dólares" }),
    ).toBeNull();
  });

  it("muestra los errores de la API en una alerta accesible", async () => {
    fakeApi({
      ...baseRoutes,
      "POST /api/conversations/{id}/messages": () => ({
        status: 429,
        body: {
          error: {
            code: "rate_limited",
            message: "Demasiadas solicitudes. Espera un momento e intenta de nuevo.",
          },
        },
      }),
    });
    const user = userEvent.setup();
    renderApp();
    await startFirstScenario(user);
    await user.type(screen.getByLabelText("Mensaje para el agente"), "hola{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Demasiadas solicitudes");
    await user.click(screen.getByRole("button", { name: "Cerrar aviso de error" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("si el servidor se reinició y ya no conoce la conversación, lo explica y abre otra", async () => {
    const calls = fakeApi({
      ...baseRoutes,
      "POST /api/conversations/{id}/messages": () => ({
        status: 404,
        body: { error: { code: "conversation_not_found", message: "Conversación no encontrada." } },
      }),
    });
    const user = userEvent.setup();
    renderApp();
    await startFirstScenario(user);
    await user.type(screen.getByLabelText("Mensaje para el agente"), "sí{Enter}");
    expect(await screen.findByText(RESTART_CONVERSATION)).toBeInTheDocument();
    expect(calls.filter((c) => c.key === "POST /api/conversations")).toHaveLength(2);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("muestra resultados desconocidos con una etiqueta neutra y el valor crudo", async () => {
    fakeApi({
      ...baseRoutes,
      "POST /api/conversations/{id}/messages": () => ({
        body: { ...clarifyTurn, outcome: "customer_request" },
      }),
    });
    const user = userEvent.setup();
    renderApp();
    await startFirstScenario(user);
    await user.type(screen.getByLabelText("Mensaje para el agente"), "quiero hablar con una persona{Enter}");
    const log = screen.getByRole("list", { name: "Mensajes de la conversación" });
    expect(await within(log).findByText("customer_request")).toBeInTheDocument();
  });

  it("en pantallas angostas organiza la demo en pestañas", async () => {
    media.wide = false;
    fakeApi(baseRoutes);
    renderApp();
    const tabs = await screen.findByRole("tablist", { name: "Secciones de la demo" });
    expect(
      within(tabs)
        .getAllByRole("tab")
        .map((t) => t.textContent),
    ).toEqual(["Escenarios", "Chat", "Por qué"]);
    expect(within(tabs).getByRole("tab", { name: "Chat" })).toHaveAttribute("aria-selected", "true");
  });

  it("alterna el tema claro/oscuro y lo refleja en <html>", async () => {
    fakeApi(baseRoutes);
    const user = userEvent.setup();
    renderApp();
    await user.click(screen.getByRole("button", { name: "Cambiar a tema oscuro" }));
    expect(document.documentElement).toHaveClass("dark");
    await user.click(screen.getByRole("button", { name: "Cambiar a tema claro" }));
    expect(document.documentElement).toHaveClass("light");
  });
});
