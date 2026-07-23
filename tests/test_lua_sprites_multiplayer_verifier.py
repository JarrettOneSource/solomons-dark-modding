#!/usr/bin/env python3
"""Tests for the two-peer Lua sprite verifier."""

from __future__ import annotations

import contextlib
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

import verify_lua_sprites_multiplayer as verifier  # noqa: E402


class LuaSpritesMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _empty(*, authority: bool) -> dict[str, str]:
        return {
            "mod_id": verifier.ACCEPTANCE_MOD_ID,
            "register_capability": "true",
            "read_capability": "true",
            "draw_capability": "true",
            "authority": "true" if authority else "false",
            "world_scene": "hub",
            "participant_count": "2",
            "participant_rows": "2",
            "owner_count": "1",
            "namespace_exact": "true",
            "registered": "false",
            "list_count": "0",
            "ready": "true",
        }

    @staticmethod
    def _registered(
        *,
        authority: bool,
        revision: int = 1,
        initial_revision: int = 1,
    ) -> dict[str, str]:
        values = LuaSpritesMultiplayerVerifierTests._empty(
            authority=authority
        )
        values.update(
            {
                "registered": "true",
                "list_count": "1",
                "id": verifier.ATLAS_ID,
                "key": verifier.ATLAS_KEY,
                "image": verifier.IMAGE_PATH,
                "bundle": verifier.BUNDLE_PATH,
                "frame_count": "2",
                "image_width": "32",
                "image_height": "16",
                "revision": str(revision),
                "initial_revision": str(initial_revision),
                "current_revision": str(revision),
                "local_only": "true",
                "schema_exact": "true",
                "limits_exact": "true",
                "frames_exact": "true",
                "raw_internals_absent": "true",
            }
        )
        return values

    @staticmethod
    def _registration(revision: int = 1) -> dict[str, Any]:
        return {
            "returncode": 0,
            "values": {
                "accepted": "true",
                "id": verifier.ATLAS_ID,
                "key": verifier.ATLAS_KEY,
                "image": verifier.IMAGE_PATH,
                "bundle": verifier.BUNDLE_PATH,
                "frame_count": "2",
                "image_width": "32",
                "image_height": "16",
                "revision": str(revision),
                "local_only": "true",
                "frame_zero_x": "0",
                "frame_zero_y": "0",
                "frame_zero_width": "16",
                "frame_zero_height": "16",
                "frame_one_x": "16",
                "frame_one_y": "0",
                "frame_one_width": "16",
                "frame_one_height": "16",
                "traversal_rejected": "true",
                "absolute_rejected": "true",
                "image_extension_rejected": "true",
                "bundle_extension_rejected": "true",
                "bad_key_rejected": "true",
                "extra_register_rejected": "true",
            },
        }

    @staticmethod
    def _fixture() -> contextlib.AbstractContextManager[dict[str, Any]]:
        return contextlib.nullcontext(
            {
                "image_sha256": verifier.FIXTURE_IMAGE_SHA256,
                "bundle_sha256": "bundle",
                "frame_count": 2,
            }
        )

    def test_registered_state_requires_exact_owned_descriptor(self) -> None:
        values = self._registered(authority=False)
        self.assertTrue(
            verifier.registered_state_matches(values, authority=False)
        )
        values["raw_internals_absent"] = "false"
        self.assertFalse(
            verifier.registered_state_matches(values, authority=False)
        )

    def test_descriptor_comparison_ignores_only_local_revision(self) -> None:
        host = self._registered(authority=True, revision=2)
        client = self._registered(authority=False, revision=1)
        self.assertTrue(verifier.atlas_descriptors_match(host, client))
        client["image_width"] = "31"
        self.assertFalse(verifier.atlas_descriptors_match(host, client))

    def test_fixture_materialization_is_reproducible_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_source = root / "lab.png.base64"
            descriptor = root / "atlas.example.json"
            image = root / "lab.png"
            bundle = root / "lab.bundle"
            image_source.write_text(
                verifier.FIXTURE_IMAGE_SOURCE.read_text(encoding="ascii"),
                encoding="ascii",
            )
            descriptor.write_text(
                verifier.FIXTURE_DESCRIPTOR.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    verifier,
                    "FIXTURE_IMAGE_SOURCE",
                    image_source,
                ),
                mock.patch.object(verifier, "FIXTURE_DESCRIPTOR", descriptor),
                mock.patch.object(verifier, "FIXTURE_IMAGE", image),
                mock.patch.object(verifier, "FIXTURE_BUNDLE", bundle),
            ):
                with verifier._materialize_fixture_assets() as fixture:
                    self.assertEqual(
                        fixture["image_sha256"],
                        verifier.FIXTURE_IMAGE_SHA256,
                    )
                    self.assertEqual(fixture["frame_count"], 2)
                    self.assertTrue(image.is_file())
                    self.assertTrue(bundle.is_file())

                self.assertFalse(image.exists())
                self.assertFalse(bundle.exists())

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
                "_materialize_fixture_assets",
                side_effect=self._fixture,
            ),
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
                "_materialize_fixture_assets",
                side_effect=self._fixture,
            ),
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

    def test_run_proves_registration_revision_and_release_isolation(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        empty_host = {
            "returncode": 0,
            "values": self._empty(authority=True),
        }
        empty_client = {
            "returncode": 0,
            "values": self._empty(authority=False),
        }
        host_one = {
            "returncode": 0,
            "values": self._registered(authority=True),
        }
        client_one = {
            "returncode": 0,
            "values": self._registered(authority=False),
        }
        host_two = {
            "returncode": 0,
            "values": self._registered(authority=True, revision=2),
        }
        client_two = {
            "returncode": 0,
            "values": self._registered(authority=False, revision=2),
        }
        replaced = {
            "returncode": 0,
            "values": {
                "accepted": "true",
                "id_stable": "true",
                "revision_advanced": "true",
                "before_revision": "1",
                "after_revision": "2",
            },
        }
        unregistered = {
            "returncode": 0,
            "values": {
                "first": "true",
                "second": "false",
                "missing": "true",
                "list_count": "0",
            },
        }
        with (
            mock.patch.object(
                verifier,
                "_materialize_fixture_assets",
                side_effect=self._fixture,
            ),
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
                side_effect=[
                    self._registration(),
                    self._registration(),
                    replaced,
                    replaced,
                    unregistered,
                    unregistered,
                ],
            ) as run_probe,
            mock.patch.object(
                verifier,
                "_poll_probe",
                side_effect=[
                    empty_host,
                    empty_client,
                    host_one,
                    empty_client,
                    host_one,
                    client_one,
                    host_two,
                    client_one,
                    host_two,
                    client_two,
                    empty_host,
                    client_two,
                    empty_host,
                    empty_client,
                ],
            ) as poll_probe,
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
        self.assertEqual(run_probe.call_count, 6)
        self.assertEqual(poll_probe.call_count, 14)
        stop.assert_called_once_with([61, 62])


if __name__ == "__main__":
    unittest.main()
