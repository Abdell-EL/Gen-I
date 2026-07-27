import os
from typing import Any

import requests


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")


def build_context(retrieved_chunks: list[dict[str, Any]], max_chunks: int = 5) -> str:
    context_blocks = []

    for item in retrieved_chunks[:max_chunks]:
        source_id = item.get("id", "unknown")
        title = item.get("article_title", "")
        section = item.get("section_title", "")
        text = item.get("text", "")

        block = (
            f"Source ID: {source_id}\n"
            f"Article: {title}\n"
            f"Section: {section}\n"
            f"Contenu: {text}"
        )

        context_blocks.append(block)

    return "\n\n---\n\n".join(context_blocks)


def build_grounded_prompt(question: str, retrieved_chunks: list[dict[str, Any]]) -> str:
    context = build_context(retrieved_chunks)

    return f"""
Tu es un assistant interne pour la base de connaissance opérationnelle Sogetrel.

Ta mission :
- Répondre en français.
- Utiliser uniquement le CONTEXTE fourni.
- Ne pas inventer d'information.
- Si le contexte ne contient pas la réponse, dire clairement que l'information n'est pas présente dans les sources disponibles.
- Donner une réponse courte, claire et opérationnelle.
- Si une règle métier ou un code situation est présent, le mettre en évidence.
- Ne cite pas de source inexistante.

QUESTION UTILISATEUR :
{question}

CONTEXTE DISPONIBLE :
{context}

RÉPONSE :
""".strip()


def generate_answer_with_ollama(
    question: str,
    retrieved_chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt = build_grounded_prompt(
        question=question,
        retrieved_chunks=retrieved_chunks,
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "top_p": 0.9,
            "num_predict": 350,
        },
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=120,
    )

    response.raise_for_status()
    data = response.json()

    answer = data.get("response", "").strip()

    if not answer:
        answer = "Je n'ai pas pu générer une réponse à partir des sources disponibles."

    return {
        "answer": answer,
        "model": OLLAMA_MODEL,
        "prompt_tokens": data.get("prompt_eval_count"),
        "completion_tokens": data.get("eval_count"),
        "total_duration": data.get("total_duration"),
    }