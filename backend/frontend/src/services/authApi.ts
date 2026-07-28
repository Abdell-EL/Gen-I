import axios from "axios";

import type { AuthResponse, AuthUser } from "../types/auth";
import { apiClient } from "./apiClient";

export const GENERIC_LOGIN_ERROR = "Email ou mot de passe incorrect.";

export class AuthenticationError extends Error {
  constructor(message = GENERIC_LOGIN_ERROR) {
    super(message);
    this.name = "AuthenticationError";
  }
}

function isAuthUser(value: unknown): value is AuthUser {
  if (!value || typeof value !== "object") return false;
  const user = value as Record<string, unknown>;
  return (
    typeof user.id === "number" &&
    typeof user.full_name === "string" &&
    typeof user.email === "string" &&
    (user.role === "agent" || user.role === "admin") &&
    typeof user.is_active === "boolean"
  );
}

function isAuthResponse(value: unknown): value is AuthResponse {
  if (!value || typeof value !== "object") return false;
  const response = value as Record<string, unknown>;
  return (
    typeof response.access_token === "string" &&
    response.access_token.length > 0 &&
    response.token_type === "bearer" &&
    typeof response.expires_in === "number" &&
    isAuthUser(response.user)
  );
}

export async function signIn(email: string, password: string, signal?: AbortSignal) {
  try {
    const response = await apiClient.post<unknown>(
      "/auth/signin",
      { email, password },
      { signal },
    );
    if (!isAuthResponse(response.data)) throw new AuthenticationError();
    return response.data;
  } catch (error) {
    if (axios.isCancel(error)) throw error;
    throw new AuthenticationError();
  }
}

export async function getCurrentUser(accessToken: string, signal?: AbortSignal) {
  const response = await apiClient.get<unknown>("/auth/me", {
    headers: { Authorization: `Bearer ${accessToken}` },
    signal,
  });
  if (!isAuthUser(response.data)) {
    throw new AuthenticationError("La session est invalide.");
  }
  return response.data;
}
