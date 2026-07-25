#!/usr/bin/env python3
"""Behavior tests for the dead progression and round-respawn verifier."""

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

import verify_multiplayer_dead_progression_round_respawn as verifier  # noqa: E402


def sample_actor_state() -> dict[str, object]:
    return {
        "actor_address": 0x123400,
        "progression": {
            "progression": 0x456700,
            "runtime": {
                "life_current": 0.0,
                "life_max": 50.0,
                "mana_current": 0.0,
                "mana_max": 50.0,
                "move_speed": 2.5,
            },
            "native": {
                "hp": 0.0,
                "max_hp": 50.0,
                "mp": 0.0,
                "max_mp": 50.0,
                "level": 2,
                "xp": 135.0,
                "entries": {
                    17: {
                        "entry_index": 17,
                        "active": 1,
                        "visible": 1,
                    }
                },
                "derived": {"push_strength": 1.0},
            },
            "ledger": {
                "entries": {
                    17: {
                        "entry_index": 17,
                        "active": 1,
                        "visible": 1,
                    }
                },
            },
            "loadout": {"primary_entry": 1},
            "raw": {
                "runtime.life_current": "0.0",
                "runtime.mana_current": "0.0",
                "native.hp": "0.0",
                "native.mp": "0.0",
                "native.max_hp": "50.0",
            },
        },
        "items": [
            {
                "index": 1,
                "valid": True,
                "address": 0x777700,
                "type_id": verifier.STAFF_TYPE_ID,
                "recipe_uid": 91,
                "slot": 0,
                "stack_count": 1,
                "color_state_valid": False,
                "color_state": "",
            }
        ],
        "book": [
            {
                "index": 1,
                "valid": True,
                "entry_index": 17,
                "internal_id": 17,
                "active": 1,
                "visible": 1,
                "category": 2,
                "statbook_max_level": 5,
            }
        ],
        "owned": {
            "equipment": {
                "valid": True,
                "revision": 4,
                "weapon": {
                    "type_id": verifier.STAFF_TYPE_ID,
                    "recipe_uid": 91,
                },
            },
            "statbook_entries": [
                {
                    "entry_index": 17,
                    "active": 1,
                }
            ],
            "inventory_items": [
                {
                    "type_id": verifier.STAFF_TYPE_ID,
                    "recipe_uid": 91,
                    "slot": 0,
                    "stack_count": 1,
                }
            ],
            "ability_loadout": {"primary_entry_index": 1},
        },
        "visuals": {
            "primary": {
                "type_id": 0,
                "recipe_uid": 0,
                "object": 0,
            },
            "secondary": {
                "type_id": 0,
                "recipe_uid": 0,
                "object": 0,
            },
            "attachment": {
                "type_id": verifier.STAFF_TYPE_ID,
                "recipe_uid": 91,
                "object": 0x888800,
            },
        },
        "death": {},
    }


