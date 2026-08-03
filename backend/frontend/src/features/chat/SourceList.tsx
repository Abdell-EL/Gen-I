import { ChevronDown, ExternalLink, Eye, FileText } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Card } from "../../components/ui/Card";
import { getApiErrorMessage } from "../../services/apiClient";
import { fetchOriginalDocument } from "../../services/knowledgeDocumentApi";
import type { SourcePreview } from "../../types/backend";
import { buildArticlePath } from "./sourceNavigation";

function formatScore(score: number | null) {
  return score === null ? "Non renseigné" : score.toFixed(3);
}

function sourceKey(source: SourcePreview, index: number) {
  return source.id ?? `${source.rank}-${index}`;
}

function triggerDownload(url: string, filename: string) {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener noreferrer";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export function SourceList({ sources }: { sources: SourcePreview[] }) {
  const [openingSourceKey, setOpeningSourceKey] = useState<string | null>(null);
  const [sourceErrors, setSourceErrors] = useState<Record<string, string>>({});

  async function openOriginalDocument(source: SourcePreview, index: number) {
    const key = sourceKey(source, index);
    setOpeningSourceKey(key);
    setSourceErrors((current) => ({ ...current, [key]: "" }));

    try {
      const { blob, filename } = await fetchOriginalDocument(source);
      const objectUrl = URL.createObjectURL(blob);
      const opened = window.open(objectUrl, "_blank", "noopener,noreferrer");
      if (opened) {
        opened.opener = null;
      } else {
        triggerDownload(objectUrl, filename);
      }
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    } catch (requestError) {
      setSourceErrors((current) => ({
        ...current,
        [key]: getApiErrorMessage(requestError) || "Le document original ne peut pas être ouvert.",
      }));
    } finally {
      setOpeningSourceKey((current) => (current === key ? null : current));
    }
  }

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
          {sources.map((source, index) => {
            const key = sourceKey(source, index);
            const articlePath = buildArticlePath(source);
            const canOpenOriginal = Boolean(source.source_document_id);
            const isOpening = openingSourceKey === key;
            const error = sourceErrors[key];

            return (
              <details
                className="source-card"
                key={key}
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
                    {source.file_name && <span>{source.file_name}</span>}
                  </div>
                  <span className="source-excerpt-label">Extrait</span>
                  <p>{source.text ?? "Aucun extrait disponible."}</p>
                  <div className="source-action-row">
                    <button
                      type="button"
                      className="source-open-link source-open-primary"
                      onClick={() => void openOriginalDocument(source, index)}
                      disabled={!canOpenOriginal || isOpening}
                    >
                      <ExternalLink size={15} />
                      {isOpening ? "Ouverture..." : "Ouvrir le document original"}
                    </button>
                    {articlePath && (
                      <Link className="source-preview-link" to={articlePath}>
                        <Eye size={15} />
                        Aperçu de l’article
                      </Link>
                    )}
                  </div>
                  {!canOpenOriginal && (
                    <span className="source-open-unavailable">Document original indisponible</span>
                  )}
                  {error && <div className="source-open-error" role="alert">{error}</div>}
                </div>
              </details>
            );
          })}
        </div>
      )}
    </Card>
  );
}
