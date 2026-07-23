#!/usr/bin/env python3
"""Pixel-analysis tests for the native Lua UI authoring verifier."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from verify_local_multiplayer_sync import VerifyFailure  # noqa: E402
from verify_lua_ui_authoring import inspect_native_ui_pixels  # noqa: E402


class LuaUiAuthoringVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.baseline = self.root / "baseline.png"
        self.visible = self.root / "visible.png"

    def _save_pair(
        self,
        baseline: Image.Image,
        visible: Image.Image,
    ) -> None:
        baseline.save(self.baseline)
        visible.save(self.visible)

    def test_localized_surface_change_passes(self) -> None:
        baseline = Image.new("RGB", (200, 120), (12, 16, 20))
        visible = baseline.copy()
        for y in range(24, 96):
            for x in range(40, 160):
                visible.putpixel((x, y), (160, 180, 200))
        self._save_pair(baseline, visible)

        evidence = inspect_native_ui_pixels(self.baseline, self.visible)

        self.assertGreater(evidence["changed_inside"], 8000)
        self.assertEqual(evidence["changed_outside"], 0)

    def test_identical_frames_fail(self) -> None:
        image = Image.new("RGB", (200, 120), (12, 16, 20))
        self._save_pair(image, image)

        with self.assertRaisesRegex(
            VerifyFailure,
            "native pixels were not localized",
        ):
            inspect_native_ui_pixels(self.baseline, self.visible)

    def test_whole_frame_change_is_not_surface_evidence(self) -> None:
        baseline = Image.new("RGB", (200, 120), (0, 0, 0))
        visible = Image.new("RGB", (200, 120), (255, 255, 255))
        self._save_pair(baseline, visible)

        with self.assertRaisesRegex(
            VerifyFailure,
            "native pixels were not localized",
        ):
            inspect_native_ui_pixels(self.baseline, self.visible)


if __name__ == "__main__":
    unittest.main()
