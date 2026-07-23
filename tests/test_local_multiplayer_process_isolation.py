#!/usr/bin/env python3
"""Tests for exact-process cleanup in local multiplayer verifiers."""

from __future__ import annotations

import ast
import importlib
import inspect
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
    def test_all_lua_pair_verifiers_disable_tiling_and_preserve_games(
        self,
    ) -> None:
        verifier_paths = sorted(TOOLS_ROOT.glob("verify_lua_*.py"))
        launch_call_count = 0
        for path in verifier_paths:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, path.name)
            launch_calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "launch_pair"
            ]
            launch_call_count += len(launch_calls)
            if launch_calls:
                with self.subTest(verifier=path.name, invariant="ledger"):
                    self.assertIn("two exact process IDs", source)
            for call in launch_calls:
                keywords = {
                    keyword.arg: keyword.value
                    for keyword in call.keywords
                    if keyword.arg is not None
                }
                with self.subTest(verifier=path.name, line=call.lineno):
                    for keyword_name in ("tile_windows", "kill_existing"):
                        value = keywords.get(keyword_name)
                        self.assertIsInstance(
                            value,
                            ast.Constant,
                            f"{keyword_name} must be an explicit false literal",
                        )
                        self.assertIs(
                            value.value,
                            False,
                            f"{keyword_name} must be false",
                        )

        self.assertGreater(launch_call_count, 0)

    def test_incomplete_lua_pair_ledgers_stop_only_owned_processes(
        self,
    ) -> None:
        module_names = (
            "verify_lua_ai_multiplayer",
            "verify_lua_enemies_multiplayer",
            "verify_lua_items_multiplayer",
            "verify_lua_mod_replication",
            "verify_lua_net_multiplayer",
            "verify_lua_runtime_contract",
            "verify_lua_spells_multiplayer",
            "verify_lua_time_multiplayer",
            "verify_lua_ui_multiplayer",
        )
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        for module_name in module_names:
            module = importlib.import_module(module_name)
            parameters = inspect.signature(module.run).parameters
            arguments: dict[str, object] = {"launch": True}
            if "timeout" in parameters:
                arguments["timeout"] = 1.0
            with (
                self.subTest(verifier=module_name),
                mock.patch.object(
                    module,
                    "launch_pair",
                    return_value={"hostProcessId": 61},
                ),
                mock.patch.object(module, "disable_bots") as disable_bots,
                mock.patch.object(module, "wait_for_remote") as wait_remote,
                mock.patch.object(module, "stop_game_processes") as stop,
                self.assertRaisesRegex(
                    RuntimeError,
                    "two exact process IDs",
                ),
            ):
                module.run(clients, **arguments)

            disable_bots.assert_not_called()
            wait_remote.assert_not_called()
            stop.assert_called_once_with([61])

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
