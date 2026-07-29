export const KNOWLEDGE_ENDPOINTS = {
  trending: "/admin/analytics/knowledge/trending-questions",
  lowConfidence: "/admin/analytics/knowledge/low-confidence",
  distribution: "/admin/analytics/knowledge/score-distribution",
  articles: "/admin/analytics/knowledge/articles",
  unreferenced: "/admin/analytics/knowledge/unreferenced-content",
  retrieval: (id: number) => `/admin/analytics/knowledge/retrievals/${id}`,
} as const;

export function buildKnowledgeParams(values: Record<string, unknown>) {
  return Object.fromEntries(Object.entries(values).filter(
    ([, value]) => value !== undefined && value !== null && value !== "",
  ));
}
