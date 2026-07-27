export type UserRole = "agent" | "admin";

export type AuthUser = {
  id: number | string;
  name: string;
  email: string;
  role: UserRole;
};

export type AuthResponse = {
  access_token: string;
  token_type: "bearer";
  user: AuthUser;
};

export type SignInPayload = {
  email: string;
  password: string;
};

export type SignUpPayload = {
  name: string;
  email: string;
  password: string;
  role: UserRole;
};