class DeadProgressionRoundRespawnVerifierTests(unittest.TestCase):
    def test_generated_prefix_and_scenario_suffixes_stay_short(self) -> None:
        prefix = verifier._default_instance_prefix()
        self.assertLessEqual(len(prefix + "-p"), 18)
        self.assertLessEqual(len(prefix + "-r"), 18)
        self.assertRegex(prefix, r"^dp-[0-9a-f]+-[0-9a-f]{4}$")

    def test_explicit_ports_keep_both_instance_groups_isolated(self) -> None:
        with mock.patch.object(
            verifier,
            "select_available_windows_udp_ports",
        ) as reserve:
            ports = verifier._resolve_ports(
                [23111, 23112, 23113, 23114]
            )
        self.assertEqual(ports, [23111, 23112, 23113, 23114])
        reserve.assert_not_called()

    def test_duplicate_or_partial_ports_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly four"):
            verifier._resolve_ports([23111, 23112, 23113])
        with self.assertRaisesRegex(ValueError, "distinct"):
            verifier._resolve_ports(
                [23111, 23112, 23112, 23114]
            )

    def test_native_corpse_gate_waits_for_tick_159_registration_state(
        self,
    ) -> None:
        state = {
            "active": "true",
            "phase": "Spectating",
            "grid_cell_address": "4096",
            "grid_member_flag": "0",
            "render_sort_bias": "-1000",
            "death_drive_state": "1",
            "red_effect_active": "false",
        }
        self.assertTrue(
            verifier._native_corpse_state_matches(state)
        )

        first_spectator_frame = dict(state)
        first_spectator_frame["grid_member_flag"] = "1"
        first_spectator_frame["render_sort_bias"] = "0"
        self.assertFalse(
            verifier._native_corpse_state_matches(
                first_spectator_frame
            )
        )

    def test_dead_picker_click_targets_the_exact_client_pid(self) -> None:
        completed = mock.Mock(
            returncode=0,
            stdout="clicked client point (600, 450)",
        )
        with mock.patch.object(
            verifier.subprocess,
            "run",
            return_value=completed,
        ) as run:
            result = verifier._click_owned_window(
                4321,
                verifier.FIRST_PICKER_OPTION_X,
                verifier.PICKER_OPTION_Y,
            )

        command = run.call_args.args[0][-1]
        self.assertIn("--pid 4321", command)
        self.assertIn("--relative", command)
        self.assertIn("--global-only", command)
        self.assertEqual(
            result["method"],
            "exact_pid_stock_window_click",
        )
        self.assertEqual(result["process_id"], 4321)

    def test_progression_projection_removes_only_current_resources(self) -> None:
        state = sample_actor_state()["progression"]
        projected = verifier.progression_respawn_projection(state)
        self.assertNotIn("life_current", projected["runtime"])
        self.assertNotIn("mana_current", projected["runtime"])
        self.assertNotIn("hp", projected["native"])
        self.assertNotIn("mp", projected["native"])
        self.assertNotIn(
            "runtime.life_current",
            projected["raw"],
        )
        self.assertNotIn("native.hp", projected["raw"])
        self.assertEqual(
            projected["raw"]["native.max_hp"],
            "50.0",
        )
        self.assertEqual(projected["native"]["max_hp"], 50.0)
        self.assertEqual(
            projected["native"]["entries"][17]["active"],
            1,
        )

    def test_same_actor_parity_includes_dead_time_skill_and_loadout(self) -> None:
        dead = sample_actor_state()
        respawned = copy.deepcopy(dead)
        respawned["progression"]["runtime"]["life_current"] = 50.0
        respawned["progression"]["runtime"]["mana_current"] = 50.0
        respawned["progression"]["native"]["hp"] = 50.0
        respawned["progression"]["native"]["mp"] = 50.0

        result = verifier.assert_same_actor_loadout_after_respawn(
            dead,
            respawned,
        )
        self.assertTrue(result["book_exact"])
        self.assertTrue(result["owned_progression_exact"])

        respawned["progression"]["native"]["entries"][17][
            "active"
        ] = 0
        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "progression/loadout changed",
        ):
            verifier.assert_same_actor_loadout_after_respawn(
                dead,
                respawned,
            )

    def test_staff_parity_rejects_a_duplicate_inventory_row(self) -> None:
        before = sample_actor_state()
        after = copy.deepcopy(before)
        result = verifier.assert_staff_preserved_without_duplication(
            before,
            after,
        )
        self.assertEqual(result["inventory_staff_row_count"], 1)
        self.assertEqual(result["inventory_staff_row_delta"], 0)
        self.assertEqual(
            result["owned_weapon_type_id"],
            verifier.STAFF_TYPE_ID,
        )
        self.assertTrue(
            result["attachment_view_matches_owned_weapon"]
        )

        after["items"].append(copy.deepcopy(after["items"][0]))
        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "changed or duplicated",
        ):
            verifier.assert_staff_preserved_without_duplication(
                before,
                after,
            )

    def test_immediate_respawn_requires_retired_timer_and_one_death(self) -> None:
        sample = {
            "active": "false",
            "phase": "Inactive",
            "death_started_ms": "0",
            "presentation_remaining_ms": "0",
            "last_applied_respawn_epoch": "4",
            "last_applied_respawn_wave": "2",
            "anim_drive_state": "0",
            "death_drive_state": "0",
            "death_presentation_ticks": "0",
            "terminal_pending": "0",
            "grid_cell_address": "4096",
            "grid_member_flag": "1",
            "render_sort_bias": "0",
            "presentation_active": "false",
            "red_effect_active": "false",
            "death_transition_hits": "1",
            "staff_drop_hits": "1",
            "x": "128",
            "y": "256",
            "hp": "50",
            "max_hp": "50",
            "mp": "50",
            "max_mp": "50",
        }
        verifier.assert_immediate_respawn_sample(
            sample,
            epoch=4,
            wave=2,
        )

        sample["x"] = "161"
        sample["y"] = "223"
        verifier.assert_immediate_respawn_sample(
            sample,
            epoch=4,
            wave=2,
        )

        sample["death_started_ms"] = "99"
        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "atomically retire",
        ):
            verifier.assert_immediate_respawn_sample(
                sample,
                epoch=4,
                wave=2,
            )

    def test_respawn_gate_reads_dynamic_spawn_and_retires_only_dead_actor(
        self,
    ) -> None:
        shared = {
            "player_spawn_valid": "true",
            "arena_address": "12288",
            "player_spawn_x": "128",
            "player_spawn_y": "256",
            "player_spawn_facing": "90",
            "materialized": "true",
            "actor_address": "16384",
            "grid_member_flag": "1",
            "render_sort_bias": "0",
            "death_drive_state": "0",
            "death_presentation_ticks": "0",
            "terminal_pending": "0",
            "presentation_active": "false",
            "red_effect_active": "false",
            "x": "128",
            "y": "256",
        }
        client = {
            **shared,
            "grid_cell_address": "20480",
            "last_respawn_x": "128",
            "last_respawn_y": "256",
        }
        host = {
            **shared,
            "actor_address": "24576",
            "grid_cell_address": "28672",
            "participant_x": "128",
            "participant_y": "256",
            "death_presentation_ticks": "7",
            "authoritative_death_presentation_ticks": "0",
        }
        result = verifier._assert_respawn_spawn_and_corpse_retired(
            views={
                "client_owner": client,
                "host_observer": host,
            },
            death_location={"x": 700.0, "y": 700.0},
            before_corpse_views={
                "client_owner": {"grid_cell_address": "32768"},
                "host_observer": {"grid_cell_address": "36864"},
            },
        )

        self.assertFalse(result["client_corpse_present"])
        self.assertFalse(result["host_corpse_present"])
        self.assertEqual(result["spawn"]["host"]["x"], 128.0)
        self.assertEqual(result["client_exact_spawn_delta"]["x"], 0.0)
        self.assertEqual(result["host_exact_spawn_delta"]["y"], 0.0)

    def test_respawn_gate_rejects_death_position_or_lingering_corpse(
        self,
    ) -> None:
        shared = {
            "player_spawn_valid": "true",
            "arena_address": "12288",
            "player_spawn_x": "128",
            "player_spawn_y": "256",
            "player_spawn_facing": "90",
            "materialized": "true",
            "actor_address": "16384",
            "grid_cell_address": "20480",
            "grid_member_flag": "1",
            "render_sort_bias": "0",
            "death_drive_state": "0",
            "death_presentation_ticks": "0",
            "terminal_pending": "0",
            "presentation_active": "false",
            "red_effect_active": "false",
            "x": "700",
            "y": "700",
            "last_respawn_x": "128",
            "last_respawn_y": "256",
        }
        host = {
            **shared,
            "actor_address": "24576",
            "grid_cell_address": "28672",
            "authoritative_death_presentation_ticks": "0",
        }
        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "retained a corpse",
        ):
            verifier._assert_respawn_spawn_and_corpse_retired(
                views={
                    "client_owner": shared,
                    "host_observer": host,
                },
                death_location={"x": 700.0, "y": 700.0},
                before_corpse_views={
                    "client_owner": {"grid_cell_address": "32768"},
                    "host_observer": {"grid_cell_address": "36864"},
                },
            )

        shared["x"] = "128"
        shared["y"] = "256"
        shared["grid_member_flag"] = "0"
        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "retained a corpse",
        ):
            verifier._assert_respawn_spawn_and_corpse_retired(
                views={
                    "client_owner": shared,
                    "host_observer": host,
                },
                death_location={"x": 700.0, "y": 700.0},
                before_corpse_views={
                    "client_owner": {"grid_cell_address": "32768"},
                    "host_observer": {"grid_cell_address": "36864"},
                },
            )


if __name__ == "__main__":
    unittest.main()
