import json
import re
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_PATH = BASE_DIR / "data" / "processed" / "articles.json"
OUTPUT_PATH = BASE_DIR / "data" / "processed" / "chunks.json"

SECTION_PATTERNS = {
    "metadata": ["métadonnées", "metadata"],
    "business_summary": ["résumé métier", "objectif de l'article", "réponse courte"],
    "main_knowledge": ["connaissance principale"],
    "key_points": ["points clés", "point clé"],
    "questions": [
        "questions auxquelles cet article répond",
        "questions principales",
        "questions formulées naturellement",
    ],
    "scope": ["périmètre d'application", "cas couverts", "cas non couverts"],
    "definitions": ["définitions", "vocabulaire standard", "glossaire"],
    "procedure": [
        "contenu opérationnel principal",
        "procédure",
        "procédure générale",
        "mode opératoire",
    ],
    "rules": ["règles métier", "règles d'utilisation", "règles explicites"],
    "warnings": ["points de vigilance", "validations nécessaires"],
    "visual_description": ["description textuelle des éléments visuels", "description des éléments visuels"],
    "faq": ["faq", "faq opérationnelle"],
    "migration_notes": ["notes de transformation", "notes de migration"],
    "history": ["historique des versions", "historique"],
}

SECTION_PRIORITY = {
    "rules": "critical",
    "procedure": "high",
    "key_points": "high",
    "faq": "high",
    "business_summary": "medium",
    "questions": "medium",
    "definitions": "medium",
    "main_knowledge": "medium",
    "scope": "low",
    "warnings": "medium",
    "visual_description": "low",
    "migration_notes": "low",
    "metadata": "low",
    "history": "low",
    "generic": "medium",
}

CATEGORY_PATTERNS = [
    r"^acc[eè]s\s*[–-]",
    r"^service\s*[–-]",
    r"^production\s*[–-]",
    r"^sav\s*[–-]",
    r"^cuivre\s*[–-]",
    r"^ftth\s*[–-]",
]

CASE_STARTERS = [
    "rv ",
    "rendez-vous",
    "vérification",
    "refus",
    "processus",
    "saturation",
    "absence",
    "pb ",
    "pm ",
    "gc ",
    "impossibilité",
    "ressource",
    "elagage",
    "élagage",
    "lien ",
    "affaiblissement",
    "poteau",
    "problème",
    "autorisation",
    "annulation",
    "client ",
    "demande",
    "conduite",
    "passage",
    "percement",
    "présence",
    "localisation",
    "déplacer",
    "la commande",
    "report",
    "mise ",
    "carte",
    "l'accès",
    "en cas",
    "si l'",
    "si le",
    "les données",
    "lors d",
    "variante",
    "serrure",
    "câble",
    "boîtier",
    "bpe ",
    "pto ",
    "pbo ",
    "nro ",
    "armoire",
    "infrastructure",
    "ligne ",
    "accès ",
    "intervention",
    "technicien",
    "clôture",
    "appel",
    "signalement",
]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def clean_heading(line: str) -> str:
    line = line.strip()
    line = re.sub(r"^\d+(\.\d+)*\s*[-–.]?\s*", "", line)
    return line.strip()


def detect_section_type(line: str) -> str | None:
    cleaned = normalize_text(clean_heading(line))

    if len(cleaned.split()) > 10:
        return None

    for section_type, patterns in SECTION_PATTERNS.items():
        for pattern in patterns:
            if pattern in cleaned:
                return section_type

    return None


