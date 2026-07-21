#!/usr/bin/env python3
"""Index headless-Ghidra decompilations by factory class and virtual role."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


TARGET_RE = re.compile(r"^=== TARGET: 0x(?P<address>[0-9A-Fa-f]{8}) ===$")
FUNCTION_RE = re.compile(
    r"^FUNCTION (?P<name>\S+) @ (?P<address>[0-9A-Fa-f]{8})$"
)
SIGNATURE_RE = re.compile(r"^SIGNATURE: (?P<signature>.*)$")
CALL_RE = re.compile(r"\b(?P<name>[A-Za-z_][A-Za-z0-9_:]*)\s*\(")
STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')
PARAM_OFFSET_RE = re.compile(
    r"(?P<param>param_\d+)\s*\+\s*0x(?P<offset>[0-9a-f]+)", re.IGNORECASE
)
GLOBAL_RE = re.compile(r"\b_?DAT_[0-9a-f]{8}\b", re.IGNORECASE)
CASE_RE = re.compile(r"\bcase\s+(?P<value>0x[0-9a-f]+|\d+)\s*:", re.IGNORECASE)

CALL_KEYWORDS = {
    "if", "while", "for", "switch", "sizeof", "return", "catch",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, action="append", required=True)
    parser.add_argument("--game-object-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def extract_methods(paths: list[Path]) -> list[dict[str, Any]]:
    methods: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        target_indices = [index for index, line in enumerate(lines) if TARGET_RE.match(line)]
        for target_position, start in enumerate(target_indices):
            end = (
                target_indices[target_position + 1]
                if target_position + 1 < len(target_indices)
                else len(lines)
            )
            target_match = TARGET_RE.match(lines[start])
            assert target_match is not None
            target_address = "0x" + target_match.group("address").upper()
            if target_address in seen:
                continue
            seen.add(target_address)

            block = lines[start + 1:end]
            function_match = next(
                (FUNCTION_RE.match(line) for line in block if FUNCTION_RE.match(line)),
                None,
            )
            signature_match = next(
                (SIGNATURE_RE.match(line) for line in block if SIGNATURE_RE.match(line)),
                None,
            )
            if function_match is None:
                raise ValueError("function header missing for %s" % target_address)
            source_start = next(
                (
                    index + 1
                    for index, line in enumerate(block)
                    if SIGNATURE_RE.match(line)
                ),
                0,
            )
            source_lines = block[source_start:]
            while source_lines and source_lines[-1].strip() in {"", "()", "=== DONE ==="}:
                source_lines.pop()
            source = "\n".join(source_lines).strip()

            calls = sorted(
                {
                    match.group("name")
                    for match in CALL_RE.finditer(source)
                    if match.group("name") not in CALL_KEYWORDS
                    and match.group("name") != function_match.group("name")
                }
            )
            strings: list[str] = []
            for match in STRING_RE.finditer(source):
                token = match.group(0)
                try:
                    value = bytes(token[1:-1], "utf-8").decode("unicode_escape")
                except UnicodeDecodeError:
                    value = token[1:-1]
                if value not in strings:
                    strings.append(value)

            parameter_offsets: dict[str, set[int]] = {}
            for match in PARAM_OFFSET_RE.finditer(source):
                parameter_offsets.setdefault(match.group("param"), set()).add(
                    int(match.group("offset"), 16)
                )

            methods.append(
                {
                    "address": target_address,
                    "name": function_match.group("name"),
                    "signature": signature_match.group("signature") if signature_match else None,
                    "source_log": str(path),
                    "decompiled_line_count": len(source.splitlines()),
                    "decompiled_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                    "calls": calls,
                    "strings": strings,
                    "parameter_offsets": {
                        parameter: ["0x%X" % value for value in sorted(values)]
                        for parameter, values in sorted(parameter_offsets.items())
                    },
                    "globals": sorted(
                        {match.group(0).upper() for match in GLOBAL_RE.finditer(source)}
                    ),
                    "switch_cases": sorted(
                        {int(match.group("value"), 0) for match in CASE_RE.finditer(source)}
                    ),
                }
            )
    methods.sort(key=lambda method: method["address"])
    return methods


def build_relations(
    methods: list[dict[str, Any]], game_objects: dict[str, Any]
) -> dict[str, Any]:
    relations: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = {}
    art_by_function: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = {}

    for object_type in game_objects["types"]:
        type_identity = {
            "type_id": object_type["type_id"],
            "type_id_hex": object_type["type_id_hex"],
            "class": object_type["class"],
            "band": object_type["band"],
        }
        constructor = object_type["constructor_address"]
        constructor_key = (
            object_type["type_id"], object_type["class"], "constructor", None
        )
        relations.setdefault(constructor, {})[constructor_key] = {
            **type_identity,
            "role": "constructor",
        }
        for slot in object_type["vtable_slots"]:
            key = (object_type["type_id"], object_type["class"], "vtable_slot", slot["offset"])
            relations.setdefault(slot["function"], {})[key] = {
                **type_identity,
                "role": "vtable_slot",
                "slot": slot["offset"],
            }
        for art_use in object_type["class_art_uses"]:
            function = art_use["consumer_function"]
            key = (
                art_use["atlas"], art_use["first_record"], art_use["last_record"],
                art_use["consumer_function"], art_use.get("vtable_slot"),
            )
            art_by_function.setdefault(function, {})[key] = art_use

    related_method_count = 0
    for method in methods:
        method_relations = list(relations.get(method["address"], {}).values())
        method_relations.sort(
            key=lambda relation: (
                relation["type_id"], relation["class"], relation["role"], relation.get("slot", "")
            )
        )
        method["object_relations"] = method_relations
        method["art_uses"] = list(art_by_function.get(method["address"], {}).values())
        if method_relations:
            related_method_count += 1

    return {
        "schema": "solomon-dark-native-method-index-v1",
        "source": {
            "decompiler_logs": sorted({method["source_log"] for method in methods}),
            "game_object_catalog": game_objects["source"],
        },
        "summary": {
            "method_count": len(methods),
            "method_with_object_relation_count": related_method_count,
            "decompiled_line_count": sum(
                method["decompiled_line_count"] for method in methods
            ),
        },
        "methods": methods,
    }


def main() -> int:
    args = parse_args()
    game_objects = json.loads(args.game_object_catalog.read_text(encoding="utf-8"))
    methods = extract_methods(args.log)
    output = build_relations(methods, game_objects)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(output["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
