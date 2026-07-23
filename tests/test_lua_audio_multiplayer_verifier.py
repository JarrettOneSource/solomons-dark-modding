#!/usr/bin/env python3
"""Tests for the two-peer Lua audio verifier."""

from __future__ import annotations

import base64
import contextlib
import hashlib
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

import verify_lua_audio_multiplayer as verifier  # noqa: E402


class LuaAudioMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _state(
        *,
        authority: bool,
        label: str | None = None,
        sample_volume: float | None = None,
        stream_volume: float | None = None,
    ) -> dict[str, str]:
        count = int(sample_volume is not None) + int(
            stream_volume is not None
        )
        return {
            "mod_id": verifier.ACCEPTANCE_MOD_ID,
            "available": "true",
            "authority": "true" if authority else "false",
            "world_scene": "hub",
            "participant_count": "2",
            "participant_rows": "2",
            "owner_count": "1",
            "playback_count": str(count),
            "label": label or "",
            "sample_present": (
                "true" if sample_volume is not None else "false"
            ),
            "stream_present": (
                "true" if stream_volume is not None else "false"
            ),
            "sample_volume": f"{sample_volume or 0:.2f}",
            "stream_volume": f"{stream_volume or 0:.2f}",
            "schema_exact": "true",
            "raw_internals_absent": "true",
            "activity_exact": "true",
            "created_positive": "true",
            "paths_exact": "true",
            "loops_exact": "true",
            "handles_exact": "true",
        }

    @staticmethod
    def _result(values: dict[str, str]) -> dict[str, Any]:
        return {"returncode": 0, "values": values}

    @staticmethod
    def _contract(*, authority: bool) -> dict[str, Any]:
        values = {
            "mod_id": verifier.ACCEPTANCE_MOD_ID,
            "playback_capability": "true",
            "sample_capability": "true",
            "stream_capability": "true",
            "available": "true",
            "authority": "true" if authority else "false",
            "world_scene": "hub",
            "participant_count": "2",
            "participant_rows": "2",
            "owner_count": "1",
            "namespace_exact": "true",
            "precleared": "0",
            "initial_count": "0",
        }
        for name in (
            "traversal_rejected",
            "absolute_rejected",
            "extension_rejected",
            "invalid_utf8_rejected",
            "missing_rejected",
            "high_volume_rejected",
            "nan_volume_rejected",
            "bad_loop_rejected",
            "unknown_option_rejected",
            "extra_play_rejected",
            "zero_handle_rejected",
            "fractional_handle_rejected",
            "bad_set_volume_rejected",
            "extra_state_rejected",
            "extra_clear_rejected",
            "extra_available_rejected",
        ):
            values[name] = "true"
        return {"returncode": 0, "values": values}

    @staticmethod
    def _play(label: str) -> dict[str, Any]:
        return {
            "returncode": 0,
            "values": {
                "played": "true",
                "label": label,
                "precleared": "0",
                "sample_handle": "1",
                "stream_handle": "2",
                "handles_monotonic": "true",
                "sample_volume_set": "true",
                "stream_volume_set": "true",
                "sample_volume": "0.40",
                "stream_volume": "0.45",
                "playback_count": "2",
            },
        }

    @staticmethod
    def _fixture() -> (
        contextlib.AbstractContextManager[dict[str, Any]]
    ):
        return contextlib.nullcontext(
            {
                "path": verifier.ASSET_PATH,
                "bytes": 204,
                "sha256": verifier.FIXTURE_SHA256,
                "silent_pcm": True,
            }
        )

    def test_audio_state_requires_exact_local_schema(self) -> None:
        values = self._state(
            authority=False,
            label=verifier.CLIENT_LABEL,
            sample_volume=0.40,
            stream_volume=0.55,
        )
        self.assertTrue(
            verifier.audio_state_matches(
                values,
                authority=False,
                label=verifier.CLIENT_LABEL,
                sample_volume=0.40,
                stream_volume=0.55,
            )
        )
        values["raw_internals_absent"] = "false"
        self.assertFalse(
            verifier.audio_state_matches(
                values,
                authority=False,
                label=verifier.CLIENT_LABEL,
                sample_volume=0.40,
                stream_volume=0.55,
            )
        )

    def test_fixture_materialization_is_exact_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "acceptance.wav.base64"
            audio = root / "acceptance.wav"
            source.write_text(
                verifier.FIXTURE_SOURCE.read_text(encoding="ascii"),
                encoding="ascii",
            )
            with (
                mock.patch.object(verifier, "FIXTURE_SOURCE", source),
                mock.patch.object(verifier, "FIXTURE_AUDIO", audio),
            ):
                with verifier._materialize_fixture_asset() as fixture:
                    self.assertEqual(fixture["bytes"], 204)
                    self.assertEqual(
                        fixture["sha256"],
                        verifier.FIXTURE_SHA256,
                    )
                    self.assertEqual(fixture["channels"], 1)
                    self.assertEqual(fixture["sample_width"], 2)
                    self.assertEqual(fixture["sample_rate"], 8000)
                    self.assertEqual(fixture["frame_count"], 80)
                    self.assertTrue(fixture["silent_pcm"])
                    self.assertTrue(audio.is_file())

                self.assertFalse(audio.exists())

    def test_fixture_refuses_to_overwrite_existing_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "acceptance.wav.base64"
            audio = root / "acceptance.wav"
            source.write_text(
                verifier.FIXTURE_SOURCE.read_text(encoding="ascii"),
                encoding="ascii",
            )
            audio.write_bytes(b"user-audio")
            with (
                mock.patch.object(verifier, "FIXTURE_SOURCE", source),
                mock.patch.object(verifier, "FIXTURE_AUDIO", audio),
                self.assertRaisesRegex(RuntimeError, "refusing to overwrite"),
            ):
                with verifier._materialize_fixture_asset():
                    self.fail("existing audio fixture was overwritten")

            self.assertEqual(audio.read_bytes(), b"user-audio")

    def test_fixture_rejects_non_silent_pcm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "acceptance.wav.base64"
            audio = root / "acceptance.wav"
            payload = bytearray(
                base64.b64decode(
                    verifier.FIXTURE_SOURCE.read_bytes().strip(),
                    validate=True,
                )
            )
            payload[-1] = 1
            source.write_bytes(base64.b64encode(payload))
            digest = hashlib.sha256(payload).hexdigest()
            with (
                mock.patch.object(verifier, "FIXTURE_SOURCE", source),
                mock.patch.object(verifier, "FIXTURE_AUDIO", audio),
                mock.patch.object(verifier, "FIXTURE_SHA256", digest),
                self.assertRaisesRegex(RuntimeError, "non-silent PCM"),
            ):
                with verifier._materialize_fixture_asset():
                    self.fail("non-silent audio fixture was accepted")

            self.assertFalse(audio.exists())

    def test_playback_confirmation_is_required_before_contact(self) -> None:
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
            self.assertIn(
                "without --confirm-silent-playback",
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
                        "--confirm-silent-playback",
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
                "_materialize_fixture_asset",
                side_effect=self._fixture,
            ),
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
                "_materialize_fixture_asset",
                side_effect=self._fixture,
            ),
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

    def test_run_proves_playback_volume_capacity_and_isolation(
        self,
    ) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        empty_host = self._result(self._state(authority=True))
        empty_client = self._result(self._state(authority=False))
        host_two = self._result(
            self._state(
                authority=True,
                label=verifier.HOST_LABEL,
                sample_volume=0.40,
                stream_volume=0.45,
            )
        )
        client_two = self._result(
            self._state(
                authority=False,
                label=verifier.CLIENT_LABEL,
                sample_volume=0.40,
                stream_volume=0.45,
            )
        )
        client_changed = self._result(
            self._state(
                authority=False,
                label=verifier.CLIENT_LABEL,
                sample_volume=0.40,
                stream_volume=0.55,
            )
        )
        host_stream = self._result(
            self._state(
                authority=True,
                label=verifier.HOST_LABEL,
                stream_volume=0.45,
            )
        )
        poll_results = [
            empty_host,
            empty_client,
            host_two,
            empty_client,
            host_two,
            client_two,
            host_two,
            client_changed,
            host_stream,
            client_changed,
            empty_host,
            client_changed,
            empty_host,
            empty_client,
        ]
        action_results = [
            self._contract(authority=True),
            self._contract(authority=False),
            self._play(verifier.HOST_LABEL),
            self._play(verifier.CLIENT_LABEL),
            {
                "returncode": 0,
                "values": {
                    "changed": "true",
                    "volume": "0.55",
                    "playback_count": "2",
                },
            },
            {
                "returncode": 0,
                "values": {
                    "first": "true",
                    "second": "false",
                    "missing": "true",
                    "remaining": "1",
                },
            },
            {
                "returncode": 0,
                "values": {
                    "before": "1",
                    "overflow_rejected": "true",
                    "ids_valid": "true",
                    "live_count": "64",
                    "cleared": "64",
                    "empty": "true",
                },
            },
            {
                "returncode": 0,
                "values": {
                    "first": "2",
                    "second": "0",
                    "empty": "true",
                },
            },
        ]

        with (
            mock.patch.object(
                verifier,
                "_materialize_fixture_asset",
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
                return_value={"returncode": 0},
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
        self.assertEqual(run_probe.call_count, 8)
        self.assertEqual(poll_state.call_count, 14)
        self.assertEqual(cleanup.call_count, 2)
        stop.assert_called_once_with([61, 62])


if __name__ == "__main__":
    unittest.main()
