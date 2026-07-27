"""
Embedding pipeline for the Sogetrel Knowledge Platform.

This version is aligned with the current chunk.py output schema.

Expected chunk fields from data/processed/chunks.json:
- external_chunk_id
- kb_code
- article_title
- file_name
- section_title
- section_type
- chunk_type
- priority
- text
- word_count
- metadata

Main responsibilities:
1. Load validated chunks from JSON.
2. Build section-aware embedding text.
3. Generate multilingual embeddings with sentence-transformers.
4. Persist embeddings to JSONL for audit/debugging.
5. Optionally index embeddings into Milvus when --write-milvus is used.

Important:
- You do NOT need Docker/Milvus just to generate embeddings.jsonl.
- You only need Milvus running if you pass --write-milvus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("embedding_pipeline")


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class EmbeddingConfig:
    model_name: str = os.getenv(
        "EMBEDDING_MODEL",
        "BAAI/bge-m3",
    )
    input_path: Path = Path(
        os.getenv("CHUNKS_PATH", "data/processed/chunks.json")
    )
    output_path: Path = Path(
        os.getenv("EMBEDDINGS_PATH", "data/processed/embeddings.jsonl")
    )
    batch_size: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "16"))
    normalize_embeddings: bool = (
        os.getenv("NORMALIZE_EMBEDDINGS", "true").lower() == "true"
    )
    device: str | None = os.getenv("EMBEDDING_DEVICE") or None
    max_retries: int = int(os.getenv("EMBEDDING_MAX_RETRIES", "3"))
    retry_sleep_seconds: float = float(os.getenv("EMBEDDING_RETRY_SLEEP", "2"))


@dataclass(frozen=True)
class MilvusConfig:
    uri: str | None = os.getenv("MILVUS_URI")
    token: str | None = os.getenv("MILVUS_TOKEN")
    collection_name: str = os.getenv("MILVUS_COLLECTION", "fde_knowledge_chunks")
    metric_type: str = os.getenv("MILVUS_METRIC_TYPE", "COSINE")


REQUIRED_CHUNK_FIELDS = {
    "external_chunk_id",
    "kb_code",
    "article_title",
    "file_name",
    "section_title",
    "section_type",
    "chunk_type",
    "priority",
    "text",
    "word_count",
}

PRIORITY_WEIGHT = {
    "critical": 1.30,
    "high": 1.15,
    "medium": 1.00,
    "low": 0.90,
}


# -----------------------------------------------------------------------------
# Utility functions
# -----------------------------------------------------------------------------

def batched(items: list[dict[str, Any]], batch_size: int) -> Iterator[list[dict[str, Any]]]:
    for index in range(0, len(items), batch_size):
        yield items[index:index + batch_size]


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_chunks(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Chunks file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        chunks = json.load(file)

    if not isinstance(chunks, list):
        raise ValueError("Chunks file must contain a JSON list of chunk objects.")

    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for idx, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, dict):
            raise ValueError(f"Chunk #{idx} is not a JSON object.")

        missing = REQUIRED_CHUNK_FIELDS - set(chunk.keys())
        if missing:
            raise ValueError(
                f"Chunk #{idx} is missing required fields: {sorted(missing)}"
            )

        external_chunk_id = str(chunk["external_chunk_id"]).strip()
        kb_code = str(chunk["kb_code"]).strip()
        text = str(chunk["text"]).strip()

        if not external_chunk_id:
            raise ValueError(f"Chunk #{idx} has an empty external_chunk_id.")

        if external_chunk_id in seen_ids:
            raise ValueError(f"Duplicate external_chunk_id detected: {external_chunk_id}")

        if not kb_code:
            raise ValueError(f"Chunk #{idx} has an empty kb_code.")

        if not text:
            logger.warning("Skipping empty chunk: %s", external_chunk_id)
            continue

        # Normalize key types so later code is stable.
        chunk["external_chunk_id"] = external_chunk_id
        chunk["kb_code"] = kb_code
        chunk["text"] = text

        seen_ids.add(external_chunk_id)
        validated.append(chunk)

    logger.info("Loaded %s valid chunks from %s", len(validated), path)
    return validated


def build_embedding_text(chunk: dict[str, Any]) -> str:
    """
    Build the text sent to the embedding model.

    We do not embed only raw text. We prepend compact structural context because
    the same sentence can have different business meaning depending on whether
    it appears in rules, FAQ, procedure, key points, etc.
    """
    return "\n".join(
        [
            "Domaine: FDE",
            f"Article: {chunk['kb_code']} - {chunk['article_title']}",
            f"Fichier source: {chunk['file_name']}",
            f"Section: {chunk['section_title']}",
            f"Type de section: {chunk['section_type']}",
            f"Type de fragment: {chunk['chunk_type']}",
            f"Priorité: {chunk['priority']}",
            "Contenu:",
            str(chunk["text"]).strip(),
        ]
    )


def build_metadata(
    chunk: dict[str, Any],
    embedding_text_hash: str,
    model_name: str,
) -> dict[str, Any]:
    """
    Return metadata safe to store in PostgreSQL, JSONL, or Milvus dynamic fields.
    """
    priority = str(chunk.get("priority", "medium"))

    metadata = {
        "external_chunk_id": str(chunk["external_chunk_id"]),
        "kb_code": str(chunk["kb_code"]),
        "article_title": str(chunk["article_title"]),
        "file_name": str(chunk["file_name"]),
        "section_title": str(chunk["section_title"]),
        "section_type": str(chunk["section_type"]),
        "chunk_type": str(chunk["chunk_type"]),
        "priority": priority,
        "priority_weight": PRIORITY_WEIGHT.get(priority, 1.0),
        "word_count": int(chunk.get("word_count", 0)),
        "embedding_model": model_name,
        "embedding_text_hash": embedding_text_hash,
        "indexed_at_unix": int(time.time()),
    }

    # Keep original chunk metadata nested in JSONL for audit/debugging.
    # For Milvus, this nested object is not expanded into scalar fields.
    original_metadata = chunk.get("metadata")
    if isinstance(original_metadata, dict):
        metadata["chunk_metadata"] = original_metadata

    return metadata


# -----------------------------------------------------------------------------
# Embedding model wrapper
# -----------------------------------------------------------------------------

class EmbeddingModel:
    """Thin wrapper around sentence-transformers with retries and normalization."""

    def __init__(self, config: EmbeddingConfig) -> None:
        self.config = config

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "Missing dependency: sentence-transformers. Install with: "
                "pip install sentence-transformers"
            ) from exc

        logger.info("Loading embedding model: %s", config.model_name)

        kwargs: dict[str, Any] = {}
        if config.device:
            kwargs["device"] = config.device

        self.model = SentenceTransformer(config.model_name, **kwargs)
        self.dimension = int(self.model.get_sentence_embedding_dimension())

        logger.info("Embedding dimension: %s", self.dimension)

    def encode(self, texts: list[str]) -> list[list[float]]:
        last_error: Exception | None = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                vectors = self.model.encode(
                    texts,
                    batch_size=self.config.batch_size,
                    normalize_embeddings=self.config.normalize_embeddings,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
                return vectors.astype("float32").tolist()

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Embedding attempt %s/%s failed: %s",
                    attempt,
                    self.config.max_retries,
                    exc,
                )
                time.sleep(self.config.retry_sleep_seconds * attempt)

        raise RuntimeError("Embedding generation failed after retries.") from last_error


# -----------------------------------------------------------------------------
# Embedding artifact generation
# -----------------------------------------------------------------------------

def embed_chunks(
    chunks: list[dict[str, Any]],
    model: EmbeddingModel,
    output_path: Path,
) -> list[dict[str, Any]]:
    """
    Generate embeddings and persist them as JSONL.

    JSONL is used because it is stream-friendly, inspectable, and recoverable.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    embedded_records: list[dict[str, Any]] = []
    total = len(chunks)
    written = 0

    with output_path.open("w", encoding="utf-8") as file:
        for batch_number, batch in enumerate(
            batched(chunks, model.config.batch_size),
            start=1,
        ):
            embedding_texts = [build_embedding_text(chunk) for chunk in batch]
            vectors = model.encode(embedding_texts)

            for chunk, embedding_text, vector in zip(batch, embedding_texts, vectors, strict=True):
                text_hash = stable_hash(embedding_text)

                metadata = build_metadata(
                    chunk=chunk,
                    embedding_text_hash=text_hash,
                    model_name=model.config.model_name,
                )

                record = {
                    "id": str(chunk["external_chunk_id"]),
                    "text": str(chunk["text"]).strip(),
                    "embedding_text": embedding_text,
                    "embedding": vector,
                    "metadata": metadata,
                }

                file.write(json.dumps(record, ensure_ascii=False) + "\n")
                embedded_records.append(record)
                written += 1

            logger.info("Embedded batch %s | %s/%s records", batch_number, written, total)

    logger.info("Saved embeddings to %s", output_path)
    return embedded_records


