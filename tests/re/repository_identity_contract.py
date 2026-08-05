#!/usr/bin/env python3
"""Regression contract for identities reachable from repository refs."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APPROVED_AUTHORS = {
    ("JarrettOneSource", "110432442+JarrettOneSource@users.noreply.github.com"),
    ("JarrettOneSource", "j.johnson@youronesourcesolution.com"),
}
APPROVED_COMMITTERS = APPROVED_AUTHORS | {
    ("GitHub", "noreply@github.com"),
}
# Already-published main history is waived by immutable commit, never by identity.
HISTORICAL_IDENTITY_EXCEPTIONS = {
    "4fe7a8539b98357fd22d54a888dbbf2102092a85": (
        "Claude ATC",
        "j.johnson@yossplatform.com",
    ),
    "9adeb266e141a50b850668bba2c6b5cf7ecd529c": (
        "Claude ATC",
        "j.johnson@yossplatform.com",
    ),
    "266ae9bda8b41ccce6a32ce8f82c99f49e4c0cbe": (
        "Jarrett Johnson",
        "j.johnson@yossplatform.com",
    ),
}


def test_repository_history_uses_approved_identities() -> str:
    result = subprocess.run(
        [
            "git",
            "log",
            "--all",
            "--format=%H%x09%an%x09%ae%x09%cn%x09%ce",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    violations: list[str] = []
    for row in result.stdout.splitlines():
        commit, author_name, author_email, committer_name, committer_email = (
            row.split("\t", 4)
        )
        author = (author_name, author_email)
        if (
            author not in APPROVED_AUTHORS
            and HISTORICAL_IDENTITY_EXCEPTIONS.get(commit) != author
        ):
            violations.append(
                f"{commit}: unapproved author {author_name} <{author_email}>"
            )
        committer = (committer_name, committer_email)
        if (
            committer not in APPROVED_COMMITTERS
            and HISTORICAL_IDENTITY_EXCEPTIONS.get(commit) != committer
        ):
            violations.append(
                f"{commit}: unapproved committer {committer_name} <{committer_email}>"
            )

    assert not violations, "\n".join(violations)
    return "all reachable commits use approved Solomon Dark project identities"

