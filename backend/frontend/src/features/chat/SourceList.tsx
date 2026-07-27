import { ChevronDown, FileText } from "lucide-react";

import { Card } from "../../components/ui/Card";
import type { SourcePreview } from "../../types/backend";

function formatScore(score: number | null) {
  return score === null ? "Non renseigné" : score.toFixed(3);
}

export function SourceList({ sources }: { sources: SourcePreview[] }) {
  return (
    <Card className="source-panel sources-used-section">
      <div className="source-panel-heading">
        <div>
          <span className="section-kicker">
            <FileText size={14} />
            SOURCES UTILISÉES
          </span>
          <h2>Références de connaissance</h2>
        </div>
        <span className="source-count">
          {sources.length} source{sources.length > 1 ? "s" : ""}
        </span>
      </div>

      {sources.length === 0 ? (
        <div className="source-empty">
          <FileText size={18} />
          <strong>Aucune source retournée</strong>
          <p>La réponse ne contient pas de références exploitables.</p>
        </div>
      ) : (
        <div className="source-list">
          {sources.map((source, index) => (
            <details
              className="source-card"
              key={source.id ?? `${source.rank}-${index}`}
            >
              <summary>
                <span className="source-rank">{source.rank ?? index + 1}</span>
                <span className="source-summary-copy">
                  <strong>{source.article_title ?? "Source sans titre"}</strong>
                  <small>
                    <span>{source.kb_code ?? "Base FDE"}</span>
                    <span>{source.section_title ?? "Section"}</span>
                  </small>
                </span>
                <span className="source-score">
                  Score <strong>{formatScore(source.score)}</strong>
                </span>
                <ChevronDown size={17} />
              </summary>
              <div className="source-details">
                <div className="source-tags">
                  <span>{source.chunk_type ?? "Type inconnu"}</span>
                  {source.priority && <span>Priorité {source.priority}</span>}
                </div>
                <span className="source-excerpt-label">Extrait</span>
                <p>{source.text ?? "Aucun extrait disponible."}</p>
              </div>
            </details>
          ))}
        </div>
      )}
    </Card>
  );
}
