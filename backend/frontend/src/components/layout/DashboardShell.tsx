import { Bell, LogOut, Search } from "lucide-react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../../app/useAuth";
import { BrandLockup } from "./BrandLockup";

export function DashboardShell({
  children,
  eyebrow,
  title,
  description,
  sidebar,
  className,
  consoleLabel = "Console d'administration",
  searchLabel = "Rechercher",
  searchShortcut = "Ctrl K",
  showNotifications = false,
  hideHeading = false,
  userDisplayName,
}: {
  children: ReactNode;
  eyebrow: string;
  title: string;
  description: string;
  sidebar?: ReactNode;
  className?: string;
  consoleLabel?: string;
  searchLabel?: string;
  searchShortcut?: string;
  showNotifications?: boolean;
  hideHeading?: boolean;
  userDisplayName?: string;
}) {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const displayUserName = userDisplayName ?? user?.full_name ?? "";

  function handleLogout() {
    signOut();
    navigate("/signin", { replace: true });
  }

  return (
    <div
      className={[
        "dashboard-layout",
        sidebar ? "with-sidebar" : "",
        className,
      ].filter(Boolean).join(" ")}
    >
      {sidebar}
      <div className="dashboard-main">
        <header className="dashboard-topbar">
          {sidebar ? (
            <div className="admin-topbar-title">
              <small>{consoleLabel}</small>
              <strong>{title}</strong>
            </div>
          ) : (
            <BrandLockup compact />
          )}
          <div className="dashboard-user-actions">
            {sidebar && (
              <div className="topbar-search" aria-label="Recherche bientôt disponible">
                <Search size={15} />
                <span>{searchLabel}</span>
                <kbd>{searchShortcut}</kbd>
              </div>
            )}
            {showNotifications && (
              <button
                type="button"
                className="icon-button notification-button"
                aria-label="Notifications"
                title="Notifications"
              >
                <Bell size={17} />
              </button>
            )}
            <div className="user-chip">
              <span className="user-avatar">{displayUserName.slice(0, 1).toUpperCase()}</span>
              <div>
                <strong>{displayUserName}</strong>
                <small>{user?.role === "admin" ? "Administrateur" : "Agent"}</small>
              </div>
            </div>
            <button
              type="button"
              className="icon-button"
              onClick={handleLogout}
              aria-label="Se déconnecter"
              title="Se déconnecter"
            >
              <LogOut size={18} />
            </button>
          </div>
        </header>

        <main className="dashboard-content">
          {!hideHeading && (
            <div className="page-heading">
              <p className="eyebrow">{eyebrow}</p>
              <h1>{title}</h1>
              <p>{description}</p>
            </div>
          )}
          {children}
        </main>
      </div>
    </div>
  );
}
