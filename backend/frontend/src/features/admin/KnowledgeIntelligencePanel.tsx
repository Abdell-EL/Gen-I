import { BookOpenCheck, FileQuestion, MessageCircleQuestion, Search, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorState } from "../../components/ui/ErrorState";
import { LoadingState } from "../../components/ui/LoadingState";
import {
  getAdminErrorMessage, getArticleAnalytics, getLowConfidence,
  getRetrievalDrillDown, getScoreDistribution, getTrendingQuestions,
  getUnreferencedContent,
} from "../../services/adminApi";
import type {
  ArticleAnalyticsResponse, ArticleFilters, KnowledgeFilters, LowConfidenceResponse,
  ArticleAnalyticsItem,
  RetrievalDrillDown, ScoreDistributionResponse, TrendingQuestionsResponse,
  UnreferencedContentResponse,
} from "../../types/admin";
import { Pagination } from "./AdminCommon";
import { formatAdminDate } from "./adminUtils";
import { knowledgeViewState, scoreBarWidth } from "./knowledgeView";

const initialFilters: KnowledgeFilters = { include_benchmarks: false };
function score(value: number | null) { return value === null ? "—" : value.toFixed(3); }
function searchType(value: string | null) {
  return value === "keyword_search" ? "Mot-clé" : value === "chat" ? "Chat" : value === "search" ? "Recherche" : "—";
}

