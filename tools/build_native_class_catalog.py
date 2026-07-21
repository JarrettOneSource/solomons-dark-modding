#!/usr/bin/env python3
"""Convert ``catalog_native_classes.py`` output to deterministic JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


CLASS_RE = re.compile(r"^CLASS (?P<name>.+) VTABLE (?P<vtable>[0-9a-fA-F]{8})$")
REF_RE = re.compile(
    r"^  VTABLE_REF (?P<address>[0-9a-fA-F]{8}) (?P<name>\S+)$"
)
SLOT_RE = re.compile(
    r"^  SLOT (?P<offset>0x[0-9A-Fa-f]+) "
    r"(?P<address>[0-9a-fA-F]{8}) (?P<name>.+)$"
)
SLOT_BYTES_RE = re.compile(r"^  SLOT_BYTES (?P<size>0x[0-9A-Fa-f]+)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def classify(name: str) -> str:
    if name.startswith("Anim_") or name == "ZAnim":
        return "animation_or_effect"
    if name.startswith("Action_"):
        return "actor_action"
    if name.startswith("Mod_") or name == "Mod":
        return "status_modifier"
    if name.startswith("Item"):
        return "item"
    if name.startswith("Bundle_"):
        return "sprite_bundle"
    if name.startswith("Array<") or name.startswith("PointerList<") or name.startswith("Stack<"):
        return "container"
    return "object_or_system"


def parse_log(path: Path) -> list[dict[str, Any]]:
    classes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = CLASS_RE.match(raw_line)
        if match:
            current = {
                "name": match.group("name"),
                "category": classify(match.group("name")),
                "vtable": "0x" + match.group("vtable").upper(),
                "vtable_references": [],
                "slots": [],
            }
            classes.append(current)
            continue
        if current is None:
            continue

        match = REF_RE.match(raw_line)
        if match:
            current["vtable_references"].append(
                {
                    "function": "0x" + match.group("address").upper(),
                    "name": match.group("name"),
                }
            )
            continue
        match = SLOT_RE.match(raw_line)
        if match:
            current["slots"].append(
                {
                    "offset": match.group("offset").upper().replace("X", "x"),
                    "function": "0x" + match.group("address").upper(),
                    "name": match.group("name"),
                }
            )
            continue
        match = SLOT_BYTES_RE.match(raw_line)
        if match:
            current["slot_bytes"] = match.group("size").upper().replace("X", "x")

    return classes


def main() -> int:
    args = parse_args()
    classes = parse_log(args.log)
    result = {
        "schema": "solomon-dark-native-class-catalog-v1",
        "source_log": str(args.log),
        "summary": {
            "class_count": len(classes),
            "vtable_reference_count": sum(
                len(entry["vtable_references"]) for entry in classes
            ),
            "vtable_slot_count": sum(len(entry["slots"]) for entry in classes),
        },
        "classes": classes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
