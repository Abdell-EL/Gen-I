import type { SourcePreview } from "../../types/backend";

export function buildArticlePath(source: SourcePreview) {
  if (!source.source_document_id) return null;
  const params = new URLSearchParams();
  if (source.document_version_id) params.set("version_id", String(source.document_version_id));
  if (source.chunk_id) params.set("chunk_id", String(source.chunk_id));
  const query = params.toString();
  return `/articles/${source.source_document_id}${query ? `?${query}` : ""}`;
}
