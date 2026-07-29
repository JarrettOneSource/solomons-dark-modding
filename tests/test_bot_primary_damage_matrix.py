#!/usr/bin/env python3
"""Contracts for the all-element primary applied-damage matrix."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import run_bot_match as bot_match  # noqa: E402
import verify_bot_primary_damage_matrix as matrix  # noqa: E402


class BotPrimaryDamageMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = json.loads(
            (TOOLS_ROOT / "bot_match.example.json").read_text(
                encoding="utf-8"
            )
        )

    def test_each_element_replaces_slot_zero_and_all_synthetics(
        self,
    ) -> None:
        for element in matrix.ELEMENTS:
            with self.subTest(element=element):
                document = matrix.element_config_document(
                    self.source,
                    element,
                )
                self.assertEqual(document["player"]["element"], element)
                self.assertEqual(
                    {row["element"] for row in document["bots"]},
                    {element},
                )

    def test_result_requires_each_fighter_to_apply_enemy_hp_damage(
        self,
    ) -> None:
        config = bot_match.BotMatchConfig.load(
            TOOLS_ROOT / "bot_match.example.json"
        )
        names = [
            config.player_name,
            *(fighter.name for fighter in config.bots),
        ]
        result = {
            "furthestWave": 1,
            "gateTransit": {"stuckTeleports": 0},
            "solomonDig": {"triggered": True},
            "end": {
                "reason": "four_fighter_damage_matrix_satisfied",
            },
            "damage": {
                "enemyDamageEdges": 4,
                "fighters": {
                    name: {
                        "damageDealt": 1.0,
                        "damageDealtEdges": 1,
                    }
                    for name in names
                },
            },
        }
        row = matrix.validate_element_result("air", config, result)
        self.assertEqual(row["enemyDamageEdges"], 4)

        result["damage"]["fighters"]["Gale"]["damageDealtEdges"] = 0
        with self.assertRaisesRegex(
            matrix.PrimaryMatrixFailure,
            "authoritative enemy-HP damage",
        ):
            matrix.validate_element_result("air", config, result)


if __name__ == "__main__":
    unittest.main()
