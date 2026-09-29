import { Clock, MessageSquarePlus, Play, TimerOff } from "lucide-react";

import type { QuickReply, Scenario } from "@/api/types";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CATEGORIES, outcomeMeta } from "@/lib/outcomes";
import { cn } from "@/lib/utils";
import type { Demo } from "@/state/useDemo";

interface Props {
  demo: Demo;
  scenarios: Scenario[];
  quickReplies: QuickReply[];
  source: string;
}

export function ScenarioPanel({ demo, scenarios, quickReplies, source }: Props) {
  const groups = Object.entries(CATEGORIES)
    .map(([key, label]) => ({ key, label, items: scenarios.filter((s) => s.category === key) }))
    .filter((g) => g.items.length > 0);
  const active = demo.scenario;
  const canChat = Boolean(demo.conversationId) && !demo.busy;

  return (
    <div className="flex flex-col gap-4">
      <Card aria-labelledby="scenarios-title">
        <CardHeader>
          <CardTitle id="scenarios-title">Escenarios</CardTitle>
          <CardDescription>
            Elegir uno inicia una sesión simulada con ese cliente. Fuente: <code>{source}</code>
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {groups.map((g) => (
            <div key={g.key} role="group" aria-labelledby={`group-${g.key}`}>
              <h3 id={`group-${g.key}`} className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {g.label}
              </h3>
              <ul className="flex flex-col gap-2">
                {g.items.map((s) => {
                  const selected = active?.id === s.id;
                  return (
                    <li key={s.id}>
                      <button
                        type="button"
                        aria-pressed={selected}
                        disabled={demo.busy}
                        onClick={() => void demo.startScenario(s)}
                        className={cn(
                          "w-full rounded-md border px-3 py-2 text-left text-sm transition-colors hover:bg-muted disabled:opacity-60",
                          selected ? "border-primary ring-1 ring-primary" : "border-border",
                        )}
                      >
                        <span className="block font-medium">{s.title}</span>
                        <span className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                          <code>{s.customer_id}</code>
                          <Badge tone="neutral" lang={s.lang}>
                            {s.lang === "pt" ? "portugués" : "español"}
                          </Badge>
                          {s.expected.outcome && <OutcomeBadge outcome={s.expected.outcome} />}
                          {s.expected.rule && <code>{s.expected.rule}</code>}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card aria-labelledby="controls-title">
        <CardHeader>
          <CardTitle id="controls-title">Controles</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" disabled={!demo.session || demo.busy} onClick={() => void demo.newConversation()}>
              <MessageSquarePlus aria-hidden="true" />
              Nueva conversación
            </Button>
            <Button variant="outline" size="sm" disabled={!demo.session || demo.busy} onClick={() => void demo.expireSession()}>
              <TimerOff aria-hidden="true" />
              Vencer sesión
            </Button>
          </div>

          {active && (
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Guion: un clic por turno</h3>
              <ol className="flex flex-col gap-2">
                {active.turns.map((t, i) => {
                  const done = i < demo.nextTurn;
                  const next = i === demo.nextTurn;
                  const label = t.kind === "expire_session" ? "Vencer la sesión" : (t.text ?? "");
                  return (
                    <li key={i}>
                      <Button
                        variant={next ? "default" : "outline"}
                        size="sm"
                        className="h-auto w-full justify-start whitespace-normal py-1.5 text-left"
                        disabled={!canChat}
                        onClick={() => void demo.playTurn(i)}
                        aria-describedby={t.expect_outcome ? `turn-exp-${i}` : undefined}
                      >
                        {t.kind === "expire_session" ? <Clock aria-hidden="true" /> : <Play aria-hidden="true" />}
                        <span className="flex-1">
                          <span className="sr-only">
                            Turno {i + 1}
                            {done ? " (enviado)" : next ? " (siguiente)" : ""}:{" "}
                          </span>
                          {label}
                        </span>
                      </Button>
                      {t.expect_outcome && (
                        <p id={`turn-exp-${i}`} className="mt-1 pl-1 text-xs text-muted-foreground">
                          Esperado: {outcomeMeta(t.expect_outcome).label}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ol>
              {active.note && <p className="mt-2 text-xs text-muted-foreground">{active.note}</p>}
            </div>
          )}

          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Respuestas rápidas</h3>
            <div className="flex flex-wrap gap-2">
              {quickReplies.map((q) => (
                <Button key={q.label} variant="secondary" size="sm" disabled={!canChat} onClick={() => void demo.send(q.text)}>
                  {q.label}
                </Button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
