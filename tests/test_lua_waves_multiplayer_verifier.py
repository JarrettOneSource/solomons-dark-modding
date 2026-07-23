#!/usr/bin/env python3
"""Tests for the two-peer Lua wave-intelligence verifier."""

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

import verify_lua_waves_multiplayer as verifier  # noqa: E402


class LuaWavesMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _registration(*, authority: bool) -> dict[str, str]:
        return {
            "mod_id": verifier.ACCEPTANCE_MOD_ID,
            "registered": "true",
            "authority": "true" if authority else "false",
            "event_count": "0",
        }

    @staticmethod
    def _schedule(*, authority: bool) -> dict[str, str]:
        return {
            "authority": "true" if authority else "false",
            "schedule_rows": "2",
            "first_wave": "1",
            "first_budget": str(verifier.EXPECTED_FIRST_WAVE_BUDGET),
            "first_planned": str(verifier.EXPECTED_FIRST_WAVE_BUDGET),
            "second_wave": "2",
            "second_budget": str(verifier.EXPECTED_SECOND_WAVE_BUDGET),
            "second_planned": str(verifier.EXPECTED_SECOND_WAVE_BUDGET),
            "schedule_valid": "true",
            "raw_addresses_absent": "true",
            "mutation_surface_absent": "true",
            "schedule_signature": "1:2:50:50:100:100:10:false:1001:2|"
            "2:3:50:50:100:100:10:false:1001:3",
        }

    @staticmethod
    def _prestart(*, authority: bool) -> dict[str, str]:
        return {
            "authority": "true" if authority else "false",
            "wave": "0",
            "phase": "idle",
            "planned": "0",
            "remaining_to_spawn": "0",
            "spawned": "0",
            "alive": "0",
            "killed": "0",
            "composition_rows": "0",
            "composition_sorted": "true",
            "aggregate_valid": "true",
            "raw_addresses_absent": "true",
            "planned_composition_signature": "",
            "composition_signature": "",
            "event_count": "0",
            "event_wave": "0",
            "event_planned": "0",
            "event_composition_signature": "",
        }

    @staticmethod
    def _active(*, authority: bool) -> dict[str, str]:
        return {
            "authority": "true" if authority else "false",
            "wave": "1",
            "phase": "clearing",
            "planned": str(verifier.EXPECTED_FIRST_WAVE_BUDGET),
            "remaining_to_spawn": "0",
            "spawned": str(verifier.EXPECTED_FIRST_WAVE_BUDGET),
            "alive": str(verifier.EXPECTED_FIRST_WAVE_BUDGET),
            "killed": "0",
            "composition_rows": "1",
            "composition_sorted": "true",
            "aggregate_valid": "true",
            "raw_addresses_absent": "true",
            "planned_composition_signature": "1001:2",
            "composition_signature": "1001:2:2:2:0",
            "event_count": "1",
            "event_wave": "1",
            "event_planned": str(verifier.EXPECTED_FIRST_WAVE_BUDGET),
            "event_composition_signature": "1001:2",
        }

    def test_schedule_requires_exact_controlled_projection(self) -> None:
        values = self._schedule(authority=True)
        self.assertTrue(verifier.schedule_matches(values, authority=True))
        values["first_budget"] = "3"
        self.assertFalse(verifier.schedule_matches(values, authority=True))

    def test_active_wave_requires_event_and_exact_composition(self) -> None:
        values = self._active(authority=False)
        self.assertTrue(
            verifier.active_wave_matches(
                values,
                authority=False,
                composition_signature="1001:2:2:2:0",
            )
        )
        values["event_composition_signature"] = "1001:1"
        self.assertFalse(
            verifier.active_wave_matches(
                values,
                authority=False,
                composition_signature="1001:2:2:2:0",
            )
        )

    def test_mutation_confirmation_is_required_before_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result.json"
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["verify", "--launch-pair", "--output", str(output)],
                ),
                mock.patch.object(verifier, "run") as run,
                mock.patch("builtins.print"),
            ):
                return_code = verifier.main()

            self.assertEqual(return_code, 2)
            run.assert_not_called()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn("without --confirm-mutation", result["error"])

    def test_disposable_pair_is_required_before_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result.json"
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["verify", "--confirm-mutation", "--output", str(output)],
                ),
                mock.patch.object(verifier, "run") as run,
                mock.patch("builtins.print"),
            ):
                return_code = verifier.main()

            self.assertEqual(return_code, 2)
            run.assert_not_called()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn("requires --launch-pair", result["error"])

    def test_failed_launch_does_not_contact_unowned_lua_pipes(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        with (
            mock.patch.object(
                verifier,
                "launch_pair",
                side_effect=RuntimeError("launch failed"),
            ),
            mock.patch.object(verifier, "_run_probe") as run_probe,
            mock.patch.object(verifier, "_poll_probe") as poll_probe,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                verifier.run(clients, launch=True, timeout=1.0)

        run_probe.assert_not_called()
        poll_probe.assert_not_called()
        stop.assert_called_once_with([])

    def test_run_stages_exact_mod_and_stops_only_launched_pair(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        registration_host = {
            "returncode": 0,
            "values": self._registration(authority=True),
        }
        registration_client = {
            "returncode": 0,
            "values": self._registration(authority=False),
        }
        schedule_host = {
            "returncode": 0,
            "values": self._schedule(authority=True),
        }
        schedule_client = {
            "returncode": 0,
            "values": self._schedule(authority=False),
        }
        prestart_host = {
            "returncode": 0,
            "values": self._prestart(authority=True),
        }
        prestart_client = {
            "returncode": 0,
            "values": self._prestart(authority=False),
        }
        active_host = {
            "returncode": 0,
            "values": self._active(authority=True),
        }
        active_client = {
            "returncode": 0,
            "values": self._active(authority=False),
        }
        started = {"returncode": 0, "values": {"started": "true"}}
        with (
            mock.patch.object(
                verifier,
                "launch_pair",
                return_value={"hostProcessId": 61, "clientProcessId": 62},
            ) as launch_pair,
            mock.patch.object(verifier, "disable_bots"),
            mock.patch.object(verifier, "wait_for_remote") as wait_remote,
            mock.patch.object(
                verifier,
                "start_host_testrun_and_wait_for_clients",
                return_value={"scene": "testrun"},
            ) as start_run,
            mock.patch.object(
                verifier,
                "_run_probe",
                side_effect=[
                    registration_host,
                    registration_client,
                    started,
                ],
            ),
            mock.patch.object(
                verifier,
                "_poll_probe",
                side_effect=[
                    schedule_host,
                    schedule_client,
                    prestart_host,
                    prestart_client,
                    active_host,
                    active_client,
                ],
            ) as poll,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            result = verifier.run(clients, launch=True, timeout=1.0)

        self.assertTrue(result["ok"])
        launch_pair.assert_called_once_with(
            god_mode=True,
            tile_windows=False,
            test_wave_override=verifier.WAVE_OVERRIDE,
            kill_existing=False,
            exact_mod_id=verifier.ACCEPTANCE_MOD_ID,
        )
        start_run.assert_called_once_with(timeout=1.0)
        self.assertEqual(wait_remote.call_count, 4)
        self.assertEqual(poll.call_count, 6)
        stop.assert_called_once_with([61, 62])


if __name__ == "__main__":
    unittest.main()
