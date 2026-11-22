import { create } from "zustand";
import type { Theme } from "../types/api";

export type Panel = "settings" | "memory" | null;

const THEME_KEY = "milt.theme";

function readTheme(): Theme {
  try {
    const value = localStorage.getItem(THEME_KEY);
    if (value === "dark" || value === "light" || value === "system") return value;
  } catch {
    // Almacenamiento no disponible (modo privado): se usa el valor por defecto.
  }
  return "system";
}

interface UiState {
  theme: Theme;
  sidebarOpen: boolean;
  panel: Panel;
  /** Modelo elegido antes de crear la conversación. */
  draftModel: string | null;
  setTheme: (theme: Theme) => void;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  openPanel: (panel: Panel) => void;
  setDraftModel: (model: string | null) => void;
}

export const useUi = create<UiState>()((set) => ({
  theme: readTheme(),
  sidebarOpen: typeof window === "undefined" ? true : window.innerWidth >= 768,
  panel: null,
  draftModel: null,
  setTheme: (theme) => {
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      // Sin persistencia local: el tema se mantiene durante la sesión.
    }
    set({ theme });
  },
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  openPanel: (panel) => set({ panel }),
  setDraftModel: (model) => set({ draftModel: model }),
}));
