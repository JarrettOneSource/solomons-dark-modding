#!/usr/bin/env python3
"""Tests for the two-peer Lua scripted-spell verifier."""

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

import verify_lua_spells_multiplayer as verifier  # noqa: E402


class LuaSpellsMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _effect_values(
        *,
        request_id: int,
        owner_participant_id: int,
        local_owner: bool,
        effect_id: int = 71,
        age_ms: int = 100,
        remaining_ms: int = 2200,
    ) -> dict[str, str]:
        return {
            "effect_count": "1",
            "matching_count": "1",
            "effect_id": str(effect_id),
            "request_id": str(request_id),
            "content_id": str(verifier.EXPECTED_CONTENT_ID),
            "owner_participant_id": str(owner_participant_id),
            "key": verifier.EXPECTED_KEY,
            "x": "1000200",
            "y": "1000000",
            "velocity_x": "0",
            "velocity_y": "0",
            "radius": "178",
            "age_ms": str(age_ms),
            "remaining_ms": str(remaining_ms),
            "data_hits": "0",
            "local_owner": "true" if local_owner else "false",
            "raw_internals_absent": "true",
        }

    def test_cast_result_requires_exact_owner_route(self) -> None:
        values = {
            "request_id": "9",
            "content_id": str(verifier.EXPECTED_CONTENT_ID),
            "owner_participant_id": str(verifier.CLIENT_ID),
            "local_owner": "false",
            "aim_x": "2000200",
            "aim_y": "2000000",
        }
        self.assertTrue(
            verifier.cast_result_matches(
                values,
                owner_participant_id=verifier.CLIENT_ID,
                local_owner=False,
            )
        )
        self.assertFalse(
            verifier.cast_result_matches(
                values,
                owner_participant_id=verifier.HOST_ID,
                local_owner=True,
            )
        )

    def test_effect_requires_exact_identity_owner_and_callback_state(self) -> None:
        values = self._effect_values(
            request_id=9,
            owner_participant_id=verifier.HOST_ID,
            local_owner=False,
        )
        self.assertTrue(
            verifier.effect_matches(
                values,
                request_id=9,
                owner_participant_id=verifier.HOST_ID,
                local_owner=False,
                aim_x=1000200.0,
                aim_y=1000000.0,
                effect_id=71,
            )
        )
        values["data_hits"] = "1"
        self.assertFalse(
            verifier.effect_matches(
                values,
                request_id=9,
                owner_participant_id=verifier.HOST_ID,
                local_owner=False,
                aim_x=1000200.0,
                aim_y=1000000.0,
                effect_id=71,
            )
        )

    def test_near_retirement_witness_precedes_bounded_empty_snapshot(self) -> None:
        cast = {
            "returncode": 0,
            "values": {
                "request_id": "9",
                "content_id": str(verifier.EXPECTED_CONTENT_ID),
                "owner_participant_id": str(verifier.HOST_ID),
                "local_owner": "true",
                "aim_x": "1000200",
                "aim_y": "1000000",
            },
        }
        owner_effect = {
            "returncode": 0,
            "values": self._effect_values(
                request_id=9,
                owner_participant_id=verifier.HOST_ID,
                local_owner=True,
            ),
        }
        observer_effect = {
            "returncode": 0,
            "values": self._effect_values(
                request_id=9,
                owner_participant_id=verifier.HOST_ID,
                local_owner=False,
            ),
        }
        near_retirement = {
            "returncode": 0,
            "values": self._effect_values(
                request_id=9,
                owner_participant_id=verifier.HOST_ID,
                local_owner=False,
                age_ms=2200,
                remaining_ms=200,
            ),
        }
        absent = {
            "returncode": 0,
            "values": {"effect_count": "0", "matching_count": "0"},
        }
        with (
            mock.patch.object(verifier, "_run_probe", return_value=cast),
            mock.patch.object(
                verifier,
                "_poll_effect",
                side_effect=[owner_effect, observer_effect, near_retirement],
            ) as poll_effect,
            mock.patch.object(
                verifier,
                "_poll_effect_absent",
                side_effect=[absent, absent],
            ) as poll_absent,
        ):
            result = verifier._exercise_cast(
                ("host", "host-pipe"),
                ("host", "host-pipe"),
                ("client", "client-pipe"),
                owner_participant_id=verifier.HOST_ID,
                command_is_local_owner=True,
                origin_x=1_000_000.0,
                origin_y=1_000_000.0,
                timeout=1.0,
            )

        self.assertEqual(result["effect_id"], 71)
        self.assertEqual(poll_effect.call_count, 3)
        self.assertEqual(
            poll_effect.call_args_list[-1].kwargs["minimum_age_ms"],
            verifier.EXPECTED_DURATION_MS - 300,
        )
        self.assertEqual(
            poll_absent.call_args_list[-1].kwargs["timeout"],
            verifier.MAX_REMOTE_RETIREMENT_SECONDS,
        )

    def test_mutation_confirmation_is_required_before_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result.json"
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["verify", "--output", str(output)],
                ),
                mock.patch.object(verifier, "run") as run,
                mock.patch("builtins.print"),
            ):
                return_code = verifier.main()

            self.assertEqual(return_code, 2)
            run.assert_not_called()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn("without --confirm-mutation", result["error"])

    def test_failed_launch_does_not_contact_unowned_lua_pipes(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        with (
            mock.patch.object(
                verifier,
                "launch_pair",
                side_effect=RuntimeError("launch failed"),
            ),
            mock.patch.object(verifier, "_best_effort_clear_selection") as clear,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                verifier.run(clients, launch=True, timeout=1.0)

        clear.assert_not_called()
        stop.assert_called_once_with([])

    def test_run_stages_exact_mod_and_stops_only_launched_pair(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        rejection = {
            "returncode": 0,
            "values": {
                "rejected": "true",
                "remote_owner_error": "true",
                "effect_count_unchanged": "true",
            },
        }
        cast_result = {
            "request_id": 9,
            "effect_id": 71,
            "remote_retirement_seconds": 0.2,
        }
        with (
            mock.patch.object(
                verifier,
                "launch_pair",
                return_value={"hostProcessId": 51, "clientProcessId": 52},
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
                "_normalize_selections",
                return_value=[{"returncode": 0}, {"returncode": 0}],
            ),
            mock.patch.object(
                verifier,
                "_poll_probe",
                side_effect=[{"returncode": 0}, {"returncode": 0}],
            ),
            mock.patch.object(
                verifier,
                "_verify_selection_is_local",
                return_value={"selected": True},
            ),
            mock.patch.object(
                verifier,
                "_poll_selection",
                side_effect=[{"returncode": 0}, {"returncode": 0}],
            ),
            mock.patch.object(verifier, "_run_probe", return_value=rejection),
            mock.patch.object(
                verifier,
                "_exercise_cast",
                side_effect=[cast_result, cast_result],
            ) as exercise_cast,
            mock.patch.object(verifier, "_best_effort_clear_selection") as clear,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            result = verifier.run(clients, launch=True, timeout=1.0)

        self.assertTrue(result["ok"])
        launch_pair.assert_called_once_with(
            god_mode=True,
            tile_windows=False,
            kill_existing=False,
            exact_mod_id=verifier.ACCEPTANCE_MOD_ID,
        )
        start_run.assert_called_once_with(timeout=1.0)
        self.assertEqual(wait_remote.call_count, 4)
        self.assertEqual(exercise_cast.call_count, 2)
        self.assertTrue(
            exercise_cast.call_args_list[0].kwargs["command_is_local_owner"]
        )
        self.assertFalse(
            exercise_cast.call_args_list[1].kwargs["command_is_local_owner"]
        )
        clear.assert_called_once_with(clients)
        stop.assert_called_once_with([51, 52])


if __name__ == "__main__":
    unittest.main()
