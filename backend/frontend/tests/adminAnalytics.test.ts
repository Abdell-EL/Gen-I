import assert from "node:assert/strict";
import test from "node:test";

import {
  formatAnalyticsValue,
  formatHealthStatusLabel,
  getHealthStatusTone,
  mapLowConfidenceScore,
  mapUserActivityRows,
  mapTopQuestions,
} from "../src/features/admin/analyticsUtils.ts";

test(" KPI values keep real numeric formatting without fabricated trend data ", () => {
  assert.equal(formatAnalyticsValue(0), "0");
  assert.equal(formatAnalyticsValue(1234), "1 234");
  assert.equal(formatAnalyticsValue(0.875, "percent"), "87,5 %");
  assert.equal(formatAnalyticsValue(42, "count"), "42");
});

test(" health statuses map only to supported API states and professional French labels ", () => {
  assert.equal(getHealthStatusTone("healthy"), "healthy");
  assert.equal(getHealthStatusTone("degraded"), "degraded");
  assert.equal(getHealthStatusTone("unhealthy"), "unhealthy");
  assert.equal(getHealthStatusTone("unknown"), "unknown");
  assert.equal(getHealthStatusTone(undefined), "unknown");
  assert.equal(formatHealthStatusLabel("healthy"), "Opérationnel");
  assert.equal(formatHealthStatusLabel("warning"), "Dégradé");
  assert.equal(formatHealthStatusLabel("down"), "Indisponible");
  assert.equal(formatHealthStatusLabel(undefined), "Inconnu");
});

test(" low-confidence scores keep zero values at zero and clamp only to valid percentages ", () => {
  assert.equal(mapLowConfidenceScore(0), 0);
  assert.equal(mapLowConfidenceScore(0.08), 8);
  assert.equal(mapLowConfidenceScore(1.2), 100);
  assert.equal(mapLowConfidenceScore(null), 0);
});

test(" user ranking rows and question rankings only use real backend fields ", () => {
  const users = mapUserActivityRows([
    { user_id: 10, full_name: "Alice", email: "alice@example.com", role: "agent", is_active: true, questions_count: 18, last_question_at: "2026-08-04T09:00:00Z" },
    { user_id: 11, full_name: "Bob", email: "bob@example.com", role: "admin", is_active: false, questions_count: 0, last_question_at: null },
  ]);

  assert.equal(users[0].label, "Alice");
  assert.equal(users[0].value, 18);
  assert.equal(users[1].status, "inactive");

  const questions = mapTopQuestions([
    { question: "Quoi de neuf ?", normalized_question: "quoi de neuf", count: 7, unique_users: 3, last_asked_at: "2026-08-04T08:00:00Z", example_user: { user_id: 10, full_name: "Alice" } },
    { question: "Que faire si le système est lent ?", normalized_question: "que faire si le système est lent", count: 2, unique_users: 2, last_asked_at: "2026-08-04T07:00:00Z", example_user: { user_id: 11, full_name: "Bob" } },
  ]);

  assert.equal(questions[0].label, "Quoi de neuf ?");
  assert.equal(questions[0].value, 7);
  assert.equal(questions[1].value, 2);
  assert.equal(questions[0].context, "3 utilisateurs");
});
