import { Link } from "react-router-dom";

export function BrandLockup({ compact = false }: { compact?: boolean }) {
  return (
    <Link className={`brand-lockup ${compact ? "brand-compact" : ""}`} to="/">
      <span className="brand-mark" aria-hidden="true">
        <img
          className="brand-logo"
          src="/brand/logo.svg"
          alt=""
          onError={(event) => {
            event.currentTarget.style.display = "none";
          }}
        />
        <span className="brand-mark-fallback">GS</span>
      </span>
      {!compact && (
        <span className="brand-product">
          <strong>Genius Services</strong>
          <small>Plateforme de connaissance interne</small>
        </span>
      )}
    </Link>
  );
}
