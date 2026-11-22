import type { ClientEvent, ServerEvent } from "../types/api";

export class ChatSocketError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "ChatSocketError";
    this.code = code;
  }
}

type Listener = (event: ServerEvent) => void;
type ChatRequest = Extract<ClientEvent, { type: "chat.send" | "chat.regenerate" }>;

export interface ChatSocketOptions {
  url: () => string;
  /** Devuelve un access token vigente (renovándolo si hace falta). */
  getToken: () => Promise<string | null>;
  createSocket?: (url: string) => WebSocket;
  pingIntervalMs?: number;
}

/**
 * Cliente del WebSocket de chat (`/api/v1/ws/chat`).
 *
 * - Autentica con el primer mensaje (el token no va en la URL).
 * - Conecta bajo demanda y reconecta en el siguiente envío si se cae.
 * - Renueva la autenticación en la misma conexión cuando el token cambia.
 * - Si la conexión se pierde, emite `chat.error` para cada petición en curso.
 */
export class ChatSocket {
  private ws: WebSocket | null = null;
  private opening: Promise<void> | null = null;
  private authedToken: string | null = null;
  private readonly listeners = new Set<Listener>();
  private readonly inflight = new Map<string, ChatRequest>();
  private readonly retried = new Set<string>();
  private pingTimer: ReturnType<typeof setInterval> | null = null;

  constructor(private readonly options: ChatSocketOptions) {}

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN && this.opening === null;
  }

  /** Envía un turno de chat. Los eventos llegan a los suscriptores. */
  async request(message: ChatRequest): Promise<void> {
    this.inflight.set(message.request_id, message);
    try {
      await this.ensureAuthenticated();
      this.write(message);
    } catch (error) {
      this.inflight.delete(message.request_id);
      throw error;
    }
  }

  cancel(requestId: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.write({ type: "chat.cancel", request_id: requestId });
    }
  }

  close(): void {
    this.stopPing();
    const ws = this.ws;
    this.ws = null;
    this.opening = null;
    this.authedToken = null;
    ws?.close(1000);
  }

  // ------------------------------------------------------------------ interno
  private emit(event: ServerEvent): void {
    for (const listener of this.listeners) listener(event);
  }

  private write(message: ClientEvent): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new ChatSocketError("connection_lost", "Sin conexión con MILT.");
    }
    this.ws.send(JSON.stringify(message));
  }

  private async ensureAuthenticated(): Promise<void> {
    if (!this.ws || this.ws.readyState > WebSocket.OPEN) {
      this.opening ??= this.open().finally(() => {
        this.opening = null;
      });
    }
    if (this.opening) await this.opening;
    // Si el token se renovó desde que nos autenticamos, se re-autentica la conexión.
    const token = await this.options.getToken();
    if (!token) throw new ChatSocketError("unauthorized", "La sesión ha caducado.");
    if (token !== this.authedToken) {
      this.authedToken = token;
      this.write({ type: "auth", token });
    }
  }

  private open(): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      void (async () => {
        const token = await this.options.getToken();
        if (!token) {
          reject(new ChatSocketError("unauthorized", "La sesión ha caducado."));
          return;
        }
        const factory = this.options.createSocket ?? ((url: string) => new WebSocket(url));
        const ws = factory(this.options.url());
        this.ws = ws;
        let settled = false;

        ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token } satisfies ClientEvent));
        ws.onmessage = (message: MessageEvent) => {
          let event: ServerEvent;
          try {
            event = JSON.parse(String(message.data)) as ServerEvent;
          } catch {
            return;
          }
          if (!settled) {
            if (event.type === "ready") {
              settled = true;
              this.authedToken = token;
              this.startPing();
              resolve();
            } else if (event.type === "error") {
              settled = true;
              reject(new ChatSocketError(event.code, event.detail));
            }
            return;
          }
          this.handle(event);
        };
        ws.onclose = () => {
          if (this.ws === ws) {
            this.ws = null;
            this.authedToken = null;
            this.stopPing();
          }
          if (!settled) {
            settled = true;
            reject(new ChatSocketError("connection_failed", "No se pudo conectar con MILT."));
          }
          this.failInflight();
        };
        ws.onerror = () => {
          // onclose se dispara a continuación y gestiona el error.
        };
      })().catch(reject);
    });
  }

  private handle(event: ServerEvent): void {
    if (event.type === "pong" || event.type === "ready") return;

    if (event.type === "error" && event.request_id) {
      const pending = this.inflight.get(event.request_id);
      // Token caducado justo en el envío: se renueva y se reintenta una vez.
      if (event.code === "token_expired" && pending && !this.retried.has(pending.request_id)) {
        this.retried.add(pending.request_id);
        this.authedToken = null;
        void this.ensureAuthenticated()
          .then(() => this.write(pending))
          .catch((error: unknown) =>
            this.finish({
              type: "chat.error",
              request_id: pending.request_id,
              code: error instanceof ChatSocketError ? error.code : "unauthorized",
              detail: error instanceof Error ? error.message : "Sesión no válida.",
            }),
          );
        return;
      }
      // Errores asociados a una petición se normalizan como chat.error.
      this.finish({
        type: "chat.error",
        request_id: event.request_id,
        code: event.code,
        detail: event.detail,
      });
      return;
    }

    if (event.type === "chat.done" || event.type === "chat.error") {
      this.finish(event);
      return;
    }
    this.emit(event);
  }

  private finish(event: Extract<ServerEvent, { type: "chat.done" | "chat.error" }>): void {
    this.inflight.delete(event.request_id);
    this.retried.delete(event.request_id);
    this.emit(event);
  }

  private failInflight(): void {
    for (const requestId of [...this.inflight.keys()]) {
      this.finish({
        type: "chat.error",
        request_id: requestId,
        code: "connection_lost",
        detail: "Se perdió la conexión con MILT.",
      });
    }
  }

  private startPing(): void {
    this.stopPing();
    const interval = this.options.pingIntervalMs ?? 25_000;
    this.pingTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) this.write({ type: "ping" });
    }, interval);
  }

  private stopPing(): void {
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.pingTimer = null;
  }
}
