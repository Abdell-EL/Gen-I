import { CheckCircle2, Eye, EyeOff, KeyRound, LoaderCircle, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { AuthLayout } from "../components/layout/AuthLayout";
import { Button } from "../components/ui/Button";
import { ErrorState } from "../components/ui/ErrorState";
import { ActivationRequestError, completeActivation, validateActivationToken } from "../services/activationApi";
import { consumeActivationToken, type ActivationViewState } from "../features/auth/activationFlow";

const stateMessages: Partial<Record<ActivationViewState, { title: string; message: string }>> = {
  invalid: { title: "Lien invalide", message: "Ce lien d’activation n’est pas valide." },
  expired: { title: "Lien expiré", message: "Ce lien d’activation a expiré. Demandez une nouvelle invitation à un administrateur." },
  consumed: { title: "Lien déjà utilisé", message: "Ce compte a déjà été activé avec ce lien." },
  failed: { title: "Service indisponible", message: "La validation du lien a échoué. Réessayez dans un instant." },
};

export function ActivationPage() {
  const [state, setState] = useState<ActivationViewState>("validating");
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
      tokenRef.current = consumeActivationToken(window.location.href, (path) => {
        window.history.replaceState(window.history.state, "", path);
      });
    }
    const token = tokenRef.current;
    if (!token) { setState("invalid"); return; }
    const controller = new AbortController();
    void validateActivationToken(token, controller.signal)
      .then(() => setState("valid"))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState(error instanceof ActivationRequestError ? error.state : "failed");
      });
    return () => controller.abort();
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submissionActive.current || !tokenRef.current || state !== "valid") return;
    if (password !== confirmation) { setFormError("Les mots de passe ne correspondent pas."); return; }
    submissionActive.current = true; setSubmitting(true); setFormError(null);
    try {
      await completeActivation(tokenRef.current, password, confirmation);
      tokenRef.current = null; setPassword(""); setConfirmation(""); setState("complete");
    } catch (error) {
      if (error instanceof ActivationRequestError && error.state !== "failed") {
        tokenRef.current = null; setPassword(""); setConfirmation(""); setState(error.state);
      } else {
        setFormError("L’activation a échoué. Votre mot de passe n’a pas été enregistré.");
      }
    } finally {
      submissionActive.current = false; setSubmitting(false);
    }
  }

  const failure = stateMessages[state];
  return <AuthLayout eyebrow="Activation" title={<>Activez votre compte<span className="auth-accent-dot">.</span></>}
    description="Choisissez votre mot de passe pour finaliser l’accès à la plateforme." pageClassName="auth-page-signin auth-page-activation">
    {state === "validating" && <div className="activation-state" role="status"><LoaderCircle className="spin" /><strong>Validation du lien…</strong></div>}
    {failure && <ErrorState title={failure.title} message={failure.message} />}
    {state === "valid" && <form className="auth-form activation-form" onSubmit={submit}>
      <div className="password-requirements"><KeyRound size={17} /><span>Utilisez un mot de passe non vide. Le serveur applique également sa limite sécurisée en octets UTF-8.</span></div>
      <div className="form-field"><label htmlFor="activation-password">Mot de passe</label><div className="input-shell"><KeyRound size={17} /><input id="activation-password" type={showPassword ? "text" : "password"} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} required /><button type="button" className="password-visibility" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "Masquer le mot de passe" : "Afficher le mot de passe"}>{showPassword ? <EyeOff /> : <Eye />}</button></div></div>
      <div className="form-field"><label htmlFor="activation-confirmation">Confirmer le mot de passe</label><div className="input-shell"><KeyRound size={17} /><input id="activation-confirmation" type={showConfirmation ? "text" : "password"} autoComplete="new-password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required /><button type="button" className="password-visibility" onClick={() => setShowConfirmation((value) => !value)} aria-label={showConfirmation ? "Masquer la confirmation" : "Afficher la confirmation"}>{showConfirmation ? <EyeOff /> : <Eye />}</button></div></div>
      {formError && <ErrorState message={formError} />}
      <Button type="submit" className="full-width" disabled={submitting} icon={<ShieldAlert size={17} />}>{submitting ? "Activation…" : "Activer mon compte"}</Button>
    </form>}
    {state === "complete" && <div className="activation-complete" role="status"><CheckCircle2 /><h3>Compte activé</h3><p>Votre mot de passe a été enregistré. Vous pouvez maintenant vous connecter.</p><Link className="button button-primary" to="/signin"><span>Se connecter</span></Link></div>}
  </AuthLayout>;
}
