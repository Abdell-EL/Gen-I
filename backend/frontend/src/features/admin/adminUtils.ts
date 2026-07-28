import type { UserRole } from "../../types/admin";

export function isEditableRole(role: UserRole): role is "admin" | "agent" {
  return role === "admin" || role === "agent";
}

export function roleLabel(role: UserRole) {
  if (role === "admin") return "Administrateur";
  if (role === "agent") return "Agent";
  return "Rôle historique";
}

export function formatAdminDate(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
