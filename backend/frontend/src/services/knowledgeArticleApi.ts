import type { KnowledgeArticleResponse } from "../types/backend.ts";
import { apiClient } from "./apiClient.ts";

export async function getKnowledgeArticle(
  sourceDocumentId: number,
  options: { versionId?: number | null; chunkId?: number | null } = {},
) {
  const response = await apiClient.get<KnowledgeArticleResponse>(
    `/knowledge/articles/${sourceDocumentId}`,
    {
      params: {
        ...(options.versionId ? { version_id: options.versionId } : {}),
        ...(options.chunkId ? { chunk_id: options.chunkId } : {}),
      },
    },
  );
  return response.data;
}
