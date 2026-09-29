import { Cpu, Landmark, ListChecks, MessageSquare, Moon, Search, Sun } from "lucide-react";

import { ChatPanel } from "@/components/ChatPanel";
import { InsightPanel } from "@/components/InsightPanel";
import { ScenarioPanel } from "@/components/ScenarioPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMediaQuery, useTheme } from "@/lib/hooks";
import { useDemo, useScenarios } from "@/state/useDemo";

const DEFAULT_DISCLAIMER = "Sandbox con datos sintéticos · política sintética · no mueve dinero";

export function App() {
  const demo = useDemo();
  const scenarios = useScenarios();
  const [theme, toggleTheme] = useTheme();
  const wide = useMediaQuery("(min-width: 1024px)");

  const picker = scenarios.isPending ? (
    <p className="text-sm text-muted-foreground" role="status">
      Cargando escenarios…
    </p>
  ) : scenarios.isError ? (
    <div role="alert" className="rounded-md bg-danger-bg p-3 text-sm text-danger-fg">
      No se pudieron cargar los escenarios. {scenarios.error.message}
      <Button size="sm" variant="outline" className="ml-2" onClick={() => void scenarios.refetch()}>
        Reintentar
      </Button>
    </div>
  ) : (
    <ScenarioPanel
      demo={demo}
      scenarios={scenarios.data.scenarios}
      quickReplies={scenarios.data.quick_replies}
      source={scenarios.data.source}
    />
  );
  const chat = <ChatPanel demo={demo} scenarios={scenarios.data?.scenarios ?? []} />;
  const insight = <InsightPanel demo={demo} />;

  return (
    <div className="flex min-h-full flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-10 focus:rounded focus:bg-card focus:px-3 focus:py-2"
      >
        Saltar al contenido
      </a>
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-[110rem] items-center gap-3 px-4 py-3">
          <Landmark aria-hidden="true" className="size-6 text-primary" />
          <div className="flex-1">
            <h1 className="text-base font-semibold leading-tight">
              Agente de disputas de cargos no reconocidos
            </h1>
            <p className="text-xs text-muted-foreground">
              Atiende cargos no reconocidos, cobros indebidos y bloqueo de tarjeta · español y portugués
            </p>
          </div>
          <Badge
            tone="info"
            title="Router por reglas y respuestas por plantillas: sin llamadas a un modelo de lenguaje"
          >
            <Cpu aria-hidden="true" />
            Modo reglas (sin LLM)
          </Badge>
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            aria-label={theme === "dark" ? "Cambiar a tema claro" : "Cambiar a tema oscuro"}
            title={theme === "dark" ? "Tema claro" : "Tema oscuro"}
          >
            {theme === "dark" ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
          </Button>
        </div>
        <details className="mx-auto max-w-[110rem] px-4 pb-2 text-xs text-muted-foreground">
          <summary className="w-fit cursor-pointer">Limitaciones conocidas</summary>
          <ul className="mt-1 list-disc pl-5">
            <li>
              Entiende por reglas y palabras clave (línea base): funciona mejor con monto, fecha o país (“no
              reconozco un cargo de 77 dólares”). Si no entiende, pregunta en vez de adivinar.
            </li>
            <li>Las sesiones duran 15 minutos y viven en la memoria del servidor: un reinicio las borra.</li>
            <li>Identidad, herramientas y política son un sandbox: ninguna acción mueve dinero real.</li>
          </ul>
        </details>
      </header>

      <main id="main" className="mx-auto w-full max-w-[110rem] flex-1 px-4 py-4">
        {wide ? (
          <div className="grid h-[calc(100vh-9.5rem)] min-h-[36rem] grid-cols-[20rem_minmax(0,1fr)_minmax(0,28rem)] gap-4">
            <div className="min-h-0 overflow-y-auto pr-1">{picker}</div>
            <div className="min-h-0">{chat}</div>
            <div className="min-h-0">{insight}</div>
          </div>
        ) : (
          <Tabs defaultValue="chat" className="flex flex-col">
            <TabsList aria-label="Secciones de la demo">
              <TabsTrigger value="scenarios">
                <ListChecks aria-hidden="true" />
                Escenarios
              </TabsTrigger>
              <TabsTrigger value="chat">
                <MessageSquare aria-hidden="true" />
                Chat
              </TabsTrigger>
              <TabsTrigger value="why">
                <Search aria-hidden="true" />
                Por qué
              </TabsTrigger>
            </TabsList>
            <TabsContent value="scenarios">{picker}</TabsContent>
            <TabsContent value="chat">{chat}</TabsContent>
            <TabsContent value="why">{insight}</TabsContent>
          </Tabs>
        )}
      </main>

      <footer className="border-t border-border px-4 py-3 text-center text-xs text-muted-foreground">
        {scenarios.data?.disclaimer ?? DEFAULT_DISCLAIMER}
        {scenarios.data && (
          <span>
            {" "}
            · base: {scenarios.data.data_source === "fixture" ? "fixture de prueba" : "datos del organizador"}
          </span>
        )}
      </footer>
    </div>
  );
}
