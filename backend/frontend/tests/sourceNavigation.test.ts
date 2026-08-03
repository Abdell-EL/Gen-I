import assert from "node:assert/strict";
import test from "node:test";

import { buildArticlePath } from "../src/features/chat/sourceNavigation.ts";
import type { SourcePreview } from "../src/types/backend.ts";

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
    file_name: "article.docx",
    section_title: "Section",
    chunk_type: "text",
    priority: null,
    text: "Extrait",
    ...overrides,
  };
}

test("source card route uses stable source, version, and chunk ids", () => {
  assert.equal(buildArticlePath(source()), "/articles/7?version_id=9&chunk_id=42");
});

test("source card route omits unavailable optional ids and never uses titles", () => {
  assert.equal(buildArticlePath(source({ document_version_id: null, chunk_id: null })), "/articles/7");
  assert.equal(buildArticlePath(source({ source_document_id: null, article_title: "Only a title" })), null);
});
