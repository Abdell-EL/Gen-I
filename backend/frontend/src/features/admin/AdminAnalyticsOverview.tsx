import {
  AlertTriangle,
  BookOpenText,
  CircleUserRound,
  Database,
  Gauge,
  MessageSquareText,
  ShieldCheck,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { ErrorState } from "../../components/ui/ErrorState";
import { LoadingState } from "../../components/ui/LoadingState";
import {
  getAdminErrorMessage,
  getArticleAnalytics,
  getFeedbackSummary,
  getLowConfidence,
  getQuestionAnalytics,
  getUnreferencedContent,
  getUserAnalytics,
} from "../../services/adminApi";
import type { HealthResponse, StatsResponse } from "../../types/backend";
import {
  formatAnalyticsValue,
  formatHealthStatusLabel,
  getHealthStatusTone,
  mapLowConfidenceScore,
} from "./analyticsUtils";

type KpiTone = "navy" | "gold" | "neutral" | "danger" | "success";

type KpiCardProps = {
  label: string;
  value: string;
  helper: string;
  icon: LucideIcon;
  tone?: KpiTone;
  tooltip?: string;
};

type BarItem = {
  label: string;
  value: number;
  helper?: string;
  tone?: "navy" | "gold" | "blue" | "soft" | "danger";
};

function AnalyticsKpiCard({ label, value, helper, icon: Icon, tone = "neutral", tooltip }: KpiCardProps) {
  return (
    <article className={`analytics-kpi-card tone-${tone}`} title={tooltip} aria-label={tooltip ?? `${label}: ${value}`}>
      <div className="analytics-kpi-header">
        <span className="analytics-kpi-icon">
          <Icon size={17} />
        </span>
        <span className="analytics-kpi-label">{label}</span>
      </div>
      <strong>{value}</strong>
      <small>{helper}</small>
    </article>
  );
}

function HorizontalBarChart({ items, emptyText }: { items: BarItem[]; emptyText: string }) {
  const maxValue = Math.max(...items.map((item) => item.value), 1);

  if (!items.length) {
    return <div className="analytics-empty-inline">{emptyText}</div>;
  }

  return (
    <div className="analytics-bar-list" aria-label="Classement analytique">
      {items.map((item) => (
        <div key={item.label} className="analytics-bar-row">
          <div className="analytics-bar-meta">
            <span>{item.label}</span>
            <strong>{formatAnalyticsValue(item.value, "count")}</strong>
          </div>
          <div className="analytics-bar-track" aria-hidden="true">
            <span
              className={`analytics-bar-fill tone-${item.tone ?? "navy"}`}
              style={{ width: `${(item.value / maxValue) * 100}%` }}
            />
          </div>
          {item.helper && <small>{item.helper}</small>}
        </div>
      ))}
    </div>
  );
}

function AnalyticsPanel({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <section className="analytics-panel">
      <div className="analytics-panel-header">
        <div>
          <span className="section-kicker">Analyse</span>
          <h3>{title}</h3>
        </div>
        <p>{subtitle}</p>
      </div>
      {children}
    </section>
  );
}

export function AdminAnalyticsOverview({
  refreshKey,
  health,
  stats,
}: {
  refreshKey: number;
  health: HealthResponse | null;
  stats: StatsResponse | null;
}) {
  const [users, setUsers] = useState<Awaited<ReturnType<typeof getUserAnalytics>> | null>(null);
  const [questions, setQuestions] = useState<Awaited<ReturnType<typeof getQuestionAnalytics>> | null>(null);
  const [lowConfidence, setLowConfidence] = useState<Awaited<ReturnType<typeof getLowConfidence>> | null>(null);
  const [articles, setArticles] = useState<Awaited<ReturnType<typeof getArticleAnalytics>> | null>(null);
  const [feedback, setFeedback] = useState<Awaited<ReturnType<typeof getFeedbackSummary>> | null>(null);
  const [unreferenced, setUnreferenced] = useState<Awaited<ReturnType<typeof getUnreferencedContent>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [partialWarning, setPartialWarning] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      setPartialWarning(null);

      void Promise.allSettled([
        getUserAnalytics({ page: 1, page_size: 10 }),
        getQuestionAnalytics({ limit: 5 }),
        getLowConfidence({ threshold: 0.5, page: 1, page_size: 5 }),
        getArticleAnalytics({ page: 1, page_size: 5, sort_by: "consultation_count", sort_order: "desc" }),
        getFeedbackSummary(),
        getUnreferencedContent({ page: 1, page_size: 5 }),
      ]).then((results) => {
        if (!active) return;

        const successful = results.filter((result) => result.status === "fulfilled");
        const failed = results.filter((result) => result.status === "rejected");

        if (successful.length === 0) {
          setError(getAdminErrorMessage(failed[0]?.reason ?? new Error("Aucune donnée analytique disponible.")));
          return;
        }

        if (failed.length > 0) {
          setPartialWarning("Certaines métriques analytiques ne sont pas disponibles; les données chargées sont conservées.");
        }

        const [nextUsers, nextQuestions, nextLowConfidence, nextArticles, nextFeedback, nextUnreferenced] = results.map(
          (result) => (result.status === "fulfilled" ? result.value : null),
        );

        setUsers(nextUsers as Awaited<ReturnType<typeof getUserAnalytics>> | null);
        setQuestions(nextQuestions as Awaited<ReturnType<typeof getQuestionAnalytics>> | null);
        setLowConfidence(nextLowConfidence as Awaited<ReturnType<typeof getLowConfidence>> | null);
        setArticles(nextArticles as Awaited<ReturnType<typeof getArticleAnalytics>> | null);
        setFeedback(nextFeedback as Awaited<ReturnType<typeof getFeedbackSummary>> | null);
        setUnreferenced(nextUnreferenced as Awaited<ReturnType<typeof getUnreferencedContent>> | null);
      }).finally(() => {
        if (active) setLoading(false);
      });
    }, 0);

    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [refreshKey]);

  const kpis = useMemo<KpiCardProps[]>(() => {
    const activeUsers = users?.items.filter((item) => item.is_active).length ?? 0;
    const totalQuestions = users?.items.reduce((sum, item) => sum + item.questions_count, 0) ?? 0;
    const lowConfidenceCount = lowConfidence?.total ?? 0;
    const healthTone = getHealthStatusTone(health?.status);

    return [
      {
        label: "Utilisateurs actifs (page)",
        value: formatAnalyticsValue(activeUsers, "count"),
        helper: users ? `Échantillon chargé: ${users.total} utilisateurs` : "Chargement…",
        icon: CircleUserRound,
        tone: "navy" as const,
      },
      {
        label: "Questions dans la page",
        value: formatAnalyticsValue(totalQuestions, "count"),
        helper: questions?.items[0] ? `Échantillon chargé: ${questions.items[0].count} occurrences max` : "Aucune donnée de référence",
        icon: MessageSquareText,
        tone: "gold" as const,
      },
      {
        label: "Articles disponibles",
        value: formatAnalyticsValue(stats?.articles ?? 0, "count"),
        helper: stats ? `${stats.chunks ?? 0} chunks indexés` : "Données introuvables",
        icon: BookOpenText,
        tone: "success" as const,
      },
      {
        label: "Taux de réponses utiles",
        value: formatAnalyticsValue(feedback?.helpful_percentage ?? 0, "percent"),
        helper: feedback ? `${feedback.total_feedback ?? 0} retours sur l’échantillon` : "Aucun retour disponible",
        icon: ShieldCheck,
        tone: "success" as const,
      },
      {
        label: "Documents non référencés",
        value: formatAnalyticsValue(unreferenced?.total ?? 0, "count"),
        helper: "Échantillon chargé: page actuelle",
        icon: AlertTriangle,
        tone: (unreferenced?.total ?? 0) > 0 ? "danger" as const : "neutral" as const,
      },
      {
        label: "Questions peu fiables",
        value: formatAnalyticsValue(lowConfidenceCount, "count"),
        helper: lowConfidence ? `Seuil ${lowConfidence.threshold} • page chargée` : "Aucun signal détecté",
        icon: Gauge,
        tone: lowConfidenceCount > 0 ? "danger" as const : "neutral" as const,
      },
      {
        label: "État du service",
        value: formatHealthStatusLabel(health?.status),
        helper: health ? `Source: ${health.service} • version ${health.version}` : "Aucune donnée de service",
        icon: Database,
        tone: healthTone === "healthy" ? "success" : healthTone === "degraded" ? "gold" : healthTone === "unhealthy" ? "danger" : "neutral",
      },
      {
        label: "Consultations (échantillon)",
        value: formatAnalyticsValue(articles?.items.reduce((sum, item) => sum + item.consultation_count, 0) ?? 0, "count"),
        helper: articles ? `Basé sur ${articles.items.length} articles chargés` : "Données non chargées",
        icon: TrendingUp,
        tone: "navy" as const,
      },
    ];
  }, [users, questions, lowConfidence, articles, feedback, unreferenced, health, stats]);

  if (loading) return <LoadingState label="Chargement du tableau de bord analytique…" />;
  if (error && !(users || questions || lowConfidence || articles || feedback || unreferenced)) return <ErrorState message={error} />;

  const topUsers: BarItem[] = (users?.items ?? []).slice(0, 5).map((item) => ({
    label: item.full_name,
    value: item.questions_count,
    helper: item.role,
    tone: item.is_active ? "navy" : "soft",
  }));

  const topQuestions: BarItem[] = (questions?.items ?? []).slice(0, 5).map((item) => ({
    label: item.question,
    value: item.count,
    helper: `${item.unique_users} utilisateur${item.unique_users > 1 ? "s" : ""}`,
    tone: "gold",
  }));

  const lowConfidenceList: BarItem[] = (lowConfidence?.items ?? []).slice(0, 5).map((item) => ({
    label: item.query_text,
    value: mapLowConfidenceScore(item.top_score),
    helper: item.low_confidence_reason === "zero_results" ? "Aucun résultat" : "Score sous seuil",
    tone: "danger",
  }));

  const topArticles: BarItem[] = (articles?.items ?? []).slice(0, 5).map((item) => ({
    label: item.article_title ?? "Article sans titre",
    value: item.consultation_count,
    helper: `${item.unique_users} utilisateurs`,
    tone: "navy",
  }));

  return (
    <section className="admin-analytics-workspace">
      <div className="analytics-header-row">
        <div>
          <span className="section-kicker">Vue d’ensemble</span>
          <h2>Tableau de bord analytique</h2>
          <p>Suivi des usages, de la qualité des réponses et de la couverture documentaire.</p>
        </div>
        <div className="analytics-header-meta">
          <span>{health ? `État global : ${health.status}` : "Données de santé indisponibles"}</span>
          <span>{stats ? `${stats.articles ?? 0} articles • ${stats.chunks ?? 0} chunks` : "Données de base indisponibles"}</span>
        </div>
      </div>

      {partialWarning && (
        <div className="analytics-partial-warning" role="status">{partialWarning}</div>
      )}

      <div className="analytics-kpi-grid">
        {kpis.map((kpi) => (
          <AnalyticsKpiCard
            key={kpi.label}
            label={kpi.label}
            value={kpi.value}
            helper={kpi.helper}
            icon={kpi.icon}
            tone={kpi.tone}
          />
        ))}
      </div>

      <div className="analytics-grid">
        <AnalyticsPanel title="Activité des utilisateurs" subtitle="Classement des contributeurs sur la période chargée">
          <HorizontalBarChart items={topUsers} emptyText="Aucune donnée d’activité disponible." />
        </AnalyticsPanel>

        <AnalyticsPanel title="Questions les plus fréquentes" subtitle="Formulations les plus répétées par les utilisateurs">
          <HorizontalBarChart items={topQuestions} emptyText="Aucune question fréquente détectée." />
        </AnalyticsPanel>

        <AnalyticsPanel title="Questions à surveiller" subtitle="Requêtes sous seuil, hors résultats ou peu fiables">
          <HorizontalBarChart items={lowConfidenceList} emptyText="Aucune question à faible confiance." />
        </AnalyticsPanel>

        <AnalyticsPanel title="Articles les plus consultés" subtitle="Contenus les plus sollicités dans la base de connaissance">
          <HorizontalBarChart items={topArticles} emptyText="Aucun article consulté sur cette plage." />
        </AnalyticsPanel>

        <AnalyticsPanel title="Satisfaction des utilisateurs" subtitle="Retour qualitatif structuré depuis les retours authentifiés">
          <div className="analytics-score-stack">
            <div className="analytics-score-row">
              <span>Utile</span>
              <strong>{formatAnalyticsValue(feedback?.helpful_percentage ?? 0, "percent")}</strong>
            </div>
            <div className="analytics-score-bar">
              <span style={{ width: `${Math.min(100, feedback?.helpful_percentage ?? 0)}%` }} />
            </div>
            <div className="analytics-score-row muted">
              <span>Peu utile</span>
              <strong>{formatAnalyticsValue(feedback?.negative_percentage ?? 0, "percent")}</strong>
            </div>
          </div>
        </AnalyticsPanel>

        <AnalyticsPanel title="Couverture de la base de connaissances" subtitle="Volumes documentaires et indexation actuellement disponibles">
          <div className="analytics-summary-list">
            <div>
              <span>Articles</span>
              <strong>{formatAnalyticsValue(stats?.articles ?? 0, "count")}</strong>
            </div>
            <div>
              <span>Chunks</span>
              <strong>{formatAnalyticsValue(stats?.chunks ?? 0, "count")}</strong>
            </div>
            <div>
              <span>Collection</span>
              <strong>{stats?.vector_collection ?? "—"}</strong>
            </div>
          </div>
        </AnalyticsPanel>

        <AnalyticsPanel title="État des services" subtitle="Disponibilité réelle confirmée par l’API de supervision">
          <div className="status-list">
            <div className="status-item">
              <span>API plateforme</span>
              <strong>{formatHealthStatusLabel(health?.status)}</strong>
            </div>
            <div className="status-item">
              <span>PostgreSQL</span>
              <strong>{formatHealthStatusLabel(health?.components.postgres?.status)}</strong>
            </div>
            <div className="status-item">
              <span>Milvus</span>
              <strong>{formatHealthStatusLabel(health?.components.milvus?.status)}</strong>
            </div>
          </div>
        </AnalyticsPanel>

        <AnalyticsPanel title="Contenu non référencé" subtitle="Documents à examiner pour mieux couvrir la base de connaissances">
          <div className="analytics-list-cards">
            {(unreferenced?.items ?? []).slice(0, 5).map((item) => (
              <div className="analytics-list-card" key={item.source_document_id}>
                <strong>{item.filename}</strong>
                <small>{item.title ?? "Sans titre"}</small>
                <span>{item.kb_code ?? "KB inconnue"}</span>
              </div>
            ))}
            {!unreferenced?.items?.length && <div className="analytics-empty-inline">Aucun document non référencé sur cette période.</div>}
          </div>
        </AnalyticsPanel>
      </div>
    </section>
  );
}
