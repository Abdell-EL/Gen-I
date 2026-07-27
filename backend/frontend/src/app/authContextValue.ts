import { createContext } from "react";

import type {
  AuthUser,
  SignInPayload,
  SignUpPayload,
} from "../types/auth";

export type AuthContextValue = {
  user: AuthUser | null;
  ready: boolean;
  mode: "demo" | "backend";
  signIn: (payload: SignInPayload) => Promise<AuthUser>;
  signUp: (payload: SignUpPayload) => Promise<AuthUser>;
  logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);
