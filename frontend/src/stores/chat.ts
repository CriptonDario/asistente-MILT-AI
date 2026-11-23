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
  remove: (conversationId, requestId) =>
    set((s) => {
      if (s.streams[conversationId]?.requestId !== requestId) return s;
      const { [conversationId]: _removed, ...rest } = s.streams;
      return { streams: rest };
    }),
}));
