#!/usr/bin/env python3
"""Tests for exact-process cleanup in local multiplayer verifiers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_local_multiplayer_sync as verifier  # noqa: E402


class LocalMultiplayerProcessIsolationTests(unittest.TestCase):
    def test_exact_mod_ids_serialize_in_declared_order(self) -> None:
        self.assertEqual(
            verifier._serialize_exact_mod_ids(
                exact_mod_id=None,
                exact_mod_ids=("sample.provider", "sample.consumer"),
            ),
            "sample.provider,sample.consumer",
        )
        self.assertEqual(
            verifier._serialize_exact_mod_ids(
                exact_mod_id="sample.single",
                exact_mod_ids=None,
            ),
            "sample.single",
        )

    def test_exact_mod_ids_reject_ambiguous_or_invalid_sets(self) -> None:
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            verifier._serialize_exact_mod_ids(
                exact_mod_id="sample.single",
                exact_mod_ids=("sample.other",),
            )
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            verifier._serialize_exact_mod_ids(
                exact_mod_id=None,
                exact_mod_ids=(),
            )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            verifier._serialize_exact_mod_ids(
                exact_mod_id=None,
                exact_mod_ids=("sample.duplicate", "sample.duplicate"),
            )
        with self.assertRaisesRegex(ValueError, "invalid exact mod id"):
            verifier._serialize_exact_mod_ids(
                exact_mod_id=None,
                exact_mod_ids=("sample.valid", "INVALID"),
            )

    def test_game_process_ids_accepts_only_positive_exact_ids(self) -> None:
        self.assertEqual(
            verifier.game_process_ids(
                {
                    "hostProcessId": 4312,
                    "clientProcessId": "4311",
                    "thirdProcessId": True,
                    "processId": -1,
                }
            ),
            [4311, 4312],
        )

    def test_empty_exact_cleanup_does_not_call_powershell(self) -> None:
        with mock.patch.object(verifier.subprocess, "run") as run:
            verifier.stop_game_processes([])

        run.assert_not_called()

    def test_exact_cleanup_never_uses_a_machine_wide_process_query(self) -> None:
        with mock.patch.object(verifier.subprocess, "run") as run:
            verifier.stop_game_processes([4312, 4311, 4312, -1, True])

        run.assert_called_once()
        command = run.call_args.args[0][-1]
        self.assertIn("$ids = @(4311,4312);", command)
        self.assertIn("Get-Process -Id $ids", command)
        self.assertIn("Where-Object", command)
        self.assertNotIn("Get-Process SolomonDark*", command)


if __name__ == "__main__":
    unittest.main()
