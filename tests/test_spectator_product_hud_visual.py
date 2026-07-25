#!/usr/bin/env python3
"""Pixel contracts for the native spectator product HUD."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from spectator_product_hud_visual import (  # noqa: E402
    inspect_spectator_product_hud_pixels,
)


class SpectatorProductHudVisualTests(unittest.TestCase):
    def _write_image(
        self,
        path: Path,
        *,
        gold_region: tuple[int, int, int, int] | None,
    ) -> None:
        image = Image.new("RGB", (400, 240), (8, 12, 16))
        if gold_region is not None:
            ImageDraw.Draw(image).rectangle(
                gold_region,
                fill=(230, 190, 90),
            )
        image.save(path)

    def test_visible_contract_requires_gold_text_inside_hud_region(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "visible.png"
            self._write_image(
                path,
                gold_region=(90, 20, 150, 30),
            )

            result = inspect_spectator_product_hud_pixels(
                path,
                expected_visible=True,
            )

            self.assertTrue(result["matches"])
            self.assertGreaterEqual(result["gold_pixels"], 500)

    def test_hidden_contract_rejects_product_text_pixels(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hidden.png"
            self._write_image(path, gold_region=None)
            self.assertTrue(
                inspect_spectator_product_hud_pixels(
                    path,
                    expected_visible=False,
                )["matches"]
            )

            self._write_image(
                path,
                gold_region=(90, 20, 150, 30),
            )
            with self.assertRaisesRegex(
                Exception,
                "non-spectating",
            ):
                inspect_spectator_product_hud_pixels(
                    path,
                    expected_visible=False,
                )

    def test_hidden_contract_allows_stock_player_name_label_budget(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "player-label.png"
            self._write_image(
                path,
                gold_region=(90, 20, 116, 30),
            )

            result = inspect_spectator_product_hud_pixels(
                path,
                expected_visible=False,
            )

            self.assertTrue(result["matches"])
            self.assertLessEqual(result["gold_pixels"], 400)

    def test_gold_pixels_on_a_world_actor_do_not_satisfy_hud_region(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "migrated.png"
            self._write_image(
                path,
                gold_region=(170, 150, 240, 165),
            )

            with self.assertRaisesRegex(
                Exception,
                "not visible in the backbuffer",
            ):
                inspect_spectator_product_hud_pixels(
                    path,
                    expected_visible=True,
                )
