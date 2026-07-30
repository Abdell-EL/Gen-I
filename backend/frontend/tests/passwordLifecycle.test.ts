import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { AxiosError } from "axios";
import type { AxiosAdapter, AxiosInstance, AxiosResponse, InternalAxiosRequestConfig } from "axios";

import { AUTH_TOKEN_STORAGE_KEY, getStoredToken } from "../src/services/authStorage.ts";
import {
  changeOwnPassword,
  changePasswordErrorMessage,
  completePasswordReset,
  publicPasswordLifecycleClient,
  requestPasswordReset,
  resetCompletionErrorMessage,
  validatePasswordResetToken,
} from "../src/services/passwordLifecycleApi.ts";
import {
  consumePasswordResetToken,
  passwordResetFailureState,
  passwordResetStateCopy,
  passwordsMatch,
} from "../src/features/auth/passwordResetFlow.ts";

const router = readFileSync(new URL("../src/app/AppRouter.tsx", import.meta.url), "utf8");
const signInPage = readFileSync(new URL("../src/pages/SignInPage.tsx", import.meta.url), "utf8");
const changePage = readFileSync(new URL("../src/pages/ChangePasswordPage.tsx", import.meta.url), "utf8");
const forgotPage = readFileSync(new URL("../src/pages/ForgotPasswordPage.tsx", import.meta.url), "utf8");
const resetPage = readFileSync(new URL("../src/pages/ResetPasswordPage.tsx", import.meta.url), "utf8");
const passwordApi = readFileSync(new URL("../src/services/passwordLifecycleApi.ts", import.meta.url), "utf8");
const resetFlow = readFileSync(new URL("../src/features/auth/passwordResetFlow.ts", import.meta.url), "utf8");
const agentSidebar = readFileSync(new URL("../src/components/layout/AgentSidebar.tsx", import.meta.url), "utf8");
const adminSidebar = readFileSync(new URL("../src/components/layout/AdminSidebar.tsx", import.meta.url), "utf8");
const activationPage = readFileSync(new URL("../src/pages/ActivationPage.tsx", import.meta.url), "utf8");

function response(config: InternalAxiosRequestConfig, data: unknown, status = 200): AxiosResponse {
  return { data, status, statusText: status === 200 ? "OK" : "Error", headers: {}, config };
}

function installAdapter(
  client: AxiosInstance,
  handler: (config: InternalAxiosRequestConfig) => AxiosResponse,
) {
  const original = client.defaults.adapter;
  const adapter: AxiosAdapter = async (config) => handler(config);
  client.defaults.adapter = adapter;
  return () => {
    client.defaults.adapter = original;
  };
}

function installSessionStorage(initialToken: string | null) {
  const values = new Map<string, string>();
  if (initialToken) values.set(AUTH_TOKEN_STORAGE_KEY, initialToken);
  const storage = {
    getItem(key: string) { return values.get(key) ?? null; },
    setItem(key: string, value: string) { values.set(key, value); },
    removeItem(key: string) { values.delete(key); },
    clear() { values.clear(); },
    key(index: number) { return Array.from(values.keys())[index] ?? null; },
    get length() { return values.size; },
  };
  Object.defineProperty(globalThis, "sessionStorage", { value: storage, configurable: true });
}

