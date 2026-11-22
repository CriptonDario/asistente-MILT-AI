import { ArrowDown } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { StreamState } from "../../stores/chat";
import { isActive } from "../../stores/chat";
import type { Message } from "../../types/api";
import { MessageItem, UserBubble } from "./MessageItem";
import { StreamingMessage } from "./StreamingMessage";

interface MessageListProps {
  messages: Message[];
  stream: StreamState | undefined;
  onRegenerate: () => void;
  onDeleteMessage: (id: string) => void;
  onDismissStream: () => void;
}

/** Une los mensajes guardados con la respuesta en curso, sin duplicados. */
export function visibleTimeline(messages: Message[], stream: StreamState | undefined) {
  const ids = new Set(messages.map((m) => m.id));
  const showOptimisticUser =
    stream?.userContent != null && !(stream.userMessageId && ids.has(stream.userMessageId));
  const showStream =
    stream !== undefined && !(stream.messageId && ids.has(stream.messageId));
  return { showOptimisticUser, showStream };
}

export function MessageList({
  messages,
  stream,
  onRegenerate,
  onDeleteMessage,
  onDismissStream,
}: MessageListProps) {
  const scroller = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const busy = isActive(stream);
  const { showOptimisticUser, showStream } = visibleTimeline(messages, stream);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = scroller.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);

  // Mantiene el final a la vista mientras llega texto, salvo que el usuario haya subido.
  useLayoutEffect(() => {
    if (atBottom) scrollToBottom();
  }, [messages, stream?.text, stream?.status, atBottom, scrollToBottom]);

  useEffect(() => {
    scrollToBottom();
  }, [scrollToBottom]);

  const lastAssistantId = [...messages].reverse().find((m) => m.role === "assistant")?.id;

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={scroller}
        onScroll={(event) => {
          const el = event.currentTarget;
          setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
        }}
        className="h-full overflow-y-auto"
      >
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
          {messages.map((message) => (
            <MessageItem
              key={message.id}
              message={message}
              isLast={message.id === lastAssistantId && messages.at(-1)?.id === message.id}
              busy={busy}
              onRegenerate={onRegenerate}
              onDelete={() => onDeleteMessage(message.id)}
            />
          ))}
          {showOptimisticUser && stream?.userContent && <UserBubble content={stream.userContent} />}
          {showStream && stream && (
            <StreamingMessage stream={stream} onRetry={onRegenerate} onDismiss={onDismissStream} />
          )}
        </div>
      </div>
      {!atBottom && (
        <button
          type="button"
          onClick={() => scrollToBottom("smooth")}
          className="absolute bottom-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1 rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-muted shadow-panel hover:text-text"
        >
          <ArrowDown className="size-3.5" /> Ir al final
        </button>
      )}
    </div>
  );
}
