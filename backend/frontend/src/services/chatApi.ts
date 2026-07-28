import type { ChatResponse } from "../types/backend";
import { apiClient } from "./apiClient";

export async function askKnowledgeBase(question: string) {
  const response = await apiClient.post<ChatResponse>("/chat", { question });
  return response.data;
}
