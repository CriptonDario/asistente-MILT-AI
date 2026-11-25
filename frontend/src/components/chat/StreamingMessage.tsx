import { CircleExclamationPoint, RotateCcw, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { StreamState } from "../../stores/chat";
import { Button } from "../ui/Button";
import { AssistantShell } from "./MessageItem";
import { Markdown } from "./Markdown";
import { Sources } from "./Sources";
import { ToolCalls } from "./ToolCalls";

const ERROR_HINTS: Record<string, string> = {
  provider_unavailable: "El motor local (Ollama) no responde. Comprueba que está abierto.",
  model_not_found: "Ese modelo no está instalado en Ollama.",
  validation_error: "La solicitud no es válida.",
  insufficient_memory: "No hay memoria RAM suficiente para cargar el modelo.",
  context_overflow: "El mensaje es demasiado largo para el contexto del modelo.",
  connection_lost: "Se perdió la conexión con el servidor de MILT.",
  connection_failed: "No se pudo conectar con el servidor de MILT.",
  busy: "Ya hay una respuesta en curso.",
};

/** Indicador de espera: en CPU la carga en frío del modelo puede tardar decenas de segundos. */
function Waiting({ since }: { since: number }) {
  const [elapsed, setElapsed] = useState(() => Date.now() - since);
  useEffect(() => {
    const timer = setInterval(() => setElapsed(Date.now() - since), 1000);
    return () => clearInterval(timer);
  }, [since]);
  const seconds = Math.floor(elapsed / 1000);
  return (
    <p className="text-sm text-muted" aria-live="polite">
      {seconds < 6 ? "Pensando…" : `Cargando el modelo en memoria… ${seconds} s`}
    </p>
  );
}

interface StreamingMessageProps {
  stream: StreamState;
  onRetry: () => void;
  onConfirmTool?: (callId: string, approved: boolean) => void;
  onDismiss: () => void;
}

export function StreamingMessage({
  stream,
  onRetry,
  onDismiss,
  onConfirmTool,
}: StreamingMessageProps) {
  const active = stream.status === "pending" || stream.status === "streaming";

  if (stream.status === "error") {
    return (
      <AssistantShell>
        <ToolCalls tools={stream.tools} />
        {stream.text && <Markdown text={stream.text} />}
        <div
          role="alert"
          className="mt-2 flex flex-col gap-3 rounded-xl border border-danger/30 bg-danger/5 p-3 text-sm sm:flex-row sm:items-center"
        >
          <CircleExclamationPoint className="size-5 shrink-0 text-danger" />
          <div className="min-w-0 flex-1">
            <p className="font-medium text-text">{ERROR_HINTS[stream.error?.code ?? ""] ?? "No se pudo generar la respuesta."}</p>
            {stream.error?.detail && <p className="mt-0.5 text-muted">{stream.error.detail}</p>}
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="secondary" icon={<RotateCcw className="size-3.5" />} onClick={onRetry}>
              Reintentar
            </Button>
            <Button size="sm" variant="ghost" icon={<X className="size-3.5" />} onClick={onDismiss}>
              Cerrar
            </Button>
          </div>
        </div>
      </AssistantShell>
    );
  }

  return (
    <AssistantShell active={active}>
      <ToolCalls tools={stream.tools} onConfirm={onConfirmTool} />
      {stream.text ? (
        <div className="relative">
          <Markdown text={stream.text} />
          {active && <span className="stream-cursor" aria-hidden="true" />}
        </div>
      ) : (
        active &&
        !stream.tools.some((t) => t.status === "awaiting") && <Waiting since={stream.startedAt} />
      )}
      <Sources sources={stream.sources} warnings={stream.warnings} />
    </AssistantShell>
  );
}
