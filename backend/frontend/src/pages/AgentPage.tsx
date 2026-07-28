import { Sparkles } from "lucide-react";
import { useState } from "react";

import { useAuth } from "../app/useAuth";
import { AgentSidebar } from "../components/layout/AgentSidebar";
import { DashboardShell } from "../components/layout/DashboardShell";
import { ChatComposer } from "../features/chat/ChatComposer";
import { SourceList } from "../features/chat/SourceList";
import { getApiErrorMessage } from "../services/apiClient";
import { askKnowledgeBase } from "../services/chatApi";
import type { ChatResponse } from "../types/backend";

export function AgentPage() {
  const { user } = useAuth();
  const [question, setQuestion] = useState(
    "Quel code situation utiliser pour une demande d'autorisation voisinage ?",
  );
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submitQuestion() {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || loading) return;

    setLoading(true);
    setError(null);
    try {
      setResponse(await askKnowledgeBase(trimmedQuestion));
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }

  function clearConversation() {
    setQuestion("");
    setResponse(null);
    setError(null);
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
          <span className="agent-greeting-kicker">
            <Sparkles size={16} />
            Assistant opérationnel
          </span>
          <h1>
            Bonjour, <span>{displayName}</span>
          </h1>
          <p>Comment puis-je vous aider aujourd'hui ?</p>
        </div>

        <ChatComposer
          question={question}
          loading={loading}
          error={error}
          response={response}
          onQuestionChange={setQuestion}
          onSubmit={submitQuestion}
          onClear={clearConversation}
        />

        {!loading && response && <SourceList sources={response.sources} />}
      </section>
    </DashboardShell>
  );
}
