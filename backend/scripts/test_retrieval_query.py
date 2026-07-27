import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.retrieval_service import search_chunks


def print_results(query: str, results: list[dict]) -> None:
    print("=" * 100)
    print(f"QUERY: {query}")
    print("=" * 100)

    for result in results:
        print()
        print("-" * 100)
        print(f"Rank: {result['rank']}")
        print(f"Score: {result['score']}")
        print(f"ID: {result['id']}")
        print(f"KB Code: {result['kb_code']}")
        print(f"Article: {result['article_title']}")
        print(f"Section: {result['section_title']}")
        print(f"Type: {result['chunk_type']}")
        print(f"Priority: {result['priority']}")
        print()
        print(result["text"])


def main():
    query = "Quel code situation utiliser pour une demande d'autorisation voisinage ?"

    results = search_chunks(query=query, top_k=5)
    print_results(query, results)


if __name__ == "__main__":
    main()