#!/usr/bin/env python3
"""Tests for isolated-worktree native RE contract paths."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RE_TEST_ROOT = ROOT / "tests/re"
if str(RE_TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(RE_TEST_ROOT))

import static_re_contract_support as support  # noqa: E402


class StaticReContractSupportTests(unittest.TestCase):
    def test_linked_worktree_resolves_binary_beside_primary_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            workspace_root = temporary_root / "Solomon Dark"
            primary_checkout = workspace_root / "Mod Loader"
            common_git_dir = primary_checkout / ".git"
            linked_worktree = temporary_root / ".codex-worktrees/lobby-fix"
            linked_git_dir = common_git_dir / "worktrees/lobby-fix"
            linked_worktree.mkdir(parents=True)
            linked_git_dir.mkdir(parents=True)
            (linked_worktree / ".git").write_text(
                f"gitdir: {linked_git_dir}\n",
                encoding="utf-8",
            )
            game_root = workspace_root / "SolomonDarkAbandonware"
            game_root.mkdir()
            binary = game_root / "SolomonDark.exe"
            binary.write_bytes(b"fixture")

            resolved = support.resolve_abandonware_binary(
                root=linked_worktree,
                workspace_root=temporary_root / "unrelated-workspace",
                environment={},
            )

        self.assertEqual(resolved, binary)

    def test_staged_retail_path_resolves_outside_worktree_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            repo_root = temporary_root / "isolated-worktree"
            game_root = temporary_root / "retail-game"
            report = (
                repo_root
                / "runtime/stage/.sdmod/stage-report.json"
            )
            report.parent.mkdir(parents=True)
            game_root.mkdir()
            binary = game_root / "SolomonDark.exe"
            binary.write_bytes(b"fixture")
            report.write_text(
                json.dumps({"retailGamePath": str(game_root)}),
                encoding="utf-8",
            )

            resolved = support.resolve_abandonware_binary(
                root=repo_root,
                workspace_root=temporary_root / "unrelated-workspace",
                environment={},
            )

        self.assertEqual(resolved, binary)

    def test_game_directory_override_is_supported(self) -> None:
        game_root = Path("/tmp/solomon-test-game")

        resolved = support.resolve_abandonware_binary(
            root=Path("/tmp/isolated-worktree"),
            workspace_root=Path("/tmp/unrelated-workspace"),
            environment={"SD_RE_GAME_DIR": str(game_root)},
        )

        self.assertEqual(resolved, game_root / "SolomonDark.exe")


if __name__ == "__main__":
    unittest.main()
