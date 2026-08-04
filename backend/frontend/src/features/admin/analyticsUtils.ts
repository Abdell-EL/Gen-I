export type AnalyticsStatusTone = "healthy" | "degraded" | "unhealthy" | "unknown";

export function normalizePercentValue(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return 0;
  const numericValue = Number(value);
  return Math.abs(numericValue) <= 1 ? numericValue * 100 : numericValue;
}

export function formatAnalyticsValue(
  value: number | null | undefined,
  kind: "count" | "percent" | "default" = "default",
) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }

  if (kind === "percent") {
    const normalizedValue = normalizePercentValue(value);
    return `${new Intl.NumberFormat("fr-FR", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    }).format(normalizedValue).replace(/\u202F/g, " ")} %`;
  }

  const formatted = new Intl.NumberFormat("fr-FR", {
    maximumFractionDigits: 0,
  }).format(value).replace(/\u202F/g, " ");

  return formatted;
}

export function formatHealthStatusLabel(status?: string) {
  const normalized = (status ?? "unknown").toLowerCase();
  if (normalized === "healthy" || normalized === "ok" || normalized === "operational") return "Opérationnel";
  if (normalized === "degraded" || normalized === "warning") return "Dégradé";
  if (normalized === "unhealthy" || normalized === "down" || normalized === "error") return "Indisponible";
  return "Inconnu";
}

export function getHealthStatusTone(status?: string): AnalyticsStatusTone {
  const normalized = (status ?? "unknown").toLowerCase();
  if (normalized === "healthy" || normalized === "ok" || normalized === "operational") return "healthy";
  if (normalized === "degraded" || normalized === "warning") return "degraded";
  if (normalized === "unhealthy" || normalized === "down" || normalized === "error") return "unhealthy";
  return "unknown";
}

export function mapLowConfidenceScore(score: number | null | undefined) {
  if (score === null || score === undefined || !Number.isFinite(score)) {
    return 0;
  }

  return Math.max(0, Math.min(1, score)) * 100;
}

export function mapUserActivityRows<T extends {
  user_id: number;
  full_name: string;
  email: string;
  role: string;
  is_active: boolean;
  questions_count: number;
  last_question_at: string | null;
}>(items: T[]) {
  return items.map((item, index) => ({
    rank: index + 1,
    label: item.full_name,
    meta: item.email,
    value: item.questions_count,
    status: item.is_active ? "active" : "inactive",
    role: item.role,
    lastActivity: item.last_question_at,
  }));
}

export function mapTopQuestions<T extends {
  question: string;
  count: number;
  unique_users: number;
  example_user: { full_name: string };
}>(items: T[]) {
  return items.map((item, index) => ({
    rank: index + 1,
    label: item.question,
    value: item.count,
    context: `${item.unique_users} utilisateur${item.unique_users > 1 ? "s" : ""}`,
    example: item.example_user?.full_name ?? "—",
  }));
}
