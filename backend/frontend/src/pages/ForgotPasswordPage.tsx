import { ArrowLeft, ExternalLink, Mail, ShieldAlert } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { AuthLayout } from "../components/layout/AuthLayout";
import { Button } from "../components/ui/Button";
import { ErrorState } from "../components/ui/ErrorState";
import { requestPasswordReset } from "../services/passwordLifecycleApi";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [resetUrl, setResetUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const submissionActive = useRef(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submissionActive.current) return;
    submissionActive.current = true;
    setSubmitting(true);
    setError(null);
    setResetUrl(null);
    try {
      const response = await requestPasswordReset({ email: email.trim() });
      setMessage(response.message);
      setEmail("");
      setResetUrl(response.reset_url ?? null);
    } catch {
      setError("Le service est momentanément indisponible. Réessayez dans un instant.");
    } finally {
      submissionActive.current = false;
      setSubmitting(false);
    }
  }

  function openCapturedResetUrl() {
    if (!resetUrl) return;
    const url = resetUrl;
    setResetUrl(null);
    window.open(url, "_blank", "noopener,noreferrer");
  }

  return (
    <AuthLayout
      eyebrow="Réinitialisation"
      title={<>Mot de passe oublié<span className="auth-accent-dot">.</span></>}
      description="Saisissez votre adresse e-mail. Si un compte éligible correspond, des instructions seront envoyées."
      pageClassName="auth-page-signin auth-page-password-lifecycle"
    >
      <form className="auth-form" onSubmit={submit}>
        <div className="form-field">
          <label htmlFor="forgot-password-email">Adresse e-mail</label>
          <div className="input-shell">
            <Mail size={17} aria-hidden="true" />
            <input
              id="forgot-password-email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </div>
        </div>
        {error && <ErrorState title="Service indisponible" message={error} />}
        {message && <div className="password-lifecycle-success" role="status"><ShieldAlert size={17} aria-hidden="true" /><span>{message}</span></div>}
        {resetUrl && (
          <div className="password-reset-capture" role="status">
            <strong>Mode développement uniquement</strong>
            <p>Un lien de test local a été capturé. Cette exposition doit rester désactivée en production.</p>
            <Button type="button" variant="secondary" onClick={openCapturedResetUrl} icon={<ExternalLink size={16} aria-hidden="true" />}>
              Ouvrir le lien de test local
            </Button>
          </div>
        )}
        <Button type="submit" className="full-width" disabled={submitting}>
          {submitting ? "Envoi…" : "Envoyer les instructions"}
        </Button>
      </form>
      <Link className="auth-secondary-link" to="/signin">
        <ArrowLeft size={16} aria-hidden="true" />
        Retour à la connexion
      </Link>
    </AuthLayout>
  );
}
