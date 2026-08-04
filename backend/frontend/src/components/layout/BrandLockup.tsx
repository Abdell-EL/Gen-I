import { Link } from "react-router-dom";

export function BrandLockup({ compact = false }: { compact?: boolean }) {
  return (
    <Link className={`brand-lockup ${compact ? "brand-compact" : ""}`} to="/">
      <span className="brand-name">Genius Services</span>
      {!compact && (
        <span className="brand-tagline">Plateforme de connaissance interne</span>
      )}
    </Link>
  );
}