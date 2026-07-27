from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, EmailStr


class DepartmentCreate(BaseModel):
    name: str
    code: str


class DepartmentRead(DepartmentCreate):
    department_id: int

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    department_id: Optional[int] = None
    role: Optional[str] = None


class UserRead(UserCreate):
    user_id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class KnowledgeBaseCreate(BaseModel):
    department_id: int
    name: str
    description: Optional[str] = None
    version: Optional[str] = None
    status: str = "active"


class KnowledgeBaseRead(KnowledgeBaseCreate):
    kb_id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SourceDocumentCreate(BaseModel):
    kb_id: int
    department_id: int
    file_name: str
    file_type: str
    source_path: Optional[str] = None
    checksum: Optional[str] = None


class SourceDocumentRead(SourceDocumentCreate):
    document_id: int
    processing_status: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DocumentVersionCreate(BaseModel):
    document_id: int
    version_number: int
    uploaded_by: Optional[int] = None
    checksum: Optional[str] = None
    storage_path: Optional[str] = None
    file_size_bytes: Optional[int] = None
    change_notes: Optional[str] = None


class DocumentVersionRead(DocumentVersionCreate):
    version_id: int
    processing_status: str
    is_current: bool
    uploaded_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChunkCreate(BaseModel):
    sheet_id: int
    version_id: int
    job_id: Optional[int] = None
    chunk_text: str
    chunk_index: int
    token_count: Optional[int] = None
    chunk_type: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None


class ChunkRead(ChunkCreate):
    chunk_id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChatSessionCreate(BaseModel):
    user_id: int
    department_id: Optional[int] = None
    kb_id: Optional[int] = None
    title: Optional[str] = None


class ChatMessageCreate(BaseModel):
    session_id: int
    role: str
    content: str
    model_name: Optional[str] = None


class ChatRequest(BaseModel):
    user_id: int
    session_id: Optional[int] = None
    department_id: Optional[int] = None
    kb_id: Optional[int] = None
    question: str
    top_k: int = 5


class RetrievedChunk(BaseModel):
    chunk_id: int
    chunk_text: str
    similarity_score: float
    rank: int
    metadata_json: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    answer: str
    session_id: int
    message_id: int
    retrieved_chunks: List[RetrievedChunk]


class FeedbackCreate(BaseModel):
    message_id: int
    user_id: int
    rating: Optional[int] = None
    feedback_text: Optional[str] = None
    is_incorrect: bool = False


class PermissionCreate(BaseModel):
    principal_type: str
    principal_id: int
    permission: str
    granted_by_fk: Optional[int] = None
    expires_at: Optional[datetime] = None


class KBPermissionCreate(PermissionCreate):
    kb_id: int


class DocumentPermissionCreate(PermissionCreate):
    document_id: int
