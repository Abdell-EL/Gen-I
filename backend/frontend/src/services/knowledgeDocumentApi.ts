import type { SourcePreview } from "../types/backend.ts";
import { apiClient } from "./apiClient.ts";

const fallbackFilename = "document.docx";

export function safeDocxFilename(value: string | null | undefined) {
  const rawName = String(value || fallbackFilename).replace(/\\/g, "/").split("/").pop() || fallbackFilename;
  const withoutExtension = rawName.replace(/\.[^.]*$/, "");
  const cleanStem = withoutExtension.replace(/[^A-Za-z0-9_.-]+/g, "_").replace(/^[._-]+|[._-]+$/g, "");
  return `${cleanStem || "document"}.docx`;
}

export function filenameFromContentDisposition(header: unknown) {
  if (typeof header !== "string") return null;

  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (utf8Match?.[1]) {
    try {
      return safeDocxFilename(decodeURIComponent(utf8Match[1]));
    } catch {
      return safeDocxFilename(utf8Match[1]);
    }
  }

  const quotedMatch = /filename="?([^";]+)"?/i.exec(header);
  return quotedMatch?.[1] ? safeDocxFilename(quotedMatch[1]) : null;
}

export async function fetchOriginalDocument(source: SourcePreview) {
  if (!source.source_document_id) {
    throw new Error("Document source indisponible.");
  }

  const response = await apiClient.get<Blob>(
    `/knowledge/documents/${source.source_document_id}/original`,
    {
      params: {
        ...(source.document_version_id ? { version_id: source.document_version_id } : {}),
      },
      responseType: "blob",
    },
  );

  return {
    blob: response.data,
    filename: filenameFromContentDisposition(response.headers["content-disposition"])
      ?? safeDocxFilename(source.file_name ?? source.article_title),
  };
}