test("password lifecycle API contracts use the expected request shapes", async () => {
  installSessionStorage("stored-jwt");
  const restoreAuthenticated = installAdapter(
    (await import("../src/services/apiClient.ts")).apiClient,
    (config) => {
      assert.equal(config.url, "/auth/password/change");
      assert.equal(config.method, "post");
      assert.equal(config.headers.Authorization, "Bearer stored-jwt");
      assert.deepEqual(JSON.parse(String(config.data)), {
        current_password: "old-value",
        new_password: "new-value",
        new_password_confirmation: "new-value",
      });
      return response(config, {
        message: "Mot de passe modifié avec succès.",
        reauthentication_required: true,
      });
    },
  );
  try {
    const result = await changeOwnPassword({
      current_password: "old-value",
      new_password: "new-value",
      new_password_confirmation: "new-value",
    });
    assert.equal(result.reauthentication_required, true);
    assert.equal("access_token" in result, false);
  } finally {
    restoreAuthenticated();
  }

  const calls: Array<{ url?: string; data: unknown; authorization: unknown }> = [];
  const restorePublic = installAdapter(publicPasswordLifecycleClient, (config) => {
    calls.push({
      url: config.url,
      data: JSON.parse(String(config.data)),
      authorization: config.headers.Authorization,
    });
    if (config.url?.endsWith("forgot")) {
      return response(config, { message: "neutral", reset_url: null }, 202);
    }
    if (config.url?.endsWith("validate")) {
      return response(config, { valid: true, expires_at: "2026-07-30T12:00:00Z" });
    }
    return response(config, {
      message: "Mot de passe réinitialisé avec succès.",
      reauthentication_required: true,
    });
  });
  try {
    await requestPasswordReset({ email: "user@example.test" });
    await validatePasswordResetToken({ token: "reset-token" });
    const completed = await completePasswordReset({
      token: "reset-token",
      password: "new-value",
      password_confirmation: "new-value",
    });
    assert.equal(completed.reauthentication_required, true);
  } finally {
    restorePublic();
  }

  assert.deepEqual(calls, [
    { url: "/auth/password/forgot", data: { email: "user@example.test" }, authorization: undefined },
    { url: "/auth/password/reset/validate", data: { token: "reset-token" }, authorization: undefined },
    {
      url: "/auth/password/reset/complete",
      data: { token: "reset-token", password: "new-value", password_confirmation: "new-value" },
      authorization: undefined,
    },
  ]);
});

test("public password-reset client is isolated from authenticated session clearing", async () => {
  installSessionStorage("existing-auth-token");
  const restorePublic = installAdapter(publicPasswordLifecycleClient, (config) => {
    const errorResponse = response(config, {
      detail: { message: "Password reset link is not valid.", code: "invalid" },
    }, 400);
    throw new AxiosError("Request failed", undefined, config, undefined, errorResponse);
  });
  try {
    await assert.rejects(validatePasswordResetToken({ token: "bad-token" }));
    assert.equal(getStoredToken(), "existing-auth-token");
  } finally {
    restorePublic();
  }
  assert.match(passwordApi, /publicPasswordLifecycleClient = axios\.create/);
  assert.doesNotMatch(passwordApi, /publicPasswordLifecycleClient\.interceptors/);
  assert.doesNotMatch(passwordApi, /authStorage|Authorization header|console\./);
});

