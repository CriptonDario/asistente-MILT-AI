import { ArrowUp, FileText, FileUp, Mic, Paperclip, Square, X } from "lucide-react";
import {
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useClickOutside } from "../../hooks/useClickOutside";
import { cn } from "../../lib/cn";
import type { DocumentInfo } from "../../types/api";
import { IconButton } from "../ui/Button";
import { Spinner } from "../ui/Spinner";

export const MAX_INPUT_CHARS = 32_000;
export const MAX_ATTACHMENTS = 10;
export const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md"];
export const MAX_UPLOAD_MB = 25;

/** Validación previa en el cliente (el servidor vuelve a validar por contenido). */
export function validateUpload(file: File): string | null {
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!ACCEPTED_EXTENSIONS.includes(ext)) {
    return `Formato no soportado. Usa ${ACCEPTED_EXTENSIONS.join(", ")}.`;
  }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `El archivo supera ${MAX_UPLOAD_MB} MB.`;
  if (file.size === 0) return "El archivo está vacío.";
  return null;
}

interface ComposerProps {
  onSend: (text: string, attachmentIds: string[]) => void;
  onStop: () => void;
  streaming: boolean;
  disabled?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
  /** Documentos del usuario (para elegir adjuntos y conocer su estado). */
  documents?: DocumentInfo[];
  /** Sube un archivo y devuelve el documento creado. Si falta, no se ofrece subir. */
  onUpload?: (file: File) => Promise<DocumentInfo>;
}

