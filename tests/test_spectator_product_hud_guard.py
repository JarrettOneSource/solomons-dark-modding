#!/usr/bin/env python3
"""Contracts for the player-facing spectator HUD state log guard."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from spectator_product_hud_guard import (  # noqa: E402
    PRODUCT_HUD_CONTEXT_EXPECTATIONS,
    assert_latest_spectator_product_hud_state,
    assert_spectator_product_hud_lifecycle,
    assert_spectator_product_hud_never_visible,
    parse_spectator_product_hud_states,
)


class SpectatorProductHudGuardTests(unittest.TestCase):
    def test_parser_reads_state_transitions(self) -> None:
        states = parse_spectator_product_hud_states(
            "Product spectator HUD surface. active=0 phase=Inactive "
            "registered=0 rendered=0 target_participant_id=0\n"
            "Product spectator HUD surface. active=1 phase=Spectating "
            "registered=1 rendered=1 "
            "target_participant_id=2305843009213698050\n"
        )
        self.assertEqual(2, len(states))
        self.assertFalse(states[0]["active"])
        self.assertEqual("Spectating", states[1]["phase"])
        self.assertTrue(states[1]["registered"])
        self.assertTrue(states[1]["rendered"])
        self.assertEqual(
            2305843009213698050,
            states[1]["target_participant_id"],
        )

    def test_context_matrix_allows_only_spectating(self) -> None:
        visible_contexts = {
            context
            for context, visible in
            PRODUCT_HUD_CONTEXT_EXPECTATIONS.items()
            if visible
        }
        self.assertEqual({"spectating"}, visible_contexts)

    def test_latest_state_assertion_checks_target_and_visibility(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "solomondarkmodloader.log"
            log_path.write_text(
                "Product spectator HUD surface. active=0 phase=Inactive "
                "registered=0 rendered=0 target_participant_id=0\n"
                "Product spectator HUD surface. active=1 phase=Spectating "
                "registered=1 rendered=1 "
                "target_participant_id=2305843009213698050\n",
                encoding="utf-8",
            )
            result = assert_latest_spectator_product_hud_state(
                [log_path],
                context="spectating",
                expected_active=True,
                expected_phase="Spectating",
                expected_registered=True,
                expected_rendered=True,
                expected_target_participant_id=2305843009213698050,
            )
            self.assertTrue(result["matches"])

            with self.assertRaisesRegex(
                AssertionError,
                "product spectator HUD state mismatch",
            ):
                assert_latest_spectator_product_hud_state(
                    [log_path],
                    context="alive",
                    expected_active=False,
                    expected_phase="Inactive",
                    expected_registered=False,
                    expected_rendered=False,
                    expected_target_participant_id=0,
                )

    def test_lifecycle_requires_hidden_presentation_visible_spectating_and_retire(
        self,
    ) -> None:
        target_id = 2305843009213698050
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "solomondarkmodloader.log"
            log_path.write_text(
                "Product spectator HUD surface. active=0 "
                "phase=Inactive registered=0 rendered=0 "
                "target_participant_id=0\n"
                "Product spectator HUD surface. active=1 "
                "phase=DeathPresentation registered=0 rendered=0 "
                "target_participant_id=0\n"
                "Product spectator HUD surface. active=1 "
                "phase=Spectating registered=1 rendered=1 "
                f"target_participant_id={target_id}\n"
                "Product spectator HUD surface. active=0 "
                "phase=Inactive registered=0 rendered=0 "
                "target_participant_id=0\n",
                encoding="utf-8",
            )

            result = assert_spectator_product_hud_lifecycle(
                log_path,
                expected_target_participant_id=target_id,
                require_retired=True,
            )

            self.assertTrue(result["matches"])
            self.assertEqual(4, len(result["matched_states"]))

    def test_non_spectator_peer_cannot_register_or_render_product_hud(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "solomondarkmodloader.log"
            log_path.write_text(
                "Product spectator HUD surface. active=0 "
                "phase=Inactive registered=0 rendered=0 "
                "target_participant_id=0\n"
                "Product spectator HUD surface. active=1 "
                "phase=DeathPresentation registered=0 rendered=0 "
                "target_participant_id=0\n",
                encoding="utf-8",
            )
            self.assertTrue(
                assert_spectator_product_hud_never_visible(
                    log_path
                )["matches"]
            )

            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(
                    "Product spectator HUD surface. active=0 "
                    "phase=Inactive registered=1 rendered=1 "
                    "target_participant_id=0\n"
                )
            with self.assertRaisesRegex(
                AssertionError,
                "became visible",
            ):
                assert_spectator_product_hud_never_visible(log_path)


if __name__ == "__main__":
    unittest.main()
