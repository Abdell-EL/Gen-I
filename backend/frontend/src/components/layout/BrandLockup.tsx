import { Link } from "react-router-dom";

import logoLeft from "../../assets/logo-left.webp";
import logoRight from "../../assets/logo-right.jpg";

export function BrandLockup({ compact = false }: { compact?: boolean }) {
  return (
    <Link className={`brand-lockup ${compact ? "brand-compact" : ""}`} to="/">
      <img src={logoLeft} alt="Sogetrel Telecom Networks" />
      <span className="brand-divider" aria-hidden="true" />
      <img src={logoRight} alt="Orange" className="orange-logo" />
      {!compact && (
        <span className="brand-product">
          <strong>FDE Knowledge</strong>
          <small>Plateforme interne</small>
        </span>
      )}
    </Link>
  );
}
