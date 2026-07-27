import {
  Bot,
  LockKeyhole,
  LogIn,
  Mail,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { useAuth } from "../app/useAuth";
import { AuthLayout } from "../components/layout/AuthLayout";
import { Button } from "../components/ui/Button";
import { ErrorState } from "../components/ui/ErrorState";
import { getApiErrorMessage } from "../services/apiClient";

export function SignInPage() {
  const { signIn, mode } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const roleHint = searchParams.get("role");
  const [email, setEmail] = useState(
    roleHint === "admin" ? "admin@sogetrel.local" : "",
  );
  const [password, setPassword] = useState(
    roleHint === "admin" ? "admin123" : "",
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const user = await signIn({ email, password });
      const requestedRedirect = searchParams.get("redirect");
      const safeRedirect =
        requestedRedirect?.startsWith("/") &&
        !(requestedRedirect === "/admin" && user.role !== "admin")
          ? requestedRedirect
          : null;
      navigate(safeRedirect ?? (user.role === "admin" ? "/admin" : "/agent"));
    } catch (submitError) {
      setError(getApiErrorMessage(submitError));
    } finally {
      setLoading(false);
    }
  }

  function fillDemoAccount(role: "agent" | "admin") {
    setEmail(`${role}@sogetrel.local`);
    setPassword(role === "agent" ? "agent123" : "admin123");
    setError(null);
  }

  return (
    <AuthLayout
      eyebrow="Connexion"
      title={<>Bienvenue sur votre espace FDE<span className="auth-accent-dot">.</span></>}
      description="Utilisez votre compte pour accéder à l’assistant ou à la console d’administration."
      pageClassName="auth-page-signin"
    >
      {roleHint && (
        <div className="role-hint">
          <ShieldAlert size={17} />
          Connexion à l’espace {roleHint === "admin" ? "Administrateur" : "Agent"}
        </div>
      )}

      <form className="auth-form" onSubmit={handleSubmit}>
        <div className="form-field">
          <label htmlFor="signin-email">Adresse e-mail</label>
          <div className="input-shell">
            <Mail size={17} aria-hidden="true" />
            <input
              id="signin-email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </div>
        </div>
        <div className="form-field">
          <label htmlFor="signin-password">Mot de passe</label>
          <div className="input-shell">
            <LockKeyhole size={17} aria-hidden="true" />
            <input
              id="signin-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </div>
        </div>

        {error && <ErrorState message={error} />}

        <Button
          type="submit"
          className="full-width"
          disabled={loading}
          icon={<LogIn size={17} />}
        >
          {loading ? "Connexion…" : "Se connecter"}
        </Button>
      </form>

      {mode === "demo" && (
        <div className="demo-credentials">
          <div className="demo-credentials-heading">
            <span>Accès de démonstration</span>
            <small>Stockage local uniquement</small>
          </div>
          <div>
            <button type="button" onClick={() => fillDemoAccount("agent")}>
              <span className="demo-role-icon demo-role-icon-agent"><Bot size={17} /></span>
              <span className="demo-role-copy">
                <strong>Agent</strong>
                <span>agent@sogetrel.local</span>
                <small>agent123</small>
              </span>
            </button>
            <button type="button" onClick={() => fillDemoAccount("admin")}>
              <span className="demo-role-icon demo-role-icon-admin"><ShieldCheck size={17} /></span>
              <span className="demo-role-copy">
                <strong>Admin</strong>
                <span>admin@sogetrel.local</span>
                <small>admin123</small>
              </span>
            </button>
          </div>
        </div>
      )}

      <p className="auth-switch">
        Pas encore de compte ? <Link to="/signup">Créer un compte</Link>
      </p>
    </AuthLayout>
  );
}
