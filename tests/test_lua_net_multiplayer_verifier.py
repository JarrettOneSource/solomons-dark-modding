#!/usr/bin/env python3
"""Tests for the two-peer Lua raw-message acceptance verifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_lua_net_multiplayer as verifier  # noqa: E402


class LuaNetMultiplayerVerifierTests(unittest.TestCase):
    def test_message_signature_preserves_binary_and_route_evidence(self) -> None:
        self.assertEqual(
            verifier.message_signature(
                sender=11,
                target=22,
                broadcast=False,
                sequence=33,
                payload_bytes=4098,
                first_byte=0,
                last_byte=255,
            ),
            "11,22,0,33,4098,0,255",
        )

    def test_messages_match_requires_exact_sorted_set_and_count(self) -> None:
        expected = ["2,0,1,9,2048,66,255", "1,2,0,8,1026,65,0"]
        self.assertTrue(
            verifier.messages_match(
                {
                    "count": "2",
                    "rows": "1,2,0,8,1026,65,0;2,0,1,9,2048,66,255",
                },
                expected,
            )
        )
        self.assertFalse(
            verifier.messages_match(
                {
                    "count": "3",
                    "rows": "1,2,0,8,1026,65,0;2,0,1,9,2048,66,255",
                },
                expected,
            )
        )

    def test_run_requires_exact_host_and_client_routes(self) -> None:
        clients = [("host", "host-pipe"), ("client", "client-pipe")]
        registrations = [
            {"returncode": 0, "values": {"registered": "true"}},
            {"returncode": 0, "values": {"registered": "true"}},
        ]
        publications = [
            {
                "returncode": 0,
                "values": {
                    "unicast_sequence": "10",
                    "broadcast_sequence": "11",
                },
            },
            {
                "returncode": 0,
                "values": {
                    "unicast_sequence": "20",
                    "broadcast_sequence": "21",
                },
            },
        ]
        with (
            mock.patch.object(
                verifier,
                "run_all",
                side_effect=[registrations, []],
            ),
            mock.patch.object(
                verifier,
                "run_lua_client",
                side_effect=publications,
            ),
            mock.patch.object(
                verifier,
                "_poll_messages",
                side_effect=[
                    {"values": {"count": "3"}},
                    {"values": {"count": "3"}},
                ],
            ) as poll,
        ):
            result = verifier.run(clients, launch=False, timeout=1.0)

        self.assertTrue(result["ok"])
        host_expected = poll.call_args_list[0].args[1]
        client_expected = poll.call_args_list[1].args[1]
        self.assertEqual(len(host_expected), 3)
        self.assertEqual(len(client_expected), 3)
        self.assertIn(
            (
                f"{verifier.CLIENT_ID},{verifier.HOST_ID},0,"
                "20,3074,67,255"
            ),
            host_expected,
        )
        self.assertIn(
            (
                f"{verifier.HOST_ID},{verifier.CLIENT_ID},0,"
                "10,2050,72,0"
            ),
            client_expected,
        )
        client_broadcast = (
            f"{verifier.CLIENT_ID},0,1,21,4098,66,255"
        )
        self.assertIn(client_broadcast, host_expected)
        self.assertIn(client_broadcast, client_expected)


if __name__ == "__main__":
    unittest.main()
