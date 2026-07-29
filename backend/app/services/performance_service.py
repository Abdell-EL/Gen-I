from __future__ import annotations

import json
import logging
from typing import Any


logger = logging.getLogger("app.performance")
_DURATION_FIELDS = (
    "embedding_ms",
    "milvus_ms",
    "postgres_ms",
    "ollama_ms",
    "time_to_first_token_ms",
    "generation_ms",
    "audit_ms",
    "cache_lookup_ms",
    "total_ms",
)


def new_performance_record() -> dict[str, Any]:
    return {
        "cache_hit": False,
        "cache_status": "not_checked",
        "embedding_ms": 0.0,
        "milvus_ms": 0.0,
        "postgres_ms": 0.0,
        "ollama_ms": 0.0,
        "audit_ms": 0.0,
        "cache_lookup_ms": 0.0,
    }


def log_performance(event: str, request_id: str, values: dict[str, Any]) -> None:
    try:
        payload: dict[str, Any] = {
            "event": event,
            "request_id": request_id,
            "cache_hit": bool(values.get("cache_hit", False)),
            "cache_status": str(values.get("cache_status", "not_checked")),
        }
        for field in _DURATION_FIELDS:
            payload[field] = round(float(values.get(field, 0.0)), 2)
        for field in (
            "embedding_cache_status",
            "context_chunks_selected",
            "context_chunks_included",
            "context_chars",
        ):
            if field in values:
                payload[field] = values[field]
        logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    except Exception:
        # Instrumentation must never alter a successful application response.
        try:
            logger.warning("performance_log_failed")
        except Exception:
            pass
