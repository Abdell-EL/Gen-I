from __future__ import annotations

import argparse
import os

from app.database import SessionLocal
from app.models import User
from app.security import PasswordTooLongError, hash_password
from app.services.auth_service import find_user_by_email, normalize_email


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or deliberately update one admin user.")
    parser.add_argument("--email", default=os.getenv("AUTH_BOOTSTRAP_ADMIN_EMAIL"))
    parser.add_argument("--full-name", default=os.getenv("AUTH_BOOTSTRAP_ADMIN_FULL_NAME"))
    parser.add_argument("--password", default=os.getenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD"))
    parser.add_argument("--update-existing", action="store_true")
    return parser


def require_value(parser: argparse.ArgumentParser, value: str | None, name: str) -> str:
    if value is None or not value.strip():
        parser.error(f"{name} is required and cannot be empty.")
    return value


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    email = require_value(parser, args.email, "email")
    full_name = require_value(parser, args.full_name, "full name").strip()
    password = require_value(parser, args.password, "password")

    normalized_email = normalize_email(email)
    if not normalized_email:
        parser.error("email is required and cannot be empty.")

    try:
        password_hash = hash_password(password)
    except PasswordTooLongError as error:
        parser.error(str(error))

    db = SessionLocal()
    try:
        user = find_user_by_email(db, normalized_email)
        if user is None:
            user = User(
                full_name=full_name,
                email=normalized_email,
                password_hash=password_hash,
                role="admin",
                is_active=True,
            )
            db.add(user)
            action = "created"
        else:
            if not args.update_existing:
                parser.error("User already exists; pass --update-existing to update it.")
            user.full_name = full_name
            user.password_hash = password_hash
            user.role = "admin"
            user.is_active = True
            db.add(user)
            action = "updated"

        db.commit()
        print(f"Admin user {action}: {normalized_email}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
