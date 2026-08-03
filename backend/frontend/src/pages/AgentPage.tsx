import { Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "../app/useAuth";
import { AgentSidebar } from "../components/layout/AgentSidebar";
import { DashboardShell } from "../components/layout/DashboardShell";
import { AnswerPanel } from "../features/chat/AnswerPanel";
import { ChatComposer } from "../features/chat/ChatComposer";
import { SourceList } from "../features/chat/SourceList";
import { getApiErrorMessage } from "../services/apiClient";
import { askKnowledgeBase } from "../services/chatApi";
import {
  ChatStreamRequestError,
  emptyStreamingResponse,
  streamKnowledgeBase,
  StreamingUnsupportedError,
  type ChatStreamEvent,
} from "../services/chatStream";
import type { ChatResponse, ChatStreamStatus } from "../types/backend";

const activeStatuses = new Set<ChatStreamStatus>(["retrieving", "generating"]);
const conversationStorageKey = "lab-ia-genius.agentConversation.v1";

type UserThreadMessage = {
  id: string;
  role: "user";
  content: string;
  messageId: number | null;
};

type AssistantThreadMessage = {
  id: string;
  role: "assistant";
  response: ChatResponse;
  status: ChatStreamStatus;
  streamWarning: string | null;
  error: string | null;
};

type ThreadMessage = UserThreadMessage | AssistantThreadMessage;

type StoredConversation = {
  sessionId: number | null;
  messages: ThreadMessage[];
};

function makeLocalId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function normalizeStoredMessages(messages: unknown): ThreadMessage[] {
  if (!Array.isArray(messages)) return [];
  return messages.map((message) => {
    const candidate = message as Partial<AssistantThreadMessage> & { role?: unknown };
    if (candidate.role !== "assistant") return message as ThreadMessage;
    if (!candidate.status || !activeStatuses.has(candidate.status)) return message as ThreadMessage;
    return {
      ...candidate,
      status: "partial",
      streamWarning: candidate.streamWarning ?? "La génération précédente a été interrompue.",
    } as ThreadMessage;
  });
}

function loadStoredConversation(): StoredConversation {
  try {
    const value = window.sessionStorage.getItem(conversationStorageKey);
    if (!value) return { sessionId: null, messages: [] };
    const parsed = JSON.parse(value) as StoredConversation;
    return {
      sessionId: typeof parsed.sessionId === "number" ? parsed.sessionId : null,
      messages: normalizeStoredMessages(parsed.messages),
    };
  } catch {
    return { sessionId: null, messages: [] };
  }
}

function getAssistantMessageId(response: ChatResponse) {
  return response.audit?.assistant_message_id ?? response.audit?.message_id ?? null;
}

export function AgentPage() {
  const { user, accessToken, signOut } = useAuth();
  const [initialConversation] = useState(loadStoredConversation);

  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ThreadMessage[]>(initialConversation.messages);
  const [sessionId, setSessionId] = useState<number | null>(initialConversation.sessionId);
  const [status, setStatus] = useState<ChatStreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const activeStreamKeyRef = useRef<string | null>(null);
  const receivedTextRef = useRef("");

  useEffect(() => () => controllerRef.current?.abort(), []);

  useEffect(() => {
    window.sessionStorage.setItem(
      conversationStorageKey,
      JSON.stringify({ sessionId, messages }),
    );
  }, [sessionId, messages]);

  const streaming = activeStatuses.has(status);

  function updateAssistant(
    assistantId: string,
    updater: (message: AssistantThreadMessage) => AssistantThreadMessage,
  ) {
    setMessages((current) => current.map((message) => (
      message.id === assistantId && message.role === "assistant"
        ? updater(message)
        : message
    )));
  }

  function updateUserMessageId(userId: string, messageId: number | null | undefined) {
    if (!messageId) return;
    setMessages((current) => current.map((message) => (
      message.id === userId && message.role === "user"
        ? { ...message, messageId }
        : message
    )));
  }

  function applyStreamEvent(
    event: ChatStreamEvent,
    assistantId: string,
    userId: string,
    streamKey: string,
  ) {
    if (activeStreamKeyRef.current !== streamKey) return;

    if (event.type === "metadata") {
      if (event.audit?.session_id) setSessionId(event.audit.session_id);
      updateUserMessageId(userId, event.audit?.user_message_id);
      updateAssistant(assistantId, (message) => ({
        ...message,
        response: {
          ...message.response,
          question: event.question,
          confidence: event.confidence,
          sources: event.sources,
          audit: event.audit,
          generation_provider: event.generation_provider,
          generation_model: event.generation_model,
        },
        status: "generating",
        error: null,
      }));
      setStatus("generating");
      return;
    }

    if (event.type === "token") {
      receivedTextRef.current += event.text;
      updateAssistant(assistantId, (message) => ({
        ...message,
        response: { ...message.response, answer: message.response.answer + event.text },
        status: "generating",
      }));
      setStatus("generating");
      return;
    }

    if (event.type === "error") {
      const message = event.message ?? "La réponse n’a pas pu être terminée.";
      if (receivedTextRef.current) {
        updateAssistant(assistantId, (current) => ({
          ...current,
          status: "partial",
          streamWarning: message,
        }));
        setStatus("partial");
      } else {
        updateAssistant(assistantId, (current) => ({
          ...current,
          status: "failed",
          error: message,
        }));
        setStatus("failed");
      }
      return;
    }

    if (event.type === "done") {
      const assistantMessageId = event.assistant_message_id ?? event.message_id;
      updateAssistant(assistantId, (message) => ({
        ...message,
        response: {
          ...message.response,
          audit: message.response.audit
            ? {
              ...message.response.audit,
              message_id: assistantMessageId,
              assistant_message_id: assistantMessageId,
            }
            : message.response.audit,
        },
        status: event.partial ? "partial" : "complete",
        streamWarning: event.partial
          ? message.streamWarning ?? "La réponse a été interrompue."
          : message.streamWarning,
      }));
      setStatus(event.partial ? "partial" : "complete");
    }
  }

  async function submitQuestion() {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || streaming || !accessToken) return;

    const controller = new AbortController();
    const streamKey = makeLocalId("stream");
    const userId = makeLocalId("user");
    const assistantId = makeLocalId("assistant");
    const requestSessionId = sessionId;

    controllerRef.current = controller;
    activeStreamKeyRef.current = streamKey;
    receivedTextRef.current = "";
    setStatus("retrieving");
    setError(null);
    setQuestion("");
    setMessages((current) => [
      ...current,
      { id: userId, role: "user", content: trimmedQuestion, messageId: null },
      {
        id: assistantId,
        role: "assistant",
        response: emptyStreamingResponse(trimmedQuestion),
        status: "retrieving",
        streamWarning: null,
        error: null,
      },
    ]);

    try {
      await streamKnowledgeBase(trimmedQuestion, {
        token: accessToken,
        sessionId: requestSessionId,
        signal: controller.signal,
        onEvent: (event) => applyStreamEvent(event, assistantId, userId, streamKey),
        onAuthenticationFailure: signOut,
      });
    } catch (requestError) {
      if (controller.signal.aborted) {
        updateAssistant(assistantId, (message) => ({
          ...message,
          status: "cancelled",
          streamWarning: "Génération arrêtée. La réponse reçue a été conservée.",
        }));
        setStatus("cancelled");
      } else if (requestError instanceof StreamingUnsupportedError) {
        try {
          const fallbackResponse = await askKnowledgeBase(trimmedQuestion, requestSessionId);
          if (fallbackResponse.audit?.session_id) setSessionId(fallbackResponse.audit.session_id);
          updateUserMessageId(userId, fallbackResponse.audit?.user_message_id);
          updateAssistant(assistantId, (message) => ({
            ...message,
            response: fallbackResponse,
            status: "complete",
            error: null,
          }));
          setStatus("complete");
        } catch (fallbackError) {
          const message = getApiErrorMessage(fallbackError);
          updateAssistant(assistantId, (current) => ({ ...current, status: "failed", error: message }));
          setQuestion(trimmedQuestion);
          setStatus("failed");
        }
      } else if (
        requestError instanceof ChatStreamRequestError &&
        requestError.authenticationFailure
      ) {
        updateAssistant(assistantId, (current) => ({
          ...current,
          status: "failed",
          error: "Votre session a expiré.",
        }));
        setStatus("failed");
      } else if (receivedTextRef.current) {
        updateAssistant(assistantId, (current) => ({
          ...current,
          status: "partial",
          streamWarning: "La connexion a été interrompue. La réponse partielle est conservée.",
        }));
        setStatus("partial");
      } else {
        updateAssistant(assistantId, (current) => ({
          ...current,
          status: "failed",
          error: "Le service est momentanément indisponible. Réessayez dans un instant.",
        }));
        setQuestion(trimmedQuestion);
        setStatus("failed");
      }
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
      if (activeStreamKeyRef.current === streamKey) activeStreamKeyRef.current = null;
    }
  }

  function stopGeneration() {
    controllerRef.current?.abort();
  }

  function clearConversation() {
    controllerRef.current?.abort();
    controllerRef.current = null;
    activeStreamKeyRef.current = null;
    receivedTextRef.current = "";
    setQuestion("");
    setMessages([]);
    setSessionId(null);
    setStatus("idle");
    setError(null);
    window.sessionStorage.removeItem(conversationStorageKey);
  }

  const displayName = user?.full_name ?? "Agent";
  const thread = messages.length > 0 ? (
    <div className="conversation-thread" aria-label="Conversation en cours">
      {messages.map((message) => (
        message.role === "user" ? (
          <article className="thread-message thread-message-user" key={message.id}>
            <div>
              <span>Vous</span>
              <p>{message.content}</p>
            </div>
          </article>
        ) : (
          <article className="thread-message thread-message-assistant" key={message.id}>
            {message.error && <div className="message-error" role="alert">{message.error}</div>}
            <AnswerPanel
              response={message.response}
              status={message.status}
              streamWarning={message.streamWarning}
            />
            {message.response.sources.length > 0 && (
              <SourceList sources={message.response.sources} />
            )}
            {getAssistantMessageId(message.response) && (
              <span className="message-id-ref">Réponse #{getAssistantMessageId(message.response)}</span>
            )}
          </article>
        )
      ))}
    </div>
  ) : null;

  return (
    <DashboardShell
      sidebar={<AgentSidebar />}
      className="agent-console"
      consoleLabel="Espace Agent"
      searchLabel="Rechercher..."
      searchShortcut="Ctrl K"
      eyebrow="Espace Agent"
      title="Assistant de connaissance FDE"
      description="Posez une question métier et obtenez une réponse contextualisée, sourcée et traçable."
      showNotifications
      hideHeading
      userDisplayName={displayName}
    >
      <section className="agent-home" aria-label="Assistant de connaissance FDE">
        <div className="agent-greeting">
          <span className="agent-greeting-kicker"><Sparkles size={16} />Assistant opérationnel</span>
          <h1>Bonjour, <span>{displayName}</span></h1>
          <p>Comment puis-je vous aider aujourd'hui ?</p>
        </div>

        <ChatComposer
          question={question}
          loading={streaming}
          status={status}
          error={error}
          thread={thread}
          onQuestionChange={setQuestion}
          onSubmit={submitQuestion}
          onCancel={stopGeneration}
          onClear={clearConversation}
        />
      </section>
    </DashboardShell>
  );
}
