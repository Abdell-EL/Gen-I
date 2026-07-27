export type SourcePreview = {
  rank: number | null;
  score: number | null;
  id: string | null;
  kb_code: string | null;
  article_title: string | null;
  section_title: string | null;
  chunk_type: string | null;
  priority: string | null;
  text: string | null;
};

export type AuditRef = {
  audit_logged: boolean;
  retrieval_id: number | null;
  user_id: number | null;
  session_id: number | null;
  message_id: number | null;
  logged_results: number;
  missing_chunk_ids: string[];
};

export type ChatResponse = {
  question: string;
  answer: string;
  confidence: string;
  sources: SourcePreview[];
  audit: AuditRef | null;
  generation_provider: string | null;
  generation_model: string | null;
  generation_error: string | null;
};

export type ComponentHealth = {
  status: string;
  connected: boolean;
  error?: string;
};

export type PostgresHealth = ComponentHealth & {
  chunks_count?: number;
  expected_chunks?: number;
  source_documents_count?: number;
  expected_source_documents?: number;
  retrieval_requests_count?: number;
};

export type MilvusHealth = ComponentHealth & {
  collection?: string;
  collection_exists?: boolean;
  vectors_count?: number;
  expected_vectors?: number;
};

export type HealthResponse = {
  status: string;
  service: string;
  version: string;
  components: {
    postgres?: PostgresHealth;
    milvus?: MilvusHealth;
  };
};

export type StatsResponse = {
  articles: number;
  chunks: number;
  vector_collection: string;
  [key: string]: string | number | boolean | null | undefined;
};

export type IngestionStatus =
  | "processing"
  | "completed"
  | "failed"
  | "duplicate"
  | (string & {});

export type IngestionUploadResponse = {
  job_id: number;
  status: IngestionStatus;
  filename: string;
  kb_code: string | null;
  article_title: string | null;
  document_id: number | null;
  version_id: number | null;
  chunks_created: number;
  embeddings_created: number;
  milvus_vectors_inserted: number;
  message: string;
};

export type IngestionJobSummary = {
  job_id: number;
  job_type: string;
  status: IngestionStatus;
  source_path: string | null;
  filename: string | null;
  created_at: string | null;
  updated_at: string | null;
  processed_documents: number;
  processed_chunks: number;
  error_message: string | null;
};

export type IngestionJobDetail = IngestionJobSummary & {
  document_id: number | null;
  version_id: number | null;
  kb_code: string | null;
  article_title: string | null;
  chunks_created: number;
  embeddings_created: number;
  config_json: Record<string, unknown> | null;
};

export type AuditSummary = {
  retrieval_id?: number;
  query_text?: string;
  top_k?: number;
  embedding_model?: string;
  milvus_collection?: string;
  results_count?: number;
  top_score?: number;
  created_at?: string;
  user_id?: number;
  full_name?: string;
  email?: string;
};

export type AuditListResponse = {
  count: number;
  retrievals: AuditSummary[];
};

export type AuditDetailResult = {
  rank?: number;
  similarity_score?: number;
  chunk_id?: number;
  external_chunk_id?: string;
  chunk_text?: string;
  chunk_type?: string;
  metadata_json?: Record<string, unknown>;
};

export type AuditDetailResponse = {
  retrieval: AuditSummary & {
    filters_json?: Record<string, unknown>;
    retriever_config_json?: Record<string, unknown>;
    message_id?: number;
    message_role?: string;
    message_content?: string;
  };
  results_count: number;
  results: AuditDetailResult[];
};
