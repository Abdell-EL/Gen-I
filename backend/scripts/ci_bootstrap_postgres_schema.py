#!/usr/bin/env python3
"""Create the minimal legacy PostgreSQL schema required before Alembic CI tests.

The production database was adopted after base tables already existed, so the
current Alembic chain starts by altering `users` and creating lifecycle token
tables. This helper is intentionally CI-only: it creates schema objects only,
in a guarded disposable PostgreSQL database, and inserts no product data.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

DATABASE_URL_ENV = "POSTGRES_INTEGRATION_DATABASE_URL"
LIVE_DATABASE_NAMES = frozenset({"labia", "sogetrel_kb"})
EXPECTED_EMPTY_OR_META_TABLES = frozenset({"alembic_version"})


def _database_url() -> str:
    value = os.getenv(DATABASE_URL_ENV, "").strip() or os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError(f"{DATABASE_URL_ENV} or DATABASE_URL is required.")

    url = make_url(value)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("CI bootstrap requires a PostgreSQL URL.")
    if url.database in LIVE_DATABASE_NAMES:
        raise RuntimeError(f"Refusing to bootstrap known live database {url.database!r}.")
    if not url.database or "ci" not in url.database.lower():
        raise RuntimeError("Disposable CI database name must contain 'ci'.")
    return value


def _assert_no_product_tables(engine) -> None:
    existing = set(inspect(engine).get_table_names(schema="public"))
    unexpected = sorted(existing - EXPECTED_EMPTY_OR_META_TABLES)
    if unexpected:
        joined = ", ".join(unexpected)
        raise RuntimeError(
            "Refusing to bootstrap non-empty schema. Existing application tables: "
            f"{joined}"
        )


def _create_legacy_schema(engine) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS departments (
            department_id SERIAL PRIMARY KEY,
            name VARCHAR NOT NULL,
            code VARCHAR NOT NULL UNIQUE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            department_id INTEGER REFERENCES departments(department_id),
            full_name VARCHAR NOT NULL,
            email VARCHAR NOT NULL UNIQUE,
            password_hash VARCHAR,
            role VARCHAR NOT NULL DEFAULT 'agent',
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_users_user_id ON users(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_users_email ON users(email)",
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            audit_id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(user_id),
            department_id INTEGER REFERENCES departments(department_id),
            action VARCHAR NOT NULL,
            entity_type VARCHAR NOT NULL,
            entity_id INTEGER,
            method_json JSONB,
            ip_address VARCHAR,
            created_at TIMESTAMP DEFAULT now()
        )
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _assert_no_rows(engine) -> None:
    with engine.connect() as connection:
        counts = {
            "departments": connection.execute(text("SELECT count(*) FROM departments")).scalar_one(),
            "users": connection.execute(text("SELECT count(*) FROM users")).scalar_one(),
            "audit_logs": connection.execute(text("SELECT count(*) FROM audit_logs")).scalar_one(),
        }
    if any(counts.values()):
        raise RuntimeError("CI bootstrap created or found product rows, refusing to continue.")
    print("ci bootstrap schema-only ok: departments=0 users=0 audit_logs=0")


def main() -> int:
    engine = create_engine(_database_url(), pool_pre_ping=True)
    try:
        if engine.dialect.name != "postgresql":
            raise RuntimeError("CI bootstrap requires PostgreSQL dialect.")
        _assert_no_product_tables(engine)
        _create_legacy_schema(engine)
        _assert_no_rows(engine)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ci bootstrap failed: {error}", file=sys.stderr)
        raise SystemExit(1)
