#!/usr/bin/env python3
"""Tests for the two-peer Lua enemy-AI verifier."""

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

import verify_lua_ai_multiplayer as verifier  # noqa: E402


class LuaAiMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _spawn_values() -> dict[str, str]:
        return {
            "complete": "true",
            "ok": "true",
            "request_id": "7",
            "content_id": str(verifier.EXPECTED_CONTENT_ID),
            "enemy_type": "18",
            "actor_address": "4096",
            "network_actor_id": "9001",
            "requested_x": "100",
            "requested_y": "200",
            "x": "100",
            "y": "200",
            "rebind_ok": "true",
            "error": "",
            "actor_found": "true",
            "object_type_id": "1002",
            "actor_hp": str(verifier.EXPECTED_HP),
            "actor_max_hp": str(verifier.EXPECTED_HP),
        }

    @staticmethod
    def _host_values(
        *,
        think_count: int,
        x: float,
        y: float,
    ) -> dict[str, str]:
        return {
            "authority": "true",
            "instance_count": "1",
            "found": "true",
            "network_actor_id": "9001",
            "content_id": str(verifier.EXPECTED_CONTENT_ID),
            "key": "grave_oracle",
            "base": "skeleton_mage",
            "active": "true",
            "think_count": str(think_count),
            "blackboard_step": str(think_count),
            "target_mode": "local",
            "target_participant_id": str(verifier.HOST_ID),
            "target_found": "true",
            "goal_offset_distance": "120",
            "goal_axis_aligned": "true",
            "move_goal_active": "true",
            "move_goal_x": "220",
            "move_goal_y": "200",
            "move_goal_stop_distance": "36",
            "raw_internals_absent": "true",
            "actor_found": "true",
            "actor_x": str(x),
            "actor_y": str(y),
            "actor_object_type_id": "1002",
            "actor_enemy_type": "18",
            "actor_hp": str(verifier.EXPECTED_HP),
            "actor_max_hp": str(verifier.EXPECTED_HP),
            "actor_dead": "false",
            "actor_tracked": "true",
        }

    @staticmethod
    def _client_values(
        *,
        x: float,
        y: float,
    ) -> dict[str, str]:
        return {
            "authority": "false",
            "ai_instance_count": "0",
            "ai_state_nil": "true",
            "snapshot_available": "true",
            "snapshot_authority_id": str(verifier.HOST_ID),
            "matching_rows": "1",
            "network_actor_id": "9001",
            "content_id": str(verifier.EXPECTED_CONTENT_ID),
            "object_type_id": "1002",
            "enemy_type": "18",
            "spawn_flags": str(verifier.EXPECTED_SPAWN_FLAGS),
            "spawn_hp": str(verifier.EXPECTED_HP),
            "spawn_speed": str(verifier.EXPECTED_SPEED),
            "spawn_scale": str(verifier.EXPECTED_SCALE),
            "target_participant_id": str(verifier.HOST_ID),
            "target_authoritative": "true",
            "row_x": str(x),
            "row_y": str(y),
            "row_dead": "false",
            "row_tracked": "true",
            "row_lifecycle_owned": "true",
            "raw_addresses_absent": "true",
            "binding_count": "1",
            "binding_address": "8192",
            "binding_matched": "true",
            "binding_parked": "false",
            "binding_removed": "false",
            "local_found": "true",
            "local_address": "8192",
            "local_object_type_id": "1002",
            "local_enemy_type": "18",
            "local_dead": "false",
            "local_tracked": "true",
            "position_error": "0.5",
        }

    def test_spawn_result_requires_registered_native_actor(self) -> None:
        values = self._spawn_values()
        self.assertTrue(verifier.spawn_result_matches(values, 7))
        values["network_actor_id"] = "0"
        self.assertFalse(verifier.spawn_result_matches(values, 7))

    def test_host_ai_requires_exact_blackboard_target_and_movement(self) -> None:
        values = self._host_values(think_count=8, x=104, y=200)
        self.assertTrue(
            verifier.host_ai_matches(
                values,
                network_actor_id=9001,
                object_type_id=1002,
                enemy_type=18,
                minimum_think_count=8,
                start_x=100,
                start_y=200,
            )
        )
        values["blackboard_step"] = "7"
        self.assertFalse(
            verifier.host_ai_matches(
                values,
                network_actor_id=9001,
                object_type_id=1002,
                enemy_type=18,
                minimum_think_count=8,
                start_x=100,
                start_y=200,
            )
        )

    def test_client_snapshot_has_no_controller_and_tracks_authority(self) -> None:
        values = self._client_values(x=104, y=200)
        self.assertTrue(
            verifier.client_snapshot_matches(
                values,
                network_actor_id=9001,
                object_type_id=1002,
                enemy_type=18,
                target_participant_id=verifier.HOST_ID,
                start_x=100,
                start_y=200,
            )
        )
        values["ai_instance_count"] = "1"
        self.assertFalse(
            verifier.client_snapshot_matches(
                values,
                network_actor_id=9001,
                object_type_id=1002,
                enemy_type=18,
                target_participant_id=verifier.HOST_ID,
                start_x=100,
                start_y=200,
            )
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
            mock.patch.object(verifier, "_best_effort_cleanup") as cleanup,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                verifier.run(clients, launch=True, timeout=1.0)

        cleanup.assert_not_called()
        stop.assert_called_once_with([])

    def test_run_stages_exact_mod_and_stops_only_launched_pair(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        registry = {"returncode": 0, "values": {}}
        nav = {
            "returncode": 0,
            "values": {"ready": "true", "x": "100", "y": "200", "distance": "600"},
        }
        spawn = {"returncode": 0, "values": self._spawn_values()}
        first_host = {
            "returncode": 0,
            "values": self._host_values(think_count=3, x=100, y=200),
        }
        first_client = {
            "returncode": 0,
            "values": self._client_values(x=100, y=200),
        }
        second_host = {
            "returncode": 0,
            "values": self._host_values(think_count=8, x=104, y=200),
        }
        second_client = {
            "returncode": 0,
            "values": self._client_values(x=104, y=200),
        }
        retired = {
            "returncode": 0,
            "values": {"instance_count": "0", "state_nil": "true"},
        }
        queued = {
            "returncode": 0,
            "values": {
                "queued": "true",
                "request_id": "7",
                "content_id": str(verifier.EXPECTED_CONTENT_ID),
                "native_type_id": "1002",
            },
        }
        rejection = {
            "returncode": 0,
            "values": {
                "target_rejected": "true",
                "goal_rejected": "true",
                "target_authority_error": "true",
                "goal_authority_error": "true",
                "ai_instance_count": "0",
            },
        }
        segment = {
            "returncode": 0,
            "values": {"query_ok": "true", "segment_clear": "true"},
        }
        killed = {
            "returncode": 0,
            "values": {
                "health_zeroed": "true",
                "death_triggered": "true",
                "exception_code": "0",
            },
        }
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
                "_bootstrap_manual_spawners",
                return_value={"ready": True},
            ),
            mock.patch.object(
                verifier,
                "_poll_probe",
                side_effect=[
                    registry,
                    registry,
                    nav,
                    spawn,
                    first_host,
                    first_client,
                    second_host,
                    second_client,
                    retired,
                    retired,
                ],
            ) as poll,
            mock.patch.object(
                verifier,
                "_run_probe",
                side_effect=[queued, rejection, segment, killed],
            ),
            mock.patch.object(verifier, "_best_effort_cleanup") as cleanup,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            result = verifier.run(clients, launch=True, timeout=1.0)

        self.assertTrue(result["ok"])
        self.assertEqual(result["network_actor_id"], 9001)
        launch_pair.assert_called_once_with(
            god_mode=True,
            kill_existing=False,
            exact_mod_id=verifier.ACCEPTANCE_MOD_ID,
        )
        start_run.assert_called_once_with(timeout=1.0)
        self.assertEqual(wait_remote.call_count, 4)
        self.assertEqual(poll.call_count, 10)
        cleanup.assert_not_called()
        stop.assert_called_once_with([61, 62])


if __name__ == "__main__":
    unittest.main()
