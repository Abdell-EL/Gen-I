import { CheckCircle2, Eye, EyeOff, KeyRound, LoaderCircle, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { AuthLayout } from "../components/layout/AuthLayout";
import { Button } from "../components/ui/Button";
import { ErrorState } from "../components/ui/ErrorState";
import {
  PasswordResetRequestError,
  completePasswordReset,
  resetCompletionErrorMessage,
  validatePasswordResetToken,
} from "../services/passwordLifecycleApi";
import {
  consumePasswordResetToken,
  passwordResetStateCopy,
  passwordsMatch,
  type PasswordResetViewState,
} from "../features/auth/passwordResetFlow";

export function ResetPasswordPage() {
  const [state, setState] = useState<PasswordResetViewState>("validating");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const tokenRef = useRef<string | null>(null);
  const started = useRef(false);
  const submissionActive = useRef(false);

  useEffect(() => {
    if (!started.current) {
      started.current = true;
      tokenRef.current = consumePasswordResetToken(window.location.href, (path) => {
        window.history.replaceState(window.history.state, "", path);
      });
    }
    const token = tokenRef.current;
    if (!token) {
      setState("invalid");
      return;
    }
    const controller = new AbortController();
    void validatePasswordResetToken({ token }, controller.signal)
      .then(() => setState("valid"))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof PasswordResetRequestError) {
          if (error.state !== "failed") tokenRef.current = null;
          setState(error.state);
        } else {
          setState("failed");
        }
      });
    return () => controller.abort();
  }, []);

  function clearSecrets() {
    tokenRef.current = null;
    setPassword("");
    setConfirmation("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = tokenRef.current;
    if (submissionActive.current || !token || state !== "valid") return;
    if (!passwordsMatch(password, confirmation)) {
      setFormError("Les mots de passe ne correspondent pas.");
      return;
    }
    submissionActive.current = true;
    setSubmitting(true);
    setFormError(null);
    try {
      await completePasswordReset({
        token,
        password,
        password_confirmation: confirmation,
      });
      clearSecrets();
      setState("complete");
    } catch (error) {
      if (error instanceof PasswordResetRequestError) {
        clearSecrets();
        setState(error.state);
      } else {
        setFormError(resetCompletionErrorMessage(error));
      }
    } finally {
      submissionActive.current = false;
      setSubmitting(false);
    }
  }

  const failure = ["invalid", "expired", "consumed", "failed"].includes(state)
    ? passwordResetStateCopy(state)
    : null;

  return (
    <AuthLayout
      eyebrow="Réinitialisation"
      title={<>Choisissez un nouveau mot de passe<span className="auth-accent-dot">.</span></>}
      description="Le lien est validé avant l’affichage du formulaire. Vous devrez vous connecter ensuite."
      pageClassName="auth-page-signin auth-page-password-lifecycle"
    >
      {state === "validating" && (
        <div className="activation-state" role="status">
          <LoaderCircle className="spin" />
          <strong>Validation du lien…</strong>
        </div>
      )}
      {failure && <ErrorState title={failure.title} message={failure.message} />}
      {state === "valid" && (
        <form className="auth-form activation-form" onSubmit={submit}>
          <div className="password-requirements">
            <KeyRound size={17} aria-hidden="true" />
            <span>Utilisez un mot de passe non vide. Le serveur applique la limite sécurisée en octets UTF-8.</span>
          </div>
          <div className="form-field">
            <label htmlFor="reset-password">Nouveau mot de passe</label>
            <div className="input-shell">
              <KeyRound size={17} aria-hidden="true" />
              <input
                id="reset-password"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
              <button type="button" className="password-visibility" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "Masquer le nouveau mot de passe" : "Afficher le nouveau mot de passe"}>
                {showPassword ? <EyeOff /> : <Eye />}
              </button>
            </div>
          </div>
          <div className="form-field">
            <label htmlFor="reset-password-confirmation">Confirmer le mot de passe</label>
            <div className="input-shell">
              <KeyRound size={17} aria-hidden="true" />
              <input
                id="reset-password-confirmation"
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
          {formError && <ErrorState message={formError} />}
          <Button type="submit" className="full-width" disabled={submitting} icon={<ShieldCheck size={17} aria-hidden="true" />}>
            {submitting ? "Réinitialisation…" : "Réinitialiser le mot de passe"}
          </Button>
        </form>
      )}
      {state === "complete" && (
        <div className="activation-complete" role="status">
          <CheckCircle2 />
          <h3>Mot de passe réinitialisé</h3>
          <p>Votre mot de passe a été modifié. Connectez-vous avec votre nouveau mot de passe.</p>
          <Link className="button button-primary" to="/signin"><span>Se connecter</span></Link>
        </div>
      )}
    </AuthLayout>
  );
}
