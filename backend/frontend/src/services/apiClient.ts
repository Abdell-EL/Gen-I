import axios from "axios";

import { getStoredToken } from "./authStorage";

const configuredApiBaseUrl =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

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
