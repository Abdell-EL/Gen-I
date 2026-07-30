from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260730_01_password_lifecycle.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location(
        "password_lifecycle_migration", MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PasswordLifecycleMigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        metadata = MetaData()
        Table(
            "users",
            metadata,
            Column("user_id", Integer, primary_key=True),
            Column("email", String, nullable=False),
        )
        metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            connection.execute(
                text("insert into users (user_id, email) values (1, 'existing@example.com')")
            )

    def tearDown(self):
        self.engine.dispose()

    def run_revision(self, method_name: str) -> None:
        module = load_migration()
        with self.engine.begin() as connection:
            context = MigrationContext.configure(connection)
            module.op = Operations(context)
            getattr(module, method_name)()

    def test_revision_metadata_and_required_operations_are_declared(self):
        module = load_migration()

        self.assertEqual(module.revision, "20260730_01")
        self.assertEqual(module.down_revision, "20260729_01")
        self.assertIsNone(module.branch_labels)
        self.assertIsNone(module.depends_on)
        self.assertTrue(callable(module.upgrade))
        self.assertTrue(callable(module.downgrade))
        source = MIGRATION_PATH.read_text()
        self.assertIn('batch_alter_table("users")', source)
        self.assertIn('server_default="0"', source)
        self.assertIn("server_default=None", source)
        self.assertIn("password_reset_tokens", source)
        self.assertIn("uq_password_reset_tokens_token_hash", source)
        self.assertIn("ix_password_reset_tokens_user_id", source)

    def test_upgrade_and_downgrade_lifecycle_on_disposable_sqlite(self):
        self.run_revision("upgrade")

        inspector = inspect(self.engine)
        user_columns = {column["name"]: column for column in inspector.get_columns("users")}
        self.assertIn("token_version", user_columns)
        self.assertFalse(user_columns["token_version"]["nullable"])
        reset_columns = {
            column["name"]: column
            for column in inspector.get_columns("password_reset_tokens")
        }
        self.assertEqual(
            set(reset_columns),
            {
                "password_reset_token_id",
                "user_id",
                "token_hash",
                "delivery_status",
                "created_at",
                "expires_at",
                "consumed_at",
                "invalidated_at",
            },
        )
        self.assertFalse(reset_columns["user_id"]["nullable"])
        self.assertFalse(reset_columns["token_hash"]["nullable"])
        self.assertFalse(reset_columns["expires_at"]["nullable"])
        self.assertIn(
            "ix_password_reset_tokens_user_id",
            {index["name"] for index in inspector.get_indexes("password_reset_tokens")},
        )
        self.assertIn(
            "uq_password_reset_tokens_token_hash",
            {constraint["name"] for constraint in inspector.get_unique_constraints("password_reset_tokens")},
        )
        with self.engine.begin() as connection:
            version = connection.execute(
                text("select token_version from users where user_id = 1")
            ).scalar_one()
            self.assertEqual(version, 0)
            connection.execute(text(
                "insert into password_reset_tokens "
                "(user_id, token_hash, expires_at) values "
                "(1, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', '2026-07-30 00:00:00')"
            ))
            with self.assertRaises(IntegrityError):
                connection.execute(text(
                    "insert into password_reset_tokens "
                    "(user_id, token_hash, expires_at) values "
                    "(1, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', '2026-07-31 00:00:00')"
                ))

        self.run_revision("downgrade")

        inspector = inspect(self.engine)
        self.assertNotIn("password_reset_tokens", inspector.get_table_names())
        self.assertNotIn(
            "token_version",
            {column["name"] for column in inspector.get_columns("users")},
        )


if __name__ == "__main__":
    unittest.main()
