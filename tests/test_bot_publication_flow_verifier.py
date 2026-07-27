#!/usr/bin/env python3
"""Tests for the isolated Lua Bots publication verifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_bot_publication_flow as verifier  # noqa: E402


def publication_view(
    roster: list[dict[str, str]],
    *,
    authority: bool,
    participant_ids: list[int],
    startup_roster: list[dict[str, str]],
    settings_change_count: int,
) -> dict[str, str]:
    values = {
        "scene": "hub",
        "authority": str(authority).lower(),
        "setting.kite_radius": "340",
        "setting.offense_enabled": "true",
        "setting.roster.count": str(len(roster)),
        "brain.roster_size": str(len(roster)),
        "brain.startup_apply_count": "1",
        "brain.startup_roster.count": str(len(startup_roster)),
        "brain.settings_change_count": str(settings_change_count),
        "actual.count": str(len(roster)),
        "actual.participant_ids": ",".join(
            str(value) for value in participant_ids
        ),
    }
    for prefix, rows in (
        ("setting.roster", roster),
        ("brain.startup_roster", startup_roster),
    ):
        for index, row in enumerate(rows, start=1):
            for key, value in row.items():
                values[f"{prefix}.{index}.{key}"] = value
    for index, row in enumerate(roster, start=1):
        for key, value in row.items():
            values[f"brain.bot.{index}.{key}"] = value
    return values


class BotPublicationFlowVerifierTests(unittest.TestCase):
    def test_initial_join_requires_host_values_before_first_apply(self) -> None:
        participant_ids = [
            0x2000000000006603,
            0x2000000000006604,
        ]
        views = {
            "host": publication_view(
                verifier.INITIAL_ROSTER,
                authority=True,
                participant_ids=participant_ids,
                startup_roster=verifier.INITIAL_ROSTER,
                settings_change_count=0,
            ),
            "client": publication_view(
                verifier.INITIAL_ROSTER,
                authority=False,
                participant_ids=participant_ids,
                startup_roster=verifier.INITIAL_ROSTER,
                settings_change_count=0,
            ),
        }

        self.assertTrue(verifier.initial_converged(views))
        views["client"]["brain.startup_roster.1.name"] = "ClientLocalDefault"
        self.assertFalse(verifier.initial_converged(views))

    def test_participant_ids_preserve_full_uint64_values(self) -> None:
        first = 0x2000000000006603
        second = 0x2000000000006604
        values = {"actual.participant_ids": f"{first},{second}"}
        self.assertEqual(verifier.participant_ids(values), {first, second})

    def test_mid_session_change_requires_exactly_one_callback(self) -> None:
        participant_ids = [
            0x2000000000006603,
            0x2000000000006604,
        ]
        views = {
            role: publication_view(
                verifier.CHANGED_ROSTER,
                authority=role == "host",
                participant_ids=participant_ids,
                startup_roster=verifier.INITIAL_ROSTER,
                settings_change_count=1 if role == "client" else 0,
            )
            for role in ("host", "client")
        }
        client = views["client"]
        client["brain.last_settings_change_key"] = "roster"
        client["brain.last_roster_new_value.count"] = "2"
        for index, row in enumerate(verifier.CHANGED_ROSTER, start=1):
            for key, value in row.items():
                client[f"brain.last_roster_new_value.{index}.{key}"] = value

        self.assertTrue(verifier.changed_converged(views))
        client["brain.settings_change_count"] = "2"
        self.assertFalse(verifier.changed_converged(views))

    def test_entry_log_order_requires_authority_before_start(self) -> None:
        valid = "\n".join(
            [
                "entry script waiting for the authoritative host-settings checkpoint.",
                "authoritative host settings ready before entry script; monotonic_ms=120",
                "started deferred entry script after host settings; monotonic_ms=121",
            ]
        )
        self.assertTrue(verifier.inspect_client_entry_order(valid)["ordered"])

        invalid = valid.replace("monotonic_ms=121", "monotonic_ms=119")
        with self.assertRaises(verifier.VerificationFailure):
            verifier.inspect_client_entry_order(invalid)


if __name__ == "__main__":
    unittest.main()
