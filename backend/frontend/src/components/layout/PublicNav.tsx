import { Link } from "react-router-dom";

import { BrandLockup } from "./BrandLockup";

export function PublicNav() {
  return (
    <header className="public-nav">
      <BrandLockup />
      <nav aria-label="Navigation principale">
        <div className="public-nav-links">
          <a className="nav-text-link" href="#solution">Solution</a>
          <Link className="nav-text-link" to="/agent">Agent</Link>
          <Link className="nav-text-link" to="/admin">Admin</Link>
          <a className="nav-text-link" href="#securite">Sécurité</a>
        </div>
        <Link className="nav-text-link nav-signin" to="/signin">
          Se connecter
        </Link>
        <Link className="button button-primary nav-cta" to="/signup">
          Créer un compte
        </Link>
      </nav>
    </header>
  );
}
