#!/usr/bin/env python3
"""Regression tests for the native world-render acceptance harness."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_world_render_z_order as verifier  # noqa: E402


class WorldRenderZOrderVerifierTests(unittest.TestCase):
    def test_loot_rows_accepts_the_public_potion_kind_label(self) -> None:
        output = "281612415664129|6|390.0|310.0|25.0|true|287346288\n"

        with mock.patch.object(verifier.sync, "lua", return_value=output) as lua:
            rows = verifier.loot_rows("test-pipe")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["item_slot"], 6)
        self.assertTrue(rows[0]["materialized"])
        self.assertIn('row.kind == "Potion"', lua.call_args.args[1])

    def test_capture_projection_uses_the_stock_region_camera(self) -> None:
        projected = "".join(
            (
                "drop.x=310\n",
                "drop.y=418\n",
                "drop.visible=true\n",
                "drop.width=1600\n",
                "drop.height=900\n",
            )
        )

        with mock.patch.object(
            verifier,
            "parse_values",
            return_value=verifier.sync.parse_key_values(projected),
        ) as parse:
            result = verifier.projections("test-pipe", {"drop": (230, 310)})

        self.assertEqual(result["drop"]["x"], 310)
        code = parse.call_args.args[1]
        self.assertIn("sd.camera.get_state()", code)
        self.assertIn("(x - camera.origin_x) * camera.scale", code)
        self.assertNotIn("sd.draw.world_to_screen", code)

    def test_potion_template_ignores_same_color_actor_pixels_off_mask(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference_path = root / "reference.png"
            control_path = root / "control.png"
            occluded_path = root / "occluded.png"
            reference = Image.new("RGB", (80, 80), (20, 20, 20))
            for y in range(32, 48):
                for x in range(35, 45):
                    reference.putpixel((x, y), (180, 40, 35))
            reference.save(reference_path)
            reference.save(control_path)

            occluded = Image.new("RGB", (80, 80), (20, 20, 20))
            for y in range(50, 70):
                for x in range(20, 60):
                    occluded.putpixel((x, y), (220, 30, 25))
            occluded.save(occluded_path)
            point = {"x": 40, "y": 40}

            control = verifier.potion_template_stats(
                reference_path,
                point,
                control_path,
                point,
                color="red",
            )
            actor_front = verifier.potion_template_stats(
                reference_path,
                point,
                occluded_path,
                point,
                color="red",
            )

        self.assertEqual(control["remaining_ratio"], 1.0)
        self.assertEqual(actor_front["remaining_ratio"], 0.0)

    def test_potion_location_calibrates_vertical_capture_offset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            image_path = Path(temporary) / "capture.png"
            image = Image.new("RGB", (120, 120), (20, 20, 20))
            for y in range(25, 35):
                for x in range(55, 65):
                    image.putpixel((x, y), (30, 180, 20))
            image.save(image_path)

            location = verifier.locate_potion_color(
                image_path,
                {"x": 60, "y": 70},
                color="green",
            )

        self.assertEqual(location["matching_pixels"], 100)
        self.assertEqual(location["center_y"], 29.5)
        self.assertEqual(location["bounds"], [55, 25, 64, 34])

    def test_pickup_range_hold_writes_the_stock_derived_field(self) -> None:
        output = "".join(
            (
                "address=287310204\n",
                "previous=2.0\n",
                "wrote=true\n",
                "current=0.01\n",
            )
        )
        with mock.patch.object(
            verifier,
            "parse_values",
            return_value=verifier.sync.parse_key_values(output),
        ) as parse:
            result = verifier.set_local_pickup_range(
                "test-pipe",
                pickup_range=0.01,
            )

        self.assertEqual(result["previous"], "2.0")
        code = parse.call_args.args[1]
        self.assertIn("player.progression_address", code)
        self.assertIn("progression + 0xCC", code)
        self.assertIn("sd.debug.write_float(address, 0.01)", code)


if __name__ == "__main__":
    unittest.main()
