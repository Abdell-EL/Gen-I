import { ArrowLeft, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { BrandLockup } from "./BrandLockup";

export function AuthLayout({
  eyebrow,
  title,
  description,
  children,
  pageClassName,
}: {
  eyebrow: string;
  title: ReactNode;
  description: string;
  children: ReactNode;
  pageClassName?: string;
}) {
  return (
    <main className={["auth-page", pageClassName].filter(Boolean).join(" ")}>
      <section className="auth-brand-panel">
        <div className="auth-orbit auth-orbit-one" aria-hidden="true" />
        <div className="auth-orbit auth-orbit-two" aria-hidden="true" />
        <span className="shooting-star star-one" aria-hidden="true" />
        <span className="shooting-star star-two" aria-hidden="true" />
        <span className="shooting-star star-three" aria-hidden="true" />
        <BrandLockup />
        <div className="auth-brand-copy">
          <span className="section-kicker">Plateforme FDE</span>
          <h1>
            La connaissance métier, accessible avec confiance
            <span className="auth-accent-dot">.</span>
          </h1>
          <p>
            Une expérience interne conçue pour accélérer les décisions tout en
            conservant la preuve, la source et la trace d’audit.
          </p>
        </div>
        <div className="auth-trust-note">
          <ShieldCheck size={20} />
          <div>
            <strong>Accès contrôlé</strong>
            <span>
              Authentification connectée au backend.
            </span>
          </div>
        </div>
      </section>

      <section className="auth-form-panel">
        <Link className="back-link" to="/">
          <ArrowLeft size={16} />
          Retour à l’accueil
        </Link>
        <div className="auth-form-wrap">
          <p className="eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
          <p className="auth-description">{description}</p>
          {children}
        </div>
      </section>
    </main>
  );
}
