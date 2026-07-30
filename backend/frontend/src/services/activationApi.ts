import axios from "axios";

import { API_BASE_URL } from "./apiClient";
import { activationFailureState, type ActivationViewState } from "../features/auth/activationFlow";

const publicActivationClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20_000,
  headers: { "Content-Type": "application/json" },
});

export class ActivationRequestError extends Error {
  state: ActivationViewState;
  constructor(state: ActivationViewState) {
    super("La demande d’activation n’a pas pu être traitée.");
    this.name = "ActivationRequestError";
    this.state = state;
  }
}

function requestError(error: unknown) {
  if (!axios.isAxiosError(error)) return new ActivationRequestError("failed");
  const detail = error.response?.data?.detail;
  const code = detail && typeof detail === "object" ? detail.code : undefined;
  return new ActivationRequestError(activationFailureState(error.response?.status, code));
}

export async function validateActivationToken(token: string, signal?: AbortSignal) {
  try {
    return (await publicActivationClient.post<{ valid: true; expires_at: string }>(
      "/auth/activation/validate", { token }, { signal },
    )).data;
  } catch (error) {
    if (axios.isCancel(error)) throw error;
    throw requestError(error);
  }
}

export async function completeActivation(token: string, password: string, passwordConfirmation: string) {
  try {
    return (await publicActivationClient.post<{ status: "activated"; user_id: number }>(
      "/auth/activation/complete",
      { token, password, password_confirmation: passwordConfirmation },
    )).data;
  } catch (error) {
    throw requestError(error);
  }
}
