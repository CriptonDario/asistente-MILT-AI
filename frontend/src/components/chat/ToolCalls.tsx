import {
  Check,
  CircleExclamationPoint,
  Clock,
  FileCode,
  FileText,
  FolderOpen,
  Network,
  Search,
  ShieldCheck,
  ShieldX,
  Terminal,
  Wrench,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "../../lib/cn";
import type { ToolCallStatus, ToolCallView } from "../../stores/chat";
import type { ToolCallLog } from "../../types/api";
import { Button } from "../ui/Button";
import { Spinner } from "../ui/Spinner";

export const TOOL_LABELS: Record<string, string> = {
  file_list: "Listar carpeta",
  file_read: "Leer archivo",
  project_tree: "Estructura del proyecto",
  code_search: "Buscar en el código",
  file_write: "Escribir archivo",
  doc_search: "Buscar en tus documentos",
  script_run: "Ejecutar script",
  logs_analyze: "Analizar log",
  ioc_match: "Buscar indicadores de compromiso",
  net_diagnose: "Diagnóstico de red",
  security_report: "Guardar reporte",
};

export const RISK_LABELS: Record<string, { label: string; className: string }> = {
  read: { label: "lectura", className: "bg-ok/10 text-ok" },
  internal: { label: "interna", className: "bg-cyan/10 text-cyan" },
  write: { label: "escritura", className: "bg-warn/15 text-warn" },
  execute: { label: "ejecución", className: "bg-danger/10 text-danger" },
  network: { label: "red", className: "bg-accent/15 text-accent" },
};

const ICONS: Record<string, typeof Wrench> = {
  file_list: FolderOpen,
  file_read: FileText,
  project_tree: FolderOpen,
  code_search: Search,
  file_write: FileCode,
  doc_search: Search,
  script_run: Terminal,
  logs_analyze: ShieldCheck,
  ioc_match: ShieldCheck,
  net_diagnose: Network,
  security_report: FileText,
};

const STATUS: Record<ToolCallStatus, { label: string; className: string }> = {
  running: { label: "en curso", className: "text-cyan" },
  awaiting: { label: "esperando tu permiso", className: "text-warn" },
  ok: { label: "completada", className: "text-ok" },
  error: { label: "error", className: "text-danger" },
  denied: { label: "no ejecutada", className: "text-muted" },
};

function Countdown({ expiresAt }: { expiresAt: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const seconds = Math.max(0, Math.round((expiresAt - now) / 1000));
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted">
      <Clock className="size-3" /> {seconds} s
    </span>
  );
}

/** Vista previa de los argumentos reales (no el resumen del modelo). */
function ArgumentsPreview({ args }: { args: Record<string, unknown> }) {
  const entries = Object.entries(args);
  if (entries.length === 0) return null;
  return (
    <dl className="mt-2 space-y-1 rounded-lg bg-code p-2 font-mono text-[12px]">
      {entries.map(([key, value]) => {
        const text = typeof value === "string" ? value : JSON.stringify(value);
        return (
          <div key={key} className="flex gap-2">
            <dt className="shrink-0 text-muted">{key}:</dt>
            <dd className="max-h-40 min-w-0 overflow-auto whitespace-pre-wrap break-all">
              {text.length > 1500 ? `${text.slice(0, 1500)}…` : text}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

interface ToolCallsProps {
  tools: Array<ToolCallView | ToolCallLog>;
  onConfirm?: (callId: string, approved: boolean) => void;
}

function normalize(tool: ToolCallView | ToolCallLog): ToolCallView {
  if ("callId" in tool) return tool;
  return {
    callId: tool.call_id,
    tool: tool.tool,
    risk: tool.risk,
    summary: tool.summary,
    arguments: {},
    status: tool.status,
    resultSummary: tool.summary,
    expiresAt: null,
  };
}

export function ToolCalls({ tools, onConfirm }: ToolCallsProps) {
  if (tools.length === 0) return null;
  return (
    <div className="mb-3 space-y-2" aria-label="Herramientas usadas">
      {tools.map(normalize).map((tool) => {
        const Icon = ICONS[tool.tool] ?? Wrench;
        const risk = RISK_LABELS[tool.risk] ?? { label: tool.risk, className: "bg-surface-2 text-muted" };
        const status = STATUS[tool.status];
        const awaiting = tool.status === "awaiting";
        return (
          <div
            key={tool.callId}
            className={cn(
              "rounded-xl border px-3 py-2 text-sm",
              awaiting ? "border-warn/50 bg-warn/5" : "border-border bg-surface",
            )}
          >
            <div className="flex flex-wrap items-center gap-2">
              <Icon className="size-4 shrink-0 text-primary" />
              <span className="font-medium">{TOOL_LABELS[tool.tool] ?? tool.tool}</span>
              <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", risk.className)}>
                {risk.label}
              </span>
              <span className={cn("ml-auto inline-flex items-center gap-1 text-xs", status.className)}>
                {tool.status === "running" && <Spinner className="size-3" />}
                {tool.status === "ok" && <Check className="size-3" />}
                {tool.status === "error" && <CircleExclamationPoint className="size-3" />}
                {tool.status === "denied" && <ShieldX className="size-3" />}
                {status.label}
              </span>
            </div>
            <p className="mt-1 text-xs text-muted">{awaiting ? tool.summary : (tool.resultSummary ?? tool.summary)}</p>
            {awaiting && (
              <>
                <ArgumentsPreview args={tool.arguments} />
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    variant="primary"
                    icon={<Check className="size-3.5" />}
                    onClick={() => onConfirm?.(tool.callId, true)}
                    disabled={!onConfirm}
                  >
                    Permitir
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={<X className="size-3.5" />}
                    onClick={() => onConfirm?.(tool.callId, false)}
                    disabled={!onConfirm}
                  >
                    Denegar
                  </Button>
                  {tool.expiresAt && <Countdown expiresAt={tool.expiresAt} />}
                </div>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
