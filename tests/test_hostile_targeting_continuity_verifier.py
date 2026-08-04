from __future__ import annotations

import unittest

from tools.verify_hostile_targeting_continuity import (
    HostileTargetingContinuityFailure,
    _arrange,
    _enemy_network_ids_from_log,
    _release_bot_lock,
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
    def test_bot_lock_release_is_explicit(self) -> None:
        class Pipe:
            code = ""

            def execute(self, code: str) -> str:
                self.code = code
                return "released=true"

        pipe = Pipe()
        self.assertTrue(_release_bot_lock(pipe)["released"])
        self.assertIn("lock.bot_actor = 0", pipe.code)

    def test_arranged_distance_is_the_straggler_acceptance_baseline(self) -> None:
        first = {
            **target_row(),
            "owner.x": 1000.0,
            "bot.x": 100.0,
            "enemy.x": 0.0,
            "bot.cast_accepted": 10,
            "bot.move_accepted": 20,
        }
        final = {
            **first,
            "enemy.alive": False,
            "bot.cast_accepted": 11,
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
            arranged_bot_distance=500.0,
        )
        self.assertEqual(assessment["initialBotDistance"], 500.0)
        self.assertEqual(assessment["firstObservedBotDistance"], 100.0)

    def test_arrange_can_lock_the_bot_during_nearest_sampling(self) -> None:
        class Pipe:
            code = ""

            def execute(self, code: str) -> str:
                self.code = code
                return "ok=true"

        pipe = Pipe()
        result = _arrange(
            pipe,
            enemy_actor_addresses=[0x111],
            bot_id=BOT_ID,
            owner_x=750.0,
            owner_y=0.0,
            bot_x=50.0,
            bot_y=0.0,
            enemy_x=0.0,
            enemy_y=0.0,
            enemy_hp=5000.0,
            enemy_spacing=0.0,
            park_other_enemies=True,
            allow_missing_bot=False,
            preserve_enemy_positions=True,
            lock_only_selected_enemy=False,
            relative_layout=True,
            require_clear_paths=True,
            lock_bot=True,
        )
        self.assertTrue(result["ok"])
        self.assertIn("bot_actor = true and bot_actor or 0", pipe.code)
        self.assertIn(
            'emit("preserved_native_enemy_positions", true)',
            pipe.code,
        )
        self.assertNotIn("__LOCK_BOT__", pipe.code)

    def test_arrange_can_hold_only_the_selected_idle_straggler(self) -> None:
        class Pipe:
            code = ""

            def execute(self, code: str) -> str:
                self.code = code
                return "ok=true"

        pipe = Pipe()
        _arrange(
            pipe,
            enemy_actor_addresses=[0x111, 0x222],
            bot_id=BOT_ID,
            owner_x=1000.0,
            owner_y=0.0,
            bot_x=500.0,
            bot_y=0.0,
            enemy_x=0.0,
            enemy_y=0.0,
            enemy_hp=1.0,
            enemy_spacing=0.0,
            park_other_enemies=False,
            allow_missing_bot=False,
            preserve_enemy_positions=True,
            lock_only_selected_enemy=True,
            relative_layout=True,
            require_clear_paths=True,
            lock_bot=False,
        )
        self.assertIn("if not true or index == 1 then", pipe.code)
        self.assertIn('emit("stationary_enemy_count", locked_enemy_count)', pipe.code)
        self.assertNotIn("__LOCK_ONLY_SELECTED_ENEMY__", pipe.code)

    def test_log_requires_one_network_identity_per_enemy(self) -> None:
        self.assertEqual(
            _enemy_network_ids_from_log(
                "\n".join((
                    "enemy.spawned hook invoked. enemy=0x111 "
                    "spawn_serial=11 enemy_type=1001",
                    "assigned host-local run actor network id. "
                    "actor=0x222 network_actor_id=43690",
                )),
                [273, 546],
            ),
            [0xAAAA, 0x100000000000B],
        )
        with self.assertRaises(HostileTargetingContinuityFailure):
            _enemy_network_ids_from_log(
                "assigned host-local run actor network id. "
                "actor=0x111 network_actor_id=43690",
                [273, 546],
            )

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

    def test_completed_phase_counts_as_wave_advancement(self) -> None:
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
            "wave.phase": "completed",
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
        self.assertTrue(assessment["completedPhaseObserved"])

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

    def test_wave_advance_requires_damage_to_every_original_enemy(self) -> None:
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

    def test_network_identity_ignores_stale_authority_snapshot(self) -> None:
        first = {
            **target_row(),
            "owner.x": 2850.0,
            "bot.x": 2350.0,
            "bot.cast_accepted": 10,
            "bot.move_accepted": 20,
            "original.live_count": 1,
            "original.network_live_count": 1,
        }
        final = {
            **first,
            "enemy.alive": False,
            "bot.cast_accepted": 11,
            "combat.wave": 2,
            "original.live_count": 1,
            "original.network_live_count": 1,
        }
        assessment = analyze_wave_completion(
            [first, final],
            starting_wave=1,
            bot_id=BOT_ID,
            original_enemy_actor_addresses=[0x111],
            original_enemy_network_ids=[0xAAAA],
            damage_rows=[
                {
                    "sourceParticipantId": BOT_ID,
                    "targetActorAddress": 0x111,
                    "targetNetworkActorId": 0xAAAA,
                    "damage": 25.0,
                }
            ],
        )
        self.assertTrue(assessment["originalEnemyLiveAtEnd"])
        self.assertTrue(assessment["allOriginalEnemiesBotDamaged"])
        self.assertEqual(
            assessment["originalEnemyIdentityKind"],
            "network_actor_id",
        )

    def test_phase_boundary_death_is_accounted_before_sampling(self) -> None:
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
            "enemy.alive": False,
            "bot.cast_accepted": 11,
            "combat.wave": 2,
        }
        assessment = analyze_wave_completion(
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
        self.assertEqual(assessment["phaseBoundaryOriginalDeathCount"], 1)
        self.assertTrue(assessment["allOriginalEnemiesAccounted"])

    def test_bot_damage_to_a_different_network_enemy_cannot_pass(self) -> None:
        first = {
            **target_row(),
            "owner.x": 2850.0,
            "bot.x": 2350.0,
            "bot.cast_accepted": 10,
            "bot.move_accepted": 20,
            "original.network_live_count": 1,
        }
        final = {
            **first,
            "enemy.alive": False,
            "bot.cast_accepted": 11,
            "combat.wave": 2,
            "original.network_live_count": 0,
        }
        with self.assertRaises(HostileTargetingContinuityFailure):
            analyze_wave_completion(
                [first, final],
                starting_wave=1,
                bot_id=BOT_ID,
                original_enemy_actor_addresses=[0x111],
                original_enemy_network_ids=[0xAAAA],
                damage_rows=[
                    {
                        "sourceParticipantId": BOT_ID,
                        "targetActorAddress": 0x222,
                        "targetNetworkActorId": 0xBBBB,
                        "damage": 25.0,
                    }
                ],
            )

    def test_wave_advance_rejects_enemy_pursuit_beyond_one_native_step(self) -> None:
        first = {
            **target_row(),
            "owner.x": 2850.0,
            "bot.x": 2350.0,
            "bot.cast_accepted": 10,
            "bot.move_accepted": 20,
        }
        moved = {
            **first,
            "enemy.x": first["enemy.x"] + 41.0,
        }
        final = {
            **moved,
            "enemy.alive": False,
            "bot.cast_accepted": 11,
            "combat.wave": 2,
        }
        with self.assertRaises(HostileTargetingContinuityFailure):
            analyze_wave_completion(
                [first, moved, final],
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
