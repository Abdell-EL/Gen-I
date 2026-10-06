from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    # Defense-in-depth alongside the auth-dependency fix above: raises the
    # ceiling before concurrent long-running requests can exhaust the
    # default pool_size=5/max_overflow=10 (15 total) and start blocking
    # unrelated requests for up to pool_timeout.
    pool_size=20,
    max_overflow=20,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()