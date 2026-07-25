#!/usr/bin/env python3
"""Behavior tests for the organic multiplayer player-death verifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_multiplayer_organic_player_death as verifier  # noqa: E402


def _completed_lifecycle() -> list[dict[str, dict[str, str]]]:
    return [
        {
            "owner": {
                "death_transition_hits": "1",
                "staff_drop_hits": "1",
            },
            "observer": {
                "death_transition_hits": "0",
                "staff_drop_hits": "0",
            },
        }
    ]


def _completed_milestones() -> dict[str, float]:
    return {
        "hp_zero_seconds": 1.0,
        "owner_death_drive_seconds": 1.4,
        "observer_death_drive_seconds": 1.42,
        "presentation_seconds": 1.4,
        "observer_presentation_seconds": 1.42,
        "owner_presentation_tick_at_observer_start": 4.0,
        "observer_presentation_tick_at_start": 5.0,
        "death_transition_seconds": 1.4,
        "staff_drop_seconds": 1.4,
        "red_effect_seconds": 2.9,
        "spectator_seconds": 4.4,
        "red_cleared_seconds": 4.4,
    }


class OrganicPlayerDeathVerifierTests(unittest.TestCase):
    def test_generated_instance_prefix_stays_below_native_path_limit(
        self,
    ) -> None:
        prefix = verifier._default_instance_prefix()
        self.assertLessEqual(len(prefix), 18)
        self.assertRegex(prefix, r"^orgd-[0-9a-f]+-[0-9a-f]{4}$")

    def test_damage_probe_parser_preserves_enemy_damage_fields(self) -> None:
        events = verifier._parse_damage_probe(
            "D|1|2305843009213698049|0|1234|5678|136|2.5|1.25|3.75\n"
        )

        self.assertEqual(
            events,
            [
                {
                    "index": 1,
                    "target_participant_id": 2305843009213698049,
                    "source_participant_id": 0,
                    "target_actor_address": 1234,
                    "source_actor_address": 5678,
                    "flags": 136,
                    "projectile_damage": 2.5,
                    "magic_damage": 1.25,
                    "total_damage": 3.75,
                }
            ],
        )

    def test_completed_organic_lifecycle_requires_owner_only_drop(
        self,
    ) -> None:
        grace = verifier._assert_lifecycle(
            _completed_lifecycle(),
            _completed_milestones(),
        )

        self.assertAlmostEqual(grace, 3.0)

    def test_premature_observer_corpse_is_rejected(self) -> None:
        milestones = _completed_milestones()
        milestones["observer_death_drive_seconds"] = 1.0

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "before the owner",
        ):
            verifier._assert_lifecycle(
                _completed_lifecycle(),
                milestones,
            )

    def test_phase_sync_survives_observer_app_tick_stall(self) -> None:
        milestones = _completed_milestones()
        milestones["observer_presentation_seconds"] = 1.8
        milestones["owner_presentation_tick_at_observer_start"] = 40.0
        milestones["observer_presentation_tick_at_start"] = 35.0

        verifier._assert_lifecycle(
            _completed_lifecycle(),
            milestones,
        )

        self.assertAlmostEqual(
            milestones["presentation_delivery_skew_seconds"],
            0.4,
        )
        self.assertEqual(
            milestones["presentation_phase_skew_ticks"],
            5.0,
        )

    def test_native_presentation_phase_desync_is_rejected(self) -> None:
        milestones = _completed_milestones()
        milestones["owner_presentation_tick_at_observer_start"] = 40.0
        milestones["observer_presentation_tick_at_start"] = 20.0

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "presentation phase diverged",
        ):
            verifier._assert_lifecycle(
                _completed_lifecycle(),
                milestones,
            )

    def test_missing_death_transition_is_rejected(self) -> None:
        milestones = _completed_milestones()
        del milestones["death_transition_seconds"]

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "death_transition_seconds",
        ):
            verifier._assert_lifecycle(
                _completed_lifecycle(),
                milestones,
            )

    def test_fixtures_use_stock_wave_enemies_without_scripted_damage(
        self,
    ) -> None:
        expected = {
            "melee": "SKELETON",
            "projectile": "FLAG_CASTFIRE",
            "poison": "FLAG_CASTPOISON",
        }
        for kill_type, token in expected.items():
            fixture = verifier.WAVE_FIXTURES[kill_type].read_text(
                encoding="utf-8"
            )
            self.assertIn(token, fixture)
            self.assertNotIn("1000", fixture)
            self.assertNotIn("invoke_native_magic_hit_trial", fixture)


if __name__ == "__main__":
    unittest.main()
