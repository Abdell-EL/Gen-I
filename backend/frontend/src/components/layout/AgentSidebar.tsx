import {
  Activity,
  BarChart3,
  Bot,
  Home,
  LayoutDashboard,
  Moon,
  RefreshCw,
  ScrollText,
} from "lucide-react";
import { Link } from "react-router-dom";

import { useAuth } from "../../app/useAuth";
import { BrandLockup } from "./BrandLockup";

const navigationItems = [
  { label: "Accueil", icon: Home, adminOnly: false },
  { label: "Santé système", icon: Activity, adminOnly: true },
  { label: "Audits", icon: ScrollText, adminOnly: true },
  { label: "Statistiques", icon: BarChart3, adminOnly: true },
  { label: "Mise à jour", icon: RefreshCw, adminOnly: true },
];

export function AgentSidebar() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  return (
    <aside className="agent-sidebar" aria-label="Espace Agent">
      <BrandLockup />

      <div className="agent-workspace-switcher" aria-label="Espaces de travail">
        <button type="button" className="active" aria-current="page">
          <Bot size={18} />
          <span>
            <strong>Assistant FDE</strong>
            <small>Assistant de connaissance</small>
          </span>
        </button>
        {isAdmin ? (
          <Link to="/admin">
            <LayoutDashboard size={18} />
            <span>
              <strong>Espace Admin</strong>
              <small>Supervision & audits</small>
            </span>
          </Link>
        ) : (
          <button
            type="button"
            disabled
            title="Réservé aux administrateurs"
          >
            <LayoutDashboard size={18} />
            <span>
              <strong>Espace Admin</strong>
              <small>Supervision & audits</small>
            </span>
          </button>
        )}
      </div>

      <span className="agent-sidebar-label">Navigation</span>
      <nav aria-label="Navigation Agent">
        {navigationItems.map((item) => {
          const Icon = item.icon;
          const isLocked = item.adminOnly && !isAdmin;

          return (
            <button
              key={item.label}
              type="button"
              disabled={isLocked}
              title={isLocked ? `${item.label} - réservé aux administrateurs` : item.label}
            >
              <Icon size={18} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="agent-sidebar-status">
        <span className="status-dot" />
        <div>
          <strong>API FastAPI</strong>
          <small>Environnement local</small>
        </div>
      </div>

      <div className="agent-sidebar-toggle" aria-label="Mode sombre actif">
        <Moon size={16} />
        <span>Mode sombre</span>
        <span className="toggle-track" aria-hidden="true">
          <span />
        </span>
      </div>

      <footer className="agent-sidebar-footer">
        © 2026 Sogetrel
        <span>Plateforme interne FDE</span>
      </footer>
    </aside>
  );
}
