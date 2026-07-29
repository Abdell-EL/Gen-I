export type DataState = "loading" | "empty" | "error" | "ready";
export function knowledgeViewState(loading: boolean, error: string | null, count: number): DataState {
  if (loading) return "loading";
  if (error) return "error";
  return count === 0 ? "empty" : "ready";
}
export function scoreBarWidth(percentage: number) {
  return `${Math.max(0, Math.min(100, percentage))}%`;
}
export function trendingChange(absolute: number, percentage: number | null) {
  return `${absolute > 0 ? "+" : ""}${absolute} · ${percentage === null ? "N/D" : `${percentage.toFixed(1)} %`}`;
}
export function confidenceReason(reason: "zero_results" | "top_score_below_threshold") {
  return reason === "zero_results" ? "Aucun résultat" : "Score sous le seuil";
}
