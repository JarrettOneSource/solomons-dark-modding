#!/usr/bin/env python3
"""Regression tests for the recovered stock item/FX grammar and catalog."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPOSITORY_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from build_native_item_catalog import parse_document  # noqa: E402


ITEM_CATALOG = REPOSITORY_ROOT / "docs/reverse-engineering/native-item-catalog.json"


class NativeItemToolsTest(unittest.TestCase):
    def test_fragment_parser_preserves_overrides_and_resolves_fx_targets(self) -> None:
        fixture = b"""
<ITEMSET>
  <NAME>Fixture Set</NAME>
  <FX>FX_SPELLCLASSMANACOST -20% AIR</FX>
  <ITEM>
    <TYPE>Staff</TYPE>
    <NAME>Override Staff</NAME>
    <IMAGE>5</IMAGE>
    <IMAGE>0</IMAGE>
    <FX>FX_ADDSKILL \"Call Leviathan\" +1</FX>
    <RARITY>RARE</RARITY>
  </ITEM>
</ITEMSET>
<ITEM>
  <TYPE>hat</TYPE>
  <NAME>Two-Layer Hat</NAME>
  <IMAGE>3</IMAGE>
  <COLOR1>255,0,128</COLOR1>
  <RARITY>EPIC</RARITY>
</ITEM>
<IGNORE>Effect=FX_SPELLDAMAGE +5%;</IGNORE>
"""
        catalog = parse_document(fixture, "fixture/items.cfg")
        self.assertEqual(catalog["summary"]["item_set_count"], 1)
        self.assertEqual(catalog["summary"]["item_count"], 2)
        self.assertEqual(catalog["summary"]["fx_count"], 2)

        staff = catalog["items"][0]
        self.assertEqual(staff["image_declarations"], [5, 0])
        self.assertEqual(staff["effective_image"], 0)
        self.assertTrue(staff["duplicate_image_declaration"])
        self.assertEqual(staff["art"]["inventory_records"], [72])
        self.assertEqual(staff["fx"][0]["target_kind"], "skill")
        self.assertEqual(staff["fx"][0]["target_id"], 11)
        self.assertEqual(staff["fx"][0]["magnitude"], 1)

        set_fx = catalog["item_sets"][0]["fx"][0]
        self.assertEqual(set_fx["kind_id"], 11)
        self.assertEqual(set_fx["operator_id"], 2)
        self.assertEqual(set_fx["magnitude"], -20)
        self.assertEqual(set_fx["target_name"], "Air")
        self.assertEqual(set_fx["target_id"], 2)

        hat = catalog["items"][1]
        self.assertEqual(hat["art"]["inventory_records"], [37, 41])
        self.assertEqual(
            hat["effective_color1"]["normalized_rgba"],
            [1.0, 0.0, 128 / 255.0, 1.0],
        )

    def test_checked_in_stock_catalog_invariants(self) -> None:
        catalog = json.loads(ITEM_CATALOG.read_text(encoding="utf-8"))
        summary = catalog["summary"]
        self.assertEqual(summary["item_set_count"], 7)
        self.assertEqual(summary["item_count"], 47)
        self.assertEqual(summary["set_member_item_count"], 29)
        self.assertEqual(summary["top_level_item_count"], 18)
        self.assertEqual(summary["fx_count"], 86)
        self.assertEqual(
            summary["type_counts"],
            {"amulet": 9, "hat": 6, "ring": 13, "robe": 7, "staff": 4, "wand": 8},
        )
        self.assertEqual(summary["rarity_counts"], {"Epic": 24, "Rare": 23})
        self.assertEqual(summary["image_declaration_count"], 48)
        self.assertEqual(summary["duplicate_image_item_count"], 1)

        boomstick = next(item for item in catalog["items"] if item["name"] == "Absolox's Boomstick")
        self.assertEqual(boomstick["image_declarations"], [5, 0])
        self.assertEqual(boomstick["effective_image"], 0)
        self.assertEqual(boomstick["art"]["inventory_records"], [72])

        combinator = next(entry for entry in catalog["item_sets"] if entry["name"] == "Combinator's Coutrement")
        self.assertEqual([effect["kind_id"] for effect in combinator["fx"]], [37, 38])


if __name__ == "__main__":
    unittest.main()
