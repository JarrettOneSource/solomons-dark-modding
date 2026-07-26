#!/usr/bin/env python3
"""Unit contracts for the exact seeded Boneyard decor verifier."""

from __future__ import annotations

import copy
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_run_static_layout_sync as verifier  # noqa: E402


def float_bits(value: float) -> str:
    bits = struct.unpack("<I", struct.pack("<f", value))[0]
    return f"0x{bits:08X}"


def matching_layout() -> dict[str, str]:
    row = {
        "scene": "testrun",
        "local_run_nonce": "0x12345678",
        "circle_count": "8",
        "circle_mask4_count": "4",
        "circle_mask4_digest": "0x00000001",
        "shape_count": "2",
        "shape_digest": "0x00000002",
        "static_actor_count": "0",
        "static_actor_digest": "0x00000003",
        "boneyard_scenery_count": "3",
        "boneyard_scenery_sampled": "1",
        "boneyard_scenery_digest": "0x00000004",
        "boneyard_tree_count": "1",
        "boneyard_tree_digest": "0x00000005",
        "boneyard_road_count": "2",
        "boneyard_road_sampled": "0",
        "boneyard_road_digest": "0x00000006",
        "boneyard_fence_count": "1",
        "boneyard_fence_sampled": "0",
        "boneyard_fence_digest": "0x00000007",
        "boneyard_terrain_count": "0",
        "boneyard_terrain_sampled": "0",
        "boneyard_terrain_digest": "0x00000008",
        "boneyard_compact_count": "1",
        "boneyard_compact_sampled": "1",
        "boneyard_compact_digest": "0x00000009",
        "boneyard_compact_ignored_flag_bits_count": "0",
        "boneyard_compact_type_7_8_count": "1",
        "boneyard_compact_type_7_8_noncanonical_flags": "0",
        "boneyard_compact_type_21_24_count": "1",
        "boneyard_presentation_run_seed": "0x12345678",
        "boneyard_presentation_arena_ambient_kind": "1",
        "boneyard_presentation_compact_ambient_result": "0",
        "boneyard_presentation_secondary_ambient_result": "0",
        "boneyard_presentation_marker_scale_bits": float_bits(0.05),
        "boneyard_presentation_marker_sign_mode": "0",
        "boneyard_presentation_marker_bias_low_bits": "0x60000000",
        "boneyard_presentation_marker_bias_high_bits": "0x3FEE6666",
        "boneyard_presentation_digest": "0x0000000A",
        "replicated_run_static_count": "0",
        "replicated_matched_actor_count": "0",
    }
    for type_id in (
        2001,
        2009,
        2029,
        2040,
        2061,
        2062,
        3006,
        3007,
        3011,
        3012,
        3013,
        3014,
    ):
        row[f"boneyard_scenery_type_{type_id}_count"] = (
            "1" if type_id == 2001 else "0"
        )
    for family in (
        "tree_ground_cover",
        "ground_patches",
        "paving_stones",
        "pebbles",
        "twig_lattice",
        "large_rocks",
        "shadow_masks",
        "dead_roots",
    ):
        row[f"boneyard_compact_family_{family}_count"] = (
            "1" if family == "large_rocks" else "0"
        )
    return row


