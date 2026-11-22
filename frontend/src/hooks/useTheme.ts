import { useEffect } from "react";
import { useUi } from "../stores/ui";

/** Aplica el tema activo a <html data-theme> y sigue al sistema si es "system". */
export function useApplyTheme(): void {
  const theme = useUi((s) => s.theme);

  useEffect(() => {
    const root = document.documentElement;
    const media = window.matchMedia?.("(prefers-color-scheme: light)");
    const apply = () => {
      const resolved = theme === "system" ? (media?.matches ? "light" : "dark") : theme;
      root.dataset.theme = resolved;
    };
    apply();
    if (theme !== "system" || !media) return;
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);
}
