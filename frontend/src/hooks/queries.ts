import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";
import { queryClient, queryKeys } from "../app/queryClient";
import {
  authApi,
  conversationsApi,
  modelsApi,
  settingsApi,
  systemApi,
} from "../services/endpoints";
import type { ConversationCreate, ConversationUpdate, SettingsUpdate } from "../types/api";

export function useConversationList(archived: boolean, q: string) {
  return useInfiniteQuery({
    queryKey: queryKeys.conversationList(archived, q),
    queryFn: ({ pageParam }) =>
      conversationsApi.list({ cursor: pageParam, archived, q: q || undefined, limit: 30 }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

export function useConversation(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.conversation(id ?? ""),
    queryFn: () => conversationsApi.get(id as string),
    enabled: Boolean(id),
  });
}

export function useMessages(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.messages(id ?? ""),
    queryFn: () => conversationsApi.allMessages(id as string),
    enabled: Boolean(id),
    staleTime: 5 * 60_000,
  });
}

export function useModels() {
  return useQuery({ queryKey: queryKeys.models, queryFn: modelsApi.list, staleTime: 60_000 });
}

export function useSettings() {
  return useQuery({ queryKey: queryKeys.settings, queryFn: settingsApi.get });
}

export function useSystemInfo() {
  return useQuery({
    queryKey: queryKeys.system,
    queryFn: systemApi.info,
    refetchInterval: 15_000,
    staleTime: 10_000,
  });
}

export function useSessions(enabled: boolean) {
  return useQuery({ queryKey: queryKeys.sessions, queryFn: authApi.sessions, enabled });
}

// ------------------------------------------------------------------ mutaciones
function invalidateConversations(id?: string) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
  if (id) void queryClient.invalidateQueries({ queryKey: queryKeys.conversation(id) });
}

export function useCreateConversation() {
  return useMutation({
    mutationFn: (body: ConversationCreate) => conversationsApi.create(body),
    onSuccess: (conv) => {
      queryClient.setQueryData(queryKeys.conversation(conv.id), conv);
      queryClient.setQueryData(queryKeys.messages(conv.id), []);
      invalidateConversations();
    },
  });
}

export function useUpdateConversation() {
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ConversationUpdate }) =>
      conversationsApi.update(id, body),
    onSuccess: (conv) => {
      queryClient.setQueryData(queryKeys.conversation(conv.id), conv);
      invalidateConversations();
    },
  });
}

export function useDeleteConversation() {
  return useMutation({
    mutationFn: (id: string) => conversationsApi.remove(id),
    onSuccess: (_data, id) => {
      queryClient.removeQueries({ queryKey: queryKeys.conversation(id) });
      queryClient.removeQueries({ queryKey: queryKeys.messages(id) });
      invalidateConversations();
    },
  });
}

export function useDeleteMessage(conversationId: string) {
  return useMutation({
    mutationFn: (messageId: string) => conversationsApi.deleteMessage(conversationId, messageId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.messages(conversationId) }),
  });
}

export function useUpdateSettings() {
  return useMutation({
    mutationFn: (body: SettingsUpdate) => settingsApi.update(body),
    onSuccess: (settings) => queryClient.setQueryData(queryKeys.settings, settings),
  });
}
