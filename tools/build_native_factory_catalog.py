#!/usr/bin/env python3
"""Recover GameObjectFactory type IDs, allocation sizes, constructors, and RTTI classes."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


TARGET_START_RE = re.compile(r"^=== TARGET: 0x005b7080 ===$", re.IGNORECASE)
TARGET_END_RE = re.compile(r"^=== TARGET:")
TYPE_RE = re.compile(
    r"(?:if|else if) \(param_1 == (?P<if_value>0x[0-9a-f]+|\d+)\)|"
    r"case (?P<case_value>0x[0-9a-f]+|\d+):",
    re.IGNORECASE,
)
ALLOC_RE = re.compile(r"Object_Allocate\((?P<size>0x[0-9a-f]+|\d+),", re.IGNORECASE)
CTOR_RE = re.compile(r"uVar3 = (?P<ctor>[A-Za-z_][A-Za-z0-9_]*)\(")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factory-log", type=Path, required=True)
    parser.add_argument("--class-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def parse_int(value: str) -> int:
    return int(value, 16) if value.lower().startswith("0x") else int(value)


def extract_factory_lines(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = next((index for index, line in enumerate(lines) if TARGET_START_RE.match(line)), None)
    if start is None:
        raise ValueError("factory target marker is missing")
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if TARGET_END_RE.match(lines[index])
        ),
        len(lines),
    )
    return lines[start:end]


def parse_factory(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current_type: int | None = None
    allocation_size: int | None = None

    for line in extract_factory_lines(path):
        type_match = TYPE_RE.search(line)
        if type_match:
            current_type = parse_int(type_match.group("if_value") or type_match.group("case_value"))
            allocation_size = None
            continue

        allocation_match = ALLOC_RE.search(line)
        if allocation_match:
            if current_type is None:
                raise ValueError("allocation without a current type: %s" % line)
            allocation_size = parse_int(allocation_match.group("size"))
            continue

        constructor_match = CTOR_RE.search(line)
        if constructor_match and allocation_size is not None:
            entries.append(
                {
                    "type_id": current_type,
                    "type_id_hex": "0x%X" % current_type,
                    "allocation_size": allocation_size,
                    "allocation_size_hex": "0x%X" % allocation_size,
                    "constructor": constructor_match.group("ctor"),
                }
            )
            allocation_size = None

    by_type: dict[int, dict[str, Any]] = {}
    for entry in entries:
        type_id = entry["type_id"]
        if type_id in by_type:
            raise ValueError("duplicate factory type 0x%X" % type_id)
        by_type[type_id] = entry
    return [by_type[type_id] for type_id in sorted(by_type)]


def normalize_function_name(name: str) -> str:
    match = re.fullmatch(r"FUN_([0-9a-fA-F]{8})", name)
    return "0x" + match.group(1).upper() if match else name


def add_class_relations(
    entries: list[dict[str, Any]], catalog: dict[str, Any]
) -> None:
    classes_by_reference: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for class_entry in catalog["classes"]:
        for reference in class_entry["vtable_references"]:
            classes_by_reference[reference["function"]].append(class_entry)

    for entry in entries:
        constructor_address = normalize_function_name(entry["constructor"])
        entry["constructor_address"] = constructor_address
        candidates = classes_by_reference.get(constructor_address, [])
        candidate_rows = [
            {
                "name": candidate["name"],
                "category": candidate["category"],
                "vtable": candidate["vtable"],
                "vtable_slot_count": len(candidate["slots"]),
            }
            for candidate in candidates
        ]
        candidate_rows.sort(key=lambda row: (row["category"], row["name"]))
        entry["rtti_candidates"] = candidate_rows

        concrete = [
            row
            for row in candidate_rows
            if row["category"] != "container"
            and row["name"] not in {"Object", "String"}
        ]
        if concrete:
            concrete.sort(
                key=lambda row: (row["vtable_slot_count"], row["name"]), reverse=True
            )
            entry["class"] = concrete[0]["name"]
            entry["vtable"] = concrete[0]["vtable"]
            entry["class_resolution"] = (
                "unique" if len(concrete) == 1 else "ranked_most_derived"
            )
        else:
            entry["class"] = None
            entry["vtable"] = None
            entry["class_resolution"] = "unresolved"


def main() -> int:
    args = parse_args()
    catalog = json.loads(args.class_catalog.read_text(encoding="utf-8"))
    entries = parse_factory(args.factory_log)
    add_class_relations(entries, catalog)
    resolved = sum(entry["class"] is not None for entry in entries)
    output = {
        "schema": "solomon-dark-native-factory-catalog-v1",
        "source": {
            "factory": "0x005B7080",
            "factory_log": str(args.factory_log),
            "class_catalog": str(args.class_catalog),
        },
        "summary": {
            "type_count": len(entries),
            "rtti_resolved_type_count": resolved,
            "unresolved_type_count": len(entries) - resolved,
        },
        "types": entries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(output["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
