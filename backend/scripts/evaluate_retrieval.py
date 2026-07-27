import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.answer_service import compose_answer
from app.services.retrieval_service import search_chunks


EVALUATION_CASES = [
    {
        "name": "Autorisation voisinage",
        "query": "Quel code situation utiliser pour une demande d'autorisation voisinage ?",
        "expected_terms": ["AV", "autorisation voisinage"],
    },
    {
        "name": "Problème de regard",
        "query": "Quel code situation utiliser pour un problème de regard ?",
        "expected_terms": ["DR", "regard"],
    },
    {
        "name": "Percement privatif",
        "query": "Quel code situation utiliser pour un percement privatif ?",
        "expected_terms": ["PP", "privative"],
    },
    {
        "name": "Localisation point de blocage",
        "query": "Quel code situation utiliser pour une localisation point de blocage ?",
        "expected_terms": ["LP", "blocage"],
    },
]


def flatten_result(answer_payload: dict[str, Any]) -> str:
    parts = [answer_payload.get("answer", "")]

    for source in answer_payload.get("sources", []):
        parts.append(str(source.get("id", "")))
        parts.append(str(source.get("kb_code", "")))
        parts.append(str(source.get("article_title", "")))
        parts.append(str(source.get("section_title", "")))
        parts.append(str(source.get("text", "")))

    return "\n".join(parts).lower()


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    query = case["query"]
    expected_terms = case["expected_terms"]

    retrieved_chunks = search_chunks(query=query, top_k=5)
    answer_payload = compose_answer(
        question=query,
        retrieved_chunks=retrieved_chunks,
    )

    combined_text = flatten_result(answer_payload)

    missing_terms = [
        term for term in expected_terms
        if term.lower() not in combined_text
    ]

    passed = len(missing_terms) == 0

    top_source = answer_payload["sources"][0] if answer_payload.get("sources") else {}

    return {
        "name": case["name"],
        "query": query,
        "passed": passed,
        "missing_terms": missing_terms,
        "answer": answer_payload.get("answer"),
        "confidence": answer_payload.get("confidence"),
        "top_id": top_source.get("id"),
        "top_score": top_source.get("score"),
        "top_text": top_source.get("text"),
    }


def main():
    print("=" * 100)
    print("SOGESTREL KB/FDE RETRIEVAL EVALUATION")
    print("=" * 100)

    results = []

    for case in EVALUATION_CASES:
        result = evaluate_case(case)
        results.append(result)

        status = "PASS" if result["passed"] else "FAIL"

        print()
        print("-" * 100)
        print(f"Case: {result['name']}")
        print(f"Status: {status}")
        print(f"Query: {result['query']}")
        print(f"Confidence: {result['confidence']}")
        print(f"Top ID: {result['top_id']}")
        print(f"Top Score: {result['top_score']}")
        print()
        print("Answer:")
        print(result["answer"])
        print()
        print("Top retrieved text:")
        print(result["top_text"])

        if result["missing_terms"]:
            print()
            print(f"Missing expected terms: {result['missing_terms']}")

    passed_count = sum(1 for result in results if result["passed"])
    total_count = len(results)

    print()
    print("=" * 100)
    print(f"SUMMARY: {passed_count}/{total_count} passed")
    print("=" * 100)

    if passed_count != total_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()