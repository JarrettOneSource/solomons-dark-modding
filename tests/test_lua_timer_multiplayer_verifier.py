#!/usr/bin/env python3
"""Tests for the two-peer Lua timer verifier."""

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

import verify_lua_timer_multiplayer as verifier  # noqa: E402


class LuaTimerMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _state(
        *,
        authority: bool,
        label: str | None = None,
        released: bool = False,
    ) -> dict[str, str]:
        values = {
            "mod_id": verifier.ACCEPTANCE_MOD_ID,
            "timer_capability": "true",
            "authority": "true" if authority else "false",
            "world_scene": "hub",
            "participant_count": "2",
            "participant_rows": "2",
            "owner_count": "1",
            "namespace_exact": "true",
            "ready": "true" if label is not None else "false",
            "label": label or "",
            "released": "true" if released else "false",
        }
        if label is not None:
            values.update(
                {
                    "after_count": "1",
                    "repeating_count": "3",
                    "sequence_order": "ABC",
                    "cancelled_count": "0",
                    "error_count": "1",
                    "spawned_count": "1",
                    "hold_count": "0",
                    "clear_count": "1" if released else "-1",
                }
            )
        return values

    @staticmethod
    def _result(values: dict[str, str]) -> dict[str, Any]:
        return {"returncode": 0, "values": values}

    @staticmethod
    def _reset_result() -> dict[str, Any]:
        return {
            "returncode": 0,
            "values": {"reset": "true", "cleared": "3"},
        }

    @staticmethod
    def _setup_result(label: str) -> dict[str, Any]:
        values = {
            "scheduled": "true",
            "label": label,
            "precleared": "0",
            "cancel_second": "false",
        }
        for name in (
            "ids_valid",
            "cancel_first",
            "empty_sequence_rejected",
            "zero_every_rejected",
            "negative_after_rejected",
            "fractional_after_rejected",
            "bad_callback_rejected",
            "bad_cancel_rejected",
            "too_many_rejected",
            "cumulative_rejected",
        ):
            values[name] = "true"
        return {"returncode": 0, "values": values}

    @staticmethod
    def _release_result() -> dict[str, Any]:
        return {
            "returncode": 0,
            "values": {
                "first": "1",
                "second": "0",
                "released": "true",
            },
        }

    @staticmethod
    def _capacity_result() -> dict[str, Any]:
        return {
            "returncode": 0,
            "values": {
                "overflow_rejected": "true",
                "ids_valid": "true",
                "cleared": "256",
            },
        }

    def test_state_matcher_requires_exact_peer_local_result(self) -> None:
        values = self._state(
            authority=False,
            label=verifier.CLIENT_LABEL,
        )
        self.assertTrue(
            verifier.timer_state_matches(
                values,
                authority=False,
                label=verifier.CLIENT_LABEL,
                released=False,
            )
        )
        values["repeating_count"] = "4"
        self.assertFalse(
            verifier.timer_state_matches(
                values,
                authority=False,
                label=verifier.CLIENT_LABEL,
                released=False,
            )
        )

    def test_setup_and_capacity_require_exact_limits(self) -> None:
        setup = self._setup_result(verifier.HOST_LABEL)["values"]
        self.assertTrue(
            verifier.setup_matches(setup, label=verifier.HOST_LABEL)
        )
        setup["too_many_rejected"] = "false"
        self.assertFalse(
            verifier.setup_matches(setup, label=verifier.HOST_LABEL)
        )
        capacity = self._capacity_result()["values"]
        self.assertTrue(verifier.capacity_matches(capacity))
        capacity["cleared"] = "255"
        self.assertFalse(verifier.capacity_matches(capacity))

    def test_scheduling_confirmation_is_required_before_contact(
        self,
    ) -> None:
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
            self.assertIn("without --confirm-scheduling", result["error"])

    def test_disposable_pair_is_required_before_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result.json"
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "verify",
                        "--confirm-scheduling",
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
            mock.patch.object(verifier, "_run_probe") as run_probe,
            mock.patch.object(verifier, "_poll_state") as poll_state,
            mock.patch.object(verifier, "wait_for_remote") as wait_remote,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                verifier.run(clients, launch=True, timeout=1.0)

        run_probe.assert_not_called()
        poll_state.assert_not_called()
        wait_remote.assert_not_called()
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
            mock.patch.object(verifier, "wait_for_remote") as wait_remote,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "two exact process IDs",
            ):
                verifier.run(clients, launch=True, timeout=1.0)

        run_probe.assert_not_called()
        poll_state.assert_not_called()
        wait_remote.assert_not_called()
        stop.assert_called_once_with([61])

    def test_run_proves_timer_completion_capacity_and_isolation(
        self,
    ) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        poll_results = [
            self._result(self._state(authority=True)),
            self._result(self._state(authority=False)),
            self._result(
                self._state(
                    authority=True,
                    label=verifier.HOST_LABEL,
                )
            ),
            self._result(self._state(authority=False)),
            self._result(
                self._state(
                    authority=True,
                    label=verifier.HOST_LABEL,
                )
            ),
            self._result(
                self._state(
                    authority=False,
                    label=verifier.CLIENT_LABEL,
                )
            ),
            self._result(
                self._state(
                    authority=True,
                    label=verifier.HOST_LABEL,
                    released=True,
                )
            ),
            self._result(
                self._state(
                    authority=False,
                    label=verifier.CLIENT_LABEL,
                )
            ),
            self._result(
                self._state(
                    authority=True,
                    label=verifier.HOST_LABEL,
                    released=True,
                )
            ),
            self._result(
                self._state(
                    authority=False,
                    label=verifier.CLIENT_LABEL,
                )
            ),
            self._result(
                self._state(
                    authority=True,
                    label=verifier.HOST_LABEL,
                    released=True,
                )
            ),
            self._result(
                self._state(
                    authority=False,
                    label=verifier.CLIENT_LABEL,
                    released=True,
                )
            ),
        ]
        action_results = [
            self._reset_result(),
            self._reset_result(),
            self._setup_result(verifier.HOST_LABEL),
            self._setup_result(verifier.CLIENT_LABEL),
            self._release_result(),
            self._capacity_result(),
            self._release_result(),
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
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            result = verifier.run(clients, launch=True, timeout=1.0)

        self.assertTrue(result["ok"])
        launch_pair.assert_called_once_with(
            tile_windows=False,
            kill_existing=False,
            exact_mod_id=verifier.ACCEPTANCE_MOD_ID,
        )
        self.assertEqual(wait_remote.call_count, 2)
        self.assertEqual(run_probe.call_count, 7)
        self.assertEqual(poll_state.call_count, 12)
        stop.assert_called_once_with([61, 62])


if __name__ == "__main__":
    unittest.main()
