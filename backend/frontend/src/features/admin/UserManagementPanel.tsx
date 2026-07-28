import { KeyRound, Pencil, Plus, RefreshCw, Search, UserCheck, UserX } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { useAuth } from "../../app/useAuth";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorState } from "../../components/ui/ErrorState";
import { LoadingState } from "../../components/ui/LoadingState";
import {
  createUser,
  getAdminErrorMessage,
  getUser,
  listUsers,
  resetUserPassword,
  updateUser,
} from "../../services/adminApi";
import type { AdminUser, CreateUserPayload, EditableUserRole, UpdateUserPayload, UserListFilters } from "../../types/admin";
import { AdminDialog, Pagination, RolePill, StatusPill } from "./AdminCommon";
import { formatAdminDate, isEditableRole } from "./adminUtils";

const initialCreate: CreateUserPayload = {
  full_name: "",
  email: "",
  password: "",
  role: "agent",
  department_id: null,
  is_active: true,
};

export function UserManagementPanel({ onDataChanged }: { onDataChanged: () => void }) {
  const { user: currentUser } = useAuth();
  const [data, setData] = useState<Awaited<ReturnType<typeof listUsers>> | null>(null);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [filters, setFilters] = useState<UserListFilters>({ page: 1, page_size: 25, sort_by: "created_at", sort_order: "desc" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [editUser, setEditUser] = useState<AdminUser | null>(null);
  const [resetUser, setResetUser] = useState<AdminUser | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(search.trim());
      setFilters((current) => ({ ...current, page: 1 }));
    }, 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const requestFilters = useMemo(() => ({ ...filters, search: debouncedSearch || undefined }), [filters, debouncedSearch]);

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
    setLoading(true);
    setError(null);
    void listUsers(requestFilters)
      .then((response) => { if (active) setData(response); })
      .catch((requestError) => { if (active) setError(getAdminErrorMessage(requestError)); })
      .finally(() => { if (active) setLoading(false); });
    }, 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [requestFilters, refreshKey]);

  const refresh = useCallback(() => setRefreshKey((value) => value + 1), []);
  function mutationSucceeded(message: string) {
    setSuccess(message);
    refresh();
    onDataChanged();
  }

  async function openEdit(userId: number) {
    setError(null);
    try { setEditUser(await getUser(userId)); }
    catch (requestError) { setError(getAdminErrorMessage(requestError)); }
  }

  async function toggleActive(target: AdminUser) {
    if (target.is_active && !window.confirm(`Désactiver le compte de ${target.full_name} ?`)) return;
    setError(null);
    try {
      await updateUser(target.id, { is_active: !target.is_active });
      mutationSucceeded(target.is_active ? "Compte désactivé." : "Compte activé.");
    } catch (requestError) { setError(getAdminErrorMessage(requestError)); }
  }

  return (
    <section className="admin-data-panel">
      <div className="admin-panel-heading">
        <div><span className="section-kicker">Gestion des accès</span><h2>Utilisateurs</h2><p>Créez et administrez les comptes autorisés à utiliser la plateforme.</p></div>
        <div><Button type="button" variant="secondary" onClick={refresh} icon={<RefreshCw size={16} />}>Actualiser</Button><Button type="button" onClick={() => setCreateOpen(true)} icon={<Plus size={16} />}>Nouvel utilisateur</Button></div>
      </div>
      {success && <div className="admin-success" role="status">{success}<button type="button" onClick={() => setSuccess(null)}>×</button></div>}
      {error && <ErrorState message={error} />}
      <div className="admin-filter-bar">
        <label className="admin-search-field"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Rechercher un nom ou un email" aria-label="Rechercher un utilisateur" /></label>
        <select value={filters.role ?? ""} onChange={(event) => setFilters((current) => ({ ...current, page: 1, role: (event.target.value || undefined) as EditableUserRole | undefined }))} aria-label="Filtrer par rôle"><option value="">Tous les rôles</option><option value="admin">Administrateurs</option><option value="agent">Agents</option></select>
        <select value={filters.is_active === undefined ? "" : String(filters.is_active)} onChange={(event) => setFilters((current) => ({ ...current, page: 1, is_active: event.target.value === "" ? undefined : event.target.value === "true" }))} aria-label="Filtrer par statut"><option value="">Tous les statuts</option><option value="true">Actifs</option><option value="false">Inactifs</option></select>
        <select value={`${filters.sort_by}:${filters.sort_order}`} onChange={(event) => { const [sort_by, sort_order] = event.target.value.split(":") as [UserListFilters["sort_by"], UserListFilters["sort_order"]]; setFilters((current) => ({ ...current, page: 1, sort_by, sort_order })); }} aria-label="Trier les utilisateurs"><option value="created_at:desc">Plus récents</option><option value="created_at:asc">Plus anciens</option><option value="full_name:asc">Nom A–Z</option><option value="email:asc">Email A–Z</option><option value="role:asc">Rôle A–Z</option></select>
        <select value={filters.page_size} onChange={(event) => setFilters((current) => ({ ...current, page: 1, page_size: Number(event.target.value) }))} aria-label="Résultats par page"><option value="10">10 / page</option><option value="25">25 / page</option><option value="50">50 / page</option><option value="100">100 / page</option></select>
      </div>
      {loading && <LoadingState label="Chargement des utilisateurs…" />}
      {!loading && data && data.items.length === 0 && <EmptyState title="Aucun utilisateur" description="Aucun compte ne correspond aux filtres sélectionnés." />}
      {!loading && data && data.items.length > 0 && <>
        <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Nom</th><th>Email</th><th>Rôle</th><th>Statut</th><th>Département</th><th>Créé le</th><th>Actions</th></tr></thead><tbody>{data.items.map((item) => <tr key={item.id}><td><strong>{item.full_name}</strong></td><td>{item.email}</td><td><RolePill role={item.role} /></td><td><StatusPill active={item.is_active} /></td><td>{item.department_id ?? "—"}</td><td>{formatAdminDate(item.created_at)}</td><td><div className="admin-row-actions"><button type="button" onClick={() => void openEdit(item.id)} title="Modifier" aria-label={`Modifier ${item.full_name}`}><Pencil size={15} /></button><button type="button" onClick={() => setResetUser(item)} title="Réinitialiser le mot de passe" aria-label={`Réinitialiser le mot de passe de ${item.full_name}`}><KeyRound size={15} /></button><button type="button" disabled={item.id === currentUser?.id && item.is_active} onClick={() => void toggleActive(item)} title={item.is_active ? "Désactiver" : "Activer"} aria-label={`${item.is_active ? "Désactiver" : "Activer"} ${item.full_name}`}>{item.is_active ? <UserX size={15} /> : <UserCheck size={15} />}</button></div></td></tr>)}</tbody></table></div>
        <Pagination page={data.page} pages={data.pages} total={data.total} onPageChange={(page) => setFilters((current) => ({ ...current, page }))} />
      </>}
      {createOpen && <CreateUserDialog onClose={() => setCreateOpen(false)} onSuccess={() => { setCreateOpen(false); mutationSucceeded("Utilisateur créé avec succès."); }} />}
      {editUser && <EditUserDialog user={editUser} onClose={() => setEditUser(null)} onSuccess={() => { setEditUser(null); mutationSucceeded("Utilisateur mis à jour."); }} />}
      {resetUser && <ResetPasswordDialog user={resetUser} onClose={() => setResetUser(null)} onSuccess={() => { setResetUser(null); mutationSucceeded("Mot de passe réinitialisé."); }} />}
    </section>
  );
}

