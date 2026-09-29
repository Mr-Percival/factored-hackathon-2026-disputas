// Estado de la demo. El estado del SERVIDOR (escenarios, sesión, turnos) va por TanStack Query; lo que es
// solo de esta pestaña (transcripción, avance del guion) vive en un reducer.
import { useMutation, useQuery } from "@tanstack/react-query";
import { useCallback, useReducer } from "react";

import { api, ApiError } from "@/api/client";
import type { Handoff, Scenario, SessionInfo, TurnResult } from "@/api/types";

export interface ChatMessage {
  id: number;
  role: "user" | "agent" | "system";
  text: string;
  result?: TurnResult;
}

interface State {
  scenario: Scenario | null;
  session: SessionInfo | null;
  conversationId: string | null;
  messages: ChatMessage[];
  nextTurn: number;
  last: TurnResult | null;
  handoff: Handoff | null;
  handoffSeq: number; // cambia con cada handoff nuevo (abre la consola del asesor)
  error: ApiError | null;
  seq: number; // id del próximo mensaje
}

type Action =
  | { type: "started"; scenario: Scenario | null; session: SessionInfo; conversationId: string; note: string }
  | { type: "conversation"; conversationId: string; note: string }
  | { type: "user"; text: string; scriptIndex?: number }
  | { type: "agent"; result: TurnResult }
  | { type: "system"; text: string; session?: SessionInfo; scriptIndex?: number }
  | { type: "error"; error: ApiError | null }
  | { type: "signedOut" };

const initial: State = {
  scenario: null,
  session: null,
  conversationId: null,
  messages: [],
  nextTurn: 0,
  last: null,
  handoff: null,
  handoffSeq: 0,
  error: null,
  seq: 0,
};

function withMessage(state: State, role: ChatMessage["role"], text: string, result?: TurnResult): State {
  const id = state.seq + 1;
  const msg: ChatMessage = result ? { id, role, text, result } : { id, role, text };
  return { ...state, seq: id, messages: [...state.messages, msg] };
}

export function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "started":
      return withMessage(
        {
          ...initial,
          seq: state.seq,
          handoffSeq: state.handoffSeq,
          scenario: action.scenario,
          session: action.session,
          conversationId: action.conversationId,
        },
        "system",
        action.note,
      );
    case "conversation":
      return withMessage(
        {
          ...state,
          conversationId: action.conversationId,
          messages: [],
          nextTurn: 0,
          last: null,
          handoff: null,
          error: null,
        },
        "system",
        action.note,
      );
    case "user":
      return withMessage(
        {
          ...state,
          error: null,
          nextTurn: action.scriptIndex === undefined ? state.nextTurn : action.scriptIndex + 1,
        },
        "user",
        action.text,
      );
    case "agent":
      return withMessage(
        {
          ...state,
          last: action.result,
          handoff: action.result.handoff ?? state.handoff,
          handoffSeq: action.result.handoff ? state.handoffSeq + 1 : state.handoffSeq,
        },
        "agent",
        action.result.reply,
        action.result,
      );
    case "system":
      return withMessage(
        {
          ...state,
          session: action.session ?? state.session,
          nextTurn: action.scriptIndex === undefined ? state.nextTurn : action.scriptIndex + 1,
        },
        "system",
        action.text,
      );
    case "error":
      return { ...state, error: action.error };
    case "signedOut":
      return { ...state, session: null, conversationId: null };
  }
}

export const RESTART_SESSION =
  "La sesión se reinició (el servidor se reinició o la sesión expiró del todo). Elige el escenario de nuevo para continuar.";
export const RESTART_CONVERSATION =
  "La conversación se reinició porque el servidor ya no la tenía (reinicio o deploy). Abrí una nueva: vuelve a enviar tu mensaje.";

function asApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, undefined);
}

export function useScenarios() {
  return useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios, staleTime: Infinity });
}

export function useDemo() {
  const [state, dispatch] = useReducer(reducer, initial);

  const login = useMutation({ mutationFn: api.login });
  const conversation = useMutation({ mutationFn: api.newConversation });
  const expire = useMutation({ mutationFn: api.expireSession });
  const message = useMutation({
    mutationFn: ({ conversationId, text }: { conversationId: string; text: string }) =>
      api.sendMessage(conversationId, text),
  });

  // El estado de las conversaciones vive en memoria del servidor (1 worker): tras un reinicio o un deploy
  // la sesión o la conversación dejan de existir. Se explica y se recupera en vez de mostrar un error.
  const fail = useCallback(
    async (e: unknown) => {
      const err = asApiError(e);
      if (err.code === "session_required") {
        dispatch({ type: "signedOut" });
        dispatch({ type: "system", text: RESTART_SESSION });
        return;
      }
      if (err.code === "conversation_not_found") {
        try {
          const { conversation_id } = await conversation.mutateAsync();
          dispatch({ type: "conversation", conversationId: conversation_id, note: RESTART_CONVERSATION });
        } catch (e2) {
          dispatch({ type: "error", error: asApiError(e2) });
        }
        return;
      }
      dispatch({ type: "error", error: err });
    },
    [conversation],
  );

  const startScenario = useCallback(
    async (scenario: Scenario) => {
      try {
        const session = await login.mutateAsync(scenario.customer_id);
        const { conversation_id } = await conversation.mutateAsync();
        dispatch({
          type: "started",
          scenario,
          session,
          conversationId: conversation_id,
          note: `Sesión simulada como ${scenario.customer_id} · ${scenario.title}`,
        });
      } catch (e) {
        await fail(e);
      }
    },
    [login, conversation, fail],
  );

  const newConversation = useCallback(async () => {
    try {
      const { conversation_id } = await conversation.mutateAsync();
      dispatch({
        type: "conversation",
        conversationId: conversation_id,
        note: "Nueva conversación (misma sesión)",
      });
    } catch (e) {
      await fail(e);
    }
  }, [conversation, fail]);

  const expireSession = useCallback(
    async (scriptIndex?: number) => {
      try {
        const session = await expire.mutateAsync();
        dispatch({
          type: "system",
          text: "Sesión vencida (control de la demo): el agente ya no puede usar el token.",
          session,
          ...(scriptIndex === undefined ? {} : { scriptIndex }),
        });
      } catch (e) {
        await fail(e);
      }
    },
    [expire, fail],
  );

  const send = useCallback(
    async (text: string, scriptIndex?: number) => {
      const conversationId = state.conversationId;
      if (!conversationId || message.isPending) return;
      dispatch({ type: "user", text, ...(scriptIndex === undefined ? {} : { scriptIndex }) });
      try {
        const result = await message.mutateAsync({ conversationId, text });
        dispatch({ type: "agent", result });
      } catch (e) {
        await fail(e);
      }
    },
    [state.conversationId, message, fail],
  );

  const playTurn = useCallback(
    async (index: number) => {
      const turn = state.scenario?.turns[index];
      if (!turn) return;
      if (turn.kind === "expire_session") await expireSession(index);
      else if (turn.text) await send(turn.text, index);
    },
    [state.scenario, expireSession, send],
  );

  const dismissError = useCallback(() => {
    dispatch({ type: "error", error: null });
  }, []);

  return {
    ...state,
    sending: message.isPending,
    busy: login.isPending || conversation.isPending || expire.isPending || message.isPending,
    startScenario,
    newConversation,
    expireSession,
    send,
    playTurn,
    dismissError,
  };
}

export type Demo = ReturnType<typeof useDemo>;
