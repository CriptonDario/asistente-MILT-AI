import { create } from "zustand";
import type { ChatUsage, ContextSource, ServerEvent } from "../types/api";

export type StreamStatus = "pending" | "streaming" | "done" | "cancelled" | "error";

/** Estado de la respuesta en curso de una conversación (aún no guardada en la lista). */
export interface StreamState {
  requestId: string;
  conversationId: string;
  /** Texto del usuario mostrado de forma optimista hasta que llega el guardado. */
  userContent: string | null;
  userMessageId: string | null;
  messageId: string | null;
  model: string | null;
  text: string;
  thinking: string;
  status: StreamStatus;
  error: { code: string; detail: string } | null;
  usage: ChatUsage | null;
  startedAt: number;
  /** Recuerdos y fragmentos de documentos usados para responder. */
  sources: ContextSource[];
  warnings: string[];
  /** Herramientas que el modelo ha pedido usar en este turno. */
  tools: ToolCallView[];
}

export type ToolCallStatus = "running" | "awaiting" | "ok" | "error" | "denied";

export interface ToolCallView {
  callId: string;
  tool: string;
  risk: string;
  summary: string;
  arguments: Record<string, unknown>;
  status: ToolCallStatus;
  resultSummary: string | null;
  /** Instante (ms epoch) en que caduca la confirmación pendiente. */
  expiresAt: number | null;
}

function upsertTool(
  tools: ToolCallView[],
  callId: string,
  patch: Partial<ToolCallView>,
  base?: ToolCallView,
): ToolCallView[] {
  const index = tools.findIndex((t) => t.callId === callId);
  if (index === -1) return base ? [...tools, { ...base, ...patch }] : tools;
  const next = [...tools];
  next[index] = { ...next[index]!, ...patch };
  return next;
}

export function newStream(
  requestId: string,
  conversationId: string,
  userContent: string | null,
): StreamState {
  return {
    requestId,
    conversationId,
    userContent,
    userMessageId: null,
    messageId: null,
    model: null,
    text: "",
    thinking: "",
    status: "pending",
    error: null,
    usage: null,
    startedAt: Date.now(),
    sources: [],
    warnings: [],
    tools: [],
  };
}

export function isActive(stream: StreamState | undefined): boolean {
  return stream?.status === "pending" || stream?.status === "streaming";
}

/** Reductor puro: aplica un evento del servidor al estado del stream. */
export function reduceStream(state: StreamState, event: ServerEvent): StreamState {
  if (!("request_id" in event) || event.request_id !== state.requestId) return state;
  switch (event.type) {
    case "chat.started":
      return {
        ...state,
        messageId: event.message_id,
        userMessageId: event.user_message_id,
        model: event.model,
      };
    case "chat.context":
      return { ...state, sources: event.sources, warnings: event.warnings };
    case "tool.call":
      return {
        ...state,
        tools: upsertTool(
          state.tools,
          event.call_id,
          { status: "running" },
          {
            callId: event.call_id,
            tool: event.tool,
            risk: event.risk,
            summary: event.summary,
            arguments: event.arguments,
            status: "running",
            resultSummary: null,
            expiresAt: null,
          },
        ),
      };
    case "tool.confirm_request":
      return {
        ...state,
        tools: upsertTool(state.tools, event.call_id, {
          status: "awaiting",
          summary: event.summary,
          expiresAt: Date.now() + event.expires_in * 1000,
        }),
      };
    case "tool.result":
      return {
        ...state,
        tools: upsertTool(state.tools, event.call_id, {
          status: event.status,
          resultSummary: event.summary,
          expiresAt: null,
        }),
      };
    case "chat.delta":
      return { ...state, status: "streaming", text: state.text + event.text };
    case "chat.thinking":
      return { ...state, thinking: state.thinking + event.text };
    case "chat.done":
      return { ...state, status: "done", messageId: event.message_id, usage: event.usage };
    case "chat.error":
      return event.code === "cancelled"
        ? { ...state, status: "cancelled" }
        : { ...state, status: "error", error: { code: event.code, detail: event.detail } };
    default:
      return state;
  }
}

interface ChatStore {
  streams: Record<string, StreamState>;
  begin: (stream: StreamState) => void;
  apply: (event: ServerEvent) => StreamState | null;
  remove: (conversationId: string, requestId: string) => void;
  /** Marca una confirmación como respondida (optimista, antes de que llegue el resultado). */
  markAnswered: (callId: string, approved: boolean) => void;
}

export const useChatStore = create<ChatStore>()((set, get) => ({
  streams: {},
  begin: (stream) => set((s) => ({ streams: { ...s.streams, [stream.conversationId]: stream } })),
  apply: (event) => {
    if (!("request_id" in event)) return null;
    const current = Object.values(get().streams).find((s) => s.requestId === event.request_id);
    if (!current) return null;
    const next = reduceStream(current, event);
    if (next !== current) {
      set((s) => ({ streams: { ...s.streams, [next.conversationId]: next } }));
    }
    return next;
  },
  markAnswered: (callId, approved) =>
    set((s) => {
      const entry = Object.values(s.streams).find((st) => st.tools.some((t) => t.callId === callId));
      if (!entry) return s;
      const tools = upsertTool(entry.tools, callId, {
        status: approved ? "running" : "denied",
        expiresAt: null,
      });
      return { streams: { ...s.streams, [entry.conversationId]: { ...entry, tools } } };
    }),
  remove: (conversationId, requestId) =>
    set((s) => {
      if (s.streams[conversationId]?.requestId !== requestId) return s;
      const { [conversationId]: _removed, ...rest } = s.streams;
      return { streams: rest };
    }),
}));
