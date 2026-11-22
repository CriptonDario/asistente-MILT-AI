import { useQuery } from "@tanstack/react-query";
import { LogIn, UserPlus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Navigate } from "react-router";
import { Button } from "../components/ui/Button";
import { Logo } from "../components/ui/Logo";
import { Spinner } from "../components/ui/Spinner";
import { authApi } from "../services/endpoints";
import { errorMessage } from "../services/http";
import { useSession } from "../stores/session";

const field =
  "h-11 w-full rounded-xl border border-border bg-surface-2 px-3 text-sm outline-none transition placeholder:text-muted focus:border-primary/60 focus:ring-2 focus:ring-primary/30";

function deviceName(): string {
  const ua = navigator.userAgent;
  const browser = /Edg\//.test(ua)
    ? "Edge"
    : /Firefox\//.test(ua)
      ? "Firefox"
      : /Chrome\//.test(ua)
        ? "Chrome"
        : "Navegador";
  const os = /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android" : /Mac/.test(ua) ? "macOS" : "";
  return os ? `${browser} en ${os}` : browser;
}

export function LoginPage() {
  const status = useSession((s) => s.status);
  const setSession = useSession((s) => s.setSession);
  const setup = useQuery({ queryKey: ["setup"], queryFn: authApi.setup, retry: 1 });
  const [mode, setMode] = useState<"login" | "register" | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (status === "authenticated") return <Navigate to="/" replace />;

  const needsSetup = setup.data?.needs_setup ?? false;
  const currentMode = needsSetup ? "register" : (mode ?? "login");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (currentMode === "register" && password !== confirm) {
      setError("Las contraseñas no coinciden.");
      return;
    }
    setBusy(true);
    try {
      if (currentMode === "register") {
        await authApi.register({ email, password, display_name: name.trim() });
      }
      setSession(await authApi.login({ email, password, device_name: deviceName() }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative flex min-h-full items-center justify-center overflow-hidden px-4 py-10">
      {/* Halo de marca sutil detrás de la tarjeta. */}
      <div className="brand-gradient pointer-events-none absolute -top-40 left-1/2 size-[520px] -translate-x-1/2 rounded-full opacity-[0.12] blur-3xl" />
      <div className="relative w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <Logo size={52} />
          <h1 className="mt-4 text-2xl font-semibold tracking-tight">
            MILT <span className="brand-text">AI</span>
          </h1>
          <p className="mt-1 text-sm text-muted">My Intelligent Local Technology</p>
        </div>

        <div className="rounded-2xl border border-border bg-surface p-6 shadow-panel">
          {setup.isLoading ? (
            <div className="flex justify-center py-6">
              <Spinner className="size-5" />
            </div>
          ) : setup.isError ? (
            <p role="alert" className="text-sm text-danger">
              No se puede conectar con el servidor de MILT. Comprueba que el backend está en
              ejecución (puerto 8765).
            </p>
          ) : (
            <form onSubmit={submit} className="space-y-3">
              <div className="mb-1">
                <h2 className="text-base font-semibold">
                  {needsSetup
                    ? "Configura tu asistente"
                    : currentMode === "register"
                      ? "Crear cuenta"
                      : "Iniciar sesión"}
                </h2>
                {needsSetup && (
                  <p className="mt-1 text-xs text-muted">
                    Esta será la cuenta de administrador de este equipo.
                  </p>
                )}
              </div>
              {currentMode === "register" && (
                <input
                  className={field}
                  placeholder="Tu nombre"
                  aria-label="Nombre"
                  autoComplete="name"
                  value={name}
                  maxLength={100}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              )}
              <input
                className={field}
                type="email"
                placeholder="Correo"
                aria-label="Correo"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
              <input
                className={field}
                type="password"
                placeholder={currentMode === "register" ? "Contraseña (mínimo 12 caracteres)" : "Contraseña"}
                aria-label="Contraseña"
                autoComplete={currentMode === "register" ? "new-password" : "current-password"}
                minLength={currentMode === "register" ? 12 : undefined}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              {currentMode === "register" && (
                <input
                  className={field}
                  type="password"
                  placeholder="Repite la contraseña"
                  aria-label="Repite la contraseña"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                />
              )}
              {error && (
                <p role="alert" className="text-sm text-danger">
                  {error}
                </p>
              )}
              <Button
                type="submit"
                variant="primary"
                className="h-11 w-full"
                disabled={busy}
                icon={
                  busy ? (
                    <Spinner className="text-white" />
                  ) : currentMode === "register" ? (
                    <UserPlus className="size-4" />
                  ) : (
                    <LogIn className="size-4" />
                  )
                }
              >
                {currentMode === "register" ? "Crear cuenta y entrar" : "Entrar"}
              </Button>
              {!needsSetup && setup.data?.registration_open && (
                <button
                  type="button"
                  onClick={() => setMode(currentMode === "login" ? "register" : "login")}
                  className="w-full text-center text-xs text-muted hover:text-text"
                >
                  {currentMode === "login" ? "¿No tienes cuenta? Crear una" : "Ya tengo cuenta"}
                </button>
              )}
            </form>
          )}
        </div>
        <p className="mt-6 text-center text-xs text-muted">
          Funciona en tu equipo. Tus conversaciones no salen de aquí.
        </p>
      </div>
    </div>
  );
}
