#!/usr/bin/env python3
"""Regression tests for the source-restoring Lua authoring live verifier."""

from __future__ import annotations

import io
import queue
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_lua_authoring as verifier  # noqa: E402
import verify_local_multiplayer_sync as multiplayer_sync  # noqa: E402


class FakeAuthoringRuntime:
    def __init__(
        self,
        source: Path,
        *,
        transport_enabled: bool,
        transport_ready: bool,
    ) -> None:
        self.source = source
        self.transport_enabled = transport_enabled
        self.transport_ready = transport_ready
        self.version = verifier.BASELINE_VERSION
        self.handle = 100

    def snapshot(self, _pipe_name: str) -> dict[str, str]:
        source = self.source.read_text(encoding="utf-8")
        if not self.transport_enabled and "authoring_syntax_error" not in source:
            if verifier.RELOADED_VERSION in source:
                desired_version = verifier.RELOADED_VERSION
            elif verifier.BASELINE_VERSION in source:
                desired_version = verifier.BASELINE_VERSION
            else:
                raise AssertionError(f"unexpected authoring source: {source!r}")
            if desired_version != self.version:
                self.version = desired_version
                self.handle += 1
        return {
            "mod_id": verifier.MOD_ID,
            "hot_reload": "true",
            "version": self.version,
            "surface_handle": str(self.handle),
            "surface_hidden": "true",
            "element_count": "2",
            "transport_enabled": str(self.transport_enabled).lower(),
            "transport_ready": str(self.transport_ready).lower(),
        }


class LuaAuthoringVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.source = Path(self.temporary_directory.name) / "main.lua"
        self.original = (
            f'local source_version = "{verifier.BASELINE_VERSION}"\n'
        ).encode("utf-8")
        self.source.write_bytes(self.original)

    def test_offline_mode_reloads_rejects_syntax_and_restores_source(self) -> None:
        runtime = FakeAuthoringRuntime(
            self.source,
            transport_enabled=False,
            transport_ready=False,
        )
        with mock.patch.object(verifier, "_snapshot", runtime.snapshot):
            result = verifier.run(
                "test-pipe",
                self.source,
                "auto",
                timeout=1.0,
                settle_seconds=0.01,
            )

        evidence = result["evidence"]
        self.assertEqual(evidence["mode"], "offline")
        self.assertEqual(
            evidence["reloaded"]["version"],
            verifier.RELOADED_VERSION,
        )
        self.assertEqual(
            evidence["syntax_error_preserved"]["surface_handle"],
            evidence["reloaded"]["surface_handle"],
        )
        self.assertEqual(
            evidence["restored"]["version"],
            verifier.BASELINE_VERSION,
        )
        self.assertTrue(evidence["source_restored"])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_windows_lua_daemon_wait_reads_redirected_pipe(self) -> None:
        process = mock.Mock()
        process.stdout = io.StringIO("encoded-frame\n")
        try:
            with mock.patch.object(multiplayer_sync.os, "name", "nt"):
                multiplayer_sync._start_lua_daemon_reader("test-pipe", process)
                ready, line = multiplayer_sync._read_lua_daemon_line(
                    "test-pipe",
                    process,
                    timeout=0.25,
                )
        finally:
            multiplayer_sync._LUA_DAEMON_READ_QUEUES.pop("test-pipe", None)

        self.assertTrue(ready)
        self.assertEqual(line, "encoded-frame\n")

    def test_windows_lua_daemon_wait_times_out_without_select(self) -> None:
        process = mock.Mock()
        process.stdout = mock.Mock()
        multiplayer_sync._LUA_DAEMON_READ_QUEUES["test-pipe"] = queue.Queue()
        try:
            with (
                mock.patch.object(multiplayer_sync.os, "name", "nt"),
                mock.patch.object(
                    multiplayer_sync.select,
                    "select",
                    side_effect=AssertionError("select must not read Windows pipes"),
                ),
            ):
                ready, line = multiplayer_sync._read_lua_daemon_line(
                    "test-pipe",
                    process,
                    timeout=0.01,
                )
        finally:
            multiplayer_sync._LUA_DAEMON_READ_QUEUES.pop("test-pipe", None)

        self.assertFalse(ready)
        self.assertEqual(line, "")

    def test_transport_mode_defers_edits_and_restores_source(self) -> None:
        runtime = FakeAuthoringRuntime(
            self.source,
            transport_enabled=True,
            transport_ready=False,
        )
        with mock.patch.object(verifier, "_snapshot", runtime.snapshot):
            result = verifier.run(
                "test-pipe",
                self.source,
                "auto",
                timeout=1.0,
                settle_seconds=0.01,
            )

        evidence = result["evidence"]
        self.assertEqual(evidence["mode"], "deferred")
        self.assertEqual(
            evidence["deferred_candidate"]["surface_handle"],
            evidence["initial"]["surface_handle"],
        )
        self.assertEqual(
            evidence["restored"]["surface_handle"],
            evidence["initial"]["surface_handle"],
        )
        self.assertTrue(evidence["source_restored"])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_failed_verification_still_restores_exact_source(self) -> None:
        runtime = FakeAuthoringRuntime(
            self.source,
            transport_enabled=False,
            transport_ready=False,
        )

        def fail_candidate_then_accept_restore(
            _pipe_name: str,
            expected: str,
            _timeout: float,
        ) -> dict[str, str]:
            if expected == verifier.RELOADED_VERSION:
                raise verifier.VerifyFailure("forced verification failure")
            return runtime.snapshot("test-pipe")

        with (
            mock.patch.object(verifier, "_snapshot", runtime.snapshot),
            mock.patch.object(
                verifier,
                "_wait_for_version",
                fail_candidate_then_accept_restore,
            ),
            self.assertRaisesRegex(
                verifier.VerifyFailure,
                "forced verification failure",
            ),
        ):
            verifier.run(
                "test-pipe",
                self.source,
                "offline",
                timeout=1.0,
                settle_seconds=0.01,
            )

        self.assertEqual(self.source.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
