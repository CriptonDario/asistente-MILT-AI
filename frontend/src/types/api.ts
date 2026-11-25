/**
 * Alias legibles sobre los tipos generados desde el OpenAPI del backend
 * (`pnpm gen:types`). No editar `api.gen.ts` a mano.
 */
import type { components } from "./api.gen";

type Schemas = components["schemas"];

export type User = Schemas["UserOut"];
export type TokenResponse = Schemas["TokenResponse"];
export type SessionInfo = Schemas["SessionOut"];
export type Conversation = Schemas["ConversationOut"];
// Los campos con valor por defecto en el backend salen como obligatorios en el esquema.
export type ConversationCreate = Partial<Schemas["ConversationCreate"]>;
export type ConversationUpdate = Schemas["ConversationUpdate"];
export type Message = Schemas["MessageOut"];
export type ConversationPage = Schemas["Page_ConversationOut_"];
export type MessagePage = Schemas["Page_MessageOut_"];
export type ModelInfo = Schemas["ModelOut"];
export type UserSettings = Schemas["SettingsOut"];
export type SettingsUpdate = Schemas["SettingsUpdate"];
export type GenerationParams = Schemas["GenerationParams"];
export type SystemInfo = Schemas["SystemInfoOut"];
export type SetupStatus = Schemas["SetupStatusOut"];
export type Theme = UserSettings["theme"];
export type Memory = Schemas["MemoryOut"];
export type MemoryKind = Memory["kind"];
export type MemoryCreate = Partial<Schemas["MemoryCreate"]> & { content: string };
export type MemoryUpdate = Schemas["MemoryUpdate"];
export type MemoryStats = Schemas["MemoryStats"];
export type ExtractResult = Schemas["ExtractResult"];
export type DocumentInfo = Schemas["DocumentOut"];
export type UploadResult = Schemas["UploadResult"];
export type ContextSource = Schemas["ContextSource"];
export type Attachment = Schemas["AttachmentOut"];
export type ToolInfo = Schemas["ToolOut"];
export type ToolDecision = ToolInfo["decision"];
export type ToolExecution = Schemas["ExecutionOut"];
export type ScriptInfo = Schemas["ScriptOut"];
export type ScriptCreate = Partial<Schemas["ScriptCreate"]> & { name: string; path: string };
export type ReportSummary = Schemas["ReportSummary"];
export type Report = Schemas["ReportOut"];
export type VoiceStatus = Schemas["VoiceStatusOut"];
export type AgentProfile = NonNullable<ConversationUpdate["agent_profile"]>;

/** Herramienta usada en una respuesta (tal como se guarda en el mensaje). */
export interface ToolCallLog {
  call_id: string;
  tool: string;
  risk: string;
  status: "ok" | "error" | "denied";
  decision: string;
  summary: string;
}

/** Cuerpo de error RFC 9457 que devuelve el backend. */
export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  code: string;
  detail: string | null;
  instance: string | null;
  errors?: { loc: (string | number)[]; msg: string; type: string }[];
}

// ----------------------------------------------------------------- protocolo WS
export type ClientEvent =
  | { type: "auth"; token: string }
  | { type: "ping" }
  | {
      type: "chat.send";
      request_id: string;
      conversation_id: string;
      content: string;
      model?: string;
      params?: GenerationParams;
      attachments?: string[];
      use_memory?: boolean;
    }
  | {
      type: "chat.regenerate";
      request_id: string;
      conversation_id: string;
      model?: string;
      params?: GenerationParams;
    }
  | { type: "chat.cancel"; request_id: string }
  | { type: "tool.confirm"; call_id: string; approved: boolean };

export interface ChatUsage {
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
  first_token_ms: number | null;
}

export type ServerEvent =
  | { type: "ready"; user_id: string }
  | { type: "pong" }
  | {
      type: "chat.started";
      request_id: string;
      conversation_id: string;
      message_id: string;
      user_message_id: string;
      model: string;
      context_dropped_messages: number;
    }
  | {
      type: "chat.context";
      request_id: string;
      sources: ContextSource[];
      warnings: string[];
    }
  | {
      type: "tool.call";
      request_id: string;
      call_id: string;
      tool: string;
      arguments: Record<string, unknown>;
      risk: string;
      summary: string;
    }
  | {
      type: "tool.confirm_request";
      request_id: string;
      call_id: string;
      tool: string;
      summary: string;
      arguments: Record<string, unknown>;
      risk: string;
      expires_in: number;
    }
  | {
      type: "tool.result";
      request_id: string;
      call_id: string;
      status: "ok" | "error" | "denied";
      summary: string;
    }
  | { type: "chat.delta"; request_id: string; text: string }
  | { type: "chat.thinking"; request_id: string; text: string }
  | { type: "chat.done"; request_id: string; message_id: string; usage: ChatUsage }
  | { type: "chat.error"; request_id: string; code: string; detail: string }
  | { type: "error"; code: string; detail: string; request_id?: string };
