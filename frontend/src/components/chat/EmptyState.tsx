import { Logo } from "../ui/Logo";

const SUGGESTIONS = [
  "Explícame la diferencia entre un proceso y un hilo",
  "Revisa esta consulta SQL y sugiere índices",
  "Ayúdame a estructurar un proyecto FastAPI",
  "Resume las buenas prácticas para contraseñas",
];

export function EmptyState({
  name,
  onPick,
}: {
  name: string | undefined;
  onPick: (text: string) => void;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4 text-center">
      <Logo size={56} />
      <h1 className="mt-5 text-2xl font-semibold tracking-tight sm:text-3xl">
        Hola{name ? `, ${name.split(" ")[0]}` : ""}. <span className="brand-text">¿En qué trabajamos?</span>
      </h1>
      <p className="mt-2 max-w-md text-sm text-muted">
        MILT funciona en tu equipo: tus conversaciones no salen de aquí.
      </p>
      <div className="mt-8 grid w-full max-w-2xl gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map((text) => (
          <button
            key={text}
            type="button"
            onClick={() => onPick(text)}
            className="rounded-xl border border-border bg-surface px-4 py-3 text-left text-sm text-muted transition hover:border-primary/50 hover:text-text"
          >
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}
