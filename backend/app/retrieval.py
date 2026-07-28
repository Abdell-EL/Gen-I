import json
from pathlib import Path
import time
from typing import Any

from app.config import get_cache_settings
from app.services.cache_service import (
    delete_key,
    get_knowledge_generation,
    read_json,
    retrieval_cache_key,
    validate_retrieval_payload,
    write_json,
)


BASE_DIR = Path(__file__).resolve().parents[1]
CHUNKS_PATH = BASE_DIR / "data" / "processed" / "chunks.json"


class RetrievalService:
    def __init__(self):
        self.chunks = self._load_chunks()

    def _load_chunks(self) -> list[dict[str, Any]]:
        if not CHUNKS_PATH.exists():
            return []
        with open(CHUNKS_PATH, "r", encoding="utf-8") as file:
            return json.load(file)

    def get_stats(self) -> dict[str, int]:
        articles = {chunk.get("kb_code") for chunk in self.chunks}
        return {"articles": len(articles), "chunks": len(self.chunks)}

    def keyword_search(
        self,
        query: str,
        limit: int = 5,
        performance: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        settings = get_cache_settings()
        lookup_started = time.perf_counter()
        generation = get_knowledge_generation(settings)
        try:
            stat = CHUNKS_PATH.stat()
            collection_version = f"chunks.json:{stat.st_mtime_ns}:{stat.st_size}"
        except OSError:
            collection_version = "chunks.json:missing"
        key = retrieval_cache_key(
            settings,
            retrieval_mode="keyword",
            query=query,
            top_k=limit,
            filters={},
            collection_name=collection_version,
            embedding_model="none",
            retrieval_config={
                "algorithm": "term-substring-count",
                "priority_tiebreak": True,
            },
            knowledge_generation=generation,
        )
        cached = read_json(key, settings)
        if performance is not None:
            performance["cache_lookup_ms"] = (
                performance.get("cache_lookup_ms", 0.0)
                + (time.perf_counter() - lookup_started) * 1000
            )
            performance["cache_status"] = cached.status
            performance["cache_hit"] = False
        validated = validate_retrieval_payload(cached.value, limit)
        if validated is not None:
            if performance is not None:
                performance["cache_hit"] = True
                performance["cache_status"] = "hit"
            return validated
        if cached.value is not None:
            delete_key(key, settings)

        query_terms = query.lower().split()
        results = []
        for chunk in self.chunks:
            text = chunk.get("text", "").lower()
            score = sum(1 for term in query_terms if term in text)
            if score > 0:
                results.append(
                    {
                        "score": score,
                        "external_chunk_id": chunk.get("external_chunk_id"),
                        "kb_code": chunk.get("kb_code"),
                        "article_title": chunk.get("article_title"),
                        "file_name": chunk.get("file_name"),
                        "section_title": chunk.get("section_title"),
                        "section_type": chunk.get("section_type"),
                        "chunk_type": chunk.get("chunk_type"),
                        "priority": chunk.get("priority"),
                        "text": chunk.get("text"),
                        "metadata": chunk.get("metadata", {}),
                    }
                )
        results.sort(
            key=lambda item: (
                item["score"],
                item["priority"] == "critical",
                item["priority"] == "high",
            ),
            reverse=True,
        )
        ranked_results = results[:limit]
        for rank, item in enumerate(ranked_results, start=1):
            item["rank"] = rank
        stored = write_json(
            key,
            {"results": ranked_results},
            settings.search_ttl_seconds,
            settings,
        )
        if performance is not None:
            performance["_cache_key"] = key
            performance["_cache_settings"] = settings
            performance["_cache_written"] = stored
        return ranked_results

    def assemble_context(self, chunks: list[dict[str, Any]]) -> str:
        context_blocks = []
        for chunk in chunks:
            context_blocks.append(
                f"[{chunk.get('external_chunk_id')} | "
                f"{chunk.get('article_title')} | "
                f"{chunk.get('section_type')} | "
                f"{chunk.get('chunk_type')}]\n"
                f"{chunk.get('text')}"
            )
        return "\n\n---\n\n".join(context_blocks)
