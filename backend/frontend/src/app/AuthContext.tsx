import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  AUTH_MODE,
  getCurrentUser,
  logout as logoutRequest,
  signIn as signInRequest,
  signUp as signUpRequest,
} from "../services/authApi";
import {
  clearAuthSession,
  getStoredToken,
  getStoredUser,
} from "../services/authStorage";
import type { AuthUser } from "../types/auth";
import { AuthContext, type AuthContextValue } from "./authContextValue";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => getStoredUser());
  const shouldValidateBackendSession =
    AUTH_MODE === "backend" && Boolean(getStoredToken());
  const [ready, setReady] = useState(!shouldValidateBackendSession);

  useEffect(() => {
    if (!shouldValidateBackendSession) return;

    let active = true;
    void getCurrentUser()
      .then((currentUser) => {
        if (active) setUser(currentUser);
      })
      .catch(() => {
        clearAuthSession();
        if (active) setUser(null);
      })
      .finally(() => {
        if (active) setReady(true);
      });

    return () => {
      active = false;
    };
  }, [shouldValidateBackendSession]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      ready,
      mode: AUTH_MODE,
      signIn: async (payload) => {
        const response = await signInRequest(payload);
        setUser(response.user);
        return response.user;
      },
      signUp: async (payload) => {
        const response = await signUpRequest(payload);
        setUser(response.user);
        return response.user;
      },
      logout: async () => {
        try {
          await logoutRequest();
        } finally {
          clearAuthSession();
          setUser(null);
        }
      },
    }),
    [ready, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
