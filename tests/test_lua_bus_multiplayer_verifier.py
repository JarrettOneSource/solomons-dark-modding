#!/usr/bin/env python3
"""Tests for the two-peer Lua bus verifier."""

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

import verify_lua_bus_multiplayer as verifier  # noqa: E402


class LuaBusMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _result(values: dict[str, str]) -> dict[str, Any]:
        return {"returncode": 0, "values": values}

    @staticmethod
    def _contract(*, authority: bool) -> dict[str, Any]:
        values = {
            "mod_id": verifier.PROVIDER_MOD_ID,
            "bus_capability": "true",
            "authority": "true" if authority else "false",
            "world_scene": "hub",
            "participant_count": "2",
            "participant_rows": "2",
            "owner_count": "1",
            "namespace_exact": "true",
            "has_provider": "true",
            "provider_count": "1",
            "provider_id": verifier.PROVIDER_MOD_ID,
            "request_deliveries": "1",
            "response_count": "1",
            "response_token": "pair-contract",
            "response_publisher": verifier.CONSUMER_MOD_ID,
            "request_mod_id": verifier.PROVIDER_MOD_ID,
            "unsubscribed": "true",
            "unsubscribed_twice": "false",
            "unknown_deliveries": "0",
        }
        for name in (
            "cycle_rejected",
            "function_rejected",
            "bad_topic_rejected",
            "bad_callback_rejected",
            "zero_unsubscribe_rejected",
        ):
            values[name] = "true"
        return {"returncode": 0, "values": values}

    @staticmethod
    def _setup() -> dict[str, Any]:
        return {
            "returncode": 0,
            "values": {
                "preexisting": "false",
                "subscription_positive": "true",
                "ready": "true",
            },
        }

    @staticmethod
    def _state(
        *,
        present: bool,
        count: int = 0,
        token: str = "",
    ) -> dict[str, Any]:
        return {
            "returncode": 0,
            "values": {
                "present": "true" if present else "false",
                "count": str(count),
                "token": token,
                "publisher_mod_id": (
                    verifier.PROVIDER_MOD_ID if count > 0 else ""
                ),
                "topic": verifier.LOCAL_TOPIC if count > 0 else "",
                "subscription_positive": "true" if present else "false",
            },
        }

    @staticmethod
    def _publish(token: str) -> dict[str, Any]:
        return {
            "returncode": 0,
            "values": {
                "delivered": "1",
                "token": token,
            },
        }

    @staticmethod
    def _cleanup(*, present: bool) -> dict[str, Any]:
        return {
            "returncode": 0,
            "values": {
                "present": "true" if present else "false",
                "first": "true" if present else "false",
                "second": "false",
                "cleared": "true",
            },
        }

    @staticmethod
    def _capacity() -> dict[str, Any]:
        return {
            "returncode": 0,
            "values": {
                "created": "127",
                "ids_monotonic": "true",
                "overflow_rejected": "true",
                "removed": "127",
                "post_deliveries": "1",
                "post_response_count": "1",
                "post_response_token": "capacity-after",
                "post_response_publisher": verifier.CONSUMER_MOD_ID,
                "post_request_mod_id": verifier.PROVIDER_MOD_ID,
                "post_unsubscribed": "true",
                "post_unsubscribed_twice": "false",
            },
        }

    def test_contract_requires_exact_cross_mod_schema(self) -> None:
        values = self._contract(authority=True)["values"]
        self.assertTrue(
            verifier.contract_matches(values, authority=True)
        )
        values["response_publisher"] = verifier.PROVIDER_MOD_ID
        self.assertFalse(
            verifier.contract_matches(values, authority=True)
        )

    def test_state_requires_exact_process_local_marker(self) -> None:
        values = self._state(
            present=True,
            count=1,
            token=verifier.CLIENT_TOKEN,
        )["values"]
        self.assertTrue(
            verifier.state_matches(
                values,
                count=1,
                token=verifier.CLIENT_TOKEN,
            )
        )
        values["publisher_mod_id"] = verifier.CONSUMER_MOD_ID
        self.assertFalse(
            verifier.state_matches(
                values,
                count=1,
                token=verifier.CLIENT_TOKEN,
            )
        )

    def test_disposable_pair_is_required_before_contact(self) -> None:
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
            mock.patch.object(verifier, "_poll_state") as poll_state,
            mock.patch.object(verifier, "_cleanup_peer") as cleanup,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                verifier.run(clients, launch=True, timeout=1.0)

        run_probe.assert_not_called()
        poll_state.assert_not_called()
        cleanup.assert_not_called()
        stop.assert_called_once_with([])

    def test_incomplete_process_ledger_stops_only_owned_process(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        with (
            mock.patch.object(
                verifier,
                "launch_pair",
                return_value={"hostProcessId": 61},
            ),
            mock.patch.object(verifier, "_run_probe") as run_probe,
            mock.patch.object(verifier, "_poll_state") as poll_state,
            mock.patch.object(verifier, "_cleanup_peer") as cleanup,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "two exact process IDs",
            ):
                verifier.run(clients, launch=True, timeout=1.0)

        run_probe.assert_not_called()
        poll_state.assert_not_called()
        cleanup.assert_not_called()
        stop.assert_called_once_with([61])

    def test_run_proves_cross_mod_dispatch_capacity_and_isolation(
        self,
    ) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        host_empty = self._state(present=True)
        client_empty = self._state(present=True)
        host_delivered = self._state(
            present=True,
            count=1,
            token=verifier.HOST_TOKEN,
        )
        client_delivered = self._state(
            present=True,
            count=1,
            token=verifier.CLIENT_TOKEN,
        )
        absent = self._state(present=False)
        poll_results = [
            host_empty,
            client_empty,
            host_delivered,
            client_empty,
            host_delivered,
            client_delivered,
            absent,
            client_delivered,
            absent,
            absent,
        ]
        action_results = [
            self._contract(authority=True),
            self._contract(authority=False),
            self._setup(),
            self._setup(),
            self._publish(verifier.HOST_TOKEN),
            self._publish(verifier.CLIENT_TOKEN),
            self._cleanup(present=True),
            self._capacity(),
            self._cleanup(present=True),
        ]

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
                "_run_probe",
                side_effect=action_results,
            ) as run_probe,
            mock.patch.object(
                verifier,
                "_poll_state",
                side_effect=poll_results,
            ) as poll_state,
            mock.patch.object(
                verifier,
                "_cleanup_peer",
                return_value=self._cleanup(present=False),
            ) as cleanup,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            result = verifier.run(clients, launch=True, timeout=1.0)

        self.assertTrue(result["ok"])
        launch_pair.assert_called_once_with(
            tile_windows=False,
            kill_existing=False,
            exact_mod_ids=verifier.ACCEPTANCE_MOD_IDS,
        )
        self.assertEqual(wait_remote.call_count, 2)
        self.assertEqual(run_probe.call_count, 9)
        self.assertEqual(poll_state.call_count, 10)
        self.assertEqual(cleanup.call_count, 2)
        stop.assert_called_once_with([61, 62])


if __name__ == "__main__":
    unittest.main()
