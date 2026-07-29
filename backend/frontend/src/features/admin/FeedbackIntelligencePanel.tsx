import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorState } from "../../components/ui/ErrorState";
import { LoadingState } from "../../components/ui/LoadingState";
import { getAdminErrorMessage, getFeedbackDetail, getFeedbackList, getFeedbackSummary } from "../../services/adminApi";
import type { AdminFeedbackItem, FeedbackListResponse, FeedbackSummary } from "../../types/admin";
import { Pagination } from "./AdminCommon";
import { formatAdminDate } from "./adminUtils";

export function FeedbackIntelligencePanel() {
  const [summary, setSummary] = useState<FeedbackSummary | null>(null);
  const [list, setList] = useState<FeedbackListResponse | null>(null);
  const [page, setPage] = useState(1); const [rating, setRating] = useState("");
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminFeedbackItem | null>(null);
  useEffect(() => { let active = true; const timer = window.setTimeout(() => {
    setLoading(true); setError(null); const params = { page, page_size: 25, rating: rating || undefined };
    void Promise.all([getFeedbackSummary(params), getFeedbackList(params)]).then(([a, b]) => {
      if (active) { setSummary(a); setList(b); }
    }).catch((e) => { if (active) setError(getAdminErrorMessage(e)); })
      .finally(() => { if (active) setLoading(false); });
  }, 0); return () => { active = false; window.clearTimeout(timer); }; }, [page, rating]);
  async function open(id: number) { try { setDetail(await getFeedbackDetail(id)); }
    catch (e) { setError(getAdminErrorMessage(e)); } }
  if (loading) return <LoadingState label="Chargement des retours…" />;
  if (error) return <ErrorState message={error} />;
  return <div className="knowledge-intelligence"><section className="admin-data-panel knowledge-overview"><div className="admin-panel-heading"><div><span className="section-kicker">Qualité des réponses</span><h2>Intelligence feedback</h2><p>Retours structurés des utilisateurs authentifiés.</p></div></div><div className="knowledge-summary-grid"><article><span>Total</span><strong>{summary?.total_feedback ?? 0}</strong></article><article><span>Utile</span><strong>{(summary?.helpful_percentage ?? 0).toFixed(1)} %</strong></article><article><span>Négatif</span><strong>{(summary?.negative_percentage ?? 0).toFixed(1)} %</strong></article><article><span>Contributeurs</span><strong>{summary?.feedback_unique_users ?? 0}</strong></article><article><span>Motif principal</span><strong>{summary?.most_common_negative_reason ?? "—"}</strong></article><article><span>Article affecté</span><strong>{summary?.most_affected_article?.article_title ?? "—"}</strong></article></div>{summary?.trend && <div className="feedback-trend"><span>Période précédente</span><div><i style={{ width: `${Math.min(100, summary.trend.previous_total ? summary.trend.current_total / summary.trend.previous_total * 50 : 100)}%` }} /></div><strong>{summary.trend.absolute_change > 0 ? "+" : ""}{summary.trend.absolute_change}</strong></div>}</section><section className="admin-data-panel knowledge-panel"><div className="admin-panel-heading"><div><h2>Retours récents</h2><p>Ouvrez une ligne pour examiner la réponse et ses sources.</p></div></div><div className="inline-controls"><label>Évaluation<select value={rating} onChange={(e) => { setPage(1); setRating(e.target.value); }}><option value="">Toutes</option><option value="helpful">Utile</option><option value="partially_helpful">Partiellement utile</option><option value="not_helpful">Pas utile</option></select></label></div>{list?.items.length === 0 ? <EmptyState title="Aucun retour" description="Aucun feedback ne correspond aux filtres." /> : <><div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Date</th><th>Utilisateur</th><th>Évaluation</th><th>Motif</th><th>Question</th><th>Article</th></tr></thead><tbody>{list?.items.map((item) => <tr className="clickable-row" key={item.feedback_id} onClick={() => void open(item.feedback_id)}><td>{formatAdminDate(item.created_at)}</td><td>{item.user.full_name}</td><td><span className={`feedback-badge ${item.rating}`}>{item.rating}</span></td><td>{item.reason ?? "—"}</td><td>{item.question ?? "—"}</td><td>{item.referenced_articles[0]?.article_title ?? "—"}</td></tr>)}</tbody></table></div>{list && <Pagination page={list.page} pages={list.pages} total={list.total} onPageChange={setPage} />}</>}</section>{detail && <div className="knowledge-drawer-backdrop"><aside className="knowledge-drawer"><button className="drawer-close" onClick={() => setDetail(null)}><X /></button><span className="section-kicker">Feedback #{detail.feedback_id}</span><h2>{detail.question}</h2><p>{detail.answer}</p><dl><div><dt>Utilisateur</dt><dd>{detail.user.full_name} · {detail.user.email}</dd></div><div><dt>Évaluation</dt><dd>{detail.rating}</dd></div><div><dt>Motif</dt><dd>{detail.reason ?? "—"}</dd></div><div><dt>Commentaire</dt><dd>{detail.comment ?? "—"}</dd></div><div><dt>Session / message / retrieval</dt><dd>{detail.session_id} / {detail.message_id} / {detail.retrieval_id ?? "—"}</dd></div></dl><div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Rang</th><th>Score</th><th>Chunk</th><th>Article</th><th>KB</th><th>Section</th></tr></thead><tbody>{detail.results?.map((source, index) => <tr key={`${source.rank}-${index}`}><td>{source.rank}</td><td>{source.score.toFixed(3)}</td><td>{source.chunk_external_id ?? "—"}</td><td>{source.article_title ?? "—"}</td><td>{source.kb_code ?? "—"}</td><td>{source.section_title ?? "—"}</td></tr>)}</tbody></table></div></aside></div>}</div>;
}
