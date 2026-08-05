import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { useAuth } from "../app/useAuth";
import {
  AdminSidebar,
  type AdminSection,
} from "../components/layout/AdminSidebar";
import { DashboardShell } from "../components/layout/DashboardShell";
import { Button } from "../components/ui/Button";
import { ErrorState } from "../components/ui/ErrorState";
import { LoadingState } from "../components/ui/LoadingState";
import { AdminAnalyticsOverview } from "../features/admin/AdminAnalyticsOverview";
import { AdminWelcome } from "../features/admin/AdminWelcome";
import { AuditList } from "../features/admin/AuditList";
import { HealthPanel } from "../features/admin/HealthPanel";
import { StatsPanel } from "../features/admin/StatsPanel";
import { QuestionAnalyticsPanel } from "../features/admin/QuestionAnalyticsPanel";
import { KnowledgeIntelligencePanel } from "../features/admin/KnowledgeIntelligencePanel";
import { FeedbackIntelligencePanel } from "../features/admin/FeedbackIntelligencePanel";
import { UpdatePanel } from "../features/admin/UpdatePanel";
import { UserActivityPanel } from "../features/admin/UserActivityPanel";
import { UserManagementPanel } from "../features/admin/UserManagementPanel";
import {
  getAuditDetail,
  getLatestAudits,
  getSystemHealth,
  getSystemStats,
} from "../services/adminApi";
import { getApiErrorMessage } from "../services/apiClient";
import type {
  AuditDetailResponse,
  AuditSummary,
  HealthResponse,
  StatsResponse,
} from "../types/backend";

const sectionHeadings: Record<
  AdminSection,
  { eyebrow: string; title: string; description: string }
> = {
  home: {
    eyebrow: "Administration",
    title: "Vue d’ensemble",
    description:
      "Pilotez la disponibilité, l’usage et l’évolution de la plateforme Genius Services.",
  },
  users: {
    eyebrow: "Gestion des accès",
    title: "Utilisateurs",
    description: "Créez, modifiez et sécurisez les comptes de la plateforme.",
  },
  "user-activity": {
    eyebrow: "Analyse d’usage",
    title: "Activité des utilisateurs",
    description: "Identifiez les utilisateurs les plus actifs sur une période donnée.",
  },
  questions: {
    eyebrow: "Analyse des demandes",
    title: "Questions fréquentes",
    description: "Analysez les formulations exactes les plus souvent soumises.",
  },
  knowledge: {
    eyebrow: "Intelligence documentaire",
    title: "Connaissance & qualité",
    description: "Analysez les tendances, la confiance et la consultation du corpus.",
  },
  feedback: { eyebrow: "Qualité", title: "Feedback utilisateurs",
    description: "Analysez les évaluations des réponses générées." },
  health: {
    eyebrow: "Supervision",
    title: "Santé système",
    description:
      "Contrôlez la disponibilité de l’API, de PostgreSQL et de l’index Milvus.",
  },
  audits: {
    eyebrow: "Traçabilité",
    title: "Audits de récupération",
    description:
      "Examinez les dernières recherches et leurs résultats journalisés.",
  },
  stats: {
    eyebrow: "Indicateurs",
    title: "Statistiques de connaissance",
    description:
      "Mesurez le volume documentaire actuellement disponible pour la recherche.",
  },
  updates: {
    eyebrow: "Cycle de vie",
    title: "Mise à jour de la base",
    description:
      "Préparez la future gestion des imports, validations et publications.",
  },
};

