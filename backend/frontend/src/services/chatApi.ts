import type { ChatResponse } from "../types/backend.ts";
import { apiClient } from "./apiClient.ts";

export async function askKnowledgeBase(question: string, sessionId?: number | null) {
  const response = await apiClient.post<ChatResponse>(
    "/chat",
    { question, ...(sessionId ? { session_id: sessionId } : {}) },
    // Generation alone can legitimately take 35-60s+ on a cache miss (confirmed
    // in production logs) — the client's default 20s timeout would abort a
    // perfectly healthy request well before the server finishes.
    { timeout: 120_000 },
  );
  return response.data;
}
