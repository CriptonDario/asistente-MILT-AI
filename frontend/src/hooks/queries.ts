import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";
import { queryClient, queryKeys } from "../app/queryClient";
import {
  authApi,
  conversationsApi,
  documentsApi,
  memoriesApi,
  modelsApi,
  toolsApi,
  voiceApi,
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

// ------------------------------------------------------------------ memoria
export function useMemories(q: string) {
  return useQuery({
    queryKey: [...queryKeys.memories, { q }],
    queryFn: () => memoriesApi.list({ q: q || undefined }),
  });
}

export function useMemorySuggestions() {
  return useQuery({ queryKey: queryKeys.memorySuggestions, queryFn: memoriesApi.suggestions });
}

export function useMemoryStats() {
  return useQuery({ queryKey: queryKeys.memoryStats, queryFn: memoriesApi.stats });
}

export function invalidateMemory() {
  void queryClient.invalidateQueries({ queryKey: queryKeys.memories });
  void queryClient.invalidateQueries({ queryKey: queryKeys.memorySuggestions });
  void queryClient.invalidateQueries({ queryKey: queryKeys.memoryStats });
}

export function useExtractMemories() {
  return useMutation({
    mutationFn: (conversationId: string) => memoriesApi.extract(conversationId),
    onSuccess: invalidateMemory,
  });
}

// ------------------------------------------------------------------ documentos
const PROCESSING = new Set(["pending", "processing"]);

export function useDocuments() {
  return useQuery({
    queryKey: queryKeys.documents,
    queryFn: documentsApi.list,
    // Mientras haya documentos procesándose, se consulta su estado cada 2 s.
    refetchInterval: (query) =>
      query.state.data?.some((d) => PROCESSING.has(d.status)) ? 2000 : false,
  });
}

export function useUploadDocument() {
  return useMutation({
    mutationFn: (file: File) => documentsApi.upload(file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.documents }),
  });
}

export function useDeleteDocument() {
  return useMutation({
    mutationFn: (id: string) => documentsApi.remove(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.documents }),
  });
}

export function useReindexDocument() {
  return useMutation({
    mutationFn: (id: string) => documentsApi.reindex(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.documents }),
  });
}

// ------------------------------------------------------------------ herramientas
export function useTools(enabled = true) {
  return useQuery({ queryKey: queryKeys.tools, queryFn: toolsApi.list, enabled });
}

export function useToolRoots() {
  return useQuery({ queryKey: queryKeys.toolRoots, queryFn: toolsApi.roots });
}

export function useToolExecutions() {
  return useQuery({ queryKey: queryKeys.toolExecutions, queryFn: () => toolsApi.executions(30) });
}

export function useScripts() {
  return useQuery({ queryKey: queryKeys.scripts, queryFn: toolsApi.scripts });
}

export function useReports() {
  return useQuery({ queryKey: queryKeys.reports, queryFn: toolsApi.reports });
}

export function useVoiceStatus() {
  return useQuery({
    queryKey: queryKeys.voice,
    queryFn: voiceApi.status,
    staleTime: 5 * 60_000,
    retry: false,
  });
}