def load_embedding_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Embedding JSONL file not found: {path}")

    records: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {line_number}: {exc}") from exc

    return records


# -----------------------------------------------------------------------------
# Optional Milvus indexing
# -----------------------------------------------------------------------------

def index_to_milvus(records: list[dict[str, Any]], config: MilvusConfig, dimension: int) -> None:
    """
    Index embeddings into Milvus.

    Only runs when --write-milvus is passed and a Milvus URI is provided.
    """
    if not config.uri:
        logger.info("Milvus URI not provided. Skipping Milvus indexing.")
        return

    try:
        from pymilvus import MilvusClient
    except ImportError as exc:
        raise ImportError("Missing dependency: pymilvus. Install with: pip install pymilvus") from exc

    logger.info("Connecting to Milvus: %s", config.uri)

    client = MilvusClient(uri=config.uri, token=config.token)

    existing = client.list_collections()

    if config.collection_name not in existing:
        logger.info("Creating Milvus collection: %s", config.collection_name)
        client.create_collection(
            collection_name=config.collection_name,
            dimension=dimension,
            metric_type=config.metric_type,
            auto_id=False,
            id_type="string",
            max_length=256,
        )

    rows: list[dict[str, Any]] = []

    for record in records:
        metadata = record["metadata"]

        # Milvus Lite / MilvusClient simple schema expects scalar fields.
        # Do not unpack nested chunk_metadata into top-level scalar fields.
        row = {
            "id": record["id"],
            "vector": record["embedding"],
            "text": record["text"],
            "external_chunk_id": metadata["external_chunk_id"],
            "kb_code": metadata["kb_code"],
            "article_title": metadata["article_title"],
            "file_name": metadata["file_name"],
            "section_title": metadata["section_title"],
            "section_type": metadata["section_type"],
            "chunk_type": metadata["chunk_type"],
            "priority": metadata["priority"],
            "priority_weight": float(metadata["priority_weight"]),
            "word_count": int(metadata["word_count"]),
            "embedding_model": metadata["embedding_model"],
            "embedding_text_hash": metadata["embedding_text_hash"],
            "indexed_at_unix": int(metadata["indexed_at_unix"]),
        }

        rows.append(row)

    logger.info(
        "Upserting %s records into Milvus collection %s",
        len(rows),
        config.collection_name,
    )

    client.upsert(
        collection_name=config.collection_name,
        data=rows,
    )

    logger.info("Milvus indexing completed.")


