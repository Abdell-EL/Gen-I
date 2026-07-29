import { Check, Copy, Sparkles, ThumbsDown, ThumbsUp, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { Button } from "../../components/ui/Button";
import type { ChatResponse, ChatStreamStatus } from "../../types/backend";
import { ChatMetadata } from "./ChatMetadata";
import { deleteAnswerFeedback, getAnswerFeedback, submitAnswerFeedback,
  type AnswerFeedback, type FeedbackRating, type FeedbackReason } from "../../services/feedbackApi";
import { getApiErrorMessage } from "../../services/apiClient";

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

export function AnswerPanel({
  response,
  status = "complete",
  streamWarning = null,
}: {
  response: ChatResponse;
  status?: ChatStreamStatus;
  streamWarning?: string | null;
}) {
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState<AnswerFeedback | null>(null);
  const [rating, setRating] = useState<FeedbackRating | null>(null);
  const [reason, setReason] = useState<FeedbackReason | "">("");
  const [comment, setComment] = useState("");
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const messageId = response.audit?.message_id ?? null;
  const canFeedback = Boolean(messageId) && (status === "complete" || status === "partial" || status === "cancelled");

  useEffect(() => {
    let active = true;
    if (!messageId || !canFeedback) return () => { active = false; };
    void getAnswerFeedback(messageId).then((value) => {
      if (!active) return; setFeedback(value); setRating(value.rating);
      setReason(value.reason ?? ""); setComment(value.comment ?? "");
    }).catch(() => undefined);
    return () => { active = false; };
  }, [messageId, canFeedback]);

  async function saveFeedback(nextRating = rating) {
    if (!messageId || !nextRating) return;
    if (nextRating !== "helpful" && !reason) { setFeedbackError("Choisissez une raison."); return; }
    if (reason === "other" && !comment.trim()) { setFeedbackError("Ajoutez un commentaire pour la raison « Autre »."); return; }
    setFeedbackError(null);
    try {
      const value = await submitAnswerFeedback(messageId, {
        rating: nextRating, reason: nextRating === "helpful" ? undefined : reason || undefined,
        comment: comment.trim() || undefined,
      });
      setFeedback(value); setRating(value.rating); setSaved(true);
      window.setTimeout(() => setSaved(false), 1800);
    } catch (requestError) { setFeedbackError(getApiErrorMessage(requestError)); }
  }

  async function removeFeedback() {
    if (!messageId || !window.confirm("Supprimer votre évaluation ?")) return;
    try { await deleteAnswerFeedback(messageId); setFeedback(null); setRating(null); setReason(""); setComment(""); }
    catch (requestError) { setFeedbackError(getApiErrorMessage(requestError)); }
  }

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

      <div className={`answer-copy ${status === "generating" ? "is-streaming" : ""}`}>
        {response.answer ? renderAnswerText(response.answer) : (
          <span className="answer-awaiting">Préparation de la réponse…</span>
        )}
      </div>

      {streamWarning && (
        <div className="stream-warning" role="status">
          {streamWarning}
        </div>
      )}

      {response.generation_error && (
        <div className="fallback-warning" role="status">
          <strong>Réponse de secours activée</strong>
          <p>{response.generation_error}</p>
        </div>
      )}

      {(response.confidence || response.audit) && <ChatMetadata response={response} />}
      {canFeedback && <div className="answer-feedback"><div className="answer-feedback-heading"><strong>Cette réponse vous a-t-elle aidé ?</strong>{saved && <span>Enregistré</span>}</div><div className="feedback-rating-buttons"><button type="button" className={rating === "helpful" ? "active" : ""} onClick={() => { setRating("helpful"); setReason(""); void saveFeedback("helpful"); }}><ThumbsUp size={15} />Utile</button><button type="button" className={rating === "partially_helpful" ? "active" : ""} onClick={() => setRating("partially_helpful")}>Partiellement utile</button><button type="button" className={rating === "not_helpful" ? "active" : ""} onClick={() => setRating("not_helpful")}><ThumbsDown size={15} />Pas utile</button>{feedback && <button type="button" className="feedback-delete" onClick={() => void removeFeedback()}><Trash2 size={14} />Supprimer</button>}</div>{rating && rating !== "helpful" && <div className="feedback-form"><label>Raison<select value={reason} onChange={(event) => setReason(event.target.value as FeedbackReason | "")}><option value="">Choisir…</option><option value="incorrect_answer">Réponse incorrecte</option><option value="incomplete_answer">Réponse incomplète</option><option value="irrelevant_sources">Sources non pertinentes</option><option value="missing_information">Information manquante</option><option value="unclear_answer">Réponse peu claire</option><option value="outdated_information">Information obsolète</option><option value="other">Autre</option></select></label><label>Commentaire {reason === "other" ? "(requis)" : "(optionnel)"}<textarea maxLength={1000} value={comment} onChange={(event) => setComment(event.target.value)} /></label><div><Button type="button" onClick={() => void saveFeedback()}>Envoyer</Button><Button type="button" variant="ghost" onClick={() => { setRating(feedback?.rating ?? null); setReason(feedback?.reason ?? ""); }}>Annuler</Button></div></div>}{feedbackError && <p className="feedback-error" role="alert">{feedbackError}</p>}</div>}
    </section>
  );
}
