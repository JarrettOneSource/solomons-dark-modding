#!/usr/bin/env python3
"""Tests for the two-peer Lua draw verifier."""

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

import verify_lua_draw_multiplayer as verifier  # noqa: E402


class LuaDrawMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _contract(*, authority: bool) -> dict[str, Any]:
        values = {
            "mod_id": verifier.ACCEPTANCE_MOD_ID,
            "alias_exact": "true",
            "authority": "true" if authority else "false",
            "world_scene": "hub",
            "participant_count": "2",
            "participant_rows": "2",
            "owner_count": "1",
            "namespace_exact": "true",
            "commands_per_mod_frame": "512",
            "text_bytes_per_mod_frame": "16384",
            "text_bytes_per_command": "1024",
            "stock_atlas_count": "28",
            "viewport_width": "1280",
            "viewport_height": "720",
            "sprite_atlas": "Title",
            "sprite_record": "9",
            "sprite_error": "",
        }
        for name in (
            "draw_capability",
            "text_capability",
            "primitives_capability",
            "sprites_capability",
            "projection_capability",
            "limits_schema_exact",
            "viewport_schema_exact",
            "sprite_schema_exact",
            "missing_sprite_nil",
            "missing_error_present",
            "outside_tick_rejected",
            "bad_record_rejected",
        ):
            values[name] = "true"
        return {"returncode": 0, "values": values}

    @staticmethod
    def _setup(
        *,
        label: str,
        x: int,
        active: bool,
    ) -> dict[str, Any]:
        return {
            "returncode": 0,
            "values": {
                "label": label,
                "x": str(x),
                "active": "true" if active else "false",
                "ready": "true",
            },
        }

    @staticmethod
    def _status(
        *,
        label: str,
        x: int,
        active: bool,
        submitted_ticks: int,
        inactive_ticks: int = 0,
        released: bool = False,
    ) -> dict[str, Any]:
        return {
            "returncode": 0,
            "values": {
                "present": "true",
                "label": label,
                "x": str(x),
                "active": "true" if active else "false",
                "observed_ticks": "4",
                "submitted_ticks": str(submitted_ticks),
                "inactive_ticks": str(inactive_ticks),
                "release_stable": "true" if released else "false",
                "last_monotonic_milliseconds": "1200",
                "viewport_width": "1280",
                "viewport_height": "720",
                "commands_exact": "true",
                "projection_available": "true",
                "projection_schema_exact": "true",
                "projection_generation": "42",
                "error": "",
            },
        }

    @staticmethod
    def _lifecycle(*, label: str, active: bool) -> dict[str, Any]:
        return {
            "returncode": 0,
            "values": {
                "label": label,
                "active": "true" if active else "false",
                "submitted_ticks": "4",
            },
        }

    def test_contract_requires_exact_local_draw_schema(self) -> None:
        values = self._contract(authority=False)["values"]
        self.assertTrue(
            verifier.contract_matches(values, authority=False)
        )
        values["sprite_schema_exact"] = "false"
        self.assertFalse(
            verifier.contract_matches(values, authority=False)
        )

    def test_status_requires_exact_peer_label_and_projection(self) -> None:
        values = self._status(
            label=verifier.HOST_LABEL,
            x=verifier.HOST_X,
            active=True,
            submitted_ticks=4,
        )["values"]
        self.assertTrue(
            verifier.status_matches(
                values,
                label=verifier.HOST_LABEL,
                x=verifier.HOST_X,
                active=True,
                released=False,
            )
        )
        values["label"] = verifier.CLIENT_LABEL
        self.assertFalse(
            verifier.status_matches(
                values,
                label=verifier.HOST_LABEL,
                x=verifier.HOST_X,
                active=True,
                released=False,
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
            mock.patch.object(verifier, "_poll_status") as poll_status,
            mock.patch.object(verifier, "_cleanup_peer") as cleanup,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                verifier.run(clients, launch=True, timeout=1.0)

        run_probe.assert_not_called()
        poll_status.assert_not_called()
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
            mock.patch.object(verifier, "_poll_status") as poll_status,
            mock.patch.object(verifier, "_cleanup_peer") as cleanup,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "two exact process IDs",
            ):
                verifier.run(clients, launch=True, timeout=1.0)

        run_probe.assert_not_called()
        poll_status.assert_not_called()
        cleanup.assert_not_called()
        stop.assert_called_once_with([61])

    def test_run_proves_independent_draw_activation_and_release(
        self,
    ) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        host_active = self._status(
            label=verifier.HOST_LABEL,
            x=verifier.HOST_X,
            active=True,
            submitted_ticks=4,
        )
        client_inactive = self._status(
            label=verifier.CLIENT_LABEL,
            x=verifier.CLIENT_X,
            active=False,
            submitted_ticks=0,
            inactive_ticks=4,
            released=True,
        )
        client_active = self._status(
            label=verifier.CLIENT_LABEL,
            x=verifier.CLIENT_X,
            active=True,
            submitted_ticks=4,
        )
        host_released = self._status(
            label=verifier.HOST_LABEL,
            x=verifier.HOST_X,
            active=False,
            submitted_ticks=4,
            inactive_ticks=3,
            released=True,
        )
        client_released = self._status(
            label=verifier.CLIENT_LABEL,
            x=verifier.CLIENT_X,
            active=False,
            submitted_ticks=4,
            inactive_ticks=3,
            released=True,
        )
        poll_results = [
            host_active,
            client_inactive,
            host_active,
            client_active,
            host_released,
            client_active,
            host_released,
            client_released,
        ]
        action_results = [
            self._contract(authority=True),
            self._contract(authority=False),
            self._setup(
                label=verifier.HOST_LABEL,
                x=verifier.HOST_X,
                active=True,
            ),
            self._setup(
                label=verifier.CLIENT_LABEL,
                x=verifier.CLIENT_X,
                active=False,
            ),
            self._lifecycle(
                label=verifier.CLIENT_LABEL,
                active=True,
            ),
            self._lifecycle(
                label=verifier.HOST_LABEL,
                active=False,
            ),
            self._lifecycle(
                label=verifier.CLIENT_LABEL,
                active=False,
            ),
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
                "_poll_status",
                side_effect=poll_results,
            ) as poll_status,
            mock.patch.object(
                verifier,
                "_cleanup_peer",
                return_value={
                    "returncode": 0,
                    "values": {
                        "present": "true",
                        "cleared": "true",
                    },
                },
            ) as cleanup,
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
        self.assertEqual(poll_status.call_count, 8)
        self.assertEqual(cleanup.call_count, 2)
        stop.assert_called_once_with([61, 62])


if __name__ == "__main__":
    unittest.main()
