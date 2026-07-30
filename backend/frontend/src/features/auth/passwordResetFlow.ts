export type PasswordResetViewState =
  | "validating"
  | "valid"
  | "invalid"
  | "expired"
  | "consumed"
  | "failed"
  | "complete";

export type PasswordResetFailureCode = "invalid" | "expired" | "consumed";

export function passwordResetFailureState(
  status: number | undefined,
  code: unknown,
): PasswordResetViewState {
  if (code === "expired") return "expired";
  if (code === "consumed") return "consumed";
  if (code === "invalid" || status === 400 || status === 404 || status === 422) {
    return "invalid";
  }
  return "failed";
}

export function consumePasswordResetToken(
  href: string,
  replace: (path: string) => void,
): string | null {
  const url = new URL(href);
  const token = url.searchParams.get("token");
  url.searchParams.delete("token");
  const query = url.searchParams.toString();
  replace(`${url.pathname}${query ? `?${query}` : ""}${url.hash}`);
  return token && token.length > 0 ? token : null;
}

export function passwordResetStateCopy(state: PasswordResetViewState) {
  if (state === "expired") {
    return {
      title: "Lien expiré",
      message: "Ce lien de réinitialisation a expiré. Demandez un nouveau lien.",
    };
  }
  if (state === "consumed") {
    return {
      title: "Lien déjà utilisé",
      message: "Ce lien a déjà été utilisé pour réinitialiser un mot de passe.",
    };
  }
  if (state === "failed") {
    return {
      title: "Service indisponible",
      message: "La validation du lien a échoué. Réessayez dans un instant.",
    };
  }
  return {
    title: "Lien invalide",
    message: "Ce lien de réinitialisation n’est pas valide.",
  };
}

export function passwordsMatch(password: string, confirmation: string) {
  return password === confirmation;
}
