import re


BENCHMARK_SUFFIX = re.compile(
    r"\s*\[benchmark [a-z0-9]+(?:-[a-z0-9]+)*\]\s*$",
    re.IGNORECASE,
)
APOSTROPHE_TRANSLATION = str.maketrans({"’": "'", "ʼ": "'"})


def canonicalize_question(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).translate(APOSTROPHE_TRANSLATION).lower()


def is_benchmark_question(value: str) -> bool:
    return BENCHMARK_SUFFIX.search(value) is not None
