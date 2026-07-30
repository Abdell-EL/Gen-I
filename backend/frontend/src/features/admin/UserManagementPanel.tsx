import axios from "axios";
import { ExternalLink, KeyRound, MailPlus, Pencil, Plus, RefreshCw, Search, UserCheck, UserX } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { useAuth } from "../../app/useAuth";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorState } from "../../components/ui/ErrorState";
import { LoadingState } from "../../components/ui/LoadingState";
import { createUser, getAdminErrorMessage, getUser, listUsers, resendUserInvitation,
  resetUserPassword, updateUser } from "../../services/adminApi";
import type { AdminUser, CreateUserPayload, EditableUserRole, InvitationDelivery,
  UpdateUserPayload, UserListFilters } from "../../types/admin";
import { AccountStatusPill, AdminDialog, Pagination, RolePill } from "./AdminCommon";
import { formatAdminDate, isEditableRole } from "./adminUtils";

const initialInvite: CreateUserPayload = { full_name: "", email: "", role: "agent" };
type EditUserForm = { full_name: string; email: string; role: EditableUserRole;
  department_id: number | null; is_active: boolean };

export function UserManagementPanel({ onDataChanged }: { onDataChanged: () => void }) {
  const { user: currentUser } = useAuth();
  const [data, setData] = useState<Awaited<ReturnType<typeof listUsers>> | null>(null);
  const [search, setSearch] = useState(""); const [debouncedSearch, setDebouncedSearch] = useState("");
  const [filters, setFilters] = useState<UserListFilters>({ page: 1, page_size: 25, sort_by: "created_at", sort_order: "desc" });
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null); const [refreshKey, setRefreshKey] = useState(0);
  const [inviteOpen, setInviteOpen] = useState(false); const [editUser, setEditUser] = useState<AdminUser | null>(null);
  const [resetUser, setResetUser] = useState<AdminUser | null>(null); const [localActivationUrl, setLocalActivationUrl] = useState<string | null>(null);
  const [resendingUserId, setResendingUserId] = useState<number | null>(null);

  useEffect(() => { const timer = window.setTimeout(() => { setDebouncedSearch(search.trim()); setFilters((current) => ({ ...current, page: 1 })); }, 350); return () => window.clearTimeout(timer); }, [search]);
  const requestFilters = useMemo(() => ({ ...filters, search: debouncedSearch || undefined }), [filters, debouncedSearch]);
  useEffect(() => { let active = true; const timer = window.setTimeout(() => {
    setLoading(true); setError(null); void listUsers(requestFilters).then((response) => { if (active) setData(response); })
      .catch((requestError) => { if (active) setError(getAdminErrorMessage(requestError)); })
      .finally(() => { if (active) setLoading(false); });
  }, 0); return () => { active = false; window.clearTimeout(timer); }; }, [requestFilters, refreshKey]);

  const refresh = useCallback(() => setRefreshKey((value) => value + 1), []);
  function invitationSucceeded(delivery: InvitationDelivery, resent = false) {
    setLocalActivationUrl(delivery.activation_url);
    if (delivery.status === "failed") { setSuccess(null); setError("Le compte reste en attente, mais la livraison de l’invitation a échoué."); }
    else if (delivery.status === "not_sent") { setError(null); setSuccess("Invitation créée sans envoi externe. Utilisez le mode local explicite pour tester le lien."); }
    else { setError(null); setSuccess(resent ? "Invitation renvoyée avec succès." : "Invitation envoyée avec succès."); }
    refresh(); onDataChanged();
  }
  function mutationSucceeded(message: string) { setSuccess(message); refresh(); onDataChanged(); }
  async function openEdit(userId: number) { setError(null); try { setEditUser(await getUser(userId)); } catch (requestError) { setError(getAdminErrorMessage(requestError)); } }
  async function toggleActive(target: AdminUser) {
    if (target.is_active && !window.confirm(`Désactiver le compte de ${target.full_name} ?`)) return;
    setError(null); try { await updateUser(target.id, { is_active: !target.is_active }); mutationSucceeded(target.is_active ? "Compte désactivé." : "Compte activé."); }
    catch (requestError) { setError(getAdminErrorMessage(requestError)); }
  }
  async function resend(target: AdminUser) {
    if (resendingUserId !== null || !window.confirm(`Renvoyer l’invitation à ${target.full_name} ?`)) return;
    setResendingUserId(target.id); setError(null); setSuccess(null); setLocalActivationUrl(null);
    try { const response = await resendUserInvitation(target.id); invitationSucceeded(response.invitation_delivery, true); }
    catch (requestError) {
      if (axios.isAxiosError(requestError) && requestError.response?.status === 429) setError("Veuillez patienter avant de renvoyer cette invitation.");
      else if (axios.isAxiosError(requestError) && requestError.response?.status === 409) setError("Ce compte est déjà activé et ne peut plus être invité.");
      else setError(getAdminErrorMessage(requestError));
    } finally { setResendingUserId(null); }
  }

  return <section className="admin-data-panel">
    <div className="admin-panel-heading"><div><span className="section-kicker">Gestion des accès</span><h2>Utilisateurs</h2><p>Invitez et administrez les comptes autorisés à utiliser la plateforme.</p></div><div><Button type="button" variant="secondary" onClick={refresh} icon={<RefreshCw size={16} />}>Actualiser</Button><Button type="button" onClick={() => setInviteOpen(true)} icon={<Plus size={16} />}>Inviter un utilisateur</Button></div></div>
    {success && <div className="admin-success" role="status">{success}<button type="button" onClick={() => setSuccess(null)}>×</button></div>}
    {localActivationUrl && <div className="admin-local-invitation" role="status"><span>Lien d’activation locale disponible pour cette invitation uniquement.</span><Button type="button" variant="secondary" icon={<ExternalLink size={15} />} onClick={() => { const url = localActivationUrl; setLocalActivationUrl(null); window.open(url, "_blank", "noopener,noreferrer"); }}>Ouvrir le test local</Button></div>}
    {error && <ErrorState message={error} />}
    <div className="admin-filter-bar"><label className="admin-search-field"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Rechercher un nom ou un email" aria-label="Rechercher un utilisateur" /></label><select value={filters.role ?? ""} onChange={(event) => setFilters((current) => ({ ...current, page: 1, role: (event.target.value || undefined) as EditableUserRole | undefined }))}><option value="">Tous les rôles</option><option value="admin">Administrateurs</option><option value="agent">Agents</option></select><select value={filters.is_active === undefined ? "" : String(filters.is_active)} onChange={(event) => setFilters((current) => ({ ...current, page: 1, is_active: event.target.value === "" ? undefined : event.target.value === "true" }))}><option value="">Tous les statuts administratifs</option><option value="true">Administrativement autorisés</option><option value="false">Administrativement désactivés</option></select><select value={`${filters.sort_by}:${filters.sort_order}`} onChange={(event) => { const [sort_by, sort_order] = event.target.value.split(":") as [UserListFilters["sort_by"], UserListFilters["sort_order"]]; setFilters((current) => ({ ...current, page: 1, sort_by, sort_order })); }}><option value="created_at:desc">Plus récents</option><option value="created_at:asc">Plus anciens</option><option value="full_name:asc">Nom A–Z</option><option value="email:asc">Email A–Z</option><option value="role:asc">Rôle A–Z</option></select><select value={filters.page_size} onChange={(event) => setFilters((current) => ({ ...current, page: 1, page_size: Number(event.target.value) }))}><option value="10">10 / page</option><option value="25">25 / page</option><option value="50">50 / page</option><option value="100">100 / page</option></select></div>
    {loading && <LoadingState label="Chargement des utilisateurs…" />}
    {!loading && data?.items.length === 0 && <EmptyState title="Aucun utilisateur" description="Aucun compte ne correspond aux filtres sélectionnés." />}
    {!loading && data && data.items.length > 0 && <><div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Nom</th><th>Email</th><th>Rôle</th><th>Statut du compte</th><th>Département</th><th>Créé le</th><th>Actions</th></tr></thead><tbody>{data.items.map((item) => <tr key={item.id}><td><strong>{item.full_name}</strong></td><td>{item.email}</td><td><RolePill role={item.role} /></td><td><AccountStatusPill user={item} /></td><td>{item.department_id ?? "—"}</td><td>{formatAdminDate(item.created_at)}</td><td><div className="admin-row-actions"><button type="button" onClick={() => void openEdit(item.id)} title="Modifier"><Pencil size={15} /></button>{item.activation_status === "pending" ? <button type="button" disabled={resendingUserId !== null} onClick={() => void resend(item)} title="Renvoyer l’invitation"><MailPlus size={15} /></button> : <button type="button" onClick={() => setResetUser(item)} title="Réinitialiser le mot de passe"><KeyRound size={15} /></button>}<button type="button" disabled={item.id === currentUser?.id && item.is_active} onClick={() => void toggleActive(item)} title={item.is_active ? "Désactiver" : "Activer"}>{item.is_active ? <UserX size={15} /> : <UserCheck size={15} />}</button></div></td></tr>)}</tbody></table></div><Pagination page={data.page} pages={data.pages} total={data.total} onPageChange={(page) => setFilters((current) => ({ ...current, page }))} /></>}
    {inviteOpen && <InviteUserDialog onClose={() => setInviteOpen(false)} onSuccess={(delivery) => { setInviteOpen(false); invitationSucceeded(delivery); }} />}
    {editUser && <EditUserDialog user={editUser} onClose={() => setEditUser(null)} onSuccess={() => { setEditUser(null); mutationSucceeded("Utilisateur mis à jour."); }} />}
    {resetUser && <ResetPasswordDialog user={resetUser} onClose={() => setResetUser(null)} onSuccess={() => { setResetUser(null); mutationSucceeded("Mot de passe réinitialisé."); }} />}
  </section>;
}

