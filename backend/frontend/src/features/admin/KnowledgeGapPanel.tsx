import { useEffect, useState } from "react";

import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorState } from "../../components/ui/ErrorState";
import { LoadingState } from "../../components/ui/LoadingState";
import { Button } from "../../components/ui/Button";
import { getAdminErrorMessage, getKnowledgeGaps, resolveKnowledgeGap } from "../../services/adminApi";
import type { KnowledgeGapItem, KnowledgeGapListResponse, KnowledgeGapStatus } from "../../types/admin";
import { AdminDialog, Pagination } from "./AdminCommon";
import { formatAdminDate } from "./adminUtils";

function statusLabel(status: KnowledgeGapStatus) {
  if (status === "resolved") return "Résolu";
  if (status === "dismissed") return "Ignoré";
  return "Ouvert";
}

export function KnowledgeGapPanel() {
  const [list, setList] = useState<KnowledgeGapListResponse | null>(null);
  const [status, setStatus] = useState<KnowledgeGapStatus | "">("open");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<KnowledgeGapItem | null>(null);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      setLoading(true); setError(null);
      getKnowledgeGaps({ status: status || undefined, page, page_size: 25 })
        .then((response) => { if (active) setList(response); })
        .catch((requestError) => { if (active) setError(getAdminErrorMessage(requestError)); })
        .finally(() => { if (active) setLoading(false); });
    }, 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [status, page, refreshKey]);

  function openGap(gap: KnowledgeGapItem) {
    setSelected(gap);
    setNotes(gap.resolution_notes ?? "");
  }

  async function resolve(nextStatus: KnowledgeGapStatus) {
    if (!selected) return;
    setSaving(true);
    try {
      await resolveKnowledgeGap(selected.gap_id, { status: nextStatus, resolution_notes: notes || null });
      setSelected(null);
      setRefreshKey((value) => value + 1);
    } catch (requestError) {
      setError(getAdminErrorMessage(requestError));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="knowledge-intelligence">
      <section className="admin-data-panel knowledge-overview">
        <div className="admin-panel-heading">
          <div>
            <span className="section-kicker">Amélioration continue</span>
            <h2>Questions sans réponse</h2>
            <p>
              Questions pour lesquelles le chatbot a signalé une information manquante, ou pour
              lesquelles la confiance de récupération était faible. Utilisez cette liste pour
              compléter la base documentaire.
            </p>
          </div>
        </div>
        <div className="inline-controls">
          <label>
            Statut
            <select value={status} onChange={(event) => { setPage(1); setStatus(event.target.value as KnowledgeGapStatus | ""); }}>
              <option value="">Tous</option>
              <option value="open">Ouvert</option>
              <option value="resolved">Résolu</option>
              <option value="dismissed">Ignoré</option>
            </select>
          </label>
          <strong>{list?.total ?? 0} question(s)</strong>
        </div>
      </section>

      <section className="admin-data-panel knowledge-panel">
        {loading && <LoadingState label="Chargement des questions sans réponse…" />}
        {!loading && error && <ErrorState message={error} />}
        {!loading && !error && list?.items.length === 0 && (
          <EmptyState title="Aucune question à traiter" description="Aucune question ne correspond à ce filtre." />
        )}
        {!loading && !error && list && list.items.length > 0 && (
          <>
            <div className="admin-table-wrap">
              <table className="admin-table knowledge-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Question</th>
                    <th>Réponse manquante</th>
                    <th>Confiance faible</th>
                    <th>Confiance</th>
                    <th>Statut</th>
                  </tr>
                </thead>
                <tbody>
                  {list.items.map((item) => (
                    <tr className="clickable-row" key={item.gap_id} onClick={() => openGap(item)}>
                      <td>{formatAdminDate(item.created_at)}</td>
                      <td><strong>{item.question_text}</strong></td>
                      <td>{item.text_indicates_missing ? "Oui" : "Non"}</td>
                      <td>{item.low_confidence ? "Oui" : "Non"}</td>
                      <td>{item.confidence_label ?? "—"}</td>
                      <td>{statusLabel(item.status)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={list.page} pages={list.pages} total={list.total} onPageChange={setPage} />
          </>
        )}
      </section>

      {selected && (
        <AdminDialog
          title={`Question #${selected.gap_id}`}
          description={statusLabel(selected.status)}
          onClose={() => setSelected(null)}
        >
          <div className="admin-form">
            <label>Question<small>{selected.question_text}</small></label>
            <label>Réponse générée<small>{selected.answer_text}</small></label>
            <label>Confiance<small>{selected.confidence_label ?? "—"}</small></label>
            <label>Signal<small>
              {selected.text_indicates_missing ? "Réponse manquante" : ""}
              {selected.text_indicates_missing && selected.low_confidence ? " · " : ""}
              {selected.low_confidence ? "Confiance faible" : ""}
            </small></label>
            <label>
              Notes de résolution
              <textarea
                rows={4}
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                placeholder="Ex : information ajoutée à l'article KB-142."
              />
            </label>
            <div className="admin-dialog-actions">
              <Button type="button" variant="ghost" disabled={saving} onClick={() => void resolve("dismissed")}>
                Ignorer
              </Button>
              <Button type="button" disabled={saving} onClick={() => void resolve("resolved")}>
                Marquer comme résolu
              </Button>
            </div>
          </div>
        </AdminDialog>
      )}
    </div>
  );
}
