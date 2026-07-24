#!/usr/bin/env python3
"""Regression tests for the live Lua draw verifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_lua_draw as verifier  # noqa: E402


class LuaDrawVerifierTests(unittest.TestCase):
    def test_pixel_verification_retries_until_committed_frame_is_rendered(
        self,
    ) -> None:
        capture = {"capture_method": "d3d9_backbuffer"}
        pixels = {"green_fill_pixels": 6272}

        with (
            mock.patch.object(
                verifier,
                "capture_game_backbuffer",
                side_effect=(capture, capture),
            ) as capture_backbuffer,
            mock.patch.object(
                verifier,
                "inspect_acceptance_pixels",
                side_effect=(
                    verifier.VerifyFailure(
                        "new display list has not reached EndScene"
                    ),
                    pixels,
                ),
            ) as inspect_pixels,
            mock.patch.object(verifier.time, "sleep") as sleep,
        ):
            actual_capture, actual_pixels = (
                verifier.capture_acceptance_frame(
                    "isolated-pipe",
                    ROOT / "runtime" / "unused.png",
                    game_path_kind="windows",
                    origin_y=666,
                    timeout=1.0,
                )
            )

        self.assertEqual(actual_capture, capture)
        self.assertEqual(actual_pixels, pixels)
        self.assertEqual(capture_backbuffer.call_count, 2)
        self.assertEqual(inspect_pixels.call_count, 2)
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
