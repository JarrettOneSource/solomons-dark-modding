#!/usr/bin/env python3
"""Unit contracts for the exact seeded Boneyard decor verifier."""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_run_static_layout_sync as verifier  # noqa: E402


def float_bits(value: float) -> str:
    bits = struct.unpack("<I", struct.pack("<f", value))[0]
    return f"0x{bits:08X}"


def matching_layout() -> dict[str, str]:
    row = {
        "scene": "testrun",
        "local_run_nonce": "0x12345678",
        "circle_count": "8",
        "circle_mask4_count": "4",
        "circle_mask4_digest": "0x00000001",
        "shape_count": "2",
        "shape_digest": "0x00000002",
        "static_actor_count": "0",
        "static_actor_digest": "0x00000003",
        "boneyard_scenery_count": "3",
        "boneyard_scenery_sampled": "1",
        "boneyard_scenery_digest": "0x00000004",
        "boneyard_tree_count": "1",
        "boneyard_tree_digest": "0x00000005",
        "boneyard_road_count": "2",
        "boneyard_road_sampled": "0",
        "boneyard_road_digest": "0x00000006",
        "boneyard_fence_count": "1",
        "boneyard_fence_sampled": "0",
        "boneyard_fence_digest": "0x00000007",
        "boneyard_terrain_count": "0",
        "boneyard_terrain_sampled": "0",
        "boneyard_terrain_digest": "0x00000008",
        "boneyard_compact_count": "1",
        "boneyard_compact_sampled": "1",
        "boneyard_compact_digest": "0x00000009",
        "boneyard_compact_ignored_flag_bits_count": "0",
        "boneyard_compact_type_7_8_count": "1",
        "boneyard_compact_type_7_8_noncanonical_flags": "0",
        "boneyard_compact_type_21_24_count": "1",
        "replicated_run_static_count": "0",
        "replicated_matched_actor_count": "0",
    }
    for type_id in (
        2001,
        2009,
        2029,
        2040,
        2061,
        2062,
        3006,
        3007,
        3011,
        3012,
        3013,
        3014,
    ):
        row[f"boneyard_scenery_type_{type_id}_count"] = (
            "1" if type_id == 2001 else "0"
        )
    for family in (
        "tree_ground_cover",
        "ground_patches",
        "paving_stones",
        "pebbles",
        "twig_lattice",
        "large_rocks",
        "shadow_masks",
        "dead_roots",
    ):
        row[f"boneyard_compact_family_{family}_count"] = (
            "1" if family == "large_rocks" else "0"
        )
    return row


