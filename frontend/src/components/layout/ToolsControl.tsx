import { Wrench } from "lucide-react";
import { useConversation, useUpdateConversation } from "../../hooks/queries";
import { cn } from "../../lib/cn";
import type { AgentProfile } from "../../types/api";

export const PROFILE_LABELS: Record<AgentProfile, string> = {
  general: "General",
  coder: "Programación",
  security: "Seguridad",
  documents: "Documentos",
};

/** Activa las herramientas de la conversación y elige el perfil del agente. */
export function ToolsControl({ conversationId }: { conversationId: string }) {
  const conversation = useConversation(conversationId);
  const update = useUpdateConversation();
  const conv = conversation.data;
  if (!conv) return null;
  const enabled = conv.tools_enabled;

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => update.mutate({ id: conv.id, body: { tools_enabled: !enabled } })}
        aria-pressed={enabled}
        title={
          enabled
            ? "Herramientas activadas: MILT puede leer tus carpetas autorizadas y pedir permiso para actuar"
            : "Activar herramientas en esta conversación"
        }
        className={cn(
          "inline-flex h-9 items-center gap-1.5 rounded-lg px-2.5 text-sm transition",
          enabled ? "bg-primary/12 text-primary" : "text-muted hover:bg-surface-2 hover:text-text",
        )}
      >
        <Wrench className="size-4" />
        <span className="hidden sm:inline">{enabled ? "Herramientas" : "Sin herramientas"}</span>
      </button>
      <select
        value={conv.agent_profile}
        onChange={(e) =>
          update.mutate({ id: conv.id, body: { agent_profile: e.target.value as AgentProfile } })
        }
        aria-label="Perfil del agente"
        title="Perfil del agente: define el enfoque y qué herramientas se ofrecen"
        className="h-9 rounded-lg bg-transparent px-1.5 text-sm text-muted outline-none hover:bg-surface-2 focus:ring-2 focus:ring-primary/40"
      >
        {(Object.keys(PROFILE_LABELS) as AgentProfile[]).map((profile) => (
          <option key={profile} value={profile}>
            {PROFILE_LABELS[profile]}
          </option>
        ))}
      </select>
    </div>
  );
}
