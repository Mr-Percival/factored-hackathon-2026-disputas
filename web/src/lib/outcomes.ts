import {
  Ban,
  CheckCircle2,
  CircleSlash,
  HelpCircle,
  Info,
  KeyRound,
  ShieldAlert,
  UserRound,
  type LucideIcon,
} from "lucide-react";

import type { Category } from "@/api/types";

export type Tone = "ok" | "info" | "warn" | "danger" | "handoff" | "neutral";

interface OutcomeMeta {
  label: string;
  description: string;
  tone: Tone;
  icon: LucideIcon;
}

export type KnownOutcome =
  | "resolved"
  | "clarify"
  | "informed"
  | "rejected"
  | "handoff"
  | "cancelled"
  | "blocked"
  | "auth_error";

// El color nunca es la única señal (WCAG 1.4.1): cada resultado lleva ícono + texto. Un resultado que esta
// versión no conoce (el grafo puede sumar nuevos) se muestra neutro con su valor crudo.
export const OUTCOMES: Record<KnownOutcome, OutcomeMeta> = {
  resolved: { label: "Resuelto", description: "Acción ejecutada y verificada", tone: "ok", icon: CheckCircle2 },
  clarify: { label: "Aclaración", description: "El agente necesita un dato o una confirmación", tone: "info", icon: HelpCircle },
  informed: { label: "Informado", description: "La política informa sin ejecutar acciones", tone: "info", icon: Info },
  rejected: { label: "Rechazado por política", description: "Una regla de la política lo impide", tone: "warn", icon: CircleSlash },
  handoff: { label: "Derivado a asesor", description: "Pasa a un humano con el contexto completo", tone: "handoff", icon: UserRound },
  cancelled: { label: "Cancelado", description: "El cliente no confirmó; no se hizo ningún cambio", tone: "neutral", icon: Ban },
  blocked: { label: "Bloqueado por el guard", description: "Intento de inyección detectado", tone: "danger", icon: ShieldAlert },
  auth_error: { label: "Error de sesión", description: "Sesión inexistente, vencida o sin permiso", tone: "danger", icon: KeyRound },
};

export function outcomeMeta(outcome: string | null | undefined): OutcomeMeta {
  return (outcome && outcome in OUTCOMES ? OUTCOMES[outcome as KnownOutcome] : undefined) ?? {
    label: outcome ?? "sin resultado",
    description: "",
    tone: "neutral",
    icon: Info,
  };
}

export const CATEGORIES: Record<Category, string> = {
  resolution: "Resolución automática",
  clarify: "Aclaración",
  handoff: "Derivación a humano",
  policy: "Política",
  security: "Seguridad",
};

export const TONE_CLASSES: Record<Tone, string> = {
  ok: "bg-ok-bg text-ok-fg",
  info: "bg-info-bg text-info-fg",
  warn: "bg-warn-bg text-warn-fg",
  danger: "bg-danger-bg text-danger-fg",
  handoff: "bg-handoff-bg text-handoff-fg",
  neutral: "bg-neutral-bg text-neutral-fg",
};
