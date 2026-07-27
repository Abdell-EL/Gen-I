import type {
  AuthResponse,
  AuthUser,
  SignInPayload,
  SignUpPayload,
} from "../types/auth";
import { apiClient } from "./apiClient";
import {
  clearAuthSession,
  getStoredUser,
  storeAuthSession,
} from "./authStorage";

export const AUTH_MODE =
  import.meta.env.VITE_AUTH_MODE === "backend" ? "backend" : "demo";

type DemoUser = AuthUser & {
  password: string;
};

const DEMO_USERS_KEY = "sogetrel.auth.demo-users";

const builtInDemoUsers: DemoUser[] = [
  {
    id: "demo-agent",
    name: "Agent Démo",
    email: "agent@sogetrel.local",
    password: "agent123",
    role: "agent",
  },
  {
    id: "demo-admin",
    name: "Admin Démo",
    email: "admin@sogetrel.local",
    password: "admin123",
    role: "admin",
  },
];

function getLocalDemoUsers(): DemoUser[] {
  const stored = localStorage.getItem(DEMO_USERS_KEY);
  if (!stored) return [];

  try {
    return JSON.parse(stored) as DemoUser[];
  } catch {
    localStorage.removeItem(DEMO_USERS_KEY);
    return [];
  }
}

function saveLocalDemoUsers(users: DemoUser[]) {
  localStorage.setItem(DEMO_USERS_KEY, JSON.stringify(users));
}

function createDemoResponse(user: DemoUser): AuthResponse {
  const safeUser: AuthUser = {
    id: user.id,
    name: user.name,
    email: user.email,
    role: user.role,
  };
  return {
    access_token: `demo-token-${safeUser.id}`,
    token_type: "bearer",
    user: safeUser,
  };
}

export async function signIn(payload: SignInPayload) {
  if (AUTH_MODE === "backend") {
    const response = await apiClient.post<AuthResponse>("/auth/signin", payload);
    storeAuthSession(response.data.access_token, response.data.user);
    return response.data;
  }

  const normalizedEmail = payload.email.trim().toLowerCase();
  const user = [...builtInDemoUsers, ...getLocalDemoUsers()].find(
    (candidate) =>
      candidate.email.toLowerCase() === normalizedEmail &&
      candidate.password === payload.password,
  );

  if (!user) {
    throw new Error("Identifiants incorrects pour le mode démonstration.");
  }

  const demoResponse = createDemoResponse(user);
  storeAuthSession(demoResponse.access_token, demoResponse.user);
  return demoResponse;
}

export async function signUp(payload: SignUpPayload) {
  if (AUTH_MODE === "backend") {
    const response = await apiClient.post<AuthResponse>("/auth/signup", payload);
    storeAuthSession(response.data.access_token, response.data.user);
    return response.data;
  }

  const normalizedEmail = payload.email.trim().toLowerCase();
  const allUsers = [...builtInDemoUsers, ...getLocalDemoUsers()];
  if (allUsers.some((user) => user.email.toLowerCase() === normalizedEmail)) {
    throw new Error("Un compte de démonstration utilise déjà cette adresse.");
  }

  // Demo mode stores credentials locally for preview only. Production security
  // requires server-side password hashing, sessions and role enforcement.
  const demoUser: DemoUser = {
    id: `local-${crypto.randomUUID()}`,
    name: payload.name.trim(),
    email: normalizedEmail,
    password: payload.password,
    role: payload.role,
  };
  saveLocalDemoUsers([...getLocalDemoUsers(), demoUser]);

  const demoResponse = createDemoResponse(demoUser);
  storeAuthSession(demoResponse.access_token, demoResponse.user);
  return demoResponse;
}

export async function getCurrentUser() {
  if (AUTH_MODE === "demo") return getStoredUser();
  const response = await apiClient.get<AuthUser>("/auth/me");
  return response.data;
}

export async function logout() {
  if (AUTH_MODE === "backend") {
    await apiClient.post("/auth/logout");
  }
  clearAuthSession();
}
