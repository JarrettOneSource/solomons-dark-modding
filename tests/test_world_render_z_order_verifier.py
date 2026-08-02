#!/usr/bin/env python3
"""Regression tests for the native world-render acceptance harness."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


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


if __name__ == "__main__":
    unittest.main()
