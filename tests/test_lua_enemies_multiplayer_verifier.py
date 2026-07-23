#!/usr/bin/env python3
"""Tests for the two-peer Lua enemy lifecycle verifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_lua_enemies_multiplayer as verifier  # noqa: E402


class LuaEnemiesMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _spawn_values() -> dict[str, str]:
        return {
            "complete": "true",
            "ok": "true",
            "request_id": "7",
            "content_id": str(verifier.EXPECTED_CONTENT_ID),
            "enemy_type": "17",
            "actor_address": "4096",
            "network_actor_id": "9001",
            "requested_x": "300",
            "requested_y": "200",
            "x": "300",
            "y": "200",
            "wrote_x": "true",
            "wrote_y": "true",
            "rebind_ok": "true",
            "error": "",
            "actor_found": "true",
            "actor_tracked": "true",
            "actor_dead": "false",
            "actor_object_type_id": str(verifier.EXPECTED_NATIVE_TYPE_ID),
            "actor_hp": str(verifier.EXPECTED_HP),
            "actor_max_hp": str(verifier.EXPECTED_HP),
        }

    @staticmethod
    def _materialized_values() -> dict[str, str]:
        return {
            "authority": "false",
            "snapshot_available": "true",
            "snapshot_authority_id": str(verifier.HOST_ID),
            "content_count": "1",
            "row_found": "true",
            "network_actor_id": "9001",
            "content_id": str(verifier.EXPECTED_CONTENT_ID),
            "object_type_id": str(verifier.EXPECTED_NATIVE_TYPE_ID),
            "enemy_type": "17",
            "spawn_flags": str(verifier.EXPECTED_SPAWN_FLAGS),
            "spawn_hp": str(verifier.EXPECTED_HP),
            "spawn_speed": str(verifier.EXPECTED_SPEED),
            "spawn_attack_speed": "0",
            "spawn_scale": str(verifier.EXPECTED_SCALE),
            "row_hp": str(verifier.EXPECTED_HP),
            "row_max_hp": str(verifier.EXPECTED_HP),
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
            "local_object_type_id": str(verifier.EXPECTED_NATIVE_TYPE_ID),
            "local_enemy_type": "17",
            "local_hp": str(verifier.EXPECTED_HP),
            "local_max_hp": str(verifier.EXPECTED_HP),
            "local_dead": "false",
            "local_tracked": "true",
            "position_error": "0.25",
        }

    @staticmethod
    def _death_values() -> dict[str, str]:
        return {
            "snapshot_available": "true",
            "snapshot_authority_id": str(verifier.HOST_ID),
            "matching_rows": "1",
            "network_actor_id": "9001",
            "dead": "true",
            "content_id": str(verifier.EXPECTED_CONTENT_ID),
            "object_type_id": str(verifier.EXPECTED_NATIVE_TYPE_ID),
            "enemy_type": "17",
            "spawn_flags": str(verifier.EXPECTED_SPAWN_FLAGS),
            "spawn_hp": str(verifier.EXPECTED_HP),
            "spawn_speed": str(verifier.EXPECTED_SPEED),
            "spawn_attack_speed": "0",
            "spawn_scale": str(verifier.EXPECTED_SCALE),
            "spawn_count": "1",
            "spawn_content_id": str(verifier.EXPECTED_CONTENT_ID),
            "death_count": "1",
            "death_content_id": str(verifier.EXPECTED_CONTENT_ID),
            "death_type": "17",
        }

    def test_spawn_result_requires_exact_content_and_native_result(self) -> None:
        values = self._spawn_values()
        self.assertTrue(verifier.spawn_result_matches(values, 7))
        values["network_actor_id"] = "0"
        self.assertFalse(verifier.spawn_result_matches(values, 7))

    def test_materialization_requires_exact_snapshot_and_local_binding(self) -> None:
        values = self._materialized_values()
        self.assertTrue(verifier.materialized_enemy_matches(values, 9001, 17))
        values["spawn_flags"] = "3"
        self.assertFalse(verifier.materialized_enemy_matches(values, 9001, 17))

    def test_events_require_exact_single_spawn_and_death(self) -> None:
        values = {
            "spawn_count": "1",
            "spawn_content_id": str(verifier.EXPECTED_CONTENT_ID),
            "spawn_type": "17",
            "spawn_x": "300",
            "spawn_y": "200",
            "death_count": "1",
            "death_content_id": str(verifier.EXPECTED_CONTENT_ID),
            "death_type": "17",
            "death_x": "301",
            "death_y": "201",
        }
        self.assertTrue(
            verifier.event_status_matches(
                values,
                spawn_count=1,
                death_count=1,
                enemy_type=17,
            )
        )
        values["death_count"] = "2"
        self.assertFalse(
            verifier.event_status_matches(
                values,
                spawn_count=1,
                death_count=1,
                enemy_type=17,
            )
        )

    def test_death_snapshot_requires_exact_identity_and_constructor_values(
        self,
    ) -> None:
        values = self._death_values()
        self.assertTrue(verifier.death_snapshot_matches(values, 9001, 17))
        values["spawn_hp"] = "320"
        self.assertFalse(verifier.death_snapshot_matches(values, 9001, 17))
        values["spawn_hp"] = str(verifier.EXPECTED_HP)
        self.assertFalse(verifier.death_snapshot_matches(values, 9002, 17))

    def test_run_stages_exact_mod_and_stops_only_launched_pair(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        registration = {
            "returncode": 0,
            "values": {
                "registered": "true",
                "authority": "true",
                "content_id": str(verifier.EXPECTED_CONTENT_ID),
                "native_type_id": str(verifier.EXPECTED_NATIVE_TYPE_ID),
            },
        }
        client_registration = {
            "returncode": 0,
            "values": {**registration["values"], "authority": "false"},
        }
        rejection = {
            "returncode": 0,
            "values": {"rejected": "true", "authority_error": "true"},
        }
        queued = {
            "returncode": 0,
            "values": {
                "queued": "true",
                "request_id": "7",
                "content_id": str(verifier.EXPECTED_CONTENT_ID),
                "native_type_id": str(verifier.EXPECTED_NATIVE_TYPE_ID),
            },
        }
        killed = {
            "returncode": 0,
            "values": {
                "health_zeroed": "true",
                "death_triggered": "true",
                "exception_code": "0",
            },
        }
        spawn_result = {
            "returncode": 0,
            "values": self._spawn_values(),
        }
        materialized = {
            "returncode": 0,
            "values": self._materialized_values(),
        }
        death_snapshot = {
            "returncode": 0,
            "values": self._death_values(),
        }
        event_probe = {"returncode": 0, "values": {}}
        loot_probe = {"returncode": 0, "values": {}}

        with (
            mock.patch.object(
                verifier,
                "launch_pair",
                return_value={"hostProcessId": 41, "clientProcessId": 42},
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
                "_register_event_probes",
                return_value=[registration, client_registration],
            ),
            mock.patch.object(
                verifier,
                "_poll_events",
                return_value=event_probe,
            ) as poll_events,
            mock.patch.object(
                verifier,
                "_poll_empty_loot_stable",
                return_value=loot_probe,
            ) as poll_loot,
            mock.patch.object(
                verifier,
                "_run_probe",
                side_effect=[rejection, queued, killed],
            ),
            mock.patch.object(
                verifier,
                "_poll_probe",
                side_effect=[spawn_result, materialized, death_snapshot],
            ),
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            result = verifier.run(clients, launch=True, timeout=1.0)

        self.assertTrue(result["ok"])
        self.assertEqual(result["network_actor_id"], 9001)
        launch_pair.assert_called_once_with(
            god_mode=True,
            tile_windows=False,
            kill_existing=False,
            exact_mod_id=verifier.ACCEPTANCE_MOD_ID,
        )
        start_run.assert_called_once_with(timeout=1.0)
        self.assertEqual(wait_remote.call_count, 4)
        self.assertEqual(poll_events.call_count, 8)
        self.assertEqual(poll_loot.call_count, 2)
        stop.assert_called_once_with([41, 42])


if __name__ == "__main__":
    unittest.main()
