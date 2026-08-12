import json
import os
import re
import time
import unicodedata
from functools import lru_cache
from typing import Any

from pymilvus import Collection, connections
from sentence_transformers import SentenceTransformer

from app.config import get_cache_settings
from app.database import SessionLocal
from app.models import Chunk, DocumentVersion, SourceDocument
from app.services.cache_service import (
    acquire_lock,
    bounded_wait_for_json,
    delete_key,
    embedding_cache_key,
    get_knowledge_generation,
    read_json,
    release_lock,
    retrieval_cache_key,
    validate_embedding,
    validate_retrieval_payload,
    write_json,
)
from scripts.embeddings import build_embedding_text


MILVUS_HOST = os.getenv("MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "sogetrel_chunks")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

SEMANTIC_RETRIEVAL_CONFIG = {
    "anns_field": "embedding",
    "metric_type": "COSINE",
    "params": {},
    "ranking": "distance_descending",
    # Changing this version also changes the retrieval cache key,
    # preventing stale pre-reranking search results from being reused.
    "reranker": {
        "name": "business_lexical_v2",
        "lexical_weight": 0.025,
        "candidate_multiplier": 8,
    },
}


FRENCH_STOP_WORDS = {
    "a",
    "au",
    "aux",
    "avec",
    "ce",
    "ces",
    "cette",
    "de",
    "des",
    "du",
    "en",
    "est",
    "et",
    "je",
    "la",
    "le",
    "les",
    "me",
    "mon",
    "ma",
    "mes",
    "pour",
    "que",
    "quel",
    "quelle",
    "quels",
    "quelles",
    "qui",
    "se",
    "si",
    "son",
    "sa",
    "ses",
    "sur",
    "un",
    "une",
    "utiliser",
    "dois",
    "doit",
    "bonjour",
}


GENERIC_RETRIEVAL_TERMS = {
    "code",
    "codes",
    "cloture",
    "cloturer",
    "utilise",
    "utiliser",
    "usage",
}


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def get_collection() -> Collection:
    connections.connect(
        alias="default",
        host=MILVUS_HOST,
        port=MILVUS_PORT,
    )
    collection = Collection(MILVUS_COLLECTION)
    collection.load()
    return collection


def build_query_embedding_text(query: str) -> str:
    return (
        "Domaine: FDE\n"
        "Type de recherche: question utilisateur\n"
        "Objectif: retrouver les procédures, règles métier, "
        "codes situation et cas applicables.\n"
        f"Question:\n{query}"
    )


def _encode_query(
    model: SentenceTransformer,
    query: str,
) -> list[float]:
    vector = model.encode(
        build_query_embedding_text(query),
        normalize_embeddings=True,
    )
    return [float(value) for value in vector]


def embed_query(
    query: str,
    performance: dict[str, Any] | None = None,
) -> list[float]:
    started = time.perf_counter()
    settings = get_cache_settings()

    model = get_embedding_model()
    dimension = int(
        model.get_sentence_embedding_dimension() or 0
    )

    key = embedding_cache_key(
        settings,
        EMBEDDING_MODEL,
        query,
    )

    cached = read_json(key, settings)

    if performance is not None:
        performance["cache_lookup_ms"] = (
            performance.get("cache_lookup_ms", 0.0)
            + cached.lookup_ms
        )
        performance["embedding_cache_status"] = cached.status

    vector = validate_embedding(
        cached.value,
        dimension,
    )

    if vector is not None:
        if performance is not None:
            performance["embedding_ms"] = (
                time.perf_counter() - started
            ) * 1000
        return vector

    if cached.value is not None:
        delete_key(key, settings)

    token = acquire_lock(
        key,
        settings=settings,
    )

    if token is not None:
        double_checked = read_json(
            key,
            settings,
        )

        if performance is not None:
            performance["cache_lookup_ms"] = (
                performance.get("cache_lookup_ms", 0.0)
                + double_checked.lookup_ms
            )

        vector = validate_embedding(
            double_checked.value,
            dimension,
        )

        if vector is not None:
            release_lock(
                key,
                token,
                settings=settings,
            )

            if performance is not None:
                performance["embedding_cache_status"] = (
                    "hit_after_lock"
                )
                performance["embedding_ms"] = (
                    time.perf_counter() - started
                ) * 1000

            return vector

    if token is None and cached.status == "miss":
        waited = bounded_wait_for_json(
            key,
            settings=settings,
        )

        if performance is not None:
            performance["cache_lookup_ms"] = (
                performance.get("cache_lookup_ms", 0.0)
                + waited.lookup_ms
            )

        vector = validate_embedding(
            waited.value,
            dimension,
        )

        if vector is not None:
            if performance is not None:
                performance["embedding_cache_status"] = (
                    "hit_after_wait"
                )
                performance["embedding_ms"] = (
                    time.perf_counter() - started
                ) * 1000

            return vector

    try:
        vector = _encode_query(
            model,
            query,
        )

        if len(vector) == dimension and dimension > 0:
            write_json(
                key,
                {
                    "dimension": dimension,
                    "vector": vector,
                },
                settings.embedding_ttl_seconds,
                settings,
            )

        if performance is not None:
            performance["embedding_ms"] = (
                time.perf_counter() - started
            ) * 1000

        return vector

    finally:
        release_lock(
            key,
            token,
            settings=settings,
        )


def _semantic_cache_key(
    query: str,
    top_k: int,
    generation: int,
) -> str:
    settings = get_cache_settings()

    return retrieval_cache_key(
        settings,
        retrieval_mode="semantic",
        query=query,
        top_k=top_k,
        filters={},
        collection_name=MILVUS_COLLECTION,
        embedding_model=EMBEDDING_MODEL,
        retrieval_config=SEMANTIC_RETRIEVAL_CONFIG,
        knowledge_generation=generation,
    )


def _metadata_dict(
    value: Any,
) -> dict[str, Any]:
    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}

        return parsed if isinstance(parsed, dict) else {}

    return {}


