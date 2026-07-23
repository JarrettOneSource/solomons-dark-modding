#!/usr/bin/env python3
"""Keep the launcher manifest and native wire protocol on one version."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NATIVE_PROTOCOL = (
    ROOT / "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
)
LAUNCHER_COMPATIBILITY = (
    ROOT
    / "SolomonDarkModLauncher/src/Staging/"
    "MultiplayerCompatibilityMaterializer.cs"
)
WAVE_DOCUMENTATION = ROOT / "docs/lua-waves.md"
LUA_SEAM_ROADMAP = ROOT / "docs/lua-seam-roadmap.md"
STATE_EVENTS_DOCUMENTATION = ROOT / "docs/lua-state-and-events.md"


def _read_version(path: Path, pattern: str) -> int:
    match = re.search(pattern, path.read_text(encoding="utf-8"))
    if match is None:
        raise AssertionError(f"protocol version declaration is missing: {path}")
    return int(match.group(1))


class ProtocolVersionAlignmentTests(unittest.TestCase):
    def test_launcher_manifest_matches_native_wire_protocol(self) -> None:
        native = _read_version(
            NATIVE_PROTOCOL,
            r"kProtocolVersion\s*=\s*(\d+);",
        )
        launcher = _read_version(
            LAUNCHER_COMPATIBILITY,
            r"CurrentProtocolVersion\s*=\s*(\d+);",
        )

        self.assertEqual(native, launcher)

    def test_wave_documentation_matches_native_wire_protocol(self) -> None:
        native = _read_version(
            NATIVE_PROTOCOL,
            r"kProtocolVersion\s*=\s*(\d+);",
        )
        documentation = _read_version(
            WAVE_DOCUMENTATION,
            r"current\s+protocol\s+version\s+is\s+(\d+);",
        )

        self.assertEqual(native, documentation)

    def test_lua_seam_roadmap_matches_native_wire_protocol(self) -> None:
        native = _read_version(
            NATIVE_PROTOCOL,
            r"kProtocolVersion\s*=\s*(\d+);",
        )
        roadmap = _read_version(
            LUA_SEAM_ROADMAP,
            r"\*\*Implemented 2026-07-22\.\*\* Protocol (\d+) provides",
        )

        self.assertEqual(native, roadmap)

    def test_state_events_documentation_matches_native_wire_protocol(self) -> None:
        native = _read_version(
            NATIVE_PROTOCOL,
            r"kProtocolVersion\s*=\s*(\d+);",
        )
        documentation = _read_version(
            STATE_EVENTS_DOCUMENTATION,
            r"Protocol version (\d+) carries the host-authored Lua stream",
        )

        self.assertEqual(native, documentation)


if __name__ == "__main__":
    unittest.main()
