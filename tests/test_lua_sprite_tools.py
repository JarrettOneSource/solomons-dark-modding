#!/usr/bin/env python3
"""Regression tests for Lua sprite bundle authoring and pixel acceptance."""

from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import build_lua_sprite_bundle as bundle_builder  # noqa: E402
from extract_bundles import parse_bundle  # noqa: E402
from verify_local_multiplayer_sync import VerifyFailure  # noqa: E402
from verify_lua_sprites import inspect_sprite_pixels  # noqa: E402


class LuaSpriteBundleBuilderTests(unittest.TestCase):
    def test_builder_round_trips_common_records_and_point_tails(self) -> None:
        document = {
            "frames": [
                {
                    "x": 0,
                    "y": 0,
                    "width": 16,
                    "height": 16,
                    "logical_width": 20,
                    "logical_height": 18,
                    "center_offset_x": 1.5,
                    "points": [[2, 3]],
                },
                {
                    "x": 16,
                    "y": 0,
                    "width": 8,
                    "height": 12,
                    "logical_width": 8,
                    "logical_height": 12,
                },
            ]
        }

        payload = bundle_builder.build_bundle(document)
        self.assertEqual(len(payload), 98)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "atlas.bundle"
            path.write_bytes(payload)
            records, groups = parse_bundle(path)

        self.assertEqual(groups, [])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].end, 53)
        self.assertEqual(records[0].point_count, 1)
        self.assertEqual(records[0].logical_width, 20)
        self.assertEqual(records[0].logical_height, 18)
        self.assertEqual(records[0].content_width, 16)
        self.assertEqual(records[0].center_offset_x, 1.5)
        self.assertEqual(records[1].offset, 53)
        self.assertEqual(records[1].end, 98)

    def test_builder_rejects_nonfinite_unknown_and_oversized_input(self) -> None:
        base = {
            "x": 0,
            "y": 0,
            "width": 16,
            "height": 16,
            "logical_width": 16,
            "logical_height": 16,
        }
        invalid_frames = (
            {**base, "x": math.nan},
            {**base, "width": 0},
            {**base, "logical_height": 16_385},
            {**base, "rotated": True},
            {**base, "points": [[math.inf, 0]]},
        )
        for frame in invalid_frames:
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                bundle_builder.build_bundle({"frames": [frame]})

        with mock.patch.object(bundle_builder, "MAX_BUNDLE_BYTES", 44):
            with self.assertRaisesRegex(ValueError, "runtime limit"):
                bundle_builder.build_bundle({"frames": [base]})


class LuaSpritePixelAcceptanceTests(unittest.TestCase):
    def test_pixel_inspector_requires_backdrop_and_visible_sprite(self) -> None:
        image = Image.new("RGB", (200, 200), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 191, 191), fill=(231, 19, 173))
        draw.rectangle((60, 60, 139, 139), fill=(12, 180, 240))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "accepted.png"
            image.save(path)
            counts = inspect_sprite_pixels(path, 0, 0)

        self.assertGreaterEqual(counts["magenta_backdrop_pixels"], 2000)
        self.assertGreaterEqual(counts["sprite_non_backdrop_pixels"], 64)

    def test_pixel_inspector_rejects_an_empty_sprite_frame(self) -> None:
        image = Image.new("RGB", (200, 200), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 191, 191), fill=(231, 19, 173))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.png"
            image.save(path)
            with self.assertRaises(VerifyFailure):
                inspect_sprite_pixels(path, 0, 0)


if __name__ == "__main__":
    unittest.main()
