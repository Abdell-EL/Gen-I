import { Check, Copy, Sparkles } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import { Button } from "../../components/ui/Button";
import type { ChatResponse } from "../../types/backend";
import { ChatMetadata } from "./ChatMetadata";

function renderAnswerText(answer: string) {
  const codePattern = /\b(?=[A-Z0-9]*[A-Z])[A-Z0-9]{2,8}\b/g;
  const parts: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = codePattern.exec(answer))) {
    if (match.index > cursor) {
      parts.push(answer.slice(cursor, match.index));
    }

    parts.push(
      <mark className="answer-code-token" key={`${match[0]}-${match.index}`}>
        {match[0]}
      </mark>,
    );
    cursor = match.index + match[0].length;
  }

  if (cursor < answer.length) {
    parts.push(answer.slice(cursor));
  }

  return parts.length > 0 ? parts : answer;
}

export function AnswerPanel({ response }: { response: ChatResponse }) {
  const [copied, setCopied] = useState(false);

  async function copyAnswer() {
    await navigator.clipboard.writeText(response.answer);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  return (
    <section className="answer-panel" aria-label="Réponse générée">
      <div className="answer-panel-heading">
        <span className="section-kicker">
          <Sparkles size={14} />
          RÉPONSE GÉNÉRÉE
        </span>
        <Button
          type="button"
          variant="ghost"
          onClick={copyAnswer}
          icon={copied ? <Check size={16} /> : <Copy size={16} />}
        >
          {copied ? "Copié" : "Copier"}
        </Button>
      </div>

      <div className="answer-copy">{renderAnswerText(response.answer)}</div>

      {response.generation_error && (
        <div className="fallback-warning" role="status">
          <strong>Réponse de secours activée</strong>
          <p>{response.generation_error}</p>
        </div>
      )}

      <ChatMetadata response={response} />
    </section>
  );
}