test("change-password page renders protected form behavior and forced logout path", () => {
  assert.match(router, /path="\/settings\/password"/);
  assert.match(router, /<ProtectedRoute roles=\{\["agent", "admin"\]\}>\s*<ChangePasswordPage \/>/);
  assert.match(changePage, /id="change-current-password"/);
  assert.match(changePage, /id="change-new-password"/);
  assert.match(changePage, /id="change-password-confirmation"/);
  assert.match(changePage, /autoComplete="current-password"/);
  assert.equal((changePage.match(/autoComplete="new-password"/g) ?? []).length, 2);
  assert.match(changePage, /newPassword !== confirmation/);
  assert.match(changePage, /submissionActive\.current/);
  assert.match(changePage, /changeOwnPassword\(\{/);
  assert.match(changePage, /current_password: currentPassword/);
  assert.match(changePage, /new_password: newPassword/);
  assert.match(changePage, /new_password_confirmation: confirmation/);
  assert.match(changePage, /clearSecrets\(\);\s*if \(response\.reauthentication_required\)/);
  assert.match(changePage, /signOut\(\);\s*navigate\("\/signin\?password_changed=1"/);
  assert.match(changePage, /disabled=\{submitting\}/);
  assert.doesNotMatch(changePage, /access_token|token_version|console\.|localStorage|sessionStorage/);
});

test("change-password navigation is discoverable without duplicating routing", () => {
  assert.match(agentSidebar, /Changer le mot de passe/);
  assert.match(agentSidebar, /path: "\/settings\/password"/);
  assert.match(adminSidebar, /Changer le mot de passe/);
  assert.match(adminSidebar, /to="\/settings\/password"/);
});

test("forgot-password page uses neutral email-only public flow and local capture guard", () => {
  assert.match(signInPage, /to="\/forgot-password"/);
  assert.match(signInPage, /Mot de passe oublié \?/);
  assert.match(forgotPage, /id="forgot-password-email"/);
  assert.match(forgotPage, /type="email"/);
  assert.doesNotMatch(forgotPage, /type=\{showPassword|autoComplete="current-password"|autoComplete="new-password"/);
  assert.match(forgotPage, /requestPasswordReset\(\{ email: email\.trim\(\) \}\)/);
  assert.match(forgotPage, /setMessage\(response\.message\)/);
  assert.match(forgotPage, /setEmail\(""\)/);
  assert.match(forgotPage, /submissionActive\.current/);
  assert.match(forgotPage, /resetUrl &&/);
  assert.match(forgotPage, /Mode développement uniquement/);
  assert.match(forgotPage, /Ouvrir le lien de test local/);
  assert.match(forgotPage, /const url = resetUrl;\s*setResetUrl\(null\);\s*window\.open\(url/);
  assert.doesNotMatch(forgotPage, /\{resetUrl\}|console\.|localStorage|sessionStorage|Authorization/);
});

test("reset-password token is read once removed from history and never persisted", () => {
  const secret = "reset-token-value";
  let replacement = "";
  assert.equal(consumePasswordResetToken(`https://ui.test/reset-password?token=${secret}&source=email#form`, (path) => { replacement = path; }), secret);
  assert.equal(replacement, "/reset-password?source=email#form");
  assert.doesNotMatch(replacement, /token=/);
  assert.match(resetPage, /history\.replaceState/);
  assert.match(resetPage, /tokenRef\.current/);
  assert.match(resetPage, /validatePasswordResetToken\(\{ token \}/);
  assert.match(resetPage, /completePasswordReset\(\{/);
  assert.match(resetPage, /token,\s*password,\s*password_confirmation: confirmation/);
  assert.doesNotMatch(resetPage, /localStorage|sessionStorage|console\.|Authorization|axios\.defaults/);
  assert.doesNotMatch(passwordApi, /reset-token-value/);
});

test("reset-password page maps lifecycle states and clears secrets on success", () => {
  assert.equal(passwordResetFailureState(400, "invalid"), "invalid");
  assert.equal(passwordResetFailureState(400, "expired"), "expired");
  assert.equal(passwordResetFailureState(400, "consumed"), "consumed");
  assert.equal(passwordResetFailureState(503, undefined), "failed");
  assert.equal(passwordResetStateCopy("invalid").title, "Lien invalide");
  assert.equal(passwordResetStateCopy("expired").title, "Lien expiré");
  assert.equal(passwordResetStateCopy("consumed").title, "Lien déjà utilisé");
  assert.equal(passwordResetStateCopy("failed").title, "Service indisponible");
  assert.match(resetPage, /state === "validating"/);
  assert.match(resetPage, /state === "valid"/);
  assert.match(resetPage, /state === "complete"/);
  assert.match(resetPage, /!passwordsMatch\(password, confirmation\)/);
  assert.match(resetPage, /submissionActive\.current/);
  assert.match(resetPage, /tokenRef\.current = null;\s*setPassword\(""\);\s*setConfirmation\(""\)/);
  assert.match(resetPage, /disabled=\{submitting\}/);
  assert.equal(passwordsMatch("été 🚀", "été 🚀"), true);
  assert.equal(passwordsMatch(" leading", "leading"), false);
});

test("password lifecycle error mapping is safe and non-sensitive", () => {
  assert.equal(changePasswordErrorMessage(new Error("boom")), "Le changement de mot de passe a échoué. Réessayez dans un instant.");
  assert.equal(resetCompletionErrorMessage(new Error("boom")), "La réinitialisation a échoué. Réessayez dans un instant.");
  for (const source of [changePage, forgotPage, resetPage, passwordApi, resetFlow]) {
    assert.doesNotMatch(source, /password_hash|token_hash|Authorization header|stack|traceback|SQL|console\./);
  }
});

test("routing keeps public and protected route boundaries", () => {
  assert.match(router, /path="\/signin" element=\{<SignInPage \/>\}/);
  assert.match(router, /path="\/activate" element=\{<ActivationPage \/>\}/);
  assert.match(router, /path="\/forgot-password" element=\{<ForgotPasswordPage \/>\}/);
  assert.match(router, /path="\/reset-password" element=\{<ResetPasswordPage \/>\}/);
  assert.ok(router.indexOf('path="/forgot-password"') < router.indexOf('path="/settings/password"'));
  assert.ok(router.indexOf('path="/reset-password"') < router.indexOf('path="/settings/password"'));
  assert.match(router, /path="\/agent"[\s\S]*<ProtectedRoute roles=\{\["agent", "admin"\]\}>/);
  assert.match(router, /path="\/admin"[\s\S]*<ProtectedRoute roles=\{\["admin"\]\}>/);
  assert.match(activationPage, /consumeActivationToken/);
});
