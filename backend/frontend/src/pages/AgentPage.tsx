import { Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "../app/useAuth";
import { AgentSidebar } from "../components/layout/AgentSidebar";
import { DashboardShell } from "../components/layout/DashboardShell";
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

export function AgentPage() {
  const { user, accessToken, signOut } = useAuth();
  const [question, setQuestion] = useState(
    "Quel code situation utiliser pour une demande d'autorisation voisinage ?",
  );
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [status, setStatus] = useState<ChatStreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [streamWarning, setStreamWarning] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const receivedTextRef = useRef("");

  useEffect(() => () => controllerRef.current?.abort(), []);

  const streaming = activeStatuses.has(status);

  function applyStreamEvent(event: ChatStreamEvent) {
    if (event.type === "metadata") {
      setResponse((current) => ({
        ...(current ?? emptyStreamingResponse(event.question)),
        question: event.question,
        confidence: event.confidence,
        sources: event.sources,
        audit: event.audit,
        generation_provider: event.generation_provider,
        generation_model: event.generation_model,
      }));
      setStatus("generating");
      return;
    }
    if (event.type === "token") {
      receivedTextRef.current += event.text;
      setResponse((current) =>
        current ? { ...current, answer: current.answer + event.text } : current,
      );
      setStatus("generating");
      return;
    }
    if (event.type === "error") {
      const message = event.message ?? "La réponse n’a pas pu être terminée.";
      if (receivedTextRef.current) {
        setStatus("partial");
        setStreamWarning(message);
      } else {
        setStatus("failed");
        setError(message);
      }
      return;
    }
    if (event.type === "done") {
      if (event.message_id) {
        setResponse((current) => current ? {
          ...current,
          audit: current.audit ? { ...current.audit, message_id: event.message_id } : null,
        } : current);
      }
      if (event.partial) {
        setStatus("partial");
        setStreamWarning((current) => current ?? "La réponse a été interrompue.");
      } else {
        setStatus("complete");
      }
    }
  }

  async function submitQuestion() {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || streaming || !accessToken) return;

    const controller = new AbortController();
    controllerRef.current = controller;
    receivedTextRef.current = "";
    setStatus("retrieving");
    setError(null);
    setStreamWarning(null);
    setResponse(emptyStreamingResponse(trimmedQuestion));
    try {
      await streamKnowledgeBase(trimmedQuestion, {
        token: accessToken,
        signal: controller.signal,
        onEvent: applyStreamEvent,
        onAuthenticationFailure: signOut,
      });
    } catch (requestError) {
      if (controller.signal.aborted) {
        setStatus("cancelled");
        setStreamWarning("Génération arrêtée. La réponse reçue a été conservée.");
      } else if (requestError instanceof StreamingUnsupportedError) {
        try {
          setResponse(await askKnowledgeBase(trimmedQuestion));
          setStatus("complete");
        } catch (fallbackError) {
          setStatus("failed");
          setError(getApiErrorMessage(fallbackError));
        }
      } else if (
        requestError instanceof ChatStreamRequestError &&
        requestError.authenticationFailure
      ) {
        setStatus("failed");
      } else if (receivedTextRef.current) {
        setStatus("partial");
        setStreamWarning("La connexion a été interrompue. La réponse partielle est conservée.");
      } else {
        setStatus("failed");
        setError("Le service est momentanément indisponible. Réessayez dans un instant.");
      }
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }

  function stopGeneration() {
    controllerRef.current?.abort();
  }

  function clearConversation() {
    controllerRef.current?.abort();
    controllerRef.current = null;
    receivedTextRef.current = "";
    setQuestion("");
    setResponse(null);
    setStatus("idle");
    setError(null);
    setStreamWarning(null);
  }

  const displayName = user?.full_name ?? "Agent";

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
          streamWarning={streamWarning}
          response={response}
          onQuestionChange={setQuestion}
          onSubmit={submitQuestion}
          onCancel={stopGeneration}
          onClear={clearConversation}
        />

        {response && response.sources.length > 0 && <SourceList sources={response.sources} />}
      </section>
    </DashboardShell>
  );
}
