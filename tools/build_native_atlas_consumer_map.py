#!/usr/bin/env python3
"""Join Ghidra atlas-singleton uses to serialized bundle record ranges.

The Ghidra producer is ``trace_bundle_field_consumers.py``. This script keeps
the raw decompiler evidence and annotates every literal singleton-relative
offset with the builder destination from ``native-content-inventory.json``.
Indirect uses that Ghidra propagates through a local remain visible as
functions with zero mapped destinations; they are intentionally not guessed.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ATLAS_RE = re.compile(r"^ATLAS (?P<name>\S+)$")
SINGLETON_RE = re.compile(r"^  SINGLETON (?P<address>[0-9a-fA-F]{8})$")
REFERENCE_COUNT_RE = re.compile(r"^  REFERENCE_COUNT (?P<count>\d+)$")
FUNCTION_COUNT_RE = re.compile(r"^  FUNCTION_COUNT (?P<count>\d+)$")
FUNCTION_RE = re.compile(
    r"^  FUNCTION (?P<address>[0-9a-fA-F]{8}) "
    r"(?P<name>\S+) MATCHES (?P<count>\d+)$"
)
FUNCTION_ERROR_RE = re.compile(
    r"^  FUNCTION (?P<address>[0-9a-fA-F]{8}) (?P<name>\S+) ERROR (?P<error>.+)$"
)
USE_RE = re.compile(r"^    USE line=(?P<line>\d+) (?P<source>.*)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--consumer-log", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def parse_consumer_logs(paths: list[Path]) -> list[dict[str, Any]]:
    atlases: list[dict[str, Any]] = []
    current_atlas: dict[str, Any] | None = None
    current_function: dict[str, Any] | None = None

    for path in paths:
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = ATLAS_RE.match(raw_line)
            if match:
                current_atlas = {
                    "name": match.group("name"),
                    "source_log": str(path),
                    "consumers": [],
                }
                atlases.append(current_atlas)
                current_function = None
                continue
            if current_atlas is None:
                continue

            match = SINGLETON_RE.match(raw_line)
            if match:
                current_atlas["singleton"] = "0x" + match.group("address").upper()
                continue
            match = REFERENCE_COUNT_RE.match(raw_line)
            if match:
                current_atlas["reference_count"] = int(match.group("count"))
                continue
            match = FUNCTION_COUNT_RE.match(raw_line)
            if match:
                current_atlas["function_count"] = int(match.group("count"))
                continue

            match = FUNCTION_RE.match(raw_line)
            if match:
                current_function = {
                    "address": "0x" + match.group("address").upper(),
                    "name": match.group("name"),
                    "decompiler_match_count": int(match.group("count")),
                    "uses": [],
                }
                current_atlas["consumers"].append(current_function)
                continue
            match = FUNCTION_ERROR_RE.match(raw_line)
            if match:
                current_function = {
                    "address": "0x" + match.group("address").upper(),
                    "name": match.group("name"),
                    "decompiler_error": match.group("error"),
                    "uses": [],
                }
                current_atlas["consumers"].append(current_function)
                continue

            match = USE_RE.match(raw_line)
            if match and current_function is not None:
                current_function["uses"].append(
                    {
                        "line": int(match.group("line")),
                        "source": match.group("source"),
                    }
                )

    return atlases


def destination_for_offset(
    offset: int, destinations: list[dict[str, Any]]
) -> dict[str, Any] | None:
    for destination in destinations:
        field = int(destination["object_field"], 16)
        if destination["destination_kind"] == "inline":
            start = field
            size = 0xC4
        elif destination["destination_kind"] == "array":
            # Generated array fields point at the first element. The four-byte
            # vector owner immediately precedes the pointer; count/capacity
            # follow it. Adjacent generated arrays are exactly 0x10 apart.
            start = field - 4
            size = 0x10
        else:
            # BundleAuxTable_Parse builds a fixed-size font/glyph lookup object.
            start = field
            size = 0x4D434
        if start <= offset < start + size:
            return {
                "destination_kind": destination["destination_kind"],
                "object_field": destination["object_field"],
                "field_delta": "0x%X" % (offset - field),
                "first_record": destination["first_record"],
                "last_record": destination["last_record"],
                **(
                    {"aux_group": destination["group"]}
                    if "group" in destination else {}
                ),
            }
    return None


def annotate(
    consumer_atlases: list[dict[str, Any]],
    inventory: dict[str, Any],
    inventory_path: Path,
    consumer_log_paths: list[Path],
) -> dict[str, Any]:
    inventory_by_name = {atlas["name"]: atlas for atlas in inventory["atlases"]}
    seen_names: set[str] = set()

    total_functions = 0
    total_use_lines = 0
    total_literal_offsets = 0
    total_mapped_offsets = 0
    total_functions_with_mapped_destination = 0

    for atlas in consumer_atlases:
        name = atlas["name"]
        if name in seen_names:
            raise ValueError("duplicate consumer atlas %s" % name)
        seen_names.add(name)
        if name not in inventory_by_name:
            raise ValueError("consumer atlas %s is absent from inventory" % name)

        inventory_atlas = inventory_by_name[name]
        destinations = list(inventory_atlas["builder_trace"]["destinations"])
        destinations.extend(
            {
                **destination,
                "destination_kind": "aux",
            }
            for destination in inventory_atlas["builder_trace"]["aux_destinations"]
        )
        atlas["builder"] = inventory_atlas["builder"]
        atlas["record_count"] = inventory_atlas["record_count"]

        singleton_token = atlas["singleton"][2:].lower()
        offset_re = re.compile(
            r"_?DAT_%s\s*\+\s*0x([0-9a-f]+)" % singleton_token,
            re.IGNORECASE,
        )
        atlas_mapped_destination_keys: set[tuple[Any, ...]] = set()

        for function in atlas["consumers"]:
            total_functions += 1
            function_mapped_destination_keys: set[tuple[Any, ...]] = set()
            for use in function["uses"]:
                total_use_lines += 1
                offsets = sorted(
                    {int(value, 16) for value in offset_re.findall(use["source"])}
                )
                use["literal_offsets"] = ["0x%X" % value for value in offsets]
                use["destinations"] = []
                for offset in offsets:
                    total_literal_offsets += 1
                    mapped = destination_for_offset(offset, destinations)
                    if mapped is None:
                        continue
                    total_mapped_offsets += 1
                    use["destinations"].append(mapped)
                    key = (
                        mapped["destination_kind"],
                        mapped["object_field"],
                        mapped["first_record"],
                        mapped["last_record"],
                        mapped.get("aux_group"),
                    )
                    function_mapped_destination_keys.add(key)
                    atlas_mapped_destination_keys.add(key)

            function["mapped_destinations"] = [
                {
                    "destination_kind": key[0],
                    "object_field": key[1],
                    "first_record": key[2],
                    "last_record": key[3],
                    **({"aux_group": key[4]} if key[4] is not None else {}),
                }
                for key in sorted(function_mapped_destination_keys)
            ]
            if function_mapped_destination_keys:
                total_functions_with_mapped_destination += 1

        atlas["mapped_destinations"] = [
            {
                "destination_kind": key[0],
                "object_field": key[1],
                "first_record": key[2],
                    "last_record": key[3],
                    **({"aux_group": key[4]} if key[4] is not None else {}),
                }
            for key in sorted(atlas_mapped_destination_keys)
        ]

    missing = sorted(set(inventory_by_name) - seen_names)
    if missing:
        raise ValueError("missing consumer logs for: %s" % ", ".join(missing))

    return {
        "schema": "solomon-dark-native-atlas-consumers-v1",
        "source": {
            "inventory": str(inventory_path),
            "consumer_logs": [str(path) for path in consumer_log_paths],
        },
        "summary": {
            "atlas_count": len(consumer_atlases),
            "consumer_function_count": total_functions,
            "function_with_direct_mapped_destination_count": (
                total_functions_with_mapped_destination
            ),
            "decompiler_use_line_count": total_use_lines,
            "literal_singleton_offset_count": total_literal_offsets,
            "mapped_literal_singleton_offset_count": total_mapped_offsets,
        },
        "atlases": consumer_atlases,
    }


if __name__ == "__main__":
    args = parse_args()
    inventory_data = json.loads(args.inventory.read_text(encoding="utf-8"))
    consumer_data = parse_consumer_logs(args.consumer_log)
    output_data = annotate(
        consumer_data, inventory_data, args.inventory, args.consumer_log
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output_data, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(output_data["summary"], indent=2))
