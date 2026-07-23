#!/usr/bin/env python3
"""Tests for the two-peer Lua UI action verifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_lua_ui_multiplayer as verifier  # noqa: E402


class LuaUiMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _values(
        *,
        authority: bool,
        shared_value: int,
        presentation_count: int,
        simulation_count: int,
        presentation_participant_id: int | None = None,
        simulation_participant_id: int | None = None,
        simulation_routed: bool | None = None,
    ) -> dict[str, str]:
        values = {
            "authority": "true" if authority else "false",
            "shared_value": str(shared_value),
            "state_revision": "7",
            "presentation_count": str(presentation_count),
            "simulation_count": str(simulation_count),
        }
        if presentation_participant_id is not None:
            values.update(
                {
                    "presentation_surface": verifier.SURFACE_ID,
                    "presentation_action": verifier.PRESENTATION_ACTION_ID,
                    "presentation_execution": "presentation",
                    "presentation_participant_id": str(
                        presentation_participant_id
                    ),
                    "presentation_request_id": "3",
                    "presentation_routed": "false",
                }
            )
        if simulation_participant_id is not None:
            values.update(
                {
                    "simulation_surface": verifier.SURFACE_ID,
                    "simulation_action": verifier.SIMULATION_ACTION_ID,
                    "simulation_execution": "simulation",
                    "simulation_participant_id": str(
                        simulation_participant_id
                    ),
                    "simulation_request_id": "4",
                    "simulation_routed": (
                        "true" if simulation_routed else "false"
                    ),
                }
            )
        return values

    def test_snapshot_matches_local_and_routed_action_metadata(self) -> None:
        self.assertTrue(
            verifier.snapshot_matches(
                self._values(
                    authority=False,
                    shared_value=1,
                    presentation_count=1,
                    simulation_count=0,
                    presentation_participant_id=verifier.CLIENT_ID,
                ),
                authority=False,
                shared_value=1,
                presentation_count=1,
                simulation_count=0,
                presentation_participant_id=verifier.CLIENT_ID,
            )
        )
        self.assertTrue(
            verifier.snapshot_matches(
                self._values(
                    authority=True,
                    shared_value=1,
                    presentation_count=0,
                    simulation_count=1,
                    simulation_participant_id=verifier.CLIENT_ID,
                    simulation_routed=True,
                ),
                authority=True,
                shared_value=1,
                presentation_count=0,
                simulation_count=1,
                simulation_participant_id=verifier.CLIENT_ID,
                simulation_routed=True,
            )
        )

    def test_snapshot_rejects_wrong_routed_participant(self) -> None:
        values = self._values(
            authority=True,
            shared_value=1,
            presentation_count=0,
            simulation_count=1,
            simulation_participant_id=123,
            simulation_routed=True,
        )
        self.assertFalse(
            verifier.snapshot_matches(
                values,
                authority=True,
                shared_value=1,
                presentation_count=0,
                simulation_count=1,
                simulation_participant_id=verifier.CLIENT_ID,
                simulation_routed=True,
            )
        )

    def test_run_stages_exact_mod_and_stops_only_launched_pair(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        registrations = [
            {
                "returncode": 0,
                "values": {"registered": "true", "authority": "true"},
            },
            {
                "returncode": 0,
                "values": {"registered": "true", "authority": "false"},
            },
        ]
        cleanup = [
            {"returncode": 0, "values": {"cleaned": "true"}},
            {"returncode": 0, "values": {"cleaned": "true"}},
        ]
        with (
            mock.patch.object(
                verifier,
                "launch_pair",
                return_value={"hostProcessId": 11, "clientProcessId": 22},
            ) as launch_pair,
            mock.patch.object(verifier, "disable_bots"),
            mock.patch.object(verifier, "wait_for_remote"),
            mock.patch.object(
                verifier,
                "run_all",
                side_effect=[registrations, cleanup],
            ),
            mock.patch.object(
                verifier,
                "_run_probe",
                return_value={
                    "returncode": 0,
                    "values": {"initialized": "true", "revision": "1"},
                },
            ),
            mock.patch.object(
                verifier,
                "_poll_snapshot",
                side_effect=[{"returncode": 0}] * 8,
            ) as poll,
            mock.patch.object(
                verifier,
                "_activate",
                side_effect=[
                    {"values": {"request_id": "1"}},
                    {"values": {"request_id": "2"}},
                    {"values": {"request_id": "3"}},
                ],
            ) as activate,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            result = verifier.run(clients, launch=True, timeout=1.0)

        self.assertTrue(result["ok"])
        launch_pair.assert_called_once_with(
            god_mode=True,
            kill_existing=False,
            exact_mod_id=verifier.ACCEPTANCE_MOD_ID,
        )
        self.assertEqual(poll.call_count, 8)
        self.assertEqual(
            [call.args[1] for call in activate.call_args_list],
            [
                verifier.PRESENTATION_ACTION_ID,
                verifier.SIMULATION_ACTION_ID,
                verifier.SIMULATION_ACTION_ID,
            ],
        )
        stop.assert_called_once_with([11, 22])


if __name__ == "__main__":
    unittest.main()
