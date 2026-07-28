import { RefreshCw, RotateCcw } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorState } from "../../components/ui/ErrorState";
import { LoadingState } from "../../components/ui/LoadingState";
import { getAdminErrorMessage, getUserAnalytics } from "../../services/adminApi";
import type { EditableUserRole, UserActivityFilters } from "../../types/admin";
import { Pagination, RolePill, StatusPill } from "./AdminCommon";
import { formatAdminDate } from "./adminUtils";

const defaults: UserActivityFilters = { page: 1, page_size: 25 };

export function UserActivityPanel({ refreshKey }: { refreshKey: number }) {
  const [draft, setDraft] = useState<UserActivityFilters>(defaults);
  const [filters, setFilters] = useState<UserActivityFilters>(defaults);
  const [data, setData] = useState<Awaited<ReturnType<typeof getUserAnalytics>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true; const timer = window.setTimeout(() => { setLoading(true); setError(null);
    void getUserAnalytics(filters).then((value) => { if (active) setData(value); }).catch((requestError) => { if (active) setError(getAdminErrorMessage(requestError)); }).finally(() => { if (active) setLoading(false); }); }, 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [filters, reload, refreshKey]);

  function apply(event: FormEvent) {
    event.preventDefault();
    if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) { setError("La date de début doit précéder la date de fin."); return; }
    setFilters({ ...draft, page: 1 });
  }
  function reset() { setDraft(defaults); setFilters(defaults); setError(null); }

  return <section className="admin-data-panel"><div className="admin-panel-heading"><div><span className="section-kicker">Analyse d’usage</span><h2>Utilisateurs les plus actifs</h2><p>Classement par nombre de questions, incluant les comptes sans activité.</p></div><Button type="button" variant="secondary" onClick={() => setReload((value) => value + 1)} icon={<RefreshCw size={16} />}>Actualiser</Button></div>
    <form className="admin-filter-bar analytics-filters" onSubmit={apply}><label>Du<input type="date" value={draft.date_from ?? ""} onChange={(event) => setDraft({ ...draft, date_from: event.target.value || undefined })} /></label><label>Au<input type="date" value={draft.date_to ?? ""} onChange={(event) => setDraft({ ...draft, date_to: event.target.value || undefined })} /></label><select value={draft.role ?? ""} onChange={(event) => setDraft({ ...draft, role: (event.target.value || undefined) as EditableUserRole | undefined })}><option value="">Tous les rôles</option><option value="admin">Administrateurs</option><option value="agent">Agents</option></select><select value={draft.is_active === undefined ? "" : String(draft.is_active)} onChange={(event) => setDraft({ ...draft, is_active: event.target.value === "" ? undefined : event.target.value === "true" })}><option value="">Tous les statuts</option><option value="true">Actifs</option><option value="false">Inactifs</option></select><select value={draft.page_size} onChange={(event) => setDraft({ ...draft, page_size: Number(event.target.value) })}><option value="10">10 / page</option><option value="25">25 / page</option><option value="50">50 / page</option><option value="100">100 / page</option></select><Button type="submit">Appliquer</Button><Button type="button" variant="ghost" onClick={reset} icon={<RotateCcw size={15} />}>Réinitialiser</Button></form>
    {error && <ErrorState message={error} />}{loading && <LoadingState label="Chargement de l’activité…" />}{!loading && data?.items.length === 0 && <EmptyState title="Aucune donnée" description="Aucun utilisateur ne correspond à ces filtres." />}{!loading && data && data.items.length > 0 && <><div className="admin-table-wrap"><table className="admin-table ranked-table"><thead><tr><th>Rang</th><th>Nom</th><th>Email</th><th>Rôle</th><th>Statut</th><th>Questions</th><th>Dernière question</th></tr></thead><tbody>{data.items.map((item, index) => <tr key={item.user_id}><td><span className="rank-number">{(data.page - 1) * data.page_size + index + 1}</span></td><td><strong>{item.full_name}</strong></td><td>{item.email}</td><td><RolePill role={item.role} /></td><td><StatusPill active={item.is_active} /></td><td><strong>{item.questions_count}</strong></td><td>{item.last_question_at ? formatAdminDate(item.last_question_at) : "Aucune question"}</td></tr>)}</tbody></table></div><Pagination page={data.page} pages={data.pages} total={data.total} onPageChange={(page) => setFilters((current) => ({ ...current, page }))} /></>}</section>;
}
