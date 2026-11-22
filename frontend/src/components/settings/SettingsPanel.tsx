import { KeyRound, LogOut, Settings, ShieldCheck } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router";
import { queryClient, queryKeys } from "../../app/queryClient";
import { chatSocket } from "../../hooks/useChat";
import { useModels, useSessions, useSettings, useUpdateSettings } from "../../hooks/queries";
import { cn } from "../../lib/cn";
import { timeAgo } from "../../lib/format";
import { authApi } from "../../services/endpoints";
import { errorMessage } from "../../services/http";
import { useSession } from "../../stores/session";
import { useUi } from "../../stores/ui";
import type { Theme } from "../../types/api";
import { Button } from "../ui/Button";
import { Spinner } from "../ui/Spinner";
import { PanelSection, SidePanel } from "../layout/SidePanel";

const THEMES: { value: Theme; label: string }[] = [
  { value: "dark", label: "Oscuro" },
  { value: "light", label: "Claro" },
  { value: "system", label: "Sistema" },
];

const CONTEXTS = [2048, 4096, 8192];

const field =
  "h-9 w-full rounded-lg border border-border bg-surface-2 px-2.5 text-sm outline-none focus:ring-2 focus:ring-primary/40";

export async function logout(navigate: (to: string) => void) {
  try {
    await authApi.logout();
  } catch {
    // Aunque falle la llamada, se cierra la sesión local.
  }
  chatSocket.close();
  useSession.getState().clear();
  queryClient.clear();
  navigate("/login");
}

function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setStatus(null);
    try {
      await authApi.changePassword(current, next);
      setCurrent("");
      setNext("");
      setStatus({ ok: true, text: "Contraseña actualizada. Se cerraron las demás sesiones." });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
    } catch (error) {
      setStatus({ ok: false, text: errorMessage(error) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-2">
      <input
        type="password"
        autoComplete="current-password"
        placeholder="Contraseña actual"
        aria-label="Contraseña actual"
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
        className={field}
        required
      />
      <input
        type="password"
        autoComplete="new-password"
        placeholder="Nueva contraseña (mínimo 12 caracteres)"
        aria-label="Nueva contraseña"
        value={next}
        minLength={12}
        onChange={(e) => setNext(e.target.value)}
        className={field}
        required
      />
      {status && (
        <p className={cn("text-xs", status.ok ? "text-ok" : "text-danger")} role="status">
          {status.text}
        </p>
      )}
      <Button type="submit" size="sm" icon={<KeyRound className="size-3.5" />} disabled={saving}>
        Cambiar contraseña
      </Button>
    </form>
  );
}

export function SettingsPanel() {
  const openPanel = useUi((s) => s.openPanel);
  const setTheme = useUi((s) => s.setTheme);
  const theme = useUi((s) => s.theme);
  const navigate = useNavigate();
  const settings = useSettings();
  const models = useModels();
  const update = useUpdateSettings();
  const sessions = useSessions(true);
  const defaults = settings.data?.generation_defaults;

  const close = () => openPanel(null);

  return (
    <SidePanel title="Configuración" icon={<Settings className="size-4 text-primary" />} onClose={close}>
      <PanelSection title="Apariencia">
        <div className="grid grid-cols-3 gap-1 rounded-lg bg-surface-2 p-1" role="radiogroup" aria-label="Tema">
          {THEMES.map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={theme === option.value}
              onClick={() => {
                setTheme(option.value);
                update.mutate({ theme: option.value });
              }}
              className={cn(
                "rounded-md py-1.5 text-sm transition",
                theme === option.value ? "bg-surface text-text shadow-sm" : "text-muted hover:text-text",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </PanelSection>

      <PanelSection title="Modelo">
        {settings.isLoading ? (
          <Spinner />
        ) : (
          <>
            <label className="block text-sm">
              <span className="mb-1 block text-muted">Modelo predeterminado</span>
              <select
                className={field}
                value={settings.data?.default_model ?? ""}
                onChange={(e) => update.mutate({ default_model: e.target.value || null })}
              >
                <option value="">
                  Del sistema ({settings.data?.effective_default_model ?? "—"})
                </option>
                {models.data?.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className="mb-1 flex justify-between text-muted">
                Creatividad (temperatura)
                <span className="tabular-nums text-text">{defaults?.temperature ?? 0.7}</span>
              </span>
              <input
                type="range"
                min={0}
                max={1.5}
                step={0.1}
                defaultValue={defaults?.temperature ?? 0.7}
                onMouseUp={(e) =>
                  update.mutate({
                    generation_defaults: { ...defaults, temperature: Number(e.currentTarget.value) },
                  })
                }
                onKeyUp={(e) =>
                  update.mutate({
                    generation_defaults: { ...defaults, temperature: Number(e.currentTarget.value) },
                  })
                }
                className="w-full accent-[var(--primary)]"
                aria-label="Temperatura"
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-muted">Contexto (tokens)</span>
              <select
                className={field}
                value={defaults?.num_ctx ?? 4096}
                onChange={(e) =>
                  update.mutate({
                    generation_defaults: { ...defaults, num_ctx: Number(e.target.value) },
                  })
                }
              >
                {CONTEXTS.map((n) => (
                  <option key={n} value={n}>
                    {n.toLocaleString("es")}
                    {n > 4096 ? " (más RAM y más lento)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-1 accent-[var(--primary)]"
                checked={defaults?.think ?? false}
                onChange={(e) =>
                  update.mutate({ generation_defaults: { ...defaults, think: e.target.checked } })
                }
              />
              <span>
                Razonamiento extendido
                <span className="block text-xs text-muted">
                  Mejora respuestas complejas, pero en CPU es mucho más lento.
                </span>
              </span>
            </label>
            {update.isError && (
              <p className="text-xs text-danger">{errorMessage(update.error)}</p>
            )}
          </>
        )}
      </PanelSection>

      <PanelSection title="Sesiones activas">
        {sessions.isLoading && <Spinner />}
        <ul className="space-y-2">
          {sessions.data?.map((session) => (
            <li
              key={session.id}
              className="flex items-center gap-3 rounded-lg border border-border px-3 py-2 text-sm"
            >
              <ShieldCheck className={cn("size-4", session.current ? "text-ok" : "text-muted")} />
              <div className="min-w-0 flex-1">
                <p className="truncate">
                  {session.device_name ?? "Dispositivo"}{" "}
                  {session.current && <span className="text-xs text-ok">(esta sesión)</span>}
                </p>
                <p className="truncate text-xs text-muted">
                  {session.platform} · {session.ip ?? "—"} · {timeAgo(session.last_refresh_at)}
                </p>
              </div>
              {!session.current && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={async () => {
                    await authApi.revokeSession(session.id);
                    void queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
                  }}
                >
                  Cerrar
                </Button>
              )}
            </li>
          ))}
        </ul>
      </PanelSection>

      <PanelSection title="Cuenta">
        <PasswordForm />
        <Button
          variant="ghost"
          icon={<LogOut className="size-4" />}
          className="text-danger hover:text-danger"
          onClick={() => void logout(navigate)}
        >
          Cerrar sesión
        </Button>
      </PanelSection>
    </SidePanel>
  );
}
