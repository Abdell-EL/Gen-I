import {
  Activity,
  BarChart3,
  Bot,
  Home,
  LayoutDashboard,
  RefreshCw,
  ScrollText,
} from "lucide-react";
import { Link } from "react-router-dom";

import { useAuth } from "../../app/useAuth";
import { BrandLockup } from "./BrandLockup";

export type AdminSection =
  | "home"
  | "health"
  | "audits"
  | "stats"
  | "updates";

const items = [
  { id: "home", label: "Accueil", icon: Home },
  { id: "health", label: "Santé système", icon: Activity },
  { id: "audits", label: "Audits", icon: ScrollText },
  { id: "stats", label: "Statistiques", icon: BarChart3 },
  { id: "updates", label: "Mise à jour", icon: RefreshCw },
] satisfies Array<{
  id: AdminSection;
  label: string;
  icon: typeof Home;
}>;

export function AdminSidebar({
  activeSection,
  onChange,
}: {
  activeSection: AdminSection;
  onChange: (section: AdminSection) => void;
}) {
  const { user } = useAuth();

  return (
    <aside className="admin-sidebar" aria-label="Console d’administration">
      <BrandLockup />
      <div className="sidebar-heading">
        <span className="sidebar-mark">FDE</span>
        <div>
          <strong>Console Admin</strong>
          <small>Supervision & audit</small>
        </div>
      </div>

      <div className="sidebar-workspaces" aria-label="Espaces de travail">
        <Link to="/agent" title="Console Agent">
          <Bot size={18} />
          <span>Console Agent</span>
        </Link>
        <button
          type="button"
          className="active"
          title="Console Admin"
          onClick={() => onChange("home")}
        >
          <LayoutDashboard size={18} />
          <span>Console Admin</span>
        </button>
      </div>

      <div className="sidebar-user">
        <span>{user?.name.slice(0, 1).toUpperCase()}</span>
        <div>
          <strong>{user?.name}</strong>
          <small>Administrateur</small>
        </div>
      </div>

      <span className="sidebar-section-label">Navigation</span>
      <nav aria-label="Navigation administration">
        {items.map((item) => {
          const Icon = item.icon;
          const isActive = activeSection === item.id;
          return (
            <button
              key={item.id}
              type="button"
              className={isActive ? "active" : ""}
              onClick={() => onChange(item.id)}
              title={item.label}
              aria-current={isActive ? "page" : undefined}
            >
              <Icon size={18} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="sidebar-note">
        <span className="status-dot" />
        <div>
          <strong>API FastAPI</strong>
          <small>Environnement local</small>
        </div>
      </div>
    </aside>
  );
}
