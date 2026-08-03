#!/usr/bin/env python3
"""Validate Alembic config loads and the repository has a single linear head."""

from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory


def main() -> int:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    bases = script.get_bases()
    revisions = list(script.walk_revisions())

    if len(heads) != 1:
        print(f"expected one Alembic head, found {heads}")
        return 1
    if len(bases) != 1:
        print(f"expected one Alembic base, found {bases}")
        return 1

    seen = set()
    for revision in revisions:
        if revision.revision in seen:
            print(f"duplicate Alembic revision: {revision.revision}")
            return 1
        seen.add(revision.revision)

    print(f"alembic chain ok: base={bases[0]} head={heads[0]} revisions={len(revisions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
