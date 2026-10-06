export const AUTH_TOKEN_STORAGE_KEY = "lab_ia_genius_access_token";

// Anything cached per-session that must never survive a user switch within
// the same browser tab belongs here, listed alongside the token itself, so
// clearAuthSession() stays the single place that guarantees a clean slate
// for the next person who logs in on this tab.
export const AGENT_CONVERSATION_STORAGE_KEY = "lab-ia-genius.agentConversation.v1";

export function getStoredToken() {
  return sessionStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
}

export function storeAuthToken(token: string) {
  sessionStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
}

export function clearAuthSession() {
  sessionStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
  sessionStorage.removeItem(AGENT_CONVERSATION_STORAGE_KEY);
}
