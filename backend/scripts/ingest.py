from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


ARTICLES_DIR = Path("data/KB_Articles")
OUTPUT_DIR = Path("data/processed")
OUTPUT_FILE = OUTPUT_DIR / "articles.json"
MANIFEST_FILE = OUTPUT_DIR / "ingestion_manifest.json"


SECTION_RE = re.compile(r"^(\d+(?:\.\d+)*)\.\s+(.+)$")
KB_ID_RE = re.compile(r"\bKB-ID\s*:\s*([A-Z0-9À-ÿ_-]+)", re.IGNORECASE)
VERSION_RE = re.compile(r"\bVersion\s*:\s*([^\n]+)", re.IGNORECASE)
TITLE_RE = re.compile(r"^(.*?)\s+[–-]\s+(.*)$")


@dataclass
class DocBlock:
    block_id: int
    block_type: str
    text: str
    section_number: str | None = None
    section_title: str | None = None
    table_index: int | None = None
    row_count: int | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_checksum(path: Path) -> str:
    sha256 = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            sha256.update(block)

    return sha256.hexdigest()


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def iter_docx_blocks(doc: DocxDocument) -> Iterable[Paragraph | Table]:
    body = doc.element.body

    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, doc)
        elif isinstance(child, CT_Tbl):
            yield Table(child, doc)


def extract_table_text(table: Table) -> tuple[str, int]:
    rows: list[str] = []

    for row in table.rows:
        cells = [clean_text(cell.text.replace("\n", " ")) for cell in row.cells]

        # Remove duplicate merged-cell values inside the same row while preserving order.
        deduped_cells: list[str] = []
        for cell in cells:
            if cell and cell not in deduped_cells:
                deduped_cells.append(cell)

        if deduped_cells:
            rows.append(" | ".join(deduped_cells))

    return "\n".join(rows), len(rows)


def parse_section(text: str) -> tuple[str | None, str | None]:
    match = SECTION_RE.match(text)

    if not match:
        return None, None

    return match.group(1), match.group(2).strip()


def extract_docx_blocks(path: Path) -> list[DocBlock]:
    doc = Document(path)
    blocks: list[DocBlock] = []

    current_section_number: str | None = None
    current_section_title: str | None = None
    table_index = 0

    for raw_block in iter_docx_blocks(doc):
        if isinstance(raw_block, Paragraph):
            text = clean_text(raw_block.text)

            if not text:
                continue

            section_number, section_title = parse_section(text)
            if section_number:
                current_section_number = section_number
                current_section_title = section_title

            blocks.append(
                DocBlock(
                    block_id=len(blocks),
                    block_type="paragraph",
                    text=text,
                    section_number=current_section_number,
                    section_title=current_section_title,
                )
            )

        elif isinstance(raw_block, Table):
            table_text, row_count = extract_table_text(raw_block)

            if not table_text:
                continue

            table_index += 1

            blocks.append(
                DocBlock(
                    block_id=len(blocks),
                    block_type="table",
                    text=table_text,
                    section_number=current_section_number,
                    section_title=current_section_title,
                    table_index=table_index,
                    row_count=row_count,
                )
            )

    return blocks


def extract_kb_code(path: Path, content: str) -> str:
    match = KB_ID_RE.search(content)

    if match:
        return match.group(1).strip()

    return path.stem.split("_")[0].strip()


def extract_version(content: str) -> str | None:
    match = VERSION_RE.search(content)

    if not match:
        return None

    value = clean_text(match.group(1))

    # Avoid grabbing weird table/history version lines.
    return value.split()[0] if value else None


def extract_title(path: Path, blocks: list[DocBlock]) -> str:
    if not blocks:
        return path.stem

    first = blocks[0].text
    match = TITLE_RE.match(first)

    if match:
        return clean_text(match.group(2))

    return first


def build_article(path: Path) -> dict[str, Any]:
    blocks = extract_docx_blocks(path)
    content = "\n\n".join(block.text for block in blocks)

    kb_code = extract_kb_code(path, content)
    title = extract_title(path, blocks)
    version = extract_version(content)

    sections = []
    seen_sections = set()

    for block in blocks:
        if block.section_number and block.section_number not in seen_sections:
            seen_sections.add(block.section_number)
            sections.append(
                {
                    "section_number": block.section_number,
                    "section_title": block.section_title,
                }
            )

    return {
        "file_name": path.name,
        "file_type": "docx",
        "source_path": str(path),
        "kb_code": kb_code,
        "title": title,
        "version": version,
        "content": content,
        "blocks": [asdict(block) for block in blocks],
        "sections": sections,
        "stats": {
            "block_count": len(blocks),
            "paragraph_count": sum(1 for b in blocks if b.block_type == "paragraph"),
            "table_count": sum(1 for b in blocks if b.block_type == "table"),
            "character_count": len(content),
            "word_count": len(content.split()),
        },
        "checksum": file_checksum(path),
        "extracted_at": utc_now(),
        "metadata": {
            "original_stem": path.stem,
            "extension": path.suffix,
        },
    }


def validate_article(article: dict[str, Any]) -> list[str]:
    warnings: list[str] = []

    if not article["content"]:
        warnings.append("empty_content")

    if not article["kb_code"]:
        warnings.append("missing_kb_code")

    if not article["title"]:
        warnings.append("missing_title")

    if article["stats"]["table_count"] == 0:
        warnings.append("no_tables_detected")

    if article["stats"]["character_count"] < 500:
        warnings.append("very_short_article")

    return warnings


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not ARTICLES_DIR.exists():
        raise FileNotFoundError(f"Articles directory not found: {ARTICLES_DIR}")

    docx_files = sorted(
        file for file in ARTICLES_DIR.glob("*.docx") if not file.name.startswith("~$")
    )

    articles: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []

    for file in docx_files:
        try:
            article = build_article(file)
            warnings = validate_article(article)
            article["warnings"] = warnings

            articles.append(article)

            manifest.append(
                {
                    "file_name": article["file_name"],
                    "kb_code": article["kb_code"],
                    "title": article["title"],
                    "version": article["version"],
                    "checksum": article["checksum"],
                    "stats": article["stats"],
                    "warnings": warnings,
                    "status": "success",
                }
            )

            warning_text = f" | warnings: {', '.join(warnings)}" if warnings else ""
            print(
                f"✅ {article['kb_code']} | "
                f"{article['stats']['paragraph_count']} paragraphs | "
                f"{article['stats']['table_count']} tables"
                f"{warning_text}"
            )

        except Exception as exc:
            manifest.append(
                {
                    "file_name": file.name,
                    "status": "failed",
                    "error": repr(exc),
                }
            )
            print(f"❌ Failed to ingest {file.name}: {exc}")

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    with MANIFEST_FILE.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": utc_now(),
                "articles_dir": str(ARTICLES_DIR),
                "output_file": str(OUTPUT_FILE),
                "article_count": len(articles),
                "manifest": manifest,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"\nSaved {len(articles)} articles to {OUTPUT_FILE}")
    print(f"Saved manifest to {MANIFEST_FILE}")


if __name__ == "__main__":
    main()