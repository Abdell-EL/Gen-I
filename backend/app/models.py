from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Float,
    ForeignKey, JSON, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Department(Base):
    __tablename__ = "departments"

    department_id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    code = Column(String, unique=True, nullable=False)

    users = relationship("User", back_populates="department")
    knowledge_bases = relationship("KnowledgeBase", back_populates="department")


class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, index=True)
    department_id = Column(
        Integer,
        ForeignKey("departments.department_id"),
        nullable=True,
    )
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)

    password_hash = Column(String, nullable=True)
    role = Column(String, nullable=False, default="agent")
    is_active = Column(Boolean, nullable=False, default=True)
    activation_status = Column(String, nullable=False, default="pending")
    token_version = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, nullable=True)

    department = relationship("Department", back_populates="users")
    chat_sessions = relationship("ChatSession", back_populates="user")


class Role(Base):
    __tablename__ = "roles"

    role_id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=True)


class UserRole(Base):
    __tablename__ = "user_roles"

    user_role_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.role_id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.kb_id"), nullable=True)
    granted_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    granted_at = Column(DateTime, server_default=func.now())


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    kb_id = Column(Integer, primary_key=True, index=True)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    version = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, nullable=True)
    created_by_fk = Column(Integer, ForeignKey("users.user_id"), nullable=True)

    department = relationship("Department", back_populates="knowledge_bases")
    documents = relationship("SourceDocument", back_populates="knowledge_base")


class KBPermission(Base):
    __tablename__ = "kb_permissions"

    permission_id = Column(Integer, primary_key=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.kb_id"), nullable=False)
    principal_type = Column(String, nullable=False)  # USER or ROLE
    principal_id = Column(Integer, nullable=False)
    permission = Column(String, nullable=False)  # read, write, admin
    granted_by_fk = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    granted_at = Column(DateTime, server_default=func.now())
    revoked_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)


class SourceDocument(Base):
    __tablename__ = "source_documents"

    document_id = Column(Integer, primary_key=True, index=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.kb_id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=False)
    file_name = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    source_path = Column(String, nullable=True)
    created_by_fk = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    current_version_id = Column(Integer, nullable=True)
    checksum = Column(String, nullable=True)
    processing_status = Column(String, nullable=False, default="pending")

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    versions = relationship("DocumentVersion", back_populates="document")


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    version_id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("source_documents.document_id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    uploaded_at = Column(DateTime, server_default=func.now())
    uploaded_by = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    checksum = Column(String, nullable=True)
    storage_path = Column(String, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    change_notes = Column(Text, nullable=True)
    processing_status = Column(String, nullable=False, default="pending")
    is_current = Column(Boolean, default=True)

    document = relationship("SourceDocument", back_populates="versions")
    sheets = relationship("DocumentSheet", back_populates="version")

    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_version"),
    )


class DocumentSheet(Base):
    __tablename__ = "document_sheets"

    sheet_id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("source_documents.document_id"), nullable=False)
    version_id = Column(Integer, ForeignKey("document_versions.version_id"), nullable=False)
    sheet_name = Column(String, nullable=False)
    sheet_index = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    version = relationship("DocumentVersion", back_populates="sheets")
    chunks = relationship("Chunk", back_populates="sheet")


class Chunk(Base):
    __tablename__ = "chunks"

    chunk_id = Column(Integer, primary_key=True)
    sheet_id = Column(Integer, ForeignKey("document_sheets.sheet_id"), nullable=False)
    version_id = Column(Integer, ForeignKey("document_versions.version_id"), nullable=False)
    job_id = Column(Integer, ForeignKey("ingestion_jobs.job_id"), nullable=True)
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    token_count = Column(Integer, nullable=True)
    chunk_type = Column(String, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    sheet = relationship("DocumentSheet", back_populates="chunks")
    embeddings = relationship("Embedding", back_populates="chunk")


class Embedding(Base):
    __tablename__ = "embeddings"

    embedding_id = Column(Integer, primary_key=True)
    chunk_id = Column(Integer, ForeignKey("chunks.chunk_id"), nullable=False)
    version_id = Column(Integer, ForeignKey("document_versions.version_id"), nullable=False)
    job_id = Column(Integer, ForeignKey("ingestion_jobs.job_id"), nullable=True)
    milvus_collection = Column(String, nullable=False)
    milvus_vector_id = Column(String, nullable=False)
    embedding_model = Column(String, nullable=False)
    embedding_dimension = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    chunk = relationship("Chunk", back_populates="embeddings")


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    job_id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("source_documents.document_id"), nullable=False)
    version_id = Column(Integer, ForeignKey("document_versions.version_id"), nullable=True)
    job_type = Column(String, nullable=False, default="full_ingestion")
    status = Column(String, nullable=False, default="pending")
    triggered_by_fk = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    chunks_created = Column(Integer, default=0)
    embeddings_created = Column(Integer, default=0)
    config_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class DocumentPermission(Base):
    __tablename__ = "document_permissions"

    doc_permission_id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("source_documents.document_id"), nullable=False)
    principal_type = Column(String, nullable=False)  # USER or ROLE
    principal_id = Column(Integer, nullable=False)
    permission = Column(String, nullable=False)
    granted_by_fk = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    granted_at = Column(DateTime, server_default=func.now())
    revoked_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.kb_id"), nullable=True)
    title = Column(String, nullable=True)
    started_at = Column(DateTime, server_default=func.now())
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    message_id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.session_id"), nullable=False)
    role = Column(String, nullable=False)  # user / assistant / system
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    model_name = Column(String, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)

    session = relationship("ChatSession", back_populates="messages")


class RetrievalRequest(Base):
    __tablename__ = "retrieval_requests"

    retrieval_id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("chat_messages.message_id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=True)
    kb_id = Column(Integer, ForeignKey("knowledge_bases.kb_id"), nullable=True)
    query_text = Column(Text, nullable=False)
    top_k = Column(Integer, default=5)
    filters_json = Column(JSON, nullable=True)
    embedding_model = Column(String, nullable=True)
    milvus_collection = Column(String, nullable=True)
    retriever_config_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class RetrievalResult(Base):
    __tablename__ = "retrieval_results"

    retrieval_result_id = Column(Integer, primary_key=True)
    retrieval_id = Column(Integer, ForeignKey("retrieval_requests.retrieval_id"), nullable=False)
    chunk_id = Column(Integer, ForeignKey("chunks.chunk_id"), nullable=False)
    similarity_score = Column(Float, nullable=False)
    rank = Column(Integer, nullable=False)


class MessageFeedback(Base):
    __tablename__ = "message_feedback"

    feedback_id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("chat_messages.message_id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    rating = Column(Integer, nullable=True)
    feedback_text = Column(Text, nullable=True)
    is_incorrect = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


class InvitationToken(Base):
    __tablename__ = "invitation_tokens"

    invitation_token_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    token_hash = Column(String(64), nullable=False)
    purpose = Column(String, nullable=False, default="account_activation")
    delivery_status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)
    invalidated_at = Column(DateTime, nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_invitation_tokens_token_hash"),
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    password_reset_token_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False)
    delivery_status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)
    invalidated_at = Column(DateTime, nullable=True)

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )

class AuditLog(Base):
    __tablename__ = "audit_logs"

    audit_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    department_id = Column(Integer, ForeignKey("departments.department_id"), nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=True)
    method_json = Column(JSON, nullable=True)
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())