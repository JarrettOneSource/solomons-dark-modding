#!/usr/bin/env python3
"""Contracts for the applied-damage Lua Bots combat verifier."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_bot_cast_in_range as verifier  # noqa: E402


def water_report() -> dict[str, object]:
    return {
        "tickCount": 200,
        "ticksWithEnemies": 180,
        "bots": [
            {
                "id": 101,
                "name": "Brook",
                "activeTicks": 190,
                "approachTicks": 80,
                "outsideRangeApproachTicks": 60,
                "rangeUnavailableTicks": 0,
                "minEnemyCenterDistance": 190.0,
                "maxEnemyCenterDistance": 500.0,
                "latestRange": 205.0,
                "latestRangeSource":
                    "native_frost_jet_query_range",
                "modes": "approach:80,kite:110",
            }
        ],
        "casts": [
            {
                "nowMs": 1_000,
                "acceptedCount": 1,
                "participantId": 101,
                "targetNetworkActorId": 501,
                "targetDistance": 190.0,
                "spellRange": 205.0,
                "rangeSource":
                    "native_frost_jet_query_range",
                "mode": "kite",
            }
        ],
        "damageEdges": [
            {
                "nowMs": 1_250,
                "targetNetworkActorId": 501,
                "hpBefore": 10.0,
                "hpAfter": 7.5,
                "damage": 2.5,
            }
        ],
    }


def fire_report() -> dict[str, object]:
    report = water_report()
    bot = report["bots"][0]
    cast = report["casts"][0]
    edge = report["damageEdges"][0]
    bot.update(
        {
            "name": "Ember",
            "latestRange": 438.0,
            "latestRangeSource":
                "native_selection_pursuit_range",
        }
    )
    cast.update(
        {
            "targetNetworkActorId": 601,
            "targetDistance": 400.0,
            "spellRange": 438.0,
            "rangeSource":
                "native_selection_pursuit_range",
        }
    )
    edge.update(
        {
            "nowMs": 1_300,
            "targetNetworkActorId": 602,
            "damage": 2.5,
        }
    )
    return report


class BotCastInRangeVerifierTests(unittest.TestCase):
    def test_isolation_and_launch_contract_is_fixed(self) -> None:
        self.assertEqual(verifier.HOST_PORT, 50411)
        self.assertEqual(verifier.CLIENT_PORT, 50412)
        self.assertEqual(verifier.INSTANCE_PREFIX, "botcast")
        self.assertEqual(verifier.CLIENT_NAME, "client B")
        self.assertEqual(verifier.EXACT_MOD_ID, "bot.brain")
        source = (
            TOOLS_ROOT / "verify_bot_cast_in_range.py"
        ).read_text(encoding="utf-8")
        self.assertIn("enable_audio=False", source)
        self.assertIn("pair.stop_owned_process(pid, expected)", source)
        self.assertIn("actual.casefold() != expected.casefold()", source)
        self.assertNotIn("verify_local_multiplayer_sync", source)
        self.assertNotIn("50311", source)
        self.assertNotIn("50312", source)

    def test_applied_damage_links_require_same_target_and_time_window(
        self,
    ) -> None:
        report = water_report()
        casts = report["casts"]
        assert isinstance(casts, list)
        edges = [
            {
                "nowMs": 1_100,
                "targetNetworkActorId": 999,
                "damage": 1.0,
            },
            {
                "nowMs": (
                    1_000
                    + verifier.CAST_DAMAGE_WINDOW_MS
                    + 1
                ),
                "targetNetworkActorId": 501,
                "damage": 1.0,
            },
            {
                "nowMs": 1_250,
                "targetNetworkActorId": 501,
                "damage": 2.5,
            },
        ]
        links = verifier.applied_damage_links(casts, edges)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["targetNetworkActorId"], 501)
        self.assertEqual(links[0]["damage"], 2.5)

    def test_accepted_cast_without_applied_damage_is_not_combat(
        self,
    ) -> None:
        report = water_report()
        report["damageEdges"] = []
        with self.assertRaisesRegex(
            verifier.BotCastRangeFailure,
            "applied no enemy damage",
        ):
            verifier.validate_scenario(
                verifier.SCENARIOS[0],
                report,
                "",
            )

    def test_fire_damage_requires_native_bot_projectile_authority(
        self,
    ) -> None:
        report = fire_report()
        with self.assertRaisesRegex(
            verifier.BotCastRangeFailure,
            "no bot-attributed native cast",
        ):
            verifier.validate_scenario(
                verifier.SCENARIOS[1],
                report,
                "",
            )

    def test_fire_projectile_may_hit_a_different_authorized_target(
        self,
    ) -> None:
        loader_log = (
            "[bots] authority synthetic Fireball native damage "
            "authorized. monotonic_ms=1250 "
            "participant_id=101 projectile_actor=0x123 "
            "target_actor=0x456 "
            "target_network_actor_id=602"
        )
        acceptance = verifier.validate_scenario(
            verifier.SCENARIOS[1],
            fire_report(),
            loader_log,
        )
        links = acceptance["appliedDamageLinks"]
        self.assertEqual(len(links), 1)
        self.assertEqual(
            links[0]["aimedTargetNetworkActorId"],
            601,
        )
        self.assertEqual(
            links[0]["targetNetworkActorId"],
            602,
        )

    def test_cast_outside_native_range_is_rejected(self) -> None:
        report = water_report()
        casts = report["casts"]
        assert isinstance(casts, list)
        casts[0]["targetDistance"] = 205.251
        with self.assertRaisesRegex(
            verifier.BotCastRangeFailure,
            "cast outside its native range",
        ):
            verifier.validate_scenario(
                verifier.SCENARIOS[0],
                report,
                "",
            )

    def test_short_range_approach_and_applied_damage_pass(self) -> None:
        acceptance = verifier.validate_scenario(
            verifier.SCENARIOS[0],
            water_report(),
            "",
        )
        self.assertTrue(
            acceptance["allCastDistancesWithinSpellRange"]
        )
        self.assertEqual(
            acceptance["combatAcceptance"],
            "applied enemy HP damage edges",
        )
        self.assertEqual(len(acceptance["appliedDamageLinks"]), 1)

    def test_old_behavior_key_must_migrate_before_combat(self) -> None:
        legacy_roster = verifier.SCENARIOS[0].roster
        self.assertEqual(
            legacy_roster,
            [
                {
                    "name": "Brook",
                    "element": "water",
                    "discipline": "skirmisher",
                }
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "bot.brain.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "values": {
                            "roster": legacy_roster,
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                verifier.pair,
                "settings_path",
                return_value=settings_path,
            ):
                with self.assertRaisesRegex(
                    verifier.BotCastRangeFailure,
                    "legacy roster did not migrate once",
                ):
                    verifier.require_migration(
                        verifier.SCENARIOS[0]
                    )
                settings_path.write_text(
                    json.dumps(
                        {
                            "schemaVersion": 1,
                            "values": {
                                "roster": [
                                    {
                                        "name": "Brook",
                                        "element": "water",
                                        "behavior": "skirmisher",
                                        "discipline": "arcane",
                                    }
                                ]
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                migrated = verifier.require_migration(
                    verifier.SCENARIOS[0]
                )
        self.assertEqual(
            migrated["values"]["roster"][0]["behavior"],
            "skirmisher",
        )
        acceptance = verifier.validate_scenario(
            verifier.SCENARIOS[0],
            water_report(),
            "",
        )
        self.assertEqual(len(acceptance["appliedDamageLinks"]), 1)


if __name__ == "__main__":
    unittest.main()