function InviteUserDialog({ onClose, onSuccess }: { onClose: () => void; onSuccess: (delivery: InvitationDelivery) => void }) {
  const [form, setForm] = useState(initialInvite); const [submitting, setSubmitting] = useState(false); const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) { event.preventDefault(); if (submitting) return; setSubmitting(true); setError(null);
    try { const response = await createUser({ full_name: form.full_name.trim(), email: form.email.trim(), role: form.role }); setForm(initialInvite); onSuccess(response.invitation_delivery); }
    catch (requestError) { if (axios.isAxiosError(requestError) && requestError.response?.status === 409) setError("Un utilisateur possède déjà cette adresse e-mail."); else setError(getAdminErrorMessage(requestError)); }
    finally { setSubmitting(false); }
  }
  return <AdminDialog title="Inviter un utilisateur" description="La personne choisira son mot de passe depuis son lien d’activation." onClose={onClose}><form className="admin-form" onSubmit={submit}><div className="admin-form-grid"><label>Nom complet<input required value={form.full_name} onChange={(event) => setForm({ ...form, full_name: event.target.value })} autoComplete="name" /></label><label>Adresse email<input required type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} autoComplete="email" /></label><label>Rôle<select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value as EditableUserRole })}><option value="agent">Agent</option><option value="admin">Administrateur</option></select></label></div>{error && <ErrorState message={error} />}<div className="admin-dialog-actions"><Button type="button" variant="ghost" onClick={onClose}>Annuler</Button><Button type="submit" disabled={submitting}>{submitting ? "Invitation…" : "Envoyer l’invitation"}</Button></div></form></AdminDialog>;
}

