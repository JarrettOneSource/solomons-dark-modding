#!/usr/bin/env python3
"""Regression tests for the recovered Boneyard scripting object model."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPOSITORY_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import decode_boneyard_scripts  # noqa: E402


ALPHA = REPOSITORY_ROOT / "mods/mpk_boneyard_alpha/files/Alpha Arena.boneyard"
BETA = REPOSITORY_ROOT / "mods/mpk_boneyard_beta/files/Beta Arena.boneyard"


class BoneyardScriptingDecoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.alpha = decode_boneyard_scripts.decode_boneyard(ALPHA)

    def test_alpha_trigger_and_script_graph_is_exact(self) -> None:
        self.assertEqual(
            self.alpha["sha256"],
            "d596b4915140f5faa23fd1286e3d622c6189ecb00b9667f5e7b3444a84b8322b",
        )
        control = self.alpha["triggerControl"]
        self.assertEqual(len(control["triggers"]), 9)
        self.assertEqual(len(control["scripts"]), 9)
        self.assertEqual(control["flags"], [])
        self.assertEqual(control["counters"], [])

        triggers = {trigger["uid"]: trigger for trigger in control["triggers"]}
        self.assertEqual(triggers[43229]["typeName"], "START GAME")
        self.assertEqual(triggers[43229]["primaryScriptUid"], 43228)
        self.assertEqual(triggers[43231]["conditionMode"], "ALL")
        self.assertEqual(triggers[43231]["conditions"][0]["id"], 1)
        self.assertEqual(
            [operand["value"] for operand in triggers[43231]["conditions"][0]["operands"]],
            [1, 0],
        )

        scripts = {script["uid"]: script for script in control["scripts"]}
        self.assertEqual(
            [line["id"] for line in scripts[51934]["lines"]],
            [1065, 1002, 1066],
        )
        self.assertEqual(scripts[56484]["lines"][0]["id"], 1067)
        self.assertEqual(scripts[56484]["lines"][0]["operands"][0]["value"], 56480)
        self.assertEqual(scripts[57434]["lines"][0]["operands"][0]["value"], 57310)

    def test_alpha_timeline_events_and_recipe_links_are_exact(self) -> None:
        self.assertEqual(len(self.alpha["timelines"]), 1)
        timeline = self.alpha["timelines"][0]
        self.assertEqual((timeline["uid"], timeline["name"]), (56480, "Skeletons"))
        self.assertFalse(timeline["enabled"])
        self.assertEqual(len(timeline["events"]), 26)
        self.assertEqual(
            [event["type"] for event in timeline["events"]],
            [0, 0, 2, 3, 6, 0, 6, 6, 2, 0, 0, 2, 0, 1, 2, 6, 0, 6, 0, 2, 0, 6, 2, 1, 0, 1],
        )
        self.assertEqual(timeline["events"][13]["uidValues"], [57433])
        self.assertEqual(timeline["events"][23]["uidValues"], [57567])
        self.assertEqual(timeline["events"][25]["uidValues"], [95529])
        self.assertEqual(timeline["events"][0]["records"][0]["id"], 3001)
        self.assertEqual(timeline["events"][0]["intValues"], [8, 0, 0])

        recipes = self.alpha["recipes"]
        self.assertEqual(len(recipes["monsterRecipes"]), 1)
        recipe = recipes["monsterRecipes"][0]
        self.assertEqual((recipe["uid"], recipe["name"]), (57310, "Rotten Tom"))
        self.assertEqual((recipe["maxHp"], recipe["primaryDamage"]), (35.0, 5.0))
        self.assertEqual(recipes["uidGroups"], [])
        self.assertEqual(recipes["itemRecipes"], [])
        self.assertEqual(recipes["itemSets"], [])
        self.assertEqual(recipes["npcRecipes"], [])

    def test_stock_editor_surface_excludes_runtime_only_gaps(self) -> None:
        self.assertEqual(len(decode_boneyard_scripts.ACTIONS), 92)
        self.assertEqual(
            set(range(1001, 1097)) - set(decode_boneyard_scripts.ACTIONS),
            {1014, 1021, 1022, 1050},
        )
        self.assertEqual(len(decode_boneyard_scripts.PREDICATES), 14)
        self.assertEqual(len(decode_boneyard_scripts.TRIGGER_TYPES), 15)
        self.assertEqual(
            decode_boneyard_scripts._code_name(1014),
            "LEGACY RUNTIME ACTION 1014",
        )

    def test_null_code_operands_and_beta_npc_recipes_decode(self) -> None:
        start_script = self.alpha["triggerControl"]["scripts"][0]
        self.assertEqual(
            [operand["typeName"] for operand in start_script["lines"][0]["operands"]],
            ["int", "none", "none", "none", "none", "float2", "float2"],
        )

        beta = decode_boneyard_scripts.decode_boneyard(BETA)
        npc_recipes = beta["recipes"]["npcRecipes"]
        self.assertEqual(len(npc_recipes), 2)
        self.assertEqual(
            (npc_recipes[0]["uid"], npc_recipes[0]["displayName"]),
            (99704, "Soronius"),
        )
        self.assertEqual(npc_recipes[0]["link1Uid"], 99740)
        self.assertEqual(npc_recipes[0]["link2Uid"], 100717)


if __name__ == "__main__":
    unittest.main()
