from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import math
import secrets
import threading
import time
from typing import Any

from app.config import CacheSettings, get_cache_settings

try:
    import redis
except ImportError:  # Cache remains optional and fails open.
    redis = None


logger = logging.getLogger(__name__)
_client: Any | None = None
_client_lock = threading.Lock()


@dataclass(frozen=True)
class CacheRead:
    value: Any | None
    status: str
    lookup_ms: float


def normalize_query(query: str) -> str:
    return " ".join(query.strip().lower().split())


def query_hash(query: str) -> str:
    return hashlib.sha256(normalize_query(query).encode("utf-8")).hexdigest()


def _component_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def embedding_cache_key(settings: CacheSettings, model: str, query: str) -> str:
    return ":".join(
        (
            settings.namespace,
            settings.version,
            "embedding",
            _component_hash(model),
            query_hash(query),
        )
    )


def retrieval_cache_key(
    settings: CacheSettings,
    *,
    retrieval_mode: str,
    query: str,
    top_k: int,
    filters: dict[str, Any] | None,
    collection_name: str,
    embedding_model: str,
    retrieval_config: dict[str, Any],
    knowledge_generation: int,
) -> str:
    inputs = {
        "retrieval_mode": retrieval_mode,
        "query_hash": query_hash(query),
        "top_k": top_k,
        "filters": filters or {},
        "collection_name": collection_name,
        "embedding_model": embedding_model,
        "retrieval_config": retrieval_config,
        "knowledge_generation": knowledge_generation,
    }
    digest = hashlib.sha256(
        json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"{settings.namespace}:{settings.version}:retrieval:{digest}"


def _get_client(settings: CacheSettings | None = None):
    global _client
    settings = settings or get_cache_settings()
    if not settings.enabled:
        return None
    if _client is not None:
        return _client
    if redis is None:
        return None
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = redis.Redis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=0.25,
                    socket_timeout=0.5,
                    health_check_interval=30,
                )
    return _client


def close_cache_client() -> None:
    global _client
    with _client_lock:
        client, _client = _client, None
    if client is None:
        return
    try:
        client.close()
    except Exception:
        logger.warning("cache_client_close_failed", exc_info=True)


def read_json(key: str, settings: CacheSettings | None = None) -> CacheRead:
    settings = settings or get_cache_settings()
    started = time.perf_counter()
    if not settings.enabled:
        return CacheRead(None, "disabled", (time.perf_counter() - started) * 1000)
    client = _get_client(settings)
    if client is None:
        return CacheRead(None, "unavailable", (time.perf_counter() - started) * 1000)
    try:
        raw = client.get(key)
        if raw is None:
            return CacheRead(None, "miss", (time.perf_counter() - started) * 1000)
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            try:
                client.delete(key)
            except Exception:
                pass
            return CacheRead(None, "corrupt", (time.perf_counter() - started) * 1000)
        return CacheRead(value, "hit", (time.perf_counter() - started) * 1000)
    except Exception:
        logger.warning("cache_read_failed", extra={"cache_operation": "get"})
        return CacheRead(None, "unavailable", (time.perf_counter() - started) * 1000)


def write_json(
    key: str,
    value: Any,
    ttl_seconds: int,
    settings: CacheSettings | None = None,
) -> bool:
    settings = settings or get_cache_settings()
    if not settings.enabled:
        return False
    client = _get_client(settings)
    if client is None:
        return False
    try:
        client.set(key, json.dumps(value, separators=(",", ":")), ex=ttl_seconds)
        return True
    except Exception:
        logger.warning("cache_write_failed", extra={"cache_operation": "set"})
        return False


def delete_key(key: str, settings: CacheSettings | None = None) -> None:
    client = _get_client(settings)
    if client is None:
        return
    try:
        client.delete(key)
    except Exception:
        logger.warning("cache_delete_failed", extra={"cache_operation": "delete"})