function CreateUserDialog({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [form, setForm] = useState(initialCreate);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (submitting) return; setSubmitting(true); setError(null);
    try { await createUser(form); setForm(initialCreate); onSuccess(); }
    catch (requestError) { setError(getAdminErrorMessage(requestError)); }
    finally { setSubmitting(false); }
  }
  return <AdminDialog title="Créer un utilisateur" description="Le mot de passe initial ne sera jamais réaffiché." onClose={onClose}><form className="admin-form" onSubmit={submit}><FormFields form={form} setForm={setForm} includePassword />{error && <ErrorState message={error} />}<div className="admin-dialog-actions"><Button type="button" variant="ghost" onClick={onClose}>Annuler</Button><Button type="submit" disabled={submitting}>{submitting ? "Création…" : "Créer le compte"}</Button></div></form></AdminDialog>;
}

function FormFields({ form, setForm, includePassword = false, legacyRole, roleDisabled = false }: { form: CreateUserPayload; setForm: (form: CreateUserPayload) => void; includePassword?: boolean; legacyRole?: string; roleDisabled?: boolean }) {
  return <div className="admin-form-grid"><label>Nom complet<input required value={form.full_name} onChange={(event) => setForm({ ...form, full_name: event.target.value })} autoComplete="name" /></label><label>Adresse email<input required type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} autoComplete="email" /></label>{includePassword && <label className="admin-form-full">Mot de passe initial<input required type="password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} autoComplete="new-password" /></label>}<label>Rôle<select disabled={roleDisabled} value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value as EditableUserRole })}><option value="agent">Agent</option><option value="admin">Administrateur</option></select>{legacyRole && <small>Rôle actuel historique : {legacyRole}. Choisissez un rôle pris en charge pour le remplacer.</small>}</label><label>Département (optionnel)<input type="number" min="1" value={form.department_id ?? ""} onChange={(event) => setForm({ ...form, department_id: event.target.value ? Number(event.target.value) : null })} /></label><label className="admin-check admin-form-full"><input type="checkbox" checked={form.is_active} onChange={(event) => setForm({ ...form, is_active: event.target.checked })} />Compte actif</label></div>;
}

