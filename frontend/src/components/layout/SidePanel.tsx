import { X } from "lucide-react";
import { type ReactNode, useEffect } from "react";
import { IconButton } from "../ui/Button";

interface SidePanelProps {
  title: string;
  icon: ReactNode;
  onClose: () => void;
  children: ReactNode;
}

/** Panel deslizante a la derecha (configuración, memoria). */
export function SidePanel({ title, icon, onClose, children }: SidePanelProps) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative flex h-full w-full max-w-md flex-col border-l border-border bg-surface shadow-panel"
      >
        <div className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-4">
          {icon}
          <h2 className="text-base font-semibold">{title}</h2>
          <IconButton label="Cerrar panel" className="ml-auto" onClick={onClose}>
            <X className="size-4" />
          </IconButton>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
      </aside>
    </div>
  );
}

export function PanelSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-6">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
      <div className="space-y-3">{children}</div>
    </section>
  );
}
