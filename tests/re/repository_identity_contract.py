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
        if (author_name, author_email) not in APPROVED_AUTHORS:
            violations.append(
                f"{commit}: unapproved author {author_name} <{author_email}>"
            )
        if (committer_name, committer_email) not in APPROVED_COMMITTERS:
            violations.append(
                f"{commit}: unapproved committer {committer_name} <{committer_email}>"
            )

    assert not violations, "\n".join(violations)
    return "all reachable commits use approved Solomon Dark project identities"

