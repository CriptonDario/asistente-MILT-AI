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
    }
  | {
      type: "chat.regenerate";
      request_id: string;
      conversation_id: string;
      model?: string;
      params?: GenerationParams;
    }
  | { type: "chat.cancel"; request_id: string };

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
  | { type: "chat.delta"; request_id: string; text: string }
  | { type: "chat.thinking"; request_id: string; text: string }
  | { type: "chat.done"; request_id: string; message_id: string; usage: ChatUsage }
  | { type: "chat.error"; request_id: string; code: string; detail: string }
  | { type: "error"; code: string; detail: string; request_id?: string };
