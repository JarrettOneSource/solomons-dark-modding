#!/usr/bin/env python3
"""Unit contracts for the exact seeded Boneyard decor verifier."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_run_static_layout_sync as verifier  # noqa: E402


def float_bits(value: float) -> str:
    bits = struct.unpack("<I", struct.pack("<f", value))[0]
    return f"0x{bits:08X}"


def matching_layout() -> dict[str, str]:
    return {
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
        "boneyard_scenery_digest": "0x00000004",
        "boneyard_tree_count": "1",
        "boneyard_tree_digest": "0x00000005",
        "boneyard_compact_count": "1",
        "boneyard_compact_sampled": "1",
        "boneyard_compact_digest": "0x00000006",
        "boneyard_compact_ignored_flag_bits_count": "0",
        "boneyard_compact_type_7_8_count": "1",
        "boneyard_compact_type_7_8_noncanonical_flags": "0",
        "replicated_run_static_count": "0",
        "replicated_matched_actor_count": "0",
    }


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
                "boneyard_compact.1.row": ",".join(
                    (
                        "7",
                        float_bits(128.0),
                        float_bits(-30.0),
                        float_bits(-3.5),
                        float_bits(0.875),
                        float_bits(1.0),
                        "1",
                    )
                ),
            }
        )

        tables = verifier.decor_tables(row)
        self.assertEqual(tables["trees"][0]["type_id"], 2001)
        self.assertEqual(tables["trees"][0]["position"], [125.5, -32.25])
        self.assertEqual(tables["trees"][0]["variant"], 6)
        self.assertEqual(tables["compact"][0]["type_id"], 7)
        self.assertEqual(tables["compact"][0]["position"], [128.0, -30.0])
        self.assertEqual(tables["compact"][0]["rotation"], -3.5)
        self.assertEqual(tables["compact"][0]["scale"], 0.875)
        self.assertEqual(tables["compact"][0]["flags"], 1)

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


if __name__ == "__main__":
    unittest.main()
