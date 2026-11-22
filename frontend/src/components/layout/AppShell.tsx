import { useEffect } from "react";
import { Outlet, useNavigate } from "react-router";
import { useSettings } from "../../hooks/queries";
import { cn } from "../../lib/cn";
import { useUi } from "../../stores/ui";
import { MemoryPanel } from "../memory/MemoryPanel";
import { SettingsPanel } from "../settings/SettingsPanel";
import { Sidebar } from "./Sidebar";

export function AppShell() {
  const sidebarOpen = useUi((s) => s.sidebarOpen);
  const setSidebarOpen = useUi((s) => s.setSidebarOpen);
  const panel = useUi((s) => s.panel);
  const navigate = useNavigate();
  const settings = useSettings();

  // El tema guardado en el servidor manda al iniciar sesión.
  const serverTheme = settings.data?.theme;
  useEffect(() => {
    if (serverTheme) useUi.getState().setTheme(serverTheme);
  }, [serverTheme]);

  // Atajos de teclado globales.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.ctrlKey || event.metaKey;
      if (mod && event.shiftKey && event.key.toLowerCase() === "o") {
        event.preventDefault();
        navigate("/");
      } else if (mod && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSidebarOpen(true);
        setTimeout(() => document.getElementById("conversation-search")?.focus(), 0);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [navigate, setSidebarOpen]);

  return (
    <div className="flex h-full overflow-hidden">
      {/* Escritorio: columna fija. Móvil: cajón superpuesto. */}
      <div
        className={cn(
          "fixed inset-y-0 left-0 z-30 transition-transform duration-200 md:static md:z-auto",
          sidebarOpen ? "translate-x-0" : "-translate-x-full md:hidden",
        )}
      >
        <Sidebar />
      </div>
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/40 md:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}
      <main className="flex min-w-0 flex-1 flex-col">
        <Outlet />
      </main>
      {panel === "settings" && <SettingsPanel />}
      {panel === "memory" && <MemoryPanel />}
    </div>
  );
}
