#!/usr/bin/env python3
"""Tests for the two-peer Lua filter verifier."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_lua_filters_multiplayer as verifier  # noqa: E402


class LuaFiltersMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _result(values: dict[str, str]) -> dict[str, Any]:
        return {"returncode": 0, "values": values}

    @staticmethod
    def _contract(
        *,
        authority: bool,
        participant_id: int,
    ) -> dict[str, str]:
        values = {
            "mod_id": verifier.ACCEPTANCE_MOD_ID,
            "authority": "true" if authority else "false",
            "world_scene": "hub",
            "participant_count": "2",
            "participant_rows": "2",
            "owner_count": "1",
            "owner_participant_id": str(participant_id),
            "registered_count": str(len(verifier.FILTER_NAMES)),
            "registered_names": ",".join(verifier.FILTER_NAMES),
            "initial_total": "0",
            "unsupported_rejected": "true",
            "empty_name_rejected": "true",
            "nonfunction_rejected": "true",
        }
        for name in (
            "filter_function",
            "damage_capability",
            "enemy_spawn_capability",
            "drop_roll_capability",
            "wave_spawn_capability",
            "spell_cast_capability",
            "resources_capability",
            "transport_enabled",
            "transport_ready",
        ):
            values[name] = "true"
        return values

    @staticmethod
    def _state(
        *,
        authority: bool,
        participant_id: int,
        xp_count: int,
    ) -> dict[str, str]:
        values = {
            "present": "true",
            "authority": "true" if authority else "false",
            "world_scene": "hub",
            "participant_count": "2",
            "participant_rows": "2",
            "owner_count": "1",
            "owner_participant_id": str(participant_id),
            "total": str(xp_count),
            "trace": "xp.gaining" if xp_count == 1 else "",
            "xp_event": "xp.gaining" if xp_count == 1 else "",
            "xp_participant_id": (
                str(participant_id) if xp_count == 1 else ""
            ),
            "xp_amount": "0",
            "xp_current": "17.5" if xp_count == 1 else "-1",
            "xp_source": "script" if xp_count == 1 else "",
            "xp_native_scaling": "false",
        }
        for filter_name, key in verifier.FILTER_KEYS.items():
            values[key] = (
                str(xp_count) if filter_name == "xp.gaining" else "0"
            )
        return values

    @staticmethod
    def _native_probe() -> dict[str, Any]:
        return {
            "queue": {
                "returncode": 0,
                "values": {
                    "queued": "true",
                    "error": "",
                    "serial": "7",
                },
            },
            "result": {
                "returncode": 0,
                "values": {
                    "completed": "true",
                    "success": "true",
                    "before_xp": "17.5",
                    "after_xp": "17.5",
                    "seh": "0",
                    "error": "",
                },
            },
        }

    def test_contract_requires_all_nine_filters_and_peer_identity(self) -> None:
        values = self._contract(
            authority=True,
            participant_id=verifier.HOST_ID,
        )
        self.assertTrue(
            verifier.contract_matches(
                values,
                authority=True,
                participant_id=verifier.HOST_ID,
            )
        )
        values["registered_names"] = ",".join(
            reversed(verifier.FILTER_NAMES)
        )
        self.assertFalse(
            verifier.contract_matches(
                values,
                authority=True,
                participant_id=verifier.HOST_ID,
            )
        )

    def test_state_requires_only_owner_local_zero_xp_callback(self) -> None:
        values = self._state(
            authority=False,
            participant_id=verifier.CLIENT_ID,
            xp_count=1,
        )
        self.assertTrue(
            verifier.state_matches(
                values,
                authority=False,
                participant_id=verifier.CLIENT_ID,
                xp_count=1,
            )
        )
        values["damage_taken_count"] = "1"
        self.assertFalse(
            verifier.state_matches(
                values,
                authority=False,
                participant_id=verifier.CLIENT_ID,
                xp_count=1,
            )
        )
        native_values = self._native_probe()["result"]["values"]
        self.assertTrue(verifier.native_result_matches(native_values))
        native_values["after_xp"] = "18.5"
        self.assertFalse(verifier.native_result_matches(native_values))

    def test_confirmation_is_required_before_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result.json"
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "verify",
                        "--launch-pair",
                        "--output",
                        str(output),
                    ],
                ),
                mock.patch.object(verifier, "run") as run,
                mock.patch("builtins.print"),
            ):
                return_code = verifier.main()

            self.assertEqual(return_code, 2)
            run.assert_not_called()
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertIn(
                "requires --confirm-zero-xp-probe",
                result["error"],
            )

    def test_disposable_pair_is_required_before_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result.json"
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "verify",
                        "--confirm-zero-xp-probe",
                        "--output",
                        str(output),
                    ],
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
            mock.patch.object(verifier, "_require_action") as require,
            mock.patch.object(verifier, "_poll_state") as poll,
            mock.patch.object(verifier, "_queue_zero_xp") as queue,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                verifier.run(
                    clients,
                    launch=True,
                    confirm_zero_xp_probe=True,
                    timeout=1.0,
                )

        require.assert_not_called()
        poll.assert_not_called()
        queue.assert_not_called()
        stop.assert_called_once_with([])

    def test_incomplete_process_ledger_stops_only_owned_process(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        with (
            mock.patch.object(
                verifier,
                "launch_pair",
                return_value={"hostProcessId": 61},
            ),
            mock.patch.object(verifier, "_require_action") as require,
            mock.patch.object(verifier, "_poll_state") as poll,
            mock.patch.object(verifier, "_queue_zero_xp") as queue,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "two exact process IDs",
            ):
                verifier.run(
                    clients,
                    launch=True,
                    confirm_zero_xp_probe=True,
                    timeout=1.0,
                )

        require.assert_not_called()
        poll.assert_not_called()
        queue.assert_not_called()
        stop.assert_called_once_with([61])

    def test_run_proves_exact_registry_and_owner_local_isolation(
        self,
    ) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]

        def require_action(
            peer: tuple[str, str],
            code: str,
            predicate: Any,
            description: str,
        ) -> dict[str, Any]:
            self.assertEqual(code, verifier.CONTRACT_PROBE)
            self.assertIn("filter registry contract", description)
            authority = peer == clients[0]
            participant_id = (
                verifier.HOST_ID if authority else verifier.CLIENT_ID
            )
            values = self._contract(
                authority=authority,
                participant_id=participant_id,
            )
            self.assertTrue(predicate(values))
            return self._result(values)

        poll_expectations = [
            (clients[0], True, verifier.HOST_ID, 0),
            (clients[1], False, verifier.CLIENT_ID, 0),
            (clients[0], True, verifier.HOST_ID, 1),
            (clients[1], False, verifier.CLIENT_ID, 0),
            (clients[0], True, verifier.HOST_ID, 1),
            (clients[1], False, verifier.CLIENT_ID, 1),
        ]

        def poll_state(
            peer: tuple[str, str],
            *,
            authority: bool,
            participant_id: int,
            xp_count: int,
            timeout: float,
            description: str,
        ) -> dict[str, Any]:
            expected = poll_expectations.pop(0)
            self.assertEqual(
                (peer, authority, participant_id, xp_count),
                expected,
            )
            self.assertEqual(timeout, 1.0)
            self.assertTrue(description)
            return self._result(
                self._state(
                    authority=authority,
                    participant_id=participant_id,
                    xp_count=xp_count,
                )
            )

        with (
            mock.patch.object(
                verifier,
                "launch_pair",
                return_value={"hostProcessId": 61, "clientProcessId": 62},
            ) as launch_pair,
            mock.patch.object(verifier, "disable_bots") as disable_bots,
            mock.patch.object(verifier, "wait_for_remote") as wait_remote,
            mock.patch.object(
                verifier,
                "_require_action",
                side_effect=require_action,
            ) as require,
            mock.patch.object(
                verifier,
                "_poll_state",
                side_effect=poll_state,
            ) as poll,
            mock.patch.object(
                verifier,
                "_queue_zero_xp",
                side_effect=[self._native_probe(), self._native_probe()],
            ) as queue,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            result = verifier.run(
                clients,
                launch=True,
                confirm_zero_xp_probe=True,
                timeout=1.0,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["exact_mod_id"], verifier.ACCEPTANCE_MOD_ID)
        self.assertEqual(poll_expectations, [])
        launch_pair.assert_called_once_with(
            tile_windows=False,
            kill_existing=False,
            exact_mod_id=verifier.ACCEPTANCE_MOD_ID,
        )
        disable_bots.assert_called_once_with()
        self.assertEqual(
            wait_remote.call_args_list,
            [
                mock.call(
                    verifier.HOST_PIPE,
                    verifier.CLIENT_ID,
                    verifier.CLIENT_NAME,
                    "hub",
                ),
                mock.call(
                    verifier.CLIENT_PIPE,
                    verifier.HOST_ID,
                    verifier.HOST_NAME,
                    "hub",
                ),
            ],
        )
        self.assertEqual(require.call_count, 2)
        self.assertEqual(poll.call_count, 6)
        self.assertEqual(
            queue.call_args_list,
            [
                mock.call(clients[0], timeout=1.0),
                mock.call(clients[1], timeout=1.0),
            ],
        )
        stop.assert_called_once_with([61, 62])


if __name__ == "__main__":
    unittest.main()
