import axios from "axios";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileText,
  FileUp,
  History,
  Layers3,
  Loader2,
  RefreshCw,
  Rocket,
  Sparkles,
  UploadCloud,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useState,
  type ChangeEvent,
} from "react";

import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import {
  listIngestionJobs,
  listKnowledgeDocumentVersions,
  uploadKnowledgeDocumentVersion,
  uploadKnowledgeDocx,
} from "../../services/adminApi";
import { fetchOriginalDocument } from "../../services/knowledgeDocumentApi";
import type {
  DocumentVersionHistoryItem,
  DocumentVersionUpdateResponse,
  IngestionJobSummary,
  IngestionStatus,
  IngestionUploadResponse,
  SourcePreview,
} from "../../types/backend";

type UploadFeedback =
  | { kind: "detail"; detail: IngestionUploadResponse }
  | { kind: "error"; message: string };

type VersionFeedback =
  | { kind: "detail"; detail: DocumentVersionUpdateResponse }
  | { kind: "error"; message: string };

const statusLabels: Record<string, string> = {
  processing: "En cours",
  completed: "Terminé",
  failed: "Échec",
  duplicate: "Doublon",
  superseded: "Remplacée",
  unknown: "En attente",
};

const docxMime =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function normalizeStatus(status: IngestionStatus | "unknown") {
  if (["processing", "completed", "failed", "duplicate", "superseded"].includes(status)) {
    return status;
  }
  return "unknown";
}

function getStatusLabel(status: IngestionStatus | "unknown") {
  return statusLabels[status] ?? status;
}

function isValidDocx(file: File) {
  return file.name.toLowerCase().endsWith(".docx");
}

function isUploadDetail(value: unknown): value is IngestionUploadResponse {
  if (!value || typeof value !== "object") return false;

  const candidate = value as Partial<IngestionUploadResponse>;
  return (
    typeof candidate.job_id === "number" &&
    typeof candidate.status === "string" &&
    typeof candidate.filename === "string" &&
    typeof candidate.message === "string"
  );
}

function getUploadErrorDetail(error: unknown) {
  if (!axios.isAxiosError<{ detail?: unknown }>(error)) return null;

  const detail = error.response?.data?.detail;
  return isUploadDetail(detail) ? detail : null;
}

function getVersionUploadError(error: unknown) {
  if (!axios.isAxiosError<{ detail?: unknown }>(error)) {
    return "La mise à jour a échoué. Vérifiez le fichier DOCX ou réessayez.";
  }

  const detail = error.response?.data?.detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }

  if (error.response?.status === 404) return "Article introuvable.";
  if (error.response?.status === 403) return "Action réservée aux administrateurs.";
  return "La mise à jour a échoué. Vérifiez le fichier DOCX ou réessayez.";
}

function formatCount(value: number | null | undefined) {
  return typeof value === "number" ? value.toLocaleString("fr-FR") : "0";
}

