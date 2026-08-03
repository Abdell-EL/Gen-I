import axios from "axios";

import type {
  AuditDetailResponse,
  AuditListResponse,
  HealthResponse,
  DocumentVersionHistoryItem,
  DocumentVersionUpdateResponse,
  IngestionJobDetail,
  IngestionJobSummary,
  IngestionUploadResponse,
  StatsResponse,
} from "../types/backend";
import type {
  AdminUser,
  InvitedUserResponse,
  InvitationResendResponse,
  AdminFeedbackItem,
  ArticleAnalyticsResponse,
  ArticleFilters,
  CreateUserPayload,
  KnowledgeFilters,
  LowConfidenceFilters,
  LowConfidenceResponse,
  FeedbackListResponse,
  FeedbackSummary,
  PasswordResetResponse,
  QuestionAnalyticsFilters,
  QuestionAnalyticsResponse,
  RetrievalDrillDown,
  ScoreDistributionResponse,
  TrendingQuestionsResponse,
  UpdateUserPayload,
  UnreferencedContentResponse,
  UnreferencedFilters,
  UserActivityFilters,
  UserActivityResponse,
  UserListFilters,
  UserListResponse,
} from "../types/admin";
import { apiClient } from "./apiClient";
import { buildKnowledgeParams, KNOWLEDGE_ENDPOINTS } from "./knowledgeApiConfig";

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

export type DocumentVersionUpdatePayload = {
  sourceDocumentId: number;
  file: File;
  changeReason?: string;
  changeSummary?: string;
  effectiveAt?: string;
};

export async function uploadKnowledgeDocumentVersion({
  sourceDocumentId,
  file,
  changeReason,
  changeSummary,
  effectiveAt,
}: DocumentVersionUpdatePayload) {
  const formData = new FormData();
  formData.append("file", file);
  if (changeReason) formData.append("change_reason", changeReason);
  if (changeSummary) formData.append("change_summary", changeSummary);
  if (effectiveAt) formData.append("effective_at", effectiveAt);

  const response = await apiClient.post<DocumentVersionUpdateResponse>(
    `/admin/knowledge/documents/${sourceDocumentId}/versions`,
    formData,
    {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    },
  );
  return response.data;
}

export async function listKnowledgeDocumentVersions(sourceDocumentId: number) {
  const response = await apiClient.get<DocumentVersionHistoryItem[]>(
    `/admin/knowledge/documents/${sourceDocumentId}/versions`,
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
  const response = await apiClient.post<InvitedUserResponse>("/admin/users", payload);
  return response.data;
}

export async function resendUserInvitation(userId: number) {
  const response = await apiClient.post<InvitationResendResponse>(
    `/admin/users/${userId}/resend-invitation`,
  );
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

export async function getTrendingQuestions(params: KnowledgeFilters & { previous_period?: boolean; limit?: number } = {}) {
  const response = await apiClient.get<TrendingQuestionsResponse>(
    KNOWLEDGE_ENDPOINTS.trending, { params: buildKnowledgeParams(params) },
  );
  return response.data;
}

export async function getLowConfidence(params: LowConfidenceFilters = {}) {
  const response = await apiClient.get<LowConfidenceResponse>(
    KNOWLEDGE_ENDPOINTS.lowConfidence, { params: buildKnowledgeParams(params) },
  );
  return response.data;
}

export async function getScoreDistribution(params: KnowledgeFilters & { bucket_size?: number; score_basis?: "top_score" | "all_results" } = {}) {
  const response = await apiClient.get<ScoreDistributionResponse>(
    KNOWLEDGE_ENDPOINTS.distribution, { params: buildKnowledgeParams(params) },
  );
  return response.data;
}

export async function getArticleAnalytics(params: ArticleFilters = {}) {
  const response = await apiClient.get<ArticleAnalyticsResponse>(
    KNOWLEDGE_ENDPOINTS.articles, { params: buildKnowledgeParams(params) },
  );
  return response.data;
}

export async function getUnreferencedContent(params: UnreferencedFilters = {}) {
  const response = await apiClient.get<UnreferencedContentResponse>(
    KNOWLEDGE_ENDPOINTS.unreferenced, { params: buildKnowledgeParams(params) },
  );
  return response.data;
}

export async function getRetrievalDrillDown(retrievalId: number) {
  const response = await apiClient.get<RetrievalDrillDown>(
    KNOWLEDGE_ENDPOINTS.retrieval(retrievalId),
  );
  return response.data;
}
export async function getFeedbackSummary(params: Record<string, unknown> = {}) {
  return (await apiClient.get<FeedbackSummary>("/admin/analytics/feedback/summary",
    { params: definedParams(params) })).data;
}
export async function getFeedbackList(params: Record<string, unknown> = {}) {
  return (await apiClient.get<FeedbackListResponse>("/admin/analytics/feedback",
    { params: definedParams(params) })).data;
}
export async function getFeedbackDetail(feedbackId: number) {
  return (await apiClient.get<AdminFeedbackItem>(`/admin/analytics/feedback/${feedbackId}`)).data;
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
