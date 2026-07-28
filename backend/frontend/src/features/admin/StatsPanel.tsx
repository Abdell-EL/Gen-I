import { Boxes, Database, Layers3 } from "lucide-react";

import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import type { StatsResponse } from "../../types/backend";

export function StatsPanel({ stats }: { stats: StatsResponse | null }) {
  if (!stats) {
    return (
      <EmptyState
        icon={<Layers3 size={22} />}
        title="Statistiques indisponibles"
        description="Le service de statistiques ne répond pas actuellement."
      />
    );
  }

  const additionalStats = Object.entries(stats).filter(
    ([key]) => !["articles", "chunks", "vector_collection"].includes(key),
  );

  return (
    <div className="stats-layout">
      <div className="stats-grid">
        <Card className="stat-card">
          <span className="component-icon blue">
            <Layers3 size={20} />
          </span>
          <p>Articles de connaissance</p>
          <strong>{stats.articles}</strong>
          <small>Référentiels structurés</small>
        </Card>
        <Card className="stat-card">
          <span className="component-icon purple">
            <Boxes size={20} />
          </span>
          <p>Chunks indexés</p>
          <strong>{stats.chunks}</strong>
          <small>Unités prêtes pour la recherche</small>
        </Card>
        <Card className="stat-card">
          <span className="component-icon orange">
            <Database size={20} />
          </span>
          <p>Collection vectorielle</p>
          <strong className="stat-text">{stats.vector_collection}</strong>
          <small>Source Milvus active</small>
        </Card>
      </div>

      {additionalStats.length > 0 && (
        <Card>
          <div className="panel-heading">
            <div>
              <span className="section-kicker">Données complémentaires</span>
              <h2>Indicateurs disponibles</h2>
            </div>
          </div>
          <dl className="metric-list">
            {additionalStats.map(([key, value]) => (
              <div key={key}>
                <dt>{key.replaceAll("_", " ")}</dt>
                <dd>{String(value ?? "—")}</dd>
              </div>
            ))}
          </dl>
        </Card>
      )}
    </div>
  );
}
