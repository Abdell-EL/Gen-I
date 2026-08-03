#!/usr/bin/env python3
"""Apply the repository npm audit policy to JSON audit output."""

from __future__ import annotations

import datetime as dt
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BLOCKING_SEVERITIES = {"high", "critical"}
TODAY = dt.date.today()


@dataclass(frozen=True)
class TemporaryException:
    advisory_id: str
    primary_package: str
    transitive_package: str
    expires_on: dt.date
    owner: str
    rationale: str


REACT_ROUTER_RSC_EXCEPTION = TemporaryException(
    advisory_id="GHSA-qwww-vcr4-c8h2",
    primary_package="react-router",
    transitive_package="react-router-dom",
    expires_on=dt.date(2026, 8, 17),
    owner="Phase 6A security owner",
    rationale=(
        "Client-rendered Vite SPA does not use React Server Components, "
        "RSC server actions, or unstable RSC APIs; remediation target is a "
        "tested compatible patched React Router release, not npm audit fix --force."
    ),
)


def _load_report(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as error:
        raise RuntimeError(f"npm audit report not found: {path}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"npm audit report is not valid JSON: {error}") from error


def _via_advisory_ids(vulnerability: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in vulnerability.get("via", []):
        if isinstance(item, str):
            ids.add(item)
            continue
        if not isinstance(item, dict):
            continue
        for key in ("id", "source"):
            value = item.get(key)
            if value is not None:
                ids.add(str(value))
        url = str(item.get("url", ""))
        if "/GHSA-" in url:
            ids.add(url.rsplit("/", 1)[-1])
        title = str(item.get("title", ""))
        for part in title.split():
            if part.startswith("GHSA-"):
                ids.add(part.rstrip(".,;:"))
    return ids


def _is_exception_active(exception: TemporaryException) -> bool:
    return TODAY <= exception.expires_on


def _is_allowed_react_router_exception(
    name: str,
    vulnerability: dict[str, Any],
    vulnerabilities: dict[str, Any],
) -> bool:
    exception = REACT_ROUTER_RSC_EXCEPTION
    if not _is_exception_active(exception):
        return False

    if name == exception.primary_package:
        return exception.advisory_id in _via_advisory_ids(vulnerability)

    if name == exception.transitive_package:
        via = vulnerability.get("via", [])
        if via != [exception.primary_package]:
            return False
        primary = vulnerabilities.get(exception.primary_package, {})
        return exception.advisory_id in _via_advisory_ids(primary)

    return False


def _blocking_vulnerabilities(report: dict[str, Any]) -> tuple[list[str], list[str]]:
    vulnerabilities = report.get("vulnerabilities", {})
    if not isinstance(vulnerabilities, dict):
        raise RuntimeError("npm audit report has no vulnerabilities object")

    failures: list[str] = []
    accepted: list[str] = []
    for name, vulnerability in sorted(vulnerabilities.items()):
        if not isinstance(vulnerability, dict):
            continue
        severity = str(vulnerability.get("severity", "")).lower()
        if severity not in BLOCKING_SEVERITIES:
            continue
        if _is_allowed_react_router_exception(name, vulnerability, vulnerabilities):
            accepted.append(
                f"{name}: {severity} {REACT_ROUTER_RSC_EXCEPTION.advisory_id} "
                f"temporarily accepted until {REACT_ROUTER_RSC_EXCEPTION.expires_on.isoformat()}"
            )
            continue
        advisory_ids = ",".join(sorted(_via_advisory_ids(vulnerability))) or "unknown-advisory"
        failures.append(f"{name}: severity={severity} advisories={advisory_ids}")
    return failures, accepted


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: npm_audit_policy.py <npm-audit.json>", file=sys.stderr)
        return 2

    try:
        report = _load_report(Path(argv[1]))
        failures, accepted = _blocking_vulnerabilities(report)
    except RuntimeError as error:
        print(f"npm audit policy failed: {error}", file=sys.stderr)
        return 1

    for item in accepted:
        print(f"accepted temporary npm audit exception: {item}")
    if not _is_exception_active(REACT_ROUTER_RSC_EXCEPTION):
        print(
            "temporary npm audit exception expired: "
            f"{REACT_ROUTER_RSC_EXCEPTION.advisory_id} expired on "
            f"{REACT_ROUTER_RSC_EXCEPTION.expires_on.isoformat()}",
            file=sys.stderr,
        )

    if failures:
        print("blocking npm audit vulnerabilities:", file=sys.stderr)
        for item in failures:
            print(f"- {item}", file=sys.stderr)
        return 1

    print("npm audit policy ok: no unaccepted high/critical vulnerabilities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
