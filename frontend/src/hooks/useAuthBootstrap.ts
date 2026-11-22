import { useEffect } from "react";
import { refreshAccessToken } from "../services/http";
import { useSession } from "../stores/session";

/**
 * Al cargar la app intenta recuperar la sesión con la cookie de refresh y, mientras
 * haya sesión, renueva el access token un minuto antes de que caduque.
 */
export function useAuthBootstrap(): void {
  const status = useSession((s) => s.status);
  const expiresAt = useSession((s) => s.expiresAt);

  useEffect(() => {
    if (status !== "loading") return;
    void refreshAccessToken().then((token) => {
      if (!token && useSession.getState().status === "loading") useSession.getState().clear();
    });
  }, [status]);

  useEffect(() => {
    if (status !== "authenticated" || !expiresAt) return;
    const delay = Math.max(5_000, expiresAt - Date.now() - 60_000);
    const timer = setTimeout(() => void refreshAccessToken(), delay);
    return () => clearTimeout(timer);
  }, [status, expiresAt]);
}
