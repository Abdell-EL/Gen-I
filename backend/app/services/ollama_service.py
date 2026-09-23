from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import re
import unicodedata
from typing import Any, Iterator

import requests
from requests.adapters import HTTPAdapter

from app.config import CacheSettings, get_cache_settings, get_ollama_settings
from app.services.cache_service import read_json, write_json


# Compatibility constants retain the established production defaults.
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "llama3.2:3b"


@lru_cache(maxsize=1)
def get_ollama_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def close_ollama_session() -> None:
    if get_ollama_session.cache_info().currsize:
        get_ollama_session().close()
        get_ollama_session.cache_clear()


def _chunk_identity(item: dict[str, Any]) -> str:
    external_id = item.get("id") or item.get("external_chunk_id")
    if external_id:
        return f"id:{external_id}"
    content = "\x1f".join(
        str(item.get(field) or "")
        for field in ("article_title", "section_title", "text")
    )
    return "content:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def deduplicate_chunks(
    retrieved_chunks: list[dict[str, Any]],
    max_chunks: int = 5,
) -> list[dict[str, Any]]:
    selected = []
    seen = set()
    for item in retrieved_chunks:
        identity = _chunk_identity(item)
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(item)
        if len(selected) >= max_chunks:
            break
    return selected


def _truncate_text(text: str, available: int) -> str:
    if len(text) <= available:
        return text
    if available <= 1:
        return ""
    candidate = text[: available - 1]
    boundary = max(candidate.rfind("\n"), candidate.rfind(". "), candidate.rfind(" "))
    if boundary >= max(0, len(candidate) // 2):
        candidate = candidate[: boundary + 1].rstrip()
    return candidate.rstrip() + "…"

PROMPT_STOP_WORDS = {
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

PROMPT_GENERIC_CASE_TERMS = {
    "code",
    "codes",
    "cloture",
    "cloturer",
    "dossier",
    "fibre",
    "technicien",
    "utilise",
    "utiliser",
}


def _normalize_prompt_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(
        char for char in text if not unicodedata.combining(char)
    )
    return text.lower()


def _prompt_tokens(value: str | None) -> list[str]:
    return re.findall(r"\b[\w-]+\b", _normalize_prompt_text(value))


def _prompt_token_forms(token: str) -> set[str]:
    forms = {token}
    if len(token) > 3 and token.endswith("s"):
        forms.add(token[:-1])
    elif len(token) > 3:
        forms.add(f"{token}s")
    return forms


def _operational_case_terms(question: str) -> list[str]:
    terms = []
    for token in _prompt_tokens(question):
        forms = _prompt_token_forms(token)
        if token in PROMPT_STOP_WORDS or forms & PROMPT_GENERIC_CASE_TERMS:
            continue
        if len(token) >= 2:
            terms.append(token)
    return terms


def _is_closure_code_question(question: str) -> bool:
    normalized = _normalize_prompt_text(question)
    return "code de cloture" in normalized or "quel code" in normalized


def _matches_operational_case(
    question: str,
    chunk: dict[str, Any],
) -> bool:
    terms = _operational_case_terms(question)
    if not terms:
        return False

    text_tokens = set(
        _prompt_tokens(
            " ".join(
                str(chunk.get(field) or "")
                for field in (
                    "text",
                    "article_title",
                    "section_title",
                    "kb_code",
                )
            )
        )
    )
    matched = sum(
        1
        for term in terms
        if _prompt_token_forms(term) & text_tokens
    )
    required = max(1, min(len(terms), round(len(terms) * 0.6)))
    return matched >= required


def _is_direct_closure_rule(
    question: str,
    chunk: dict[str, Any],
) -> bool:
    chunk_type = str(chunk.get("chunk_type") or "").lower()
    if chunk_type not in {"rule", "business_case"}:
        return False

    text = _normalize_prompt_text(str(chunk.get("text") or ""))
    has_direct_rule_language = (
        "code de cloture" in text
        or "code situation" in text
        or "code unique" in text
        or "codes ou motifs" in text
    )
    return has_direct_rule_language and _matches_operational_case(
        question,
        chunk,
    )



def build_context(
    retrieved_chunks: list[dict[str, Any]],
    max_chunks: int = 5,
    max_chars: int | None = None,
) -> str:
    settings = get_ollama_settings()
    budget = max_chars if max_chars is not None else settings.max_context_chars
    context_blocks = []
    used = 0
    separator = "\n\n---\n\n"
    for item in deduplicate_chunks(retrieved_chunks, max_chunks=max_chunks):
        source_id = item.get("id") or item.get("external_chunk_id") or "unknown"
        title = item.get("article_title", "")
        section = item.get("section_title", "")
        header = (
            f"Source ID: {source_id}\n"
            f"Article: {title}\n"
            f"Section: {section}\n"
            "Contenu: "
        )
        separator_cost = len(separator) if context_blocks else 0
        available = budget - used - separator_cost - len(header)
        if available <= 0:
            break
        text = _truncate_text(str(item.get("text") or ""), available)
        if not text and item.get("text"):
            break
        block = header + text
        context_blocks.append(block)
        used += separator_cost + len(block)
    return separator.join(context_blocks)


def build_history_context(
    conversation_history: list[dict[str, Any]] | None,
    max_chars: int = 3000,
) -> str:
    if not conversation_history:
        return ""

    lines = []
    used = 0
    for item in conversation_history:
        role = "Utilisateur" if item.get("role") == "user" else "Assistant"
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        line = f"{role}: {content}"
        if used + len(line) > max_chars:
            remaining = max_chars - used
            if remaining <= 0:
                break
            line = _truncate_text(line, remaining)
        lines.append(line)
        used += len(line)
    return "\n".join(lines)


def build_grounded_prompt(
    question: str,
    retrieved_chunks: list[dict[str, Any]],
    context: str | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
) -> str:
    if context is None:
        context = build_context(retrieved_chunks)
    history = build_history_context(conversation_history)
    closure_code_question = _is_closure_code_question(question)
    direct_closure_rule = (
        bool(retrieved_chunks)
        and closure_code_question
        and _is_direct_closure_rule(question, retrieved_chunks[0])
    )
    top_source_matches_case = bool(retrieved_chunks) and _matches_operational_case(
        question,
        retrieved_chunks[0],
    )
    direct_answer_block = (
        "\n- La première source fournie contient une règle métier directe et spécifique à la question. "
        "Réponds uniquement avec cette règle prioritaire.\n"
        "- N'ajoute pas de cas alternatifs, de contre-exemples, ni de détails non demandés comme le code unique.\n"
        "- Si la source répond explicitement à la typologie/cas demandé, n'utilise pas les sources de rang inférieur sauf contradiction.\n"
        if direct_closure_rule else ""
    )
    retrieval_safety_block = (
        "\n- Si les premières sources ne correspondent pas explicitement au cas opérationnel demandé, "
        "ne choisis pas un code provenant d'une règle de rang inférieur portant sur un autre cas ; "
        "dis que l'information n'est pas présente dans les sources disponibles.\n"
        if closure_code_question and not direct_closure_rule and not top_source_matches_case else ""
    )
    history_block = (
        f"\nHISTORIQUE RÉCENT DE LA CONVERSATION (pour comprendre le suivi, sans remplacer les sources) :\n{history}\n"
        if history else ""
    )
    return f"""
Tu es un assistant interne pour la base de connaissance opérationnelle Sogetrel.

Ta mission :
- Répondre en français.
- Utiliser uniquement le CONTEXTE fourni pour les faits métier.
- Utiliser l'historique récent uniquement pour comprendre les références d'une question de suivi.
- Ne pas inventer d'information.
- Si le contexte ne contient pas la réponse, dire clairement que l'information n'est pas présente dans les sources disponibles.
- Donner une réponse courte, claire et opérationnelle.
- Si une règle métier ou un code situation est présent, le mettre en évidence.
- Ne cite pas de source inexistante.
- Quand une source répond directement à la question, privilégie cette règle directe et ignore les passages moins spécifiques.{direct_answer_block}{retrieval_safety_block}
{history_block}
QUESTION UTILISATEUR ACTUELLE :
{question}

CONTEXTE DISPONIBLE :
{context}

RÉPONSE :
""".strip()

NO_ANSWER_MESSAGE = "Je n'ai pas pu générer une réponse à partir des sources disponibles."


def _answer_cache_key(settings: CacheSettings, model: str, prompt: str) -> str:
    # Keyed on the exact rendered prompt, which already encodes the question,
    # the retrieved context, and any conversation history — identical prompts
    # deserve the same answer; anything that changes the prompt naturally
    # misses instead of needing separate invalidation bookkeeping.
    return ":".join(
        (
            settings.namespace,
            settings.version,
            "answer",
            hashlib.sha256(model.encode("utf-8")).hexdigest()[:16],
            hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        )
    )


def generate_answer_with_ollama(
    question: str,
    retrieved_chunks: list[dict[str, Any]],
    conversation_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    settings = get_ollama_settings()
    selected_chunks = deduplicate_chunks(retrieved_chunks, max_chunks=5)
    context = build_context(selected_chunks, max_chunks=5, max_chars=settings.max_context_chars)
    prompt = build_grounded_prompt(
        question=question,
        retrieved_chunks=selected_chunks,
        context=context,
        conversation_history=conversation_history,
    )
    # build_grounded_prompt applies the same deterministic context budget.
    if context not in prompt:
        raise RuntimeError("Ollama context assembly failed.")

    cache_settings = get_cache_settings()
    cache_key = _answer_cache_key(cache_settings, settings.selected_model, prompt)
    cached = read_json(cache_key, cache_settings)
    if isinstance(cached.value, dict) and cached.value.get("answer"):
        return {
            **cached.value,
            "context_chunks_selected": len(retrieved_chunks),
            "context_chunks_included": context.count("Source ID:"),
            "context_chars": len(context),
        }

    payload = {
        "model": settings.selected_model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": settings.keep_alive,
        "options": {
            "temperature": settings.temperature,
            "top_p": 0.9,
            "num_ctx": settings.num_ctx,
            "num_predict": settings.num_predict,
        },
    }
    response = get_ollama_session().post(
        settings.url,
        json=payload,
        timeout=settings.request_timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    answer = data.get("response", "").strip()
    if not answer:
        answer = NO_ANSWER_MESSAGE
    result = {
        "answer": answer,
        "model": settings.selected_model,
        "prompt_tokens": data.get("prompt_eval_count"),
        "completion_tokens": data.get("eval_count"),
        "total_duration": data.get("total_duration"),
    }
    if answer != NO_ANSWER_MESSAGE:
        write_json(cache_key, result, cache_settings.answer_ttl_seconds, cache_settings)
    return {
        **result,
        "context_chunks_selected": len(retrieved_chunks),
        "context_chunks_included": context.count("Source ID:"),
        "context_chars": len(context),
    }


@dataclass
class OllamaStream:
    model: str
    context_chunks_selected: int
    context_chunks_included: int
    context_chars: int
    _url: str
    _payload: dict[str, Any]
    _timeout: float
    _cached_answer: str | None = None
    _cache_key: str | None = None
    _cache_settings: CacheSettings | None = None

    def chunks(self) -> Iterator[dict[str, Any]]:
        """Yield validated Ollama events and always release the HTTP response."""
        if self._cached_answer is not None:
            yield {"type": "token", "text": self._cached_answer}
            yield {
                "type": "ollama_done",
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_duration": 0,
            }
            return

        response = None
        answer_parts: list[str] = []
        completed = False
        try:
            response = get_ollama_session().post(
                self._url,
                json=self._payload,
                timeout=self._timeout,
                stream=True,
            )
            response.raise_for_status()
            for raw_line in response.iter_lines(decode_unicode=False):
                if not raw_line:
                    continue
                try:
                    line = raw_line.decode("utf-8")
                    payload = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(payload, dict):
                    continue
                text = payload.get("response")
                if isinstance(text, str) and text:
                    answer_parts.append(text)
                    yield {"type": "token", "text": text}
                if payload.get("done") is True:
                    completed = True
                    yield {
                        "type": "ollama_done",
                        "prompt_tokens": payload.get("prompt_eval_count"),
                        "completion_tokens": payload.get("eval_count"),
                        "total_duration": payload.get("total_duration"),
                    }
                    return
        finally:
            if response is not None:
                response.close()
            full_answer = "".join(answer_parts).strip()
            if completed and self._cache_key and full_answer:
                write_json(
                    self._cache_key,
                    {"answer": full_answer},
                    (self._cache_settings or get_cache_settings()).answer_ttl_seconds,
                    self._cache_settings,
                )


def stream_answer_with_ollama(
    question: str,
    retrieved_chunks: list[dict[str, Any]],
    conversation_history: list[dict[str, Any]] | None = None,
) -> OllamaStream:
    """Prepare an Ollama streaming request using the legacy prompt and settings."""
    settings = get_ollama_settings()
    selected_chunks = deduplicate_chunks(retrieved_chunks, max_chunks=5)
    context = build_context(
        selected_chunks,
        max_chunks=5,
        max_chars=settings.max_context_chars,
    )
    prompt = build_grounded_prompt(
        question=question,
        retrieved_chunks=selected_chunks,
        context=context,
        conversation_history=conversation_history,
    )
    if context not in prompt:
        raise RuntimeError("Ollama context assembly failed.")

    cache_settings = get_cache_settings()
    cache_key = _answer_cache_key(cache_settings, settings.selected_model, prompt)
    cached = read_json(cache_key, cache_settings)
    cached_answer = (
        cached.value.get("answer")
        if isinstance(cached.value, dict) and cached.value.get("answer")
        else None
    )

    return OllamaStream(
        model=settings.selected_model,
        context_chunks_selected=len(retrieved_chunks),
        context_chunks_included=context.count("Source ID:"),
        context_chars=len(context),
        _url=settings.url,
        _payload={
            "model": settings.selected_model,
            "prompt": prompt,
            "stream": True,
            "keep_alive": settings.keep_alive,
            "options": {
                "temperature": settings.temperature,
                "top_p": 0.9,
                "num_ctx": settings.num_ctx,
                "num_predict": settings.num_predict,
            },
        },
        _timeout=settings.request_timeout_seconds,
        _cached_answer=cached_answer,
        _cache_key=cache_key,
        _cache_settings=cache_settings,
    )
