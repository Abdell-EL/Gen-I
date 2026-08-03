#!/usr/bin/env python3
"""Fail CI on tracked files that should never enter the repository."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

TEXT_EXTENSIONS = {
    ".env", ".example", ".ini", ".json", ".lock", ".md", ".py", ".sh",
    ".sql", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml",
}

JWT_RE = re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
PRIVATE_KEY_RE = re.compile(rb"-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")
TOKEN_ARTIFACT_RE = re.compile(r"(?:activation|reset)[_-]?(?:token|artifact|capture)", re.IGNORECASE)
TOKEN_ARTIFACT_SUFFIXES = {".json", ".txt", ".csv", ".log", ".ndjson"}

ALLOWED_ENV_EXAMPLES = {
    "backend/.env.example",
    "backend/frontend/.env.example",
}

DENY_PATH_PARTS = {
    "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules", "dist",
    ".venv", "venv", "env", ".env",
}
DENY_SUFFIXES = {
    ".pem", ".key", ".p12", ".pfx", ".crt", ".csr",
    ".sqlite", ".sqlite3", ".db", ".dump", ".dmp",
}
DENY_FILENAMES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return [item.decode() for item in result.stdout.split(b"\0") if item]


def _is_text_candidate(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    return path.name.startswith(".env")


def _scan_content(path: Path) -> list[str]:
    if not _is_text_candidate(path) or not path.is_file() or path.stat().st_size > 2_000_000:
        return []
    try:
        data = path.read_bytes()
    except OSError:
        return []
    findings: list[str] = []
    if JWT_RE.search(data):
        findings.append("jwt-like value")
    if PRIVATE_KEY_RE.search(data):
        findings.append("private key material")
    return findings


def _scan_path(path_text: str) -> list[str]:
    path = Path(path_text)
    parts = set(path.parts)
    findings: list[str] = []

    if path.name.startswith(".env") and path_text not in ALLOWED_ENV_EXAMPLES:
        findings.append("tracked env file")
    if path.suffix.lower() in DENY_SUFFIXES or path.name in DENY_FILENAMES:
        findings.append("tracked key/certificate/database artifact")
    if parts.intersection(DENY_PATH_PARTS):
        findings.append("tracked generated/local artifact")
    if path.suffix.lower() == ".sql":
        findings.append("tracked database dump or SQL artifact")
    if (
        TOKEN_ARTIFACT_RE.search(path_text)
        and path.suffix.lower() in TOKEN_ARTIFACT_SUFFIXES
        and "test" not in path_text.lower()
    ):
        findings.append("tracked token/reset artifact")
    if path_text.startswith("backend/frontend/dist/"):
        findings.append("tracked frontend dist")

    return findings


def main() -> int:
    failures: list[tuple[str, list[str]]] = []
    for item in _tracked_files():
        rules = _scan_path(item)
        rules.extend(_scan_content(Path(item)))
        if rules:
            failures.append((item, sorted(set(rules))))

    if failures:
        print("repository hygiene failed:", file=sys.stderr)
        for path, rules in failures:
            print(f"- {path}: {', '.join(rules)}", file=sys.stderr)
        return 1

    print("repository hygiene ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
