import { apiClient } from "./apiClient";

export type FeedbackRating = "helpful" | "partially_helpful" | "not_helpful";
export type FeedbackReason = "incorrect_answer" | "incomplete_answer" | "irrelevant_sources" |
  "missing_information" | "unclear_answer" | "outdated_information" | "other";
export type AnswerFeedback = { feedback_id: number; message_id: number; user_id: number;
  rating: FeedbackRating; reason: FeedbackReason | null; comment: string | null;
  created_at: string; updated_at: string; was_updated: boolean };
export type FeedbackPayload = { rating: FeedbackRating; reason?: FeedbackReason; comment?: string };

export async function submitAnswerFeedback(messageId: number, payload: FeedbackPayload) {
  return (await apiClient.post<AnswerFeedback>(`/chat/messages/${messageId}/feedback`, payload)).data;
}
export async function getAnswerFeedback(messageId: number) {
  return (await apiClient.get<AnswerFeedback>(`/chat/messages/${messageId}/feedback`)).data;
}
export async function deleteAnswerFeedback(messageId: number) {
  await apiClient.delete(`/chat/messages/${messageId}/feedback`);
}
