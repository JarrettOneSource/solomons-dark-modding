#!/usr/bin/env python3
"""Behavior tests for the organic spectator follow-up verifier."""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_multiplayer_organic_spectator_followup as verifier  # noqa: E402


class OrganicSpectatorFollowupVerifierTests(unittest.TestCase):
    def test_spectated_target_must_stay_attached_for_full_presentation(
        self,
    ) -> None:
        lifecycle = [
            {
                "elapsed_seconds": 0.1,
                "owner": {"phase": "DeathPresentation"},
                "observer": {"presentation_active": "true"},
                "spectator_hold": {
                    "target_participant_id": "23",
                    "target_name": "Ether Player",
                    "expected_target_presentation_active": "true",
                },
            },
            {
                "elapsed_seconds": 4.9,
                "owner": {"phase": "DeathPresentation"},
                "observer": {"presentation_active": "true"},
                "spectator_hold": {
                    "target_participant_id": "23",
                    "target_name": "Ether Player",
                    "expected_target_presentation_active": "true",
                },
            },
            {
                "elapsed_seconds": 5.2,
                "owner": {"phase": "Spectating"},
                "observer": {"presentation_active": "false"},
                "spectator_hold": {
                    "target_participant_id": "11",
                    "target_name": "Host Player",
                    "expected_target_presentation_active": "false",
                },
            },
        ]

        evidence = verifier._assert_spectated_target_hold(
            lifecycle,
            expected_participant_id=23,
        )

        self.assertEqual(evidence["sample_count"], 2)
        self.assertAlmostEqual(evidence["span_seconds"], 4.8)
        self.assertEqual(evidence["target_names"], ["Ether Player"])

    def test_spectated_target_migration_during_grace_is_rejected(
        self,
    ) -> None:
        lifecycle = [
            {
                "elapsed_seconds": 0.1,
                "owner": {"phase": "DeathPresentation"},
                "observer": {"presentation_active": "true"},
                "spectator_hold": {
                    "target_participant_id": "23",
                    "target_name": "Ether Player",
                    "expected_target_presentation_active": "true",
                },
            },
            {
                "elapsed_seconds": 2.0,
                "owner": {"phase": "DeathPresentation"},
                "observer": {"presentation_active": "true"},
                "spectator_hold": {
                    "target_participant_id": "11",
                    "target_name": "Host Player",
                    "expected_target_presentation_active": "true",
                },
            },
        ]

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "migrated during the death presentation",
        ):
            verifier._assert_spectated_target_hold(
                lifecycle,
                expected_participant_id=23,
            )

    def test_boundary_samples_use_atomic_spectator_view(self) -> None:
        lifecycle = [
            {
                "elapsed_seconds": 0.1,
                "owner": {"phase": "DeathPresentation"},
                "observer": {"presentation_active": "true"},
                "spectator_hold": {
                    "target_participant_id": "23",
                    "target_name": "Ether Player",
                    "expected_target_presentation_active": "true",
                },
            },
            {
                "elapsed_seconds": 4.9,
                "owner": {"phase": "DeathPresentation"},
                "observer": {"presentation_active": "true"},
                "spectator_hold": {
                    "target_participant_id": "23",
                    "target_name": "Ether Player",
                    "expected_target_presentation_active": "true",
                },
            },
            {
                # The old remote probe ran before the presentation edge while
                # the atomic spectator probe ran after it. This is a sampling
                # boundary, not a target migration during presentation.
                "elapsed_seconds": 5.2,
                "owner": {"phase": "Spectating"},
                "observer": {"presentation_active": "true"},
                "spectator_hold": {
                    "target_participant_id": "11",
                    "target_name": "Host Player",
                    "expected_target_presentation_active": "false",
                },
            },
        ]

        evidence = verifier._assert_spectated_target_hold(
            lifecycle,
            expected_participant_id=23,
        )

        self.assertEqual(evidence["sample_count"], 2)
        self.assertAlmostEqual(evidence["span_seconds"], 4.8)

    def test_lifecycle_compaction_keeps_atomic_target_state(self) -> None:
        compact = verifier._small_state(
            {
                "target_participant_id": "23",
                "expected_target_participant_id": "23",
                "expected_target_presentation_active": "true",
                "expected_target_death_presentation_tick": "159",
                "unrelated": "discarded",
            }
        )

        self.assertEqual(
            compact,
            {
                "target_participant_id": "23",
                "expected_target_participant_id": "23",
                "expected_target_presentation_active": "true",
                "expected_target_death_presentation_tick": "159",
            },
        )

    def test_ether_minion_must_materialize_on_every_peer(self) -> None:
        counts = {
            "host": {"native_type_id": "2034", "count": "1"},
            "client": {"native_type_id": "2034", "count": "1"},
            "third": {"native_type_id": "2034", "count": "2"},
        }

        self.assertEqual(
            verifier._assert_ether_minion_counts(counts),
            {
                "native_type_id": 0x07F2,
                "minimum_peer_count": 1,
                "all_peers_materialized": True,
            },
        )
        counts["client"]["count"] = "0"
        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "did not materialize on every peer",
        ):
            verifier._assert_ether_minion_counts(counts)

    def test_terminal_capture_retries_only_blank_render_phase(self) -> None:
        attempts: list[int] = []

        def capture(_pipe: str, _path: Path) -> dict[str, object]:
            attempts.append(len(attempts) + 1)
            if len(attempts) == 1:
                raise verifier.VerifyFailure(
                    "D3D9 backbuffer capture is blank or "
                    "low-information"
                )
            return {"path": "terminal.png"}

        evidence = verifier._capture_rendered_backbuffer(
            "pipe",
            Path("terminal.png"),
            capture=capture,
            attempts=2,
            retry_delay=0.0,
        )

        self.assertEqual(attempts, [1, 2])
        self.assertEqual(evidence["capture_attempt"], 2)
        self.assertEqual(evidence["blank_frame_retries"], 1)

        def fail_capture(_pipe: str, _path: Path) -> dict[str, object]:
            raise verifier.VerifyFailure("capture command failed")

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "capture command failed",
        ):
            verifier._capture_rendered_backbuffer(
                "pipe",
                Path("terminal.png"),
                capture=fail_capture,
                attempts=2,
                retry_delay=0.0,
            )

    def test_terminal_corpse_frames_capture_both_peers_concurrently(
        self,
    ) -> None:
        barrier = threading.Barrier(2)

        def capture(pipe: str, path: Path) -> dict[str, object]:
            barrier.wait(timeout=1.0)
            return {"pipe": pipe, "path": str(path)}

        evidence = verifier._capture_terminal_corpse_frames(
            spectator_pipe="spectator-pipe",
            owner_pipe="owner-pipe",
            artifact_directory=Path("evidence"),
            capture=capture,
        )

        self.assertEqual(
            "spectator-pipe",
            evidence["spectator"]["pipe"],
        )
        self.assertEqual("owner-pipe", evidence["owner"]["pipe"])


if __name__ == "__main__":
    unittest.main()
