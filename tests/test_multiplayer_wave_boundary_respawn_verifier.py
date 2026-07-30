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

    def test_wave_one_completion_never_kills_wave_two(self) -> None:
        with (
            mock.patch.object(
                verifier,
                "lua",
                side_effect=[
                    (
                        "wave=1\nphase=clearing\n"
                        "remaining_to_spawn=0\nalive=1\nkilled=4"
                    ),
                    "attempted=1\ntriggered=1",
                    (
                        "wave=2\nphase=spawning\n"
                        "remaining_to_spawn=5\nalive=0\nkilled=0"
                    ),
                ],
            ) as lua,
            mock.patch.object(verifier.time, "sleep"),
        ):
            attempts = verifier._trigger_wave_one_completion(
                "host-pipe",
                timeout=1.0,
            )

        self.assertEqual(attempts[0]["wave"], "1")
        self.assertEqual(attempts[0]["triggered"], "1")
        self.assertEqual(lua.call_count, 3)

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
                    game_directory=None,
                    launcher_path=None,
                    runtime_root=None,
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
