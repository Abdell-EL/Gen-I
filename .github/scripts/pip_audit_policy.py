#!/usr/bin/env python3
"""Apply the repository pip-audit severity policy without printing secrets."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

FAIL_SCORE = 7.0
FAIL_WORDS = {"high", "critical"}


def _score(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_high_or_critical(vuln: dict[str, Any]) -> bool:
    severities = vuln.get("severity") or vuln.get("severities") or []
    if isinstance(severities, dict):
        severities = [severities]
    for item in severities:
        if not isinstance(item, dict):
            continue
        label = str(item.get("type") or item.get("level") or item.get("severity") or "").lower()
        if label in FAIL_WORDS:
            return True
        score = _score(item.get("score") or item.get("cvss_score"))
        if score is not None and score >= FAIL_SCORE:
            return True
    aliases = " ".join(str(alias) for alias in vuln.get("aliases", []))
    description = str(vuln.get("description", ""))[:500].lower()
    text = f"{aliases} {description}".lower()
    return "critical severity" in text or "high severity" in text


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: pip_audit_policy.py pip-audit.json", file=sys.stderr)
        return 2
    payload = json.loads(Path(argv[1]).read_text())
    dependencies = payload.get("dependencies", [])
    blocking: list[tuple[str, str]] = []
    informational = 0

    for dependency in dependencies:
        name = str(dependency.get("name") or "unknown")
        for vuln in dependency.get("vulns", []) or []:
            vuln_id = str(vuln.get("id") or "unknown")
            if _is_high_or_critical(vuln):
                blocking.append((name, vuln_id))
            else:
                informational += 1

    if blocking:
        print("pip-audit high/critical policy failed:", file=sys.stderr)
        for name, vuln_id in blocking:
            print(f"- {name}: {vuln_id}", file=sys.stderr)
        return 1

    print(f"pip-audit policy ok: high_critical=0 informational={informational}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
