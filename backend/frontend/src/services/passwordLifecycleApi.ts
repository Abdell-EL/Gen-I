import axios from "axios";

import { passwordResetFailureState, type PasswordResetViewState } from "../features/auth/passwordResetFlow.ts";
import { apiClient, API_BASE_URL } from "./apiClient.ts";

export type ChangePasswordRequest = {
  current_password: string;
  new_password: string;
  new_password_confirmation: string;
};

export type ChangePasswordResponse = {
  message: "Mot de passe modifié avec succès.";
  reauthentication_required: true;
};

export type ForgotPasswordRequest = {
  email: string;
};

export type ForgotPasswordResponse = {
  message: string;
  reset_url: string | null;
};

export type ResetPasswordValidationRequest = {
  token: string;
};

export type ResetPasswordValidationResponse = {
  valid: true;
  expires_at: string;
};

export type ResetPasswordCompletionRequest = {
  token: string;
  password: string;
  password_confirmation: string;
};

export type ResetPasswordCompletionResponse = {
  message: "Mot de passe réinitialisé avec succès.";
  reauthentication_required: true;
};

export const publicPasswordLifecycleClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20_000,
  headers: { "Content-Type": "application/json" },
});

export class PasswordResetRequestError extends Error {
  state: PasswordResetViewState;

  constructor(state: PasswordResetViewState) {
    super("La demande de réinitialisation n’a pas pu être traitée.");
    this.name = "PasswordResetRequestError";
    this.state = state;
  }
}

export class PasswordLifecycleFormError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PasswordLifecycleFormError";
  }
}

function lifecycleError(error: unknown) {
  if (!axios.isAxiosError(error)) return new PasswordResetRequestError("failed");
  const detail = error.response?.data?.detail;
  const code = detail && typeof detail === "object" ? detail.code : undefined;
  return new PasswordResetRequestError(passwordResetFailureState(error.response?.status, code));
}

function detailText(error: unknown) {
  if (!axios.isAxiosError(error)) return "";
  const detail = error.response?.data?.detail;
  return typeof detail === "string" ? detail : "";
}

export function changePasswordErrorMessage(error: unknown) {
  if (!axios.isAxiosError(error)) {
    return "Le changement de mot de passe a échoué. Réessayez dans un instant.";
  }
  const detail = detailText(error).toLowerCase();
  if (error.response?.status === 400 && detail.includes("current password")) {
    return "Le mot de passe actuel est incorrect.";
  }
  if (error.response?.status === 401) {
    return "Votre session a expiré. Reconnectez-vous.";
  }
  if (error.response?.status === 422) {
    if (detail.includes("confirmation")) return "Les nouveaux mots de passe ne correspondent pas.";
    if (detail.includes("different")) return "Le nouveau mot de passe doit être différent de l’ancien.";
    if (detail.includes("empty")) return "Le nouveau mot de passe ne peut pas être vide.";
    if (detail.includes("utf-8") || detail.includes("too long")) {
      return "Le nouveau mot de passe dépasse la limite autorisée.";
    }
    return "Le nouveau mot de passe ne respecte pas la politique de sécurité.";
  }
  return "Le changement de mot de passe a échoué. Réessayez dans un instant.";
}

export function resetCompletionErrorMessage(error: unknown) {
  if (error instanceof PasswordLifecycleFormError) return error.message;
  if (!axios.isAxiosError(error)) {
    return "La réinitialisation a échoué. Réessayez dans un instant.";
  }
  const detail = detailText(error).toLowerCase();
  if (error.response?.status === 422) {
    if (detail.includes("confirmation")) return "Les mots de passe ne correspondent pas.";
    if (detail.includes("different")) return "Le nouveau mot de passe doit être différent de l’ancien.";
    if (detail.includes("empty")) return "Le mot de passe ne peut pas être vide.";
    if (detail.includes("utf-8") || detail.includes("too long")) {
      return "Le mot de passe dépasse la limite autorisée.";
    }
    return "Le mot de passe ne respecte pas la politique de sécurité.";
  }
  return "La réinitialisation a échoué. Réessayez dans un instant.";
}

export async function changeOwnPassword(payload: ChangePasswordRequest) {
  const response = await apiClient.post<ChangePasswordResponse>(
    "/auth/password/change",
    payload,
  );
  return response.data;
}

export async function requestPasswordReset(payload: ForgotPasswordRequest) {
  const response = await publicPasswordLifecycleClient.post<ForgotPasswordResponse>(
    "/auth/password/forgot",
    payload,
  );
  return response.data;
}

export async function validatePasswordResetToken(
  payload: ResetPasswordValidationRequest,
  signal?: AbortSignal,
) {
  try {
    const response = await publicPasswordLifecycleClient.post<ResetPasswordValidationResponse>(
      "/auth/password/reset/validate",
      payload,
      { signal },
    );
    return response.data;
  } catch (error) {
    if (axios.isCancel(error)) throw error;
    throw lifecycleError(error);
  }
}

export async function completePasswordReset(payload: ResetPasswordCompletionRequest) {
  try {
    const response = await publicPasswordLifecycleClient.post<ResetPasswordCompletionResponse>(
      "/auth/password/reset/complete",
      payload,
    );
    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 400) {
      throw lifecycleError(error);
    }
    throw error;
  }
}
