from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from scripts.create_admin_user import main


class CreateAdminUserScriptTests(unittest.TestCase):
    def test_update_existing_admin_password_increments_token_version(self):
        db = MagicMock()
        user = SimpleNamespace(
            full_name="Old Admin",
            password_hash="old-hash",
            role="agent",
            is_active=False,
            activation_status="pending",
            token_version=7,
        )

        with (
            patch("scripts.create_admin_user.SessionLocal", return_value=db),
            patch("scripts.create_admin_user.find_user_by_email", return_value=user),
            patch("scripts.create_admin_user.hash_password", return_value="new-hash"),
            patch("sys.argv", [
                "create_admin_user.py",
                "--email", " Admin@Example.COM ",
                "--full-name", "Updated Admin",
                "--password", "new-secret",
                "--update-existing",
            ]),
        ):
            main()

        self.assertEqual(user.full_name, "Updated Admin")
        self.assertEqual(user.password_hash, "new-hash")
        self.assertEqual(user.token_version, 8)
        self.assertEqual(user.role, "admin")
        self.assertTrue(user.is_active)
        self.assertEqual(user.activation_status, "active")
        db.add.assert_called_once_with(user)
        db.commit.assert_called_once_with()
        db.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
