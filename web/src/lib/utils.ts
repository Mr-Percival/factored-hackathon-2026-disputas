import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

// Helper estándar de shadcn/ui: combina clases condicionales y resuelve conflictos de Tailwind.
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatMs(ms: number): string {
  return `${ms.toFixed(ms < 10 ? 2 : 1)} ms`;
}

export function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "sí" : "no";
  if (typeof v === "number")
    return Number.isInteger(v) ? String(v) : v.toLocaleString("es", { maximumFractionDigits: 2 });
  if (Array.isArray(v)) return v.length ? v.map(formatValue).join(", ") : "ninguno";
  if (typeof v === "object") return JSON.stringify(v);
  return typeof v === "string" ? v : "—";
}

/** Cabecera: qué router respondió el último turno (`understanding.router` de la API). Antes del primer turno no se
 * sabe (lo decide el servidor con BANKAGENT_ROUTER); si el modelo aprendido no cargó, la API dice `fallback`. */
export function routerBadge(router: string | null | undefined): { label: string; title: string } {
  if (!router)
    return {
      label: "Sin LLM",
      title: "Router local y respuestas por plantillas: sin llamadas a un modelo de lenguaje",
    };
  if (router.includes("fallback"))
    return {
      label: "Modo reglas (fallback)",
      title: `El router aprendido no cargó: responde el de reglas (${router})`,
    };
  if (router.startsWith("embed"))
    return {
      label: "Router aprendido (sin LLM)",
      title: `Intención con el modelo local de n-gramas; datos y confirmaciones por reglas (${router})`,
    };
  return {
    label: "Modo reglas (sin LLM)",
    title: `Router por reglas y respuestas por plantillas (${router})`,
  };
}
