from __future__ import annotations

import unittest

from tools.verify_hostile_targeting_continuity import (
    HostileTargetingContinuityFailure,
    analyze_selector_log,
    analyze_target_samples,
    analyze_wave_completion,
)


BOT_ID = 0x1000000000000000


def target_row(*, target: int = BOT_ID, latch: int = 0) -> dict[str, object]:
    return {
        "owner.x": 2600.0,
        "owner.y": 1750.0,
        "bot.x": 1900.0,
        "bot.y": 1750.0,
        "bot.cast_accepted": 4,
        "bot.move_accepted": 8,
        "enemy.alive": True,
        "enemy.x": 1850.0,
        "enemy.y": 1750.0,
        "enemy.target_participant_id": target,
        "enemy.selector_latch": latch,
        "combat.wave": 1,
    }


class HostileTargetingContinuityVerifierTests(unittest.TestCase):
    def test_nearest_bot_must_remain_the_selected_target(self) -> None:
        assessment = analyze_target_samples(
            [target_row() for _ in range(20)],
            bot_id=BOT_ID,
        )
        self.assertEqual(assessment["correctNearestTargetSampleCount"], 20)
        self.assertEqual(assessment["targetParticipantIds"], [BOT_ID])

    def test_matching_zero_target_cannot_pass_nearest_gate(self) -> None:
        with self.assertRaises(HostileTargetingContinuityFailure):
            analyze_target_samples(
                [target_row(target=0) for _ in range(20)],
                bot_id=BOT_ID,
            )

    def test_selector_log_counts_stock_owner_to_extended_bot_rewrites(self) -> None:
        line = (
            "[hostile_ai] authoritative nearest target applied. "
            "reason=native_selector hostile=0x111 previous_target=0x222 "
            "target=0x333 target_participant_id=1152921504606846976"
        )
        assessment = analyze_selector_log(
            "\n".join((line, line, "unrelated")),
            hostile_actor_address=0x111,
            owner_actor_address=0x222,
            bot_actor_address=0x333,
        )
        self.assertEqual(assessment["nativeSelectorApplyCount"], 2)
        self.assertEqual(
            assessment["stockOwnerToExtendedBotRewriteCount"], 2
        )

    def test_stationary_straggler_requires_bot_damage_and_wave_advance(self) -> None:
        first = {
            **target_row(),
            "owner.x": 2850.0,
            "bot.x": 2350.0,
            "bot.cast_accepted": 10,
            "bot.move_accepted": 20,
        }
        final = {
            **first,
            "enemy.alive": False,
            "bot.cast_accepted": 11,
            "bot.move_accepted": 24,
            "combat.wave": 2,
        }
        assessment = analyze_wave_completion(
            [first, final],
            starting_wave=1,
            bot_id=BOT_ID,
            original_enemy_actor_addresses=[0x111],
            damage_rows=[
                {
                    "sourceParticipantId": BOT_ID,
                    "targetActorAddress": 0x111,
                    "damage": 25.0,
                }
            ],
        )
        self.assertTrue(assessment["advanced"])
        self.assertEqual(assessment["ownerSearchInputRequests"], 0)

    def test_wave_number_alone_cannot_hide_missing_bot_damage(self) -> None:
        first = {
            **target_row(),
            "owner.x": 2850.0,
            "bot.x": 2350.0,
            "bot.cast_accepted": 10,
            "bot.move_accepted": 20,
        }
        final = {
            **first,
            "enemy.alive": False,
            "bot.cast_accepted": 11,
            "combat.wave": 2,
        }
        with self.assertRaises(HostileTargetingContinuityFailure):
            analyze_wave_completion(
                [first, final],
                starting_wave=1,
                bot_id=BOT_ID,
                original_enemy_actor_addresses=[0x111],
                damage_rows=[],
            )

    def test_wave_advance_requires_bot_damage_to_every_original_enemy(self) -> None:
        first = {
            **target_row(),
            "owner.x": 2850.0,
            "bot.x": 2350.0,
            "bot.cast_accepted": 10,
            "bot.move_accepted": 20,
        }
        final = {
            **first,
            "enemy.alive": False,
            "bot.cast_accepted": 11,
            "combat.wave": 2,
        }
        with self.assertRaises(HostileTargetingContinuityFailure):
            analyze_wave_completion(
                [first, final],
                starting_wave=1,
                bot_id=BOT_ID,
                original_enemy_actor_addresses=[0x111, 0x222],
                damage_rows=[
                    {
                        "sourceParticipantId": BOT_ID,
                        "targetActorAddress": 0x111,
                        "damage": 25.0,
                    }
                ],
            )

    def test_pre_fix_stall_requires_an_active_bot_and_a_live_straggler(self) -> None:
        first = {
            **target_row(),
            "owner.x": 2850.0,
            "bot.x": 2350.0,
            "bot.cast_accepted": 10,
            "bot.move_accepted": 20,
            "original.live_count": 1,
        }
        final = {
            **first,
            "bot.cast_accepted": 12,
            "bot.move_accepted": 24,
        }
        assessment = analyze_wave_completion(
            [first, final],
            starting_wave=1,
            bot_id=BOT_ID,
            original_enemy_actor_addresses=[0x111],
            damage_rows=[
                {
                    "sourceParticipantId": BOT_ID,
                    "targetActorAddress": 0x111,
                    "damage": 1.0,
                }
            ],
            expect_stall=True,
        )
        self.assertTrue(assessment["preFixStallReproduced"])
        self.assertFalse(assessment["completedAutonomously"])


if __name__ == "__main__":
    unittest.main()
