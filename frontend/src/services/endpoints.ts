/** Funciones tipadas para cada endpoint REST del backend (docs/fase-1/04-api.md). */
import type {
  Conversation,
  ConversationCreate,
  ConversationPage,
  ConversationUpdate,
  DocumentInfo,
  ExtractResult,
  Memory,
  MemoryCreate,
  MemoryKind,
  MemoryStats,
  MemoryUpdate,
  Message,
  MessagePage,
  ModelInfo,
  Report,
  ReportSummary,
  ScriptCreate,
  ScriptInfo,
  ToolDecision,
  ToolExecution,
  ToolInfo,
  UploadResult,
  VoiceStatus,
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

// ------------------------------------------------------------------- memoria
export const memoriesApi = {
  list: (params: { kind?: MemoryKind; q?: string } = {}) =>
    api<Memory[]>("/memories", { query: params }),
  stats: () => api<MemoryStats>("/memories/stats"),
  suggestions: () => api<Memory[]>("/memories/suggestions"),
  create: (body: MemoryCreate) => api<Memory>("/memories", { method: "POST", body }),
  update: (id: string, body: MemoryUpdate) =>
    api<Memory>(`/memories/${id}`, { method: "PATCH", body }),
  remove: (id: string) => api<void>(`/memories/${id}`, { method: "DELETE" }),
  removeAll: () => api<void>("/memories", { method: "DELETE", body: { confirm: "DELETE" } }),
  accept: (id: string) => api<Memory>(`/memories/suggestions/${id}/accept`, { method: "POST" }),
  reject: (id: string) => api<void>(`/memories/suggestions/${id}/reject`, { method: "POST" }),
  extract: (conversationId: string) =>
    api<ExtractResult>("/memories/extract", {
      method: "POST",
      body: { conversation_id: conversationId },
    }),
  reindex: () => api<MemoryStats>("/memories/reindex", { method: "POST" }),
};

// ------------------------------------------------------------------- documentos
export const documentsApi = {
  list: () => api<DocumentInfo[]>("/documents"),
  get: (id: string) => api<DocumentInfo>(`/documents/${id}`),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api<UploadResult>("/documents", { method: "POST", body: form });
  },
  remove: (id: string) => api<void>(`/documents/${id}`, { method: "DELETE" }),
  reindex: (id: string) => api<DocumentInfo>(`/documents/${id}/reindex`, { method: "POST" }),
  /** Descarga el original como Blob (el endpoint exige el token de acceso). */
  download: async (doc: DocumentInfo) => {
    const blob = await api<Blob>(`/documents/${doc.id}/file`, { responseType: "blob" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = doc.filename;
    link.click();
    URL.revokeObjectURL(url);
  },
};

// ------------------------------------------------------------------- herramientas
export const toolsApi = {
  list: () => api<ToolInfo[]>("/tools"),
  setPolicy: (name: string, decision: ToolDecision | "default") =>
    api<ToolInfo>(`/tools/policies/${name}`, { method: "PUT", body: { decision } }),
  executions: (limit = 30) => api<ToolExecution[]>("/tools/executions", { query: { limit } }),
  roots: () => api<{ roots: string[] }>("/settings/allowed-roots"),
  setRoots: (roots: string[]) =>
    api<{ roots: string[] }>("/settings/allowed-roots", { method: "PUT", body: { roots } }),
  scripts: () => api<ScriptInfo[]>("/automation/scripts"),
  registerScript: (body: ScriptCreate) =>
    api<ScriptInfo>("/automation/scripts", { method: "POST", body }),
  reauthorizeScript: (id: string) =>
    api<ScriptInfo>(`/automation/scripts/${id}/reauthorize`, { method: "POST" }),
  deleteScript: (id: string) => api<void>(`/automation/scripts/${id}`, { method: "DELETE" }),
  reports: () => api<ReportSummary[]>("/security/reports"),
  report: (id: string) => api<Report>(`/security/reports/${id}`),
  deleteReport: (id: string) => api<void>(`/security/reports/${id}`, { method: "DELETE" }),
  downloadReport: async (report: ReportSummary) => {
    const text = await api<string>(`/security/reports/${report.id}/markdown`);
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${report.title.slice(0, 60)}.md`;
    link.click();
    URL.revokeObjectURL(url);
  },
};

// ------------------------------------------------------------------- voz
export const voiceApi = {
  status: () => api<VoiceStatus>("/voice/status"),
  transcribe: (audio: Blob) => {
    const form = new FormData();
    const ext = audio.type.includes("ogg") ? "ogg" : audio.type.includes("mp4") ? "mp4" : "webm";
    form.append("audio", audio, `voz.${ext}`);
    return api<{ text: string; duration_ms: number }>("/voice/transcribe", {
      method: "POST",
      body: form,
    });
  },
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
