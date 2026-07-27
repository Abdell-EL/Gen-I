import { FileText, ShieldCheck, Sparkles } from "lucide-react";

import type { ChatResponse } from "../../types/backend";

function providerLabel(provider: string | null) {
  if (provider === "ollama") return "Ollama local";
  if (provider === "rule_based_fallback") return "Moteur de secours";
  return provider ?? "Non renseigné";
}

function auditLabel(response: ChatResponse) {
  if (!response.audit) return "Non renseigné";
  if (!response.audit.audit_logged) return "Non journalisé";
  return response.audit.retrieval_id
    ? `#${response.audit.retrieval_id}`
    : "Journalisé";
}

export function ChatMetadata({ response }: { response: ChatResponse }) {
  return (
    <dl className="chat-metadata">
      <div>
        <dt>Confiance</dt>
        <dd className="metadata-confidence">{response.confidence}</dd>
      </div>
      <div>
        <dt><ShieldCheck size={13} /> Audit</dt>
        <dd>{auditLabel(response)}</dd>
      </div>
      <div>
        <dt><Sparkles size={13} /> Moteur</dt>
        <dd>{providerLabel(response.generation_provider)}</dd>
      </div>
      <div>
        <dt>Modèle</dt>
        <dd>{response.generation_model ?? "Règles métier"}</dd>
      </div>
      <div>
        <dt><FileText size={13} /> Sources</dt>
        <dd>{response.sources.length} source{response.sources.length > 1 ? "s" : ""}</dd>
      </div>
    </dl>
  );
}