# -----------------------------------------------------------------------------
# Pipeline entrypoint
# -----------------------------------------------------------------------------

def run_embedding_pipeline(
    embedding_config: EmbeddingConfig,
    milvus_config: MilvusConfig,
    write_milvus: bool = False,
) -> None:
    chunks = load_chunks(embedding_config.input_path)
    model = EmbeddingModel(embedding_config)
    records = embed_chunks(chunks, model, embedding_config.output_path)

    if write_milvus:
        index_to_milvus(records, milvus_config, model.dimension)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Embed KB chunks and optionally index them in Milvus."
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=EmbeddingConfig().input_path,
        help="Path to chunks.json.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=EmbeddingConfig().output_path,
        help="Path to embeddings.jsonl.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=EmbeddingConfig().model_name,
        help="Sentence-transformers model name.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=EmbeddingConfig().batch_size,
        help="Embedding batch size.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=EmbeddingConfig().device,
        help='Device for sentence-transformers, e.g. "cpu" or "cuda".',
    )
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="Disable embedding normalization.",
    )
    parser.add_argument(
        "--milvus-uri",
        type=str,
        default=MilvusConfig().uri,
        help="Milvus URI, e.g. http://localhost:19530.",
    )
    parser.add_argument(
        "--milvus-token",
        type=str,
        default=MilvusConfig().token,
        help="Milvus token if required.",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=MilvusConfig().collection_name,
        help="Milvus collection name.",
    )
    parser.add_argument(
        "--write-milvus",
        action="store_true",
        help="Also write embeddings to Milvus. Requires Milvus to be running.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    embedding_config = EmbeddingConfig(
        model_name=args.model,
        input_path=args.input,
        output_path=args.output,
        batch_size=args.batch_size,
        normalize_embeddings=not args.no_normalize,
        device=args.device,
    )

    milvus_config = MilvusConfig(
        uri=args.milvus_uri,
        token=args.milvus_token,
        collection_name=args.collection,
    )

    run_embedding_pipeline(
        embedding_config=embedding_config,
        milvus_config=milvus_config,
        write_milvus=args.write_milvus,
    )


if __name__ == "__main__":
    main()
