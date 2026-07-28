export const AUTH_TOKEN_STORAGE_KEY = "lab_ia_genius_access_token";

export function getStoredToken() {
  return sessionStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
}

export function storeAuthToken(token: string) {
  sessionStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
}

export function clearAuthSession() {
  sessionStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
}