function EditUserDialog({ user, onClose, onSuccess }: { user: AdminUser; onClose: () => void; onSuccess: () => void }) {
  const legacy = !isEditableRole(user.role);
  const [form, setForm] = useState<CreateUserPayload>({ full_name: user.full_name, email: user.email, password: "", role: isEditableRole(user.role) ? user.role : "agent", department_id: user.department_id, is_active: user.is_active });
  const [replaceLegacyRole, setReplaceLegacyRole] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (submitting) return;
    if (user.is_active && !form.is_active && !window.confirm("Confirmer la désactivation de ce compte ?")) return;
    if (user.role === "admin" && form.role === "agent" && !window.confirm("Confirmer le retrait du rôle administrateur ?")) return;
    const payload: UpdateUserPayload = { full_name: form.full_name, email: form.email, department_id: form.department_id, is_active: form.is_active };
    if (!legacy || replaceLegacyRole) payload.role = form.role;
    setSubmitting(true); setError(null);
    try { await updateUser(user.id, payload); onSuccess(); }
    catch (requestError) { setError(getAdminErrorMessage(requestError)); }
    finally { setSubmitting(false); }
  }
  return <AdminDialog title={`Modifier ${user.full_name}`} description="Les règles de sécurité sont vérifiées par le serveur." onClose={onClose}><form className="admin-form" onSubmit={submit}>{legacy && <div className="admin-legacy-notice"><strong>Rôle historique : {user.role}</strong><span>Ce rôle n’accorde aucun privilège administrateur.</span><label><input type="checkbox" checked={replaceLegacyRole} onChange={(event) => setReplaceLegacyRole(event.target.checked)} />Remplacer par un rôle pris en charge</label></div>}<FormFields form={form} setForm={setForm} roleDisabled={legacy && !replaceLegacyRole} legacyRole={legacy && !replaceLegacyRole ? user.role : undefined} />{error && <ErrorState message={error} />}<div className="admin-dialog-actions"><Button type="button" variant="ghost" onClick={onClose}>Annuler</Button><Button type="submit" disabled={submitting}>{submitting ? "Enregistrement…" : "Enregistrer"}</Button></div></form></AdminDialog>;
}

function ResetPasswordDialog({ user, onClose, onSuccess }: { user: AdminUser; onClose: () => void; onSuccess: () => void }) {
  const [password, setPassword] = useState(""); const [confirmation, setConfirmation] = useState(""); const [submitting, setSubmitting] = useState(false); const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) { event.preventDefault(); if (submitting) return; if (password !== confirmation) { setError("Les mots de passe ne correspondent pas."); return; } setSubmitting(true); setError(null); try { await resetUserPassword(user.id, password); setPassword(""); setConfirmation(""); onSuccess(); } catch (requestError) { setError(getAdminErrorMessage(requestError)); } finally { setSubmitting(false); } }
  return <AdminDialog title="Réinitialiser le mot de passe" description={`Définissez un nouveau mot de passe pour ${user.full_name}.`} onClose={onClose}><form className="admin-form" onSubmit={submit}><div className="admin-session-warning">Les sessions existantes restent valides jusqu’à expiration.</div><label>Nouveau mot de passe<input required type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" /></label><label>Confirmation<input required type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="new-password" /></label>{error && <ErrorState message={error} />}<div className="admin-dialog-actions"><Button type="button" variant="ghost" onClick={onClose}>Annuler</Button><Button type="submit" disabled={submitting}>{submitting ? "Réinitialisation…" : "Réinitialiser"}</Button></div></form></AdminDialog>;
}
