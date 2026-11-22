import { Download, FileText, FileUp, RefreshCw, Trash } from "lucide-react";
import { type DragEvent, useRef, useState } from "react";
import {
  useDeleteDocument,
  useDocuments,
  useReindexDocument,
  useUploadDocument,
} from "../../hooks/queries";
import { cn } from "../../lib/cn";
import { formatBytes, timeAgo } from "../../lib/format";
import { documentsApi } from "../../services/endpoints";
import { errorMessage } from "../../services/http";
import { useUi } from "../../stores/ui";
import type { DocumentInfo } from "../../types/api";
import { ACCEPTED_EXTENSIONS, MAX_UPLOAD_MB, validateUpload } from "../chat/Composer";
import { IconButton } from "../ui/Button";
import { ConfirmDialog } from "../ui/Modal";
import { Spinner } from "../ui/Spinner";
import { PanelSection, SidePanel } from "../layout/SidePanel";

const STATUS: Record<DocumentInfo["status"], { label: string; className: string }> = {
  pending: { label: "En cola", className: "text-muted" },
  processing: { label: "Procesando", className: "text-cyan" },
  ready: { label: "Listo", className: "text-ok" },
  failed: { label: "Error", className: "text-danger" },
};

function DocumentRow({ doc }: { doc: DocumentInfo }) {
  const remove = useDeleteDocument();
  const reindex = useReindexDocument();
  const [confirm, setConfirm] = useState(false);
  const status = STATUS[doc.status];
  const busy = doc.status === "pending" || doc.status === "processing";

  return (
    <li className="rounded-xl border border-border p-3">
      <div className="flex items-start gap-3">
        <FileText className="mt-0.5 size-5 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={doc.filename}>
            {doc.filename}
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-muted">
            <span className={cn("inline-flex items-center gap-1 font-medium", status.className)}>
              {busy && <Spinner className="size-3" />}
              {status.label}
            </span>
            · {doc.kind.toUpperCase()} · {formatBytes(doc.size_bytes)}
            {doc.status === "ready" && ` · ${doc.chunk_count} fragmentos`}· {timeAgo(doc.created_at)}
          </p>
          {doc.status === "failed" && doc.error && (
            <p className="mt-1 text-xs text-danger">{doc.error}</p>
          )}
        </div>
        <div className="flex shrink-0 gap-0.5">
          {doc.status === "failed" && (
            <IconButton
              label="Reintentar procesamiento"
              className="size-7"
              onClick={() => reindex.mutate(doc.id)}
            >
              <RefreshCw className="size-3.5" />
            </IconButton>
          )}
          <IconButton
            label="Descargar original"
            className="size-7"
            onClick={() => void documentsApi.download(doc)}
          >
            <Download className="size-3.5" />
          </IconButton>
          <IconButton label="Eliminar documento" className="size-7" onClick={() => setConfirm(true)}>
            <Trash className="size-3.5" />
          </IconButton>
        </div>
      </div>
      {confirm && (
        <ConfirmDialog
          title="Eliminar documento"
          message={`Se eliminará «${doc.filename}» y su índice. Las conversaciones que lo usaban dejarán de consultarlo.`}
          confirmLabel="Eliminar"
          danger
          onCancel={() => setConfirm(false)}
          onConfirm={() => {
            setConfirm(false);
            remove.mutate(doc.id);
          }}
        />
      )}
    </li>
  );
}

export function DocumentsPanel() {
  const openPanel = useUi((s) => s.openPanel);
  const documents = useDocuments();
  const upload = useUploadDocument();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFiles = async (files: File[]) => {
    setError(null);
    for (const file of files) {
      const problem = validateUpload(file);
      if (problem) {
        setError(`${file.name}: ${problem}`);
        continue;
      }
      try {
        await upload.mutateAsync(file);
      } catch (err) {
        setError(`${file.name}: ${errorMessage(err)}`);
      }
    }
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    void handleFiles(Array.from(event.dataTransfer.files));
  };

  return (
    <SidePanel
      title="Documentos"
      icon={<FileText className="size-4 text-primary" />}
      onClose={() => openPanel(null)}
    >
      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          "mb-2 flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-6 text-sm transition",
          dragging ? "border-primary bg-primary/5" : "border-border hover:border-primary/50",
        )}
      >
        {upload.isPending ? <Spinner className="size-6" /> : <FileUp className="size-6 text-primary" />}
        <span className="font-medium">Arrastra archivos o pulsa para subir</span>
        <span className="text-xs text-muted">
          {ACCEPTED_EXTENSIONS.join(" ")} · máx. {MAX_UPLOAD_MB} MB
        </span>
      </button>
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPTED_EXTENSIONS.join(",")}
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = "";
          void handleFiles(files);
        }}
      />
      {error && (
        <p role="alert" className="mb-2 text-sm text-danger">
          {error}
        </p>
      )}
      <p className="mb-4 text-xs text-muted">
        Los documentos se procesan en tu equipo. Adjúntalos a un mensaje con el clip para que
        MILT responda basándose en ellos y cite la fuente.
      </p>

      <PanelSection title="Tus documentos">
        {documents.isLoading && <Spinner />}
        {documents.data?.length === 0 && <p className="text-sm text-muted">Aún no hay documentos.</p>}
        <ul className="space-y-2">
          {documents.data?.map((doc) => <DocumentRow key={doc.id} doc={doc} />)}
        </ul>
      </PanelSection>
    </SidePanel>
  );
}
