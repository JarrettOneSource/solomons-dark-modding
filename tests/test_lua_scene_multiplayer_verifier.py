#!/usr/bin/env python3
"""Tests for the two-peer Lua scene-control verifier."""

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

import verify_lua_scene_multiplayer as verifier  # noqa: E402


class LuaSceneMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _state(
        *,
        authority: bool,
        kind: str,
        name: str,
        region_index: int,
        host_scene_kind: str,
        host_scene_region_index: int,
    ) -> dict[str, str]:
        arena = kind == "arena"
        hub = kind == "hub"
        return {
            "mod_id": verifier.ACCEPTANCE_MOD_ID,
            "read_capability": "true",
            "switch_capability": "true",
            "authority": "true" if authority else "false",
            "kind": kind,
            "name": name,
            "region_index": str(region_index),
            "region_type_id": "19",
            "transitioning": "false",
            "state_authority": "true" if authority else "false",
            "can_switch_region": (
                "true" if authority and not arena else "false"
            ),
            "can_enter_run": "true" if authority and hub else "false",
            "namespace_exact": "true",
            "raw_addresses_absent": "true",
            "host_runtime_row_found": "true",
            "host_participant_found": "false" if authority else "true",
            "host_scene_kind": host_scene_kind,
            "host_scene_region_index": str(host_scene_region_index),
            "host_scene_region_type_id": "-1",
        }

    def test_client_hub_can_observe_host_private_room(self) -> None:
        values = self._state(
            authority=False,
            kind="hub",
            name="hub",
            region_index=verifier.HUB_REGION_INDEX,
            host_scene_kind="PrivateRegion",
            host_scene_region_index=verifier.PRIVATE_REGION_INDEX,
        )
        self.assertTrue(
            verifier.hub_observing_private_host_state_matches(values)
        )
        values["host_scene_region_index"] = "3"
        self.assertFalse(
            verifier.hub_observing_private_host_state_matches(values)
        )

    def test_host_and_client_can_occupy_different_private_rooms(self) -> None:
        host = self._state(
            authority=True,
            kind="region",
            name="region_2",
            region_index=verifier.PRIVATE_REGION_INDEX,
            host_scene_kind="PrivateRegion",
            host_scene_region_index=verifier.PRIVATE_REGION_INDEX,
        )
        client = self._state(
            authority=False,
            kind="shop",
            name="region_3",
            region_index=3,
            host_scene_kind="PrivateRegion",
            host_scene_region_index=verifier.PRIVATE_REGION_INDEX,
        )
        self.assertTrue(
            verifier.different_private_rooms_state_matches(host, client)
        )
        client["region_index"] = str(verifier.PRIVATE_REGION_INDEX)
        self.assertFalse(
            verifier.different_private_rooms_state_matches(host, client)
        )

    def test_dormant_hub_world_requires_motion_in_the_same_epoch(self) -> None:
        before = {
            "sequence": "40",
            "scene_epoch": "7",
            "scene_kind": "SharedHub",
            "actor_count": "9",
            "apply_valid": "true",
            "student_count": "2",
            "named_npc_count": "8",
            "motion_checksum": "100.000000",
        }
        after = dict(before)
        after["sequence"] = "44"
        after["motion_checksum"] = "100.250000"
        self.assertTrue(
            verifier.hub_world_stream_advanced(before, after)
        )
        after["scene_epoch"] = "8"
        self.assertFalse(
            verifier.hub_world_stream_advanced(before, after)
        )

    def test_arena_exit_rejection_distinguishes_host_and_client(self) -> None:
        host = {
            "authority": "true",
            "rejected": "true",
            "authority_error": "false",
            "stock_leave_error": "true",
            "kind": "arena",
            "region_index": str(verifier.ARENA_REGION_INDEX),
        }
        client = {
            "authority": "false",
            "rejected": "true",
            "authority_error": "true",
            "stock_leave_error": "false",
            "kind": "arena",
            "region_index": str(verifier.ARENA_REGION_INDEX),
        }
        self.assertTrue(
            verifier.arena_exit_rejection_matches(host, authority=True)
        )
        self.assertTrue(
            verifier.arena_exit_rejection_matches(client, authority=False)
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
                verifier.run(
                    clients,
                    launch=True,
                    timeout=1.0,
                    instance_prefix="scene-test",
                    ports=(48001, 48002),
                )

        run_probe.assert_not_called()
        poll_probe.assert_not_called()
        stop.assert_called_once_with([])

    def test_run_stages_exact_mod_and_stops_only_launched_pair(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        hub_host = {
            "returncode": 0,
            "values": self._state(
                authority=True,
                kind="hub",
                name="hub",
                region_index=verifier.HUB_REGION_INDEX,
                host_scene_kind="SharedHub",
                host_scene_region_index=verifier.HUB_REGION_INDEX,
            ),
        }
        hub_client = {
            "returncode": 0,
            "values": self._state(
                authority=False,
                kind="hub",
                name="hub",
                region_index=verifier.HUB_REGION_INDEX,
                host_scene_kind="SharedHub",
                host_scene_region_index=verifier.HUB_REGION_INDEX,
            ),
        }
        private_host = {
            "returncode": 0,
            "values": self._state(
                authority=True,
                kind="region",
                name="region_2",
                region_index=verifier.PRIVATE_REGION_INDEX,
                host_scene_kind="PrivateRegion",
                host_scene_region_index=verifier.PRIVATE_REGION_INDEX,
            ),
        }
        private_client = {
            "returncode": 0,
            "values": self._state(
                authority=False,
                kind="hub",
                name="hub",
                region_index=verifier.HUB_REGION_INDEX,
                host_scene_kind="PrivateRegion",
                host_scene_region_index=verifier.PRIVATE_REGION_INDEX,
            ),
        }
        different_private_client = {
            "returncode": 0,
            "values": self._state(
                authority=False,
                kind="shop",
                name="region_3",
                region_index=verifier.CLIENT_PRIVATE_REGION_INDEX,
                host_scene_kind="PrivateRegion",
                host_scene_region_index=verifier.PRIVATE_REGION_INDEX,
            ),
        }
        hub_world_before = {
            "returncode": 0,
            "values": {
                "sequence": "40",
                "scene_epoch": "7",
                "scene_kind": "SharedHub",
                "actor_count": "9",
                "apply_valid": "true",
                "student_count": "2",
                "named_npc_count": "8",
                "identity_checksum": "1234",
                "motion_checksum": "100.000000",
            },
        }
        hub_world_after = {
            "returncode": 0,
            "values": {
                **hub_world_before["values"],
                "sequence": "44",
                "motion_checksum": "100.250000",
            },
        }
        arena_host = {
            "returncode": 0,
            "values": self._state(
                authority=True,
                kind="arena",
                name="testrun",
                region_index=verifier.ARENA_REGION_INDEX,
                host_scene_kind="Run",
                host_scene_region_index=-1,
            ),
        }
        arena_client = {
            "returncode": 0,
            "values": self._state(
                authority=False,
                kind="arena",
                name="testrun",
                region_index=verifier.ARENA_REGION_INDEX,
                host_scene_kind="Run",
                host_scene_region_index=-1,
            ),
        }
        private_request = {
            "returncode": 0,
            "values": {
                "queued": "true",
                "fraction_rejected": "true",
                "negative_rejected": "true",
                "too_large_rejected": "true",
            },
        }
        queued = {"returncode": 0, "values": {"queued": "true"}}
        client_rejection = {
            "returncode": 0,
            "values": {
                "rejected": "true",
                "authority_error": "true",
                "region_index": "0",
                "transitioning": "false",
            },
        }
        host_exit = {
            "returncode": 0,
            "values": {
                "authority": "true",
                "rejected": "true",
                "authority_error": "false",
                "stock_leave_error": "true",
                "kind": "arena",
                "region_index": "5",
            },
        }
        client_exit = {
            "returncode": 0,
            "values": {
                "authority": "false",
                "rejected": "true",
                "authority_error": "true",
                "stock_leave_error": "false",
                "kind": "arena",
                "region_index": "5",
            },
        }
        with (
            mock.patch.object(
                verifier,
                "launch_pair",
                return_value={"hostProcessId": 61, "clientProcessId": 62},
            ) as launch_pair,
            mock.patch.object(verifier, "wait_for_remote") as wait_remote,
            mock.patch.object(
                verifier,
                "_run_probe",
                side_effect=[
                    client_rejection,
                    private_request,
                    queued,
                    queued,
                    queued,
                    queued,
                    host_exit,
                    client_exit,
                ],
            ) as run_probe,
            mock.patch.object(
                verifier,
                "_poll_probe",
                side_effect=[
                    hub_host,
                    hub_client,
                    hub_world_before,
                    private_host,
                    private_client,
                    hub_world_after,
                    private_host,
                    different_private_client,
                    private_host,
                    private_client,
                    hub_host,
                    hub_client,
                    arena_host,
                    arena_client,
                ],
            ) as poll,
            mock.patch.object(verifier, "_disable_bots"),
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            result = verifier.run(
                clients,
                launch=True,
                timeout=1.0,
                instance_prefix="scene-test",
                ports=(48001, 48002),
            )

        self.assertTrue(result["ok"])
        launch_pair.assert_called_once_with(
            god_mode=True,
            tile_windows=False,
            kill_existing=False,
            exact_mod_id=verifier.ACCEPTANCE_MOD_ID,
            instance_prefix="scene-test",
            host_port=48001,
            client_port=48002,
            game_directory=None,
            quick_start=True,
        )
        self.assertEqual(wait_remote.call_count, 4)
        self.assertEqual(run_probe.call_count, 8)
        self.assertEqual(poll.call_count, 14)
        stop.assert_called_once_with([61, 62])


if __name__ == "__main__":
    unittest.main()
