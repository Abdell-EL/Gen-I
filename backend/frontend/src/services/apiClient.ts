import axios from "axios";

import { getStoredToken } from "./authStorage.ts";

const viteEnvironment = (
  import.meta as ImportMeta & { env?: { VITE_API_BASE_URL?: string } }
).env;
const configuredApiBaseUrl =
  viteEnvironment?.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

export const API_BASE_URL = configuredApiBaseUrl.replace(/\/+$/, "");

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20_000,
  headers: {
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.request.use((config) => {
  const token = getStoredToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export const SESSION_EXPIRED_EVENT = "auth:session-expired";

// A 401 on /auth/signin means "wrong email/password", not an expired
// session — must not be treated the same way as every other 401.
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (
      axios.isAxiosError(error) &&
      error.response?.status === 401 &&
      !error.config?.url?.includes("/auth/signin")
    ) {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    }
    return Promise.reject(error);
  },
);

export function getApiErrorMessage(error: unknown) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (error.code === "ECONNABORTED") {
      return "Le service met trop de temps à répondre. Réessayez dans un instant.";
    }
    return error.message;
  }

  if (error instanceof Error) return error.message;

  return "Une erreur inattendue est survenue.";
}
