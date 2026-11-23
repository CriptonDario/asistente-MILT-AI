import { Globe, Laptop, Monitor, Moon, PanelLeft, Sparkles, Sun } from "lucide-react";
import { useExtractMemories, useSystemInfo, useUpdateSettings } from "../../hooks/queries";
import { errorMessage } from "../../services/http";
import { cn } from "../../lib/cn";
import { useSession } from "../../stores/session";
import { useUi } from "../../stores/ui";
import type { Theme } from "../../types/api";
import { useState } from "react";
import { ModelSelector } from "../chat/ModelSelector";
import { IconButton } from "../ui/Button";

const NEXT_THEME: Record<Theme, Theme> = { dark: "light", light: "system", system: "dark" };
const THEME_LABEL: Record<Theme, string> = {
  dark: "Tema oscuro",
  light: "Tema claro",
  system: "Tema del sistema",
};

/** Insignia LOCAL (cian) / WEB (violeta) y estado del motor de IA. */
function NodeStatus() {
  const info = useSystemInfo();
  const profile = info.data?.profile ?? "local";
  const engineOk = info.data?.llm.ok ?? false;
  const reachable = !info.isError;

  let engineLabel = "Comprobando el motor de IA…";
  if (!reachable) engineLabel = "Sin conexión con el servidor de MILT";
  else if (info.data) {
    engineLabel = engineOk
      ? `Motor ${info.data.llm_provider} activo${info.data.llm.version ? ` (v${info.data.llm.version})` : ""}`
      : "Motor de IA detenido: abre Ollama";
  }

  return (
    <div className="flex items-center gap-2">
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold tracking-wider",
          profile === "local" ? "bg-cyan/12 text-cyan" : "bg-accent/15 text-accent",
        )}
        title={profile === "local" ? "Funcionando en este equipo" : "Conectado al servidor web"}
      >
        {profile === "local" ? <Laptop className="size-3" /> : <Globe className="size-3" />}
        {profile === "local" ? "LOCAL" : "WEB"}
      </span>
      <span className="relative flex size-2.5" role="status" aria-label={engineLabel} title={engineLabel}>
        {reachable && engineOk && (
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-ok opacity-40" />
        )}
        <span
          className={cn(
            "relative inline-flex size-2.5 rounded-full",
            !info.data && reachable ? "bg-muted" : reachable && engineOk ? "bg-ok" : "bg-danger",
          )}
        />
      </span>
    </div>
  );
}

function SuggestMemoriesButton({ conversationId }: { conversationId: string }) {
  const extract = useExtractMemories();
  const openPanel = useUi((s) => s.openPanel);
  const [note, setNote] = useState<string | null>(null);

  const run = () => {
    setNote(null);
    extract.mutate(conversationId, {
      onSuccess: (result) => {
        if (result.created.length > 0) openPanel("memory", "suggestions");
        else setNote("No hay nada nuevo que recordar en esta conversación.");
      },
      onError: (error) => setNote(errorMessage(error)),
    });
  };

  return (
    <div className="relative">
      <IconButton
        label={extract.isPending ? "Analizando la conversación…" : "Sugerir recuerdos de esta conversación"}
        onClick={run}
        disabled={extract.isPending}
      >
        <Sparkles className={cn("size-4", extract.isPending && "animate-pulse text-accent")} />
      </IconButton>
      {note && (
        <button
          type="button"
          onClick={() => setNote(null)}
          className="absolute right-0 top-11 z-30 w-64 rounded-lg border border-border bg-surface p-3 text-left text-xs text-muted shadow-panel"
        >
          {note}
        </button>
      )}
    </div>
  );
}

interface HeaderProps {
  conversationId?: string;
  title: string;
  model: string | null;
  defaultModel: string | undefined;
  onModelChange: (model: string) => void;
}

export function Header({ conversationId, title, model, defaultModel, onModelChange }: HeaderProps) {
  const sidebarOpen = useUi((s) => s.sidebarOpen);
  const toggleSidebar = useUi((s) => s.toggleSidebar);
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  const authenticated = useSession((s) => s.status === "authenticated");
  const updateSettings = useUpdateSettings();

  const cycleTheme = () => {
    const next = NEXT_THEME[theme];
    setTheme(next);
    if (authenticated) updateSettings.mutate({ theme: next });
  };
  const ThemeIcon = theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;

  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-3">
      {!sidebarOpen && (
        <IconButton label="Mostrar barra lateral" onClick={toggleSidebar}>
          <PanelLeft className="size-4" />
        </IconButton>
      )}
      <ModelSelector value={model} fallback={defaultModel} onChange={onModelChange} />
      <h1 className="hidden min-w-0 flex-1 truncate text-center text-sm text-muted lg:block">
        {title}
      </h1>
      <div className="ml-auto flex items-center gap-1">
        <NodeStatus />
        {conversationId && <SuggestMemoriesButton conversationId={conversationId} />}
        <IconButton label={`${THEME_LABEL[theme]} (cambiar)`} onClick={cycleTheme}>
          <ThemeIcon className="size-4" />
        </IconButton>
      </div>
    </header>
  );
}
