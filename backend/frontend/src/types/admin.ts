export type EditableUserRole = "admin" | "agent";
export type UserRole = EditableUserRole | (string & {});

export type AdminUser = {
  id: number;
  full_name: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  activation_status: "pending" | "active";
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
  role: EditableUserRole;
};

export type InvitationDelivery = {
  status: "sent" | "not_sent" | "failed";
  activation_url: string | null;
};

export type InvitedUserResponse = AdminUser & { invitation_delivery: InvitationDelivery };

export type InvitationResendResponse = {
  user_id: number;
  activation_status: "pending";
  invitation_delivery: InvitationDelivery;
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
  include_benchmarks?: boolean;
};

export type QuestionAnalyticsResponse = {
  items: QuestionAnalyticsItem[];
  date_from: string | null;
  date_to: string | null;
  normalization: string;
  include_benchmarks: boolean;
};

export type KnowledgeSearchType = "search" | "keyword_search" | "chat";
export type KnowledgeFilters = DateRangeFilters & {
  user_id?: number;
  role?: EditableUserRole;
  search_type?: KnowledgeSearchType;
  include_benchmarks?: boolean;
};
export type TrendingQuestion = {
  question: string; normalized_question: string; current_count: number;
  previous_count: number; absolute_change: number; percentage_change: number | null;
  unique_users: number; last_asked_at: string;
};
export type TrendingQuestionsResponse = {
  items: TrendingQuestion[]; date_from: string | null; date_to: string | null;
  previous_period: boolean; include_benchmarks: boolean; normalization: string;
};
export type AnalyticsUser = { id: number; name: string; email: string; role: string };
export type LowConfidenceItem = {
  retrieval_id: number; query_text: string; created_at: string; user: AnalyticsUser;
  search_type: KnowledgeSearchType | null; results_count: number;
  top_score: number | null; average_score: number | null;
  low_confidence_reason: "zero_results" | "top_score_below_threshold";
  top_article_title: string | null; top_kb_code: string | null;
};
export type LowConfidenceFilters = KnowledgeFilters & {
  threshold?: number; include_zero_results?: boolean; page?: number; page_size?: number;
};
export type LowConfidenceResponse = {
  items: LowConfidenceItem[]; page: number; page_size: number; total: number; pages: number;
  threshold: number; include_zero_results: boolean; include_benchmarks: boolean;
};
export type ScoreBucket = { lower_bound: number; upper_bound: number; count: number; percentage: number };
export type ScoreDistributionResponse = {
  bucket_size: number; score_basis: "top_score" | "all_results"; total: number;
  buckets: ScoreBucket[]; include_benchmarks: boolean;
};
export type ArticleAnalyticsItem = {
  article_title: string | null; kb_code: string | null; consultation_count: number;
  unique_requests: number; unique_users: number; average_score: number; top_score: number;
  last_consulted_at: string;
};
export type ArticleFilters = KnowledgeFilters & {
  search?: string; page?: number; page_size?: number;
  sort_by?: "consultation_count" | "unique_users" | "last_consulted_at" | "article_title";
  sort_order?: "asc" | "desc";
};
export type ArticleAnalyticsResponse = {
  items: ArticleAnalyticsItem[]; page: number; page_size: number; total: number; pages: number;
};
export type UnreferencedContentItem = {
  source_document_id: number; filename: string; title: string | null; kb_code: string | null;
  current_version_chunk_count: number; created_at: string | null; last_referenced_at: string | null;
  reference_count: number; reference_scope: "selected_period";
};
export type UnreferencedFilters = DateRangeFilters & { search?: string; page?: number; page_size?: number };
export type UnreferencedContentResponse = {
  items: UnreferencedContentItem[]; page: number; page_size: number; total: number; pages: number;
  date_from: string | null; date_to: string | null;
  scope_label: "unreferenced_in_selected_period";
};
export type RetrievalResultDetail = {
  rank: number; score: number; chunk_external_id: string | null; article_title: string | null;
  kb_code: string | null; section_title: string | null; chunk_type: string | null; priority: string | null;
};
export type RetrievalDrillDown = {
  retrieval_id: number; query_text: string; created_at: string; top_k: number | null;
  user: AnalyticsUser; search_type: KnowledgeSearchType | null; result_count: number;
  session_id: number | null; message_id: number | null; results: RetrievalResultDetail[];
};
export type FeedbackSummary = { total_feedback: number; helpful_count: number;
  partially_helpful_count: number; not_helpful_count: number; helpful_percentage: number;
  negative_percentage: number; feedback_unique_users: number; feedback_unique_messages: number;
  most_common_negative_reason: string | null; most_affected_article: { article_title: string | null;
  kb_code: string | null; negative_feedback_count: number } | null;
  trend: { current_total: number; previous_total: number; absolute_change: number;
  percentage_change: number | null } | null };
export type AdminFeedbackItem = { feedback_id: number; created_at: string; updated_at: string;
  rating: string; reason: string | null; comment: string | null;
  user: { id: number; full_name: string; email: string; role: string };
  message_id: number; session_id: number; retrieval_id: number | null; question: string | null;
  answer: string; search_type: string | null; confidence: string | null;
  referenced_articles: Array<{ article_title: string | null; kb_code: string | null; top_score: number }>;
  result_count: number; results?: RetrievalResultDetail[] };
export type FeedbackListResponse = { items: AdminFeedbackItem[]; page: number; page_size: number;
  total: number; pages: number };
