#!/usr/bin/env python3
"""Regression tests for the live multiplayer healthbar verifier."""

from __future__ import annotations

import inspect
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_multiplayer_hud_names as verifier  # noqa: E402


class MultiplayerHudNamesVerifierTests(unittest.TestCase):
    def test_live_verifier_uses_quick_start_and_exact_process_cleanup(
        self,
    ) -> None:
        source = inspect.getsource(verifier.run_live_verification)

        for token in (
            "quick_start=True",
            "kill_existing=False",
            "tile_windows=False",
            "exact_mod_id=ACCEPTANCE_MOD_ID",
            "stop_game_processes(process_ids)",
        ):
            self.assertIn(token, source)
        self.assertNotIn("stop_games(", inspect.getsource(verifier))

    def test_generated_instance_prefix_stays_below_native_path_limit(
        self,
    ) -> None:
        prefix = verifier._default_instance_prefix()

        self.assertRegex(prefix, r"^[A-Za-z0-9][A-Za-z0-9._-]+$")
        self.assertLessEqual(len(prefix), 48)

    def test_loopback_transport_evidence_rejects_wildcard_bind(self) -> None:
        loopback_line = (
            "Multiplayer local UDP transport initialized. role=host "
            "local_port=42000 bind=127.0.0.1 "
            "remote=127.0.0.1:42001 participant_id=1"
        )

        self.assertEqual(
            verifier.verify_loopback_transport_log(loopback_line),
            loopback_line,
        )
        with self.assertRaises(verifier.VerifyFailure):
            verifier.verify_loopback_transport_log(
                loopback_line.replace("bind=127.0.0.1", "bind=0.0.0.0"),
            )

    def test_half_healthbar_pixels_are_required_in_captured_backbuffer(
        self,
    ) -> None:
        geometry = {
            "health_ratio": 0.5,
            "left": 10.0,
            "top": 10.0,
            "right": 74.0,
            "bottom": 17.0,
        }
        with tempfile.TemporaryDirectory() as temporary:
            capture = Path(temporary) / "healthbar.png"
            image = Image.new("RGB", (100, 40), (20, 50, 90))
            draw = ImageDraw.Draw(image)
            draw.rectangle((10, 10, 73, 16), fill=(12, 6, 6))
            draw.rectangle((11, 11, 72, 15), fill=(54, 13, 13))
            draw.rectangle((11, 11, 41, 15), fill=(190, 31, 24))
            draw.line((11, 11, 41, 11), fill=(255, 105, 78))
            image.save(capture)

            evidence = verifier.verify_health_bar_pixels(capture, geometry)

        self.assertGreater(evidence["filled_health_pixels"], 0)
        self.assertGreater(evidence["empty_pixels"], 0)

    def test_missing_healthbar_pixels_fail_even_when_capture_is_not_blank(
        self,
    ) -> None:
        geometry = {
            "health_ratio": 0.5,
            "left": 10.0,
            "top": 10.0,
            "right": 74.0,
            "bottom": 17.0,
        }
        with tempfile.TemporaryDirectory() as temporary:
            capture = Path(temporary) / "missing-healthbar.png"
            Image.new("RGB", (100, 40), (20, 50, 90)).save(capture)

            with self.assertRaisesRegex(
                verifier.VerifyFailure,
                "healthbar pixels",
            ):
                verifier.verify_health_bar_pixels(capture, geometry)


if __name__ == "__main__":
    unittest.main()
