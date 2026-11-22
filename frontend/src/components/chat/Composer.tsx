import { ArrowUp, Mic, Paperclip, Square } from "lucide-react";
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { cn } from "../../lib/cn";
import { IconButton } from "../ui/Button";

export const MAX_INPUT_CHARS = 32_000;

interface ComposerProps {
  onSend: (text: string) => void;
  onStop: () => void;
  streaming: boolean;
  disabled?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
}

export function Composer({
  onSend,
  onStop,
  streaming,
  disabled = false,
  placeholder = "Escribe a MILT…",
  autoFocus = true,
}: ComposerProps) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  // Altura automática hasta un máximo.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [text]);

  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);

  const trimmed = text.trim();
  const tooLong = text.length > MAX_INPUT_CHARS;
  const canSend = trimmed.length > 0 && !tooLong && !streaming && !disabled;

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!canSend) return;
    onSend(trimmed);
    setText("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter envía; Shift+Enter, salto de línea. Se respeta la composición IME.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form
      onSubmit={submit}
      className="focus-glow mx-auto w-full max-w-3xl rounded-2xl border border-border bg-surface p-2 shadow-panel transition"
    >
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
      <div className="flex items-center gap-1 pt-1">
        <IconButton label="Adjuntar archivos (disponible en la Fase 4)" disabled>
          <Paperclip className="size-4" />
        </IconButton>
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
            title="Enviar (Enter)"
            className="brand-gradient inline-flex size-9 items-center justify-center rounded-xl text-white transition hover:brightness-110 disabled:opacity-30 disabled:grayscale"
          >
            <ArrowUp className="size-4" />
          </button>
        )}
      </div>
    </form>
  );
}
