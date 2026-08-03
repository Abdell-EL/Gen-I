#!/usr/bin/env python3
"""Verify the disposable PostgreSQL integration schema after Alembic upgrade."""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

DATABASE_URL_ENV = "POSTGRES_INTEGRATION_DATABASE_URL"
LIVE_DATABASE_NAMES = frozenset({"labia", "sogetrel_kb"})
REQUIRED_TABLES = {"users", "audit_logs", "invitation_tokens", "password_reset_tokens", "alembic_version"}
REQUIRED_USER_COLUMNS = {"activation_status", "token_version", "password_hash", "email", "role"}
REQUIRED_INDEXES = {"ix_invitation_tokens_user_id", "ix_password_reset_tokens_user_id"}


def _database_url() -> str:
    value = os.getenv(DATABASE_URL_ENV, "").strip() or os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError(f"{DATABASE_URL_ENV} or DATABASE_URL is required.")
    url = make_url(value)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("PostgreSQL schema verification requires a PostgreSQL URL.")
    if url.database in LIVE_DATABASE_NAMES:
        raise RuntimeError(f"Refusing known live database {url.database!r}.")
    if not url.database or "ci" not in url.database.lower():
        raise RuntimeError("Disposable CI database name must contain 'ci'.")
    return value


def main() -> int:
    engine = create_engine(_database_url(), pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names(schema="public"))
        missing_tables = sorted(REQUIRED_TABLES - tables)
        if missing_tables:
            raise RuntimeError(f"missing tables: {', '.join(missing_tables)}")

        user_columns = {column["name"] for column in inspector.get_columns("users")}
        missing_columns = sorted(REQUIRED_USER_COLUMNS - user_columns)
        if missing_columns:
            raise RuntimeError(f"missing users columns: {', '.join(missing_columns)}")

        indexes = {
            index["name"]
            for table in ("invitation_tokens", "password_reset_tokens")
            for index in inspector.get_indexes(table)
        }
        missing_indexes = sorted(REQUIRED_INDEXES - indexes)
        if missing_indexes:
            raise RuntimeError(f"missing indexes: {', '.join(missing_indexes)}")

        with engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            counts = {
                "users": connection.execute(text("SELECT count(*) FROM users")).scalar_one(),
                "audit_logs": connection.execute(text("SELECT count(*) FROM audit_logs")).scalar_one(),
                "invitation_tokens": connection.execute(text("SELECT count(*) FROM invitation_tokens")).scalar_one(),
                "password_reset_tokens": connection.execute(text("SELECT count(*) FROM password_reset_tokens")).scalar_one(),
            }
        if any(counts.values()):
            raise RuntimeError("schema verification found product/test rows before integration tests")
        print(f"postgres schema ok: alembic_version={version} rows=0")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"postgres schema verification failed: {error}", file=sys.stderr)
        raise SystemExit(1)
