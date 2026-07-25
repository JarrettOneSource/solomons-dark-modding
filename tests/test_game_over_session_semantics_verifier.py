#!/usr/bin/env python3
"""Behavior tests for the solo/multiplayer Game Over live verifier."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_game_over_session_semantics as verifier  # noqa: E402


class GameOverSessionSemanticsVerifierTests(unittest.TestCase):
    def test_generated_instance_prefix_stays_below_native_path_limit(self) -> None:
        prefix = verifier._default_instance_prefix()
        self.assertLessEqual(len(prefix), 18)
        self.assertRegex(prefix, r"^go-[0-9a-f]+-[0-9a-f]{4}$")

    def test_launcher_instance_groups_are_short_stable_and_distinct(self) -> None:
        evidence_prefix = "descriptive-evidence-name-that-can-be-long"
        groups = {
            role: verifier._launcher_instance_prefix(
                evidence_prefix,
                role,
            )
            for role in ("s", "m", "t")
        }

        self.assertEqual(len(set(groups.values())), 3)
        for role, value in groups.items():
            self.assertEqual(len(value), 10)
            self.assertRegex(value, rf"^g[0-9a-f]{{8}}{role}$")
            self.assertEqual(
                value,
                verifier._launcher_instance_prefix(
                    evidence_prefix,
                    role,
                ),
            )
        self.assertNotEqual(
            groups["m"],
            verifier._launcher_instance_prefix(
                evidence_prefix + "-other",
                "m",
            ),
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            verifier._launcher_instance_prefix(
                evidence_prefix,
                "x",
            )

    def test_explicit_ports_keep_both_instance_groups_isolated(self) -> None:
        with mock.patch.object(
            verifier,
            "select_available_windows_udp_ports",
        ) as reserve:
            ports = verifier._resolve_udp_ports(
                [
                    23111,
                    23112,
                    23113,
                    23114,
                    23115,
                    23116,
                    23117,
                ]
            )

        self.assertEqual(
            ports,
            [
                23111,
                23112,
                23113,
                23114,
                23115,
                23116,
                23117,
            ],
        )
        reserve.assert_not_called()

    def test_partial_and_duplicate_port_groups_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "all seven ports"):
            verifier._resolve_udp_ports(
                [
                    23111,
                    None,
                    23113,
                    23114,
                    23115,
                    23116,
                    23117,
                ]
            )
        with self.assertRaisesRegex(ValueError, "must be distinct"):
            verifier._resolve_udp_ports(
                [
                    23111,
                    23112,
                    23113,
                    23113,
                    23115,
                    23116,
                    23117,
                ]
            )

    def test_windows_process_paths_are_case_and_separator_insensitive(self) -> None:
        self.assertTrue(
            verifier._windows_path_equal(
                r"C:\Runtime\Instances\TEST\stage\SolomonDark.exe",
                r"c:/runtime/instances/test/stage/solomondark.exe",
            )
        )
        self.assertFalse(
            verifier._windows_path_equal(
                r"C:\Runtime\Instances\ours\stage\SolomonDark.exe",
                r"C:\Runtime\Instances\theirs\stage\SolomonDark.exe",
            )
        )

    def test_windows_log_path_conversion_is_bounded(self) -> None:
        completed = mock.Mock(
            returncode=0,
            stdout="/mnt/c/runtime/instances/ours/loader.log\n",
        )
        with mock.patch.object(
            verifier.os,
            "name",
            "posix",
        ), mock.patch.object(
            verifier.subprocess,
            "run",
            return_value=completed,
        ) as run:
            converted = verifier._path_for_local_python(
                r"C:\runtime\instances\ours\loader.log"
            )

        self.assertEqual(
            converted,
            Path("/mnt/c/runtime/instances/ours/loader.log"),
        )
        self.assertEqual(
            run.call_args.args[0],
            [
                "wslpath",
                "-u",
                r"C:\runtime\instances\ours\loader.log",
            ],
        )
        self.assertEqual(run.call_args.kwargs["timeout"], 5.0)

    def test_exact_process_ownership_rejects_another_instance(self) -> None:
        expected = {
            1234: r"C:\runtime\instances\ours\stage\SolomonDark.exe"
        }
        with mock.patch.object(
            verifier,
            "_query_process_executable",
            return_value=r"C:\runtime\instances\theirs\stage\SolomonDark.exe",
        ):
            with self.assertRaisesRegex(
                verifier.VerifyFailure,
                "ownership mismatch",
            ):
                verifier.validate_owned_processes(expected)

    def test_solo_terminal_requires_dead_stock_flow_without_spectator(self) -> None:
        values = {
            "scene": "testrun",
            "participant_count": "1",
            "remote_peer_count": "0",
            "spectator_active": "false",
            "spectator_phase": "Inactive",
            "local_life_current": "-24",
        }
        self.assertTrue(verifier.solo_terminal_state_matches(values))
        values["spectator_active"] = "true"
        self.assertFalse(verifier.solo_terminal_state_matches(values))

    def test_terminal_game_over_requires_one_consumed_authority_command(self) -> None:
        values = {
            "game_over_command_epoch": "7",
            "game_over_accepted_epoch": "7",
            "game_over_run_nonce": "91",
            "game_over_authority_participant_id": "2305843009213698049",
            "game_over_pending_dispatch": "false",
            "game_over_dispatch_count": "1",
            "spectator_active": "false",
            "spectator_phase": "Inactive",
        }
        self.assertTrue(verifier.terminal_game_over_state_matches(values))
        values["game_over_dispatch_count"] = "2"
        self.assertFalse(verifier.terminal_game_over_state_matches(values))

    def test_boneyard_game_over_requires_stock_object_at_full_input_alpha(
        self,
    ) -> None:
        values = {
            "game_over_found": "true",
            "boneyard_mode": "1",
            "game_over_closed": "0",
            "game_over_tick_count": "616",
            "game_over_title_alpha": "1.0",
            "game_over_click_alpha": "1.0",
            "game_over_close_alpha": "0.0",
        }
        self.assertTrue(
            verifier.native_boneyard_game_over_state_matches(values)
        )
        values["game_over_tick_count"] = "599"
        self.assertFalse(
            verifier.native_boneyard_game_over_state_matches(values)
        )
        values["game_over_tick_count"] = "616"
        values["boneyard_mode"] = "0"
        self.assertFalse(
            verifier.native_boneyard_game_over_state_matches(values)
        )

    def test_boneyard_game_over_capture_accepts_fade_only_frame_quality(
        self,
    ) -> None:
        native_state = {
            "game_over_found": "true",
            "boneyard_mode": "1",
            "game_over_closed": "0",
            "game_over_tick_count": "616",
            "game_over_title_alpha": "1.0",
            "game_over_click_alpha": "1.0",
            "game_over_close_alpha": "0.0",
        }
        classification = {
            "matched": False,
            "dark_fraction": 0.93,
            "gold_fractions": {
                "game": 0.0,
                "over": 0.0,
                "continue": 0.0,
            },
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            verifier,
            "query_native_game_over_state",
            return_value=native_state,
        ), mock.patch.object(
            verifier,
            "capture_game_backbuffer",
            return_value={"capture_method": "d3d9_backbuffer"},
        ) as capture, mock.patch.object(
            verifier,
            "classify_native_game_over_image",
            return_value=classification,
        ):
            output_path = Path(directory) / "game-over.png"
            result = verifier.capture_native_game_over(
                "test-pipe",
                output_path,
                allow_boneyard_mode=True,
            )

        capture.assert_called_once_with(
            "test-pipe",
            output_path,
            minimum_unique_colors=20,
            maximum_dominant_fraction=0.9999,
        )
        self.assertEqual(result["presentation"], "boneyard-fade")
        self.assertEqual(result["native_state"], native_state)

    def test_healthy_loading_release_requires_exact_mutual_actor_set(self) -> None:
        values = {
            "session_state": "in-boneyard",
            "run_nonce": "91",
            "loading_active": "true",
            "loading_released": "true",
            "loading_timed_out": "false",
            "loading_local_mutual_visibility": "true",
            "loading_run_nonce": "91",
            "loading_local_ack_nonce": "91",
            "loading_release_nonce": "91",
            "loading_visible_participant_count": "3",
            "loading_expected_participant_count": "3",
            "loading_ready_participant_count": "3",
            "loading_visible_participant_set_hash": "-411",
            "loading_expected_participant_set_hash": "-411",
            "loading_release_reason": "all-participants-ready",
        }
        self.assertTrue(
            verifier.healthy_loading_barrier_state_matches(
                values,
                3,
            )
        )
        values["loading_visible_participant_set_hash"] = "-412"
        self.assertFalse(
            verifier.healthy_loading_barrier_state_matches(
                values,
                3,
            )
        )

    def test_timeout_loading_release_proceeds_with_missing_peer(self) -> None:
        values = {
            "session_state": "in-boneyard",
            "run_nonce": "92",
            "loading_active": "true",
            "loading_released": "true",
            "loading_timed_out": "true",
            "loading_run_nonce": "92",
            "loading_release_nonce": "92",
            "loading_visible_participant_count": "1",
            "loading_expected_participant_count": "2",
            "loading_ready_participant_count": "0",
            "loading_expected_participant_set_hash": "481",
            "loading_release_reason": "timeout",
        }
        self.assertTrue(
            verifier.loading_barrier_released_state_matches(
                values,
                2,
                expected_reason="timeout",
            )
        )

    def test_loading_classifier_accepts_centered_text_on_black(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loading.png"
            image = Image.new("RGB", (800, 450), (0, 0, 0))
            for x in range(300, 500):
                for y in range(215, 235):
                    if (x + y) % 4 == 0:
                        image.putpixel((x, y), (220, 220, 220))
            image.save(path)

            matched = verifier.classify_loading_boneyard_image(path)
            self.assertTrue(matched["matched"])

            image.paste((0, 0, 0), (280, 180, 520, 270))
            image.save(path)
            blank = verifier.classify_loading_boneyard_image(path)
            self.assertFalse(blank["matched"])

    def test_native_game_over_classifier_requires_all_three_gold_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "game-over.png"
            image = Image.new("RGB", (800, 450), (0, 0, 0))
            gold = (220, 180, 80)
            for bounds in (
                (0.39, 0.21, 0.62, 0.39),
                (0.39, 0.54, 0.62, 0.72),
                (0.38, 0.90, 0.63, 0.98),
            ):
                left, top, right, bottom = bounds
                for x in range(
                    int(image.width * left),
                    int(image.width * right),
                ):
                    for y in range(
                        int(image.height * top),
                        int(image.height * bottom),
                    ):
                        if (x + y) % 5 == 0:
                            image.putpixel((x, y), gold)
            image.save(path)

            matched = verifier.classify_native_game_over_image(path)
            self.assertTrue(matched["matched"])

            image.paste(
                (0, 0, 0),
                (
                    int(image.width * 0.38),
                    int(image.height * 0.90),
                    int(image.width * 0.63),
                    int(image.height * 0.98),
                ),
            )
            image.save(path)
            missing_continue = verifier.classify_native_game_over_image(path)
            self.assertFalse(missing_continue["matched"])

    def test_stock_post_game_over_click_targets_one_exact_process(self) -> None:
        completed = mock.Mock(returncode=0, stdout="clicked owned game\n")
        with mock.patch.object(
            verifier.subprocess,
            "run",
            return_value=completed,
        ) as run:
            result = verifier._click_owned_window(4321, 0.5, 0.95)

        self.assertEqual(result, "clicked owned game")
        command = run.call_args.args[0]
        self.assertEqual(
            command[:3],
            ["powershell.exe", "-NoProfile", "-Command"],
        )
        self.assertIn("--pid 4321", command[3])
        self.assertNotIn("--activate", command[3])
        self.assertIn("--window-only", command[3])
        self.assertNotIn("--global-only", command[3])


if __name__ == "__main__":
    unittest.main()
