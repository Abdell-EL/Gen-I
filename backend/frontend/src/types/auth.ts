export type UserRole = "agent" | "admin";

export type AuthUser = {
  id: number;
  full_name: string;
  email: string;
  role: UserRole;
  is_active: boolean;
};

export type AuthResponse = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: AuthUser;
};
