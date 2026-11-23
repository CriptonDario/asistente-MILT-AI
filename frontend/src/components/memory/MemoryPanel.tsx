import { Brain, Check, Pencil, Plus, RefreshCw, Search, Trash, X } from "lucide-react";
import { type FormEvent, useState } from "react";
import {
  invalidateMemory,
  useMemories,
  useMemoryStats,
  useMemorySuggestions,
  useSettings,
  useUpdateSettings,
} from "../../hooks/queries";
import { cn } from "../../lib/cn";
import { memoriesApi } from "../../services/endpoints";
import { errorMessage } from "../../services/http";
import { useUi } from "../../stores/ui";
import type { Memory, MemoryKind } from "../../types/api";
import { Button, IconButton } from "../ui/Button";
import { ConfirmDialog } from "../ui/Modal";
import { Spinner } from "../ui/Spinner";
import { PanelSection, SidePanel } from "../layout/SidePanel";

export const KIND_LABEL: Record<MemoryKind, string> = {
  fact: "Dato",
  preference: "Preferencia",
  project: "Proyecto",
  instruction: "Instrucción",
};
const KIND_STYLE: Record<MemoryKind, string> = {
  fact: "bg-primary/10 text-primary",
  preference: "bg-accent/12 text-accent",
  project: "bg-cyan/12 text-cyan",
  instruction: "bg-warn/12 text-warn",
};

const field =
  "w-full rounded-lg border border-border bg-surface-2 px-2.5 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/40";

function KindBadge({ kind }: { kind: MemoryKind }) {
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", KIND_STYLE[kind])}>
      {KIND_LABEL[kind]}
    </span>
  );
}

function NewMemoryForm() {
  const [content, setContent] = useState("");
  const [kind, setKind] = useState<MemoryKind>("fact");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (content.trim().length < 2) return;
    setSaving(true);
    try {
      await memoriesApi.create({ content: content.trim(), kind });
      setContent("");
      setError(null);
      invalidateMemory();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-2 rounded-xl border border-border p-3">
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        maxLength={1000}
        rows={2}
        placeholder="Ej.: Trabajo con Laravel y MySQL en mis proyectos"
        aria-label="Nuevo recuerdo"
        className={cn(field, "resize-none")}
      />
      <div className="flex items-center gap-2">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as MemoryKind)}
          aria-label="Tipo de recuerdo"
          className={cn(field, "h-8 w-auto py-0")}
        >
          {(Object.keys(KIND_LABEL) as MemoryKind[]).map((k) => (
            <option key={k} value={k}>
              {KIND_LABEL[k]}
            </option>
          ))}
        </select>
        <Button
          type="submit"
          size="sm"
          variant="primary"
          icon={<Plus className="size-3.5" />}
          disabled={saving || content.trim().length < 2}
          className="ml-auto"
        >
          Recordar
        </Button>
      </div>
      {error && <p className="text-xs text-danger">{error}</p>}
    </form>
  );
}

function MemoryRow({ memory }: { memory: Memory }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(memory.content);
  const [confirm, setConfirm] = useState(false);

  const save = async () => {
    setEditing(false);
    if (draft.trim() && draft.trim() !== memory.content) {
      await memoriesApi.update(memory.id, { content: draft.trim() });
      invalidateMemory();
    }
  };

  return (
    <li className="group rounded-xl border border-border p-3">
      <div className="mb-1.5 flex items-center gap-2">
        <KindBadge kind={memory.kind} />
        {!memory.indexed && (
          <span className="text-[10px] text-warn" title="Se indexará cuando Ollama esté disponible">
            sin indexar
          </span>
        )}
        <div className="ml-auto flex gap-0.5 opacity-60 group-hover:opacity-100">
          <IconButton label="Editar recuerdo" className="size-7" onClick={() => setEditing(true)}>
            <Pencil className="size-3.5" />
          </IconButton>
          <IconButton label="Eliminar recuerdo" className="size-7" onClick={() => setConfirm(true)}>
            <Trash className="size-3.5" />
          </IconButton>
        </div>
      </div>
      {editing ? (
        <textarea
          autoFocus
          value={draft}
          rows={2}
          maxLength={1000}
          aria-label="Editar recuerdo"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void save()}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void save();
            }
            if (e.key === "Escape") {
              setDraft(memory.content);
              setEditing(false);
            }
          }}
          className={cn(field, "resize-none")}
        />
      ) : (
        <p className="text-sm">{memory.content}</p>
      )}
      {confirm && (
        <ConfirmDialog
          title="Olvidar recuerdo"
          message={`MILT dejará de recordar: «${memory.content}»`}
          confirmLabel="Olvidar"
          danger
          onCancel={() => setConfirm(false)}
          onConfirm={async () => {
            setConfirm(false);
            await memoriesApi.remove(memory.id);
            invalidateMemory();
          }}
        />
      )}
    </li>
  );
}

