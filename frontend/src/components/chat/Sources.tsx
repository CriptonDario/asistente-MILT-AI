import { Brain, FileText, TriangleExclamationPoint } from "lucide-react";
import type { Attachment, ContextSource } from "../../types/api";

/** Fuentes en las que se basó la respuesta: fragmentos de documentos y recuerdos. */
export function Sources({ sources, warnings = [] }: { sources: ContextSource[]; warnings?: string[] }) {
  if (sources.length === 0 && warnings.length === 0) return null;
  const documents = sources.filter((s) => s.kind === "document");
  const memories = sources.filter((s) => s.kind === "memory");

  return (
    <div className="mt-2 space-y-1.5" aria-label="Fuentes de la respuesta">
      {(documents.length > 0 || memories.length > 0) && (
        <div className="flex flex-wrap gap-1.5">
          {documents.map((source) => (
            <span
              key={source.id}
              title={`${source.title}${source.location ? ` · ${source.location}` : ""}`}
              className="inline-flex max-w-full items-center gap-1 rounded-md border border-border bg-surface px-2 py-0.5 text-xs text-muted"
            >
              <FileText className="size-3 shrink-0 text-primary" />
              {source.ref != null && <span className="font-mono text-text">[{source.ref}]</span>}
              <span className="truncate">{source.title}</span>
              {source.location && <span className="shrink-0 text-muted/80">· {source.location}</span>}
            </span>
          ))}
          {memories.map((source) => (
            <span
              key={source.id}
              title={source.title}
              className="inline-flex max-w-[16rem] items-center gap-1 rounded-md border border-border bg-surface px-2 py-0.5 text-xs text-muted"
            >
              <Brain className="size-3 shrink-0 text-accent" />
              <span className="truncate">{source.title}</span>
            </span>
          ))}
        </div>
      )}
      {warnings.map((warning) => (
        <p key={warning} className="flex items-start gap-1 text-xs text-warn">
          <TriangleExclamationPoint className="mt-0.5 size-3 shrink-0" />
          {warning}
        </p>
      ))}
    </div>
  );
}

export function AttachmentChips({ attachments }: { attachments: Attachment[] }) {
  if (attachments.length === 0) return null;
  return (
    <div className="mb-1.5 flex flex-wrap justify-end gap-1.5">
      {attachments.map((a) => (
        <span
          key={a.document_id}
          className="inline-flex max-w-[16rem] items-center gap-1 rounded-md border border-border bg-surface px-2 py-0.5 text-xs text-muted"
        >
          <FileText className="size-3 shrink-0 text-primary" />
          <span className="truncate">{a.filename}</span>
        </span>
      ))}
    </div>
  );
}
