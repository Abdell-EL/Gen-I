import { ArrowLeft, FileText } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { useAuth } from "../app/useAuth";
import { AgentSidebar } from "../components/layout/AgentSidebar";
import { DashboardShell } from "../components/layout/DashboardShell";
import { Badge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { LoadingState } from "../components/ui/LoadingState";
import { getApiErrorMessage } from "../services/apiClient";
import { getKnowledgeArticle } from "../services/knowledgeArticleApi";
import type { KnowledgeArticleResponse } from "../types/backend";

function splitParagraphs(content: string) {
  return content.split(/\n{2,}/).map((value) => value.trim()).filter(Boolean);
}

export function ArticlePage() {
  const { user } = useAuth();
  const { sourceDocumentId } = useParams();
  const [searchParams] = useSearchParams();
  const [articleState, setArticleState] = useState<{
    key: string;
    article: KnowledgeArticleResponse | null;
    error: string | null;
  }>({ key: "", article: null, error: null });
  const highlightedRef = useRef<HTMLElement | null>(null);

  const documentId = Number(sourceDocumentId);
  const versionId = Number(searchParams.get("version_id") || 0) || null;
  const chunkId = Number(searchParams.get("chunk_id") || 0) || null;
  const displayName = user?.full_name ?? "Agent";
  const invalidDocument = !Number.isInteger(documentId) || documentId <= 0;
  const requestKey = `${documentId}:${versionId ?? ""}:${chunkId ?? ""}`;

  useEffect(() => {
    let active = true;
    if (invalidDocument) return () => { active = false; };

    void getKnowledgeArticle(documentId, { versionId, chunkId })
      .then((value) => {
        if (active) setArticleState({ key: requestKey, article: value, error: null });
      })
      .catch((requestError) => {
        if (active) {
          setArticleState({ key: requestKey, article: null, error: getApiErrorMessage(requestError) });
        }
      });

    return () => { active = false; };
  }, [documentId, versionId, chunkId, invalidDocument, requestKey]);

  const loading = !invalidDocument && articleState.key !== requestKey;
  const error = invalidDocument ? "Article introuvable." : (!loading ? articleState.error : null);
  const article = !loading && !invalidDocument ? articleState.article : null;

  useEffect(() => {
    if (!article || !highlightedRef.current) return;
    highlightedRef.current.scrollIntoView({ block: "center" });
  }, [article]);

  const hasContent = useMemo(() => {
    if (!article) return false;
    return article.sections.some((section) => section.content.trim()) || article.content.trim().length > 0;
  }, [article]);

  return (
    <DashboardShell
      sidebar={<AgentSidebar />}
      className="agent-console"
      consoleLabel="Espace Agent"
      searchLabel="Rechercher..."
      searchShortcut="Ctrl K"
      eyebrow="Article"
      title="Source de connaissance"
      description="Consultation authentifiée de l’article cité."
      showNotifications
      userDisplayName={displayName}
    >
      <section className="article-detail-page" aria-label="Article de connaissance">
        <div className="article-detail-toolbar">
          <Link className="button button-ghost article-back-link" to="/agent">
            <ArrowLeft size={16} />
            <span>Retour au chat</span>
          </Link>
        </div>

        {loading && <LoadingState label="Chargement de l’article..." />}
        {!loading && error && <ErrorState message={error} />}
        {!loading && article && !hasContent && (
          <EmptyState
            icon={<FileText size={20} />}
            title="Article vide"
            description="Aucun contenu lisible n’est disponible pour cette version."
          />
        )}

        {!loading && article && hasContent && (
          <Card className="article-detail-card">
            <div className="article-detail-heading">
              <span className="section-kicker"><FileText size={14} />ARTICLE SOURCE</span>
              <h1>{article.title}</h1>
              <div className="article-detail-meta">
                {article.kb_code && <Badge>{article.kb_code}</Badge>}
                <span>{article.filename}</span>
                <span>Version {article.version_number}</span>
                {!article.is_current_version && <span>Version citée archivée</span>}
              </div>
            </div>

            <div className="article-section-list">
              {article.sections.map((section, index) => {
                const highlighted = Boolean(
                  article.requested_chunk && section.chunk_ids.includes(article.requested_chunk.chunk_id),
                );
                return (
                  <section
                    className={`article-section ${highlighted ? "is-highlighted" : ""}`}
                    key={`${section.title}-${index}`}
                    ref={highlighted ? highlightedRef : undefined}
                  >
                    <h2>{section.title}</h2>
                    {splitParagraphs(section.content).map((paragraph, paragraphIndex) => (
                      <p key={paragraphIndex}>{paragraph}</p>
                    ))}
                  </section>
                );
              })}
            </div>
          </Card>
        )}
      </section>
    </DashboardShell>
  );
}
