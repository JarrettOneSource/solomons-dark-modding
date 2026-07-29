#!/usr/bin/env python3
"""Contracts for the isolated four-fighter bot-match harness."""

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

import run_bot_match as bot_match  # noqa: E402


class BotMatchRunnerTests(unittest.TestCase):
    def test_arrival_radius_tolerates_only_float_noise(self) -> None:
        self.assertTrue(
            bot_match.within_arrival_radius(50.000032, 50.0)
        )
        self.assertFalse(
            bot_match.within_arrival_radius(50.02, 50.0)
        )

    def test_instance_name_preserves_readable_unique_batch_suffix(self) -> None:
        self.assertNotEqual(
            bot_match.instance_name(
                "smoke",
                1,
                "smoke-regression-01",
            ),
            bot_match.instance_name(
                "smoke",
                1,
                "smoke-regression-02",
            ),
        )
        long_name = bot_match.instance_name(
            "full",
            3,
            "a-very-long-readable-botmatch-baseline-run-name-003",
        )
        self.assertLessEqual(len(long_name), 48)
        self.assertTrue(long_name.endswith("name-003"))

    def test_configuration_owns_exact_ports_roster_and_evidence_root(
        self,
    ) -> None:
        config = bot_match.BotMatchConfig.load(
            TOOLS_ROOT / "bot_match.example.json"
        )
        self.assertEqual(
            (config.local_port, config.unused_remote_port),
            (50511, 50512),
        )
        self.assertEqual(
            config.evidence_root,
            Path("/mnt/d/codex-evidence/botmatch-20260728"),
        )
        self.assertEqual(len(config.bots), 3)
        self.assertEqual(
            [fighter.name for fighter in config.bots],
            ["Ember", "Brook", "Gale"],
        )
        self.assertEqual(config.gate_formation_spacing, 65.0)
        self.assertEqual(config.gate_parking_arrival_radius, 12.0)
        self.assertEqual(
            config.gate_alignment_lateral_tolerance,
            35.0,
        )
        self.assertEqual(config.gather_distance, 400.0)
        self.assertEqual(config.gather_search_step, 65.0)
        self.assertEqual(config.gather_search_limit, 260.0)
        self.assertEqual(config.run_count, 3)

    def test_gate_selection_uses_live_openable_segments_on_route(
        self,
    ) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        selected = runner.select_route_gate(
            (100.0, 100.0),
            (100.0, 1000.0),
            [
                {
                    "object": 1,
                    "record": 2,
                    "start": (500.0, 400.0),
                    "end": (520.0, 400.0),
                    "midpoint": (510.0, 400.0),
                },
                {
                    "object": 3,
                    "record": 4,
                    "start": (80.0, 500.0),
                    "end": (120.0, 500.0),
                    "midpoint": (100.0, 500.0),
                },
            ],
        )
        self.assertEqual(selected["midpoint"], (100.0, 500.0))
        self.assertEqual(selected["routeUnit"], (0.0, 1.0))
        self.assertEqual(selected["gateTangentUnit"], (1.0, 0.0))
        self.assertEqual(len(selected["segments"]), 1)

    def test_four_fighter_formation_includes_slot_zero_and_roster(
        self,
    ) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.config = bot_match.BotMatchConfig.load(
            TOOLS_ROOT / "bot_match.example.json"
        )
        formation = runner.formation(
            (100.0, 200.0),
            (0.0, 1.0),
            10.0,
        )
        self.assertEqual(
            list(formation),
            ["slot0", "Ember", "Brook", "Gale"],
        )
        self.assertEqual(len(set(formation.values())), 4)
        points = list(formation.values())
        self.assertEqual(
            points,
            [
                (105.0, 195.0),
                (95.0, 195.0),
                (105.0, 205.0),
                (95.0, 205.0),
            ],
        )

    def test_gate_formation_is_collision_spaced_and_stays_behind_front(
        self,
    ) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.config = bot_match.BotMatchConfig.load(
            TOOLS_ROOT / "bot_match.example.json"
        )
        formation = runner.gate_formation(
            (100.0, 200.0),
            (0.0, 1.0),
        )
        points = list(formation.values())
        for left_index, left in enumerate(points):
            for right in points[left_index + 1:]:
                self.assertGreaterEqual(
                    bot_match.distance(left, right),
                    runner.config.gate_formation_spacing,
                )
        self.assertEqual(points[0][1], 200.0)
        self.assertEqual(points[1][1], 200.0)
        self.assertEqual(points[2][1], 135.0)
        self.assertEqual(points[3][1], 135.0)

    def test_gate_arrival_is_signed_dig_side_progress(self) -> None:
        midpoint = (100.0, 200.0)
        transit = (0.0, 1.0)
        self.assertEqual(
            bot_match.signed_gate_progress(
                (75.0, 265.0),
                midpoint,
                transit,
            ),
            65.0,
        )
        self.assertEqual(
            bot_match.signed_gate_progress(
                (125.0, 135.0),
                midpoint,
                transit,
            ),
            -65.0,
        )
        self.assertEqual(
            bot_match.gate_lateral_offset(
                (135.0, 225.0),
                midpoint,
                (1.0, 0.0),
            ),
            35.0,
        )

    def test_gate_approach_allows_one_formation_lane_past_leaf_end(
        self,
    ) -> None:
        source = (TOOLS_ROOT / "run_bot_match.py").read_text(
            encoding="utf-8"
        )
        approach = source[
            source.index("    def wait_gate_approach("):
            source.index("    def wait_group(")
        ]
        self.assertIn(
            "max(endpoint_offsets)\n"
            "            + self.config.gate_formation_spacing",
            approach,
        )
        self.assertNotIn(
            "max(endpoint_offsets) + self.config.gate_arrival_radius",
            approach,
        )

    def test_hub_gather_search_rejects_blocked_native_segment(
        self,
    ) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.config = bot_match.BotMatchConfig.load(
            TOOLS_ROOT / "bot_match.example.json"
        )
        placements = []
        segment_results = iter(
            [
                {
                    "allTraversable": False,
                    "blockedCount": 2,
                    "totalDistance": 500.0,
                    "fighters": {},
                },
                {
                    "allTraversable": True,
                    "blockedCount": 0,
                    "totalDistance": 400.0,
                    "fighters": {},
                },
            ]
        )
        with (
            patch.object(
                runner,
                "assign_destinations_without_crossing",
                side_effect=lambda destinations: destinations,
            ),
            patch.object(
                runner,
                "validate_gate_convoy_destinations",
                side_effect=lambda destinations: placements.append(
                    destinations
                ) or {"clear": "true"},
            ),
            patch.object(
                runner,
                "validate_group_segments",
                side_effect=lambda _: next(segment_results),
            ),
        ):
            plan = runner.plan_hub_gather(
                (0.0, 0.0),
                {"midpoint": (0.0, 1000.0)},
                (0.0, -1.0),
            )

        self.assertEqual(plan["selectedDistance"], 465.0)
        self.assertEqual(len(plan["attempts"]), 2)
        self.assertEqual(len(placements), 2)
        self.assertFalse(
            plan["attempts"][0]["segments"]["allTraversable"]
        )
        self.assertTrue(
            plan["attempts"][1]["segments"]["allTraversable"]
        )

    def test_hub_gather_target_is_capped_by_short_live_route(
        self,
    ) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.config = bot_match.BotMatchConfig.load(
            TOOLS_ROOT / "bot_match.example.json"
        )
        with (
            patch.object(
                runner,
                "assign_destinations_without_crossing",
                side_effect=lambda destinations: destinations,
            ),
            patch.object(
                runner,
                "validate_gate_convoy_destinations",
                return_value={"clear": "true"},
            ),
            patch.object(
                runner,
                "validate_group_segments",
                return_value={
                    "allTraversable": True,
                    "blockedCount": 0,
                    "totalDistance": 100.0,
                    "fighters": {},
                },
            ),
        ):
            plan = runner.plan_hub_gather(
                (0.0, 0.0),
                {"midpoint": (0.0, 435.0)},
                (0.0, -1.0),
            )

        self.assertTrue(plan["routeCapped"])
        self.assertEqual(plan["selectedDistance"], 325.0)

    def test_gate_convoy_holds_fighters_clear_of_each_other(self) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.config = bot_match.BotMatchConfig.load(
            TOOLS_ROOT / "bot_match.example.json"
        )
        destinations = runner.gate_convoy_destinations(
            {
                "midpoint": (100.0, 200.0),
                "routeUnit": (0.0, 1.0),
            }
        )
        self.assertEqual(
            list(destinations),
            ["slot0", "Ember", "Brook", "Gale"],
        )
        points = list(destinations.values())
        for left_index, left in enumerate(points):
            for right in points[left_index + 1:]:
                self.assertGreater(
                    bot_match.distance(left, right),
                    runner.config.gate_formation_spacing,
                )
        self.assertEqual(
            [
                bot_match.signed_gate_progress(
                    point,
                    (100.0, 200.0),
                    (0.0, 1.0),
                )
                for point in points
            ],
            [240.0, 175.0, 175.0, 110.0],
        )
        crossing = (
            100.0,
            200.0 + runner.config.gate_exit_distance,
        )
        self.assertEqual(destinations["Gale"], crossing)

    def test_regroup_recommands_fighters_pushed_out_of_hold(
        self,
    ) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        destinations = {
            "Ember": (10.0, 20.0),
            "Brook": (30.0, 40.0),
            "Gale": (50.0, 60.0),
        }
        released = {"Ember", "Brook"}
        with (
            patch.object(
                runner,
                "command_fighter",
                return_value={"accepted": "true"},
            ) as command,
            patch.object(
                runner,
                "stop_fighter",
                return_value={"accepted": "true"},
            ) as stop,
        ):
            reissued = runner.reconcile_group_holds(
                {"Brook", "Gale"},
                released,
                destinations,
            )

        self.assertEqual(reissued, ["Ember"])
        self.assertEqual(released, {"Brook", "Gale"})
        command.assert_called_once_with("Ember", (10.0, 20.0))
        stop.assert_called_once_with("Gale")

    def test_slot_zero_convoy_command_renders_numeric_lua(self) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.config = bot_match.BotMatchConfig.load(
            TOOLS_ROOT / "bot_match.example.json"
        )
        captured = []

        def values(source: str) -> dict[str, str]:
            captured.append(source)
            return {"accepted": "true"}

        runner.values = values
        runner.command_fighter("slot0", (123.25, 456.5))
        self.assertIn(
            "controller.arrival_radius = 12.000000000",
            captured[0],
        )
        self.assertIn("x = 123.250000000", captured[0])
        self.assertIn("y = 456.500000000", captured[0])

    def test_group_command_holds_fighters_already_inside_radius(
        self,
    ) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.config = bot_match.BotMatchConfig.load(
            TOOLS_ROOT / "bot_match.example.json"
        )
        runner.snapshot = lambda: {}
        runner.fighter_position_record = lambda _snapshot: {
            "slot0": {"x": 0.0, "y": 0.0},
            "Ember": {"x": 10.0, "y": 0.0},
            "Brook": {"x": 100.0, "y": 0.0},
            "Gale": {"x": 120.0, "y": 0.0},
        }
        stops = []
        runner.stop_group = lambda: stops.append(True)
        captured = []

        def values(source: str) -> dict[str, str]:
            captured.append(source)
            return {"accepted": "2", "failures": ""}

        runner.values = values
        result = runner.command_group(
            {
                "slot0": (5.0, 0.0),
                "Ember": (15.0, 0.0),
                "Brook": (20.0, 0.0),
                "Gale": (30.0, 0.0),
            },
            arrival_radius=10.0,
        )

        self.assertEqual(stops, [True])
        self.assertIn("controller.destination = nil", captured[0])
        self.assertNotIn('["Ember"]', captured[0])
        self.assertIn('["Brook"]', captured[0])
        self.assertIn('["Gale"]', captured[0])
        self.assertEqual(result["skipped"], "slot0,Ember")

    def test_gate_alignment_stays_at_the_safe_approach_distance(
        self,
    ) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.config = bot_match.BotMatchConfig.load(
            TOOLS_ROOT / "bot_match.example.json"
        )
        runner.validate_gate_convoy_destinations = (
            lambda destinations: {
                "point": next(iter(destinations))
            }
        )
        runner.stop_group = lambda: {}
        runner.command_fighter = lambda *_args: {}
        runner.wait_fighter_destination = lambda *_args: {}
        result = runner.transit_gate_convoy(
            {
                "midpoint": (100.0, 200.0),
                "routeUnit": (0.0, 1.0),
            },
            {"slot0": (100.0, 310.0)},
            {"slot0": {"needsAlignment": True}},
        )
        self.assertEqual(result["alignment"], (100.0, 100.0))
        self.assertEqual(
            result["alignmentPlacement"],
            {"point": "alignment"},
        )

    def test_gate_convoy_clears_aligned_front_before_rear(self) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.config = bot_match.BotMatchConfig.load(
            TOOLS_ROOT / "bot_match.example.json"
        )
        runner.snapshot = lambda: {}
        runner.fighter_position_record = lambda _snapshot: {
            "slot0": {"x": 100.0, "y": 90.0},
            "Ember": {"x": 125.0, "y": 95.0},
            "Brook": {"x": 145.0, "y": 25.0},
            "Gale": {"x": 100.0, "y": 0.0},
        }
        gate = {
            "midpoint": (100.0, 200.0),
            "routeUnit": (0.0, 1.0),
            "gateTangentUnit": (1.0, 0.0),
        }
        holding = runner.gate_convoy_destinations(gate)
        plan = runner.plan_gate_convoy(gate, holding)
        self.assertEqual(
            plan["order"],
            ["Ember", "slot0", "Brook", "Gale"],
        )
        self.assertFalse(
            plan["fighters"]["Ember"]["needsAlignment"]
        )
        self.assertTrue(
            plan["fighters"]["Brook"]["needsAlignment"]
        )
        self.assertEqual(
            list(plan["destinations"].values()),
            list(holding.values()),
        )

    def test_group_assignment_preserves_lateral_order(self) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.snapshot = lambda: {}
        runner.fighter_position_record = lambda _snapshot: {
            "slot0": {"x": 30.0, "y": 0.0},
            "Ember": {"x": 20.0, "y": 0.0},
            "Brook": {"x": 10.0, "y": 0.0},
            "Gale": {"x": 0.0, "y": 0.0},
        }
        assigned = runner.assign_destinations_without_crossing(
            {
                "slot0": (0.0, 100.0),
                "Ember": (10.0, 100.0),
                "Brook": (20.0, 100.0),
                "Gale": (30.0, 100.0),
            }
        )
        self.assertEqual(
            assigned,
            {
                "slot0": (30.0, 100.0),
                "Ember": (20.0, 100.0),
                "Brook": (10.0, 100.0),
                "Gale": (0.0, 100.0),
            },
        )

    def test_gate_approach_assignment_avoids_roster_cell_crossing(
        self,
    ) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.snapshot = lambda: {}
        runner.fighter_position_record = lambda _snapshot: {
            "slot0": {"x": 1151.35, "y": 150.0},
            "Ember": {"x": 1151.35, "y": 97.0},
            "Brook": {"x": 1200.14, "y": 162.03},
            "Gale": {"x": 1151.35, "y": 200.25},
        }
        assigned = runner.assign_destinations_without_crossing(
            {
                "slot0": (1166.38, 201.55),
                "Ember": (1101.61, 206.97),
                "Brook": (1160.97, 136.78),
                "Gale": (1096.20, 142.19),
            }
        )

        starts = runner.fighter_position_record({})
        segments = [
            (
                (starts[key]["x"], starts[key]["y"]),
                assigned[key],
            )
            for key in assigned
        ]
        self.assertFalse(
            any(
                bot_match.segments_properly_cross(
                    left[0],
                    left[1],
                    right[0],
                    right[1],
                )
                for index, left in enumerate(segments)
                for right in segments[index + 1:]
            )
        )
        self.assertLess(
            sum(
                bot_match.distance(start, target)
                for start, target in segments
            ),
            220.0,
        )

    def test_gate_approach_accepts_native_blocked_endpoint_envelope(
        self,
    ) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.config = bot_match.BotMatchConfig.load(
            TOOLS_ROOT / "bot_match.example.json"
        )
        gate = {
            "midpoint": (0.0, 0.0),
            "routeUnit": (0.0, 1.0),
            "gateTangentUnit": (1.0, 0.0),
            "segments": [
                {"start": (-60.0, 0.0), "end": (60.0, 0.0)},
            ],
        }
        destinations = runner.gate_formation(
            (0.0, -runner.config.gate_approach_distance),
            gate["routeUnit"],
        )
        positions = {
            key: {
                "x": target[0],
                "y": target[1],
            }
            for key, target in destinations.items()
        }
        positions["Brook"] = {
            "x": 0.0,
            "y": -220.0,
        }
        runner.stuck_teleport_lines = lambda: []
        runner.snapshot = lambda: {
            "sampledAt": "test",
            "wave": 0,
            "solomon": {"acquired": False},
        }
        runner.fighter_position_record = lambda _snapshot: positions
        accepted_samples = []

        def reconcile(
            accepted: set[str],
            _released: set[str],
            _destinations: dict[str, tuple[float, float]],
        ) -> list[str]:
            accepted_samples.append(accepted)
            return []

        runner.reconcile_group_holds = reconcile
        with (
            patch.object(
                bot_match.time,
                "monotonic",
                side_effect=(0.0, 1.0, 2.0, 3.0),
            ),
            patch.object(bot_match.time, "sleep"),
        ):
            result = runner.wait_gate_approach(gate, destinations)

        self.assertEqual(result["signedProgressBand"], [-230.0, -55.0])
        self.assertTrue(
            all("Brook" in accepted for accepted in accepted_samples)
        )
        self.assertGreater(
            bot_match.distance(
                (
                    positions["Brook"]["x"],
                    positions["Brook"]["y"],
                ),
                destinations["Brook"],
            ),
            runner.config.gate_parking_arrival_radius,
        )

    def test_post_gate_gather_uses_gate_to_solomon_route(self) -> None:
        source = (TOOLS_ROOT / "run_bot_match.py").read_text(
            encoding="utf-8"
        )
        post_gate = source[source.index("            dig_route ="):].split(
            '            result["end"] =',
            maxsplit=1,
        )[0]
        self.assertIn(
            'solomon[0] - gate["midpoint"][0]',
            post_gate,
        )
        self.assertIn(
            "self.plan_hub_gather(\n"
            "                solomon,\n"
            "                gate,\n"
            "                dig_route,",
            post_gate,
        )
        planner = source[
            source.index("    def plan_hub_gather("):
            source.index("    def command_fighter(")
        ]
        self.assertIn(
            "solomon[0] - dig_route[0] * candidate_distance",
            planner,
        )

    def test_known_scene_churn_is_retried_but_other_errors_are_not(
        self,
    ) -> None:
        self.assertTrue(
            bot_match.is_transient_scene_churn(
                "Gameplay scene churn is still in flight."
            )
        )
        self.assertTrue(
            bot_match.is_transient_scene_churn(
                "scene is settling"
            )
        )
        self.assertFalse(
            bot_match.is_transient_scene_churn(
                "host authority is unavailable"
            )
        )
        self.assertTrue(
            bot_match.is_transient_lua_pipe_transition(
                "Pipe closed without returning a response."
            )
        )
        self.assertFalse(
            bot_match.is_transient_lua_pipe_transition(
                "Lua execution failed with a syntax error."
            )
        )

    def test_monitor_lua_retries_only_the_transition_pipe_close(
        self,
    ) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.pipe_name = "test-pipe"
        calls = [
            RuntimeError("Pipe closed without returning a response."),
            "ok",
        ]

        def run(*_args, **_kwargs):
            result = calls.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with patch.object(bot_match, "run_checked", side_effect=run):
            self.assertEqual(
                runner.lua("return true", transition_retry_seconds=1),
                "ok",
            )
        with patch.object(
            bot_match,
            "run_checked",
            side_effect=RuntimeError("syntax error"),
        ):
            with self.assertRaisesRegex(
                bot_match.BotMatchFailure,
                "syntax error",
            ):
                runner.lua(
                    "return true",
                    transition_retry_seconds=1,
                )

    def test_damage_drain_preserves_exact_64_bit_participant_ids(
        self,
    ) -> None:
        participant_id = 0x200000000000B001
        runner = object.__new__(bot_match.BotMatchRun)
        runner.enemy_damage = []
        runner.player_damage = []
        runner.last_damage_monotonic = 0.0
        runner.lua = lambda _code, **_kwargs: "\n".join(
            (
                "enemy|1|100|"
                f"{participant_id}|10|11|0|12|13|14|20|17|20|3",
                "player|2|101|"
                f"{participant_id}|0|15|16|17|50|45|50|5",
            )
        )

        runner.drain_damage()

        self.assertEqual(
            runner.enemy_damage[0]["sourceParticipantId"],
            participant_id,
        )
        self.assertEqual(
            runner.player_damage[0]["targetParticipantId"],
            participant_id,
        )
        self.assertEqual(runner.enemy_damage[0]["damage"], 3.0)
        self.assertEqual(runner.player_damage[0]["damage"], 5.0)

    def test_damage_probe_returns_a_sentinel_when_no_edges_exist(
        self,
    ) -> None:
        self.assertIn(
            'if #output == 0 then\n  return "none"\nend',
            bot_match.DAMAGE_DRAIN_PROBE,
        )

    def test_wave_capture_retries_a_rejected_transition_frame(
        self,
    ) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.wave_screenshots = {}
        with tempfile.TemporaryDirectory() as temporary:
            runner.screenshot_directory = Path(temporary)
            raw = runner.screenshot_directory / "wave-09.bmp"
            raw.write_bytes(b"transition" * 1_000)

            def request_capture(_source: str) -> dict[str, str]:
                raw.write_bytes(b"gameplay" * 1_500)
                return {"ok": "true", "error": ""}

            validations = 0

            def validate(
                _raw: Path,
                output: Path,
            ) -> dict[str, object]:
                nonlocal validations
                validations += 1
                if validations == 1:
                    raise bot_match.VerificationFailure(
                        "blank transition frame"
                    )
                output.write_bytes(b"validated png")
                return {
                    "width": 640,
                    "height": 480,
                    "uniqueColors": 1000,
                    "dominantFraction": 0.5,
                    "bytes": output.stat().st_size,
                }

            runner.values = request_capture
            with (
                patch.object(
                    bot_match,
                    "validate_backbuffer",
                    side_effect=validate,
                ),
                patch.object(bot_match.time, "sleep"),
            ):
                artifact = runner.collect_wave_screenshot(9)

            self.assertEqual(artifact["captureAttempts"], 2)
            self.assertEqual(len(artifact["rejectedFrames"]), 1)
            self.assertTrue(
                Path(artifact["rejectedFrames"][0]["path"]).is_file()
            )
            self.assertTrue(Path(artifact["path"]).is_file())
            self.assertIs(runner.wave_screenshots[9], artifact)

    def test_pending_wave_capture_sweep_closes_sampled_wave_gaps(
        self,
    ) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.wave_screenshots = {
            7: {"label": "wave-07"},
            9: {"label": "wave-09"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            runner.screenshot_directory = Path(temporary)
            for wave in (8, 12):
                (
                    runner.screenshot_directory / f"wave-{wave:02d}.bmp"
                ).write_bytes(b"armed frame" * 1_000)
            (
                runner.screenshot_directory
                / "wave-11-rejected-01.bmp"
            ).write_bytes(b"rejected frame" * 1_000)

            captures = []

            def capture(
                label: str,
                *,
                armed: bool = False,
            ) -> dict[str, object]:
                captures.append((label, armed))
                return {"label": label}

            runner.capture = capture
            collected = runner.collect_pending_wave_screenshots()

        self.assertEqual(collected, [8, 12])
        self.assertEqual(
            captures,
            [("wave-08", True), ("wave-12", True)],
        )
        self.assertEqual(set(runner.wave_screenshots), {7, 8, 9, 12})

    def test_death_cause_uses_latest_unconsumed_native_lethal_edge(
        self,
    ) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.last_death_damage_sequence = {}
        runner.player_damage = [
            {
                "sequence": 8,
                "monotonicMs": 80,
                "targetParticipantId": 2,
                "sourceActor": 100,
                "sourceNativeTypeId": 1001,
                "targetHpBefore": 2.0,
                "targetHpAfter": 0.5,
                "damage": 1.5,
            },
            {
                "sequence": 9,
                "monotonicMs": 90,
                "targetParticipantId": 2,
                "sourceActor": 101,
                "sourceNativeTypeId": 1002,
                "targetHpBefore": 0.5,
                "targetHpAfter": -1.0,
                "damage": 1.5,
            },
        ]

        cause = runner.lethal_damage_cause(2)

        self.assertEqual(
            cause,
            {
                "observationSequence": 9,
                "monotonicMs": 90,
                "sourceActor": 101,
                "sourceNativeTypeId": 1002,
                "damage": 1.5,
                "targetHpBefore": 0.5,
                "targetHpAfter": -1.0,
            },
        )
        self.assertIsNone(runner.lethal_damage_cause(2))

    def test_smoke_acceptance_requires_four_fighters_and_bot_hp_edges(
        self,
    ) -> None:
        runner = object.__new__(bot_match.BotMatchRun)
        runner.config = bot_match.BotMatchConfig.load(
            TOOLS_ROOT / "bot_match.example.json"
        )
        runner.fighter_names_by_id = {
            1: "Aster",
            2: "Ember",
            3: "Brook",
            4: "Gale",
        }
        runner.enemy_damage = [
            {"sourceParticipantId": 2, "damage": 1.0},
        ]
        runner.player_damage = []
        runner.death_transitions = []
        runner.respawn_transitions = []
        runner.assert_smoke_damage()

        runner.enemy_damage = [
            {"sourceParticipantId": 1, "damage": 1.0},
        ]
        with self.assertRaisesRegex(
            bot_match.BotMatchFailure,
            "bot-attributed post-native damage",
        ):
            runner.assert_smoke_damage()

    def test_harness_is_real_path_isolated_and_failsafe_rejecting(
        self,
    ) -> None:
        source = (TOOLS_ROOT / "run_bot_match.py").read_text(
            encoding="utf-8"
        )
        launcher = (
            ROOT / "scripts/Launch-LocalSoloSession.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "from verify_remote_latency_wave5 import",
            source,
        )
        self.assertIn("csp.drive_hub_flow(", source)
        self.assertIn("sd.hub.start_testrun", source)
        self.assertIn("sd.hub.trigger_solomon_dig()", source)
        self.assertNotIn("sd.gameplay.start_waves", source)
        self.assertEqual(source.count("sd.bots.update({{"), 1)
        self.assertIn("STUCK_TELEPORT_MARKER", source)
        self.assertIn("stuckTeleports\"] = 0", source)
        self.assertIn("minimumSignedProgress", source)
        self.assertIn("signedProgressBand", source)
        self.assertIn("gateConvoy", source)
        self.assertIn("sd.nav.test_segment", source)
        self.assertIn('choices=(\"gate\", \"smoke\", \"full\")', source)
        self.assertIn('"wave_1_cleared"', source)
        self.assertIn("SDMOD_DISABLE_AUDIO", launcher)
        self.assertIn("$expectedExecutable", launcher)
        self.assertIn("Get-NetUDPEndpoint -LocalPort $LocalPort", launcher)


if __name__ == "__main__":
    unittest.main()
