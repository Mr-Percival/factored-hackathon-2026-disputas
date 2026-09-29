import { Lightbulb, UserRound } from "lucide-react";
import { useState } from "react";

import { AdvisorConsole } from "@/components/AdvisorConsole";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WhyPanel } from "@/components/WhyPanel";
import type { Demo } from "@/state/useDemo";

type Tab = "why" | "advisor";

export function InsightPanel({ demo }: { demo: Demo }) {
  // Si se monta con un handoff ya abierto (en móvil las pestañas desmontan el panel), abre la consola.
  const [tab, setTab] = useState<Tab>(demo.handoff ? "advisor" : "why");
  const [seenHandoff, setSeenHandoff] = useState(demo.handoffSeq);

  // Cada handoff nuevo abre la consola del asesor y se anuncia, sin robar el foco del chat
  // (ajuste de estado durante el render: https://react.dev/learn/you-might-not-need-an-effect).
  if (demo.handoffSeq !== seenHandoff) {
    setSeenHandoff(demo.handoffSeq);
    setTab("advisor");
  }
  const announce =
    demo.handoffSeq > 0
      ? `Caso ${demo.handoffSeq} derivado a un asesor humano: la consola del asesor está abierta.`
      : "";

  return (
    <Card aria-label="Explicación y consola del asesor" className="flex h-full flex-col">
      <CardContent className="flex min-h-0 flex-1 flex-col">
        <Tabs
          value={tab}
          onValueChange={(v) => {
            setTab(v as Tab);
          }}
          className="flex min-h-0 flex-1 flex-col"
        >
          <TabsList aria-label="Paneles de explicación">
            <TabsTrigger value="why">
              <Lightbulb aria-hidden="true" />
              Por qué respondió así
            </TabsTrigger>
            <TabsTrigger value="advisor">
              <UserRound aria-hidden="true" />
              Consola del asesor
              {demo.handoff && (
                <span className="ml-1 rounded-full bg-handoff-bg px-1.5 text-xs text-handoff-fg">
                  1<span className="sr-only"> caso derivado</span>
                </span>
              )}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="why" className="overflow-y-auto">
            <WhyPanel result={demo.last} />
          </TabsContent>
          <TabsContent value="advisor" className="overflow-y-auto">
            <AdvisorConsole handoff={demo.handoff} />
          </TabsContent>
        </Tabs>
        <div aria-live="polite" className="sr-only">
          {announce}
        </div>
      </CardContent>
    </Card>
  );
}
