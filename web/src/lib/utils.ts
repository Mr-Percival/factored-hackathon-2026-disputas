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
