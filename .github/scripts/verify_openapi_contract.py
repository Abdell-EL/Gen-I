#!/usr/bin/env python3
"""Verify that critical API routes remain present in the generated OpenAPI schema."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPOSITORY_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app

CRITICAL_PATHS = {
    "/api/v1/auth/signin",
    "/api/v1/auth/activation/validate",
    "/api/v1/auth/activation/complete",
    "/api/v1/auth/password/change",
    "/api/v1/auth/password/forgot",
    "/api/v1/auth/password/reset/validate",
    "/api/v1/auth/password/reset/complete",
    "/api/v1/chat",
    "/api/v1/chat/stream",
    "/api/v1/knowledge/documents/{source_document_id}/original",
    "/api/v1/knowledge/articles/{source_document_id}",
    "/api/v1/admin/knowledge/documents/{source_document_id}/versions",
    "/api/v1/chat/messages/{message_id}/feedback",
    "/api/v1/admin/analytics/feedback/summary",
    "/api/v1/admin/analytics/feedback",
    "/api/v1/admin/analytics/knowledge/articles",
    "/api/v1/admin/analytics/knowledge/trending-questions",
    "/api/v1/admin/analytics/knowledge/low-confidence",
    "/api/v1/admin/analytics/knowledge/score-distribution",
    "/api/v1/admin/analytics/knowledge/unreferenced-content",
}


def main() -> int:
    schema = app.openapi()
    paths = set(schema.get("paths", {}))
    missing = sorted(CRITICAL_PATHS - paths)
    if missing:
        print("missing critical OpenAPI paths:")
        for path in missing:
            print(f"- {path}")
        return 1
    print(f"openapi critical route inventory ok: {len(CRITICAL_PATHS)} routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
