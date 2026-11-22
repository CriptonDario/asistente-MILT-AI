import {
  Archive,
  ArchiveArrowUp,
  Download,
  Ellipsis,
  Pencil,
  Pin,
  PinOff,
  Trash,
} from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { NavLink, useNavigate } from "react-router";
import { useDeleteConversation, useUpdateConversation } from "../../hooks/queries";
import { useClickOutside } from "../../hooks/useClickOutside";
import { cn } from "../../lib/cn";
import { timeAgo } from "../../lib/format";
import { conversationsApi } from "../../services/endpoints";
import type { Conversation } from "../../types/api";
import { ConfirmDialog } from "../ui/Modal";

const UNTITLED = "Nueva conversación";

function MenuItem({
  icon,
  label,
  onClick,
  danger = false,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-surface-2",
        danger ? "text-danger" : "text-text",
      )}
    >
      {icon}
      {label}
    </button>
  );
}

async function downloadMarkdown(conversation: Conversation) {
  const markdown = await conversationsApi.exportMarkdown(conversation.id);
  const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${(conversation.title ?? "conversacion").slice(0, 60)}.md`;
  link.click();
  URL.revokeObjectURL(url);
}

export function ConversationItem({
  conversation,
  onNavigate,
}: {
  conversation: Conversation;
  onNavigate: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [title, setTitle] = useState(conversation.title ?? "");
  const menuRef = useRef<HTMLDivElement>(null);
  const closeMenu = useCallback(() => setMenuOpen(false), []);
  useClickOutside(menuRef, closeMenu, menuOpen);
  const update = useUpdateConversation();
  const remove = useDeleteConversation();
  const navigate = useNavigate();

  const saveTitle = () => {
    setRenaming(false);
    const next = title.trim();
    if (next && next !== conversation.title) {
      update.mutate({ id: conversation.id, body: { title: next } });
    } else {
      setTitle(conversation.title ?? "");
    }
  };

  if (renaming) {
    return (
      <input
        autoFocus
        value={title}
        maxLength={200}
        aria-label="Nuevo título"
        onChange={(event) => setTitle(event.target.value)}
        onBlur={saveTitle}
        onKeyDown={(event) => {
          if (event.key === "Enter") saveTitle();
          if (event.key === "Escape") {
            setTitle(conversation.title ?? "");
            setRenaming(false);
          }
        }}
        className="w-full rounded-lg border border-primary/60 bg-surface-2 px-2.5 py-1.5 text-sm outline-none"
      />
    );
  }

  return (
    <div className="group relative" ref={menuRef}>
      <NavLink
        to={`/c/${conversation.id}`}
        onClick={onNavigate}
        className={({ isActive }) =>
          cn(
            "flex items-center gap-2 rounded-lg px-2.5 py-2 pr-9 text-sm transition",
            isActive ? "bg-surface-2 text-text" : "text-muted hover:bg-surface-2/60 hover:text-text",
          )
        }
      >
        {conversation.pinned && <Pin className="size-3 shrink-0 text-accent" />}
        <span className="min-w-0 flex-1 truncate">{conversation.title ?? UNTITLED}</span>
        <span className="shrink-0 text-[11px] text-muted/80 group-hover:invisible">
          {timeAgo(conversation.updated_at)}
        </span>
      </NavLink>
      <button
        type="button"
        aria-label="Opciones de la conversación"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen((o) => !o)}
        className={cn(
          "absolute right-1 top-1/2 inline-flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-muted hover:bg-surface-3 hover:text-text",
          menuOpen ? "visible" : "invisible group-hover:visible group-focus-within:visible",
        )}
      >
        <Ellipsis className="size-4" />
      </button>
      {menuOpen && (
        <div
          role="menu"
          className="absolute right-0 top-9 z-30 w-48 rounded-lg border border-border bg-surface p-1 shadow-panel"
        >
          <MenuItem
            icon={<Pencil className="size-3.5" />}
            label="Renombrar"
            onClick={() => {
              closeMenu();
              setRenaming(true);
            }}
          />
          <MenuItem
            icon={conversation.pinned ? <PinOff className="size-3.5" /> : <Pin className="size-3.5" />}
            label={conversation.pinned ? "Desfijar" : "Fijar"}
            onClick={() => {
              closeMenu();
              update.mutate({ id: conversation.id, body: { pinned: !conversation.pinned } });
            }}
          />
          <MenuItem
            icon={
              conversation.archived ? (
                <ArchiveArrowUp className="size-3.5" />
              ) : (
                <Archive className="size-3.5" />
              )
            }
            label={conversation.archived ? "Restaurar" : "Archivar"}
            onClick={() => {
              closeMenu();
              update.mutate({ id: conversation.id, body: { archived: !conversation.archived } });
            }}
          />
          <MenuItem
            icon={<Download className="size-3.5" />}
            label="Exportar (.md)"
            onClick={() => {
              closeMenu();
              void downloadMarkdown(conversation);
            }}
          />
          <MenuItem
            icon={<Trash className="size-3.5" />}
            label="Eliminar"
            danger
            onClick={() => {
              closeMenu();
              setConfirmDelete(true);
            }}
          />
        </div>
      )}
      {confirmDelete && (
        <ConfirmDialog
          title="Eliminar conversación"
          message={`Se eliminará «${conversation.title ?? UNTITLED}» y todos sus mensajes.`}
          confirmLabel="Eliminar"
          danger
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => {
            setConfirmDelete(false);
            remove.mutate(conversation.id, {
              onSuccess: () => {
                if (window.location.pathname.endsWith(conversation.id)) navigate("/");
              },
            });
          }}
        />
      )}
    </div>
  );
}
