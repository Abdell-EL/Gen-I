import {
  Bot,
  LockKeyhole,
  Mail,
  ShieldCheck,
  UserPlus,
  UserRound,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { useAuth } from "../app/useAuth";
import { AuthLayout } from "../components/layout/AuthLayout";
import { Button } from "../components/ui/Button";
import { ErrorState } from "../components/ui/ErrorState";
import { getApiErrorMessage } from "../services/apiClient";
import type { UserRole } from "../types/auth";

export function SignUpPage() {
  const { signUp, mode } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [role, setRole] = useState<UserRole>(
    searchParams.get("role") === "admin" ? "admin" : "agent",
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (password.length < 8) {
      setError("Le mot de passe doit contenir au moins 8 caractères.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Les mots de passe ne correspondent pas.");
      return;
    }

    setLoading(true);
    try {
      const user = await signUp({ name, email, password, role });
      navigate(user.role === "admin" ? "/admin" : "/agent");
    } catch (submitError) {
      setError(getApiErrorMessage(submitError));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      eyebrow="Création de compte"
      title={<>Rejoignez la plateforme FDE<span className="auth-accent-dot">.</span></>}
      pageClassName="auth-page-signin auth-page-signup"
      description={
        mode === "demo"
          ? "Le compte sera créé localement pour la démonstration. Il ne constitue pas un compte de production."
          : "Créez votre identité pour accéder aux services adaptés à votre rôle."
      }
    >
      <form className="auth-form" onSubmit={handleSubmit}>
        <div className="form-field">
          <label htmlFor="signup-name">Nom complet</label>
          <div className="input-shell">
            <UserRound size={17} aria-hidden="true" />
            <input
              id="signup-name"
              type="text"
              autoComplete="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </div>
        </div>
        <div className="form-field">
          <label htmlFor="signup-email">Adresse e-mail</label>
          <div className="input-shell">
            <Mail size={17} aria-hidden="true" />
            <input
              id="signup-email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </div>
        </div>
        <fieldset className="role-selector">
          <legend>Rôle souhaité</legend>
          <label className={role === "agent" ? "selected" : ""}>
            <input
              type="radio"
              name="role"
              value="agent"
              checked={role === "agent"}
              onChange={() => setRole("agent")}
            />
            <Bot size={19} aria-hidden="true" />
            <span>
              <strong>Agent</strong>
              <small>Interroger la base de connaissance</small>
            </span>
          </label>
          <label className={role === "admin" ? "selected" : ""}>
            <input
              type="radio"
              name="role"
              value="admin"
              checked={role === "admin"}
              onChange={() => setRole("admin")}
            />
            <ShieldCheck size={19} aria-hidden="true" />
            <span>
              <strong>Administrateur</strong>
              <small>Superviser la plateforme</small>
            </span>
          </label>
        </fieldset>
        <div className="form-field-grid">
          <div className="form-field">
            <label htmlFor="signup-password">Mot de passe</label>
            <div className="input-shell">
              <LockKeyhole size={17} aria-hidden="true" />
              <input
                id="signup-password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                minLength={8}
                required
              />
            </div>
          </div>
          <div className="form-field">
            <label htmlFor="signup-confirm-password">Confirmation</label>
            <div className="input-shell">
              <LockKeyhole size={17} aria-hidden="true" />
              <input
                id="signup-confirm-password"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                minLength={8}
                required
              />
            </div>
          </div>
        </div>

        {error && <ErrorState message={error} />}

        <Button
          type="submit"
          className="full-width"
          disabled={loading}
          icon={<UserPlus size={17} />}
        >
          {loading ? "Création…" : "Créer mon compte"}
        </Button>
      </form>

      <p className="auth-switch">
        Déjà inscrit ? <Link to="/signin">Se connecter</Link>
      </p>
    </AuthLayout>
  );
}
