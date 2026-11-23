import {
  Download,
  Eye,
  FolderPlus,
  RefreshCw,
  ShieldCheck,
  Terminal,
  Trash,
  Wrench,
  X,
} from "lucide-react";
import { type FormEvent, useState } from "react";
import { queryClient, queryKeys } from "../../app/queryClient";
import {
  useReports,
  useScripts,
  useToolExecutions,
  useToolRoots,
  useTools,
} from "../../hooks/queries";
import { cn } from "../../lib/cn";
import { timeAgo } from "../../lib/format";
import { toolsApi } from "../../services/endpoints";
import { errorMessage } from "../../services/http";
import { useSession } from "../../stores/session";
import { useUi } from "../../stores/ui";
import type { Report, ToolDecision } from "../../types/api";
import { Markdown } from "../chat/Markdown";
import { RISK_LABELS, TOOL_LABELS } from "../chat/ToolCalls";
import { PanelSection, SidePanel } from "../layout/SidePanel";
import { Button, IconButton } from "../ui/Button";
import { ConfirmDialog, Modal } from "../ui/Modal";
import { Spinner } from "../ui/Spinner";

const field =
  "h-9 w-full rounded-lg border border-border bg-surface-2 px-2.5 text-sm outline-none focus:ring-2 focus:ring-primary/40";

const DECISION_LABELS: Record<ToolDecision | "default", string> = {
  auto: "Automática",
  confirm: "Pedir permiso",
  deny: "Bloqueada",
  default: "Por defecto",
};

function invalidate(...keys: (readonly unknown[])[]) {
  for (const key of keys) void queryClient.invalidateQueries({ queryKey: key });
}

