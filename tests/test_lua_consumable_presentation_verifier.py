from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_lua_consumable_presentation as verifier  # noqa: E402


class LuaConsumablePresentationVerifierTests(unittest.TestCase):
    def test_strong_green_stats_rejects_muted_inventory_background(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "muted.png"
            Image.new("RGB", (16, 12), (38, 90, 55)).save(path)

            stats = verifier.strong_green_stats(path)

        self.assertEqual(stats["strong_green_pixels"], 0)
        self.assertEqual(stats["maximum_green"], 0)

    def test_strong_green_stats_accepts_registered_icon_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "icon.png"
            image = Image.new("RGB", (16, 12), (20, 20, 20))
            for y in range(6):
                for x in range(12):
                    image.putpixel((x, y), (25, 230, 35))
            image.save(path)

            stats = verifier.strong_green_stats(path)

        self.assertEqual(stats["strong_green_pixels"], 72)
        self.assertEqual(stats["maximum_green"], 230)

    def test_inventory_icon_requires_new_green_pixels_when_opened(self) -> None:
        closed = {
            "width": 800,
            "height": 600,
            "strong_green_pixels": 20,
            "maximum_green": 220,
        }
        opened = dict(closed, strong_green_pixels=90)
        unchanged = dict(closed, strong_green_pixels=55)

        self.assertTrue(verifier.inventory_icon_visible(closed, opened))
        self.assertFalse(verifier.inventory_icon_visible(closed, unchanged))


if __name__ == "__main__":
    unittest.main()
