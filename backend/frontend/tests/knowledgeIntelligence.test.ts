import assert from "node:assert/strict";
import test from "node:test";
import { buildKnowledgeParams, KNOWLEDGE_ENDPOINTS } from "../src/services/knowledgeApiConfig.ts";
import { confidenceReason, knowledgeViewState, scoreBarWidth, trendingChange } from "../src/features/admin/knowledgeView.ts";

test("knowledge API paths and query construction preserve false benchmark toggle", () => {
  assert.equal(KNOWLEDGE_ENDPOINTS.trending, "/admin/analytics/knowledge/trending-questions");
  assert.equal(KNOWLEDGE_ENDPOINTS.retrieval(42), "/admin/analytics/knowledge/retrievals/42");
  assert.deepEqual(buildKnowledgeParams({ date_from: "2026-01-01", search_type: "chat", include_benchmarks: false, search: "" }), { date_from: "2026-01-01", search_type: "chat", include_benchmarks: false });
});
test("loading empty error and ready states are deterministic", () => {
  assert.equal(knowledgeViewState(true, null, 3), "loading");
  assert.equal(knowledgeViewState(false, "failure", 3), "error");
  assert.equal(knowledgeViewState(false, null, 0), "empty");
  assert.equal(knowledgeViewState(false, null, 3), "ready");
});
test("trending low-confidence and score bucket render helpers are safe", () => {
  assert.equal(trendingChange(2, 50), "+2 · 50.0 %");
  assert.equal(trendingChange(1, null), "+1 · N/D");
  assert.equal(confidenceReason("zero_results"), "Aucun résultat");
  assert.equal(scoreBarWidth(36.5), "36.5%");
  assert.equal(scoreBarWidth(120), "100%");
});
test("retrieval drill-down request path contains no secret fields", () => {
  const path = KNOWLEDGE_ENDPOINTS.retrieval(7);
  for (const secret of ["token", "password", "hash", "redis"]) assert.equal(path.includes(secret), false);
});
