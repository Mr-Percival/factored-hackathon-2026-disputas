import { AlertTriangle, Bot, SendHorizontal, User, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent, type SyntheticEvent } from "react";

import { MAX_MESSAGE_CHARS } from "@/api/client";
import type { Scenario, TurnResult } from "@/api/types";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { ChatMessage, Demo } from "@/state/useDemo";

export function ChatPanel({ demo, scenarios = [] }: { demo: Demo; scenarios?: Scenario[] }) {
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const counterId = useId();
  const hintId = useId();
  const canChat = Boolean(demo.conversationId);
  const lastAgent = [...demo.messages].reverse().find((m) => m.role === "agent");

  // Se desplaza el contenedor (no scrollIntoView): scrollIntoView movía el punto de partida de la navegación
  // con Tab al final del chat y el primer Tab de la página saltaba el enlace "Saltar al contenido" (#35).
  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [demo.messages.length, demo.sending]);

  const submit = (e?: SyntheticEvent) => {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || !canChat || demo.sending) return;
    setDraft("");
    void demo.send(text);
    inputRef.current?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter envía, Shift+Enter agrega una línea. No se interrumpe la composición de un IME.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <Card aria-labelledby="chat-title" className="flex h-full min-h-[32rem] flex-col">
      <CardHeader>
        <CardTitle id="chat-title">Chat con el agente</CardTitle>
        <CardDescription>
          {demo.session
            ? `Cliente ${demo.session.customer_id} · ${demo.session.expired ? "sesión vencida" : "sesión activa"}`
            : "Elige un escenario para iniciar una sesión simulada."}
        </CardDescription>
      </CardHeader>

      {demo.error && (
        <div
          role="alert"
          className="mx-4 mt-3 flex items-start gap-2 rounded-md bg-danger-bg px-3 py-2 text-sm text-danger-fg"
        >
          <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <p className="flex-1">{demo.error.message}</p>
          <button
            type="button"
            onClick={demo.dismissError}
            className="rounded p-0.5 hover:bg-background/40"
            aria-label="Cerrar aviso de error"
          >
            <X aria-hidden="true" className="size-4" />
          </button>
        </div>
      )}

      {/* Región desplazable enfocable: con teclado se puede leer el historial aunque no tenga controles
          (axe scrollable-region-focusable, WCAG 2.1.1). */}
      <div
        ref={logRef}
        role="region"
        aria-label="Historial del chat"
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- región desplazable: WCAG 2.1.1
        tabIndex={0}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-3"
        aria-busy={demo.sending}
      >
        {!demo.session && <StartHere demo={demo} scenarios={scenarios} />}
        <ol aria-label="Mensajes de la conversación" className="flex flex-col gap-3">
          {demo.messages.map((m) => (
            <MessageItem key={m.id} message={m} demo={demo} isLast={m === lastAgent} />
          ))}
        </ol>
        {demo.sending && (
          <p className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
            <Bot aria-hidden="true" className="size-4" />
            <span>El agente está respondiendo</span>
            <span aria-hidden="true" className="inline-flex gap-0.5">
              <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground" />
              <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:150ms]" />
              <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:300ms]" />
            </span>
          </p>
        )}
      </div>

      {/* Solo la última respuesta del agente se anuncia a lectores de pantalla (WAI-ARIA live region). */}
      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {lastAgent ? `Agente: ${lastAgent.text}` : ""}
      </div>

      <Suggestions demo={demo} />

      <form onSubmit={submit} className="border-t border-border p-3">
        <label htmlFor="composer" className="sr-only">
          Mensaje para el agente
        </label>
        <div className="flex items-end gap-2">
          <textarea
            id="composer"
            ref={inputRef}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
            }}
            onKeyDown={onKeyDown}
            disabled={!canChat}
            maxLength={MAX_MESSAGE_CHARS}
            rows={2}
            placeholder={canChat ? "Escribe como el cliente (es / pt)…" : "Elige un escenario para empezar"}
            aria-describedby={`${hintId} ${counterId}`}
            className="min-h-[2.5rem] flex-1 resize-y rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground disabled:opacity-60"
          />
          <Button
            type="submit"
            disabled={!canChat || demo.sending || !draft.trim()}
            aria-label="Enviar mensaje"
          >
            <SendHorizontal aria-hidden="true" />
            <span className="hidden sm:inline">Enviar</span>
          </Button>
        </div>
        <div className="mt-1 flex justify-between text-xs text-muted-foreground">
          <span id={hintId}>Enter envía · Shift+Enter nueva línea</span>
          <span id={counterId}>
            {draft.length}/{MAX_MESSAGE_CHARS}
            <span className="sr-only"> caracteres</span>
          </span>
        </div>
      </form>
    </Card>
  );
}

