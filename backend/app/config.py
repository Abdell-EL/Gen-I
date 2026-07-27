import os

from dotenv import load_dotenv
from sqlalchemy import URL

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    DATABASE_URL = URL.create(
        drivername="postgresql+psycopg2",
        username=os.getenv("POSTGRES_USER", "kb_user"),
        password=os.getenv("POSTGRES_PASSWORD", "kb_password"),
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.getenv("POSTGRES_PORT", "15432")),
        database=os.getenv("POSTGRES_DB", "sogetrel_kb"),
    )

MILVUS_HOST = os.getenv("MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
MILVUS_COLLECTION = os.getenv(
    "MILVUS_COLLECTION",
    "sogetrel_chunks",
)