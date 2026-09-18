import { Link } from "react-router-dom";

import geniusServicesLogo from "../../assets/genius-services-logo.png";

export function BrandLockup({ compact = false }: { compact?: boolean }) {
  return (
    <Link className={`brand-lockup ${compact ? "brand-compact" : ""}`} to="/">
      <img className="brand-wordmark" src={geniusServicesLogo} alt="Genius Services" />
      {!compact && (
        <span className="brand-tagline">Plateforme de connaissance interne</span>
      )}
    </Link>
  );
}