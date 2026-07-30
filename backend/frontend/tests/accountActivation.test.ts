import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { accountStatusLabel, activationFailureState, consumeActivationToken, invitePayload } from "../src/features/auth/activationFlow.ts";
const userPanel = readFileSync(new URL("../src/features/admin/UserManagementPanel.tsx", import.meta.url), "utf8");
const activationPage = readFileSync(new URL("../src/pages/ActivationPage.tsx", import.meta.url), "utf8");
const activationApi = readFileSync(new URL("../src/services/activationApi.ts", import.meta.url), "utf8");
const adminApi = readFileSync(new URL("../src/services/adminApi.ts", import.meta.url), "utf8");
const router = readFileSync(new URL("../src/app/AppRouter.tsx", import.meta.url), "utf8");

test("invite request contains only name email and role and form has no password", () => {
  assert.deepEqual(invitePayload("  New User ", " new@example.test ", "agent"), { full_name: "New User", email: "new@example.test", role: "agent" });
  const dialog = userPanel.slice(userPanel.indexOf("function InviteUserDialog"), userPanel.indexOf("function EditFields"));
  assert.doesNotMatch(dialog, /type="password"|password_confirmation|initial_password/);
  assert.match(dialog, /full_name: form\.full_name\.trim\(\), email: form\.email\.trim\(\), role: form\.role/);
});
test("account status labels separate lifecycle from administration", () => {
  assert.equal(accountStatusLabel({ is_active: true, activation_status: "pending" }), "En attente d’activation");
  assert.equal(accountStatusLabel({ is_active: true, activation_status: "active" }), "Actif");
  assert.equal(accountStatusLabel({ is_active: false, activation_status: "pending" }), "Désactivé administrativement");
});
test("resend is pending-only with confirmation throttling and failures", () => {
  assert.match(userPanel, /item\.activation_status === "pending"/); assert.match(userPanel, /window\.confirm\(`Renvoyer l’invitation/);
  assert.match(userPanel, /response\?\.status === 429/); assert.match(userPanel, /response\?\.status === 409/);
  assert.match(userPanel, /livraison de l’invitation a échoué/); assert.match(adminApi, /\/admin\/users\/\$\{userId\}\/resend-invitation/);
});
test("activation token is removed from history and not persisted", () => {
  const secret = "x".repeat(48); let replacement = "";
  assert.equal(consumeActivationToken(`https://ui.test/activate?token=${secret}&source=invite#form`, (path) => { replacement = path; }), secret);
  assert.equal(replacement, "/activate?source=invite#form"); assert.doesNotMatch(replacement, /token=/);
  for (const source of [activationPage, activationApi]) assert.doesNotMatch(source, /localStorage|sessionStorage|console\.|Authorization/);
  assert.match(activationPage, /history\.replaceState/);
});
test("activation maps invalid expired consumed and failure states", () => {
  assert.equal(activationFailureState(400, "invalid"), "invalid"); assert.equal(activationFailureState(400, "expired"), "expired");
  assert.equal(activationFailureState(400, "consumed"), "consumed"); assert.equal(activationFailureState(503, undefined), "failed");
  assert.match(activationPage, /state === "validating"/); assert.match(activationPage, /state === "valid"/);
});
test("password workflow validates mismatch clears secrets and prevents duplicates", () => {
  assert.match(activationPage, /password !== confirmation/); assert.match(activationPage, /autoComplete="new-password"/g);
  assert.match(activationPage, /submissionActive\.current/); assert.match(activationPage, /tokenRef\.current = null; setPassword\(""\); setConfirmation\(""\); setState\("complete"\)/);
  assert.match(activationPage, /disabled=\{submitting\}/);
});
test("public activation client is isolated from authenticated logout", () => {
  assert.match(activationApi, /axios\.create/); assert.doesNotMatch(activationApi, /apiClient\.|authStorage|interceptors/);
  assert.match(router, /path="\/activate" element=\{<ActivationPage \/>\}/); assert.ok(router.indexOf('path="/activate"') < router.indexOf("<ProtectedRoute"));
});
test("local activation link is one-time component state and never logged", () => {
  assert.match(userPanel, /setLocalActivationUrl\(delivery\.activation_url\)/); assert.match(userPanel, /setLocalActivationUrl\(null\); window\.open/);
  assert.doesNotMatch(userPanel, /console\.|localStorage|sessionStorage/);
});
