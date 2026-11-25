import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "../services/http";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // Los errores de cliente (4xx) no se reintentan.
        if (error instanceof ApiError && error.status < 500) return false;
        return failureCount < 2;
      },
    },
  },
});

export const queryKeys = {
  conversations: ["conversations"] as const,
  conversationList: (archived: boolean, q: string) => ["conversations", { archived, q }] as const,
  conversation: (id: string) => ["conversation", id] as const,
  messages: (id: string) => ["messages", id] as const,
  models: ["models"] as const,
  settings: ["settings"] as const,
  system: ["system"] as const,
  sessions: ["sessions"] as const,
  memories: ["memories"] as const,
  memorySuggestions: ["memory-suggestions"] as const,
  memoryStats: ["memory-stats"] as const,
  documents: ["documents"] as const,
  tools: ["tools"] as const,
  toolRoots: ["tool-roots"] as const,
  toolExecutions: ["tool-executions"] as const,
  scripts: ["scripts"] as const,
  reports: ["reports"] as const,
  voice: ["voice"] as const,
};
