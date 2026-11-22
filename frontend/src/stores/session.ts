import { create } from "zustand";
import type { TokenResponse, User } from "../types/api";

export type SessionStatus = "loading" | "authenticated" | "anonymous";

interface SessionState {
  status: SessionStatus;
  /** El access token vive solo en memoria (nunca en localStorage). */
  accessToken: string | null;
  /** Instante (ms epoch) en que caduca el access token. */
  expiresAt: number | null;
  user: User | null;
  setSession: (tokens: TokenResponse) => void;
  setUser: (user: User) => void;
  clear: () => void;
}

export const useSession = create<SessionState>()((set) => ({
  status: "loading",
  accessToken: null,
  expiresAt: null,
  user: null,
  setSession: (tokens) =>
    set({
      status: "authenticated",
      accessToken: tokens.access_token,
      expiresAt: Date.now() + tokens.expires_in * 1000,
      user: tokens.user,
    }),
  setUser: (user) => set({ user }),
  clear: () => set({ status: "anonymous", accessToken: null, expiresAt: null, user: null }),
}));
