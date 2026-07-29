import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { NdjsonEventParser } from "../src/services/chatStream.ts";

const answerPanel = readFileSync(new URL("../src/features/chat/AnswerPanel.tsx", import.meta.url), "utf8");
const adminPanel = readFileSync(new URL("../src/features/admin/FeedbackIntelligencePanel.tsx", import.meta.url), "utf8");
const feedbackApi = readFileSync(new URL("../src/services/feedbackApi.ts", import.meta.url), "utf8");

test("stream completion retains the assistant message identifier", () => {
  const parser = new NdjsonEventParser();
  assert.deepEqual(parser.feed('{"type":"done","status":"complete","partial":false,"message_id":91}\n'), [
    { type: "done", status: "complete", partial: false, message_id: 91 },
  ]);
});

test("feedback API constructs authenticated message-scoped requests", () => {
  assert.match(feedbackApi, /\/chat\/messages\/\$\{messageId\}\/feedback/g);
  assert.match(feedbackApi, /apiClient\.post/);
  assert.match(feedbackApi, /apiClient\.get/);
  assert.match(feedbackApi, /apiClient\.delete/);
});

test("answer feedback controls are completion-gated and validate negative input", () => {
  assert.match(answerPanel, /status === "complete"/);
  assert.match(answerPanel, /status === "partial"/);
  assert.match(answerPanel, /status === "cancelled"/);
  assert.match(answerPanel, /Boolean\(messageId\)/);
  assert.match(answerPanel, /Choisissez une raison/);
  assert.match(answerPanel, /reason === "other" && !comment\.trim\(\)/);
  assert.match(answerPanel, /getAnswerFeedback/);
  assert.match(answerPanel, /deleteAnswerFeedback/);
});

test("feedback request failures leave the answer rendering intact", () => {
  assert.match(answerPanel, /setFeedbackError\(getApiErrorMessage\(requestError\)\)/);
  assert.match(answerPanel, /renderAnswerText\(response\.answer\)/);
  assert.doesNotMatch(answerPanel, /setResponse\(/);
});

test("admin feedback panel includes loading empty error table and drill-down states", () => {
  assert.match(adminPanel, /LoadingState/);
  assert.match(adminPanel, /ErrorState/);
  assert.match(adminPanel, /EmptyState/);
  assert.match(adminPanel, /getFeedbackSummary/);
  assert.match(adminPanel, /getFeedbackList/);
  assert.match(adminPanel, /getFeedbackDetail/);
  assert.match(adminPanel, /detail\.results/);
  assert.match(adminPanel, /feedback-badge/);
});