def split_sections(text: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current_type = "generic"
    current_title = "Global"
    buffer: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        detected_type = detect_section_type(line)

        if detected_type:
            if buffer:
                sections.append({
                    "section_type": current_type,
                    "section_title": current_title,
                    "text": "\n".join(buffer).strip(),
                })
                buffer = []

            current_type = detected_type
            current_title = clean_heading(line)
        else:
            buffer.append(line)

    if buffer:
        sections.append({
            "section_type": current_type,
            "section_title": current_title,
            "text": "\n".join(buffer).strip(),
        })

    return sections


def is_category_heading(line: str) -> bool:
    normalized = normalize_text(line)

    if len(normalized.split()) > 12:
        return False

    return any(re.search(pattern, normalized) for pattern in CATEGORY_PATTERNS)


def is_detail_line(line: str) -> bool:
    normalized = normalize_text(line)

    field_patterns = [
        r"\bcode\s+gem\s*:",
        r"\bcode\s+situation\s*:",
        r"\bretail\b[^:;]{0,80}\s*:",
        r"\bwholesale\b[^:;]{0,80}\s*:",
        r"\bgard[ée]\s+en\s+main\b[^:;]{0,80}\s*:",
        r"\blibell[ée]\s*:",
        r"\bd[ée]lai\s*:",
        r"\bservice\s+[àa]\s+informer(?:\s+[àa]\s+chaud)?\s*:",
        r"^source\s*:",
        r"^version\s*:",
        r"^tags\s*:",
        r"^kb-id\s*:",
        r"^titre\s*:",
    ]

    return any(re.search(pattern, normalized) for pattern in field_patterns)


def is_general_procedure_line(line: str) -> bool:
    normalized = normalize_text(line)
    procedure_verbs = [
        "identifier ",
        "lire ",
        "appliquer ",
        "associer ",
        "annoncer ",
        "informer ",
        "sécuriser ",
        "demander ",
        "ne pas inventer",
    ]
    return any(normalized.startswith(v) for v in procedure_verbs)


def is_business_case_title(line: str, next_line: str | None = None) -> bool:
    stripped = line.strip()
    if not stripped:
        return False

    normalized = normalize_text(stripped)

    if is_category_heading(stripped):
        return False

    if is_general_procedure_line(stripped):
        return False

    if is_detail_line(stripped):
        return False

    if re.match(r"^\d+\.", stripped):
        return False

    word_count = len(normalized.split())

    if word_count < 2 or word_count > 28:
        return False

    starts_like_case = any(normalized.startswith(prefix) for prefix in CASE_STARTERS)
    next_is_detail = bool(next_line and is_detail_line(next_line))

    if starts_like_case:
        return True

    if next_is_detail and word_count <= 28:
        return True

    return False


def _is_title_only_chunk(case_lines: list[str]) -> bool:
    non_header = [
        line for line in case_lines
        if not line.startswith("Catégorie:") and not line.startswith("Cas:")
    ]
    has_details = any(is_detail_line(line) for line in non_header)
    return not has_details and len(non_header) < 3


def split_business_cases(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    chunks: list[str] = []

    current_category = ""
    general_intro: list[str] = []
    current_case: list[str] = []

    def flush_case() -> None:
        nonlocal current_case
        if not current_case:
            return

        if not _is_title_only_chunk(current_case):
            text_case = "\n".join(current_case).strip()
            chunks.append(text_case)

        current_case = []

    i = 0
    while i < len(lines):
        line = lines[i]
        next_line = lines[i + 1] if i + 1 < len(lines) else None

        if is_category_heading(line):
            flush_case()
            current_category = line
            i += 1
            continue

        if is_business_case_title(line, next_line):
            flush_case()
            prefix = f"Catégorie: {current_category}\n" if current_category else ""
            current_case = [f"{prefix}Cas: {line}"]
            i += 1
            continue

        if current_case:
            current_case.append(line)
        else:
            general_intro.append(line)

        i += 1

    flush_case()

    clean_intro = []
    for line in general_intro:
        if is_category_heading(line):
            continue
        if is_business_case_title(line):
            continue
        if is_detail_line(line):
            continue
        clean_intro.append(line)

    if clean_intro:
        intro_text = "\n".join(clean_intro).strip()
        if len(intro_text.split()) >= 8:
            chunks.insert(0, intro_text)

    cleaned_chunks = []
    for chunk in chunks:
        cleaned_chunks.extend(split_embedded_cases(chunk))

    return cleaned_chunks


def _current_has_case_header(current: list[str]) -> bool:
    return any(line.startswith("Cas:") for line in current)


def split_embedded_cases(chunk: str) -> list[str]:
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]

    if len(lines) <= 4:
        return [chunk]

    result: list[str] = []
    current: list[str] = []
    current_category = ""

    for idx, line in enumerate(lines):
        if line.startswith("Catégorie:"):
            current_category = line.replace("Catégorie:", "").strip()
            if current:
                result.append("\n".join(current).strip())
                current = []
            continue

        if line.startswith("Cas:"):
            if current:
                result.append("\n".join(current).strip())
            prefix = f"Catégorie: {current_category}\n" if current_category else ""
            current = [prefix + line]
            continue

        next_line = lines[idx + 1] if idx + 1 < len(lines) else None
        next_is_detail = bool(next_line and is_detail_line(next_line))
        current_has_details = any(is_detail_line(item) for item in current)
        already_in_case = _current_has_case_header(current)
        looks_like_title = is_business_case_title(line, next_line)
        starts_like_case = any(normalize_text(line).startswith(prefix) for prefix in CASE_STARTERS)

        should_split = (
            looks_like_title and (
                current_has_details
                or (already_in_case and starts_like_case)
                or (already_in_case and next_is_detail)
            )
        )

        if should_split:
            result.append("\n".join(current).strip())
            prefix = f"Catégorie: {current_category}\n" if current_category else ""
            current = [prefix + f"Cas: {line}"]
        else:
            current.append(line)

    if current:
        result.append("\n".join(current).strip())

    return [item for item in result if len(item.split()) >= 4]


def split_rules(text: str) -> list[str]:
    rules = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if re.search(r"^(si|lorsque|quand)\b", line, re.IGNORECASE):
            rules.append(line)
        elif re.search(r"\b(alors|=>)\b", line, re.IGNORECASE):
            rules.append(line)
        elif len(line.split()) >= 12:
            rules.append(line)

    return rules


def split_faq(text: str) -> list[str]:
    chunks = []
    current_q = None
    current_a: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.endswith("?"):
            if current_q:
                answer = " ".join(current_a).strip()
                chunks.append(f"Question: {current_q}\nRéponse: {answer}" if answer else f"Question: {current_q}")
                current_a = []
            current_q = line
        else:
            current_a.append(line)

    if current_q:
        answer = " ".join(current_a).strip()
        chunks.append(f"Question: {current_q}\nRéponse: {answer}" if answer else f"Question: {current_q}")

    return chunks


def split_questions(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().endswith("?") and len(line.strip().split()) >= 3
    ]


def split_key_points(text: str, max_words: int = 120) -> list[str]:
    chunks = []
    buffer = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        buffer.append(line)

        if len(" ".join(buffer).split()) >= max_words:
            chunks.append(" ".join(buffer))
            buffer = []

    if buffer:
        chunks.append(" ".join(buffer))

    return chunks


def chunk_by_size(text: str, max_words: int = 220, overlap: int = 35) -> list[str]:
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0

    while start < len(words):
        end = min(start + max_words, len(words))
        chunks.append(" ".join(words[start:end]))

        if end == len(words):
            break

        start += max_words - overlap

    return chunks


def should_skip_section(section: dict[str, str]) -> bool:
    title = normalize_text(section.get("section_title", ""))
    text = normalize_text(section.get("text", ""))

    skip_markers = [
        "tableau de référence consolidé",
        "historique des versions",
    ]

    return any(marker in title or marker in text[:200] for marker in skip_markers)


def get_article_kb_code(article: dict[str, Any]) -> str:
    """
    Supports both the old ingest format:
        article["kb_id"]

    and the new ERD-aligned ingest format:
        article["kb_code"]
    """
    kb_code = article.get("kb_code") or article.get("kb_id")

    if not kb_code:
        raise ValueError(f"Missing kb_code/kb_id for article: {article.get('file_name', 'unknown file')}")

    return str(kb_code)


def make_chunk(
    article: dict[str, Any],
    section: dict[str, str],
    text: str,
    chunk_type: str,
    index: int,
) -> dict[str, Any]:
    section_type = section["section_type"]
    kb_code = get_article_kb_code(article)

    return {
        # External/stable ID used before DB insertion.
        # The real DB chunk_id will be generated later by PostgreSQL.
        "external_chunk_id": f"{kb_code}::{index:04d}",

        # ERD-aligned identifiers.
        # kb_code is mapped later to knowledge_bases.kb_id.
        "kb_code": kb_code,

        # Source document metadata.
        "article_title": article["title"],
        "file_name": article["file_name"],
        "file_type": article.get("file_type"),
        "source_path": article.get("source_path"),
        "checksum": article.get("checksum"),

        # Chunk metadata.
        "section_title": section["section_title"],
        "section_type": section_type,
        "chunk_type": chunk_type,
        "priority": SECTION_PRIORITY.get(section_type, "medium"),
        "text": text.strip(),
        "word_count": len(text.split()),

        # This maps directly to chunks.metadata_json later.
    "metadata": {
         "extracted_at": article.get("extracted_at"),
         "paragraph_count": article.get("stats", {}).get("paragraph_count"),
         "original_metadata": article.get("metadata", {}),
},
    }


def smart_chunk_article(article: dict[str, Any]) -> list[dict[str, Any]]:
    sections = split_sections(article["content"])
    chunks: list[dict[str, Any]] = []
    counter = 1

    for section in sections:
        text = section["text"].strip()
        section_type = section["section_type"]

        if not text:
            continue

        if should_skip_section(section):
            continue

        if section_type == "rules":
            pieces = split_rules(text)
            chunk_type = "rule"
        elif section_type == "faq":
            pieces = split_faq(text)
            chunk_type = "faq"
        elif section_type == "questions":
            pieces = split_questions(text)
            chunk_type = "question"
        elif section_type == "key_points":
            pieces = split_key_points(text)
            chunk_type = "key_points"
        elif section_type == "procedure":
            pieces = split_business_cases(text)
            chunk_type = "business_case"
        else:
            pieces = chunk_by_size(text)
            chunk_type = "generic"

        for piece in pieces:
            if len(piece.split()) < 4:
                continue

            chunks.append(make_chunk(article, section, piece, chunk_type, counter))
            counter += 1

    return chunks


def main() -> None:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"Missing input file: {INPUT_PATH}")

    with open(INPUT_PATH, "r", encoding="utf-8") as file:
        articles = json.load(file)

    all_chunks = []

    for article in articles:
        article_chunks = smart_chunk_article(article)
        all_chunks.extend(article_chunks)

        kb_code = get_article_kb_code(article)
        print(f"{kb_code} | {len(article_chunks)} chunks")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as file:
        json.dump(all_chunks, file, ensure_ascii=False, indent=2)

    print("\nDone.")
    print(f"Articles processed: {len(articles)}")
    print(f"Chunks created: {len(all_chunks)}")
    print(f"Output saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()