import { useCallback } from "react";
import { queryClient, queryKeys } from "../app/queryClient";
import { chatSocketUrl } from "../lib/config";
import { newRequestId } from "../lib/ids";
import { ChatSocket, ChatSocketError } from "../services/chatSocket";
import { getFreshToken } from "../services/http";
import { isActive, newStream, useChatStore } from "../stores/chat";
import type { GenerationParams, ServerEvent } from "../types/api";

/** Conexión única por pestaña, compartida por todas las conversaciones. */
export const chatSocket = new ChatSocket({ url: chatSocketUrl, getToken: getFreshToken });

async function settle(conversationId: string, requestId: string, removeStream: boolean) {
  // Se recargan los mensajes guardados y luego se retira el stream: sin parpadeos.
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.messages(conversationId) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.conversation(conversationId) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.conversations }),
    queryClient.invalidateQueries({ queryKey: queryKeys.toolExecutions }),
    queryClient.invalidateQueries({ queryKey: queryKeys.reports }),
  ]);
  if (removeStream) useChatStore.getState().remove(conversationId, requestId);
}

function onServerEvent(event: ServerEvent): void {
  const stream = useChatStore.getState().apply(event);
  if (!stream) return;
  if (stream.status === "done" || stream.status === "cancelled") {
    void settle(stream.conversationId, stream.requestId, true);
  } else if (stream.status === "error") {
    // El error se queda visible (con opción de reintentar); el mensaje del usuario sí
    // pudo guardarse, así que se recarga la lista.
    void settle(stream.conversationId, stream.requestId, false);
  }
}

chatSocket.subscribe(onServerEvent);

interface SendOptions {
  model?: string | null;
  params?: GenerationParams;
  attachments?: string[];
}

function fail(requestId: string, error: unknown): void {
  onServerEvent({
    type: "chat.error",
    request_id: requestId,
    code: error instanceof ChatSocketError ? error.code : "connection_failed",
    detail: error instanceof Error ? error.message : "No se pudo enviar el mensaje.",
  });
}

export function useChatActions() {
  const send = useCallback(
    async (conversationId: string, content: string, options: SendOptions = {}) => {
      const current = useChatStore.getState().streams[conversationId];
      if (isActive(current)) return;
      const requestId = newRequestId();
      useChatStore.getState().begin(newStream(requestId, conversationId, content));
      try {
        await chatSocket.request({
          type: "chat.send",
          request_id: requestId,
          conversation_id: conversationId,
          content,
          ...(options.model ? { model: options.model } : {}),
          ...(options.params ? { params: options.params } : {}),
          ...(options.attachments?.length ? { attachments: options.attachments } : {}),
        });
      } catch (error) {
        fail(requestId, error);
      }
    },
    [],
  );

  const regenerate = useCallback(async (conversationId: string, options: SendOptions = {}) => {
    const current = useChatStore.getState().streams[conversationId];
    if (isActive(current)) return;
    const requestId = newRequestId();
    useChatStore.getState().begin(newStream(requestId, conversationId, null));
    try {
      await chatSocket.request({
        type: "chat.regenerate",
        request_id: requestId,
        conversation_id: conversationId,
        ...(options.model ? { model: options.model } : {}),
      });
    } catch (error) {
      fail(requestId, error);
    }
  }, []);

  const cancel = useCallback((conversationId: string) => {
    const stream = useChatStore.getState().streams[conversationId];
    if (stream && isActive(stream)) chatSocket.cancel(stream.requestId);
  }, []);

  const confirmTool = useCallback((callId: string, approved: boolean) => {
    if (chatSocket.confirmTool(callId, approved)) {
      useChatStore.getState().markAnswered(callId, approved);
    }
  }, []);

  const dismiss = useCallback((conversationId: string) => {
    const stream = useChatStore.getState().streams[conversationId];
    if (stream && !isActive(stream)) {
      useChatStore.getState().remove(conversationId, stream.requestId);
    }
  }, []);

  return { send, regenerate, cancel, dismiss, confirmTool };
}

export function useStream(conversationId: string | undefined) {
  return useChatStore((s) => (conversationId ? s.streams[conversationId] : undefined));
}
