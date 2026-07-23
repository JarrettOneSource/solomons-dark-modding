#!/usr/bin/env python3
"""Tests for the live Lua spell registry and picker verifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import verify_lua_spells as verifier  # noqa: E402


REGISTRY_RESULT = f"""
stable_id={verifier.EXPECTED_CONTENT_ID}
effect_snapshot_schema_valid=true
descriptor_copy_isolated=true
raw_internals_absent=true
zero_rejected=true
fraction_rejected=true
late_registration_rejected=true
selection_round_trip=true
"""


class LuaSpellsVerifierTests(unittest.TestCase):
    def test_run_activates_and_clears_the_owned_picker(self) -> None:
        outputs = [
            REGISTRY_RESULT,
            f"""
exec_target={verifier.PICKER_MOD_ID}
picker_visible=true
equip_queued=true
equip_request_id=17
""",
            f"""
slot1_selected=true
slot1_content_id={verifier.EXPECTED_CONTENT_ID}
""",
            """
clear_queued=true
clear_request_id=18
""",
            """
slot1_selected=false
slot1_content_id=0
""",
            "true",
        ]
        with mock.patch.object(verifier, "lua", side_effect=outputs) as lua_call:
            result = verifier.run("test-pipe", timeout=1.0)

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["picker"]["equipped"]["slot1_content_id"],
            str(verifier.EXPECTED_CONTENT_ID),
        )
        self.assertEqual(result["picker"]["cleared"]["slot1_selected"], "false")
        self.assertEqual(
            lua_call.call_args_list[-1].args[1],
            verifier.PICKER_CLEANUP_PROBE,
        )

    def test_failed_picker_action_still_clears_slot_one(self) -> None:
        outputs = [
            REGISTRY_RESULT,
            f"""
exec_target={verifier.PICKER_MOD_ID}
picker_visible=false
equip_queued=false
""",
            "true",
        ]
        with mock.patch.object(verifier, "lua", side_effect=outputs) as lua_call:
            with self.assertRaisesRegex(
                verifier.VerifyFailure,
                "picker equip action failed",
            ):
                verifier.run("test-pipe", timeout=1.0)

        self.assertEqual(
            lua_call.call_args_list[-1].args[1],
            verifier.PICKER_CLEANUP_PROBE,
        )


if __name__ == "__main__":
    unittest.main()
