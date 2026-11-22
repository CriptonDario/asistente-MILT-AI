import { Check, ChevronDown, Cpu } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { useClickOutside } from "../../hooks/useClickOutside";
import { useModels } from "../../hooks/queries";
import { cn } from "../../lib/cn";
import { formatBytes } from "../../lib/format";

interface ModelSelectorProps {
  value: string | null;
  fallback: string | undefined;
  onChange: (model: string) => void;
}

export function ModelSelector({ value, fallback, onChange }: ModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useClickOutside(ref, close, open);
  const models = useModels();
  const current = value ?? fallback ?? "modelo";

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="inline-flex h-9 max-w-[45vw] items-center gap-2 rounded-lg px-2.5 text-sm hover:bg-surface-2"
      >
        <Cpu className="size-4 shrink-0 text-accent" />
        <span className="truncate font-medium">{current}</span>
        <ChevronDown className="size-4 shrink-0 text-muted" />
      </button>
      {open && (
        <div
          role="listbox"
          aria-label="Modelos disponibles"
          className="absolute left-0 top-11 z-40 w-80 max-w-[90vw] rounded-xl border border-border bg-surface p-1.5 shadow-panel"
        >
          {models.isLoading && <p className="p-3 text-sm text-muted">Cargando modelos…</p>}
          {models.isError && (
            <p className="p-3 text-sm text-danger">
              No se pudo obtener la lista. ¿Está Ollama en ejecución?
            </p>
          )}
          {models.data?.length === 0 && (
            <p className="p-3 text-sm text-muted">
              No hay modelos instalados. Ejecuta <code>ollama pull qwen3:1.7b</code>.
            </p>
          )}
          {models.data?.map((model) => (
            <button
              key={model.name}
              type="button"
              role="option"
              aria-selected={model.name === current}
              onClick={() => {
                onChange(model.name);
                setOpen(false);
              }}
              className={cn(
                "flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left hover:bg-surface-2",
                model.name === current && "bg-surface-2",
              )}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium">{model.name}</span>
                  {model.is_default && (
                    <span className="rounded bg-accent/15 px-1.5 text-[10px] font-medium uppercase text-accent">
                      predeterminado
                    </span>
                  )}
                </div>
                <div className="mt-0.5 text-xs text-muted">
                  {[model.parameter_size, model.quantization, formatBytes(model.size_bytes)]
                    .filter(Boolean)
                    .join(" · ")}
                  {model.capabilities.includes("tools") && " · herramientas"}
                </div>
              </div>
              {model.name === current && <Check className="mt-1 size-4 text-primary" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
