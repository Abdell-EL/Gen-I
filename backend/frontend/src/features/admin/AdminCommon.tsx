import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useEffect, type ReactNode } from "react";

import { Button } from "../../components/ui/Button";
import { accountStatusLabel } from "../auth/activationFlow";
import type { UserRole } from "../../types/admin";
import { isEditableRole, roleLabel } from "./adminUtils";

export function RolePill({ role }: { role: UserRole }) {
  return (
    <span className={`admin-role-pill role-${isEditableRole(role) ? role : "legacy"}`}>
      {roleLabel(role)}
    </span>
  );
}

export function StatusPill({ active }: { active: boolean }) {
  return (
    <span className={`admin-status-pill ${active ? "active" : "inactive"}`}>
      <span />
      {active ? "Actif" : "Inactif"}
    </span>
  );
}

export function AccountStatusPill({ user }: { user: { is_active: boolean; activation_status: "pending" | "active" } }) {
  const label = accountStatusLabel(user);
  const className = !user.is_active ? "inactive" : user.activation_status === "pending" ? "pending" : "active";
  return <span className={`admin-status-pill ${className}`}>
    <span />
    {label}
  </span>;
}

export function AdminDialog({
  title,
  description,
  children,
  onClose,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  onClose: () => void;
}) {
  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div className="admin-dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="admin-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="admin-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <h2 id="admin-dialog-title">{title}</h2>
            {description && <p>{description}</p>}
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Fermer">
            <X size={18} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}

export function Pagination({
  page,
  pages,
  total,
  onPageChange,
}: {
  page: number;
  pages: number;
  total: number;
  onPageChange: (page: number) => void;
}) {
  return (
    <div className="admin-pagination">
      <span>{total} résultat{total > 1 ? "s" : ""}</span>
      <div>
        <Button type="button" variant="ghost" disabled={page <= 1} onClick={() => onPageChange(page - 1)} icon={<ChevronLeft size={15} />}>Précédent</Button>
        <strong>Page {page} sur {Math.max(pages, 1)}</strong>
        <Button type="button" variant="ghost" disabled={pages === 0 || page >= pages} onClick={() => onPageChange(page + 1)} icon={<ChevronRight size={15} />}>Suivant</Button>
      </div>
    </div>
  );
}
