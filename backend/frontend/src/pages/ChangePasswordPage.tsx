import { Eye, EyeOff, KeyRound, LockKeyhole, Save } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../app/useAuth";
import { AgentSidebar } from "../components/layout/AgentSidebar";
import { DashboardShell } from "../components/layout/DashboardShell";
import { Button } from "../components/ui/Button";
import { ErrorState } from "../components/ui/ErrorState";
import { changeOwnPassword, changePasswordErrorMessage } from "../services/passwordLifecycleApi";

export function ChangePasswordPage() {
  const { signOut, user } = useAuth();
  const navigate = useNavigate();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const submissionActive = useRef(false);

  function clearSecrets() {
    setCurrentPassword("");
    setNewPassword("");
    setConfirmation("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submissionActive.current) return;
    if (newPassword !== confirmation) {
      setError("Les nouveaux mots de passe ne correspondent pas.");
      return;
    }
    submissionActive.current = true;
    setSubmitting(true);
    setError(null);
    try {
      const response = await changeOwnPassword({
        current_password: currentPassword,
        new_password: newPassword,
        new_password_confirmation: confirmation,
      });
      clearSecrets();
      if (response.reauthentication_required) {
        signOut();
        navigate("/signin?password_changed=1", { replace: true });
      }
    } catch (requestError) {
      setError(changePasswordErrorMessage(requestError));
    } finally {
      submissionActive.current = false;
      setSubmitting(false);
    }
  }

  return (
    <DashboardShell
      sidebar={<AgentSidebar />}
      className="agent-console password-settings-page"
      consoleLabel="Paramètres"
      eyebrow="Sécurité"
      title="Changer le mot de passe"
      description="Modifiez votre mot de passe. Vous devrez vous reconnecter après la confirmation."
      userDisplayName={user?.full_name ?? "Utilisateur"}
    >
      <section className="password-lifecycle-card card" aria-labelledby="change-password-title">
        <div className="password-lifecycle-heading">
          <p className="section-kicker">Compte</p>
          <h2 id="change-password-title">Mot de passe</h2>
          <p>Votre mot de passe actuel est vérifié avant toute modification.</p>
        </div>
        <form className="auth-form activation-form" onSubmit={submit}>
          <div className="password-requirements">
            <KeyRound size={17} aria-hidden="true" />
            <span>Utilisez un mot de passe non vide. Le serveur applique la limite sécurisée en octets UTF-8.</span>
          </div>
          <div className="form-field">
            <label htmlFor="change-current-password">Mot de passe actuel</label>
            <div className="input-shell">
              <LockKeyhole size={17} aria-hidden="true" />
              <input
                id="change-current-password"
                type={showCurrent ? "text" : "password"}
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                required
              />
              <button type="button" className="password-visibility" onClick={() => setShowCurrent((value) => !value)} aria-label={showCurrent ? "Masquer le mot de passe actuel" : "Afficher le mot de passe actuel"}>
                {showCurrent ? <EyeOff /> : <Eye />}
              </button>
            </div>
          </div>
          <div className="form-field">
            <label htmlFor="change-new-password">Nouveau mot de passe</label>
            <div className="input-shell">
              <KeyRound size={17} aria-hidden="true" />
              <input
                id="change-new-password"
                type={showNew ? "text" : "password"}
                autoComplete="new-password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                required
              />
              <button type="button" className="password-visibility" onClick={() => setShowNew((value) => !value)} aria-label={showNew ? "Masquer le nouveau mot de passe" : "Afficher le nouveau mot de passe"}>
                {showNew ? <EyeOff /> : <Eye />}
              </button>
            </div>
          </div>
          <div className="form-field">
            <label htmlFor="change-password-confirmation">Confirmer le nouveau mot de passe</label>
            <div className="input-shell">
              <KeyRound size={17} aria-hidden="true" />
              <input
                id="change-password-confirmation"
                type={showConfirmation ? "text" : "password"}
                autoComplete="new-password"
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                required
              />
              <button type="button" className="password-visibility" onClick={() => setShowConfirmation((value) => !value)} aria-label={showConfirmation ? "Masquer la confirmation" : "Afficher la confirmation"}>
                {showConfirmation ? <EyeOff /> : <Eye />}
              </button>
            </div>
          </div>
          {error && <ErrorState message={error} />}
          <Button type="submit" className="full-width" disabled={submitting} icon={<Save size={17} aria-hidden="true" />}>
            {submitting ? "Modification…" : "Modifier le mot de passe"}
          </Button>
        </form>
      </section>
    </DashboardShell>
  );
}