class RunStaticLayoutSyncTest(unittest.TestCase):
    def test_exact_tree_and_compact_tables_decode_float_bits(self) -> None:
        row = matching_layout()
        row.update(
            {
                "boneyard_tree.1.type_id": "2001",
                "boneyard_tree.1.x_bits": float_bits(125.5),
                "boneyard_tree.1.y_bits": float_bits(-32.25),
                "boneyard_tree.1.radius_bits": float_bits(48.0),
                "boneyard_tree.1.materialization_key": "-3200",
                "boneyard_tree.1.variant": "6",
                "boneyard_tree.1.overlay_variant": "2",
                "boneyard_tree.1.overlay_enabled": "1",
                "boneyard_tree.1.phase_bits": float_bits(0.25),
                "boneyard_tree.1.render_parameter_bits": float_bits(1.0),
                "boneyard_tree.1.sway_countdown": "25",
                "boneyard_tree.1.sway_target_bits": float_bits(1.0),
                "boneyard_tree.1.sway_current_bits": float_bits(1.0),
                "boneyard_tree.1.scrub_collision_flag": "0",
                "boneyard_tree.1.native_index": "4",
                "boneyard_scenery.1.row": ",".join(
                    (
                        "4",
                        "2001",
                        str(int(float_bits(125.5), 0)),
                        str(int(float_bits(-32.25), 0)),
                        str(int(float_bits(48.0), 0)),
                        "-3200",
                        "0",
                        "0",
                        "0",
                        str(int(float_bits(1.0), 0)),
                        "0",
                        str(int(float_bits(1.0), 0)),
                        str(int(float_bits(1.0), 0)),
                        "0",
                        "0",
                        "0",
                        str(int(float_bits(1.0), 0)),
                        str(int(float_bits(1.0), 0)),
                        "5",
                        "6",
                        "2",
                        "1",
                        str(int(float_bits(1.0), 0)),
                        str(int(float_bits(1.0), 0)),
                    )
                ),
                "boneyard_compact.1.row": ",".join(
                    (
                        "8",
                        "7",
                        float_bits(128.0),
                        float_bits(-30.0),
                        float_bits(-3.5),
                        float_bits(0.875),
                        float_bits(1.0),
                        "1",
                        float_bits(112.0),
                        float_bits(-46.0),
                        float_bits(144.0),
                        float_bits(-14.0),
                    )
                ),
            }
        )

        tables = verifier.decor_tables(row)
        self.assertEqual(tables["trees"][0]["type_id"], 2001)
        self.assertEqual(tables["trees"][0]["position"], [125.5, -32.25])
        self.assertEqual(tables["trees"][0]["variant"], 6)
        self.assertNotIn("sway_countdown", tables["trees"][0])
        self.assertEqual(tables["trees"][0]["native_index"], 4)
        self.assertEqual(tables["compact"][0]["type_id"], 7)
        self.assertEqual(tables["compact"][0]["native_index"], 8)
        self.assertEqual(tables["compact"][0]["position"], [128.0, -30.0])
        self.assertEqual(tables["compact"][0]["rotation"], -3.5)
        self.assertEqual(tables["compact"][0]["scale"], 0.875)
        self.assertEqual(tables["compact"][0]["flags"], 1)
        self.assertEqual(
            tables["compact"][0]["bounds_bits"][0],
            int(float_bits(112.0), 0),
        )

    def test_layout_match_requires_canonical_type_7_8_flags(self) -> None:
        host = matching_layout()
        client = matching_layout()
        self.assertTrue(verifier.layouts_match(host, client))

        client["boneyard_compact_type_7_8_noncanonical_flags"] = "1"
        self.assertFalse(verifier.layouts_match(host, client))

    def test_camera_target_selects_a_central_tree_and_nearby_compact(self) -> None:
        decor = {
            "trees": [
                {"position": [0.0, 0.0]},
                {"position": [1000.0, 1000.0]},
            ],
            "compact": [
                {"type_id": 7, "position": [995.0, 1000.0], "flags": 1},
                {"type_id": 8, "position": [100.0, 100.0], "flags": 1},
            ],
        }
        target = verifier.matched_camera_target(decor)
        self.assertEqual(target["position"], [0.0, 0.0])
        self.assertEqual(target["nearby_compact"]["position"], [100.0, 100.0])
        self.assertAlmostEqual(target["nearby_compact_distance"], 2**0.5 * 100)

    def test_frame_correlation_rejects_a_displaced_world_region(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            host_path = root / "host.png"
            client_path = root / "client.png"
            displaced_path = root / "displaced.png"
            image = Image.new("RGB", (400, 240), "black")
            for x in range(80, 160):
                for y in range(60, 180):
                    image.putpixel((x, y), (220, 180, 120))
            image.save(host_path)
            image.save(client_path)

            displaced = Image.new("RGB", image.size, "black")
            for x in range(240, 320):
                for y in range(60, 180):
                    displaced.putpixel((x, y), (220, 180, 120))
            displaced.save(displaced_path)

            matched = verifier.matched_frame_correlation(
                host_path, client_path
            )
            mismatched = verifier.matched_frame_correlation(
                host_path, displaced_path
            )
            self.assertAlmostEqual(matched["grayscale_correlation"], 1.0)
            self.assertAlmostEqual(matched["edge_correlation"], 1.0)
            self.assertLess(mismatched["grayscale_correlation"], 0.75)
            self.assertLess(mismatched["edge_correlation"], 0.65)


if __name__ == "__main__":
    unittest.main()