export function KnowledgeIntelligencePanel() {
  const [filters, setFilters] = useState<KnowledgeFilters>(initialFilters);
  const [draft, setDraft] = useState<KnowledgeFilters>(initialFilters);
  const [trending, setTrending] = useState<TrendingQuestionsResponse | null>(null);
  const [low, setLow] = useState<LowConfidenceResponse | null>(null);
  const [distribution, setDistribution] = useState<ScoreDistributionResponse | null>(null);
  const [articles, setArticles] = useState<ArticleAnalyticsResponse | null>(null);
  const [overviewArticle, setOverviewArticle] = useState<ArticleAnalyticsItem | null>(null);
  const [unreferenced, setUnreferenced] = useState<UnreferencedContentResponse | null>(null);
  const [threshold, setThreshold] = useState(.5);
  const [lowPage, setLowPage] = useState(1);
  const [basis, setBasis] = useState<"top_score" | "all_results">("top_score");
  const [bucket, setBucket] = useState(.1);
  const [articleFilters, setArticleFilters] = useState<ArticleFilters>({ page: 1, page_size: 25, sort_by: "consultation_count", sort_order: "desc" });
  const [articleSearch, setArticleSearch] = useState("");
  const [unrefSearch, setUnrefSearch] = useState("");
  const [unrefPage, setUnrefPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<RetrievalDrillDown | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      setLoading(true); setError(null);
      const shared = { ...filters };
      void Promise.all([
      getTrendingQuestions({ ...shared, limit: 20, previous_period: true }),
      getLowConfidence({ ...shared, threshold, page: lowPage, page_size: 25 }),
      getScoreDistribution({ ...shared, bucket_size: bucket, score_basis: basis }),
      getArticleAnalytics({ ...shared, page: 1, page_size: 1,
                            sort_by: "consultation_count", sort_order: "desc" }),
      getArticleAnalytics({ ...shared, ...articleFilters }),
      getUnreferencedContent({ date_from: filters.date_from, date_to: filters.date_to,
                               search: unrefSearch || undefined, page: unrefPage, page_size: 25 }),
      ]).then(([nextTrending, nextLow, nextDistribution, overviewArticles, nextArticles, nextUnreferenced]) => {
        if (!active) return;
        setTrending(nextTrending); setLow(nextLow); setDistribution(nextDistribution);
        setOverviewArticle(overviewArticles.items[0] ?? null);
        setArticles(nextArticles); setUnreferenced(nextUnreferenced);
      }).catch((requestError) => { if (active) setError(getAdminErrorMessage(requestError)); })
        .finally(() => { if (active) setLoading(false); });
    }, 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [filters, threshold, lowPage, basis, bucket, articleFilters, unrefSearch, unrefPage]);

  function applyShared(event: React.FormEvent) {
    event.preventDefault(); setLowPage(1); setUnrefPage(1); setFilters(draft);
  }
  async function openDetail(retrievalId: number) {
    setDetailLoading(true); setError(null);
    try { setDetail(await getRetrievalDrillDown(retrievalId)); }
    catch (requestError) { setError(getAdminErrorMessage(requestError)); }
    finally { setDetailLoading(false); }
  }
  const overviewState = knowledgeViewState(loading, error,
    (trending?.items.length ?? 0) + (low?.total ?? 0) + (unreferenced?.total ?? 0) + (articles?.total ?? 0));
  const topArticle = overviewArticle;

  return <div className="knowledge-intelligence">
    <section className="admin-data-panel knowledge-overview">
      <div className="admin-panel-heading"><div><span className="section-kicker">Intelligence documentaire</span><h2>Vue d’ensemble connaissance</h2><p>Questions émergentes, signaux de confiance et couverture des contenus persistés.</p></div></div>
      <form className="admin-filter-bar analytics-filters" onSubmit={applyShared}>
        <label>Du<input type="date" value={draft.date_from ?? ""} onChange={(event) => setDraft({ ...draft, date_from: event.target.value || undefined })} /></label>
        <label>Au<input type="date" value={draft.date_to ?? ""} onChange={(event) => setDraft({ ...draft, date_to: event.target.value || undefined })} /></label>
        <label>Type<select value={draft.search_type ?? ""} onChange={(event) => setDraft({ ...draft, search_type: (event.target.value || undefined) as KnowledgeFilters["search_type"] })}><option value="">Tous</option><option value="search">Recherche</option><option value="keyword_search">Mot-clé</option><option value="chat">Chat</option></select></label>
        <label className="admin-check benchmark-toggle"><input type="checkbox" checked={draft.include_benchmarks ?? false} onChange={(event) => setDraft({ ...draft, include_benchmarks: event.target.checked })} />Inclure le trafic benchmark</label>
        <Button type="submit">Appliquer</Button>
      </form>
      {overviewState === "loading" && <LoadingState label="Chargement de l’intelligence connaissance…" />}
      {overviewState === "error" && <ErrorState message={error ?? "Données indisponibles."} />}
      {overviewState === "empty" && <EmptyState title="Aucune donnée" description="Aucune activité ne correspond à la sélection." />}
      {!loading && !error && <div className="knowledge-summary-grid">
        <article><MessageCircleQuestion /><span>Questions tendance</span><strong>{trending?.items.length ?? 0}</strong></article>
        <article><FileQuestion /><span>Faible confiance</span><strong>{low?.total ?? 0}</strong></article>
        <article><BookOpenCheck /><span>Documents non référencés</span><strong>{unreferenced?.total ?? 0}</strong></article>
        <article><Search /><span>Article le plus consulté</span><strong title={topArticle?.article_title ?? ""}>{topArticle?.article_title ?? "Aucun"}</strong><small>{topArticle ? `${topArticle.consultation_count} consultation(s)` : "—"}</small></article>
      </div>}
    </section>

    <Panel title="Questions tendance" description="Regroupement canonique, sans rapprochement sémantique.">
      {!loading && trending?.items.length === 0 && <EmptyState title="Aucune question tendance" description="Essayez une autre période." />}
      {trending && trending.items.length > 0 && <Table headings={["Question", "Actuel", "Précédent", "Évolution", "Utilisateurs", "Dernière demande"]}>{trending.items.map((item) => <tr key={item.normalized_question}><td><strong>{item.question}</strong><small>{item.normalized_question}</small></td><td>{item.current_count}</td><td>{item.previous_count}</td><td className={item.absolute_change >= 0 ? "trend-up" : "trend-down"}>{item.absolute_change > 0 ? "+" : ""}{item.absolute_change} · {item.percentage_change === null ? "N/D" : `${item.percentage_change.toFixed(1)} %`}</td><td>{item.unique_users}</td><td>{formatAdminDate(item.last_asked_at)}</td></tr>)}</Table>}
    </Panel>

    <Panel title="Recherches à faible confiance" description="Cliquez une ligne pour consulter les résultats persistés.">
      <div className="inline-controls"><label>Seuil<input type="number" min="0" max="1" step="0.05" value={threshold} onChange={(event) => { setLowPage(1); setThreshold(Number(event.target.value)); }} /></label></div>
      {!loading && low?.items.length === 0 && <EmptyState title="Aucun signal faible" description="Aucune recherche ne passe sous le seuil." />}
      {low && low.items.length > 0 && <><Table headings={["Question", "Utilisateur", "Type", "Résultats", "Score max", "Motif"]}>{low.items.map((item) => <tr className="clickable-row" key={item.retrieval_id} onClick={() => void openDetail(item.retrieval_id)}><td><strong>{item.query_text}</strong></td><td>{item.user.name}<small>{item.user.email}</small></td><td>{searchType(item.search_type)}</td><td>{item.results_count}</td><td>{score(item.top_score)}</td><td>{item.low_confidence_reason === "zero_results" ? "Aucun résultat" : "Score sous le seuil"}</td></tr>)}</Table><Pagination page={low.page} pages={low.pages} total={low.total} onPageChange={setLowPage} /></>}
    </Panel>

    <Panel title="Distribution des scores" description="Les recherches sans résultat sont exclues du mode score maximal.">
      <div className="inline-controls"><label>Base<select value={basis} onChange={(event) => setBasis(event.target.value as typeof basis)}><option value="top_score">Score maximal</option><option value="all_results">Tous les résultats</option></select></label><label>Taille<select value={bucket} onChange={(event) => setBucket(Number(event.target.value))}><option value="0.05">0.05</option><option value="0.1">0.10</option><option value="0.2">0.20</option></select></label><strong>{distribution?.total ?? 0} score(s)</strong></div>
      {distribution && <div className="score-chart" aria-label="Distribution des scores">{distribution.buckets.map((item) => <div className="score-bar-row" key={item.lower_bound}><span>{item.lower_bound.toFixed(2)}–{item.upper_bound.toFixed(2)}</span><div><i style={{ width: scoreBarWidth(item.percentage) }} /></div><strong>{item.count} <small>{item.percentage.toFixed(1)} %</small></strong></div>)}</div>}
    </Panel>

    <Panel title="Consultations des articles" description="Classement issu des métadonnées de résultats persistées.">
      <form className="inline-controls" onSubmit={(event) => { event.preventDefault(); setArticleFilters({ ...articleFilters, search: articleSearch || undefined, page: 1 }); }}><label className="admin-search-field"><Search size={15} /><input value={articleSearch} onChange={(event) => setArticleSearch(event.target.value)} placeholder="Titre ou code KB" /></label><label>Trier<select value={articleFilters.sort_by} onChange={(event) => setArticleFilters({ ...articleFilters, page: 1, sort_by: event.target.value as ArticleFilters["sort_by"] })}><option value="consultation_count">Consultations</option><option value="unique_users">Utilisateurs</option><option value="last_consulted_at">Dernière consultation</option><option value="article_title">Titre</option></select></label><label>Ordre<select value={articleFilters.sort_order} onChange={(event) => setArticleFilters({ ...articleFilters, page: 1, sort_order: event.target.value as ArticleFilters["sort_order"] })}><option value="desc">Décroissant</option><option value="asc">Croissant</option></select></label><Button type="submit">Rechercher</Button></form>
      {!loading && articles?.items.length === 0 && <EmptyState title="Aucun article" description="Aucune consultation ne correspond aux filtres." />}
      {articles && articles.items.length > 0 && <><Table headings={["Article", "Code KB", "Consultations", "Requêtes", "Utilisateurs", "Score moyen", "Score max", "Dernière consultation"]}>{articles.items.map((item) => <tr key={`${item.article_title}-${item.kb_code}`}><td><strong>{item.article_title ?? "Sans titre"}</strong></td><td>{item.kb_code ?? "—"}</td><td>{item.consultation_count}</td><td>{item.unique_requests}</td><td>{item.unique_users}</td><td>{score(item.average_score)}</td><td>{score(item.top_score)}</td><td>{formatAdminDate(item.last_consulted_at)}</td></tr>)}</Table><Pagination page={articles.page} pages={articles.pages} total={articles.total} onPageChange={(page) => setArticleFilters({ ...articleFilters, page })} /></>}
    </Panel>

    <Panel title="Contenus non référencés sur la période" description="Ces contenus ne sont pas déclarés inutilisés globalement.">
      <form className="inline-controls" onSubmit={(event) => { event.preventDefault(); setUnrefPage(1); setUnrefSearch(unrefSearch.trim()); }}><label className="admin-search-field"><Search size={15} /><input value={unrefSearch} onChange={(event) => setUnrefSearch(event.target.value)} placeholder="Fichier, titre ou code KB" /></label><Button type="submit">Rechercher</Button></form>
      {!loading && unreferenced?.items.length === 0 && <EmptyState title="Tous les contenus sont référencés" description="Aucun document non référencé sur la période sélectionnée." />}
      {unreferenced && unreferenced.items.length > 0 && <><div className="scope-note">Périmètre : non référencé dans la période sélectionnée.</div><Table headings={["Fichier", "Titre", "Code KB", "Chunks actuels", "Créé le", "Périmètre"]}>{unreferenced.items.map((item) => <tr key={item.source_document_id}><td><strong>{item.filename}</strong></td><td>{item.title ?? "—"}</td><td>{item.kb_code ?? "—"}</td><td>{item.current_version_chunk_count}</td><td>{item.created_at ? formatAdminDate(item.created_at) : "—"}</td><td>Dans la période sélectionnée</td></tr>)}</Table><Pagination page={unreferenced.page} pages={unreferenced.pages} total={unreferenced.total} onPageChange={setUnrefPage} /></>}
    </Panel>
    {detailLoading && <div className="knowledge-drawer-backdrop"><aside className="knowledge-drawer"><LoadingState label="Chargement du détail…" /></aside></div>}
    {detail && <RetrievalDrawer detail={detail} onClose={() => setDetail(null)} />}
  </div>;
}

