#!/usr/bin/env python3
"""Validate the repository Trivy ignore policy stays narrowly scoped and expires."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_POLICY_PATH = Path(".trivyignore.yaml")
ALLOWED_ID = "GHSA-qwww-vcr4-c8h2"
ALLOWED_PURLS = {
    "pkg:npm/react-router@7.18.2",
    "pkg:npm/react-router-dom@7.18.2",
}
EXPIRY = dt.date(2026, 8, 17)
REQUIRED_STATEMENT_PARTS = (
    "project maintainer",
    "client-rendered Vite SPA",
    "does not use React Server Components",
    "React Router 8.3.0+",
)
FORBIDDEN_IDS = {"CVE-2026-54283", "GHSA-82w8-qh3p-5jfq"}


def _today() -> dt.date:
    value = os.getenv("TRIVY_POLICY_TODAY", "").strip()
    if value:
        return dt.date.fromisoformat(value)
    return dt.date.today()


def _load_policy() -> dict[str, Any]:
    try:
        policy_path = Path(os.getenv("TRIVY_POLICY_PATH", str(DEFAULT_POLICY_PATH)))
        data = json.loads(policy_path.read_text())
    except FileNotFoundError as error:
        raise RuntimeError(f"missing Trivy policy: {policy_path}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Trivy policy must remain JSON-compatible YAML: {error}") from error
    if not isinstance(data, dict):
        raise RuntimeError("Trivy policy must be a mapping")
    return data


def _as_date(value: Any) -> dt.date:
    if not isinstance(value, str):
        raise RuntimeError(f"invalid expired_at value: {value!r}")
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    if "T" in value:
        return dt.datetime.fromisoformat(value).date()
    return dt.date.fromisoformat(value)


def main() -> int:
    try:
        policy = _load_policy()
        vulnerabilities = policy.get("vulnerabilities")
        if not isinstance(vulnerabilities, list) or len(vulnerabilities) != 1:
            raise RuntimeError("Trivy policy must contain exactly one vulnerability exception")
        item = vulnerabilities[0]
        if not isinstance(item, dict):
            raise RuntimeError("Trivy vulnerability exception must be a mapping")

        finding_id = item.get("id")
        if finding_id in FORBIDDEN_IDS:
            raise RuntimeError(f"Starlette advisory must not be ignored: {finding_id}")
        if finding_id != ALLOWED_ID:
            raise RuntimeError(f"unexpected Trivy exception id: {finding_id!r}")

        purls = set(item.get("purls") or [])
        if purls != ALLOWED_PURLS:
            raise RuntimeError(f"Trivy exception purls are not the exact allowlist: {sorted(purls)}")

        expired_at = _as_date(item.get("expired_at"))
        if expired_at != EXPIRY:
            raise RuntimeError(f"unexpected Trivy exception expiry: {expired_at.isoformat()}")
        if _today() > expired_at:
            raise RuntimeError(f"Trivy exception {ALLOWED_ID} expired on {expired_at.isoformat()}")

        statement = str(item.get("statement", ""))
        missing = [part for part in REQUIRED_STATEMENT_PARTS if part not in statement]
        if missing:
            raise RuntimeError(f"Trivy exception statement missing: {', '.join(missing)}")

    except Exception as error:
        print(f"Trivy policy validation failed: {error}", file=sys.stderr)
        return 1

    print(f"Trivy policy ok: {ALLOWED_ID} accepted until {EXPIRY.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
