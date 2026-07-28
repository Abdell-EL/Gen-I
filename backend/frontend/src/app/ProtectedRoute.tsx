import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { LoadingState } from "../components/ui/LoadingState";
import type { UserRole } from "../types/auth";
import { useAuth } from "./useAuth";

type ProtectedRouteProps = {
  children: ReactNode;
  roles: UserRole[];
};

export function ProtectedRoute({ children, roles }: ProtectedRouteProps) {
  const { user, isInitialising, isAuthenticated } = useAuth();
  const location = useLocation();

  if (isInitialising) {
    return (
      <div className="route-loading">
        <LoadingState label="Vérification de la session…" />
      </div>
    );
  }

  if (!isAuthenticated || !user) {
    return (
      <Navigate
        to={`/signin?redirect=${encodeURIComponent(`${location.pathname}${location.search}${location.hash}`)}`}
        replace
      />
    );
  }

  if (!roles.includes(user.role)) {
    return <Navigate to={user.role === "admin" ? "/admin" : "/agent"} replace />;
  }

  return children;
}