function Panel({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return <section className="admin-data-panel knowledge-panel"><div className="admin-panel-heading"><div><h2>{title}</h2><p>{description}</p></div></div>{children}</section>;
}
function Table({ headings, children }: { headings: string[]; children: React.ReactNode }) {
  return <div className="admin-table-wrap"><table className="admin-table knowledge-table"><thead><tr>{headings.map((heading) => <th key={heading}>{heading}</th>)}</tr></thead><tbody>{children}</tbody></table></div>;
}
function RetrievalDrawer({ detail, onClose }: { detail: RetrievalDrillDown; onClose: () => void }) {
  return <div className="knowledge-drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><aside className="knowledge-drawer" role="dialog" aria-modal="true" aria-label="Détail de récupération"><button className="drawer-close" type="button" onClick={onClose} aria-label="Fermer"><X /></button><span className="section-kicker">Récupération #{detail.retrieval_id}</span><h2>{detail.query_text}</h2><dl><div><dt>Utilisateur</dt><dd>{detail.user.name} · {detail.user.email}</dd></div><div><dt>Type</dt><dd>{searchType(detail.search_type)}</dd></div><div><dt>Créée le</dt><dd>{formatAdminDate(detail.created_at)}</dd></div><div><dt>Session / message</dt><dd>{detail.session_id ?? "—"} / {detail.message_id ?? "—"}</dd></div><div><dt>Résultats</dt><dd>{detail.result_count}</dd></div></dl>{detail.results.length === 0 ? <EmptyState title="Aucun résultat persisté" description="Cette récupération ne contient aucune ligne de résultat." /> : <Table headings={["Rang", "Score", "Chunk", "Article", "KB", "Section", "Type", "Priorité"]}>{detail.results.map((item, index) => <tr key={`${item.rank}-${item.chunk_external_id ?? index}`}><td>{item.rank}</td><td>{score(item.score)}</td><td>{item.chunk_external_id ?? "—"}</td><td>{item.article_title ?? "—"}</td><td>{item.kb_code ?? "—"}</td><td>{item.section_title ?? "—"}</td><td>{item.chunk_type ?? "—"}</td><td>{item.priority ?? "—"}</td></tr>)}</Table>}</aside></div>;
}
