from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_multiplayer_local_hit_feedback as verifier  # noqa: E402


CAPTURE = (
    "[hit-feedback] event=authority_capture "
    f"target_participant_id={verifier.CLIENT_ID} run_nonce=77 "
    "event_sequence=4 health_before=29 health_after=26 "
    "health_maximum=50 hit_primary_alpha=1 hit_intensity=1 "
    "hit_secondary_alpha=1 hit_color_red=0.65 "
    "hit_color_green=0 hit_color_blue=0 hit_color_alpha=1 "
    "ouch_eligible=1"
)
REPLAY = (
    "[hit-feedback] event=replay "
    f"target_participant_id={verifier.CLIENT_ID} run_nonce=77 "
    "event_sequence=4 health_before=29 health_after=26 "
    "health_maximum=50 actor_live=1 actor_reaction_written=1 "
    "hit_primary_alpha=1 hit_intensity=1 hit_secondary_alpha=1 "
    "hit_color_red=0.65 hit_color_green=0 hit_color_blue=0 "
    "hit_color_alpha=1 ouch_eligible=1 "
    "ouch_requested=1 ouch_index=2 ouch_gain=0.7 "
    "red_written=1 red_value=0.245"
)
AUDIO = (
    '[native-audio] event=play sequence=9 '
    'asset="sounds/Wizard_Ouch/SAY_OUCH3.wav" owner=player.hit '
    f"participant_id={verifier.CLIENT_ID} remote=0"
)


class MultiplayerLocalHitFeedbackVerifierTests(unittest.TestCase):
    def test_exactly_once_matches_authority_event_to_owner_replay(self) -> None:
        result = verifier.assert_exactly_once(
            CAPTURE,
            f"{REPLAY}\n{AUDIO}",
        )
        self.assertEqual(result["eventCount"], 1)
        self.assertEqual(result["ouchRequestCount"], 1)
        self.assertEqual(result["redReplayCount"], 1)
        self.assertEqual(result["actorReactionReplayCount"], 1)

    def test_duplicate_replay_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "not exactly once",
        ):
            verifier.assert_exactly_once(
                CAPTURE,
                f"{REPLAY}\n{REPLAY}\n{AUDIO}",
            )

    def test_missing_authority_event_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "never produced",
        ):
            verifier.assert_exactly_once("", f"{REPLAY}\n{AUDIO}")

    def test_actor_reaction_must_match_authority(self) -> None:
        mismatched = REPLAY.replace(
            "hit_intensity=1 ",
            "hit_intensity=0.5 ",
        )
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "differs from authority",
        ):
            verifier.assert_exactly_once(
                CAPTURE,
                f"{mismatched}\n{AUDIO}",
            )

    def test_heal_and_snapshot_phases_require_complete_silence(self) -> None:
        self.assertEqual(
            verifier.assert_no_feedback_on_heal("", "")[
                "ownerReplayCount"
            ],
            0,
        )
        self.assertEqual(
            verifier.assert_no_feedback_on_snapshot_reapply("", "")[
                "authorityCaptureCount"
            ],
            0,
        )
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "healing emitted hit feedback",
        ):
            verifier.assert_no_feedback_on_heal(CAPTURE, "")

    def test_other_participant_cannot_replay_on_client_b(self) -> None:
        self.assertEqual(
            verifier.assert_no_feedback_for_other_participant("")[
                "ownerReplayCount"
            ],
            0,
        )
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "leaked feedback",
        ):
            verifier.assert_no_feedback_for_other_participant(REPLAY)

    def test_host_native_gate_rejects_framework_contribution(self) -> None:
        result = verifier.assert_host_native_feedback_unchanged(
            AUDIO,
            red_value=0.25,
            actor_reaction_value=1.0,
            hp_before=29.0,
            hp_after=26.0,
        )
        self.assertEqual(result["frameworkRowCount"], 0)
        with self.assertRaisesRegex(
            verifier.VerificationFailure,
            "framework replay path",
        ):
            verifier.assert_host_native_feedback_unchanged(
                f"{REPLAY}\n{AUDIO}",
                red_value=0.25,
                actor_reaction_value=1.0,
                hp_before=29.0,
                hp_after=26.0,
            )


if __name__ == "__main__":
    unittest.main()