function SuggestionRow({ memory }: { memory: Memory }) {
  const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      invalidateMemory();
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className="rounded-xl border border-dashed border-accent/40 p-3">
      <div className="mb-1.5">
        <KindBadge kind={memory.kind} />
      </div>
      <p className="text-sm">{memory.content}</p>
      <div className="mt-2 flex gap-2">
        <Button
          size="sm"
          variant="primary"
          icon={<Check className="size-3.5" />}
          disabled={busy}
          onClick={() => void act(() => memoriesApi.accept(memory.id))}
        >
          Recordar
        </Button>
        <Button
          size="sm"
          variant="ghost"
          icon={<X className="size-3.5" />}
          disabled={busy}
          onClick={() => void act(() => memoriesApi.reject(memory.id))}
        >
          Descartar
        </Button>
      </div>
    </li>
  );
}

export function MemoryPanel() {
  const openPanel = useUi((s) => s.openPanel);
  const tab = useUi((s) => s.memoryTab);
  const [search, setSearch] = useState("");
  const [confirmAll, setConfirmAll] = useState(false);
  const memories = useMemories(search.trim());
  const suggestions = useMemorySuggestions();
  const stats = useMemoryStats();
  const settings = useSettings();
  const updateSettings = useUpdateSettings();
  const enabled = settings.data?.memory_enabled ?? true;
  const pending = suggestions.data?.length ?? 0;

  return (
    <SidePanel
      title="Memoria"
      icon={<Brain className="size-4 text-accent" />}
      onClose={() => openPanel(null)}
    >
      <label className="mb-4 flex items-start gap-3 rounded-xl border border-border p-3 text-sm">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => updateSettings.mutate({ memory_enabled: e.target.checked })}
          className="mt-1 accent-[var(--primary)]"
        />
        <span>
          Usar la memoria en las respuestas
          <span className="block text-xs text-muted">
            MILT consulta tus recuerdos aprobados cuando son relevantes. Todo se guarda en tu
            equipo.
          </span>
        </span>
      </label>

      <div className="mb-4 grid grid-cols-2 gap-1 rounded-lg bg-surface-2 p-1" role="tablist">
        {(["memories", "suggestions"] as const).map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={tab === value}
            onClick={() => openPanel("memory", value)}
            className={cn(
              "rounded-md py-1.5 text-sm transition",
              tab === value ? "bg-surface text-text shadow-sm" : "text-muted hover:text-text",
            )}
          >
            {value === "memories" ? `Recuerdos (${stats.data?.active ?? 0})` : `Sugerencias (${pending})`}
          </button>
        ))}
      </div>

      {tab === "memories" ? (
        <>
          <PanelSection title="Añadir">
            <NewMemoryForm />
          </PanelSection>
          <PanelSection title="Lo que MILT recuerda">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar en la memoria"
                aria-label="Buscar en la memoria"
                className={cn(field, "pl-8")}
              />
            </label>
            {stats.data && stats.data.unindexed > 0 && (
              <div className="flex items-center gap-2 rounded-lg bg-warn/10 px-3 py-2 text-xs text-warn">
                {stats.data.unindexed} recuerdo(s) sin indexar.
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto"
                  icon={<RefreshCw className="size-3.5" />}
                  onClick={async () => {
                    await memoriesApi.reindex();
                    invalidateMemory();
                  }}
                >
                  Indexar
                </Button>
              </div>
            )}
            {memories.isLoading && <Spinner />}
            {memories.data?.length === 0 && (
              <p className="text-sm text-muted">
                {search ? "Sin resultados." : "Aún no hay recuerdos. Añade uno o pide sugerencias desde una conversación."}
              </p>
            )}
            <ul className="space-y-2">
              {memories.data?.map((m) => <MemoryRow key={m.id} memory={m} />)}
            </ul>
            {(stats.data?.active ?? 0) > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="text-danger hover:text-danger"
                icon={<Trash className="size-3.5" />}
                onClick={() => setConfirmAll(true)}
              >
                Borrar toda la memoria
              </Button>
            )}
          </PanelSection>
        </>
      ) : (
        <PanelSection title="Propuestas por MILT">
          <p className="text-xs text-muted">
            Pulsa ✨ en la cabecera de una conversación para que MILT proponga qué recordar.
            Nada se guarda sin tu aprobación.
          </p>
          {suggestions.isLoading && <Spinner />}
          {pending === 0 && !suggestions.isLoading && (
            <p className="text-sm text-muted">No hay sugerencias pendientes.</p>
          )}
          <ul className="space-y-2">
            {suggestions.data?.map((m) => <SuggestionRow key={m.id} memory={m} />)}
          </ul>
        </PanelSection>
      )}

      {confirmAll && (
        <ConfirmDialog
          title="Borrar toda la memoria"
          message="MILT olvidará todos tus recuerdos y sugerencias. Esta acción no se puede deshacer."
          confirmLabel="Borrar todo"
          danger
          onCancel={() => setConfirmAll(false)}
          onConfirm={async () => {
            setConfirmAll(false);
            await memoriesApi.removeAll();
            invalidateMemory();
          }}
        />
      )}
    </SidePanel>
  );
}
