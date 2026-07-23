#!/usr/bin/env python3
"""Tests for the two-peer Lua camera verifier."""

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

import verify_lua_camera_multiplayer as verifier  # noqa: E402


class LuaCameraMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _state(
        *,
        authority: bool,
        target: tuple[float, float] | None = None,
        quiet: bool = True,
    ) -> dict[str, str]:
        focused = target is not None
        return {
            "mod_id": verifier.ACCEPTANCE_MOD_ID,
            "read_capability": "true",
            "focus_capability": "true",
            "shake_capability": "true",
            "authority": "true" if authority else "false",
            "world_scene": "testrun",
            "participant_count": "2",
            "participant_rows": "2",
            "owner_count": "1",
            "namespace_exact": "true",
            "available": "true",
            "scene_available": "true",
            "focus_active": "true" if focused else "false",
            "owns_focus": "true" if focused else "false",
            "width": "640",
            "height": "360",
            "scale": "1",
            "center_x": str(target[0] if target else 320),
            "center_y": str(target[1] if target else 180),
            "shake_magnitude": "0" if quiet else "0.2",
            "shake_accumulator": "0" if quiet else "0.4",
            "schema_exact": "true",
            "numbers_finite": "true",
            "focus_fields_valid": "true",
            "raw_addresses_absent": "true",
            "target_set": "true" if focused else "false",
            "target_x": str(target[0] if target else 0),
            "target_y": str(target[1] if target else 0),
            "focus_matches_target": "true" if focused else "false",
            "native_focus_applied": "true" if focused else "false",
            "shake_quiet": "true" if quiet else "false",
        }

    @staticmethod
    def _focus_request(
        target: tuple[float, float],
    ) -> dict[str, str]:
        return {
            "accepted": "true",
            "target_x": str(target[0]),
            "target_y": str(target[1]),
            "focus_active": "true",
            "owns_focus": "true",
            "focus_x": str(target[0]),
            "focus_y": str(target[1]),
            "extra_get_rejected": "true",
            "nan_focus_rejected": "true",
            "huge_focus_rejected": "true",
            "missing_focus_rejected": "true",
        }

    def test_focus_state_requires_native_center_and_exact_local_target(self) -> None:
        values = self._state(authority=False, target=verifier.CLIENT_FOCUS)
        self.assertTrue(
            verifier.focused_state_matches(
                values,
                authority=False,
                target=verifier.CLIENT_FOCUS,
                require_quiet=True,
            )
        )
        values["native_focus_applied"] = "false"
        self.assertFalse(
            verifier.focused_state_matches(
                values,
                authority=False,
                target=verifier.CLIENT_FOCUS,
            )
        )

    def test_shake_request_requires_synchronous_native_feedback_delta(self) -> None:
        values = {
            "accepted": "true",
            "before_magnitude": "0",
            "before_accumulator": "0",
            "after_magnitude": "0",
            "after_accumulator": "0.2",
            "native_feedback_changed": "true",
            "zero_rejected": "true",
            "high_rejected": "true",
            "nan_rejected": "true",
            "extra_rejected": "true",
        }
        self.assertTrue(verifier.shake_request_matches(values))
        values["native_feedback_changed"] = "false"
        self.assertFalse(verifier.shake_request_matches(values))

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
            mock.patch.object(verifier, "wait_for_remote") as wait_remote,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                verifier.run(clients, launch=True, timeout=1.0)

        run_probe.assert_not_called()
        poll_probe.assert_not_called()
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
            mock.patch.object(verifier, "_poll_probe") as poll_probe,
            mock.patch.object(verifier, "wait_for_remote") as wait_remote,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "two exact process IDs"):
                verifier.run(clients, launch=True, timeout=1.0)

        run_probe.assert_not_called()
        poll_probe.assert_not_called()
        wait_remote.assert_not_called()
        stop.assert_called_once_with([61])

    def test_run_proves_independent_focus_and_host_shake_isolation(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        initial_host = {
            "returncode": 0,
            "values": self._state(authority=True),
        }
        initial_client = {
            "returncode": 0,
            "values": self._state(authority=False),
        }
        focused_host = {
            "returncode": 0,
            "values": self._state(
                authority=True,
                target=verifier.HOST_FOCUS,
            ),
        }
        focused_client = {
            "returncode": 0,
            "values": self._state(
                authority=False,
                target=verifier.CLIENT_FOCUS,
            ),
        }
        shaken_host = {
            "returncode": 0,
            "values": self._state(
                authority=True,
                target=verifier.HOST_FOCUS,
                quiet=False,
            ),
        }
        host_focus_request = {
            "returncode": 0,
            "values": self._focus_request(verifier.HOST_FOCUS),
        }
        client_focus_request = {
            "returncode": 0,
            "values": self._focus_request(verifier.CLIENT_FOCUS),
        }
        shake_request = {
            "returncode": 0,
            "values": {
                "accepted": "true",
                "before_magnitude": "0",
                "before_accumulator": "0",
                "after_magnitude": "0",
                "after_accumulator": "0.2",
                "native_feedback_changed": "true",
                "zero_rejected": "true",
                "high_rejected": "true",
                "nan_rejected": "true",
                "extra_rejected": "true",
            },
        }
        cleared = {
            "returncode": 0,
            "values": {
                "first": "true",
                "second": "false",
                "focus_active": "false",
                "owns_focus": "false",
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
                "_run_probe",
                side_effect=[
                    host_focus_request,
                    client_focus_request,
                    shake_request,
                    cleared,
                    cleared,
                ],
            ) as run_probe,
            mock.patch.object(
                verifier,
                "_poll_probe",
                side_effect=[
                    initial_host,
                    initial_client,
                    focused_host,
                    initial_client,
                    focused_host,
                    focused_client,
                    shaken_host,
                    focused_client,
                    initial_host,
                    initial_client,
                ],
            ) as poll_probe,
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
        self.assertEqual(run_probe.call_count, 5)
        self.assertEqual(poll_probe.call_count, 10)
        stop.assert_called_once_with([61, 62])


if __name__ == "__main__":
    unittest.main()
