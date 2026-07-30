export type ActivationViewState =
  | "validating" | "valid" | "invalid" | "expired" | "consumed" | "failed" | "complete";

export type ActivationFailureCode = "invalid" | "expired" | "consumed";

export function activationFailureState(status: number | undefined, code: unknown): ActivationViewState {
  if (code === "expired") return "expired";
  if (code === "consumed") return "consumed";
  if (code === "invalid" || status === 400 || status === 404 || status === 422) return "invalid";
  return "failed";
}

export function consumeActivationToken(
  href: string,
  replace: (path: string) => void,
): string | null {
  const url = new URL(href);
  const token = url.searchParams.get("token");
  url.searchParams.delete("token");
  const query = url.searchParams.toString();
  replace(`${url.pathname}${query ? `?${query}` : ""}${url.hash}`);
  return token?.trim() || null;
}

export function accountStatusLabel(user: { is_active: boolean; activation_status: "pending" | "active" }) {
  if (!user.is_active) return "Désactivé administrativement";
  return user.activation_status === "pending" ? "En attente d’activation" : "Actif";
}

export function invitePayload(fullName: string, email: string, role: "admin" | "agent") {
  return { full_name: fullName.trim(), email: email.trim(), role };
}
