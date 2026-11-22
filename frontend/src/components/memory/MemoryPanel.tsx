import { Brain, FileText, Sparkles } from "lucide-react";
import { useUi } from "../../stores/ui";
import { PanelSection, SidePanel } from "../layout/SidePanel";

/** La memoria persistente llega en la Fase 4; el panel explica qué hará. */
export function MemoryPanel() {
  const openPanel = useUi((s) => s.openPanel);
  return (
    <SidePanel title="Memoria" icon={<Brain className="size-4 text-accent" />} onClose={() => openPanel(null)}>
      <div className="rounded-xl border border-dashed border-border p-4 text-sm">
        <p className="font-medium">Disponible en la Fase 4</p>
        <p className="mt-1 text-muted">
          Por ahora MILT recuerda el historial de cada conversación, pero no comparte
          información entre conversaciones.
        </p>
      </div>
      <PanelSection title="Qué incluirá">
        <ul className="space-y-3 text-sm text-muted">
          <li className="flex gap-2">
            <Sparkles className="mt-0.5 size-4 shrink-0 text-cyan" />
            Recuerdos sobre ti y tus proyectos, propuestos por MILT y aprobados por ti.
          </li>
          <li className="flex gap-2">
            <Brain className="mt-0.5 size-4 shrink-0 text-accent" />
            Búsqueda semántica en todo tu historial, en tu equipo.
          </li>
          <li className="flex gap-2">
            <FileText className="mt-0.5 size-4 shrink-0 text-primary" />
            Documentos (PDF, DOCX, XLSX, CSV, TXT) con respuestas que citan la fuente.
          </li>
        </ul>
      </PanelSection>
    </SidePanel>
  );
}
