#!/usr/bin/env python3
"""Behavior tests for the organic multiplayer player-death verifier."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_multiplayer_organic_player_death as verifier  # noqa: E402


def _completed_lifecycle() -> list[dict[str, dict[str, str]]]:
    return [
        {
            "owner": {
                "death_transition_hits": "0",
                "staff_drop_hits": "0",
                "death_presentation_ticks": "0",
                "authoritative_death_presentation_ticks": "0",
                "death_drive_state": "0",
                "grid_member_flag": "1",
                "hp": "1",
                "render_sort_bias": "0",
                "x": "640.0",
                "y": "384.0",
            },
            "observer": {
                "death_transition_hits": "0",
                "staff_drop_hits": "0",
                "death_presentation_ticks": "0",
                "authoritative_death_presentation_ticks": "0",
                "death_drive_state": "0",
                "grid_member_flag": "1",
                "hp": "1",
                "render_sort_bias": "0",
                "x": "640.0",
                "y": "384.0",
            },
        },
        {
            "owner": {
                "death_transition_hits": "1",
                "staff_drop_hits": "1",
                "death_presentation_ticks": "150",
                "authoritative_death_presentation_ticks": "159",
                "death_drive_state": "1",
                "grid_member_flag": "1",
                "hp": "0",
                "render_sort_bias": "0",
                "x": "640.0",
                "y": "384.0",
            },
            "observer": {
                "death_transition_hits": "0",
                "staff_drop_hits": "0",
                "death_presentation_ticks": "0",
                "authoritative_death_presentation_ticks": "0",
                "death_drive_state": "0",
                "grid_member_flag": "1",
                "hp": "1",
                "render_sort_bias": "0",
                "x": "630.0",
                "y": "384.0",
            },
        },
        {
            "owner": {
                "death_transition_hits": "1",
                "staff_drop_hits": "1",
                "death_presentation_ticks": "150",
                "authoritative_death_presentation_ticks": "159",
                "death_drive_state": "1",
                "grid_member_flag": "1",
                "hp": "0",
                "render_sort_bias": "0",
                "x": "640.0",
                "y": "384.0",
            },
            "observer": {
                "death_transition_hits": "0",
                "staff_drop_hits": "0",
                "death_presentation_ticks": "150",
                "authoritative_death_presentation_ticks": "159",
                "death_drive_state": "1",
                "grid_member_flag": "1",
                "hp": "0",
                "render_sort_bias": "0",
                "x": "640.0",
                "y": "384.0",
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
        "spectator_seconds": 6.4,
        "red_cleared_seconds": 6.4,
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

    def test_dead_input_world_probe_parser_preserves_spawn_identity(
        self,
    ) -> None:
        actors = verifier._parse_dead_input_world_probe(
            "count=1\nW|1234|2004|5678|false\n"
        )

        self.assertEqual(
            actors,
            [
                {
                    "actor_address": 1234,
                    "object_type_id": 2004,
                    "owner_address": 5678,
                    "tracked_enemy": False,
                }
            ],
        )

    def test_single_target_spectator_samples_remain_camera_stable(
        self,
    ) -> None:
        target_id = 2305843009213698050
        samples = [
            {
                "active": "true",
                "phase": "Spectating",
                "target_participant_id": str(target_id),
                "target_name": "Client Player",
                "target_alive": "true",
                "target_x": "812.25",
                "target_y": "150.0",
                "camera_focus_active": "true",
                "camera_center_x": "812.25",
                "camera_center_y": "150.0",
                "display_text":
                    "Spectating Client Player  |  "
                    "Left / Right click: next player",
            },
            {
                "active": "true",
                "phase": "Spectating",
                "target_participant_id": str(target_id),
                "target_name": "Client Player",
                "target_alive": "true",
                "target_x": "813.0",
                "target_y": "150.0",
                "camera_focus_active": "true",
                "camera_center_x": "813.1",
                "camera_center_y": "150.0",
                "display_text":
                    "Spectating Client Player  |  "
                    "Left / Right click: next player",
            },
        ]

        result = verifier._assert_single_target_spectator_samples(
            samples,
            expected_target_participant_id=target_id,
        )

        self.assertTrue(result["stable"])
        self.assertEqual(2, result["sample_count"])
        self.assertEqual(["Client Player"], result["target_names"])

    def test_single_target_spectator_sample_rejects_blank_target(
        self,
    ) -> None:
        target_id = 2305843009213698050
        sample = {
            "active": "true",
            "phase": "Spectating",
            "target_participant_id": "0",
            "target_name": "",
            "target_alive": "false",
            "target_x": "0",
            "target_y": "0",
            "camera_focus_active": "false",
            "camera_center_x": "0",
            "camera_center_y": "0",
            "display_text": "Spectating - waiting for an alive player",
        }

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "blanked or migrated",
        ):
            verifier._assert_single_target_spectator_samples(
                [sample],
                expected_target_participant_id=target_id,
            )

    def test_lifecycle_samples_are_timestamped_after_blocking_queries(
        self,
    ) -> None:
        owner = {
            "active": "true",
            "phase": "Spectating",
            "hp": "0",
            "death_drive_state": "1",
            "red_effect_active": "false",
            "death_transition_hits": "1",
            "staff_drop_hits": "1",
        }
        observer = {
            "hp": "0",
            "death_drive_state": "1",
            "presentation_active": "false",
            "red_effect_active": "false",
        }
        with (
            patch.object(
                verifier.time,
                "monotonic",
                side_effect=(100.0, 100.0, 100.0, 102.0),
            ),
            patch.object(
                verifier,
                "query_spectator_state",
                return_value=owner,
            ),
            patch.object(
                verifier,
                "query_remote_death_state",
                return_value=observer,
            ),
        ):
            samples, milestones = verifier._sample_lifecycle(
                victim_pipe="victim",
                observer_pipe="observer",
                victim_id=23,
                timeout=10.0,
            )

        self.assertEqual(2.0, samples[0]["elapsed_seconds"])
        self.assertEqual(2.0, milestones["spectator_seconds"])
        self.assertEqual(2.0, milestones["red_cleared_seconds"])

    def test_completed_organic_lifecycle_requires_owner_only_drop(
        self,
    ) -> None:
        grace = verifier._assert_lifecycle(
            _completed_lifecycle(),
            _completed_milestones(),
        )

        self.assertAlmostEqual(grace, 5.0)

    def test_incomplete_native_death_animation_is_rejected(self) -> None:
        lifecycle = _completed_lifecycle()
        for sample in lifecycle:
            sample["owner"][
                "authoritative_death_presentation_ticks"
            ] = "158"
            sample["observer"][
                "authoritative_death_presentation_ticks"
            ] = "158"

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "terminal corpse frame",
        ):
            verifier._assert_lifecycle(
                lifecycle,
                _completed_milestones(),
            )

    def test_native_cpu_death_lifecycle_side_effect_is_rejected(
        self,
    ) -> None:
        lifecycle = _completed_lifecycle()
        lifecycle[1]["owner"]["death_presentation_ticks"] = "159"
        lifecycle[1]["owner"]["grid_member_flag"] = "0"
        lifecycle[1]["owner"]["render_sort_bias"] = "-1000"

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "native CPU death timer crossed",
        ):
            verifier._assert_lifecycle(
                lifecycle,
                _completed_milestones(),
            )

    def test_corpse_motion_during_grace_is_rejected(self) -> None:
        lifecycle = _completed_lifecycle()
        lifecycle[-1]["owner"]["x"] = "641.0"

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "corpse moved",
        ):
            verifier._assert_lifecycle(
                lifecycle,
                _completed_milestones(),
            )

    def test_observer_motion_before_death_delivery_is_not_corpse_motion(
        self,
    ) -> None:
        lifecycle = _completed_lifecycle()
        lifecycle[1]["observer"]["x"] = "625.0"

        verifier._assert_lifecycle(
            lifecycle,
            _completed_milestones(),
        )

    def test_prior_observer_death_traces_are_used_as_baseline(
        self,
    ) -> None:
        lifecycle = _completed_lifecycle()
        for sample in lifecycle:
            sample["observer"]["death_transition_hits"] = "7"
            sample["observer"]["staff_drop_hits"] = "9"

        verifier._assert_lifecycle(
            lifecycle,
            _completed_milestones(),
        )

    def test_observer_death_trace_increment_is_rejected(self) -> None:
        lifecycle = _completed_lifecycle()
        lifecycle[0]["observer"]["death_transition_hits"] = "1"
        lifecycle[0]["observer"]["staff_drop_hits"] = "1"
        lifecycle[-1]["observer"]["death_transition_hits"] = "2"
        lifecycle[-1]["observer"]["staff_drop_hits"] = "2"

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "observer executed owner-only",
        ):
            verifier._assert_lifecycle(
                lifecycle,
                _completed_milestones(),
            )

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

    def test_native_schedule_materialization_rewrites_every_wave_record(
        self,
    ) -> None:
        retail_schedule = (
            b"WAVE\r\n"
            b"\tNEXT:1\r\n"
            b"\tSPAWN:14\r\n"
            b"\tSPAWNDELAY:50-300\r\n"
            b"\tWAVEDELAY:100-300\r\n"
            b"\tMAXENEMIES:40\r\n"
            b"\tGROUP\r\n"
            b"\t\tSKELETON\r\n"
            b"\tENDWAVE\r\n"
            b"WAVE\r\n"
            b"\tNEXT:0,1\r\n"
            b"\tSPAWN:18\r\n"
            b"\tSPAWNDELAY:25-150\r\n"
            b"\tWAVEDELAY:80-180\r\n"
            b"\tMAXENEMIES:50\r\n"
            b"\tGROUP\r\n"
            b"\t\tSKELETONARCHER\r\n"
            b"\tENDWAVE\r\n"
            b"\tENDWAVE\r\n"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            source_path = temporary_root / "retail-wave.txt"
            output_path = temporary_root / "effective-wave.txt"
            source_path.write_bytes(retail_schedule)

            manifest = verifier._materialize_native_wave_schedule(
                retail_wave_path=source_path,
                fixture_path=verifier.WAVE_FIXTURES["poison"],
                output_path=output_path,
            )

            self.assertEqual(source_path.read_bytes(), retail_schedule)
            effective = output_path.read_bytes()
            self.assertIn(b"\r\n", effective)
            self.assertNotIn(b"\n", effective.replace(b"\r\n", b""))
            self.assertEqual(effective.splitlines().count(b"WAVE"), 2)
            self.assertEqual(effective.splitlines().count(b"\tENDWAVE"), 2)
            self.assertEqual(
                [
                    line
                    for line in effective.splitlines()
                    if line.lstrip().startswith(b"NEXT:")
                ],
                [b"\tNEXT:1", b"\tNEXT:0,1"],
            )
            self.assertEqual(effective.count(b"\tSPAWN:1\r\n"), 2)
            self.assertEqual(effective.count(b"\tMAXENEMIES:1\r\n"), 2)
            self.assertEqual(
                effective.count(
                    b"\t\tSKELETONMAGE:"
                    b"FLAG_CASTPOISON|FLAG_RANGEEASY\r\n"
                ),
                2,
            )
            self.assertEqual(manifest["record_count"], 2)
            self.assertEqual(manifest["next_graph"], ["1", "0,1"])
            self.assertEqual(
                manifest["enemy_token"],
                "SKELETONMAGE:FLAG_CASTPOISON|FLAG_RANGEEASY",
            )
            self.assertNotEqual(
                manifest["retail_sha256"],
                manifest["effective_sha256"],
            )

    def test_pre_wave_boneyard_enemies_cannot_satisfy_wave_selection(
        self,
    ) -> None:
        actors = verifier._parse_live_enemy_probe(
            "A|111|1001|10.0|20.0|2.5\n"
            "A|222|1001|30.0|40.0|2.5\n"
        )

        selected = verifier._select_new_wave_enemy(
            actors,
            pre_wave_actor_addresses={111},
        )

        self.assertEqual(selected["actor_address"], 222)
        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "new native-wave enemy",
        ):
            verifier._select_new_wave_enemy(
                actors[:1],
                pre_wave_actor_addresses={111},
            )

    def test_fixtures_define_stock_wave_enemies_without_scripted_damage(
        self,
    ) -> None:
        expected = {
            "melee": "SKELETON",
            "projectile":
                "SKELETONMAGE:FLAG_CASTFIRE|FLAG_RANGEEASY",
            "poison":
                "SKELETONMAGE:FLAG_CASTPOISON|FLAG_RANGEEASY",
        }
        self.assertEqual(
            verifier.EXPECTED_BASE_ACTOR_OBJECT_TYPE,
            1001,
        )
        for kill_type, token in expected.items():
            fixture_path = verifier.WAVE_FIXTURES[kill_type]
            fixture_bytes = fixture_path.read_bytes()
            fixture = fixture_bytes.decode("utf-8")
            self.assertIn(token, fixture)
            self.assertEqual(
                verifier._read_wave_fixture_enemy_token(fixture_path),
                token,
            )
            self.assertNotIn("1000", fixture)
            self.assertNotIn("invoke_native_magic_hit_trial", fixture)


if __name__ == "__main__":
    unittest.main()