function AttachmentChip({ doc, onRemove }: { doc: DocumentInfo | undefined; onRemove: () => void }) {
  const processing = !doc || doc.status === "pending" || doc.status === "processing";
  const failed = doc?.status === "failed";
  return (
    <span
      className={cn(
        "inline-flex max-w-[14rem] items-center gap-1 rounded-lg border px-2 py-1 text-xs",
        failed ? "border-danger/40 text-danger" : "border-border bg-surface-2 text-muted",
      )}
      title={failed ? (doc?.error ?? "Error al procesar") : doc?.filename}
    >
      {processing ? <Spinner className="size-3" label="Procesando" /> : <FileText className="size-3 shrink-0 text-primary" />}
      <span className="truncate">{doc?.filename ?? "Subiendo…"}</span>
      {processing && <span className="shrink-0">procesando</span>}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Quitar ${doc?.filename ?? "adjunto"}`}
        className="ml-0.5 rounded hover:text-text"
      >
        <X className="size-3" />
      </button>
    </span>
  );
}

export function Composer({
  onSend,
  onStop,
  streaming,
  disabled = false,
  placeholder = "Escribe a MILT…",
  autoFocus = true,
  documents = [],
  onUpload,
}: ComposerProps) {
  const [text, setText] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(0);
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const pickerRef = useRef<HTMLDivElement>(null);
  const closePicker = useCallback(() => setPickerOpen(false), []);
  useClickOutside(pickerRef, closePicker, pickerOpen);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [text]);

  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);

  const byId = new Map(documents.map((d) => [d.id, d]));
  const selectedDocs = selected.map((id) => byId.get(id));
  const attachmentsReady = selectedDocs.every((d) => d?.status === "ready") && uploading === 0;
  const readyDocs = documents.filter((d) => d.status === "ready");

  const trimmed = text.trim();
  const tooLong = text.length > MAX_INPUT_CHARS;
  const canSend = trimmed.length > 0 && !tooLong && !streaming && !disabled && attachmentsReady;

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!canSend) return;
    onSend(trimmed, selected);
    setText("");
    setSelected([]);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  const toggle = (id: string) =>
    setSelected((current) =>
      current.includes(id)
        ? current.filter((x) => x !== id)
        : current.length < MAX_ATTACHMENTS
          ? [...current, id]
          : current,
    );

  const onFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    setPickerOpen(false);
    if (!onUpload) return;
    for (const file of files) {
      const problem = validateUpload(file);
      if (problem) {
        setUploadError(`${file.name}: ${problem}`);
        continue;
      }
      setUploading((n) => n + 1);
      try {
        const doc = await onUpload(file);
        setUploadError(null);
        setSelected((current) =>
          current.includes(doc.id) || current.length >= MAX_ATTACHMENTS ? current : [...current, doc.id],
        );
      } catch (error) {
        setUploadError(`${file.name}: ${error instanceof Error ? error.message : "no se pudo subir"}`);
      } finally {
        setUploading((n) => n - 1);
      }
    }
  };

  return (
    <form
      onSubmit={submit}
      className="focus-glow mx-auto w-full max-w-3xl rounded-2xl border border-border bg-surface p-2 shadow-panel transition"
    >
      {(selected.length > 0 || uploading > 0) && (
        <div className="flex flex-wrap gap-1.5 px-1 pb-1.5" aria-label="Adjuntos">
          {selected.map((id) => (
            <AttachmentChip key={id} doc={byId.get(id)} onRemove={() => toggle(id)} />
          ))}
          {uploading > 0 && <AttachmentChip doc={undefined} onRemove={() => undefined} />}
        </div>
      )}
      <textarea
        ref={ref}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
        rows={1}
        placeholder={placeholder}
        aria-label="Mensaje"
        disabled={disabled}
        className="block max-h-56 w-full resize-none bg-transparent px-2 py-2 text-[15px] outline-none placeholder:text-muted disabled:opacity-60"
      />
      {uploadError && (
        <p role="alert" className="px-2 pb-1 text-xs text-danger">
          {uploadError}
        </p>
      )}
      <div className="flex items-center gap-1 pt-1">
        <div className="relative" ref={pickerRef}>
          <IconButton
            label="Adjuntar documentos"
            onClick={() => setPickerOpen((o) => !o)}
            active={pickerOpen}
            disabled={disabled}
          >
            <Paperclip className="size-4" />
          </IconButton>
          {pickerOpen && (
            <div className="absolute bottom-11 left-0 z-30 w-72 max-w-[85vw] rounded-xl border border-border bg-surface p-1.5 shadow-panel">
              {onUpload && (
                <button
                  type="button"
                  onClick={() => fileInput.current?.click()}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-2"
                >
                  <FileUp className="size-4 text-primary" />
                  Subir archivo…
                  <span className="ml-auto text-[11px] text-muted">máx. {MAX_UPLOAD_MB} MB</span>
                </button>
              )}
              {readyDocs.length > 0 && (
                <p className="px-3 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wider text-muted">
                  Tus documentos
                </p>
              )}
              <div className="max-h-56 overflow-y-auto">
                {readyDocs.map((doc) => (
                  <label
                    key={doc.id}
                    className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-sm hover:bg-surface-2"
                  >
                    <input
                      type="checkbox"
                      checked={selected.includes(doc.id)}
                      onChange={() => toggle(doc.id)}
                      className="accent-[var(--primary)]"
                    />
                    <span className="truncate">{doc.filename}</span>
                  </label>
                ))}
              </div>
              {readyDocs.length === 0 && !onUpload && (
                <p className="p-3 text-sm text-muted">No hay documentos listos.</p>
              )}
            </div>
          )}
          <input
            ref={fileInput}
            type="file"
            multiple
            accept={ACCEPTED_EXTENSIONS.join(",")}
            className="hidden"
            onChange={(event) => void onFiles(event)}
            data-testid="file-input"
          />
        </div>
        <IconButton label="Hablar (disponible en la Fase 5)" disabled>
          <Mic className="size-4" />
        </IconButton>
        <span
          className={cn(
            "ml-auto px-2 text-xs tabular-nums",
            tooLong ? "text-danger" : "text-muted",
            text.length < MAX_INPUT_CHARS * 0.8 && "invisible",
          )}
        >
          {text.length.toLocaleString("es")} / {MAX_INPUT_CHARS.toLocaleString("es")}
        </span>
        {streaming ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Detener respuesta"
            title="Detener respuesta"
            className="inline-flex size-9 items-center justify-center rounded-xl bg-surface-3 text-text transition hover:bg-danger hover:text-white"
          >
            <Square className="size-3.5 fill-current" />
          </button>
        ) : (
          <button
            type="submit"
            disabled={!canSend}
            aria-label="Enviar mensaje"
            title={attachmentsReady ? "Enviar (Enter)" : "Esperando a que terminen de procesarse los adjuntos"}
            className="brand-gradient inline-flex size-9 items-center justify-center rounded-xl text-white transition hover:brightness-110 disabled:opacity-30 disabled:grayscale"
          >
            <ArrowUp className="size-4" />
          </button>
        )}
      </div>
    </form>
  );
}
