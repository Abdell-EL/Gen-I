import { createContext } from "react";

import type { AuthUser } from "../types/auth";

export type AuthContextValue = {
  user: AuthUser | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  isInitialising: boolean;
  isSubmitting: boolean;
  authenticationError: string | null;
  signIn: (email: string, password: string) => Promise<AuthUser>;
  signOut: () => void;
  restoreSession: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);
