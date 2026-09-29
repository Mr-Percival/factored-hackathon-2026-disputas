import { ArrowRight, CheckCircle2, XCircle } from "lucide-react";

import type { Decision, TraceStep, TurnResult } from "@/api/types";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { Badge } from "@/components/ui/badge";
import { outcomeMeta } from "@/lib/outcomes";
import { formatMs, formatValue } from "@/lib/utils";

const NODE_LABELS: Record<string, string> = {
  guard: "Guard (inyección · PII · sesión)",
  understand: "Entender intención y datos",
  find_transaction: "Buscar la transacción",
  find_card: "Buscar la tarjeta",
  select_option: "Aplicar la opción elegida",
  decide: "Decidir con la política",
  act: "Ejecutar con confirmación",
  cancel: "Cancelar",
  handoff: "Armar el paquete para el asesor",
  respond: "Redactar la respuesta",
};

export function WhyPanel({ result }: { result: TurnResult | null }) {
  if (!result) {
    return (
      <p className="text-sm text-muted-foreground">
        Envía un mensaje: aquí verás cada paso del grafo, las herramientas que usó, las reglas de la política y
        los hechos verificados que explican la respuesta.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-5">
      <section aria-labelledby="why-outcome">
        <h3 id="why-outcome" className="mb-1 text-sm font-semibold">
          Resultado del turno {result.turn}
        </h3>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <OutcomeBadge outcome={result.outcome} />
          <span className="text-muted-foreground">{outcomeMeta(result.outcome).description}</span>
        </div>
      </section>
      <TraceTimeline steps={result.trace} totalMs={result.trace_total_ms} />
      <PolicyView decision={result.decision ?? null} />
    </div>
  );
}

export function TraceTimeline({ steps, totalMs }: { steps: TraceStep[]; totalMs: number }) {
  return (
    <section aria-labelledby="why-trace">
      <h3 id="why-trace" className="mb-2 flex items-baseline justify-between text-sm font-semibold">
        <span>Traza del grafo</span>
        <span className="text-xs font-normal text-muted-foreground">
          {steps.length} pasos · {formatMs(totalMs)}
        </span>
      </h3>
      <ol aria-label="Pasos del grafo en orden" className="relative flex flex-col gap-3 border-l border-border pl-4">
        {steps.map((s, i) => (
          <li key={`${s.node}-${i}`} className="relative">
            <span aria-hidden="true" className="absolute -left-[1.3rem] top-1.5 size-2.5 rounded-full border-2 border-primary bg-card" />
            <div className="flex flex-wrap items-center gap-1.5 text-sm">
              <code className="font-semibold">{s.node}</code>
              <ArrowRight aria-hidden="true" className="size-3.5 text-muted-foreground" />
              <span className="sr-only">va a</span>
              <code>{s.next}</code>
              <span className="ml-auto text-xs text-muted-foreground">{formatMs(s.ms)}</span>
            </div>
            <p className="text-xs text-muted-foreground">{NODE_LABELS[s.node] ?? s.node}</p>
            {s.detail && <p className="mt-0.5 break-all font-mono text-xs">{s.detail}</p>}
            {s.tools.length > 0 && (
              <ul aria-label={`Herramientas de ${s.node}`} className="mt-1 flex flex-col gap-1">
                {s.tools.map((t, j) => (
                  <li key={`${t.tool}-${j}`} className="flex flex-wrap items-center gap-1.5 text-xs">
                    {t.ok ? (
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
                    <code>{t.tool}</code>
                    <span className="text-muted-foreground">
                      intento {t.attempt}
                      {t.ms != null ? ` · ${formatMs(t.ms)}` : ""}
                      {t.error ? ` · ${t.error}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

function PolicyView({ decision }: { decision: Decision | null }) {
  return (
    <section aria-labelledby="why-policy">
      <h3 id="why-policy" className="mb-2 text-sm font-semibold">
        Política
      </h3>
      {!decision ? (
        <p className="text-sm text-muted-foreground">En este turno no se evaluó la política.</p>
      ) : (
        <div className="flex flex-col gap-3 text-sm">
          <p>
            Decisión <code className="font-semibold">{decision.outcome}</code> · versión{" "}
            <code>{decision.policy_version}</code>
          </p>
          {decision.rules.length === 0 ? (
            <p className="text-muted-foreground">
              Ninguna regla bloqueó ni derivó: la disputa procede con confirmación del cliente.
            </p>
          ) : (
            <ul aria-label="Reglas que se cumplieron" className="flex flex-col gap-2">
              {decision.rules.map((r, i) => (
                <li key={r.id} className="rounded-md border border-border p-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <code className="font-semibold">{r.id}</code>
                    <Badge tone={r.outcome === "handoff" ? "handoff" : r.outcome === "reject" ? "warn" : "info"}>{r.outcome}</Badge>
                    {i === 0 && <span className="text-xs text-muted-foreground">(decide)</span>}
                  </div>
                  <p className="mt-1 text-muted-foreground">{r.explain}</p>
                </li>
              ))}
            </ul>
          )}
          <Facts title="Hechos verificados (de las herramientas, no del texto)" facts={decision.facts} />
        </div>
      )}
    </section>
  );
}

export function Facts({ title, facts }: { title: string; facts: Record<string, unknown> }) {
  const entries = Object.entries(facts);
  if (entries.length === 0) return null;
  return (
    <div>
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h4>
      <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
        {entries.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="font-mono text-muted-foreground">{k}</dt>
            <dd className="break-words">{formatValue(v)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
