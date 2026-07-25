#!/usr/bin/env python3
"""Behavior tests for the real Steam lobby-state transition verifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_lobby_session_state_transitions as verifier  # noqa: E402


class LobbySessionStateTransitionsVerifierTests(unittest.TestCase):
    def test_transition_capture_deduplicates_consecutive_states(self) -> None:
        transitions: list[dict[str, object]] = []
        status = {
            "sessionState": "not-in-game",
            "members": [{"steamId": "1"}],
        }

        verifier._append_transition(transitions, status)
        verifier._append_transition(transitions, status)
        verifier._append_transition(
            transitions,
            {
                "sessionState": "in-hub",
                "members": [{"steamId": "1"}],
            },
        )

        self.assertEqual(
            [transition["sessionState"] for transition in transitions],
            ["not-in-game", "in-hub"],
        )

    def test_invalid_session_state_is_rejected_immediately(self) -> None:
        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "invalid sessionState",
        ):
            verifier._append_transition(
                [],
                {
                    "sessionState": "results",
                    "members": [{"steamId": "1"}],
                },
            )

    def test_required_transition_order_and_members_are_enforced(self) -> None:
        transitions = [
            {
                "sessionState": state,
                "status": {
                    "sessionState": state,
                    "members": [{"steamId": "1"}],
                },
            }
            for state in verifier.EXPECTED_STATES
        ]

        verifier._validate_transition_sequence(transitions)

        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "required ordered transition",
        ):
            verifier._validate_transition_sequence(
                [transitions[0], transitions[2]]
            )

        transitions[1]["status"]["members"] = []
        with self.assertRaisesRegex(
            verifier.VerifyFailure,
            "omitted lobby members",
        ):
            verifier._validate_transition_sequence(transitions)

    def test_empty_exact_process_query_is_an_empty_owned_set(self) -> None:
        completed = mock.Mock(returncode=0, stdout="null", stderr="")
        with mock.patch.object(
            verifier.subprocess,
            "run",
            return_value=completed,
        ):
            self.assertEqual(
                verifier._query_exact_process_ids(
                    r"C:\runtime\instances\ours\stage\SolomonDark.exe"
                ),
                [],
            )


if __name__ == "__main__":
    unittest.main()
