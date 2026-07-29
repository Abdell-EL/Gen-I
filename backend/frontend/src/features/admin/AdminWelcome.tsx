import {
  Activity,
  ArrowUpRight,
  BarChart3,
  CheckCircle2,
  Database,
  FileUp,
  RefreshCw,
  ScrollText,
  Server,
} from "lucide-react";
import { useState } from "react";

import type { AdminSection } from "../../components/layout/AdminSidebar";
import { StatusBadge } from "../../components/ui/StatusBadge";
import type {
  AuditSummary,
  HealthResponse,
  StatsResponse,
} from "../../types/backend";

type ModuleSection = "health" | "audits" | "stats" | "updates";

const moduleTabs = [
  { id: "health", label: "Santé système", icon: Activity },
  { id: "audits", label: "Audits", icon: ScrollText },
  { id: "stats", label: "Statistiques", icon: BarChart3 },
  { id: "updates", label: "Mise à jour", icon: RefreshCw },
] satisfies Array<{ id: ModuleSection; label: string; icon: typeof Activity }>;

export function AdminWelcome({
  userName,
  health,
  stats,
  auditCount,
  latestAudit,
  onNavigate,
}: {
  userName: string;
  health: HealthResponse | null;
  stats: StatsResponse | null;
  auditCount: number;
  latestAudit: AuditSummary | null;
  onNavigate: (section: AdminSection) => void;
}) {
  const [activeModule, setActiveModule] = useState<ModuleSection>("health");

  const moduleContent = {
    health: {
      kicker: "Supervision opérationnelle",
      title: "Les services critiques, visibles en un regard.",
      description: "Contrôlez la disponibilité et le volume des composants qui alimentent la recherche.",
      cards: [
        { icon: Database, label: "PostgreSQL", value: health?.components.postgres?.connected ? "Connecté" : "À vérifier", meta: `${health?.components.postgres?.chunks_count ?? "—"} chunks` },
        { icon: Server, label: "Milvus", value: health?.components.milvus?.connected ? "Connecté" : "À vérifier", meta: `${health?.components.milvus?.vectors_count ?? "—"} vecteurs` },
        { icon: Activity, label: "API FastAPI", value: health?.status ?? "Indisponible", meta: health ? "Version " + health.version : "Aucune donnée" },
        { icon: Server, label: "Redis", value: "À venir", meta: "Connecteur planifié" },
      ],
    },
    audits: {
      kicker: "Traçabilité de bout en bout",
      title: "Chaque recherche conserve sa preuve.",
      description: "Retrouvez les requêtes, les scores et les résultats qui ont construit une réponse.",
      cards: [
        { icon: ScrollText, label: "Dernière requête", value: latestAudit?.query_text ?? "Aucune requête", meta: `${auditCount} entrées chargées` },
        { icon: CheckCircle2, label: "Résultats", value: String(latestAudit?.results_count ?? "—"), meta: "Dernière récupération" },
        { icon: Activity, label: "Meilleur score", value: latestAudit?.top_score?.toFixed(3) ?? "—", meta: "Pertinence maximale" },
      ],
    },
    stats: {
      kicker: "Couverture documentaire",
      title: "Mesurez la matière réellement exploitable.",
      description: "Suivez la structure de la base et la collection vectorielle en production.",
      cards: [
        { icon: BarChart3, label: "Articles", value: String(stats?.articles ?? "—"), meta: "Référentiels structurés" },
        { icon: Database, label: "Chunks", value: String(stats?.chunks ?? "—"), meta: "Unités de recherche" },
        { icon: Server, label: "Collection", value: stats?.vector_collection ?? "—", meta: "Index Milvus actif" },
      ],
    },
    updates: {
      kicker: "Cycle de publication",
      title: "Préparez la prochaine version de la base.",
      description: "Un futur workflow gouverné pour importer, valider puis publier les contenus.",
      cards: [
        { icon: FileUp, label: "Importer", value: "Étape 01", meta: "Bientôt disponible" },
        { icon: CheckCircle2, label: "Valider", value: "Étape 02", meta: "Bientôt disponible" },
        { icon: RefreshCw, label: "Publier", value: "Étape 03", meta: "Bientôt disponible" },
      ],
    },
  } satisfies Record<ModuleSection, {
    kicker: string;
    title: string;
    description: string;
    cards: Array<{ icon: typeof Activity; label: string; value: string; meta: string }>;
  }>;

  const activeContent = moduleContent[activeModule];

  return (
    <div className="admin-welcome">
      <section className="welcome-banner">
        <div>
          <span className="section-kicker">Pilotage de la plateforme</span>
          <h2>Bonjour {userName}.</h2>
          <p>Voici l’état opérationnel de votre base de connaissance.</p>
        </div>
        <div className="welcome-status">
          <span>État global</span>
          <StatusBadge status={health?.status} />
        </div>
      </section>

      <div className="summary-strip">
        <div className="summary-card summary-card-articles">
          <span className="metric-card-icon" aria-hidden="true">
            <BarChart3 size={17} />
          </span>
          <span>Articles</span>
          <strong>{stats?.articles ?? "—"}</strong>
          <small>Base structurée</small>
          <span className="metric-spark" aria-hidden="true"><i /><i /><i /><i /></span>
        </div>
        <div className="summary-card summary-card-chunks">
          <span className="metric-card-icon" aria-hidden="true">
            <Database size={17} />
          </span>
          <span>Chunks</span>
          <strong>{stats?.chunks ?? health?.components.postgres?.chunks_count ?? "—"}</strong>
          <small>Unités indexées</small>
          <span className="metric-spark" aria-hidden="true"><i /><i /><i /><i /></span>
        </div>
        <div className="summary-card summary-card-vectors">
          <span className="metric-card-icon" aria-hidden="true">
            <Server size={17} />
          </span>
          <span>Vecteurs</span>
          <strong>{health?.components.milvus?.vectors_count ?? "—"}</strong>
          <small>Collection active</small>
          <span className="metric-spark" aria-hidden="true"><i /><i /><i /><i /></span>
        </div>
        <div className="summary-card summary-card-audits">
          <span className="metric-card-icon" aria-hidden="true">
            <ScrollText size={17} />
          </span>
          <span>Requêtes auditées</span>
          <strong>{auditCount}</strong>
          <small>Dernières entrées</small>
          <span className="metric-spark" aria-hidden="true"><i /><i /><i /><i /></span>
        </div>
      </div>

      <section className="module-showcase">
        <span className="shooting-star star-one" aria-hidden="true" />
        <span className="shooting-star star-two" aria-hidden="true" />
        <div className="module-showcase-header">
          <div>
            <span>Modules de pilotage</span>
            <strong>Explorer la console</strong>
          </div>
          <div className="module-tabs" role="tablist" aria-label="Modules d’administration">
            {moduleTabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeModule === tab.id}
                  className={activeModule === tab.id ? "active" : ""}
                  key={tab.id}
                  onClick={() => setActiveModule(tab.id)}
                >
                  <Icon size={16} />
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className={"module-active-panel module-" + activeModule}>
          <div className="module-active-copy">
            <span>{activeContent.kicker}</span>
            <h3>{activeContent.title}</h3>
            <p>{activeContent.description}</p>
            <button type="button" onClick={() => onNavigate(activeModule)}>
              Ouvrir le module <ArrowUpRight size={17} />
            </button>
          </div>
          <div className="module-card-row">
            {activeContent.cards.map((card) => {
              const Icon = card.icon;
              return (
                <article key={card.label}>
                  <Icon size={20} />
                  <span>{card.label}</span>
                  <strong>{card.value}</strong>
                  <small>{card.meta}</small>
                </article>
              );
            })}
          </div>
        </div>
      </section>
    </div>
  );
}
