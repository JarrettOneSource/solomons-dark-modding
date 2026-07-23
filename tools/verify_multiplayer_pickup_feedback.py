#!/usr/bin/env python3
"""Verify that an accepted client pickup replayed its stock presentation once."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_PIPE,
    ROOT,
    VerifyFailure,
    lua,
    parse_int_text,
    parse_key_values,
)


OUTPUT = ROOT / "runtime" / "multiplayer_pickup_feedback.json"

STOCK_POTION_SUBTYPES = (0, 1, 2, 3, 4, 5)
STOCK_POTION_NAMES = {
    0: "Health Potion",
    1: "Mana Potion",
    2: "Wizard Chug",
    3: "Antidote",
    4: "Mind Chug",
    5: "Rejuvenation Potion",
}
MISC_ITEM_SUBTYPES = (0, 1, 2, 3)
MISC_ITEM_NAMES = {
    0: "Fabric Dye Kit",
    1: "Wizard Key",
    2: "Book of Skill",
    3: "Book of Skill",
}


CAPTURE_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local loot = sd.world and sd.world.get_replicated_loot and
  sd.world.get_replicated_loot() or nil
local result = loot and loot.last_pickup_result or nil
local feedback = loot and loot.last_pickup_feedback or nil
emit("result.valid", result ~= nil)
emit("result.network_drop_id", result and result.network_drop_id or 0)
emit("result.request_sequence", result and result.request_sequence or 0)
emit("result.result", result and result.result or "")
emit("result.kind", result and result.kind or "")
emit("result.item_type_id", result and result.item_type_id or 0)
emit("result.item_recipe_uid", result and result.item_recipe_uid or 0)
emit("result.item_slot", result and result.item_slot or -1)
emit("result.stack_count", result and result.stack_count or 0)
emit("feedback.valid", feedback ~= nil and feedback.valid or false)
emit("feedback.accepted", feedback and feedback.accepted or false)
emit("feedback.applied", feedback and feedback.applied or false)
emit("feedback.network_drop_id", feedback and feedback.network_drop_id or 0)
emit("feedback.request_sequence", feedback and feedback.request_sequence or 0)
emit("feedback.kind", feedback and feedback.kind or "")
emit("feedback.item_type_id", feedback and feedback.item_type_id or 0)
emit("feedback.item_recipe_uid", feedback and feedback.item_recipe_uid or 0)
emit("feedback.item_slot", feedback and feedback.item_slot or -1)
emit("feedback.stack_count", feedback and feedback.stack_count or 0)
emit("feedback.stock_feedback_applied",
  feedback and feedback.stock_feedback_applied or false)
emit("feedback.notification_applied",
  feedback and feedback.notification_applied or false)
emit("feedback.apply_count", feedback and feedback.apply_count or 0)
emit("feedback.accepted_ms", feedback and feedback.accepted_ms or 0)
emit("feedback.applied_ms", feedback and feedback.applied_ms or 0)
"""


def capture(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, CAPTURE_LUA, timeout=8.0))


def is_true(value: str | None) -> bool:
    return value == "true"


def validate_feedback(
    values: dict[str, str],
    *,
    expected_kind: str | None,
    expected_network_drop_id: int | None,
    expected_item_type_id: int | None,
    expected_item_slot: int | None,
    require_notification: bool,
) -> dict[str, Any]:
    failures: list[str] = []
    result_drop_id = parse_int_text(values.get("result.network_drop_id"), 0)
    feedback_drop_id = parse_int_text(values.get("feedback.network_drop_id"), 0)
    result_kind = values.get("result.kind", "")
    feedback_kind = values.get("feedback.kind", "")

    if not is_true(values.get("result.valid")):
        failures.append("last pickup result is unavailable")
    if values.get("result.result") != "Accepted":
        failures.append(f"last pickup result is {values.get('result.result')!r}, not Accepted")
    if not is_true(values.get("feedback.valid")):
        failures.append("last pickup feedback is unavailable")
    if not is_true(values.get("feedback.accepted")):
        failures.append("pickup feedback was not marked accepted")
    if not is_true(values.get("feedback.applied")):
        failures.append("pickup feedback was not marked applied")
    if not is_true(values.get("feedback.stock_feedback_applied")):
        failures.append("stock pickup presentation was not confirmed")
    if parse_int_text(values.get("feedback.apply_count"), 0) != 1:
        failures.append("pickup presentation did not apply exactly once")
    if result_drop_id == 0 or feedback_drop_id != result_drop_id:
        failures.append(
            f"result/feedback drop mismatch: result={result_drop_id} feedback={feedback_drop_id}"
        )
    if result_kind != feedback_kind:
        failures.append(
            f"result/feedback kind mismatch: result={result_kind!r} feedback={feedback_kind!r}"
        )
    if expected_kind is not None and feedback_kind != expected_kind:
        failures.append(
            f"feedback kind {feedback_kind!r} did not match {expected_kind!r}"
        )
    if expected_network_drop_id is not None and feedback_drop_id != expected_network_drop_id:
        failures.append(
            f"feedback drop {feedback_drop_id} did not match {expected_network_drop_id}"
        )
    if expected_item_type_id is not None and parse_int_text(
        values.get("feedback.item_type_id"), 0
    ) != expected_item_type_id:
        failures.append("feedback item type did not match the expected native identity")
    if expected_item_slot is not None and parse_int_text(
        values.get("feedback.item_slot"), -1
    ) != expected_item_slot:
        failures.append("feedback item subtype did not match the expected native identity")
    if require_notification and not is_true(values.get("feedback.notification_applied")):
        failures.append("native pickup notification was not confirmed")

    report: dict[str, Any] = {
        "passed": not failures,
        "failures": failures,
        "capture": values,
        "supported_stock_potions": [
            {"subtype": subtype, "name": STOCK_POTION_NAMES[subtype]}
            for subtype in STOCK_POTION_SUBTYPES
        ],
        "supported_misc_items": [
            {"subtype": subtype, "name": MISC_ITEM_NAMES[subtype]}
            for subtype in MISC_ITEM_SUBTYPES
        ],
    }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=CLIENT_PIPE)
    parser.add_argument(
        "--expected-kind",
        choices=("Gold", "Orb", "Item", "Potion", "Powerup"),
    )
    parser.add_argument("--expected-network-drop-id", type=lambda value: int(value, 0))
    parser.add_argument("--expected-item-type-id", type=lambda value: int(value, 0))
    parser.add_argument("--expected-item-slot", type=int)
    parser.add_argument("--require-notification", action="store_true")
    parser.add_argument("--list-supported", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.list_supported:
        print(json.dumps({
            "stock_potions": STOCK_POTION_NAMES,
            "misc_items": MISC_ITEM_NAMES,
        }, indent=2, sort_keys=True))
        return 0

    report = validate_feedback(
        capture(args.pipe),
        expected_kind=args.expected_kind,
        expected_network_drop_id=args.expected_network_drop_id,
        expected_item_type_id=args.expected_item_type_id,
        expected_item_slot=args.expected_item_slot,
        require_notification=args.require_notification,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise VerifyFailure("; ".join(report["failures"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
