import { ChevronRight, Search, X } from "lucide-react";

import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { LoadingState } from "../../components/ui/LoadingState";
import type {
  AuditDetailResponse,
  AuditSummary,
} from "../../types/backend";

function formatScore(score?: number) {
  return score === undefined || score === null ? "—" : score.toFixed(3);
}

function formatDate(value?: string) {
  if (!value) return "Date inconnue";
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function AuditList({
  audits,
  detail,
  detailLoading,
  onSelect,
  onCloseDetail,
}: {
  audits: AuditSummary[];
  detail: AuditDetailResponse | null;
  detailLoading: boolean;
  onSelect: (retrievalId: number) => void;
  onCloseDetail: () => void;
}) {
  if (audits.length === 0) {
    return (
      <EmptyState
        icon={<Search size={22} />}
        title="Aucun audit disponible"
        description="Les nouvelles recherches apparaîtront ici dès leur journalisation."
      />
    );
  }

  return (
    <div className="audit-layout">
      <Card className="audit-table-card">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">Journal de recherche</span>
            <h2>Dernières récupérations</h2>
          </div>
          <span className="source-count">{audits.length}</span>
        </div>
        <div className="audit-table" role="table">
          {audits.map((audit) => (
            <button
              type="button"
              className="audit-table-row"
              key={audit.retrieval_id}
              onClick={() =>
                audit.retrieval_id && onSelect(audit.retrieval_id)
              }
              role="row"
            >
              <span className="audit-id">#{audit.retrieval_id ?? "—"}</span>
              <span className="audit-query">
                <strong>{audit.query_text ?? "Requête sans libellé"}</strong>
                <small>{formatDate(audit.created_at)}</small>
              </span>
              <span className="audit-metric">
                <strong>{audit.results_count ?? "—"}</strong>
                <small>résultats</small>
              </span>
              <span className="audit-metric">
                <strong>{formatScore(audit.top_score)}</strong>
                <small>meilleur score</small>
              </span>
              <ChevronRight size={18} />
            </button>
          ))}
        </div>
      </Card>

      {(detailLoading || detail) && (
        <Card className="audit-detail">
          {detailLoading ? (
            <LoadingState label="Chargement du détail…" />
          ) : (
            detail && (
              <>
                <div className="panel-heading">
                  <div>
                    <span className="section-kicker">
                      Audit #{detail.retrieval.retrieval_id}
                    </span>
                    <h2>Détail de la récupération</h2>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    icon={<X size={16} />}
                    onClick={onCloseDetail}
                  >
                    Fermer
                  </Button>
                </div>
                <dl className="metric-list">
                  <div>
                    <dt>Question</dt>
                    <dd>{detail.retrieval.query_text ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>Modèle d’embedding</dt>
                    <dd>{detail.retrieval.embedding_model ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>Collection</dt>
                    <dd>{detail.retrieval.milvus_collection ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>Résultats journalisés</dt>
                    <dd>{detail.results_count}</dd>
                  </div>
                </dl>
                <div className="audit-detail-results">
                  {detail.results.slice(0, 5).map((result, index) => (
                    <div key={result.chunk_id ?? index}>
                      <span>#{result.rank ?? index + 1}</span>
                      <p>{result.chunk_text ?? "Extrait indisponible"}</p>
                    </div>
                  ))}
                </div>
              </>
            )
          )}
        </Card>
      )}
    </div>
  );
}
