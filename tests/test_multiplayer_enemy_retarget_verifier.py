from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_multiplayer_enemy_retarget as verifier  # noqa: E402


def _record(
    *,
    participant_id: int = 0,
    native_type_id: int = 0,
    ineligible: int = 0,
) -> dict[str, int]:
    return {
        "target_actor_address":
            0x12345678 if participant_id or native_type_id else 0,
        "target_participant_id": participant_id,
        "target_native_type_id": native_type_id,
        "target_ineligible_state": ineligible,
    }


class EnemyRetargetVerifierTests(unittest.TestCase):
    def test_participant_reacquisition_requires_stable_host_and_client_match(
        self,
    ) -> None:
        samples = []
        for index in range(12):
            samples.append(
                {
                    "elapsed_seconds": index * 0.05,
                    "host": (
                        _record(participant_id=verifier.CLIENT_ID)
                        if index >= 2 else _record()
                    ),
                    "client": (
                        _record(participant_id=verifier.CLIENT_ID)
                        if index >= 4 else _record()
                    ),
                }
            )
        analysis = verifier.analyze_retarget_samples(
            samples,
            expected_participant_id=verifier.CLIENT_ID,
            expected_native_type_id=0,
            dead_participant_id=verifier.HOST_ID,
        )
        self.assertTrue(analysis["passed"])
        self.assertAlmostEqual(
            analysis["host_reacquire_latency_ms"],
            100.0,
        )
        self.assertAlmostEqual(
            analysis["client_reacquire_latency_ms"],
            200.0,
        )
        self.assertGreaterEqual(
            analysis["stable_match_sample_count"],
            verifier.MINIMUM_STABLE_MATCH_SAMPLES,
        )

    def test_idle_enemy_fails_even_when_the_old_gate_has_no_mismatch(
        self,
    ) -> None:
        samples = [
            {
                "elapsed_seconds": index * 0.05,
                "host": _record(),
                "client": _record(),
            }
            for index in range(12)
        ]
        analysis = verifier.analyze_retarget_samples(
            samples,
            expected_participant_id=verifier.CLIENT_ID,
            expected_native_type_id=0,
            dead_participant_id=verifier.HOST_ID,
        )
        self.assertFalse(analysis["passed"])
        self.assertIsNone(analysis["host_reacquire_latency_ms"])
        self.assertIsNone(analysis["client_reacquire_latency_ms"])

    def test_dead_or_ineligible_player_never_satisfies_target_match(
        self,
    ) -> None:
        dead_target = _record(
            participant_id=verifier.HOST_ID,
            ineligible=1,
        )
        samples = [
            {
                "elapsed_seconds": index * 0.05,
                "host": dead_target,
                "client": dead_target,
            }
            for index in range(12)
        ]
        analysis = verifier.analyze_retarget_samples(
            samples,
            expected_participant_id=verifier.HOST_ID,
            expected_native_type_id=0,
            dead_participant_id=verifier.HOST_ID,
        )
        self.assertFalse(analysis["passed"])
        self.assertEqual(analysis["dead_target_sample_count"], 24)

    def test_native_minion_identity_must_converge_on_both_peers(
        self,
    ) -> None:
        samples = [
            {
                "elapsed_seconds": index * 0.05,
                "host": _record(
                    native_type_id=verifier.ETHER_MINION_NATIVE_TYPE_ID,
                ),
                "client": _record(
                    native_type_id=verifier.ETHER_MINION_NATIVE_TYPE_ID,
                ),
            }
            for index in range(8)
        ]
        analysis = verifier.analyze_retarget_samples(
            samples,
            expected_participant_id=0,
            expected_native_type_id=
                verifier.ETHER_MINION_NATIVE_TYPE_ID,
            dead_participant_id=0,
        )
        self.assertTrue(analysis["passed"])
        self.assertEqual(
            analysis["final_host"]["target_native_type_id"],
            verifier.ETHER_MINION_NATIVE_TYPE_ID,
        )


if __name__ == "__main__":
    unittest.main()