def validate_embedding(value: Any, expected_dimension: int) -> list[float] | None:
    if not isinstance(value, dict) or value.get("dimension") != expected_dimension:
        return None
    vector = value.get("vector")
    if not isinstance(vector, list) or len(vector) != expected_dimension:
        return None
    if any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(float(item))
        for item in vector
    ):
        return None
    return [float(item) for item in vector]


def validate_retrieval_payload(value: Any, top_k: int) -> list[dict[str, Any]] | None:
    if not isinstance(value, dict) or not isinstance(value.get("results"), list):
        return None
    results = value["results"]
    if len(results) > top_k:
        return None
    validated: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            return None
        rank = item.get("rank")
        score = item.get("score")
        external_id = item.get("id") or item.get("external_chunk_id")
        if (
            isinstance(rank, bool)
            or not isinstance(rank, int)
            or rank < 1
            or isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
            or not isinstance(external_id, str)
            or not external_id
        ):
            return None
        validated.append(dict(item))
    return validated


def knowledge_generation_key(settings: CacheSettings) -> str:
    return f"{settings.namespace}:{settings.version}:knowledge-generation"


def get_knowledge_generation(settings: CacheSettings | None = None) -> int:
    settings = settings or get_cache_settings()
    if not settings.enabled:
        return 0
    client = _get_client(settings)
    if client is None:
        return 0
    try:
        value = client.get(knowledge_generation_key(settings))
        generation = int(value) if value is not None else 0
        return max(0, generation)
    except Exception:
        logger.warning("cache_generation_read_failed")
        return 0


def advance_knowledge_generation(settings: CacheSettings | None = None) -> int | None:
    settings = settings or get_cache_settings()
    if not settings.enabled:
        return None
    client = _get_client(settings)
    if client is None:
        return None
    try:
        return int(client.incr(knowledge_generation_key(settings)))
    except Exception:
        logger.warning("cache_generation_advance_failed")
        return None


def acquire_lock(
    key: str,
    expiry_seconds: int = 5,
    settings: CacheSettings | None = None,
) -> str | None:
    client = _get_client(settings)
    if client is None:
        return None
    token = secrets.token_hex(16)
    try:
        if client.set(f"{key}:lock", token, nx=True, ex=expiry_seconds):
            return token
    except Exception:
        logger.warning("cache_lock_failed")
    return None


def release_lock(
    key: str,
    token: str | None,
    settings: CacheSettings | None = None,
) -> None:
    if token is None:
        return
    client = _get_client(settings)
    if client is None:
        return
    script = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('del', KEYS[1])
    end
    return 0
    """
    try:
        client.eval(script, 1, f"{key}:lock", token)
    except Exception:
        logger.warning("cache_lock_release_failed")


def bounded_wait_for_json(
    key: str,
    wait_seconds: float = 0.15,
    settings: CacheSettings | None = None,
) -> CacheRead:
    started = time.perf_counter()
    deadline = started + max(0.0, min(wait_seconds, 0.5))
    last = CacheRead(None, "miss", 0.0)
    while time.perf_counter() < deadline:
        time.sleep(0.01)
        last = read_json(key, settings)
        if last.value is not None or last.status in {"disabled", "unavailable"}:
            break
    return CacheRead(last.value, last.status, (time.perf_counter() - started) * 1000)


def get_cache_status() -> dict[str, Any]:
    settings = get_cache_settings()
    connected = False
    generation = None
    if settings.enabled:
        client = _get_client(settings)
        if client is not None:
            try:
                connected = bool(client.ping())
                generation = get_knowledge_generation(settings) if connected else None
            except Exception:
                connected = False
    return {
        "enabled": settings.enabled,
        "connected": connected,
        "namespace": settings.namespace,
        "version": settings.version,
        "knowledge_generation": generation,
    }


def discard_new_retrieval_cache(performance: dict[str, Any]) -> None:
    if performance.get("_cache_written") and performance.get("_cache_key"):
        delete_key(
            str(performance["_cache_key"]),
            performance.get("_cache_settings"),
        )
        performance["_cache_written"] = False
