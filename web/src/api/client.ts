// Cliente HTTP tipado. Mismo origen: la cookie de sesión (HttpOnly) la maneja el navegador; este código
// nunca ve ni guarda credenciales.
import type {
  ConversationCreated,
  ErrorBody,
  ScenariosResponse,
  SessionInfo,
  TurnResult,
} from "./types";

export const MAX_MESSAGE_CHARS = 1000;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, body: Partial<ErrorBody> | undefined) {
    super(body?.message ?? defaultMessage(status));
    this.name = "ApiError";
    this.status = status;
    this.code = body?.code ?? `http_${status}`;
  }
}

function defaultMessage(status: number): string {
  if (status === 0) return "No hay conexión con el servidor. Revisa tu red e intenta de nuevo.";
  if (status === 429) return "Demasiadas solicitudes. Espera un momento e intenta de nuevo.";
  if (status >= 500) return "El servidor tuvo un problema. Intenta de nuevo.";
  return "La solicitud no se pudo completar.";
}

function isErrorEnvelope(v: unknown): v is { error: Partial<ErrorBody> } {
  return typeof v === "object" && v !== null && "error" in v && typeof v.error === "object";
}

async function request<T>(method: "GET" | "POST" | "DELETE", path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? { accept: "application/json" } : { "content-type": "application/json", accept: "application/json" },
      body: body === undefined ? null : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, undefined);
  }
  if (res.status === 204) return undefined as T;
  const data: unknown = await res.json().catch(() => undefined);
  if (!res.ok) throw new ApiError(res.status, isErrorEnvelope(data) ? data.error : undefined);
  return data as T;
}

export const api = {
  scenarios: () => request<ScenariosResponse>("GET", "/api/scenarios"),
  login: (customerId: string) => request<SessionInfo>("POST", "/api/sessions", { customer_id: customerId }),
  currentSession: () => request<SessionInfo>("GET", "/api/sessions/current"),
  expireSession: () => request<SessionInfo>("POST", "/api/sessions/expire"),
  logout: () => request<undefined>("DELETE", "/api/sessions/current"),
  newConversation: () => request<ConversationCreated>("POST", "/api/conversations"),
  sendMessage: (conversationId: string, text: string) =>
    request<TurnResult>("POST", `/api/conversations/${encodeURIComponent(conversationId)}/messages`, { text }),
};