function formatDate(value: string | null | undefined) {
  if (!value) return "—";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} o`;

  const kilobytes = bytes / 1024;
  if (kilobytes < 1024) return `${kilobytes.toFixed(1)} Ko`;

  return `${(kilobytes / 1024).toFixed(1)} Mo`;
}

export function UpdatePanel({
  onRefreshStats,
}: {
  onRefreshStats?: () => Promise<void> | void;
}) {
  const fileInputId = useId();
  const versionFileInputId = useId();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [feedback, setFeedback] = useState<UploadFeedback | null>(null);
  const [jobs, setJobs] = useState<IngestionJobSummary[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [versionDocumentId, setVersionDocumentId] = useState("");
  const [versionFile, setVersionFile] = useState<File | null>(null);
  const [versionFileError, setVersionFileError] = useState<string | null>(null);
  const [changeReason, setChangeReason] = useState("");
  const [changeSummary, setChangeSummary] = useState("");
  const [effectiveAt, setEffectiveAt] = useState("");
  const [versionUploading, setVersionUploading] = useState(false);
  const [versionFeedback, setVersionFeedback] = useState<VersionFeedback | null>(null);
  const [versionHistory, setVersionHistory] = useState<DocumentVersionHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [downloadingVersionId, setDownloadingVersionId] = useState<number | null>(null);

  const uploadDetail = feedback?.kind === "detail" ? feedback.detail : null;
  const completedDetail =
    uploadDetail?.status === "completed" ? uploadDetail : null;
  const failedDetail =
    uploadDetail && uploadDetail.status !== "completed" ? uploadDetail : null;
  const errorMessage =
    feedback?.kind === "error" ? feedback.message : failedDetail?.message;
  const validationStatus = normalizeStatus(
    uploading
      ? "processing"
      : completedDetail
        ? "completed"
        : failedDetail?.status ?? "unknown",
  );
  const parsedVersionDocumentId = Number.parseInt(versionDocumentId, 10);
  const canSubmitVersionUpdate =
    Number.isInteger(parsedVersionDocumentId) &&
    parsedVersionDocumentId > 0 &&
    Boolean(versionFile) &&
    !versionUploading;
  const versionDetail =
    versionFeedback?.kind === "detail" ? versionFeedback.detail : null;
  const versionError =
    versionFeedback?.kind === "error" ? versionFeedback.message : null;

  const loadJobs = useCallback(async () => {
    setJobsLoading(true);
    setJobsError(null);

    try {
      setJobs(await listIngestionJobs(20));
    } catch {
      setJobsError("Impossible de charger l’historique des traitements.");
    } finally {
      setJobsLoading(false);
    }
  }, []);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void loadJobs();
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, [loadJobs]);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setFeedback(null);

    if (!file) {
      setSelectedFile(null);
      setFileError(null);
      return;
    }

    if (!isValidDocx(file)) {
      setSelectedFile(null);
      setFileError("Sélectionnez un fichier DOCX au format .docx.");
      event.target.value = "";
      return;
    }

    setSelectedFile(file);
    setFileError(null);
  }

  async function handleUpload() {
    if (!selectedFile || uploading) return;

    if (!isValidDocx(selectedFile)) {
      setFileError("Sélectionnez un fichier DOCX au format .docx.");
      return;
    }

    setUploading(true);
    setFeedback(null);
    setFileError(null);

    try {
      const detail = await uploadKnowledgeDocx(selectedFile);
      setFeedback({ kind: "detail", detail });

      if (detail.status === "completed") {
        await onRefreshStats?.();
      }
    } catch (requestError) {
      const detail = getUploadErrorDetail(requestError);

      if (detail) {
        setFeedback({ kind: "detail", detail });
      } else {
        setFeedback({
          kind: "error",
          message: "L’import a échoué. Vérifiez le fichier DOCX ou réessayez.",
        });
      }
    } finally {
      setUploading(false);
      void loadJobs();
    }
  }

  function handleVersionFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setVersionFeedback(null);

    if (!file) {
      setVersionFile(null);
      setVersionFileError(null);
      return;
    }

    if (!isValidDocx(file)) {
      setVersionFile(null);
      setVersionFileError("Sélectionnez un fichier DOCX au format .docx.");
      event.target.value = "";
      return;
    }

    setVersionFile(file);
    setVersionFileError(null);
  }

  const loadVersionHistory = useCallback(async () => {
    if (!Number.isInteger(parsedVersionDocumentId) || parsedVersionDocumentId <= 0) {
      setHistoryError("Saisissez un source_document_id valide.");
      return;
    }

    setHistoryLoading(true);
    setHistoryError(null);

    try {
      setVersionHistory(await listKnowledgeDocumentVersions(parsedVersionDocumentId));
    } catch {
      setHistoryError("Impossible de charger l’historique de versions.");
    } finally {
      setHistoryLoading(false);
    }
  }, [parsedVersionDocumentId]);

  async function handleVersionUpload() {
    if (!canSubmitVersionUpdate || !versionFile) return;

    if (!isValidDocx(versionFile)) {
      setVersionFileError("Sélectionnez un fichier DOCX au format .docx.");
      return;
    }

    setVersionUploading(true);
    setVersionFeedback(null);
    setVersionFileError(null);

    try {
      const detail = await uploadKnowledgeDocumentVersion({
        sourceDocumentId: parsedVersionDocumentId,
        file: versionFile,
        changeReason,
        changeSummary,
        effectiveAt,
      });
      setVersionFeedback({ kind: "detail", detail });
      if (detail.status === "completed") {
        await onRefreshStats?.();
        await loadVersionHistory();
      }
    } catch (requestError) {
      setVersionFeedback({
        kind: "error",
        message: getVersionUploadError(requestError),
      });
    } finally {
      setVersionUploading(false);
      void loadJobs();
    }
  }

  async function openVersionDocument(version: DocumentVersionHistoryItem) {
    setDownloadingVersionId(version.document_version_id);
    setHistoryError(null);

    const source: SourcePreview = {
      rank: null,
      score: null,
      id: null,
      chunk_id: null,
      source_document_id: version.source_document_id,
      document_version_id: version.document_version_id,
      kb_code: null,
      article_title: null,
      file_name: version.filename,
      section_title: null,
      chunk_type: null,
      priority: null,
      text: null,
    };

    try {
      const { blob, filename } = await fetchOriginalDocument(source);
      const objectUrl = URL.createObjectURL(blob);
      const opened = window.open(objectUrl, "_blank", "noopener,noreferrer");

      if (!opened) {
        const link = document.createElement("a");
        link.href = objectUrl;
        link.download = filename;
        link.rel = "noopener noreferrer";
        document.body.appendChild(link);
        link.click();
        link.remove();
      }

      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    } catch {
      setHistoryError("Le document original ne peut pas être ouvert.");
    } finally {
      setDownloadingVersionId(null);
    }
  }

  return (
    <Card className="update-panel">
      <div className="update-visual">
        <Sparkles size={28} />
      </div>
      <div className="update-copy">
        <span className="section-kicker">Mise à jour Knowledge Base</span>
        <h2>Gouvernance de la base de connaissance</h2>
        <p>
          Le MVP ingère et publie automatiquement les articles DOCX après un
          traitement réussi. La validation et la publication manuelles restent
          des étapes de workflow futures.
        </p>

        <div className="future-actions update-workflow">
          <article className="workflow-card workflow-card-import">
            <div className="workflow-card-top">
              <FileUp size={18} />
              <span className="ingestion-status ingestion-status-processing">
                DOCX actif
              </span>
            </div>
            <span className="workflow-card-title">Importer</span>
            <small className="workflow-card-copy">
              {selectedFile?.name ?? "Sélectionnez un article DOCX."}
            </small>

            <input
              id={fileInputId}
              className="workflow-file-input"
              type="file"
              accept={`.docx,${docxMime}`}
              onChange={handleFileChange}
            />
            <label className="workflow-file-trigger" htmlFor={fileInputId}>
              <FileText size={15} />
              <span>{selectedFile ? "Changer le fichier" : "Choisir un DOCX"}</span>
            </label>

            {selectedFile && (
              <small className="workflow-file-meta">
                {formatFileSize(selectedFile.size)} · prêt à importer
              </small>
            )}
            {fileError && <p className="ingestion-inline-error">{fileError}</p>}

            <Button
              type="button"
              className="workflow-upload-button"
              onClick={handleUpload}
              disabled={!selectedFile || uploading}
              icon={
                uploading ? (
                  <Loader2 className="ingestion-spin" size={15} />
                ) : (
                  <UploadCloud size={15} />
                )
              }
            >
              {uploading ? "Import en cours" : "Importer le DOCX"}
            </Button>
          </article>

          <article
            className={`workflow-card workflow-card-validate workflow-card-${validationStatus}`}
          >
            <div className="workflow-card-top">
              {uploading ? (
                <Loader2 className="ingestion-spin" size={18} />
              ) : errorMessage ? (
                <AlertCircle size={18} />
              ) : (
                <CheckCircle2 size={18} />
              )}
              <span className={`ingestion-status ingestion-status-${validationStatus}`}>
                {getStatusLabel(validationStatus)}
              </span>
            </div>
            <span className="workflow-card-title">Valider</span>
            <small className="workflow-card-copy">
              {uploading
                ? "Traitement backend en cours."
                : completedDetail
                  ? "Validation et préparation terminées."
                  : errorMessage
                    ? errorMessage
                    : selectedFile
                      ? "En attente du lancement de l’import."
                      : "En attente d’un fichier."}
            </small>
            {failedDetail && (
              <p className="workflow-message">
                {failedDetail.filename}
                {failedDetail.kb_code ? ` · ${failedDetail.kb_code}` : ""}
              </p>
            )}
          </article>

          <article
            className={`workflow-card workflow-card-publish ${
              completedDetail ? "workflow-card-completed" : "workflow-card-inactive"
            }`}
          >
            <div className="workflow-card-top">
              <Rocket size={18} />
              <span
                className={`ingestion-status ingestion-status-${
                  completedDetail ? "completed" : "unknown"
                }`}
              >
                {completedDetail ? "Terminé" : "Inactif"}
              </span>
            </div>
            <span className="workflow-card-title">Publier</span>
            <small className="workflow-card-copy">
              Publication automatique MVP
            </small>

            {completedDetail ? (
              <dl className="workflow-result-grid">
                <div>
                  <dt>job_id</dt>
                  <dd>#{completedDetail.job_id}</dd>
                </div>
                <div>
                  <dt>kb_code</dt>
                  <dd>{completedDetail.kb_code ?? "—"}</dd>
                </div>
                <div>
                  <dt>chunks_created</dt>
                  <dd>{formatCount(completedDetail.chunks_created)}</dd>
                </div>
                <div>
                  <dt>embeddings_created</dt>
                  <dd>{formatCount(completedDetail.embeddings_created)}</dd>
                </div>
                <div>
                  <dt>milvus_vectors_inserted</dt>
                  <dd>{formatCount(completedDetail.milvus_vectors_inserted)}</dd>
                </div>
              </dl>
            ) : (
              <p className="workflow-message muted">
                Disponible après traitement réussi.
              </p>
            )}
          </article>
        </div>

        <section className="version-update-panel">
          <div className="ingestion-history-heading">
            <div>
              <span className="section-kicker">Versions d’article</span>
              <h3>Mettre à jour l’article</h3>
            </div>
            <Button
              type="button"
              variant="secondary"
              onClick={() => void loadVersionHistory()}
              disabled={historyLoading}
              icon={
                historyLoading ? (
                  <Loader2 className="ingestion-spin" size={16} />
                ) : (
                  <History size={16} />
                )
              }
            >
              Historique des versions
            </Button>
          </div>

          <p className="workflow-message muted">
            La version actuelle reste active jusqu’à la fin du traitement de la
            révision DOCX. Les anciennes versions restent disponibles pour audit.
          </p>

          <div className="version-update-grid">
            <label className="version-field">
              <span>source_document_id</span>
              <input
                type="number"
                min="1"
                inputMode="numeric"
                value={versionDocumentId}
                onChange={(event) => {
                  setVersionDocumentId(event.target.value);
                  setVersionFeedback(null);
                }}
                placeholder="Ex. 123"
              />
            </label>

            <label className="version-field version-field-file" htmlFor={versionFileInputId}>
              <span>DOCX révisé</span>
              <input
                id={versionFileInputId}
                className="workflow-file-input"
                type="file"
                accept={`.docx,${docxMime}`}
                onChange={handleVersionFileChange}
              />
              <span className="workflow-file-trigger">
                <FileText size={15} />
                {versionFile ? "Changer le fichier" : "Choisir un DOCX"}
              </span>
              {versionFile && (
                <small className="workflow-file-meta">
                  {formatFileSize(versionFile.size)} · prêt à mettre à jour
                </small>
              )}
            </label>

            <label className="version-field">
              <span>Raison</span>
              <input
                type="text"
                value={changeReason}
                onChange={(event) => setChangeReason(event.target.value)}
                placeholder="Procédure révisée"
              />
            </label>

            <label className="version-field">
              <span>Date d’effet</span>
              <input
                type="date"
                value={effectiveAt}
                onChange={(event) => setEffectiveAt(event.target.value)}
              />
            </label>

            <label className="version-field version-field-summary">
              <span>Résumé du changement</span>
              <textarea
                rows={3}
                value={changeSummary}
                onChange={(event) => setChangeSummary(event.target.value)}
                placeholder="Décrivez brièvement la modification."
              />
            </label>
          </div>

          {versionFileError && (
            <p className="ingestion-inline-error">{versionFileError}</p>
          )}
          {versionError && <p className="ingestion-inline-error">{versionError}</p>}
          {versionDetail && (
            <p className="workflow-message">
              Version #{versionDetail.version_number ?? "—"} · {versionDetail.status}
              {versionDetail.ingestion_job_id
                ? ` · job #${versionDetail.ingestion_job_id}`
                : ""}
            </p>
          )}

          <Button
            type="button"
            className="workflow-upload-button"
            onClick={handleVersionUpload}
            disabled={!canSubmitVersionUpdate}
            icon={
              versionUploading ? (
                <Loader2 className="ingestion-spin" size={15} />
              ) : (
                <UploadCloud size={15} />
              )
            }
          >
            {versionUploading ? "Traitement en cours" : "Mettre à jour l’article"}
          </Button>

          {historyError && <p className="ingestion-inline-error">{historyError}</p>}

          {versionHistory.length > 0 && (
            <div className="version-history-list">
              <div className="version-history-row version-history-row-head">
                <span>Version</span>
                <span>Statut</span>
                <span>Fichier</span>
                <span>Ajoutée</span>
                <span>Changement</span>
                <span>Document</span>
              </div>
              {versionHistory.map((version) => {
                const status = normalizeStatus(version.ingestion_status ?? version.status);
                const downloading = downloadingVersionId === version.document_version_id;

                return (
                  <div className="version-history-row" key={version.document_version_id}>
                    <span>
                      v{version.version_number}
                      {version.is_current ? (
                        <strong className="version-current-badge">Actuelle</strong>
                      ) : null}
                    </span>
                    <span className={`ingestion-status ingestion-status-${status}`}>
                      {getStatusLabel(status)}
                    </span>
                    <span title={version.filename}>{version.filename}</span>
                    <span>{formatDate(version.uploaded_at)}</span>
                    <span title={version.change_summary ?? ""}>
                      {version.change_reason ?? version.change_summary ?? "—"}
                    </span>
                    <div className="version-actions">
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => void openVersionDocument(version)}
                        disabled={downloading}
                        icon={
                          downloading ? (
                            <Loader2 className="ingestion-spin" size={15} />
                          ) : (
                            <Download size={15} />
                          )
                        }
                      >
                        Original DOCX
                      </Button>
                      <a
                        className="version-preview-link"
                        href={`/articles/${version.source_document_id}?version_id=${version.document_version_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Aperçu
                      </a>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="ingestion-history">
          <div className="ingestion-history-heading">
            <div>
              <span className="section-kicker">Historique des traitements</span>
              <h3>Historique des traitements</h3>
            </div>
            <Button
              type="button"
              variant="secondary"
              onClick={() => void loadJobs()}
              disabled={jobsLoading}
              icon={
                jobsLoading ? (
                  <Loader2 className="ingestion-spin" size={16} />
                ) : (
                  <RefreshCw size={16} />
                )
              }
            >
              Actualiser les jobs
            </Button>
          </div>

          {jobsError && <p className="ingestion-inline-error">{jobsError}</p>}

          {jobsLoading && jobs.length === 0 ? (
            <div className="ingestion-loading">
              <Loader2 className="ingestion-spin" size={17} />
              <span>Chargement des jobs…</span>
            </div>
          ) : jobs.length === 0 ? (
            <div className="ingestion-empty">
              <Layers3 size={18} />
              <span>Aucun traitement récent.</span>
            </div>
          ) : (
            <div className="ingestion-job-list">
              <div className="ingestion-job-row ingestion-job-row-head">
                <span>job_id</span>
                <span>filename</span>
                <span>status</span>
                <span>processed_chunks</span>
                <span>created_at</span>
                <span>error_message</span>
              </div>
              {jobs.map((job) => {
                const status = normalizeStatus(job.status);
                return (
                  <div className="ingestion-job-row" key={job.job_id}>
                    <span className="ingestion-job-id">#{job.job_id}</span>
                    <span className="ingestion-job-file" title={job.filename ?? ""}>
                      {job.filename ?? job.source_path ?? "Document sans nom"}
                    </span>
                    <span className={`ingestion-status ingestion-status-${status}`}>
                      {getStatusLabel(job.status)}
                    </span>
                    <span>{formatCount(job.processed_chunks)}</span>
                    <span>{formatDate(job.created_at)}</span>
                    <span
                      className={
                        job.error_message
                          ? "ingestion-job-error"
                          : "ingestion-job-error muted"
                      }
                      title={job.error_message ?? ""}
                    >
                      {job.error_message ?? "—"}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </Card>
  );
}
