import { CheckCircle2, ClipboardList, UserRound, XCircle } from "lucide-react";
import type { ReactNode } from "react";

import type { Handoff } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Facts } from "@/components/WhyPanel";

/** Lo que recibe el asesor humano cuando el agente deriva: no tiene que volver a preguntarle nada al cliente. */
export function AdvisorConsole({ handoff }: { handoff: Handoff | null }) {
  if (!handoff) {
    return (
      <p className="text-sm text-muted-foreground">
        Se abre sola cuando el agente deriva un caso a una persona: motivo, hechos verificados, reglas,
        acciones tomadas, evidencia y preguntas abiertas.
      </p>
    );
  }
  const { transaction, ...customerFacts } = handoff.verified_facts as Record<string, unknown> & {
    transaction?: Record<string, unknown> | null;
  };
  return (
    <div className="flex flex-col gap-4 text-sm">
      <section aria-labelledby="advisor-reason" className="rounded-md bg-handoff-bg p-3 text-handoff-fg">
        <h3 id="advisor-reason" className="flex items-center gap-1.5 font-semibold">
          <UserRound aria-hidden="true" className="size-4" />
          Motivo: <code>{handoff.reason}</code>
        </h3>
        <p className="mt-1">{handoff.reason_text}</p>
        <p className="mt-1 text-xs">
          Idioma del cliente: {handoff.language === "pt" ? "portugués" : "español"} · creado{" "}
          {handoff.created_at}
        </p>
      </section>

      <Section id="advisor-request" title="Lo que pidió el cliente (PII enmascarada)">
        <ul className="flex flex-col gap-1">
          {handoff.request.map((r, i) => (
            <li key={i} lang={handoff.language} className="rounded bg-muted px-2 py-1 text-xs">
              “{r}”
            </li>
          ))}
        </ul>
      </Section>

      {transaction && <Facts title="Transacción verificada" facts={transaction} />}
      <Facts title="Hechos del cliente" facts={customerFacts} />

      <Section id="advisor-rules" title={`Política ${handoff.policy.version ?? ""}`.trim()}>
        {handoff.policy.rules_fired.length === 0 ? (
          <p className="text-xs text-muted-foreground">Sin reglas disparadas (derivación por otro motivo).</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {handoff.policy.rules_fired.map((r) => (
              <li key={r.id} className="text-xs">
                <code className="font-semibold">{r.id}</code> · {r.explain}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="advisor-actions" title="Acciones ya tomadas">
        {handoff.actions_taken.length === 0 ? (
          <p className="text-xs text-muted-foreground">Ninguna: no se abrió disputa ni se bloqueó tarjeta.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {handoff.actions_taken.map((a, i) => (
              <li key={i} className="flex items-center gap-1.5 text-xs">
                {a.ok ? (
                  <Badge tone="ok">
                    <CheckCircle2 aria-hidden="true" />
                    ok
                  </Badge>
                ) : (
                  <Badge tone="danger">
                    <XCircle aria-hidden="true" />
                    falló
                  </Badge>
                )}
                <code>{a.tool}</code>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="advisor-evidence" title="Evidencia (herramientas por paso)">
        <ul className="flex flex-col gap-1 text-xs">
          {handoff.evidence.map((e, i) => (
            <li key={i}>
              turno {e.turn} · <code>{e.node}</code>: {e.tools.join(", ")}
            </li>
          ))}
        </ul>
      </Section>

      <Section id="advisor-questions" title="Preguntas abiertas para el asesor">
        <ul className="flex list-disc flex-col gap-1 pl-5 text-xs">
          {handoff.unresolved_questions.map((q, i) => (
            <li key={i}>{q}</li>
          ))}
        </ul>
      </Section>

      {handoff.extra && Object.keys(handoff.extra).length > 0 && (
        <Facts title="Otros campos del paquete" facts={handoff.extra} />
      )}

      <details className="rounded-md border border-border">
        <summary className="flex cursor-pointer items-center gap-1.5 px-3 py-2 text-xs font-medium">
          <ClipboardList aria-hidden="true" className="size-4" />
          Paquete completo (JSON)
        </summary>
        <pre
          // Desplazable: enfocable para leerlo con teclado (axe scrollable-region-focusable, WCAG 2.1.1).
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- región desplazable
          tabIndex={0}
          role="region"
          aria-label="Paquete completo del handoff en JSON"
          className="max-h-80 overflow-auto border-t border-border p-3 text-xs"
        >
          {JSON.stringify(handoff, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id}>
      <h3 id={id} className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      {children}
    </section>
  );
}
