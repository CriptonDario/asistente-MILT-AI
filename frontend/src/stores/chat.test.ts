import { describe, expect, it } from "vitest";
import { visibleTimeline } from "../components/chat/MessageList";
import type { Message } from "../types/api";
import { isActive, newStream, reduceStream, useChatStore } from "./chat";

describe("reduceStream", () => {
  const base = newStream("r1", "c1", "hola");

  it("recorre started -> delta -> done", () => {
    let s = reduceStream(base, {
      type: "chat.started",
      request_id: "r1",
      conversation_id: "c1",
      message_id: "m2",
      user_message_id: "m1",
      model: "qwen3:1.7b",
      context_dropped_messages: 0,
    });
    expect(s.messageId).toBe("m2");
    expect(isActive(s)).toBe(true);
    s = reduceStream(s, { type: "chat.delta", request_id: "r1", text: "Ho" });
    s = reduceStream(s, { type: "chat.delta", request_id: "r1", text: "la" });
    expect(s.text).toBe("Hola");
    expect(s.status).toBe("streaming");
    s = reduceStream(s, {
      type: "chat.done",
      request_id: "r1",
      message_id: "m2",
      usage: { prompt_tokens: 1, completion_tokens: 2, latency_ms: 3, first_token_ms: 1 },
    });
    expect(s.status).toBe("done");
    expect(isActive(s)).toBe(false);
  });

  it("guarda las fuentes y avisos de chat.context", () => {
    const s = reduceStream(base, {
      type: "chat.context",
      request_id: "r1",
      sources: [{ kind: "document", id: "k1", title: "orion.txt", ref: 1, location: "pág. 2" }],
      warnings: ["aviso"],
    });
    expect(s.sources[0]?.title).toBe("orion.txt");
    expect(s.warnings).toEqual(["aviso"]);
    expect(s.status).toBe("pending");
  });

  it("distingue cancelación de error y ignora otros request_id", () => {
    expect(
      reduceStream(base, { type: "chat.error", request_id: "r1", code: "cancelled", detail: "" })
        .status,
    ).toBe("cancelled");
    const failed = reduceStream(base, {
      type: "chat.error",
      request_id: "r1",
      code: "provider_unavailable",
      detail: "Ollama apagado",
    });
    expect(failed.status).toBe("error");
    expect(failed.error?.code).toBe("provider_unavailable");
    expect(reduceStream(base, { type: "chat.delta", request_id: "otro", text: "x" })).toBe(base);
  });
});

describe("useChatStore", () => {
  it("aplica eventos al stream correcto y lo elimina", () => {
    const store = useChatStore.getState();
    store.begin(newStream("a", "conv-a", "x"));
    store.begin(newStream("b", "conv-b", "y"));
    useChatStore.getState().apply({ type: "chat.delta", request_id: "b", text: "hola" });
    expect(useChatStore.getState().streams["conv-b"]?.text).toBe("hola");
    expect(useChatStore.getState().streams["conv-a"]?.text).toBe("");
    useChatStore.getState().remove("conv-b", "otro-id");
    expect(useChatStore.getState().streams["conv-b"]).toBeDefined();
    useChatStore.getState().remove("conv-b", "b");
    expect(useChatStore.getState().streams["conv-b"]).toBeUndefined();
  });
});

describe("visibleTimeline", () => {
  const msg = (id: string, role: "user" | "assistant"): Message => ({
    id,
    conversation_id: "c",
    role,
    content: id,
    model: null,
    status: "complete",
    prompt_tokens: null,
    completion_tokens: null,
    latency_ms: null,
    context_sources: null,
    attachments: [],
    created_at: "2026-01-01T00:00:00Z",
  });

  it("muestra el mensaje optimista hasta que llega el guardado, sin duplicar", () => {
    const stream = { ...newStream("r", "c", "hola"), userMessageId: "u1", messageId: "a1" };
    expect(visibleTimeline([], stream)).toEqual({ showOptimisticUser: true, showStream: true });
    expect(visibleTimeline([msg("u1", "user")], stream)).toEqual({
      showOptimisticUser: false,
      showStream: true,
    });
    expect(visibleTimeline([msg("u1", "user"), msg("a1", "assistant")], stream)).toEqual({
      showOptimisticUser: false,
      showStream: false,
    });
  });
});
