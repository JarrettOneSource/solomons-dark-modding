#!/usr/bin/env python3
"""Tests for the two-peer Lua authoring verifier."""

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

import verify_lua_authoring_multiplayer as verifier  # noqa: E402


class LuaAuthoringMultiplayerVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.source = Path(self.temporary_directory.name) / "main.lua"
        self.original = (
            f'local source_version = "{verifier.BASELINE_VERSION}"\n'
        ).encode("utf-8")
        self.source.write_bytes(self.original)

    @staticmethod
    def _snapshot(
        *,
        authority: bool,
        handle: str,
    ) -> dict[str, str]:
        return {
            "mod_id": verifier.ACCEPTANCE_MOD_ID,
            "hot_reload": "true",
            "version": verifier.BASELINE_VERSION,
            "surface_handle": handle,
            "surface_hidden": "true",
            "element_count": "2",
            "transport_enabled": "true",
            "transport_ready": "true",
            "authority": "true" if authority else "false",
            "world_scene": "hub",
            "participant_count": "2",
            "participant_rows": "2",
            "owner_count": "1",
        }

    def _snapshot_for_peer(
        self,
        client: tuple[str, str],
    ) -> dict[str, str]:
        return self._snapshot(
            authority=client[0] == "host",
            handle="101" if client[0] == "host" else "202",
        )

    def test_snapshot_requires_transport_pair_and_stable_surface(self) -> None:
        values = self._snapshot(authority=False, handle="202")
        self.assertTrue(
            verifier.snapshot_matches(
                values,
                authority=False,
                version=verifier.BASELINE_VERSION,
                surface_handle="202",
            )
        )
        values["transport_enabled"] = "false"
        self.assertFalse(
            verifier.snapshot_matches(
                values,
                authority=False,
                version=verifier.BASELINE_VERSION,
                surface_handle="202",
            )
        )
        values["transport_enabled"] = "true"
        values["surface_handle"] = "native-pointer"
        self.assertFalse(
            verifier.snapshot_matches(
                values,
                authority=False,
                version=verifier.BASELINE_VERSION,
                surface_handle=None,
            )
        )

    def test_disposable_pair_is_required_before_contact(self) -> None:
        output = Path(self.temporary_directory.name) / "result.json"
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
            mock.patch.object(verifier, "_snapshot") as snapshot,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                verifier.run(
                    clients,
                    launch=True,
                    source_path=self.source,
                    settle_seconds=0.0,
                )

        snapshot.assert_not_called()
        stop.assert_called_once_with([])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_incomplete_process_ledger_stops_only_owned_process(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        with (
            mock.patch.object(
                verifier,
                "launch_pair",
                return_value={"hostProcessId": 61},
            ),
            mock.patch.object(verifier, "_snapshot") as snapshot,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "two exact process IDs",
            ):
                verifier.run(
                    clients,
                    launch=True,
                    source_path=self.source,
                    settle_seconds=0.0,
                )

        snapshot.assert_not_called()
        stop.assert_called_once_with([61])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_run_defers_one_edit_on_both_peers_and_restores_source(
        self,
    ) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
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
                "_snapshot",
                side_effect=self._snapshot_for_peer,
            ) as snapshot,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            result = verifier.run(
                clients,
                launch=True,
                source_path=self.source,
                settle_seconds=0.0,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["source_restored"])
        self.assertEqual(
            result["deferred_candidate"]["samples"],
            {"host": 1, "client": 1},
        )
        self.assertEqual(
            result["restored"]["samples"],
            {"host": 1, "client": 1},
        )
        self.assertEqual(self.source.read_bytes(), self.original)
        launch_pair.assert_called_once_with(
            tile_windows=False,
            kill_existing=False,
            exact_mod_id=verifier.ACCEPTANCE_MOD_ID,
        )
        self.assertEqual(wait_remote.call_count, 2)
        self.assertEqual(snapshot.call_count, 6)
        stop.assert_called_once_with([61, 62])

    def test_concurrent_source_change_is_never_overwritten(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        external = b"concurrent user source\n"

        def change_source_then_fail(
            _clients: list[tuple[str, str]],
            _initial: list[dict[str, str]],
            *,
            duration: float,
            description: str,
        ) -> dict[str, Any]:
            self.assertEqual(duration, 0.0)
            self.assertIn("candidate", description)
            self.source.write_bytes(external)
            raise RuntimeError("forced candidate failure")

        with (
            mock.patch.object(
                verifier,
                "launch_pair",
                return_value={"hostProcessId": 61, "clientProcessId": 62},
            ),
            mock.patch.object(verifier, "disable_bots"),
            mock.patch.object(verifier, "wait_for_remote"),
            mock.patch.object(
                verifier,
                "_snapshot",
                side_effect=self._snapshot_for_peer,
            ),
            mock.patch.object(
                verifier,
                "_assert_pair_stays",
                side_effect=change_source_then_fail,
            ),
            mock.patch.object(verifier, "stop_game_processes") as stop,
            self.assertRaisesRegex(
                RuntimeError,
                "refusing to overwrite",
            ),
        ):
            verifier.run(
                clients,
                launch=True,
                source_path=self.source,
                settle_seconds=0.0,
            )

        self.assertEqual(self.source.read_bytes(), external)
        stop.assert_called_once_with([61, 62])


if __name__ == "__main__":
    unittest.main()
