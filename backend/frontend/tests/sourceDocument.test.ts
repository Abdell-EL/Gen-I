import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { SourcePreview } from "../src/types/backend.ts";
import { apiClient } from "../src/services/apiClient.ts";
import {
  fetchOriginalDocument,
  filenameFromContentDisposition,
  safeDocxFilename,
} from "../src/services/knowledgeDocumentApi.ts";

const sourceList = readFileSync(new URL("../src/features/chat/SourceList.tsx", import.meta.url), "utf8");
const documentApi = readFileSync(new URL("../src/services/knowledgeDocumentApi.ts", import.meta.url), "utf8");

function source(overrides: Partial<SourcePreview> = {}): SourcePreview {
  return {
    rank: 1,
    score: 0.91,
    id: "chunk-ext",
    chunk_id: 42,
    source_document_id: 7,
    document_version_id: 9,
    kb_code: "KB",
    article_title: "Article",
    file_name: "unsafe article.docx",
    section_title: "Section",
    chunk_type: "text",
    priority: null,
    text: "Extrait",
    ...overrides,
  };
}

test("original document client uses authenticated apiClient Blob request without token URLs", async () => {
  const originalGet = apiClient.get;
  let requestedUrl = "";
  let requestedOptions: { params?: Record<string, unknown>; responseType?: string } | undefined;
  apiClient.get = (async (url: string, options?: { params?: Record<string, unknown>; responseType?: string }) => {
    requestedUrl = url;
    requestedOptions = options;
    return {
      data: new Blob(["docx"]),
      headers: { "content-disposition": 'attachment; filename="original.docx"' },
    };
  }) as typeof apiClient.get;

  try {
    const result = await fetchOriginalDocument(source());
    assert.equal(result.filename, "original.docx");
    assert.equal(result.blob.size, 4);
    assert.equal(requestedUrl, "/knowledge/documents/7/original");
    assert.deepEqual(requestedOptions?.params, { version_id: 9 });
    assert.equal(requestedOptions?.responseType, "blob");
    assert.doesNotMatch(requestedUrl, /token|Authorization|Bearer|jwt/i);
  } finally {
    apiClient.get = originalGet;
  }
});

test("content disposition and fallback filenames are sanitized docx names", () => {
  assert.equal(filenameFromContentDisposition("attachment; filename*=UTF-8''unsafe%20name.docx"), "unsafe_name.docx");
  assert.equal(filenameFromContentDisposition('attachment; filename="../secret.txt"'), "secret.docx");
  assert.equal(safeDocxFilename("folder\\bad name.pdf"), "bad_name.docx");
});

test("source card exposes original document as primary and article preview as secondary", () => {
  assert.match(sourceList, /Ouvrir le document original/);
  assert.match(sourceList, /fetchOriginalDocument/);
  assert.match(sourceList, /URL\.createObjectURL/);
  assert.match(sourceList, /window\.open\(objectUrl, "_blank", "noopener,noreferrer"\)/);
  assert.match(sourceList, /URL\.revokeObjectURL/);
  assert.match(sourceList, /Aperçu de l’article/);
  assert.doesNotMatch(documentApi, /access_token|token=.*|Authorization.*params/);
});

test("source card has safe loading and failure states", () => {
  assert.match(sourceList, /Ouverture\.\.\./);
  assert.match(sourceList, /disabled=\{!canOpenOriginal \|\| isOpening\}/);
  assert.match(sourceList, /role="alert"/);
  assert.match(sourceList, /Le document original ne peut pas être ouvert/);
});
