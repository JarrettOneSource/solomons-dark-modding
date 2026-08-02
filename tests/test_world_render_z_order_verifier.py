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


if __name__ == "__main__":
    unittest.main()
