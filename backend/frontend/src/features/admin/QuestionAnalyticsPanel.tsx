import { RefreshCw, RotateCcw } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorState } from "../../components/ui/ErrorState";
import { LoadingState } from "../../components/ui/LoadingState";
import { getAdminErrorMessage, getQuestionAnalytics } from "../../services/adminApi";
import type { EditableUserRole, QuestionAnalyticsFilters } from "../../types/admin";
import { formatAdminDate } from "./adminUtils";

const defaults: QuestionAnalyticsFilters = { limit: 20, minimum_count: 1 };

export function QuestionAnalyticsPanel({ refreshKey }: { refreshKey: number }) {
  const [draft, setDraft] = useState<QuestionAnalyticsFilters>(defaults);
  const [filters, setFilters] = useState<QuestionAnalyticsFilters>(defaults);
  const [data, setData] = useState<Awaited<ReturnType<typeof getQuestionAnalytics>> | null>(null);
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null); const [reload, setReload] = useState(0);
  useEffect(() => { let active = true; const timer = window.setTimeout(() => { setLoading(true); setError(null); void getQuestionAnalytics(filters).then((value) => { if (active) setData(value); }).catch((requestError) => { if (active) setError(getAdminErrorMessage(requestError)); }).finally(() => { if (active) setLoading(false); }); }, 0); return () => { active = false; window.clearTimeout(timer); }; }, [filters, reload, refreshKey]);
  function apply(event: FormEvent) { event.preventDefault(); if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) { setError("La date de début doit précéder la date de fin."); return; } setFilters(draft); }
  function reset() { setDraft(defaults); setFilters(defaults); setError(null); }
  return <section className="admin-data-panel"><div className="admin-panel-heading"><div><span className="section-kicker">Analyse des demandes</span><h2>Questions les plus fréquentes</h2><p>Le regroupement est basé sur le texte normalisé, pas sur le sens.</p></div><Button type="button" variant="secondary" onClick={() => setReload((value) => value + 1)} icon={<RefreshCw size={16} />}>Actualiser</Button></div>
    <form className="admin-filter-bar analytics-filters question-filters" onSubmit={apply}><label>Du<input type="date" value={draft.date_from ?? ""} onChange={(event) => setDraft({ ...draft, date_from: event.target.value || undefined })} /></label><label>Au<input type="date" value={draft.date_to ?? ""} onChange={(event) => setDraft({ ...draft, date_to: event.target.value || undefined })} /></label><label>Utilisateur<input type="number" min="1" placeholder="ID" value={draft.user_id ?? ""} onChange={(event) => setDraft({ ...draft, user_id: event.target.value ? Number(event.target.value) : undefined })} /></label><select value={draft.role ?? ""} onChange={(event) => setDraft({ ...draft, role: (event.target.value || undefined) as EditableUserRole | undefined })}><option value="">Tous les rôles</option><option value="admin">Administrateurs</option><option value="agent">Agents</option></select><label>Minimum<input type="number" min="1" max="100000" value={draft.minimum_count} onChange={(event) => setDraft({ ...draft, minimum_count: Number(event.target.value) })} /></label><label>Limite<select value={draft.limit} onChange={(event) => setDraft({ ...draft, limit: Number(event.target.value) })}><option value="10">10</option><option value="20">20</option><option value="50">50</option><option value="100">100</option></select></label><Button type="submit">Appliquer</Button><Button type="button" variant="ghost" onClick={reset} icon={<RotateCcw size={15} />}>Réinitialiser</Button></form>
    {error && <ErrorState message={error} />}{loading && <LoadingState label="Chargement des questions…" />}{!loading && data?.items.length === 0 && <EmptyState title="Aucune question" description="Aucune question ne correspond à ces filtres." />}{!loading && data && data.items.length > 0 && <div className="admin-table-wrap"><table className="admin-table questions-table"><thead><tr><th>Rang</th><th>Question</th><th>Occurrences</th><th>Utilisateurs uniques</th><th>Dernière occurrence</th><th>Exemple</th></tr></thead><tbody>{data.items.map((item, index) => <tr key={item.normalized_question}><td><span className="rank-number">{index + 1}</span></td><td className="question-cell"><strong title={item.question}>{item.question}</strong>{item.normalized_question !== item.question.toLowerCase() && <small>{item.normalized_question}</small>}</td><td><strong>{item.count}</strong></td><td>{item.unique_users}</td><td>{formatAdminDate(item.last_asked_at)}</td><td>{item.example_user.full_name}<small>#{item.example_user.user_id}</small></td></tr>)}</tbody></table></div>}</section>;
}
