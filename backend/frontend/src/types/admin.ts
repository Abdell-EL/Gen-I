export type EditableUserRole = "admin" | "agent";
export type UserRole = EditableUserRole | (string & {});

export type AdminUser = {
  id: number;
  full_name: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  department_id: number | null;
  created_at: string | null;
  updated_at: string | null;
};

export type UserListResponse = {
  items: AdminUser[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
};

export type UserListFilters = {
  page?: number;
  page_size?: number;
  search?: string;
  role?: EditableUserRole;
  is_active?: boolean;
  sort_by?: "created_at" | "full_name" | "email" | "role";
  sort_order?: "asc" | "desc";
};

export type CreateUserPayload = {
  full_name: string;
  email: string;
  password: string;
  role: EditableUserRole;
  department_id: number | null;
  is_active: boolean;
};

export type UpdateUserPayload = Partial<
  Pick<AdminUser, "full_name" | "email" | "department_id" | "is_active">
> & { role?: EditableUserRole };

export type PasswordResetResponse = {
  status: "password_reset";
  user_id: number;
};

export type DateRangeFilters = {
  date_from?: string;
  date_to?: string;
};

export type UserActivityItem = {
  user_id: number;
  full_name: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  questions_count: number;
  last_question_at: string | null;
};

export type UserActivityFilters = DateRangeFilters & {
  page?: number;
  page_size?: number;
  role?: EditableUserRole;
  is_active?: boolean;
};

export type UserActivityResponse = {
  items: UserActivityItem[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
  date_from: string | null;
  date_to: string | null;
};

export type QuestionAnalyticsItem = {
  question: string;
  normalized_question: string;
  count: number;
  unique_users: number;
  last_asked_at: string;
  example_user: { user_id: number; full_name: string };
};

export type QuestionAnalyticsFilters = DateRangeFilters & {
  limit?: number;
  user_id?: number;
  role?: EditableUserRole;
  minimum_count?: number;
};

export type QuestionAnalyticsResponse = {
  items: QuestionAnalyticsItem[];
  date_from: string | null;
  date_to: string | null;
  normalization: string;
};
