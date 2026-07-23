#!/usr/bin/env python3
"""Tests for the two-peer Lua time acceptance verifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_lua_time_multiplayer as verifier  # noqa: E402


class LuaTimeMultiplayerVerifierTests(unittest.TestCase):
    @staticmethod
    def _state(
        *,
        scale: str,
        revision: int,
        step_sequence: int,
        requested_scale: str,
        returned_step_sequence: int | None = None,
    ) -> dict[str, object]:
        values = {
            "scale": scale,
            "revision": str(revision),
            "step_sequence": str(step_sequence),
            "replicated": "false",
            "authority_participant_id": str(verifier.HOST_ID),
            "run_nonce": "99",
            "requested_scale": requested_scale,
        }
        if returned_step_sequence is not None:
            values["returned_step_sequence"] = str(returned_step_sequence)
        return {"returncode": 0, "values": values}

    def test_state_matches_authority_and_replicated_views(self) -> None:
        common = {
            "scale": "0.5",
            "revision": "7",
            "step_sequence": "3",
            "authority_participant_id": str(verifier.HOST_ID),
            "run_nonce": "99",
        }
        self.assertTrue(
            verifier.state_matches(
                {
                    **common,
                    "replicated": "false",
                    "requested_scale": "0.5",
                },
                scale=0.5,
                revision=7,
                step_sequence=3,
                replicated=False,
                run_nonce=99,
                requested_scale=0.5,
            )
        )
        self.assertTrue(
            verifier.state_matches(
                {
                    **common,
                    "replicated": "true",
                    "requested_scale": "nil",
                },
                scale=0.5,
                revision=7,
                step_sequence=3,
                replicated=True,
                run_nonce=99,
                requested_scale=None,
            )
        )

    def test_state_match_rejects_wrong_authority_or_sequence(self) -> None:
        values = {
            "scale": "0",
            "revision": "8",
            "step_sequence": "6",
            "replicated": "true",
            "authority_participant_id": "123",
            "run_nonce": "99",
            "requested_scale": "nil",
        }
        self.assertFalse(
            verifier.state_matches(
                values,
                scale=0.0,
                revision=8,
                step_sequence=6,
                replicated=True,
                run_nonce=99,
                requested_scale=None,
            )
        )

    def test_run_checks_exact_step_sequence_only_before_resume(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        rejection = {
            "returncode": 0,
            "values": {
                "set_rejected": "true",
                "step_rejected": "true",
                "set_authority_error": "true",
                "step_authority_error": "true",
                "unchanged": "true",
            },
        }
        release = {"returncode": 0, "values": {"released": "true"}}
        with (
            mock.patch.object(
                verifier,
                "_run_probe",
                side_effect=[
                    self._state(
                        scale="1",
                        revision=1,
                        step_sequence=0,
                        requested_scale="nil",
                    ),
                    rejection,
                    self._state(
                        scale="0.5",
                        revision=2,
                        step_sequence=0,
                        requested_scale="0.5",
                    ),
                    self._state(
                        scale="0",
                        revision=3,
                        step_sequence=0,
                        requested_scale="0",
                    ),
                    self._state(
                        scale="0",
                        revision=4,
                        step_sequence=3,
                        requested_scale="0",
                        returned_step_sequence=3,
                    ),
                    self._state(
                        scale="1",
                        revision=5,
                        step_sequence=3,
                        requested_scale="nil",
                    ),
                    release,
                ],
            ),
            mock.patch.object(
                verifier,
                "_poll_state",
                side_effect=[{"returncode": 0}] * 5,
            ) as poll,
            mock.patch.object(verifier, "stop_game_processes") as stop,
        ):
            result = verifier.run(clients, launch=False, timeout=1.0)

        self.assertTrue(result["ok"])
        self.assertEqual(
            [call.kwargs["step_sequence"] for call in poll.call_args_list],
            [0, 0, 0, 3, None],
        )
        self.assertIs(result["release"], release)
        stop.assert_called_once_with([])

    def test_failed_release_fails_the_result(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        rejection = {
            "returncode": 0,
            "values": {
                "set_rejected": "true",
                "step_rejected": "true",
                "set_authority_error": "true",
                "step_authority_error": "true",
                "unchanged": "true",
            },
        }
        successful_states = [
            self._state(
                scale="1",
                revision=1,
                step_sequence=0,
                requested_scale="nil",
            ),
            rejection,
            self._state(
                scale="0.5",
                revision=2,
                step_sequence=0,
                requested_scale="0.5",
            ),
            self._state(
                scale="0",
                revision=3,
                step_sequence=0,
                requested_scale="0",
            ),
            self._state(
                scale="0",
                revision=4,
                step_sequence=3,
                requested_scale="0",
                returned_step_sequence=3,
            ),
            self._state(
                scale="1",
                revision=5,
                step_sequence=3,
                requested_scale="nil",
            ),
            {"returncode": 0, "values": {"released": "false"}},
        ]
        with (
            mock.patch.object(
                verifier,
                "_run_probe",
                side_effect=successful_states,
            ),
            mock.patch.object(
                verifier,
                "_poll_state",
                side_effect=[{"returncode": 0}] * 5,
            ),
            mock.patch.object(verifier, "stop_game_processes"),
        ):
            result = verifier.run(clients, launch=False, timeout=1.0)

        self.assertFalse(result["ok"])
        self.assertIn("normal speed", result["release_error"])


if __name__ == "__main__":
    unittest.main()
