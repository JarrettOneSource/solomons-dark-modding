#!/usr/bin/env python3
"""Regression coverage for original-game lookup from isolated worktrees."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RE_TESTS = ROOT / "tests" / "re"
if str(RE_TESTS) not in sys.path:
    sys.path.insert(0, str(RE_TESTS))

from static_re_contract_support import resolve_workspace_root


class StaticReWorktreePathTests(unittest.TestCase):
    def test_linked_worktree_resolves_the_main_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "Solomon Dark"
            main_repo = workspace / "Mod Loader"
            worktree = Path(directory) / "isolated" / "netcode"
            git_directory = (
                main_repo / ".git" / "worktrees" / "netcode"
            )
            worktree.mkdir(parents=True)
            (worktree / ".git").write_text(
                f"gitdir: {git_directory}\n",
                encoding="utf-8",
            )

            self.assertEqual(
                resolve_workspace_root(worktree),
                workspace,
            )

    def test_main_checkout_uses_its_parent_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "Solomon Dark" / "Mod Loader"
            (repo / ".git").mkdir(parents=True)

            self.assertEqual(
                resolve_workspace_root(repo),
                repo.parent,
            )


if __name__ == "__main__":
    unittest.main()
