import { ArrowLeft, Compass } from "lucide-react";
import { Link } from "react-router-dom";

import { BrandLockup } from "../components/layout/BrandLockup";

export function NotFoundPage() {
  return (
    <main className="not-found-page">
      <BrandLockup />
      <div className="not-found-card">
        <span className="not-found-code">404</span>
        <Compass size={34} />
        <h1>Cette page n’existe pas.</h1>
        <p>
          Le lien est peut-être obsolète ou l’espace demandé a été déplacé.
        </p>
        <Link className="button button-primary" to="/">
          <ArrowLeft size={16} />
          Retour à l’accueil
        </Link>
      </div>
    </main>
  );
}
