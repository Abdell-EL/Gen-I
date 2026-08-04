import { Link } from "react-router-dom";
import geniusServicesLogo from "../../assets/genius-services-logo.jpg";

export function BrandLockup({ compact = false }: { compact?: boolean }) {
  return (
    <Link className={`brand-lockup ${compact ? "brand-compact" : ""}`} to="/">
      <img src={geniusServicesLogo} alt="Genius Services" />
      {!compact && (
        <span className="brand-product">
          <small>Plateforme de connaissance interne</small>
        </span>
      )}
    </Link>
  );
}