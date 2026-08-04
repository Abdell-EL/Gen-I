import { Link } from "react-router-dom";

export function BrandLockup({ compact = false }: { compact?: boolean }) {
  return (
    <Link className={`brand-lockup ${compact ? "brand-compact" : ""}`} to="/">
      <span className="brand-mark" aria-hidden="true">GS</span>
      {!compact && (
        <span className="brand-product">
          <strong>Genius Services</strong>
          <small>Plateforme de connaissance interne</small>
        </span>
      )}
    </Link>
  );
}
