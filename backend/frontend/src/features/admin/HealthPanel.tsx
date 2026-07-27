import { Activity, Database, Server } from "lucide-react";

import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { StatusBadge } from "../../components/ui/StatusBadge";
import type { HealthResponse } from "../../types/backend";

function valueOrDash(value: string | number | undefined) {
  return value ?? "—";
}

export function HealthPanel({ health }: { health: HealthResponse | null }) {
  if (!health) {
    return (
      <EmptyState
        icon={<Activity size={22} />}
        title="Santé indisponible"
        description="Les informations de supervision n’ont pas pu être chargées."
      />
    );
  }

  const postgres = health.components.postgres;
  const milvus = health.components.milvus;

  return (
    <div className="admin-panel-stack">
      <Card className="overall-health">
        <div className="overall-health-copy">
          <span className="overall-health-icon" aria-hidden="true">
            <Activity size={20} />
          </span>
          <div>
            <span className="section-kicker">État global</span>
            <h2>{health.service}</h2>
            <p>Version API {health.version}</p>
          </div>
        </div>
        <StatusBadge status={health.status} />
      </Card>

      <div className="health-grid">
        <Card className="component-card">
          <div className="component-heading">
            <span className="component-icon blue">
              <Database size={20} />
            </span>
            <div>
              <h3>PostgreSQL</h3>
              <p>Stockage documentaire et traçabilité</p>
            </div>
            <StatusBadge status={postgres?.status} />
          </div>
          <dl className="metric-list">
            <div>
              <dt>Connexion</dt>
              <dd>{postgres?.connected ? "Active" : "Inactive"}</dd>
            </div>
            <div>
              <dt>Chunks</dt>
              <dd>{valueOrDash(postgres?.chunks_count)}</dd>
            </div>
            <div>
              <dt>Documents sources</dt>
              <dd>{valueOrDash(postgres?.source_documents_count)}</dd>
            </div>
            <div>
              <dt>Requêtes tracées</dt>
              <dd>{valueOrDash(postgres?.retrieval_requests_count)}</dd>
            </div>
          </dl>
          {postgres?.error && <p className="component-error">{postgres.error}</p>}
        </Card>

        <Card className="component-card">
          <div className="component-heading">
            <span className="component-icon purple">
              <Server size={20} />
            </span>
            <div>
              <h3>Milvus</h3>
              <p>Index vectoriel de recherche sémantique</p>
            </div>
            <StatusBadge status={milvus?.status} />
          </div>
          <dl className="metric-list">
            <div>
              <dt>Connexion</dt>
              <dd>{milvus?.connected ? "Active" : "Inactive"}</dd>
            </div>
            <div>
              <dt>Collection</dt>
              <dd>{valueOrDash(milvus?.collection)}</dd>
            </div>
            <div>
              <dt>Vecteurs</dt>
              <dd>{valueOrDash(milvus?.vectors_count)}</dd>
            </div>
            <div>
              <dt>Collection disponible</dt>
              <dd>{milvus?.collection_exists === false ? "Non" : "Oui"}</dd>
            </div>
          </dl>
          {milvus?.error && <p className="component-error">{milvus.error}</p>}
        </Card>
      </div>
    </div>
  );
}
