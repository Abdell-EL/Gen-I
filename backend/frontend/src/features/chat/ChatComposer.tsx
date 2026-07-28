import {
  ArrowRight,
  Bot,
  CircleHelp,
  Eraser,
  FileQuestion,
  Paperclip,
  Search,
  Send,
  Sparkles,
} from "lucide-react";
import type { KeyboardEvent } from "react";

import { Button } from "../../components/ui/Button";
import { ErrorState } from "../../components/ui/ErrorState";
import { LoadingState } from "../../components/ui/LoadingState";
import type { ChatResponse } from "../../types/backend";
import { AnswerPanel } from "./AnswerPanel";

const suggestions = [
  {
    question: "Quel code situation utiliser pour une demande d'autorisation voisinage ?",
    icon: CircleHelp,
  },
  {
    question: "Que faire si aucun code situation n'est fourni ?",
    icon: FileQuestion,
  },
  {
    question: "Quel code utiliser pour un problème de regard ?",
    icon: Search,
  },
  {
    question: "Quels sont les délais de traitement standard ?",
    icon: Sparkles,
  },
];

export function ChatComposer({
  question,
  loading,
  error,
  response,
  onQuestionChange,
  onSubmit,
  onClear,
}: {
  question: string;
  loading: boolean;
  error: string | null;
  response: ChatResponse | null;
  onQuestionChange: (value: string) => void;
  onSubmit: () => void;
  onClear: () => void;
}) {
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter") return;
    if (event.shiftKey) return;

    event.preventDefault();
    onSubmit();
  }

  return (
    <div className="agent-assistant-flow">
      <section className="chat-composer" aria-label="Assistant FDE">
        <div className="chat-composer-heading">
          <div className="assistant-orb">
            <Bot size={21} />
          </div>
          <div className="composer-heading-copy">
            <strong>Assistant FDE</strong>
            <p>Interrogez les procédures et référentiels opérationnels.</p>
          </div>
          <span className="composer-status-pill">Opérationnel</span>
          <Button
            type="button"
            variant="ghost"
            className="composer-clear"
            onClick={onClear}
            icon={<Eraser size={16} />}
          >
            Effacer la conversation
          </Button>
        </div>

        <label htmlFor="knowledge-question">POSEZ VOTRE QUESTION</label>
        <div className="composer-field">
          <button
            type="button"
            className="composer-attachment"
            aria-label="Pièce jointe non disponible"
            disabled
          >
            <Paperclip size={17} />
          </button>
          <textarea
            id="knowledge-question"
            value={question}
            onChange={(event) => onQuestionChange(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ex. Quel code utiliser pour une réparation réseau nécessaire ?"
            rows={4}
          />
          <Button
            type="button"
            onClick={onSubmit}
            disabled={loading || !question.trim()}
            icon={<Send size={17} />}
            className="composer-submit"
          >
            {loading ? "Recherche..." : "Envoyer"}
          </Button>
        </div>
        <p className="keyboard-hint">
          Appuyez sur Entrée pour envoyer · Ctrl + K pour rechercher
        </p>

        {error && <ErrorState message={error} />}
        {loading && <LoadingState label="Recherche et génération en cours..." />}
        {!loading && response && <AnswerPanel response={response} />}
      </section>

      <section className="suggested-questions" aria-label="Questions suggérées">
        <div className="suggested-questions-heading">QUESTIONS SUGGÉRÉES</div>
        <div className="suggestion-card-grid">
          {suggestions.map((suggestion) => {
            const Icon = suggestion.icon;

            return (
              <button
                type="button"
                key={suggestion.question}
                onClick={() => onQuestionChange(suggestion.question)}
              >
                <span className="suggestion-icon-tile">
                  <Icon size={17} />
                </span>
                <span>{suggestion.question}</span>
                <ArrowRight size={16} />
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}
