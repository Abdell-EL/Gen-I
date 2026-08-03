import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const updatePanel = readFileSync(new URL("../src/features/admin/UpdatePanel.tsx", import.meta.url), "utf8");
const adminApi = readFileSync(new URL("../src/services/adminApi.ts", import.meta.url), "utf8");

test("admin API exposes version update and history contracts without token URLs", () => {
  assert.match(adminApi, /uploadKnowledgeDocumentVersion/);
  assert.match(adminApi, /listKnowledgeDocumentVersions/);
  assert.match(adminApi, /FormData/);
  assert.match(adminApi, /formData\.append\("file", file\)/);
  assert.match(adminApi, /change_reason/);
  assert.match(adminApi, /change_summary/);
  assert.match(adminApi, /effective_at/);
  assert.match(adminApi, /\/admin\/knowledge\/documents\/\$\{sourceDocumentId\}\/versions/);
  assert.match(adminApi, /multipart\/form-data/);
  assert.doesNotMatch(adminApi, /access_token|token=.*|Authorization.*params/);
});

test("admin update panel exposes revised upload workflow and version history", () => {
  assert.match(updatePanel, /Mettre à jour l’article/);
  assert.match(updatePanel, /Historique des versions/);
  assert.match(updatePanel, /source_document_id/);
  assert.match(updatePanel, /DOCX révisé/);
  assert.match(updatePanel, /La version actuelle reste active/);
  assert.match(updatePanel, /uploadKnowledgeDocumentVersion/);
  assert.match(updatePanel, /listKnowledgeDocumentVersions/);
  assert.match(updatePanel, /Original DOCX/);
  assert.match(updatePanel, /Aperçu/);
  assert.match(updatePanel, /fetchOriginalDocument/);
  assert.match(updatePanel, /URL\.createObjectURL/);
  assert.match(updatePanel, /URL\.revokeObjectURL/);
  assert.match(updatePanel, /window\.open\(objectUrl, "_blank", "noopener,noreferrer"\)/);
  assert.match(updatePanel, /disabled=\{!canSubmitVersionUpdate\}/);
  assert.doesNotMatch(adminApi, /access_token|token=.*|Authorization.*params/);
});