class RunStaticLayoutSyncTest(unittest.TestCase):
    def test_full_render_digest_covers_presentation_and_profile(self) -> None:
        render_decor = {
            "scenery": [],
            "trees": [],
            "roads": [],
            "fences": [],
            "terrain": [],
            "compact": [],
            "presentation_inputs": {
                "run_seed": 0x12345678,
                "ambient_spawn_results": {
                    "compact": 0,
                    "secondary": 0,
                },
                "marker_tint": {
                    "scale_bits": int(float_bits(0.05), 0),
                    "sign_mode": 0,
                    "bias_bits": [0x60000000, 0x3FEE6666],
                },
            },
        }
        profile = {
            "after.complex_lighting": "1",
            "after.complex_shadows": "1",
            "after.multiple_shadows": "1",
            "after.zoom_effects": "1",
            "after.enhanced_effects": "0",
        }
        baseline = verifier.full_render_input_digest(
            render_decor,
            profile,
        )
        self.assertEqual(
            baseline,
            verifier.full_render_input_digest(
                copy.deepcopy(render_decor),
                dict(profile),
            ),
        )

        changed_presentation = copy.deepcopy(render_decor)
        changed_presentation["presentation_inputs"]["marker_tint"][
            "scale_bits"
        ] += 1
        self.assertNotEqual(
            baseline,
            verifier.full_render_input_digest(
                changed_presentation,
                profile,
            ),
        )

        changed_profile = dict(profile)
        changed_profile["after.complex_lighting"] = "0"
        self.assertNotEqual(
            baseline,
            verifier.full_render_input_digest(
                render_decor,
                changed_profile,
            ),
        )

    def test_exact_tree_and_compact_tables_decode_float_bits(self) -> None:
        row = matching_layout()
        row.update(
            {
                "boneyard_tree.1.type_id": "2001",
                "boneyard_tree.1.x_bits": float_bits(125.5),
                "boneyard_tree.1.y_bits": float_bits(-32.25),
                "boneyard_tree.1.radius_bits": float_bits(48.0),
                "boneyard_tree.1.materialization_key": "-3200",
                "boneyard_tree.1.variant": "6",
                "boneyard_tree.1.overlay_variant": "2",
                "boneyard_tree.1.overlay_enabled": "1",
                "boneyard_tree.1.phase_bits": float_bits(0.25),
                "boneyard_tree.1.render_parameter_bits": float_bits(1.0),
                "boneyard_tree.1.common_scalar_bits": float_bits(0.0),
                "boneyard_tree.1.sway_countdown": "25",
                "boneyard_tree.1.sway_target_bits": float_bits(1.0),
                "boneyard_tree.1.sway_current_bits": float_bits(1.0),
                "boneyard_tree.1.scrub_collision_flag": "0",
                "boneyard_tree.1.native_index": "4",
                "boneyard_scenery.1.row": ",".join(
                    (
                        "4",
                        "2001",
                        str(int(float_bits(125.5), 0)),
                        str(int(float_bits(-32.25), 0)),
                        str(int(float_bits(48.0), 0)),
                        "-3200",
                        "0",
                        "0",
                        "0",
                        str(int(float_bits(1.0), 0)),
                        "0",
                        str(int(float_bits(1.0), 0)),
                        str(int(float_bits(1.0), 0)),
                        "0",
                        "0",
                        "0",
                        str(int(float_bits(1.0), 0)),
                        str(int(float_bits(1.0), 0)),
                        "5",
                        "6",
                        "2",
                        "1",
                        str(int(float_bits(1.0), 0)),
                        str(int(float_bits(1.0), 0)),
                    )
                ),
                "boneyard_compact.1.row": ",".join(
                    (
                        "8",
                        "7",
                        float_bits(128.0),
                        float_bits(-30.0),
                        float_bits(-3.5),
                        float_bits(0.875),
                        float_bits(1.0),
                        "1",
                        float_bits(112.0),
                        float_bits(-46.0),
                        float_bits(144.0),
                        float_bits(-14.0),
                    )
                ),
            }
        )

        tables = verifier.decor_tables(row)
        self.assertEqual(tables["trees"][0]["type_id"], 2001)
        self.assertEqual(tables["trees"][0]["position"], [125.5, -32.25])
        self.assertEqual(tables["trees"][0]["variant"], 6)
        self.assertEqual(tables["trees"][0]["common_scalar_bits"], 0)
        self.assertNotIn("sway_countdown", tables["trees"][0])
        self.assertEqual(tables["trees"][0]["native_index"], 4)
        self.assertEqual(tables["compact"][0]["type_id"], 7)
        self.assertEqual(tables["compact"][0]["native_index"], 8)
        self.assertEqual(tables["compact"][0]["position"], [128.0, -30.0])
        self.assertEqual(tables["compact"][0]["rotation"], -3.5)
        self.assertEqual(tables["compact"][0]["scale"], 0.875)
        self.assertEqual(tables["compact"][0]["flags"], 1)
        self.assertEqual(
            tables["presentation_inputs"]["run_seed"],
            0x12345678,
        )
        self.assertEqual(
            tables["presentation_inputs"]["ambient_spawn_results"],
            {"compact": 0, "secondary": 0},
        )
        self.assertEqual(
            tables["compact"][0]["bounds_bits"][0],
            int(float_bits(112.0), 0),
        )

    def test_layout_match_requires_canonical_type_7_8_flags(self) -> None:
        host = matching_layout()
        client = matching_layout()
        self.assertTrue(verifier.layouts_match(host, client))

        client["boneyard_compact_type_7_8_noncanonical_flags"] = "1"
        self.assertFalse(verifier.layouts_match(host, client))

    def test_camera_target_selects_a_central_tree_and_nearby_compact(self) -> None:
        decor = {
            "trees": [
                {"position": [0.0, 0.0]},
                {"position": [1000.0, 1000.0]},
            ],
            "compact": [
                {"type_id": 7, "position": [995.0, 1000.0], "flags": 1},
                {"type_id": 8, "position": [100.0, 100.0], "flags": 1},
            ],
        }
        target = verifier.matched_camera_target(decor)
        self.assertEqual(target["position"], [0.0, 0.0])
        self.assertEqual(target["nearby_compact"]["position"], [100.0, 100.0])
        self.assertAlmostEqual(target["nearby_compact_distance"], 2**0.5 * 100)

    def test_camera_targets_require_a_real_nav_parking_sample(self) -> None:
        decor = {
            "trees": [
                {
                    "type_id": 2001,
                    "position": [1000.0, 1000.0],
                    "native_index": 1,
                },
                {
                    "type_id": 2001,
                    "position": [1500.0, 1000.0],
                    "native_index": 2,
                },
            ],
            "scenery": [
                {
                    "type_id": 9999,
                    "position": [-1000.0, -1000.0],
                    "native_index": 0,
                },
                {
                    "type_id": 2029,
                    "position": [1600.0, 2200.0],
                    "native_index": 3,
                },
            ],
            "compact": [
                {
                    "type_id": 21,
                    "position": [1000.0, 1600.0],
                    "native_index": 4,
                },
                {
                    "type_id": 7,
                    "position": [1600.0, 1600.0],
                    "native_index": 5,
                },
                {
                    "type_id": 99,
                    "position": [3000.0, 3000.0],
                    "native_index": 6,
                },
            ],
        }
        parking_samples = [
            [1180.0, 1000.0],
            [680.0, 1600.0],
            [1280.0, 1600.0],
            [1280.0, 2200.0],
        ]
        targets = verifier.matched_camera_targets(
            decor,
            [[-5000.0, -5000.0]],
            parking_samples,
        )
        self.assertEqual(
            targets[0]["candidates"][0]["position"],
            [1500.0, 1000.0],
        )
        self.assertEqual(
            targets[0]["candidates"][0][
                "preselected_actor_parking_sample"
            ]["position"],
            [1180.0, 1000.0],
        )
        self.assertEqual(
            targets[0]["candidates"][0][
                "preselected_actor_parking_sample"
            ]["target_distance"],
            verifier.TARGET_PLAYER_LIGHT_DISTANCE,
        )
        self.assertEqual(len(targets), 4)

    def test_actor_light_parking_is_shared_outside_roi_and_within_radial_band(
        self,
    ) -> None:
        target_x = 1000.0
        target_y = 2000.0
        goal_x, goal_y = verifier.actor_light_parking_goal(
            target_x,
            target_y,
        )
        self.assertEqual(
            [goal_x, goal_y],
            [680.0, 2000.0],
        )

        parking = verifier.actor_light_parking_geometry(
            target_x,
            target_y,
            680.0,
            2000.0,
        )
        self.assertEqual(parking["host"], [680.0, 2000.0])
        self.assertEqual(parking["client"], parking["host"])
        self.assertEqual(parking["actor_separation"], 0.0)
        self.assertGreaterEqual(
            parking["decor_roi_clearance"],
            verifier.MINIMUM_DECOR_ROI_CLEARANCE,
        )
        self.assertGreaterEqual(
            parking["target_distances"]["host"],
            verifier.MINIMUM_PLAYER_LIGHT_DISTANCE,
        )
        self.assertLessEqual(
            parking["target_distances"]["host"],
            verifier.MAXIMUM_PLAYER_LIGHT_DISTANCE,
        )
        self.assertEqual(
            parking["target_distances"]["host"],
            verifier.TARGET_PLAYER_LIGHT_DISTANCE,
        )

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "outside player-light radial band",
        ):
            verifier.actor_light_parking_geometry(
                target_x,
                target_y,
                735.0,
                2000.0,
            )

    def test_settled_actor_parking_allows_native_collision_displacement(
        self,
    ) -> None:
        settled = verifier.settled_actor_parking_geometry(
            1000.0,
            2000.0,
            {
                "host": [680.0, 2000.0],
                "client": [680.0, 2012.5],
            },
        )
        self.assertEqual(settled["owner_separation"], 12.5)
        self.assertTrue(settled["native_collision_displacement_allowed"])
        for owner in ("host", "client"):
            self.assertGreaterEqual(
                settled["target_distances"][owner],
                verifier.MINIMUM_PLAYER_LIGHT_DISTANCE
                - verifier.NATIVE_COLLISION_RADIAL_TOLERANCE,
            )
            self.assertLessEqual(
                settled["target_distances"][owner],
                verifier.MAXIMUM_PLAYER_LIGHT_DISTANCE
                + verifier.NATIVE_COLLISION_RADIAL_TOLERANCE,
            )
            self.assertGreaterEqual(
                settled["decor_roi_clearances"][owner],
                verifier.MINIMUM_DECOR_ROI_CLEARANCE,
            )

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "outside player-light radial band",
        ):
            verifier.settled_actor_parking_geometry(
                1000.0,
                2000.0,
                {
                    "host": [680.0, 2000.0],
                    "client": [1400.0, 2000.0],
                },
            )

    def test_actor_parking_retries_native_collision_displacement(self) -> None:
        candidates = [
            {
                "host": [680.0, 2000.0],
                "client": [680.0, 2000.0],
                "actor_light_candidate_count": 2,
                "candidate_index": 1,
            },
            {
                "host": [1000.0, 1680.0],
                "client": [1000.0, 1680.0],
                "actor_light_candidate_count": 2,
                "candidate_index": 2,
            },
        ]
        settled_positions = [
            [800.0, 2000.0, 0.0],
            [800.0, 2000.0, 0.0],
            [1000.0, 1680.0, 0.0],
            [1000.0, 1680.0, 0.0],
        ]
        attempts: list[dict[str, object]] = []
        with (
            mock.patch.object(
                verifier,
                "nav_actor_parking_positions",
                side_effect=candidates,
            ) as parking_samples,
            mock.patch.object(
                verifier,
                "place_player",
                return_value={"rebind": "true"},
            ),
            mock.patch.object(
                verifier.local_sync,
                "wait_for_local_transform_settled",
                side_effect=settled_positions,
            ),
        ):
            result = verifier.settle_shared_actor_parking(
                "host-pipe",
                "client-pipe",
                1000.0,
                2000.0,
                attempts,
            )

        self.assertEqual(parking_samples.call_count, 2)
        self.assertEqual(result["parking"]["candidate_index"], 2)
        self.assertFalse(attempts[0]["ok"])
        self.assertIn("exclusion zone", attempts[0]["error"])
        self.assertTrue(attempts[1]["ok"])
        self.assertEqual(
            result["settled_actor_geometry"]["owner_positions"],
            {
                "host": [1000.0, 1680.0],
                "client": [1000.0, 1680.0],
            },
        )

    def test_camera_target_retries_when_ranked_area_has_no_safe_parking(
        self,
    ) -> None:
        target_plan = {
            "family": "large-rocks",
            "candidates": [
                {
                    "family": "large-rocks",
                    "position": [1000.0, 2400.0],
                },
                {
                    "family": "large-rocks",
                    "position": [2000.0, 1600.0],
                },
            ],
        }
        safe_parking = {
            "parking": {"candidate_index": 1},
            "attempts": [{"candidate_index": 1, "ok": True}],
        }
        attempts: list[dict[str, object]] = []
        with mock.patch.object(
            verifier,
            "settle_shared_actor_parking",
            side_effect=[
                verifier.ParkingSelectionFailure("unsafe native wall"),
                safe_parking,
            ],
        ) as settle:
            result = verifier.settle_matched_camera_target(
                "host-pipe",
                "client-pipe",
                target_plan,
                [],
                attempts,
            )

        self.assertEqual(settle.call_count, 2)
        self.assertEqual(result["target"]["position"], [2000.0, 1600.0])
        self.assertFalse(attempts[0]["ok"])
        self.assertIn("unsafe native wall", attempts[0]["error"])
        self.assertTrue(attempts[1]["ok"])

    def test_exact_pixel_gate_rejects_a_displaced_world_region(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            host_path = root / "host.png"
            client_path = root / "client.png"
            displaced_path = root / "displaced.png"
            matched_prefix = root / "matched"
            displaced_prefix = root / "displaced"
            image = Image.new("RGB", (400, 240), "black")
            for x in range(80, 160):
                for y in range(60, 180):
                    image.putpixel(
                        (x, y),
                        (
                            100 + x % 120,
                            80 + y % 100,
                            50 + (x + y) % 100,
                        ),
                    )
            image.save(host_path)
            image.save(client_path)

            displaced = Image.new("RGB", image.size, "black")
            for x in range(240, 320):
                for y in range(60, 180):
                    displaced.putpixel(
                        (x, y),
                        (
                            100 + (x - 160) % 120,
                            80 + y % 100,
                            50 + (x + y - 160) % 100,
                        ),
                    )
            displaced.save(displaced_path)
            nameplate_only = image.copy()
            for x in range(190, 230):
                for y in range(90, 120):
                    nameplate_only.putpixel((x, y), (255, 0, 0))
            nameplate_path = root / "nameplate.png"
            nameplate_only.save(nameplate_path)

            camera = {"width": 400.0, "height": 240.0}
            matched = verifier.exact_decor_pixel_comparison(
                host_path,
                client_path,
                camera,
                matched_prefix,
            )
            mismatched = verifier.exact_decor_pixel_comparison(
                host_path,
                displaced_path,
                camera,
                displaced_prefix,
            )
            self.assertTrue(matched["exact_match"])
            self.assertEqual(matched["differing_pixel_count"], 0)
            self.assertTrue(matched["pixel_hashes_match"])
            self.assertFalse(mismatched["exact_match"])
            self.assertGreater(mismatched["differing_pixel_count"], 0)
            self.assertFalse(mismatched["pixel_hashes_match"])
            masked_nameplate = verifier.exact_decor_pixel_comparison(
                host_path,
                nameplate_path,
                camera,
                root / "masked-nameplate",
                excluded_rectangles=[[190, 90, 230, 120]],
            )
            self.assertTrue(masked_nameplate["exact_match"])
            self.assertEqual(
                masked_nameplate["excluded_pixel_count"],
                1200,
            )
            envelope_mismatch = (
                verifier.exact_temporal_envelope_decor_pixel_comparison(
                    [host_path] * 3,
                    [displaced_path] * 3,
                    camera,
                    root / "envelope-displaced",
                )
            )
            self.assertFalse(envelope_mismatch["exact_match"])
            self.assertGreater(
                envelope_mismatch["differing_envelope_pixel_count"],
                0,
            )

    def test_stable_pixel_gate_excludes_dynamic_actor_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            host_paths: list[Path] = []
            client_paths: list[Path] = []
            for frame in range(3):
                for peer, paths in (
                    ("host", host_paths),
                    ("client", client_paths),
                ):
                    image = Image.new("RGB", (400, 240), "black")
                    for x in range(80, 180):
                        for y in range(60, 180):
                            image.putpixel(
                                (x, y),
                                (
                                    80 + x % 150 + frame,
                                    60 + y % 140,
                                    40 + (x + y) % 180,
                                ),
                            )
                    dynamic_left = (
                        240
                        + frame * 20
                        + (5 if peer == "client" else 0)
                    )
                    for x in range(dynamic_left, dynamic_left + 30):
                        for y in range(90, 140):
                            image.putpixel((x, y), (255, 180, 80))
                    path = root / f"{peer}-{frame}.png"
                    image.save(path)
                    paths.append(path)

            result = verifier.exact_stable_decor_pixel_comparison(
                host_paths,
                client_paths,
                {"width": 400.0, "height": 240.0},
                root / "stable",
            )
            self.assertTrue(result["exact_match"])
            self.assertEqual(result["differing_stable_pixel_count"], 0)
            self.assertTrue(result["stable_pixel_hashes_match"])
            self.assertEqual(
                result["maximum_stable_temporal_channel_range"],
                2,
            )
            self.assertGreaterEqual(
                result["stable_visible_pixel_count"],
                result["minimum_stable_visible_pixel_count"],
            )
            envelope = (
                verifier.exact_temporal_envelope_decor_pixel_comparison(
                    host_paths,
                    client_paths,
                    {"width": 400.0, "height": 240.0},
                    root / "envelope",
                )
            )
            self.assertTrue(envelope["exact_match"])
            self.assertEqual(
                envelope["differing_envelope_pixel_count"],
                0,
            )
            self.assertEqual(
                envelope["maximum_envelope_channel_gap"],
                0,
            )

    def test_stable_pixel_gate_rejects_more_than_two_levels_of_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            host_paths: list[Path] = []
            client_paths: list[Path] = []
            for frame in range(3):
                host = Image.new("RGB", (400, 240))
                tolerated = Image.new("RGB", (400, 240))
                for x in range(400):
                    for y in range(240):
                        pixel = (
                            80 + x % 100,
                            60 + y % 100,
                            40 + (x + y) % 100,
                        )
                        host.putpixel((x, y), pixel)
                        tolerated.putpixel(
                            (x, y),
                            tuple(value + 2 for value in pixel),
                        )
                host_path = root / f"host-{frame}.png"
                client_path = root / f"client-{frame}.png"
                host.save(host_path)
                tolerated.save(client_path)
                host_paths.append(host_path)
                client_paths.append(client_path)

            tolerated = verifier.exact_stable_decor_pixel_comparison(
                host_paths,
                client_paths,
                {"width": 400.0, "height": 240.0},
                root / "tolerated",
            )
            self.assertFalse(tolerated["exact_match"])
            self.assertTrue(tolerated["bounded_match"])
            self.assertEqual(tolerated["maximum_stable_channel_delta"], 2)
            self.assertEqual(tolerated["maximum_stable_envelope_gap"], 2)

            phase_offsets = ((0, 3), (1, 2), (2, 4))
            for frame, (host_offset, client_offset) in enumerate(
                phase_offsets
            ):
                phased_host = Image.new("RGB", (400, 240))
                phased_client = Image.new("RGB", (400, 240))
                for x in range(400):
                    for y in range(240):
                        pixel = (
                            80 + x % 100,
                            60 + y % 100,
                            40 + (x + y) % 100,
                        )
                        phased_host.putpixel(
                            (x, y),
                            tuple(value + host_offset for value in pixel),
                        )
                        phased_client.putpixel(
                            (x, y),
                            tuple(value + client_offset for value in pixel),
                        )
                phased_host.save(host_paths[frame])
                phased_client.save(client_paths[frame])
            phased = verifier.exact_stable_decor_pixel_comparison(
                host_paths,
                client_paths,
                {"width": 400.0, "height": 240.0},
                root / "phased",
            )
            self.assertTrue(phased["bounded_match"])
            self.assertEqual(phased["maximum_stable_channel_delta"], 3)
            self.assertEqual(phased["maximum_stable_envelope_gap"], 0)

            for host_path, client_path in zip(
                host_paths,
                client_paths,
                strict=True,
            ):
                host = Image.new("RGB", (400, 240))
                shifted = Image.new("RGB", (400, 240))
                for x in range(400):
                    for y in range(240):
                        pixel = (
                            80 + x % 100,
                            60 + y % 100,
                            40 + (x + y) % 100,
                        )
                        host.putpixel((x, y), pixel)
                        shifted.putpixel(
                            (x, y),
                            tuple(value + 3 for value in pixel),
                        )
                host.save(host_path)
                shifted.save(client_path)
            rejected = verifier.exact_stable_decor_pixel_comparison(
                host_paths,
                client_paths,
                {"width": 400.0, "height": 240.0},
                root / "rejected",
            )
            self.assertFalse(rejected["bounded_match"])
            self.assertEqual(rejected["maximum_stable_channel_delta"], 3)
            self.assertEqual(rejected["maximum_stable_envelope_gap"], 3)

    def test_stable_pixel_gate_uses_visible_content_not_dark_fraction(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            host_paths: list[Path] = []
            client_paths: list[Path] = []
            for frame in range(3):
                image = Image.new("RGB", (400, 240), "black")
                for x in range(80, 85):
                    for y in range(240):
                        image.putpixel(
                            (x, y),
                            (
                                30 + x % 180,
                                20 + y % 180,
                                15 + (x + y) % 180,
                            ),
                        )
                for x in range(180, 320):
                    for y in range(240):
                        image.putpixel(
                            (x, y),
                            (
                                30 + x % 100 + frame * 10,
                                20 + y % 100 + frame * 10,
                                15 + (x + y) % 100 + frame * 10,
                            ),
                        )
                for peer, paths in (
                    ("host", host_paths),
                    ("client", client_paths),
                ):
                    path = root / f"{peer}-{frame}.png"
                    image.save(path)
                    paths.append(path)

            result = verifier.exact_stable_decor_pixel_comparison(
                host_paths,
                client_paths,
                {"width": 400.0, "height": 240.0},
                root / "visible-content",
            )
            self.assertLess(result["stable_pixel_fraction"], 0.5)
            self.assertLess(result["stable_visible_pixel_count"], 1536)
            self.assertGreaterEqual(
                result["stable_visible_pixel_count"],
                result["minimum_stable_visible_pixel_count"],
            )
            self.assertGreaterEqual(
                result["stable_host_unique_colors"],
                result["minimum_stable_unique_colors"],
            )
            self.assertTrue(result["bounded_match"])

            blank_paths: list[Path] = []
            for frame in range(3):
                path = root / f"blank-{frame}.png"
                Image.new("RGB", (400, 240), "black").save(path)
                blank_paths.append(path)
            blank = verifier.exact_stable_decor_pixel_comparison(
                blank_paths,
                blank_paths,
                {"width": 400.0, "height": 240.0},
                root / "blank-content",
            )
            self.assertEqual(blank["stable_pixel_fraction"], 1.0)
            self.assertFalse(blank["sufficient_stable_content"])
            self.assertFalse(blank["bounded_match"])

    def test_temporal_maximum_edge_gate_rejects_missing_decor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            host_paths: list[Path] = []
            client_paths: list[Path] = []
            for frame in range(3):
                for peer, paths in (
                    ("host", host_paths),
                    ("client", client_paths),
                ):
                    image = Image.new("RGB", (400, 240), "black")
                    for x in range(80, 320):
                        for y in range(48, 192):
                            value = (
                                220
                                if ((x // 4) + (y // 4)) % 2
                                else 35
                            )
                            image.putpixel(
                                (x, y),
                                (
                                    value,
                                    (value + frame * 7) % 256,
                                    value // 2,
                                ),
                            )
                    path = root / f"{peer}-{frame}.png"
                    image.save(path)
                    paths.append(path)

            matching = verifier.temporal_maximum_edge_comparison(
                host_paths,
                client_paths,
                {"width": 400.0, "height": 240.0},
                root / "matching",
            )
            self.assertTrue(matching["ok"])
            self.assertGreaterEqual(
                matching["host_edge_count"],
                matching["minimum_edge_count"],
            )

            for path in client_paths:
                with Image.open(path) as source:
                    changed = source.convert("RGB")
                for x in range(130, 270):
                    for y in range(60, 180):
                        changed.putpixel((x, y), (0, 0, 0))
                changed.save(path)

            changed = verifier.temporal_maximum_edge_comparison(
                host_paths,
                client_paths,
                {"width": 400.0, "height": 240.0},
                root / "changed",
            )
            self.assertFalse(changed["ok"])


if __name__ == "__main__":
    unittest.main()
