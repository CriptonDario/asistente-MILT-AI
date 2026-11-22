import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { Composer } from "../components/chat/Composer";
import { EmptyState } from "../components/chat/EmptyState";
import { MessageList } from "../components/chat/MessageList";
import { Header } from "../components/layout/Header";
import { Spinner } from "../components/ui/Spinner";
import {
  useConversation,
  useCreateConversation,
  useDeleteMessage,
  useMessages,
  useSettings,
  useUpdateConversation,
} from "../hooks/queries";
import { useChatActions, useStream } from "../hooks/useChat";
import { errorMessage } from "../services/http";
import { isActive } from "../stores/chat";
import { useSession } from "../stores/session";
import { useUi } from "../stores/ui";

export function ChatPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const user = useSession((s) => s.user);
  const draftModel = useUi((s) => s.draftModel);
  const setDraftModel = useUi((s) => s.setDraftModel);
  const settings = useSettings();
  const conversation = useConversation(conversationId);
  const messages = useMessages(conversationId);
  const stream = useStream(conversationId);
  const createConversation = useCreateConversation();
  const updateConversation = useUpdateConversation();
  const deleteMessage = useDeleteMessage(conversationId ?? "");
  const { send, regenerate, cancel, dismiss } = useChatActions();
  const [createError, setCreateError] = useState<string | null>(null);

  const streaming = isActive(stream);
  const model = conversationId ? (conversation.data?.model ?? null) : draftModel;
  const defaultModel = settings.data?.effective_default_model;

  const handleSend = async (text: string) => {
    setCreateError(null);
    if (conversationId) {
      void send(conversationId, text);
      return;
    }
    // Primera pregunta: se crea la conversación y se envía en cuanto existe.
    try {
      const conv = await createConversation.mutateAsync(draftModel ? { model: draftModel } : {});
      setDraftModel(null);
      navigate(`/c/${conv.id}`);
      void send(conv.id, text);
    } catch (error) {
      setCreateError(errorMessage(error));
    }
  };

  const handleModelChange = (name: string) => {
    if (conversationId) updateConversation.mutate({ id: conversationId, body: { model: name } });
    else setDraftModel(name);
  };

  const notFound = conversationId && conversation.isError;

  return (
    <>
      <Header
        title={conversation.data?.title ?? "Nueva conversación"}
        model={model}
        defaultModel={defaultModel}
        onModelChange={handleModelChange}
      />

      {notFound ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center">
          <p className="font-medium">No se encontró esta conversación.</p>
          <p className="text-sm text-muted">Puede que se haya eliminado.</p>
        </div>
      ) : !conversationId ? (
        <EmptyState name={user?.display_name} onPick={(text) => void handleSend(text)} />
      ) : messages.isLoading ? (
        <div className="flex flex-1 items-center justify-center">
          <Spinner className="size-6" />
        </div>
      ) : (
        <MessageList
          messages={messages.data ?? []}
          stream={stream}
          onRegenerate={() => void regenerate(conversationId)}
          onDeleteMessage={(id) => deleteMessage.mutate(id)}
          onDismissStream={() => dismiss(conversationId)}
        />
      )}

      <div className="shrink-0 px-3 pb-3 pt-1 sm:px-4 sm:pb-4">
        {createError && (
          <p role="alert" className="mx-auto mb-2 max-w-3xl text-sm text-danger">
            {createError}
          </p>
        )}
        <Composer
          key={conversationId ?? "nueva"}
          onSend={(text) => void handleSend(text)}
          onStop={() => conversationId && cancel(conversationId)}
          streaming={streaming}
          disabled={Boolean(notFound) || createConversation.isPending}
        />
        <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-muted">
          MILT puede equivocarse. Verifica la información importante.
        </p>
      </div>
    </>
  );
}
