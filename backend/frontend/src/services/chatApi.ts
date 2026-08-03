import type { ChatResponse } from "../types/backend.ts";
import { apiClient } from "./apiClient.ts";

export async function askKnowledgeBase(question: string, sessionId?: number | null) {
  const response = await apiClient.post<ChatResponse>(
    "/chat",
    { question, ...(sessionId ? { session_id: sessionId } : {}) },
  );
  return response.data;
}
