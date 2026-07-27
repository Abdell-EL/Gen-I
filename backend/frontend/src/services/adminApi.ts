import type {
  AuditDetailResponse,
  AuditListResponse,
  HealthResponse,
  IngestionJobDetail,
  IngestionJobSummary,
  IngestionUploadResponse,
  StatsResponse,
} from "../types/backend";
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