function EditFields({ form, setForm, legacyRole, roleDisabled = false }: { form: EditUserForm; setForm: (form: EditUserForm) => void; legacyRole?: string; roleDisabled?: boolean }) {
  return <div className="admin-form-grid"><label>Nom complet<input required value={form.full_name} onChange={(event) => setForm({ ...form, full_name: event.target.value })} /></label><label>Adresse email<input required type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></label><label>Rôle<select disabled={roleDisabled} value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value as EditableUserRole })}><option value="agent">Agent</option><option value="admin">Administrateur</option></select>{legacyRole && <small>Rôle actuel historique : {legacyRole}.</small>}</label><label>Département (optionnel)<input type="number" min="1" value={form.department_id ?? ""} onChange={(event) => setForm({ ...form, department_id: event.target.value ? Number(event.target.value) : null })} /></label><label className="admin-check admin-form-full"><input type="checkbox" checked={form.is_active} onChange={(event) => setForm({ ...form, is_active: event.target.checked })} />Compte administrativement autorisé</label></div>;
}

function EditUserDialog({ user, onClose, onSuccess }: { user: AdminUser; onClose: () => void; onSuccess: () => void }) {
  const legacy = !isEditableRole(user.role); const [form, setForm] = useState<EditUserForm>({ full_name: user.full_name, email: user.email, role: isEditableRole(user.role) ? user.role : "agent", department_id: user.department_id, is_active: user.is_active }); const [replaceLegacyRole, setReplaceLegacyRole] = useState(false); const [submitting, setSubmitting] = useState(false); const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) { event.preventDefault(); if (submitting) return; if (user.is_active && !form.is_active && !window.confirm("Confirmer la désactivation de ce compte ?")) return; if (user.role === "admin" && form.role === "agent" && !window.confirm("Confirmer le retrait du rôle administrateur ?")) return; const payload: UpdateUserPayload = { full_name: form.full_name, email: form.email, department_id: form.department_id, is_active: form.is_active }; if (!legacy || replaceLegacyRole) payload.role = form.role; setSubmitting(true); setError(null); try { await updateUser(user.id, payload); onSuccess(); } catch (requestError) { setError(getAdminErrorMessage(requestError)); } finally { setSubmitting(false); } }
  return <AdminDialog title={`Modifier ${user.full_name}`} description="Les règles de sécurité sont vérifiées par le serveur." onClose={onClose}><form className="admin-form" onSubmit={submit}>{legacy && <div className="admin-legacy-notice"><strong>Rôle historique : {user.role}</strong><label><input type="checkbox" checked={replaceLegacyRole} onChange={(event) => setReplaceLegacyRole(event.target.checked)} />Remplacer par un rôle pris en charge</label></div>}<EditFields form={form} setForm={setForm} roleDisabled={legacy && !replaceLegacyRole} legacyRole={legacy && !replaceLegacyRole ? user.role : undefined} />{error && <ErrorState message={error} />}<div className="admin-dialog-actions"><Button type="button" variant="ghost" onClick={onClose}>Annuler</Button><Button type="submit" disabled={submitting}>{submitting ? "Enregistrement…" : "Enregistrer"}</Button></div></form></AdminDialog>;
}

function ResetPasswordDialog({ user, onClose, onSuccess }: { user: AdminUser; onClose: () => void; onSuccess: () => void }) {
  const [password, setPassword] = useState(""); const [confirmation, setConfirmation] = useState(""); const [submitting, setSubmitting] = useState(false); const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) { event.preventDefault(); if (submitting) return; if (password !== confirmation) { setError("Les mots de passe ne correspondent pas."); return; } setSubmitting(true); setError(null); try { await resetUserPassword(user.id, password); setPassword(""); setConfirmation(""); onSuccess(); } catch (requestError) { setError(getAdminErrorMessage(requestError)); } finally { setSubmitting(false); } }
  return <AdminDialog title="Réinitialiser le mot de passe" description={`Définissez un nouveau mot de passe pour ${user.full_name}.`} onClose={onClose}><form className="admin-form" onSubmit={submit}><label>Nouveau mot de passe<input required type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" /></label><label>Confirmation<input required type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="new-password" /></label>{error && <ErrorState message={error} />}<div className="admin-dialog-actions"><Button type="button" variant="ghost" onClick={onClose}>Annuler</Button><Button type="submit" disabled={submitting}>{submitting ? "Réinitialisation…" : "Réinitialiser"}</Button></div></form></AdminDialog>;
}
