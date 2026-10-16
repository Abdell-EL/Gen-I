"""Load the decision-table extract (produced by
excel-sources/extract_decision_tables.py on the host, since openpyxl isn't
available in this container) into Postgres.

Run inside the api container, after copying the JSON in:
  docker cp excel-sources/decision_tables_extract.json lab_api:/app/data/decision_tables_extract.json
  docker exec -w /app -e PYTHONPATH=/app lab_api python scripts/load_decision_tables.py

Idempotent: replaces all rows for a table (matched by name) on each run.
"""
from __future__ import annotations

import json

from app.database import SessionLocal
from app.models import DecisionTable, DecisionTableRow, KBArticleTable

EXTRACT_FILE = "data/decision_tables_extract.json"


def load_table(session, entry: dict) -> DecisionTable:
    table = session.query(DecisionTable).filter_by(name=entry["name"]).one_or_none()
    if table is None:
        table = DecisionTable(name=entry["name"])
        session.add(table)

    table.source_sheet = entry["source_sheet"]
    table.source_type = entry["source_type"]
    table.key_schema = entry["key_schema"]
    table.value_schema = entry["value_schema"]
    table.description = entry["description"]
    table.row_count_expected = len(entry["rows"])
    session.flush()

    session.query(DecisionTableRow).filter_by(table_id=table.table_id).delete()
    for row in entry["rows"]:
        session.add(DecisionTableRow(
            table_id=table.table_id,
            key_columns=row["key"],
            value_columns=row["value"],
        ))

    for kb_code in entry.get("kb_codes", []):
        exists = session.query(KBArticleTable).filter_by(
            kb_code=kb_code, table_id=table.table_id,
        ).one_or_none()
        if exists is None:
            session.add(KBArticleTable(kb_code=kb_code, table_id=table.table_id))

    return table


def main() -> None:
    with open(EXTRACT_FILE, encoding="utf-8") as f:
        entries = json.load(f)

    session = SessionLocal()
    try:
        for entry in entries:
            table = load_table(session, entry)
            session.flush()
            print(f"  {table.name!r}: {len(entry['rows'])} rows, "
                  f"linked to {entry.get('kb_codes', [])}")
        session.commit()

        print()
        print(f"Loaded {len(entries)} decision tables.")
        print(f"Total rows: {session.query(DecisionTableRow).count()}")
        print(f"Total article links: {session.query(KBArticleTable).count()}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
