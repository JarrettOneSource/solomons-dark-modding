#!/usr/bin/env python3
"""Tests for the two-peer Lua navigation verifier."""

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

import verify_lua_nav_multiplayer as verifier  # noqa: E402


class LuaNavMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _values(*, authority: bool) -> dict[str, str]:
        return {
            "mod_id": verifier.ACCEPTANCE_MOD_ID,
            "capability": "true",
            "authority": "true" if authority else "false",
            "world_scene": "testrun",
            "participant_count": "2",
            "participant_rows": "2",
            "owner_count": "1",
            "namespace_exact": "true",
            "ready": "true",
            "width": "16",
            "height": "12",
            "cell_width": "32.0",
            "cell_height": "32.0",
            "probe_x": "48.5",
            "probe_y": "64.5",
            "subdivisions": str(verifier.SUBDIVISIONS),
            "requested_subdivisions": str(verifier.SUBDIVISIONS),
            "refresh_pending": "false",
            "cell_count": "192",
            "sample_count": "768",
            "traversable_count": "150",
            "path_traversable_count": "145",
            "sample_traversable_count": "601",
            "schema_exact": "true",
            "coordinates_finite": "true",
            "raw_addresses_absent": "true",
            "segment_ok": "true",
            "segment_type": "boolean",
            "segment_value": "true",
            "low_rejected": "true",
            "high_rejected": "true",
            "fraction_rejected": "true",
            "infinite_rejected": "true",
            "nan_rejected": "true",
        }

    def test_state_requires_exact_read_only_native_shape(self) -> None:
        values = self._values(authority=False)
        self.assertTrue(
            verifier.navigation_state_matches(values, authority=False)
        )
        values["schema_exact"] = "false"
        self.assertFalse(
            verifier.navigation_state_matches(values, authority=False)
        )

    def test_shared_geometry_requires_equal_grid_not_local_traversal(self) -> None:
        host = self._values(authority=True)
        client = self._values(authority=False)
        client["traversable_count"] = "140"
        self.assertTrue(verifier.grid_geometry_matches(host, client))
        client["cell_width"] = "31.5"
        self.assertFalse(verifier.grid_geometry_matches(host, client))

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
            mock.patch.object(verifier, "_poll_probe") as poll,
            mock.patch.object(verifier, "wait_for_remote") as wait_remote,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                verifier.run(clients, launch=True, timeout=1.0)

        poll.assert_not_called()
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
            mock.patch.object(verifier, "_poll_probe") as poll,
            mock.patch.object(verifier, "wait_for_remote") as wait_remote,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "two exact process IDs"):
                verifier.run(clients, launch=True, timeout=1.0)

        poll.assert_not_called()
        wait_remote.assert_not_called()
        stop.assert_called_once_with([61])

    def test_run_stages_exact_mod_and_stops_only_launched_pair(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        host = {
            "returncode": 0,
            "values": self._values(authority=True),
        }
        client = {
            "returncode": 0,
            "values": self._values(authority=False),
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
                "_poll_probe",
                side_effect=[host, client],
            ) as poll,
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
        self.assertEqual(poll.call_count, 2)
        stop.assert_called_once_with([61, 62])


if __name__ == "__main__":
    unittest.main()
