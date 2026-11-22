import { describe, expect, it, vi } from "vitest";
import type { ServerEvent } from "../types/api";
import { ChatSocket } from "./chatSocket";

/** WebSocket simulado controlable desde la prueba. */
class FakeSocket {
  readyState: number = WebSocket.CONNECTING;
  sent: Record<string, unknown>[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(readonly url: string) {}

  send(data: string) {
    this.sent.push(JSON.parse(data) as Record<string, unknown>);
  }
  close() {
    this.readyState = WebSocket.CLOSED;
    this.onclose?.();
  }
  // --- controles de la prueba
  open() {
    this.readyState = WebSocket.OPEN;
    this.onopen?.();
  }
  push(event: ServerEvent) {
    this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  }
  drop() {
    this.readyState = WebSocket.CLOSED;
    this.onclose?.();
  }
}

function setup(tokens: string[] = ["t1"]) {
  const sockets: FakeSocket[] = [];
  let tokenIndex = 0;
  const socket = new ChatSocket({
    url: () => "ws://test/api/v1/ws/chat",
    getToken: async () => tokens[Math.min(tokenIndex, tokens.length - 1)] ?? null,
    createSocket: (url) => {
      const fake = new FakeSocket(url);
      sockets.push(fake);
      return fake as unknown as WebSocket;
    },
    pingIntervalMs: 60_000,
  });
  const events: ServerEvent[] = [];
  socket.subscribe((event) => events.push(event));
  return { socket, sockets, events, nextToken: () => (tokenIndex += 1) };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("ChatSocket", () => {
  it("autentica con el primer mensaje y después envía el turno", async () => {
    const { socket, sockets, events } = setup();
    const pending = socket.request({
      type: "chat.send",
      request_id: "r1",
      conversation_id: "c1",
      content: "hola",
    });
    await flush();
    const ws = sockets[0]!;
    expect(ws.url).not.toContain("t1");
    ws.open();
    expect(ws.sent[0]).toEqual({ type: "auth", token: "t1" });
    ws.push({ type: "ready", user_id: "u" });
    await pending;
    expect(ws.sent[1]).toMatchObject({ type: "chat.send", request_id: "r1" });

    ws.push({ type: "chat.delta", request_id: "r1", text: "Ho" });
    expect(events).toEqual([{ type: "chat.delta", request_id: "r1", text: "Ho" }]);
  });

  it("rechaza si la autenticación falla", async () => {
    const { socket, sockets } = setup();
    const pending = socket.request({
      type: "chat.send",
      request_id: "r1",
      conversation_id: "c1",
      content: "hola",
    });
    await flush();
    sockets[0]!.open();
    sockets[0]!.push({ type: "error", code: "unauthorized", detail: "no" });
    await expect(pending).rejects.toMatchObject({ code: "unauthorized" });
  });

  it("emite connection_lost para los turnos en curso si se cae", async () => {
    const { socket, sockets, events } = setup();
    const pending = socket.request({
      type: "chat.send",
      request_id: "r1",
      conversation_id: "c1",
      content: "hola",
    });
    await flush();
    sockets[0]!.open();
    sockets[0]!.push({ type: "ready", user_id: "u" });
    await pending;
    sockets[0]!.drop();
    expect(events.at(-1)).toMatchObject({ type: "chat.error", code: "connection_lost" });
    expect(socket.connected).toBe(false);
  });

  it("se re-autentica cuando el token cambia y normaliza errores con request_id", async () => {
    const { socket, sockets, events, nextToken } = setup(["t1", "t2"]);
    const first = socket.request({
      type: "chat.send",
      request_id: "r1",
      conversation_id: "c1",
      content: "a",
    });
    await flush();
    const ws = sockets[0]!;
    ws.open();
    ws.push({ type: "ready", user_id: "u" });
    await first;

    nextToken();
    await socket.request({ type: "chat.regenerate", request_id: "r2", conversation_id: "c1" });
    expect(ws.sent.map((m) => m.type)).toEqual(["auth", "chat.send", "auth", "chat.regenerate"]);
    expect(ws.sent[2]).toEqual({ type: "auth", token: "t2" });

    ws.push({ type: "error", code: "busy", detail: "ocupado", request_id: "r2" });
    expect(events.at(-1)).toEqual({
      type: "chat.error",
      request_id: "r2",
      code: "busy",
      detail: "ocupado",
    });
  });

  it("cancel envía chat.cancel solo con la conexión abierta", async () => {
    const { socket, sockets } = setup();
    socket.cancel("nada");
    expect(sockets).toHaveLength(0);
    const pending = socket.request({
      type: "chat.send",
      request_id: "r1",
      conversation_id: "c1",
      content: "a",
    });
    await flush();
    sockets[0]!.open();
    sockets[0]!.push({ type: "ready", user_id: "u" });
    await pending;
    socket.cancel("r1");
    expect(sockets[0]!.sent.at(-1)).toEqual({ type: "chat.cancel", request_id: "r1" });
    vi.restoreAllMocks();
  });
});
