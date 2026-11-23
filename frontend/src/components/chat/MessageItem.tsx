import { Check, Copy, RotateCcw, Trash } from "lucide-react";
import { useState } from "react";
import { formatDuration } from "../../lib/format";
import type { Attachment, Message, ToolCallLog } from "../../types/api";
import { AttachmentChips, Sources } from "./Sources";
import { SpeakButton } from "./SpeakButton";
import { ToolCalls } from "./ToolCalls";
import { IconButton } from "../ui/Button";
import { Logo } from "../ui/Logo";
import { Markdown } from "./Markdown";

interface MessageItemProps {
  message: Message;
  isLast: boolean;
  busy: boolean;
  onRegenerate: () => void;
  onDelete: () => void;
}

export function UserBubble({
  content,
  attachments = [],
}: {
  content: string;
  attachments?: Attachment[];
}) {
  return (
    <div className="flex flex-col items-end">
      <AttachmentChips attachments={attachments} />
      <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-surface-2 px-4 py-2.5 text-[15px] leading-relaxed">
        {content}
      </div>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <IconButton
      label={copied ? "Copiado" : "Copiar respuesta"}
      className="size-7"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          // Portapapeles no disponible.
        }
      }}
    >
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
    </IconButton>
  );
}

export function AssistantShell({
  children,
  active = false,
}: {
  children: React.ReactNode;
  active?: boolean;
}) {
  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-border bg-surface">
        <Logo size={20} active={active} />
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

export function MessageItem({ message, isLast, busy, onRegenerate, onDelete }: MessageItemProps) {
  if (message.role === "user") {
    return <UserBubble content={message.content} attachments={message.attachments ?? []} />;
  }

  const meta = [
    message.model,
    formatDuration(message.latency_ms),
    message.completion_tokens ? `${message.completion_tokens} tokens` : null,
  ].filter(Boolean);

  return (
    <AssistantShell>
      {message.status !== "complete" && (
        <div
          className={
            message.status === "error"
              ? "mb-2 inline-block rounded-md bg-danger/10 px-2 py-0.5 text-xs text-danger"
              : "mb-2 inline-block rounded-md bg-warn/10 px-2 py-0.5 text-xs text-warn"
          }
        >
          {message.status === "error" ? "Respuesta incompleta por un error" : "Respuesta interrumpida"}
        </div>
      )}
      <ToolCalls tools={(message.tool_calls ?? []) as unknown as ToolCallLog[]} />
      <Markdown text={message.content} />
      <Sources sources={message.context_sources ?? []} />
      <div className="group mt-1 flex items-center gap-1 text-xs text-muted">
        <CopyButton text={message.content} />
        <SpeakButton text={message.content} />
        {isLast && (
          <IconButton
            label="Regenerar respuesta"
            className="size-7"
            onClick={onRegenerate}
            disabled={busy}
          >
            <RotateCcw className="size-3.5" />
          </IconButton>
        )}
        <IconButton label="Eliminar mensaje" className="size-7" onClick={onDelete} disabled={busy}>
          <Trash className="size-3.5" />
        </IconButton>
        {meta.length > 0 && <span className="ml-1 truncate">{meta.join(" · ")}</span>}
      </div>
    </AssistantShell>
  );
}
