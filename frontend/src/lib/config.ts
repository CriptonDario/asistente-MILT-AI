/** Base de la API. En desarrollo, Vite hace de proxy de /api hacia el backend local. */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api/v1";

/** URL del WebSocket de chat, derivada de API_BASE (relativa o absoluta). */
export function chatSocketUrl(): string {
  const base = new URL(API_BASE, window.location.href);
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  base.pathname = `${base.pathname.replace(/\/$/, "")}/ws/chat`;
  return base.toString();
}
