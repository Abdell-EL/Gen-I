import json
from pathlib import Path
from typing import Any

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

        return {
            "articles": len(articles),
            "chunks": len(self.chunks),
        }

    def keyword_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query_terms = query.lower().split()
        results = []

        for chunk in self.chunks:
            text = chunk.get("text", "").lower()
            score = sum(1 for term in query_terms if term in text)

            if score > 0:
                results.append({
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
                })

        results.sort(
            key=lambda item: (
                item["score"],
                item["priority"] == "critical",
                item["priority"] == "high",
            ),
            reverse=True,
        )

        return results[:limit]

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