function MessageItem({ message, demo, isLast }: { message: ChatMessage; demo: Demo; isLast: boolean }) {
  if (message.role === "system") {
    return (
      <li className="text-center text-xs text-muted-foreground">
        <span className="rounded-full bg-muted px-3 py-1">{message.text}</span>
      </li>
    );
  }
  const isUser = message.role === "user";
  const Icon = isUser ? User : Bot;
  return (
    <li className={cn("flex gap-2", isUser ? "flex-row-reverse" : "flex-row")}>
      <Icon aria-hidden="true" className="mt-1 size-5 shrink-0 text-muted-foreground" />
      <div className={cn("flex max-w-[85%] flex-col gap-1.5", isUser ? "items-end" : "items-start")}>
        <span className="sr-only">{isUser ? "Cliente:" : "Agente:"}</span>
        {/* Texto plano: nunca se interpreta HTML ni Markdown de la respuesta (OWASP LLM05). */}
        <p
          lang={message.result?.lang}
          className={cn(
            "whitespace-pre-wrap break-words rounded-lg px-3 py-2 text-sm",
            isUser ? "bg-user-bubble text-user-bubble-foreground" : "border border-border bg-muted",
          )}
        >
          {message.text}
        </p>
        {message.result && (
          <>
            <OutcomeBadge outcome={message.result.outcome} />
            {isLast && <TurnActions result={message.result} demo={demo} />}
          </>
        )}
      </div>
    </li>
  );
}

/** Atajos contextuales: elegir una opción o confirmar la acción pendiente, sin escribir. */
function TurnActions({ result, demo }: { result: TurnResult; demo: Demo }) {
  const disabled = demo.sending || !demo.conversationId;
  const pt = result.lang === "pt";
  if (result.awaiting === "option" && result.candidates.length > 0) {
    return (
      <div role="group" aria-label="Opciones" className="flex flex-wrap gap-1.5">
        {result.candidates.map((c) => (
          <Button
            key={c.index}
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => void demo.send(String(c.index))}
          >
            Elegir {c.index}
          </Button>
        ))}
      </div>
    );
  }
  if (result.awaiting === "confirmation" && result.pending_action) {
    return (
      <div role="group" aria-label="Confirmación" className="flex flex-wrap gap-1.5">
        <Button size="sm" disabled={disabled} onClick={() => void demo.send(pt ? "sim" : "sí")}>
          {pt ? "Sim, confirmo" : "Sí, confirmo"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={disabled}
          onClick={() => void demo.send(pt ? "não" : "no")}
        >
          {pt ? "Não" : "No"}
        </Button>
      </div>
    );
  }
  return null;
}

/** Sin sesión: los primeros escenarios, a un clic (en móvil el selector está en otra pestaña). */
function StartHere({ demo, scenarios }: { demo: Demo; scenarios: Scenario[] }) {
  if (scenarios.length === 0) return null;
  return (
    <div className="mb-4 rounded-md border border-dashed border-border p-3">
      <h3 className="text-sm font-semibold">Empieza con un escenario</h3>
      <p className="mb-2 text-xs text-muted-foreground">
        Inicia una sesión simulada con un cliente de demo y usa los mensajes sugeridos, o escribe los tuyos.
      </p>
      <div className="flex flex-wrap gap-2">
        {scenarios.slice(0, 4).map((s) => (
          <Button
            key={s.id}
            size="sm"
            variant="outline"
            disabled={demo.busy}
            onClick={() => void demo.startScenario(s)}
          >
            {s.title}
          </Button>
        ))}
      </div>
    </div>
  );
}

/** Mensajes sugeridos del guion del escenario activo (el siguiente, resaltado). */
function Suggestions({ demo }: { demo: Demo }) {
  const turns = demo.scenario?.turns ?? [];
  if (!demo.conversationId || turns.length === 0) return null;
  const pending = turns.map((t, i) => ({ t, i })).filter(({ i }) => i >= demo.nextTurn);
  if (pending.length === 0) return null;
  return (
    <div
      role="group"
      aria-label="Mensajes sugeridos"
      className="flex flex-wrap items-center gap-1.5 border-t border-border px-3 pt-2"
    >
      <span className="text-xs text-muted-foreground">Sugerido:</span>
      {pending.map(({ t, i }) => (
        <Button
          key={i}
          size="sm"
          variant={i === demo.nextTurn ? "default" : "outline"}
          className="h-auto max-w-full whitespace-normal py-1 text-left"
          disabled={demo.busy}
          onClick={() => void demo.playTurn(i)}
        >
          {t.kind === "expire_session" ? "(vencer la sesión)" : t.text}
        </Button>
      ))}
    </div>
  );
}
