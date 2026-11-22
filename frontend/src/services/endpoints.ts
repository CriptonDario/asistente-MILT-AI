/** Funciones tipadas para cada endpoint REST del backend (docs/fase-1/04-api.md). */
import type {
  Conversation,
  ConversationCreate,
  ConversationPage,
  ConversationUpdate,
  Message,
  MessagePage,
  ModelInfo,
  SessionInfo,
  SettingsUpdate,
  SetupStatus,
  SystemInfo,
  TokenResponse,
  User,
  UserSettings,
} from "../types/api";
import { api } from "./http";

// ------------------------------------------------------------------- auth
export const authApi = {
  setup: () => api<SetupStatus>("/system/setup", { auth: false }),
  register: (body: { email: string; password: string; display_name: string }) =>
    api<User>("/auth/register", { method: "POST", body, auth: false }),
  login: (body: { email: string; password: string; device_name?: string }) =>
    api<TokenResponse>("/auth/login", {
      method: "POST",
      body: { ...body, platform: "web", use_cookie: true },
      auth: false,
    }),
  logout: () => api<void>("/auth/logout", { method: "POST" }),
  me: () => api<User>("/auth/me"),
  changePassword: (current_password: string, new_password: string) =>
    api<void>("/auth/me/password", { method: "PATCH", body: { current_password, new_password } }),
  sessions: () => api<SessionInfo[]>("/sessions"),
  revokeSession: (id: string) => api<void>(`/sessions/${id}`, { method: "DELETE" }),
};

// ------------------------------------------------------------------- conversaciones
export const conversationsApi = {
  list: (params: { cursor?: string | null; archived?: boolean; q?: string; limit?: number }) =>
    api<ConversationPage>("/conversations", { query: params }),
  get: (id: string) => api<Conversation>(`/conversations/${id}`),
  create: (body: ConversationCreate) =>
    api<Conversation>("/conversations", { method: "POST", body }),
  update: (id: string, body: ConversationUpdate) =>
    api<Conversation>(`/conversations/${id}`, { method: "PATCH", body }),
  remove: (id: string) => api<void>(`/conversations/${id}`, { method: "DELETE" }),
  messagesPage: (id: string, cursor?: string | null) =>
    api<MessagePage>(`/conversations/${id}/messages`, { query: { cursor, limit: 200 } }),
  /** Todos los mensajes (recorre la paginación por cursor). */
  async allMessages(id: string): Promise<Message[]> {
    const out: Message[] = [];
    let cursor: string | null | undefined = null;
    do {
      const page: MessagePage = await conversationsApi.messagesPage(id, cursor);
      out.push(...page.items);
      cursor = page.next_cursor;
    } while (cursor);
    return out;
  },
  deleteMessage: (id: string, messageId: string) =>
    api<void>(`/conversations/${id}/messages/${messageId}`, { method: "DELETE" }),
  exportMarkdown: (id: string) =>
    api<string>(`/conversations/${id}/export`, { query: { format: "md" } }),
};

// ------------------------------------------------------------------- otros
export const modelsApi = {
  list: () => api<ModelInfo[]>("/models"),
};

export const settingsApi = {
  get: () => api<UserSettings>("/settings"),
  update: (body: SettingsUpdate) => api<UserSettings>("/settings", { method: "PATCH", body }),
};

export const systemApi = {
  info: () => api<SystemInfo>("/system/info"),
};
