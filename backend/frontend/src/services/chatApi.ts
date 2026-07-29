import type { ChatResponse } from "../types/backend.ts";
import { apiClient } from "./apiClient.ts";

export async function askKnowledgeBase(question: string) {
  const response = await apiClient.post<ChatResponse>("/chat", { question });
  return response.data;
}