// ------------------------------------------------------------------ carpetas
function RootsSection() {
  const roots = useToolRoots();
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const current = roots.data?.roots ?? [];

  const save = async (next: string[]) => {
    setSaving(true);
    setError(null);
    try {
      await toolsApi.setRoots(next);
      setDraft("");
      invalidate(queryKeys.toolRoots);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const add = (event: FormEvent) => {
    event.preventDefault();
    if (draft.trim()) void save([...current, draft.trim()]);
  };

  return (
    <PanelSection title="Carpetas autorizadas">
      <p className="text-xs text-muted">
        Las herramientas solo pueden leer o escribir dentro de estas carpetas. Nunca en la
        carpeta de Windows, en archivos de claves (.env, .ssh…) ni en los datos de MILT.
      </p>
      {roots.isLoading && <Spinner />}
      <ul className="space-y-1.5">
        {current.map((root) => (
          <li key={root} className="flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm">
            <span className="min-w-0 flex-1 truncate font-mono text-xs" title={root}>
              {root}
            </span>
            <IconButton
              label="Quitar carpeta"
              className="size-7"
              disabled={saving}
              onClick={() => void save(current.filter((r) => r !== root))}
            >
              <X className="size-3.5" />
            </IconButton>
          </li>
        ))}
        {!roots.isLoading && current.length === 0 && (
          <li className="text-sm text-muted">Ninguna todavía.</li>
        )}
      </ul>
      <form onSubmit={add} className="flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="C:\laragon\www\mi-proyecto"
          aria-label="Nueva carpeta autorizada"
          className={cn(field, "font-mono text-xs")}
        />
        <Button type="submit" size="sm" icon={<FolderPlus className="size-3.5" />} disabled={saving || !draft.trim()}>
          Añadir
        </Button>
      </form>
      {error && <p className="text-xs text-danger">{error}</p>}
    </PanelSection>
  );
}

// ------------------------------------------------------------------ permisos
function PermissionsSection() {
  const tools = useTools();
  const [error, setError] = useState<string | null>(null);

  const change = async (name: string, decision: ToolDecision | "default") => {
    setError(null);
    try {
      await toolsApi.setPolicy(name, decision);
      invalidate(queryKeys.tools);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <PanelSection title="Permisos">
      <p className="text-xs text-muted">
        Leer es automático; escribir, ejecutar y usar la red piden tu permiso. Ejecutar scripts y
        diagnosticar la red siempre lo piden.
      </p>
      {tools.isLoading && <Spinner />}
      <ul className="space-y-1">
        {tools.data?.map((tool) => {
          const risk = RISK_LABELS[tool.risk];
          const locked = tool.risk === "execute" || tool.risk === "network";
          return (
            <li key={tool.name} className="flex items-center gap-2 py-1 text-sm">
              <span className="min-w-0 flex-1 truncate" title={tool.description}>
                {TOOL_LABELS[tool.name] ?? tool.name}
              </span>
              {risk && (
                <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", risk.className)}>
                  {risk.label}
                </span>
              )}
              <select
                value={tool.customized ? tool.decision : "default"}
                onChange={(e) => void change(tool.name, e.target.value as ToolDecision | "default")}
                aria-label={`Permiso de ${TOOL_LABELS[tool.name] ?? tool.name}`}
                className="h-8 w-36 rounded-lg border border-border bg-surface-2 px-1.5 text-xs outline-none"
              >
                <option value="default">
                  {DECISION_LABELS.default} ({DECISION_LABELS[tool.decision]})
                </option>
                {!locked && <option value="auto">{DECISION_LABELS.auto}</option>}
                <option value="confirm">{DECISION_LABELS.confirm}</option>
                <option value="deny">{DECISION_LABELS.deny}</option>
              </select>
            </li>
          );
        })}
      </ul>
      {error && <p className="text-xs text-danger">{error}</p>}
    </PanelSection>
  );
}

// ------------------------------------------------------------------ scripts
function ScriptsSection() {
  const isAdmin = useSession((s) => s.user?.role === "admin");
  const scripts = useScripts();
  const [form, setForm] = useState({ name: "", path: "", description: "", max_args: 0, timeout_seconds: 60 });
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const register = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await toolsApi.registerScript(form);
      setForm({ name: "", path: "", description: "", max_args: 0, timeout_seconds: 60 });
      invalidate(queryKeys.scripts);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <PanelSection title="Scripts autorizados">
      <p className="text-xs text-muted">
        MILT solo puede ejecutar estos scripts (.py, .ps1 o .exe), siempre con tu permiso, con
        límite de tiempo y memoria. Si un script cambia, se bloquea hasta que un administrador lo
        vuelva a autorizar.
      </p>
      {scripts.isLoading && <Spinner />}
      <ul className="space-y-1.5">
        {scripts.data?.map((script) => (
          <li key={script.id} className="rounded-lg border border-border px-3 py-2 text-sm">
            <div className="flex items-center gap-2">
              <Terminal className="size-4 shrink-0 text-primary" />
              <span className="font-medium">{script.name}</span>
              <span className="text-xs text-muted">· {script.runner} · {script.timeout_seconds} s</span>
              {isAdmin && (
                <div className="ml-auto flex gap-0.5">
                  <IconButton
                    label="Volver a autorizar (acepta la versión actual)"
                    className="size-7"
                    onClick={async () => {
                      await toolsApi.reauthorizeScript(script.id);
                      invalidate(queryKeys.scripts);
                    }}
                  >
                    <RefreshCw className="size-3.5" />
                  </IconButton>
                  <IconButton label="Quitar autorización" className="size-7" onClick={() => setConfirmDelete(script.id)}>
                    <Trash className="size-3.5" />
                  </IconButton>
                </div>
              )}
            </div>
            {script.description && <p className="mt-0.5 text-xs text-muted">{script.description}</p>}
            <p className="mt-0.5 truncate font-mono text-[11px] text-muted" title={script.path}>
              {script.path}
            </p>
          </li>
        ))}
        {scripts.data?.length === 0 && <li className="text-sm text-muted">Ninguno autorizado.</li>}
      </ul>
      {isAdmin && (
        <form onSubmit={register} className="space-y-2 rounded-xl border border-dashed border-border p-3">
          <div className="grid grid-cols-2 gap-2">
            <input
              className={field}
              placeholder="nombre (a-z, 0-9, -_)"
              aria-label="Nombre del script"
              value={form.name}
              pattern="[a-z0-9_-]{1,64}"
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
            <input
              className={field}
              placeholder="Descripción"
              aria-label="Descripción del script"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </div>
          <input
            className={cn(field, "font-mono text-xs")}
            placeholder="C:\scripts\copia_seguridad.ps1"
            aria-label="Ruta del script"
            value={form.path}
            onChange={(e) => setForm({ ...form, path: e.target.value })}
            required
          />
          <div className="flex items-center gap-2 text-xs text-muted">
            <label className="flex items-center gap-1">
              Argumentos máx.
              <input
                type="number"
                min={0}
                max={20}
                value={form.max_args}
                onChange={(e) => setForm({ ...form, max_args: Number(e.target.value) })}
                className="h-8 w-14 rounded border border-border bg-surface-2 px-1 text-text"
              />
            </label>
            <label className="flex items-center gap-1">
              Tiempo (s)
              <input
                type="number"
                min={1}
                max={300}
                value={form.timeout_seconds}
                onChange={(e) => setForm({ ...form, timeout_seconds: Number(e.target.value) })}
                className="h-8 w-16 rounded border border-border bg-surface-2 px-1 text-text"
              />
            </label>
            <Button type="submit" size="sm" className="ml-auto" icon={<ShieldCheck className="size-3.5" />}>
              Autorizar
            </Button>
          </div>
          {error && <p className="text-xs text-danger">{error}</p>}
        </form>
      )}
      {confirmDelete && (
        <ConfirmDialog
          title="Quitar autorización"
          message="MILT dejará de poder ejecutar este script."
          confirmLabel="Quitar"
          danger
          onCancel={() => setConfirmDelete(null)}
          onConfirm={async () => {
            const id = confirmDelete;
            setConfirmDelete(null);
            await toolsApi.deleteScript(id);
            invalidate(queryKeys.scripts);
          }}
        />
      )}
    </PanelSection>
  );
}

// ------------------------------------------------------------------ historial y reportes
function HistorySection() {
  const executions = useToolExecutions();
  const statusClass: Record<string, string> = { ok: "text-ok", error: "text-danger", denied: "text-muted" };
  return (
    <PanelSection title="Historial">
      {executions.isLoading && <Spinner />}
      {executions.data?.length === 0 && <p className="text-sm text-muted">Aún no se ha usado ninguna herramienta.</p>}
      <ul className="space-y-1">
        {executions.data?.map((e) => (
          <li key={e.id} className="text-xs">
            <span className="font-medium text-text">{TOOL_LABELS[e.tool_name] ?? e.tool_name}</span>{" "}
            <span className={statusClass[e.status] ?? "text-muted"}>({e.status})</span>{" "}
            <span className="text-muted">· {e.decision} · {timeAgo(e.created_at)}</span>
            {e.result_summary && <p className="truncate text-muted">{e.result_summary}</p>}
          </li>
        ))}
      </ul>
    </PanelSection>
  );
}

function ReportsSection() {
  const reports = useReports();
  const [open, setOpen] = useState<Report | null>(null);
  const severity: Record<string, string> = {
    critical: "bg-danger/15 text-danger",
    high: "bg-danger/10 text-danger",
    medium: "bg-warn/15 text-warn",
    low: "bg-primary/10 text-primary",
    info: "bg-surface-2 text-muted",
  };
  return (
    <PanelSection title="Reportes de seguridad">
      {reports.isLoading && <Spinner />}
      {reports.data?.length === 0 && (
        <p className="text-sm text-muted">
          Sin reportes. En una conversación con el perfil Seguridad, pide a MILT que analice un
          log y guarde un reporte.
        </p>
      )}
      <ul className="space-y-1.5">
        {reports.data?.map((report) => (
          <li key={report.id} className="flex items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm">
            <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", severity[report.severity])}>
              {report.severity}
            </span>
            <span className="min-w-0 flex-1 truncate">{report.title}</span>
            <IconButton label="Ver reporte" className="size-7" onClick={async () => setOpen(await toolsApi.report(report.id))}>
              <Eye className="size-3.5" />
            </IconButton>
            <IconButton label="Descargar (.md)" className="size-7" onClick={() => void toolsApi.downloadReport(report)}>
              <Download className="size-3.5" />
            </IconButton>
            <IconButton
              label="Eliminar reporte"
              className="size-7"
              onClick={async () => {
                await toolsApi.deleteReport(report.id);
                invalidate(queryKeys.reports);
              }}
            >
              <Trash className="size-3.5" />
            </IconButton>
          </li>
        ))}
      </ul>
      {open && (
        <Modal title={open.title} onClose={() => setOpen(null)}>
          <div className="max-h-[60vh] overflow-y-auto text-text">
            <Markdown text={open.content} />
          </div>
        </Modal>
      )}
    </PanelSection>
  );
}

export function ToolsPanel() {
  const openPanel = useUi((s) => s.openPanel);
  return (
    <SidePanel title="Herramientas" icon={<Wrench className="size-4 text-primary" />} onClose={() => openPanel(null)}>
      <p className="mb-4 text-xs text-muted">
        Actívalas en cada conversación con el botón <strong>Herramientas</strong> de la cabecera y
        elige el perfil (Programación, Seguridad…). MILT propone; tú decides.
      </p>
      <RootsSection />
      <PermissionsSection />
      <ScriptsSection />
      <ReportsSection />
      <HistorySection />
    </SidePanel>
  );
}
