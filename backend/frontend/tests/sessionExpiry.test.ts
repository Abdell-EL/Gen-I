import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { AxiosError } from "axios";
import type { AxiosAdapter, AxiosInstance, AxiosResponse, InternalAxiosRequestConfig } from "axios";

import { AUTH_TOKEN_STORAGE_KEY, AGENT_CONVERSATION_STORAGE_KEY } from "../src/services/authStorage.ts";

const authContextSource = readFileSync(new URL("../src/app/AuthContext.tsx", import.meta.url), "utf8");

function response(config: InternalAxiosRequestConfig, data: unknown, status = 200): AxiosResponse {
  return { data, status, statusText: status === 200 ? "OK" : "Error", headers: {}, config };
}

function unauthorized(config: InternalAxiosRequestConfig): never {
  throw new AxiosError("Request failed with status code 401", "ERR_BAD_REQUEST", config,
    undefined, response(config, { detail: "Not authenticated." }, 401));
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

// Real browsers' `window` is an EventTarget; this gives the interceptor the
// same real dispatchEvent/addEventListener behavior under plain Node, rather
// than a hand-rolled stand-in.
function installWindow() {
  const target = new EventTarget();
  Object.defineProperty(globalThis, "window", { value: target, configurable: true });
  return target;
}

test("a 401 on a protected endpoint dispatches the session-expired event", async () => {
  installSessionStorage("stored-jwt");
  const windowTarget = installWindow();
  const { apiClient, SESSION_EXPIRED_EVENT } = await import("../src/services/apiClient.ts");
  const restore = installAdapter(apiClient, (config) => unauthorized(config));

  let fired = false;
  windowTarget.addEventListener(SESSION_EXPIRED_EVENT, () => { fired = true; });

  try {
    await assert.rejects(() => apiClient.get("/admin/users"));
    assert.equal(fired, true);
  } finally {
    restore();
  }
});

test("a 401 on /auth/signin does NOT dispatch the session-expired event (that's a wrong-password case)", async () => {
  installSessionStorage(null);
  const windowTarget = installWindow();
  const { apiClient, SESSION_EXPIRED_EVENT } = await import("../src/services/apiClient.ts");
  const restore = installAdapter(apiClient, (config) => unauthorized(config));

  let fired = false;
  windowTarget.addEventListener(SESSION_EXPIRED_EVENT, () => { fired = true; });

  try {
    await assert.rejects(() => apiClient.post("/auth/signin", { email: "a@b.com", password: "wrong" }));
    assert.equal(fired, false);
  } finally {
    restore();
  }
});

test("the blocking chat request uses a 120s timeout, not the client's 20s default", async () => {
  installSessionStorage("stored-jwt");
  installWindow();
  const { apiClient } = await import("../src/services/apiClient.ts");
  const { askKnowledgeBase } = await import("../src/services/chatApi.ts");
  let seenTimeout: number | undefined;
  const restore = installAdapter(apiClient, (config) => {
    seenTimeout = config.timeout;
    return response(config, {
      question: "q", answer: "a", confidence: "high", sources: [], audit: null,
      generation_provider: "ollama", generation_model: "llama3.2:3b", generation_error: null,
    });
  });
  try {
    await askKnowledgeBase("q");
    assert.equal(seenTimeout, 120_000);
  } finally {
    restore();
  }
});

test("logging out clears the cached conversation too, so the next user on this tab doesn't inherit it", async () => {
  installSessionStorage("stored-jwt");
  sessionStorage.setItem(AGENT_CONVERSATION_STORAGE_KEY, JSON.stringify({
    sessionId: 42,
    messages: [{ id: "u-1", role: "user", content: "admin's question", messageId: 1 }],
  }));

  const { clearAuthSession } = await import("../src/services/authStorage.ts");
  clearAuthSession();

  assert.equal(sessionStorage.getItem(AUTH_TOKEN_STORAGE_KEY), null);
  assert.equal(sessionStorage.getItem(AGENT_CONVERSATION_STORAGE_KEY), null);
});

test("AuthContext wires the session-expired event to clearSession and a French message", () => {
  assert.match(authContextSource, /SESSION_EXPIRED_EVENT/);
  assert.match(authContextSource, /addEventListener\(SESSION_EXPIRED_EVENT, handleSessionExpired\)/);
  assert.match(authContextSource, /clearSession\(\)/);
  assert.match(authContextSource, /Votre session a expiré/);
});

test("restoreSession only wipes the stored token on a confirmed 401, not on any other failure", () => {
  // A transient failure (timeout, network blip, a saturated DB connection
  // pool under concurrent chat load) is not proof the token is invalid —
  // destroying it on any error was forcing a password re-login over
  // something that might resolve itself on the very next reload.
  const restoreSessionBody = authContextSource.slice(
    authContextSource.indexOf("const restoreSession"),
    authContextSource.indexOf("}, [clearSession]);"),
  );
  assert.match(restoreSessionBody, /axios\.isAxiosError\(error\)\s*&&\s*error\.response\?\.status === 401/);
  assert.match(restoreSessionBody, /clearSession\(\);\s*\} else \{/);
});
