import { Brain, PanelLeftClose, Search, Settings, SquarePen } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { useConversationList } from "../../hooks/queries";
import { useSession } from "../../stores/session";
import { useUi } from "../../stores/ui";
import { IconButton } from "../ui/Button";
import { Logo } from "../ui/Logo";
import { Spinner } from "../ui/Spinner";
import { ConversationItem } from "./ConversationItem";

function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-3">
      <h2 className="px-2.5 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted/80">
        {title}
      </h2>
      <div className="space-y-0.5">{children}</div>
    </section>
  );
}

export function Sidebar() {
  const navigate = useNavigate();
  const user = useSession((s) => s.user);
  const setSidebarOpen = useUi((s) => s.setSidebarOpen);
  const openPanel = useUi((s) => s.openPanel);
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState(false);
  const q = useDebounced(search.trim());
  const list = useConversationList(archived, q);

  const conversations = useMemo(
    () => list.data?.pages.flatMap((page) => page.items) ?? [],
    [list.data],
  );
  const pinned = conversations.filter((c) => c.pinned);
  const recent = conversations.filter((c) => !c.pinned);

  // En móvil, al navegar se cierra la barra lateral.
  const afterNavigate = () => {
    if (window.innerWidth < 768) setSidebarOpen(false);
  };

  const initials = (user?.display_name ?? "?")
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  let emptyText = "Aún no hay conversaciones.";
  if (q) emptyText = "Sin resultados.";
  else if (archived) emptyText = "No hay conversaciones archivadas.";

  return (
    <nav
      aria-label="Conversaciones"
      className="flex h-full w-72 flex-col border-r border-border bg-surface"
    >
      <div className="flex items-center gap-2 px-3 pb-2 pt-3">
        <Logo size={26} />
        <span className="text-[15px] font-semibold tracking-tight">
          MILT <span className="brand-text">AI</span>
        </span>
        <IconButton
          label="Ocultar barra lateral"
          className="ml-auto"
          onClick={() => setSidebarOpen(false)}
        >
          <PanelLeftClose className="size-4" />
        </IconButton>
      </div>

      <div className="space-y-2 px-3">
        <button
          type="button"
          onClick={() => {
            navigate("/");
            afterNavigate();
          }}
          className="flex w-full items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium transition hover:border-primary/50 hover:bg-surface-2"
          title="Nueva conversación (Ctrl+Shift+O)"
        >
          <SquarePen className="size-4 text-primary" />
          Nueva conversación
        </button>
        <label className="relative block">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
          <input
            id="conversation-search"
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Buscar (Ctrl+K)"
            aria-label="Buscar conversaciones"
            className="h-9 w-full rounded-lg bg-surface-2 pl-8 pr-2 text-sm outline-none placeholder:text-muted focus:ring-2 focus:ring-primary/40"
          />
        </label>
      </div>

      <div className="mt-3 min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {list.isLoading && (
          <div className="flex justify-center p-4">
            <Spinner />
          </div>
        )}
        {list.isError && (
          <p className="px-2 py-3 text-sm text-danger">No se pudieron cargar las conversaciones.</p>
        )}
        {!list.isLoading && !list.isError && conversations.length === 0 && (
          <p className="px-2 py-3 text-sm text-muted">{emptyText}</p>
        )}
        {pinned.length > 0 && (
          <Group title="Fijadas">
            {pinned.map((c) => (
              <ConversationItem key={c.id} conversation={c} onNavigate={afterNavigate} />
            ))}
          </Group>
        )}
        {recent.length > 0 && (
          <Group title={archived ? "Archivadas" : "Recientes"}>
            {recent.map((c) => (
              <ConversationItem key={c.id} conversation={c} onNavigate={afterNavigate} />
            ))}
          </Group>
        )}
        {list.hasNextPage && (
          <button
            type="button"
            onClick={() => void list.fetchNextPage()}
            disabled={list.isFetchingNextPage}
            className="w-full rounded-lg py-2 text-xs text-muted hover:bg-surface-2 hover:text-text"
          >
            {list.isFetchingNextPage ? "Cargando…" : "Cargar más"}
          </button>
        )}
        <button
          type="button"
          onClick={() => setArchived((a) => !a)}
          className="mt-2 w-full rounded-lg py-1.5 text-xs text-muted hover:text-text"
        >
          {archived ? "← Volver a recientes" : "Ver archivadas"}
        </button>
      </div>

      <div className="flex items-center gap-2 border-t border-border p-3">
        <div className="brand-gradient flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white">
          {initials}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{user?.display_name}</p>
          <p className="truncate text-xs text-muted">{user?.email}</p>
        </div>
        <IconButton label="Memoria" onClick={() => openPanel("memory")}>
          <Brain className="size-4" />
        </IconButton>
        <IconButton label="Configuración" onClick={() => openPanel("settings")}>
          <Settings className="size-4" />
        </IconButton>
      </div>
    </nav>
  );
}