def _metadata_int(
    metadata: dict[str, Any],
    *keys: str,
) -> int | None:
    for key in keys:
        value = metadata.get(key)

        if value in (None, ""):
            continue

        try:
            return int(value)
        except (TypeError, ValueError):
            continue

    return None


def _filter_current_version_hits(
    hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requested_pairs: set[tuple[int, int]] = set()
    hit_pairs: list[
        tuple[int | None, int | None]
    ] = []

    for hit in hits:
        metadata = _metadata_dict(
            hit.get("metadata")
        )

        document_id = _metadata_int(
            metadata,
            "document_id",
            "source_document_id",
        )

        version_id = _metadata_int(
            metadata,
            "version_id",
            "document_version_id",
        )

        hit_pairs.append(
            (document_id, version_id)
        )

        if (
            document_id is not None
            and version_id is not None
        ):
            requested_pairs.add(
                (document_id, version_id)
            )

    if not requested_pairs:
        return hits

    document_ids = sorted(
        {
            document_id
            for document_id, _version_id
            in requested_pairs
        }
    )

    db = SessionLocal()

    try:
        current_rows = (
            db.query(
                SourceDocument.document_id,
                SourceDocument.current_version_id,
            )
            .filter(
                SourceDocument.document_id.in_(
                    document_ids
                ),
                SourceDocument.processing_status
                == "completed",
            )
            .all()
        )
    finally:
        db.close()

    current_pairs = {
        (
            int(document_id),
            int(version_id),
        )
        for document_id, version_id
        in current_rows
        if version_id is not None
    }

    if not current_pairs:
        return hits

    filtered: list[dict[str, Any]] = []

    for hit, pair in zip(
        hits,
        hit_pairs,
        strict=True,
    ):
        document_id, version_id = pair

        if (
            document_id is None
            or version_id is None
        ):
            filtered.append(hit)

        elif (
            document_id,
            version_id,
        ) in current_pairs:
            filtered.append(hit)

    return filtered


# ------------------------------------------------------------------
# BUSINESS-AWARE SEMANTIC RERANKING
# ------------------------------------------------------------------


def _normalize_text(
    value: str | None,
) -> str:
    text = unicodedata.normalize(
        "NFKD",
        value or "",
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    return text.lower()


def _tokenize(
    value: str | None,
) -> list[str]:
    normalized = _normalize_text(value)

    return re.findall(
        r"\b[\w-]+\b",
        normalized,
    )


def _meaningful_tokens(
    value: str | None,
) -> list[str]:
    return [
        token
        for token in _tokenize(value)
        if (
            token not in FRENCH_STOP_WORDS
            and len(token) >= 2
        )
    ]


def _token_match_forms(
    token: str,
) -> set[str]:
    forms = {token}

    if (
        len(token) > 3
        and token.endswith("s")
        and not token.isupper()
    ):
        forms.add(token[:-1])

    elif len(token) > 3:
        forms.add(f"{token}s")

    return forms


def _contains_token(
    token: str,
    text_term_set: set[str],
) -> bool:
    return bool(
        _token_match_forms(token)
        & text_term_set
    )


def _is_generic_retrieval_term(
    token: str,
) -> bool:
    return bool(
        _token_match_forms(token)
        & GENERIC_RETRIEVAL_TERMS
    )


def _query_acronyms(
    query: str,
) -> set[str]:
    """
    Preserve exact operational identifiers such as:
    PM, PB, DR, BL, LP, MA, F04, P03, TSO, etc.
    """

    return {
        token.upper()
        for token in re.findall(
            r"\b[A-Za-z0-9]{2,10}\b",
            query,
        )
        if (
            token.isupper()
            or any(
                char.isdigit()
                for char in token
            )
        )
    }


def _lexical_rerank_score(
    query: str,
    hit: dict[str, Any],
) -> float:
    combined_text = " ".join(
        str(value or "")
        for value in (
            hit.get("text"),
            hit.get("article_title"),
            hit.get("section_title"),
            hit.get("kb_code"),
        )
    )

    query_terms = _meaningful_tokens(
        query
    )

    text_terms = _meaningful_tokens(
        combined_text
    )

    text_term_set = set(text_terms)

    normalized_query = " ".join(
        query_terms
    )

    normalized_business_text = " ".join(
        text_terms
    )

    score = 0.0

    # --------------------------------------------------------------
    # 1. Reward meaningful business-term overlap.
    # --------------------------------------------------------------

    for term in query_terms:
        if _contains_token(term, text_term_set):
            if _is_generic_retrieval_term(term):
                score += 0.35
            else:
                score += 2.0

    # --------------------------------------------------------------
    # 2. Reward adjacent meaningful phrases.
    #
    # Because stop words have already been removed, something like:
    #
    # "branchement au PB"
    #
    # becomes:
    #
    # "branchement pb"
    #
    # for both the query and candidate.
    # --------------------------------------------------------------

    for left, right in zip(
        query_terms,
        query_terms[1:],
    ):
        phrase = f"{left} {right}"

        if phrase in normalized_business_text:
            if (
                _is_generic_retrieval_term(left)
                and _is_generic_retrieval_term(right)
            ):
                score += 0.40
            else:
                score += 8.0

    # --------------------------------------------------------------
    # 3. Extremely strong reward for exact operational identifiers.
    #
    # PM must strongly prefer PM.
    # PB must strongly prefer PB.
    # F04 must strongly prefer F04.
    # --------------------------------------------------------------

    text_upper_tokens = {
        token.upper()
        for token in re.findall(
            r"\b[A-Za-z0-9]{2,20}\b",
            combined_text,
        )
    }

    for acronym in _query_acronyms(
        query
    ):
        if acronym in text_upper_tokens:
            score += 4.0

    # --------------------------------------------------------------
    # 4. Reward near-exact/full-query matches.
    #
    # Useful for copied rules and FAQ questions.
    # --------------------------------------------------------------

    if (
        normalized_query
        and normalized_query
        in normalized_business_text
    ):
        if any(
            not _is_generic_retrieval_term(term)
            for term in query_terms
        ):
            score += 8.0
        else:
            score += 1.0

    # --------------------------------------------------------------
    # 5. Prefer authoritative knowledge chunk types.
    # --------------------------------------------------------------

    chunk_type = str(
        hit.get("chunk_type") or ""
    ).lower()

    discriminative_overlap = any(
        _contains_token(term, text_term_set)
        for term in query_terms
        if not _is_generic_retrieval_term(term)
    )

    if chunk_type == "rule":
        score += 0.75
        if discriminative_overlap:
            score += 3.00

    elif chunk_type == "business_case":
        score += 1.00
        if discriminative_overlap:
            score += 3.00

    elif chunk_type == "faq":
        score += 0.35

    elif chunk_type == "question" and any(
        not _is_generic_retrieval_term(term)
        for term in query_terms
    ):
        if not discriminative_overlap:
            score -= 0.50

    # --------------------------------------------------------------
    # 6. Small priority preference.
    # --------------------------------------------------------------

    priority = str(
        hit.get("priority") or ""
    ).lower()

    if priority == "critical":
        score += 0.40

    elif priority == "high":
        score += 0.20

    return score


def _build_current_chunk_search_row(
    chunk: Chunk,
    version: DocumentVersion,
    document: SourceDocument,
) -> dict[str, Any]:
    metadata = _metadata_dict(chunk.metadata_json)
    external_id = str(metadata.get("external_chunk_id") or chunk.chunk_id)

    return {
        "rank": 0,
        "score": 0.0,
        "id": external_id,
        "text": chunk.chunk_text,
        "kb_code": str(metadata.get("kb_code") or document.file_name),
        "article_title": str(metadata.get("article_title") or document.file_name),
        "file_name": str(document.file_name),
        "section_title": str(metadata.get("section_title") or ""),
        "section_type": str(metadata.get("section_type") or ""),
        "chunk_type": str(chunk.chunk_type or metadata.get("chunk_type") or ""),
        "priority": str(metadata.get("priority") or "medium"),
        "word_count": int(chunk.token_count or len((chunk.chunk_text or "").split())),
        "metadata": {
            **metadata,
            "document_id": document.document_id,
            "version_id": version.version_id,
            "source_document_id": document.document_id,
            "document_version_id": version.version_id,
            "file_name": document.file_name,
            "source_filename": document.file_name,
        },
    }


def _embedding_vector(values: Any) -> list[float]:
    if hasattr(values, "tolist"):
        values = values.tolist()

    if values is None:
        return []

    if isinstance(values, (list, tuple)) and values:
        first = values[0]
        if isinstance(first, (list, tuple)):
            values = first

    return [float(value) for value in values]


def _embedding_matrix(values: Any, expected_rows: int) -> list[list[float]]:
    if hasattr(values, "tolist"):
        values = values.tolist()

    if values is None or expected_rows <= 0:
        return []

    if isinstance(values, (list, tuple)) and values:
        first = values[0]
        if isinstance(first, (int, float)):
            row = [float(value) for value in values]
            return [row for _ in range(expected_rows)]

    return [[float(value) for value in row] for row in values]


def _lexical_current_version_candidates(
    query: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    db = SessionLocal()

    try:
        rows = (
            db.query(Chunk, DocumentVersion, SourceDocument)
            .join(DocumentVersion, Chunk.version_id == DocumentVersion.version_id)
            .join(SourceDocument, DocumentVersion.document_id == SourceDocument.document_id)
            .filter(SourceDocument.processing_status == "completed")
            .filter(SourceDocument.current_version_id == DocumentVersion.version_id)
            .all()
        )
    finally:
        db.close()

    candidates: list[dict[str, Any]] = []
    model = get_embedding_model()
    query_vector = model.encode(
        build_query_embedding_text(query),
        normalize_embeddings=True,
    )
    query_vector = _embedding_vector(query_vector)

    for chunk, version, document in rows:
        text = chunk.chunk_text or ""
        if not text.strip():
            continue

        candidate = _build_current_chunk_search_row(
            chunk=chunk,
            version=version,
            document=document,
        )
        lexical_score = _lexical_rerank_score(query, candidate)
        if lexical_score <= 0:
            continue
        candidate["score"] = lexical_score
        candidates.append(candidate)

    if not candidates:
        return []

    candidates.sort(
        key=lambda item: (
            item["score"],
            str(item.get("priority") or "") == "critical",
            str(item.get("priority") or "") == "high",
        ),
        reverse=True,
    )
    candidates = candidates[:limit]

    candidate_vectors = _embedding_matrix(
        model.encode(
            [build_embedding_text(candidate) for candidate in candidates],
            normalize_embeddings=True,
        ),
        len(candidates),
    )

    for candidate, candidate_vector in zip(candidates, candidate_vectors):
        candidate["score"] = float(
            sum(a * b for a, b in zip(query_vector, candidate_vector))
        )

    candidates.sort(
        key=lambda item: (
            item["score"],
            str(item.get("priority") or "") == "critical",
            str(item.get("priority") or "") == "high",
        ),
        reverse=True,
    )

    return candidates[:limit]

def _merge_candidate_hits(
    hits: list[dict[str, Any]],
    lexical_hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    for hit in hits:
        hit_id = str(hit.get("id") or "").strip()
        if not hit_id:
            continue
        merged[hit_id] = dict(hit)
        merged[hit_id]["retrieval_source"] = "semantic"

    for hit in lexical_hits:
        hit_id = str(hit.get("id") or "").strip()
        if not hit_id:
            continue
        current = merged.get(hit_id)
        if current is None or float(hit.get("score") or 0.0) > float(current.get("score") or 0.0):
            merged[hit_id] = dict(hit)
            merged[hit_id]["retrieval_source"] = "lexical"
        else:
            current.setdefault("retrieval_source", "semantic")

    return list(merged.values())


def _rerank_semantic_hits(
    query: str,
    hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Rerank Milvus candidates while keeping semantic similarity
    as the primary retrieval signal.

    The API continues returning the original semantic similarity
    score so existing analytics/confidence logic remains compatible.
    """

    if not hits:
        return hits

    for hit in hits:
        semantic_score = float(
            hit.get("score") or 0.0
        )

        lexical_score = (
            _lexical_rerank_score(
                query,
                hit,
            )
        )

        hybrid_score = (
            semantic_score
            + lexical_score * 0.025
        )

        hit["_semantic_score"] = (
            semantic_score
        )

        hit["_hybrid_score"] = (
            hybrid_score
        )

    hits.sort(
        key=lambda item: item[
            "_hybrid_score"
        ],
        reverse=True,
    )

    for hit in hits:
        # Preserve the original COSINE score for current
        # API contracts, dashboards and analytics.
        hit["score"] = hit.pop(
            "_semantic_score"
        )

        hit.pop(
            "_hybrid_score",
            None,
        )

    return hits


# ------------------------------------------------------------------
# SEMANTIC SEARCH
# ------------------------------------------------------------------


def search_chunks(
    query: str,
    top_k: int = 5,
    performance: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not query or not query.strip():
        raise ValueError(
            "Query cannot be empty."
        )

    settings = get_cache_settings()

    generation_started = (
        time.perf_counter()
    )

    generation = get_knowledge_generation(
        settings
    )

    key = _semantic_cache_key(
        query,
        top_k,
        generation,
    )

    cached = read_json(
        key,
        settings,
    )

    if performance is not None:
        performance["cache_lookup_ms"] = (
            performance.get(
                "cache_lookup_ms",
                0.0,
            )
            + (
                time.perf_counter()
                - generation_started
            )
            * 1000
            + cached.lookup_ms
        )

        performance["cache_status"] = (
            cached.status
        )

        performance["cache_hit"] = False

    hits = validate_retrieval_payload(
        cached.value,
        top_k,
    )

    if hits is not None:
        if performance is not None:
            performance["cache_hit"] = True
            performance["cache_status"] = (
                "hit"
            )

        return hits

    if cached.value is not None:
        delete_key(
            key,
            settings,
        )

    token = acquire_lock(
        key,
        settings=settings,
    )

    if token is not None:
        double_checked = read_json(
            key,
            settings,
        )

        if performance is not None:
            performance["cache_lookup_ms"] += (
                double_checked.lookup_ms
            )

        hits = validate_retrieval_payload(
            double_checked.value,
            top_k,
        )

        if hits is not None:
            release_lock(
                key,
                token,
                settings=settings,
            )

            if performance is not None:
                performance["cache_hit"] = True
                performance["cache_status"] = (
                    "hit_after_lock"
                )

            return hits

    if (
        token is None
        and cached.status == "miss"
    ):
        waited = bounded_wait_for_json(
            key,
            settings=settings,
        )

        if performance is not None:
            performance["cache_lookup_ms"] += (
                waited.lookup_ms
            )

        hits = validate_retrieval_payload(
            waited.value,
            top_k,
        )

        if hits is not None:
            if performance is not None:
                performance["cache_hit"] = True
                performance["cache_status"] = (
                    "hit_after_wait"
                )

            return hits

    try:
        query_vector = embed_query(
            query,
            performance=performance,
        )

        milvus_started = (
            time.perf_counter()
        )

        collection = get_collection()

        # Retrieve a broader semantic candidate set and rerank it.
        #
        # top_k=5  -> 40 Milvus candidates
        # top_k=10 -> 50 Milvus candidates (maximum)
        search_limit = min(
            max(
                top_k * 8,
                top_k,
            ),
            50,
        )

        results = collection.search(
            data=[query_vector],
            anns_field="embedding",
            param={
                "metric_type": "COSINE",
                "params": {},
            },
            limit=search_limit,
            output_fields=[
                "id",
                "text",
                "kb_code",
                "article_title",
                "section_title",
                "chunk_type",
                "priority",
                "metadata",
            ],
        )

        if performance is not None:
            performance["milvus_ms"] = (
                time.perf_counter()
                - milvus_started
            ) * 1000

        raw_hits: list[
            dict[str, Any]
        ] = []

        for hit in results[0]:
            entity = hit.entity

            raw_hits.append(
                {
                    "rank": 0,
                    "score": float(
                        hit.distance
                    ),
                    "id": entity.get(
                        "id"
                    ),
                    "text": entity.get(
                        "text"
                    ),
                    "kb_code": entity.get(
                        "kb_code"
                    ),
                    "article_title": entity.get(
                        "article_title"
                    ),
                    "section_title": entity.get(
                        "section_title"
                    ),
                    "chunk_type": entity.get(
                        "chunk_type"
                    ),
                    "priority": entity.get(
                        "priority"
                    ),
                    "metadata": entity.get(
                        "metadata"
                    ),
                }
            )

        # Remove superseded document versions first.
        hits = _filter_current_version_hits(
            raw_hits
        )

        lexical_hits = _lexical_current_version_candidates(
            query,
            limit=min(max(top_k * 5, 20), 50),
        )

        hits = _merge_candidate_hits(
            hits,
            lexical_hits,
        )

        # Then rerank the merged semantic + lexical candidates using
        # exact business terminology, phrases and identifiers.
        hits = _rerank_semantic_hits(query, hits)

        # Only after reranking do we select the final Top-K.
        hits = hits[:top_k]

        for rank, hit in enumerate(
            hits,
            start=1,
        ):
            hit["rank"] = rank

        stored = write_json(
            key,
            {
                "results": hits,
            },
            settings.search_ttl_seconds,
            settings,
        )

        if performance is not None:
            performance["_cache_key"] = key
            performance["_cache_settings"] = (
                settings
            )
            performance["_cache_written"] = (
                stored
            )

        return hits

    finally:
        release_lock(
            key,
            token,
            settings=settings,
        )
