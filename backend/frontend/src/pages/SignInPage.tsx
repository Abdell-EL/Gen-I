import { LockKeyhole, LogIn, Mail, ShieldAlert } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../app/useAuth";
import { AuthLayout } from "../components/layout/AuthLayout";
import { Button } from "../components/ui/Button";
import { ErrorState } from "../components/ui/ErrorState";

function landingPageFor(role: "agent" | "admin") { return role === "admin" ? "/admin" : "/agent"; }

export function SignInPage() {
  const { user, isInitialising, isSubmitting, authenticationError, signIn } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const roleHint = searchParams.get("role");
  const passwordChanged = searchParams.get("password_changed") === "1";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  if (isInitialising) return <div className="route-loading">Vérification de la session…</div>;
  if (user) return <Navigate to={landingPageFor(user.role)} replace />;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting) return;
    try {
      const authenticatedUser = await signIn(email.trim(), password);
      const requestedRedirect = searchParams.get("redirect");
      const isSafeInternalPath = requestedRedirect?.startsWith("/") && !requestedRedirect.startsWith("//");
      const roleAllowsRedirect = requestedRedirect !== "/admin" || authenticatedUser.role === "admin";
      const destination =
        isSafeInternalPath && roleAllowsRedirect && requestedRedirect
          ? requestedRedirect
          : landingPageFor(authenticatedUser.role);
      navigate(destination, { replace: true });
    } catch { /* Generic error is exposed by the provider. */ }
  }

  return (
    <AuthLayout eyebrow="Connexion" title={<>Bienvenue sur votre espace FDE<span className="auth-accent-dot">.</span></>}
      description="Utilisez votre compte pour accéder à l’assistant ou à la console d’administration." pageClassName="auth-page-signin">
      {passwordChanged && <div className="password-lifecycle-success" role="status"><ShieldAlert size={17} />Votre mot de passe a été modifié. Reconnectez-vous.</div>}
      {roleHint && <div className="role-hint"><ShieldAlert size={17} />Connexion à l’espace {roleHint === "admin" ? "Administrateur" : "Agent"}</div>}
      <form className="auth-form" onSubmit={handleSubmit}>
        <div className="form-field"><label htmlFor="signin-email">Adresse e-mail</label><div className="input-shell"><Mail size={17} aria-hidden="true" /><input id="signin-email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></div></div>
        <div className="form-field"><label htmlFor="signin-password">Mot de passe</label><div className="input-shell"><LockKeyhole size={17} aria-hidden="true" /><input id="signin-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></div></div>
        <Link className="auth-inline-link" to="/forgot-password">Mot de passe oublié ?</Link>
        {authenticationError && <ErrorState message={authenticationError} />}
        <Button type="submit" className="full-width" disabled={isSubmitting} icon={<LogIn size={17} />}>{isSubmitting ? "Connexion…" : "Se connecter"}</Button>
      </form>
    </AuthLayout>
  );
}
