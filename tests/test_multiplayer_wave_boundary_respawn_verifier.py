#!/usr/bin/env python3
"""Behavior tests for the focused wave-boundary respawn verifier."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_local_multiplayer_sync as local  # noqa: E402
import verify_multiplayer_wave_boundary_respawn as verifier  # noqa: E402


def owner_state(
    *,
    x: float = 520.0,
    y: float = 420.0,
    hp: float = 50.0,
    epoch: int = 0,
    wave: int = 0,
    actor: int = 0x101000,
    grid: int = 0x102000,
) -> dict[str, str]:
    return {
        "active": "false",
        "phase": "Inactive",
        "actor_address": str(actor),
        "x": str(x),
        "y": str(y),
        "hp": str(hp),
        "max_hp": "50",
        "mp": "50",
        "max_mp": "50",
        "anim_drive_state": "0",
        "death_presentation_ticks": "0",
        "terminal_pending": "0",
        "grid_cell_address": str(grid),
        "grid_member_flag": "1",
        "last_applied_respawn_epoch": str(epoch),
        "last_applied_respawn_wave": str(wave),
        "last_respawn_x": "0",
        "last_respawn_y": "0",
        "player_spawn_valid": "true",
        "player_spawn_x": "100",
        "player_spawn_y": "100",
        "player_spawn_facing": "90",
        "arena_address": str(0x103000),
    }


def observer_state(
    *,
    x: float = 520.0,
    y: float = 420.0,
    hp: float = 50.0,
    actor: int = 0x201000,
) -> dict[str, str]:
    return {
        "materialized": "true",
        "actor_address": str(actor),
        "x": str(x),
        "y": str(y),
        "participant_x": str(x),
        "participant_y": str(y),
        "hp": str(hp),
        "max_hp": "50",
        "grid_cell_address": str(0x202000),
        "grid_member_flag": "1",
        "render_sort_bias": "0",
        "death_drive_state": "0",
        "death_presentation_ticks": "0",
        "authoritative_death_presentation_ticks": "0",
        "terminal_pending": "0",
        "presentation_active": "false",
        "red_effect_active": "false",
    }


def equipped_primary_state(
    *,
    owner_view: bool,
    primary_entry: int = 16,
    combo_entry: int = 16,
    current_spell_id: int = 1011,
) -> dict[str, str]:
    return {
        "participant_present": "true",
        "owner_view": "true" if owner_view else "false",
        "progression_address": str(
            0x301000 if owner_view else 0x401000
        ),
        "ability_present": "true",
        "primary_entry": str(primary_entry),
        "combo_entry": str(combo_entry),
        "current_spell_id": str(current_spell_id),
        "spellbook_count": "83",
        "spellbook_total_count": "83",
        "spellbook_truncated": "false",
        "spellbook_fingerprint": "16,65537,1,1,257,25",
        "details_present": "true",
        "details_primary_entry": str(primary_entry),
        "details_combo_entry": str(combo_entry),
        "details_build_id": str(primary_entry),
        "details_build_resolved": "true",
        "primary_visual_type_id": "7005",
    }


def equipped_primary_pair() -> dict[str, dict[str, dict[str, str]]]:
    return {
        fighter: {
            "owner": equipped_primary_state(owner_view=True),
            "observer": equipped_primary_state(owner_view=False),
        }
        for fighter in ("host", "client")
    }


class WaveBoundaryRespawnVerifierTests(unittest.TestCase):
    def test_ports_and_generated_prefix_stay_in_the_fb25_group(self) -> None:
        self.assertEqual(
            (verifier.HOST_PORT, verifier.CLIENT_PORT),
            (50911, 50912),
        )
        prefix = verifier._default_instance_prefix()
        self.assertRegex(prefix, r"^fb25-wb-[0-9a-f]+-[0-9a-f]{4}$")
        self.assertLessEqual(len(prefix), 24)

    def test_existing_save_fixture_has_the_pinned_isolated_hashes(
        self,
    ) -> None:
        manifest = verifier._fixture_manifest()
        self.assertEqual(
            manifest,
            {
                "solomondark/darkdata.cfg":
                    "0a9dd9c222b61df4930495aea50a65ebe2e057811092080451fee94a6594ea06",
                "solomondark/savegames/ARTORIUS/Region0._cache":
                    "b161e5ee2db912f55b6086b562f1dff797e81176a69c887fc1eb2324bd0bf15e",
            },
        )

    def test_living_owner_acknowledges_epoch_without_any_reset(
        self,
    ) -> None:
        before = {
            "owner": owner_state(),
            "observer": observer_state(),
        }
        after = copy.deepcopy(before)
        after["owner"]["last_applied_respawn_epoch"] = "1"
        after["owner"]["last_applied_respawn_wave"] = "1"

        result = verifier.assert_living_participant_unchanged(
            before=before,
            after=after,
            expected_wave=1,
        )

        self.assertEqual(result["local_displacement"], 0.0)
        self.assertEqual(result["remote_displacement"], 0.0)
        self.assertGreater(
            result["after_spawn_separation"],
            verifier.SPAWN_SEPARATION_MINIMUM,
        )

    def test_living_owner_teleport_to_spawn_is_rejected(self) -> None:
        before = {
            "owner": owner_state(),
            "observer": observer_state(),
        }
        after = copy.deepcopy(before)
        after["owner"].update(
            {
                "x": "100",
                "y": "100",
                "last_applied_respawn_epoch": "1",
                "last_applied_respawn_wave": "1",
            }
        )
        after["observer"].update({"x": "100", "y": "100"})

        with self.assertRaisesRegex(
            local.VerifyFailure,
            "moved across the wave boundary",
        ):
            verifier.assert_living_participant_unchanged(
                before=before,
                after=after,
                expected_wave=1,
            )

    def test_living_owner_resource_or_grid_reset_is_rejected(self) -> None:
        before = {
            "owner": owner_state(),
            "observer": observer_state(),
        }
        after = copy.deepcopy(before)
        after["owner"].update(
            {
                "hp": "49",
                "grid_cell_address": str(0x999000),
                "last_applied_respawn_epoch": "1",
                "last_applied_respawn_wave": "1",
            }
        )

        with self.assertRaisesRegex(
            local.VerifyFailure,
            "resources, animation, or grid registration",
        ):
            verifier.assert_living_participant_unchanged(
                before=before,
                after=after,
                expected_wave=1,
            )

    def test_dead_owner_respawns_at_spawn_on_the_same_actor(self) -> None:
        before = {
            "owner": owner_state(),
            "observer": observer_state(),
        }
        dead = copy.deepcopy(before)
        dead["owner"].update(
            {
                "active": "true",
                "phase": "DeathPresentation",
                "hp": "0",
            }
        )
        dead["observer"]["hp"] = "0"
        after = {
            "owner": owner_state(
                x=100.0,
                y=100.0,
                epoch=1,
                wave=1,
            ),
            "observer": observer_state(x=100.0, y=100.0),
        }
        after["owner"].update(
            {
                "last_respawn_x": "100",
                "last_respawn_y": "100",
            }
        )

        result = (
            verifier.assert_dead_participant_respawned_same_actor(
                before_death=before,
                death_presentation=dead,
                after_respawn=after,
            )
        )

        self.assertEqual(result["owner_spawn_delta"], 0.0)
        self.assertEqual(result["observer_spawn_delta"], 0.0)
        self.assertGreater(
            result["death_distance_from_spawn"],
            verifier.SPAWN_SEPARATION_MINIMUM,
        )

    def test_dead_owner_actor_replacement_is_rejected(self) -> None:
        before = {
            "owner": owner_state(),
            "observer": observer_state(),
        }
        dead = copy.deepcopy(before)
        dead["owner"]["hp"] = "0"
        after = {
            "owner": owner_state(
                x=100.0,
                y=100.0,
                epoch=1,
                wave=1,
                actor=0x303000,
            ),
            "observer": observer_state(x=100.0, y=100.0),
        }

        with self.assertRaisesRegex(
            local.VerifyFailure,
            "same owner actor",
        ):
            verifier.assert_dead_participant_respawned_same_actor(
                before_death=before,
                death_presentation=dead,
                after_respawn=after,
            )

    def test_equipped_primary_persists_on_both_peer_views(self) -> None:
        before = equipped_primary_pair()
        after = copy.deepcopy(before)

        result = verifier.assert_equipped_primary_persisted(
            before=before,
            after=after,
        )

        self.assertEqual(result["host"]["primary_entry"], "16")
        self.assertEqual(result["client"]["current_spell_id"], "1011")

    def test_missing_current_spell_after_respawn_is_rejected(self) -> None:
        before = equipped_primary_pair()
        after = copy.deepcopy(before)
        after["client"]["owner"]["current_spell_id"] = "-1"

        with self.assertRaisesRegex(
            local.VerifyFailure,
            "did not expose an equipped native primary",
        ):
            verifier.assert_equipped_primary_persisted(
                before=before,
                after=after,
            )

    def test_peer_local_visual_types_do_not_replace_spell_identity(
        self,
    ) -> None:
        before = equipped_primary_pair()
        before["host"]["observer"]["primary_visual_type_id"] = "7006"
        after = copy.deepcopy(before)

        result = verifier.assert_equipped_primary_persisted(
            before=before,
            after=after,
        )

        self.assertEqual(result["host"]["current_spell_id"], "1011")

    def test_owner_observer_primary_disagreement_is_rejected(self) -> None:
        before = equipped_primary_pair()
        before["client"]["observer"]["current_spell_id"] = "1012"
        after = copy.deepcopy(before)

        with self.assertRaisesRegex(
            local.VerifyFailure,
            "did not converge on both peers",
        ):
            verifier.assert_equipped_primary_persisted(
                before=before,
                after=after,
            )

    def test_primary_probe_reads_owned_book_and_native_spell(self) -> None:
        with mock.patch.object(
            verifier,
            "lua",
            return_value="participant_present=true\ncurrent_spell_id=1011",
        ) as lua:
            result = verifier._query_equipped_primary_view(
                "host-pipe",
                42,
                owner_view=True,
            )

        code = lua.call_args.args[1]
        self.assertEqual(result["current_spell_id"], "1011")
        self.assertIn("requested_participant_id = 42", code)
        self.assertIn("expected_owner_view = true", code)
        self.assertIn("owned.spellbook_entries", code)
        self.assertIn('layout_offset("progression_current_spell_id")', code)
        self.assertIn("sd.bots.get_loadout_details", code)

    def test_wave_two_requires_both_peers_live_and_not_completed(
        self,
    ) -> None:
        converged = {
            "host": {
                "wave": "2",
                "alive": "1",
                "phase": "spawning",
            },
            "client": {
                "wave": "2",
                "alive": "1",
                "phase": "spawning",
            },
        }
        self.assertTrue(
            verifier.wave_two_samples_converged(converged)
        )
        converged["client"]["phase"] = "completed"
        self.assertFalse(
            verifier.wave_two_samples_converged(converged)
        )

    def test_survival_hold_can_be_disabled_before_the_lethal_hit(
        self,
    ) -> None:
        with mock.patch.object(
            verifier,
            "lua",
            return_value=(
                "registered=true\n"
                "enabled=false\n"
                "initial_apply=true"
            ),
        ) as lua:
            result = verifier._set_survival_hold(
                "client-pipe",
                enabled=False,
            )

        self.assertEqual(result["enabled"], "false")
        self.assertIn("local enabled = false", lua.call_args.args[1])

    def test_run_generation_seed_is_fixed_and_verified(self) -> None:
        expected = str(verifier.RUN_GENERATION_SEED)
        with mock.patch.object(
            verifier,
            "lua",
            return_value=(
                f"requested={expected}\n"
                f"accepted={expected}\n"
                f"observed={expected}"
            ),
        ) as lua:
            result = verifier._set_run_generation_seed("host-pipe")

        self.assertEqual(result["observed"], expected)
        self.assertIn("sd.rng.set_seed", lua.call_args.args[1])

    def test_wave_one_survivor_must_remain_alive_after_boundary(self) -> None:
        with mock.patch.object(
            verifier,
            "lua",
            return_value=(
                "held_actor=1234\nfound=true\ntracked_enemy=true\n"
                "dead=false\nhp=1000000"
            ),
        ):
            result = (
                verifier._assert_held_wave_one_enemy_survived_boundary(
                    "host-pipe"
                )
            )

        self.assertEqual(result["held_actor"], "1234")

    def test_dead_wave_one_survivor_rejects_completion_based_gate(
        self,
    ) -> None:
        with mock.patch.object(
            verifier,
            "lua",
            return_value=(
                "held_actor=1234\nfound=true\ntracked_enemy=true\n"
                "dead=true\nhp=0"
            ),
        ):
            with self.assertRaisesRegex(
                local.VerifyFailure,
                "did not remain alive",
            ):
                verifier._assert_held_wave_one_enemy_survived_boundary(
                    "host-pipe"
                )

    def test_wave_one_hold_leaves_one_stock_enemy(self) -> None:
        with (
            mock.patch.object(
                verifier,
                "lua",
                side_effect=[
                    (
                        "wave=1\nphase=clearing\n"
                        "remaining_to_spawn=0\nalive=3\nkilled=0"
                    ),
                    "live_seen=3\nheld_actor=1234\ntriggered=2",
                    (
                        "wave=1\nphase=clearing\n"
                        "remaining_to_spawn=0\nalive=1\nkilled=2"
                    ),
                ],
            ) as lua,
            mock.patch.object(verifier.time, "sleep"),
        ):
            result = verifier._hold_wave_one_on_single_enemy(
                "host-pipe",
                timeout=1.0,
            )

        self.assertEqual(result["held_actor"], 1234)
        self.assertEqual(result["state"]["alive"], "1")
        self.assertEqual(lua.call_count, 3)

    def test_start_match_waits_for_the_stock_request_to_queue(
        self,
    ) -> None:
        with (
            mock.patch.object(
                verifier,
                "lua",
                side_effect=[
                    "invoked=false\nqueued=false\ndetail=not ready",
                    "invoked=true\nqueued=true\ndetail=true",
                ],
            ) as lua,
            mock.patch.object(verifier.time, "sleep"),
        ):
            result = verifier._start_match_when_ready(
                "host-pipe",
                timeout=1.0,
            )

        self.assertEqual(result["queued"], "true")
        self.assertEqual(lua.call_count, 2)
        self.assertIn("sd.hub.start_match", lua.call_args.args[1])

    def test_stock_wave_start_uses_the_native_arena_entrypoint(self) -> None:
        with mock.patch.object(
            verifier,
            "lua",
            return_value="invoked=true\nqueued=true\ndetail=true",
        ) as lua:
            result = verifier._queue_stock_wave_start("host-pipe")

        self.assertEqual(result["queued"], "true")
        self.assertIn("sd.gameplay.start_waves", lua.call_args.args[1])

    def test_stock_wave_start_rejects_a_failed_queue(self) -> None:
        with mock.patch.object(
            verifier,
            "lua",
            return_value=(
                "invoked=false\nqueued=false\n"
                "detail=Arena is not active."
            ),
        ):
            with self.assertRaisesRegex(
                local.VerifyFailure,
                "ArenaStartWaves",
            ):
                verifier._queue_stock_wave_start("host-pipe")

    def test_live_launch_stages_saves_and_cleans_only_reported_pid(
        self,
    ) -> None:
        launch_result = {
            "hostProcessId": 71,
            "hostLuaPipe": "host-pipe",
            "clientLuaPipe": "client-pipe",
        }
        with (
            mock.patch.object(
                verifier,
                "_source_sha",
                return_value="a" * 40,
            ),
            mock.patch.object(
                verifier,
                "_fixture_manifest",
                return_value={"fixture": "hash"},
            ),
            mock.patch.object(
                verifier,
                "_copy_fixture_to_save_root",
            ),
            mock.patch.object(
                verifier,
                "launch_pair",
                return_value=launch_result,
            ) as launch_pair,
            mock.patch.object(
                verifier,
                "game_process_ids",
                return_value=[71],
            ),
            mock.patch.object(
                verifier,
                "stop_game_processes",
            ) as stop,
        ):
            with self.assertRaisesRegex(
                local.VerifyFailure,
                "exactly two process IDs",
            ):
                verifier.run_live_verification(
                    instance_prefix="fb25-test",
                    host_port=50911,
                    client_port=50912,
                    game_directory=None,
                    launcher_path=None,
                    runtime_root=None,
                    with_bot_play_mod=False,
                )

        kwargs = launch_pair.call_args.kwargs
        self.assertEqual(kwargs["host_port"], 50911)
        self.assertEqual(kwargs["client_port"], 50912)
        self.assertEqual(kwargs["third_port"], 50912)
        self.assertTrue(kwargs["quick_start"])
        self.assertTrue(kwargs["no_lua_automation"])
        self.assertIsNone(kwargs["test_wave_override"])
        self.assertFalse(kwargs["tile_windows"])
        self.assertFalse(kwargs["allow_focus_steal"])
        self.assertFalse(kwargs["kill_existing"])
        self.assertFalse(kwargs["enable_audio"])
        self.assertNotEqual(
            kwargs["host_savegames_root"],
            kwargs["client_savegames_root"],
        )
        stop.assert_called_once_with([71])

    def test_local_pair_rejects_ambiguous_save_profile_modes(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "requires quick_start",
        ):
            local.launch_pair(no_lua_automation=True)
        with self.assertRaisesRegex(
            ValueError,
            "fresh_install",
        ):
            local.launch_pair(
                fresh_install=True,
                host_savegames_root=Path("host"),
            )
        with self.assertRaisesRegex(
            ValueError,
            "temporary_host_profile",
        ):
            local.launch_pair(
                temporary_host_profile=True,
                host_savegames_root=Path("host"),
            )


if __name__ == "__main__":
    unittest.main()
