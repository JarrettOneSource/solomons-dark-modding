from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from multiplayer_frame_capture import convert_and_validate_backbuffer
from verify_local_multiplayer_sync import VerifyFailure


def detailed_dark_frame(width: int, height: int, dominant_fraction: float) -> Image.Image:
    pixel_count = width * height
    dominant_count = int(pixel_count * dominant_fraction)
    pixels = [(0, 0, 0)] * dominant_count
    for index in range(pixel_count - dominant_count):
        value = index + 1
        pixels.append((value & 0xFF, (value >> 8) & 0xFF, (value * 37) & 0xFF))
    image = Image.new("RGB", (width, height))
    image.putdata(pixels)
    return image


class BackbufferQualityTests(unittest.TestCase):
    def test_accepts_a_detailed_dark_game_frame(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw_path = Path(directory) / "frame.bmp"
            output_path = Path(directory) / "frame.png"
            detailed_dark_frame(200, 200, 0.74).save(raw_path)

            quality = convert_and_validate_backbuffer(raw_path, output_path)

            self.assertGreater(quality["unique_colors"], 1000)
            self.assertAlmostEqual(quality["dominant_fraction"], 0.74, places=2)
            self.assertTrue(output_path.is_file())

    def test_rejects_a_nearly_blank_frame_even_with_colored_noise(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw_path = Path(directory) / "frame.bmp"
            output_path = Path(directory) / "frame.png"
            detailed_dark_frame(400, 400, 0.99).save(raw_path)

            with self.assertRaises(VerifyFailure):
                convert_and_validate_backbuffer(raw_path, output_path)


if __name__ == "__main__":
    unittest.main()
