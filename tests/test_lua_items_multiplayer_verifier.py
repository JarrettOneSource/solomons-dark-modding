#!/usr/bin/env python3
"""Tests for the two-peer Lua item grant verifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_lua_items_multiplayer as verifier  # noqa: E402


class LuaItemsMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _item_state(
        *,
        authority: bool,
        recipe_uid: int,
        unit_count: int,
    ) -> dict[str, object]:
        return {
            "returncode": 0,
            "values": {
                "authority": "true" if authority else "false",
                "content_id": str(verifier.EXPECTED_CONTENT_ID),
                "available": "true",
                "recipe_uid": str(recipe_uid),
                "inventory_valid": "true",
                "unit_count": str(unit_count),
                "row_count": str(unit_count),
            },
        }

    def test_item_state_requires_exact_content_recipe_and_units(self) -> None:
        values = self._item_state(
            authority=False,
            recipe_uid=77,
            unit_count=3,
        )["values"]
        self.assertTrue(
            verifier.item_state_matches(
                values,
                authority=False,
                recipe_uid=77,
                unit_count=3,
            )
        )
        self.assertFalse(
            verifier.item_state_matches(
                values,
                authority=False,
                recipe_uid=78,
                unit_count=3,
            )
        )

    def test_grant_result_requires_exact_route(self) -> None:
        values = {
            "request_id": "9",
            "content_id": str(verifier.EXPECTED_CONTENT_ID),
            "target_participant_id": str(verifier.CLIENT_ID),
            "local_target": "false",
        }
        self.assertTrue(
            verifier.grant_result_matches(
                values,
                target_participant_id=verifier.CLIENT_ID,
                local_target=False,
            )
        )
        self.assertFalse(
            verifier.grant_result_matches(
                values,
                target_participant_id=verifier.LOCAL_TARGET_ID,
                local_target=True,
            )
        )

    def test_run_stages_exact_mod_and_stops_only_launched_pair(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        host_initial = self._item_state(
            authority=True,
            recipe_uid=101,
            unit_count=2,
        )
        client_initial = self._item_state(
            authority=False,
            recipe_uid=202,
            unit_count=4,
        )
        rejection = {
            "returncode": 0,
            "values": {"rejected": "true", "authority_error": "true"},
        }
        remote_grant = {
            "returncode": 0,
            "values": {
                "request_id": "1",
                "content_id": str(verifier.EXPECTED_CONTENT_ID),
                "target_participant_id": str(verifier.CLIENT_ID),
                "local_target": "false",
            },
        }
        local_grant = {
            "returncode": 0,
            "values": {
                "request_id": "2",
                "content_id": str(verifier.EXPECTED_CONTENT_ID),
                "target_participant_id": str(verifier.LOCAL_TARGET_ID),
                "local_target": "true",
            },
        }
        with (
            mock.patch.object(
                verifier,
                "launch_pair",
                return_value={"hostProcessId": 31, "clientProcessId": 32},
            ) as launch_pair,
            mock.patch.object(verifier, "disable_bots"),
            mock.patch.object(verifier, "wait_for_remote"),
            mock.patch.object(
                verifier,
                "start_host_testrun_and_wait_for_clients",
                return_value={"scene": "testrun"},
            ) as start_run,
            mock.patch.object(
                verifier,
                "_poll_item_state",
                side_effect=[
                    host_initial,
                    client_initial,
                    client_initial,
                    self._item_state(
                        authority=False,
                        recipe_uid=202,
                        unit_count=5,
                    ),
                    host_initial,
                    self._item_state(
                        authority=True,
                        recipe_uid=101,
                        unit_count=3,
                    ),
                    self._item_state(
                        authority=False,
                        recipe_uid=202,
                        unit_count=5,
                    ),
                ],
            ) as poll,
            mock.patch.object(
                verifier,
                "_run_probe",
                side_effect=[rejection, remote_grant, local_grant],
            ),
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            result = verifier.run(clients, launch=True, timeout=1.0)

        self.assertTrue(result["ok"])
        self.assertEqual(result["recipe_uids"], {"host": 101, "client": 202})
        launch_pair.assert_called_once_with(
            god_mode=True,
            tile_windows=False,
            kill_existing=False,
            exact_mod_id=verifier.ACCEPTANCE_MOD_ID,
        )
        start_run.assert_called_once_with(timeout=1.0)
        self.assertEqual(poll.call_count, 7)
        stop.assert_called_once_with([31, 32])


if __name__ == "__main__":
    unittest.main()
