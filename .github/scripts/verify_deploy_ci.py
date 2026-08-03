#!/usr/bin/env python3
"""Verify required CI workflows succeeded for the commit being deployed."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


REQUIRED_WORKFLOWS = (
    "quality.yml",
    "security.yml",
    "postgres-integration.yml",
)


def github_api(path: str, token: str) -> dict:
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"GitHub API request failed for {path}: {exc.code} {message}") from exc


def latest_run_for_sha(repo: str, workflow: str, sha: str, token: str) -> dict | None:
    data = github_api(
        f"/repos/{repo}/actions/workflows/{workflow}/runs?head_sha={sha}&per_page=20",
        token,
    )
    runs = data.get("workflow_runs", [])
    if not isinstance(runs, list):
        raise SystemExit(f"unexpected GitHub API response for workflow {workflow}")
    return runs[0] if runs else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub repository, for example owner/name")
    parser.add_argument("--sha", required=True, help="Commit SHA to deploy")
    parser.add_argument(
        "--workflow",
        action="append",
        default=[],
        help="Required workflow filename. Defaults to the repository deployment gate.",
    )
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required to verify CI workflow results")

    required = tuple(args.workflow) if args.workflow else REQUIRED_WORKFLOWS
    failures: list[str] = []

    for workflow in required:
        run = latest_run_for_sha(args.repo, workflow, args.sha, token)
        if run is None:
            failures.append(f"{workflow}: no run found for {args.sha}")
            continue

        status = run.get("status")
        conclusion = run.get("conclusion")
        html_url = run.get("html_url", "")
        if status != "completed" or conclusion != "success":
            failures.append(
                f"{workflow}: status={status!r} conclusion={conclusion!r} url={html_url}"
            )
            continue

        print(f"CI gate ok: {workflow} completed successfully for {args.sha}")

    if failures:
        print("Deployment blocked because required CI is not green for this commit:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