export function AdminPage() {
  const { user } = useAuth();
  const [activeSection, setActiveSection] = useState<AdminSection>("home");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [audits, setAudits] = useState<AuditSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [auditDetail, setAuditDetail] = useState<AuditDetailResponse | null>(
    null,
  );
  const [detailLoading, setDetailLoading] = useState(false);
  const [controlPlaneRefresh, setControlPlaneRefresh] = useState(0);

  useEffect(() => {
    let active = true;

    void Promise.allSettled([
      getSystemHealth(),
      getSystemStats(),
      getLatestAudits(10),
    ]).then(([healthResult, statsResult, auditsResult]) => {
      if (!active) return;

      if (healthResult.status === "fulfilled") setHealth(healthResult.value);
      if (statsResult.status === "fulfilled") setStats(statsResult.value);
      if (auditsResult.status === "fulfilled") {
        setAudits(auditsResult.value.retrievals ?? []);
      }

      if (
        healthResult.status === "rejected" ||
        statsResult.status === "rejected" ||
        auditsResult.status === "rejected"
      ) {
        setError(
          "Certaines données d’administration sont temporairement indisponibles.",
        );
      }
      setLoading(false);
    });

    return () => {
      active = false;
    };
  }, []);

  async function refreshData() {
    setLoading(true);
    setError(null);
    try {
      const [nextHealth, nextStats, nextAudits] = await Promise.all([
        getSystemHealth(),
        getSystemStats(),
        getLatestAudits(10),
      ]);
      setHealth(nextHealth);
      setStats(nextStats);
      setAudits(nextAudits.retrievals ?? []);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }

  async function refreshKnowledgeMetrics() {
    try {
      const [nextHealth, nextStats] = await Promise.all([
        getSystemHealth(),
        getSystemStats(),
      ]);
      setHealth(nextHealth);
      setStats(nextStats);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    }
  }

  async function selectAudit(retrievalId: number) {
    setDetailLoading(true);
    setAuditDetail(null);
    try {
      setAuditDetail(await getAuditDetail(retrievalId));
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setDetailLoading(false);
    }
  }

  const heading = sectionHeadings[activeSection];

  return (
    <DashboardShell
      className="admin-console"
      sidebar={
        <AdminSidebar
          activeSection={activeSection}
          onChange={setActiveSection}
        />
      }
      eyebrow={heading.eyebrow}
      title={heading.title}
      description={heading.description}
    >
      {!(["users", "user-activity", "questions", "knowledge", "feedback"] as AdminSection[]).includes(activeSection) && <div className="admin-toolbar">
        <Button
          type="button"
          variant="secondary"
          onClick={refreshData}
          disabled={loading}
          icon={<RefreshCw size={16} />}
        >
          Actualiser
        </Button>
      </div>}

      {error && <ErrorState message={error} />}
      {loading && <LoadingState label="Chargement des données système…" />}

      {!loading && activeSection === "home" && (
        <>
        <AdminWelcome
          userName={user?.full_name ?? "Administrateur"}
          health={health}
          stats={stats}
          auditCount={audits.length}
          latestAudit={audits[0] ?? null}
          onNavigate={setActiveSection}
        />
        <AdminAnalyticsOverview
          refreshKey={controlPlaneRefresh}
          health={health}
          stats={stats}
        />
        </>
      )}
      {!loading && activeSection === "users" && (
        <UserManagementPanel onDataChanged={() => setControlPlaneRefresh((value) => value + 1)} />
      )}
      {!loading && activeSection === "user-activity" && (
        <UserActivityPanel refreshKey={controlPlaneRefresh} />
      )}
      {!loading && activeSection === "questions" && (
        <QuestionAnalyticsPanel refreshKey={controlPlaneRefresh} />
      )}
      {!loading && activeSection === "knowledge" && <KnowledgeIntelligencePanel />}
      {!loading && activeSection === "feedback" && <FeedbackIntelligencePanel />}
      {!loading && activeSection === "health" && (
        <HealthPanel health={health} />
      )}
      {!loading && activeSection === "audits" && (
        <AuditList
          audits={audits}
          detail={auditDetail}
          detailLoading={detailLoading}
          onSelect={selectAudit}
          onCloseDetail={() => setAuditDetail(null)}
        />
      )}
      {!loading && activeSection === "stats" && <StatsPanel stats={stats} />}
      {!loading && activeSection === "updates" && (
        <UpdatePanel onRefreshStats={refreshKnowledgeMetrics} />
      )}
    </DashboardShell>
  );
}
