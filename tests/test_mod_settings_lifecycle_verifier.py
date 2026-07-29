#!/usr/bin/env python3
"""Tests for the structured mod-settings loopback verifier."""

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


def roster_view(
    roster: list[dict[str, str]],
    *,
    authority: bool,
    think: str,
    participant_ids: list[int],
) -> dict[str, str]:
    values = {
        "scene": "hub",
        "authority": str(authority).lower(),
        "setting.think_profile": think,
        "setting.roster.copy_isolated": "true",
        "setting.roster.count": str(len(roster)),
        "brain.roster_size": str(len(roster)),
        "actual.count": str(len(roster)),
        "actual.participant_ids": ",".join(
            str(value) for value in participant_ids
        ),
        "actual.1.element_id": "1",
        "actual.2.element_id": "3",
    }
    for index, row in enumerate(roster, start=1):
        for key, value in row.items():
            values[f"setting.roster.{index}.{key}"] = value
            values[f"brain.bot.{index}.{key}"] = value
        values[f"brain.bot.{index}.participant_id"] = str(
            participant_ids[index - 1]
        )
        values[f"brain.bot.{index}.actual_element_id"] = str(
            verifier.ELEMENT_IDS[row["element"]]
        )
    return values


class ModSettingsLifecycleVerifierTests(unittest.TestCase):
    def test_isolation_contract_is_fixed(self) -> None:
        self.assertEqual(verifier.INSTANCE_PREFIX, "ms2")
        self.assertEqual(verifier.HOST_PORT, 49211)
        self.assertEqual(verifier.CLIENT_PORT, 49212)
        self.assertEqual(
            verifier.HOST_PIPE,
            "SolomonDarkModLoader_LuaExec_ms2-host",
        )
        self.assertEqual(
            verifier.CLIENT_PIPE,
            "SolomonDarkModLoader_LuaExec_ms2-client",
        )
        self.assertEqual(
            verifier.EVIDENCE_ROOT,
            Path("/mnt/d/codex-evidence/mod-settings-v2-20260727"),
        )
        source = (TOOLS_ROOT / "verify_mod_settings_lifecycle.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("enable_audio=False", source)
        self.assertIn("kill_existing=False", source)
        self.assertIn("stop_exact_game_processes(launch)", source)
        self.assertNotIn("stop_game_processes(", source)
        self.assertNotIn("49011", source)
        self.assertNotIn("49012", source)

    def test_fixture_writer_uses_canonical_atomic_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            with mock.patch.object(verifier, "ROOT", temporary_root):
                path = verifier._atomic_write_settings(
                    "host",
                    {"roster": verifier.INITIAL_ROSTER},
                )
            self.assertEqual(
                path,
                temporary_root
                / "runtime"
                / "instances"
                / "ms2-host"
                / "stage"
                / ".sdmod"
                / "mod-settings"
                / "bot.brain.json",
            )
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {
                    "schemaVersion": 1,
                    "values": {"roster": verifier.INITIAL_ROSTER},
                },
            )
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_initial_predicate_proves_host_list_replication(self) -> None:
        participant_ids = [101, 102]
        views = {
            "host": roster_view(
                verifier.INITIAL_ROSTER,
                authority=True,
                think="standard",
                participant_ids=participant_ids,
            ),
            "client": roster_view(
                verifier.INITIAL_ROSTER,
                authority=False,
                think="relaxed",
                participant_ids=participant_ids,
            ),
        }
        self.assertTrue(verifier._initial_values_converged(views))
        views["client"]["setting.roster.2.element"] = "fire"
        self.assertFalse(verifier._initial_values_converged(views))

    def test_behavior_predicate_requires_live_leash_and_thresholds(self) -> None:
        values = {
            "scene": "testrun",
            "brain.bot.1.active": "true",
            "brain.bot.2.active": "true",
            "brain.bot.1.guardian_human_participant_id": "51",
            "brain.bot.1.guardian_leash_radius": "260",
            "brain.bot.1.guardian_ward_distance": "180",
            "brain.bot.1.flee_threshold": "0.35",
            "brain.bot.2.flee_threshold": "0.20",
            "brain.bot.1.cast_interval_ms": "500",
            "brain.bot.2.cast_interval_ms": "300",
            "brain.bot.1.engage_radius": "380",
            "brain.bot.2.engage_radius": "240",
            "brain.bot.1.attack_window_max": "275",
            "brain.bot.2.attack_window_max": "250",
            "brain.bot.1.move_accepted": "2",
            "brain.bot.2.move_accepted": "2",
        }
        self.assertTrue(verifier._behaviors_measurable(values))
        values["brain.bot.1.guardian_ward_distance"] = "261"
        self.assertFalse(verifier._behaviors_measurable(values))

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

    def test_lifecycle_always_uses_exact_launch_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary)
            initial = {
                "host": {
                    "brain.bot.1.participant_id": "10",
                    "brain.bot.2.participant_id": "11",
                },
                "client": {},
            }
            behaviors = {"brain.settings_change_count": "0"}
            reconciled = {
                "host": {"brain.bot.1.participant_id": "12"},
                "client": {},
            }
            skirmisher = {"brain.bot.1.participant_id": "13"}
            survived = {"host": {}, "client": {}}
            launch = {
                "audioDisabled": True,
                "hostPort": verifier.HOST_PORT,
                "clientPort": verifier.CLIENT_PORT,
                "hostProcessId": 101,
                "hostExecutablePath": (
                    "C:/sd-mod-settings-v2-20260727/runtime/instances/"
                    "ms2-host/stage/SolomonDark.exe"
                ),
                "clientProcessId": 102,
                "clientExecutablePath": (
                    "C:/sd-mod-settings-v2-20260727/runtime/instances/"
                    "ms2-client/stage/SolomonDark.exe"
                ),
            }
            with (
                mock.patch.object(verifier, "_seed_persisted_values"),
                mock.patch.object(
                    verifier.local_sync,
                    "launch_pair",
                    return_value=launch,
                ) as launch_pair,
                mock.patch.object(
                    verifier,
                    "_require_owned_stage_paths",
                ),
                mock.patch.object(
                    verifier,
                    "_wait",
                    side_effect=[
                        initial,
                        behaviors,
                        reconciled,
                        skirmisher,
                        survived,
                    ],
                ),
                mock.patch.object(verifier, "_start_testrun"),
                mock.patch.object(
                    verifier.local_sync,
                    "wait_for_scene",
                ),
                mock.patch.object(
                    verifier,
                    "_query",
                    return_value={"brain.settings_change_count": "0"},
                ),
                mock.patch.object(verifier, "_write_roster"),
                mock.patch.object(
                    verifier,
                    "_reload",
                    side_effect=[
                        {"ok": "true", "changed": "roster", "error": ""},
                        {"ok": "true", "changed": "roster", "error": ""},
                        {"ok": "true", "changed": "roster", "error": ""},
                    ],
                ),
                mock.patch.object(
                    verifier,
                    "_stage_crash_artifacts",
                    return_value=[],
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
