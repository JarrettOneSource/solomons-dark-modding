#!/usr/bin/env python3
"""Tests for the loopback mod-settings lifecycle verifier."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_mod_settings_lifecycle as verifier  # noqa: E402


class ModSettingsLifecycleVerifierTests(unittest.TestCase):
    def test_isolation_contract_is_fixed(self) -> None:
        self.assertEqual(verifier.INSTANCE_PREFIX, "mset")
        self.assertEqual(verifier.HOST_PORT, 49011)
        self.assertEqual(verifier.CLIENT_PORT, 49012)
        self.assertEqual(
            verifier.HOST_PIPE,
            "SolomonDarkModLoader_LuaExec_mset-host",
        )
        self.assertEqual(
            verifier.CLIENT_PIPE,
            "SolomonDarkModLoader_LuaExec_mset-client",
        )
        source = (TOOLS_ROOT / "verify_mod_settings_lifecycle.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("enable_audio=False", source)
        self.assertIn("kill_existing=False", source)
        self.assertIn("stop_exact_game_processes(launch)", source)
        self.assertNotIn("stop_game_processes(", source)
        self.assertNotIn("48911", source)
        self.assertNotIn("48912", source)

    def test_fixture_writer_uses_canonical_atomic_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            with mock.patch.object(verifier, "ROOT", temporary_root):
                path = verifier._atomic_write_settings(
                    "host",
                    {"kite_radius": 500},
                )
            self.assertEqual(
                path,
                temporary_root
                / "runtime"
                / "instances"
                / "mset-host"
                / "stage"
                / ".sdmod"
                / "mod-settings"
                / "bot.brain.json",
            )
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {
                    "schemaVersion": 1,
                    "values": {"kite_radius": 500},
                },
            )
            self.assertEqual(
                list(path.parent.glob("*.tmp")),
                [],
            )

    def test_initial_predicate_separates_host_and_local_scope(self) -> None:
        common = {
            "scene": "hub",
            "setting.kite_radius": "100",
            "setting.offense_enabled": "false",
            "setting.persona_name": "MsetBot",
            "brain.persona_name": "MsetBot",
            "brain.offense_enabled": "false",
            "brain.kite_radius": "100",
            "bot.count": "1",
            "bot.participant_id": "77",
            "bot.name": "MsetBot",
            "bot.controller": "LuaBrain",
        }
        views = {
            "host": {
                **common,
                "authority": "true",
                "setting.think_profile": "standard",
            },
            "client": {
                **common,
                "authority": "false",
                "setting.think_profile": "relaxed",
            },
        }
        self.assertTrue(verifier._initial_values_converged(views))
        views["client"]["setting.kite_radius"] = "700"
        self.assertFalse(verifier._initial_values_converged(views))

    def test_integer_parser_preserves_uint64_participant_ids(self) -> None:
        first = "1152921504606851072"
        second = "1152921504606851073"
        self.assertEqual(
            verifier._integer({"participant": first}, "participant"),
            int(first),
        )
        self.assertEqual(
            verifier._integer({"participant": second}, "participant"),
            int(second),
        )
        self.assertNotEqual(
            verifier._integer({"participant": first}, "participant"),
            verifier._integer({"participant": second}, "participant"),
        )

    def test_lifecycle_always_uses_exact_launch_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary)
            reloaded = evidence / "bot.brain.json"
            reloaded.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "values": {
                            "persona_name": verifier.RESTART_PERSONA
                        },
                    }
                ),
                encoding="utf-8",
            )
            initial = {"host": {}, "client": {}}
            before = {
                "brain.settings_change_count": "0",
                "bot.participant_id": "10",
                "brain.respawn_action_count": "0",
            }
            client_before = {"brain.settings_change_count": "1"}
            after = {
                "host": {
                    "setting.persona_name": verifier.INITIAL_PERSONA,
                    "brain.persona_name": verifier.INITIAL_PERSONA,
                    "bot.participant_id": "10",
                    "brain.respawn_action_count": "0",
                },
                "client": {
                    "setting.persona_name": verifier.INITIAL_PERSONA,
                    "bot.participant_id": "10",
                },
            }
            respawned = {
                "host": {"bot.participant_id": "11"},
                "client": {"bot.participant_id": "11"},
            }
            launch = {
                "audioDisabled": True,
                "hostPort": verifier.HOST_PORT,
                "clientPort": verifier.CLIENT_PORT,
                "hostProcessId": 101,
                "hostExecutablePath": "C:/stage/host/SolomonDark.exe",
                "clientProcessId": 102,
                "clientExecutablePath": "C:/stage/client/SolomonDark.exe",
            }
            with (
                mock.patch.object(
                    verifier,
                    "_seed_persisted_values",
                ),
                mock.patch.object(
                    verifier.local_sync,
                    "launch_pair",
                    return_value=launch,
                ) as launch_pair,
                mock.patch.object(
                    verifier,
                    "_wait",
                    side_effect=[initial, before, after, respawned],
                ),
                mock.patch.object(verifier, "_start_testrun"),
                mock.patch.object(
                    verifier.local_sync,
                    "wait_for_scene",
                ),
                mock.patch.object(
                    verifier,
                    "_start_waves",
                    return_value={"prelude": "true", "waves": "true"},
                ),
                mock.patch.object(
                    verifier,
                    "_query",
                    return_value=client_before,
                ),
                mock.patch.object(
                    verifier,
                    "_atomic_write_settings",
                    return_value=reloaded,
                ),
                mock.patch.object(
                    verifier,
                    "_reload",
                    return_value={
                        "ok": "true",
                        "changed": "kite_radius",
                        "error": "",
                    },
                ),
                mock.patch.object(
                    verifier,
                    "_invoke_action",
                    side_effect=[
                        {
                            "ok": "false",
                            "error": (
                                "host-scope action requires "
                                "session authority"
                            ),
                        },
                        {"ok": "true", "error": ""},
                    ],
                ),
                mock.patch.object(
                    verifier,
                    "_copy_runtime_evidence",
                    return_value={},
                ),
                mock.patch.object(
                    verifier.local_sync,
                    "stop_exact_game_processes",
                    return_value=[{"pid": 101}, {"pid": 102}],
                ) as stop,
                mock.patch.dict("os.environ", {}, clear=False),
            ):
                result = verifier.verify_lifecycle(
                    evidence_dir=evidence,
                    game_directory=Path("/safe/game"),
                    launcher_path=Path("/safe/launcher.exe"),
                    timeout_seconds=1.0,
                )

            self.assertTrue(result["success"])
            self.assertFalse(launch_pair.call_args.kwargs["enable_audio"])
            self.assertFalse(launch_pair.call_args.kwargs["kill_existing"])
            self.assertEqual(
                launch_pair.call_args.kwargs["runtime_root"],
                verifier.ROOT / "runtime",
            )
            stop.assert_called_once_with(launch)


if __name__ == "__main__":
    unittest.main()
