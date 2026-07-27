from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests


DEFAULT_URL = "http://127.0.0.1:8000/api/v1/admin/ingestion/docx"
DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Post one DOCX file to the admin KB ingestion endpoint."
    )
    parser.add_argument("path", type=Path, help="Path to a standardized DOCX article.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Ingestion endpoint URL.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = args.path

    if not path.exists():
        raise FileNotFoundError(path)

    with path.open("rb") as handle:
        response = requests.post(
            args.url,
            files={"file": (path.name, handle, DOCX_MIME_TYPE)},
            timeout=300,
        )

    print(f"HTTP {response.status_code}")

    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except ValueError:
        print(response.text)


if __name__ == "__main__":
    main()
