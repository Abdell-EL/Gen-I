import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import axios from "axios";

import { GENERIC_LOGIN_ERROR, getCurrentUser, signIn as signInRequest } from "../services/authApi";
import { clearAuthSession, getStoredToken, storeAuthToken } from "../services/authStorage";
import { SESSION_EXPIRED_EVENT } from "../services/apiClient";
import type { AuthUser } from "../types/auth";
import { AuthContext, type AuthContextValue } from "./authContextValue";

const SESSION_EXPIRED_MESSAGE = "Votre session a expiré. Veuillez vous reconnecter.";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [isInitialising, setIsInitialising] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [authenticationError, setAuthenticationError] = useState<string | null>(null);
  const requestVersion = useRef(0);
  const activeRequest = useRef<AbortController | null>(null);
  const submissionActive = useRef(false);

  const clearSession = useCallback(() => {
    clearAuthSession();
    setAccessToken(null);
    setUser(null);
  }, []);

  const restoreSession = useCallback(async () => {
    const version = ++requestVersion.current;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setIsInitialising(true);
    const storedToken = getStoredToken();
    if (!storedToken) {
      clearSession();
      setIsInitialising(false);
      return;
    }
    try {
      const currentUser = await getCurrentUser(storedToken, controller.signal);
      if (version !== requestVersion.current) return;
      setAccessToken(storedToken);
      setUser(currentUser);
    } catch (error) {
      if (version !== requestVersion.current) return;
      // Only a confirmed 401 means the token is actually invalid/expired —
      // that's the one case it's correct to wipe it. Anything else (a
      // timeout, a network blip, a transient 5xx — e.g. a saturated DB
      // connection pool during concurrent chat traffic) is not proof the
      // token is bad, so destroying it here would force a password re-login
      // over what might resolve itself on the very next reload.
      if (axios.isAxiosError(error) && error.response?.status === 401) {
        clearSession();
      } else {
        setAccessToken(null);
        setUser(null);
      }
    } finally {
      if (version === requestVersion.current) setIsInitialising(false);
    }
  }, [clearSession]);

  useEffect(() => {
    const timer = window.setTimeout(() => void restoreSession(), 0);
    return () => {
      window.clearTimeout(timer);
      requestVersion.current += 1;
      activeRequest.current?.abort();
    };
  }, [restoreSession]);

  useEffect(() => {
    function handleSessionExpired() {
      clearSession();
      setAuthenticationError(SESSION_EXPIRED_MESSAGE);
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
  }, [clearSession]);

  const signIn = useCallback(async (email: string, password: string) => {
    if (submissionActive.current) throw new Error(GENERIC_LOGIN_ERROR);
    submissionActive.current = true;
    const version = ++requestVersion.current;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setIsSubmitting(true);
    setAuthenticationError(null);
    try {
      const response = await signInRequest(email.trim(), password, controller.signal);
      if (version !== requestVersion.current) throw new Error(GENERIC_LOGIN_ERROR);
      storeAuthToken(response.access_token);
      setAccessToken(response.access_token);
      setUser(response.user);
      return response.user;
    } catch (error) {
      if (version === requestVersion.current) {
        clearSession();
        setAuthenticationError(GENERIC_LOGIN_ERROR);
      }
      throw error;
    } finally {
      if (version === requestVersion.current) {
        submissionActive.current = false;
        setIsSubmitting(false);
      }
    }
  }, [clearSession]);

  const signOut = useCallback(() => {
    requestVersion.current += 1;
    activeRequest.current?.abort();
    activeRequest.current = null;
    clearSession();
    submissionActive.current = false;
    setIsSubmitting(false);
    setAuthenticationError(null);
  }, [clearSession]);

  const value = useMemo<AuthContextValue>(() => ({
    user, accessToken, isAuthenticated: Boolean(user && accessToken), isInitialising,
    isSubmitting, authenticationError, signIn, signOut, restoreSession,
  }), [accessToken, authenticationError, isInitialising, isSubmitting, restoreSession, signIn, signOut, user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
