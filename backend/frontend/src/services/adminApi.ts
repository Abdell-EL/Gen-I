import axios from "axios";

import type {
  AuditDetailResponse,
  AuditListResponse,
  HealthResponse,
  IngestionJobDetail,
  IngestionJobSummary,
  IngestionUploadResponse,
  StatsResponse,
} from "../types/backend";
import type {
  AdminUser,
  CreateUserPayload,
  PasswordResetResponse,
  QuestionAnalyticsFilters,
  QuestionAnalyticsResponse,
  UpdateUserPayload,
  UserActivityFilters,
  UserActivityResponse,
  UserListFilters,
  UserListResponse,
} from "../types/admin";
import { apiClient } from "./apiClient";

export async function getSystemHealth() {
  const response = await apiClient.get<HealthResponse>("/health");
  return response.data;
}

export async function getSystemStats() {
  const response = await apiClient.get<StatsResponse>("/stats");
  return response.data;
}

export async function getLatestAudits(limit = 10) {
  const response = await apiClient.get<AuditListResponse>(
    "/audit/retrievals/latest",
    { params: { limit } },
  );
  return response.data;
}

export async function getAuditDetail(retrievalId: number) {
  const response = await apiClient.get<AuditDetailResponse>(
    `/audit/retrievals/${retrievalId}`,
  );
  return response.data;
}

export async function uploadKnowledgeDocx(file: File) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await apiClient.post<IngestionUploadResponse>(
    "/admin/ingestion/docx",
    formData,
    {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    },
  );
  return response.data;
}

export async function listIngestionJobs(limit = 20) {
  const response = await apiClient.get<IngestionJobSummary[]>(
    "/admin/ingestion/jobs",
    { params: { limit } },
  );
  return response.data;
}

export async function getIngestionJob(jobId: number) {
  const response = await apiClient.get<IngestionJobDetail>(
    `/admin/ingestion/jobs/${jobId}`,
  );
  return response.data;
}


function definedParams(values: Record<string, unknown>) {
  return Object.fromEntries(
    Object.entries(values).filter(
      ([, value]) => value !== undefined && value !== null && value !== "",
    ),
  );
}

export async function listUsers(params: UserListFilters = {}) {
  const response = await apiClient.get<UserListResponse>("/admin/users", {
    params: definedParams(params),
  });
  return response.data;
}

export async function getUser(userId: number) {
  const response = await apiClient.get<AdminUser>(`/admin/users/${userId}`);
  return response.data;
}

export async function createUser(payload: CreateUserPayload) {
  const response = await apiClient.post<AdminUser>("/admin/users", payload);
  return response.data;
}

export async function updateUser(userId: number, payload: UpdateUserPayload) {
  const response = await apiClient.patch<AdminUser>(
    `/admin/users/${userId}`,
    payload,
  );
  return response.data;
}

export async function resetUserPassword(userId: number, newPassword: string) {
  const response = await apiClient.post<PasswordResetResponse>(
    `/admin/users/${userId}/reset-password`,
    { new_password: newPassword },
  );
  return response.data;
}

export async function getUserAnalytics(params: UserActivityFilters = {}) {
  const response = await apiClient.get<UserActivityResponse>(
    "/admin/analytics/users",
    { params: definedParams(params) },
  );
  return response.data;
}

export async function getQuestionAnalytics(
  params: QuestionAnalyticsFilters = {},
) {
  const response = await apiClient.get<QuestionAnalyticsResponse>(
    "/admin/analytics/questions",
    { params: definedParams(params) },
  );
  return response.data;
}

export function getAdminErrorMessage(error: unknown) {
  if (!axios.isAxiosError(error)) {
    return "Une erreur inattendue est survenue. Réessayez.";
  }
  if (!error.response) {
    return error.code === "ECONNABORTED"
      ? "Le service met trop de temps à répondre. Réessayez."
      : "Impossible de joindre le service. Vérifiez votre connexion.";
  }

  const status = error.response.status;
  const detail =
    typeof error.response.data?.detail === "string"
      ? error.response.data.detail
      : "";
  if (status === 401) return "Votre session a expiré. Reconnectez-vous.";
  if (status === 403) return "Vous n’avez pas les permissions nécessaires.";
  if (status === 404) return "Utilisateur introuvable.";
  if (status === 409) {
    if (detail.toLowerCase().includes("email")) {
      return "Un utilisateur avec cet email existe déjà.";
    }
    if (detail.toLowerCase().includes("own account")) {
      return "Vous ne pouvez pas désactiver votre propre compte.";
    }
    if (detail.toLowerCase().includes("own admin role")) {
      return "Vous ne pouvez pas retirer votre propre rôle administrateur.";
    }
    if (detail.toLowerCase().includes("final active administrator")) {
      return "Le dernier administrateur actif ne peut pas être désactivé ou rétrogradé.";
    }
    return "Cette modification est impossible afin de préserver la sécurité des comptes.";
  }
  if (status === 422) {
    return "Certaines informations sont invalides. Vérifiez le formulaire.";
  }
  return "Le service a rencontré une erreur. Réessayez dans un instant.";
}
