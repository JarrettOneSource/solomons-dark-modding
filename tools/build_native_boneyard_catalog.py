#!/usr/bin/env python3
"""Build a deterministic catalog of native .boneyard containers and RegionLayout lists."""

from __future__ import annotations

import argparse
import json
import struct
from collections import Counter
from pathlib import Path
from typing import Any

from inspect_native_boneyard import (
    Cursor,
    ParseError,
    build_summary,
    parse_sync_buffer,
    resolve_node,
)


REGION_LAYOUT_PATH = (0, 12, 0)

REGION_LAYOUT_CHUNKS = (
    (0, "scenery", "polymorphic_list", None),
    (1, "trigger_control", "object", None),
    (2, "origin_and_scalar", "fixed_payload", None),
    (3, "monster_recipes", "polymorphic_list", 6001),
    (4, "uid_groups", "polymorphic_list", 6002),
    (5, "roads", "polymorphic_list", 3004),
    (6, "fences", "polymorphic_list", 3005),
    (7, "item_recipes", "polymorphic_list", 6003),
    (8, "item_sets", "polymorphic_list", 6005),
    (9, "npc_recipes", "polymorphic_list", 6004),
    (10, "layout_flag", "byte", None),
    (11, "compact_decorations", "compact_records", None),
    (12, "terrain", "polymorphic_list", 3009),
    (13, "timelines", "polymorphic_list", 6006),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        metavar="LABEL=PATH",
        help="catalog one file under a stable semantic label; repeat for each file",
    )
    parser.add_argument("--object-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def parse_input(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError("--input must use LABEL=PATH")
    label, raw_path = value.split("=", 1)
    if not label or not raw_path:
        raise ValueError("--input must use non-empty LABEL=PATH values")
    return label, Path(raw_path)


def read_u32_array(payload: bytes, context: str) -> list[int]:
    if len(payload) < 4:
        raise ParseError(f"{context}: missing list count")
    count = struct.unpack_from("<I", payload)[0]
    expected_size = 4 + count * 4
    if len(payload) != expected_size:
        raise ParseError(
            f"{context}: count {count} requires {expected_size} payload bytes, "
            f"found {len(payload)}"
        )
    return list(struct.unpack_from(f"<{count}I", payload, 4)) if count else []


def named_counts(values: list[int], type_names: dict[int, str]) -> dict[str, int]:
    counts = Counter(values)
    return {
        type_names.get(type_id, f"unknown_{type_id}"): count
        for type_id, count in sorted(counts.items())
    }


def parse_timeline(node: Any, type_names: dict[int, str], context: str) -> dict[str, Any]:
    payload = node.payload
    if len(payload) < 9:
        raise ParseError(f"{context}: truncated TimeLine payload")
    string_size = struct.unpack_from("<I", payload)[0]
    string_end = 4 + string_size
    if string_size == 0 or string_end + 9 > len(payload):
        raise ParseError(f"{context}: invalid TimeLine name size {string_size}")
    raw_name = payload[4:string_end]
    if raw_name[-1] != 0:
        raise ParseError(f"{context}: TimeLine name is not NUL terminated")
    name = raw_name[:-1].decode("utf-8")
    uid = struct.unpack_from("<I", payload, string_end)[0]
    enabled = payload[string_end + 4]
    event_count = struct.unpack_from("<I", payload, string_end + 5)[0]
    event_types_offset = string_end + 9
    event_types_end = event_types_offset + event_count * 4
    if event_types_end > len(payload):
        raise ParseError(f"{context}: truncated TimeLine event type list")
    event_types = (
        list(struct.unpack_from(f"<{event_count}I", payload, event_types_offset))
        if event_count
        else []
    )
    if event_count != len(node.children):
        raise ParseError(
            f"{context}: payload declares {event_count} events, "
            f"but {len(node.children)} event chunks exist"
        )
    return {
        "name": name,
        "uid": uid,
        "enabled_byte": enabled,
        "event_count": event_count,
        "event_type_counts": named_counts(event_types, type_names),
        "trailing_payload_bytes": len(payload) - event_types_end,
    }


def parse_region_layout(node: Any, type_names: dict[int, str], label: str) -> dict[str, Any]:
    if len(node.children) != len(REGION_LAYOUT_CHUNKS):
        raise ParseError(
            f"{label}: RegionLayout has {len(node.children)} top-level chunks, "
            f"expected {len(REGION_LAYOUT_CHUNKS)}"
        )

    lists: dict[str, Any] = {}
    for index, name, kind, expected_type in REGION_LAYOUT_CHUNKS:
        if kind != "polymorphic_list":
            continue
        child = node.children[index]
        type_ids = read_u32_array(child.payload, f"{label}:{name}")
        if expected_type is not None and any(value != expected_type for value in type_ids):
            raise ParseError(
                f"{label}:{name}: expected only type {expected_type}, "
                f"found {sorted(set(type_ids))}"
            )
        lists[name] = {
            "count": len(type_ids),
            "type_counts": named_counts(type_ids, type_names),
            "serialized_child_chunk_count": len(child.children),
        }

    origin_payload = node.children[2].payload
    if len(origin_payload) != 12:
        raise ParseError(f"{label}: origin_and_scalar payload is not 12 bytes")
    origin_x, origin_y, scalar = struct.unpack("<fff", origin_payload)

    flag_payload = node.children[10].payload
    if len(flag_payload) != 1:
        raise ParseError(f"{label}: layout_flag payload is not one byte")

    compact_payload = node.children[11].payload
    if len(compact_payload) < 4:
        raise ParseError(f"{label}: compact decoration payload is truncated")
    compact_count = struct.unpack_from("<I", compact_payload)[0]
    expected_compact_size = 4 + compact_count * 25
    if len(compact_payload) != expected_compact_size:
        raise ParseError(
            f"{label}: {compact_count} compact records require "
            f"{expected_compact_size} bytes, found {len(compact_payload)}"
        )
    compact_types = [
        struct.unpack_from("<I", compact_payload, 4 + index * 25)[0]
        for index in range(compact_count)
    ]

    timeline_nodes = node.children[13].children
    if len(timeline_nodes) != lists["timelines"]["count"]:
        raise ParseError(
            f"{label}: timeline list declares {lists['timelines']['count']} objects, "
            f"but {len(timeline_nodes)} object chunks exist"
        )

    return {
        "node_path": ".".join(map(str, REGION_LAYOUT_PATH)),
        "top_level_chunk_count": len(node.children),
        "origin": {"x": origin_x, "y": origin_y},
        "scalar": scalar,
        "layout_flag": flag_payload[0],
        "lists": lists,
        "compact_decorations": {
            "count": compact_count,
            "record_size": 25,
            "type_counts": {
                str(type_id): count
                for type_id, count in sorted(Counter(compact_types).items())
            },
        },
        "timelines": [
            parse_timeline(timeline, type_names, f"{label}:timeline[{index}]")
            for index, timeline in enumerate(timeline_nodes)
        ],
    }


def build_entry(label: str, path: Path, type_names: dict[int, str]) -> dict[str, Any]:
    data = path.read_bytes()
    cursor = Cursor(data)
    root = parse_sync_buffer(cursor)
    if cursor.offset != len(data):
        raise ParseError(
            f"{label}: unparsed data starts at 0x{cursor.offset:X} "
            f"({len(data) - cursor.offset} bytes remain)"
        )
    summary = build_summary(path, data, root)
    layout = resolve_node(root.root, REGION_LAYOUT_PATH)
    return {
        "label": label,
        "size": summary["size"],
        "sha256": summary["sha256"],
        "sync_buffer_count": summary["sync_buffer_count"],
        "anonymous_node_count": summary["anonymous_node_count"],
        "payload_bytes": summary["payload_bytes"],
        "maximum_anonymous_node_depth": summary["maximum_anonymous_node_depth"],
        "named_child_count": len(root.named_children),
        "region_layout": parse_region_layout(layout, type_names, label),
    }


def main() -> int:
    args = parse_args()
    object_catalog = json.loads(args.object_catalog.read_text(encoding="utf-8"))
    type_names = {
        entry["type_id"]: entry["class"] for entry in object_catalog["types"]
    }
    inputs = [parse_input(value) for value in args.input]
    labels = [label for label, _ in inputs]
    if len(labels) != len(set(labels)):
        raise ValueError("--input labels must be unique")

    output = {
        "schema": "solomon-dark-native-boneyard-catalog-v1",
        "source": {
            "object_catalog": args.object_catalog.as_posix(),
            "region_layout_node_path": ".".join(map(str, REGION_LAYOUT_PATH)),
        },
        "container_grammar": {
            "chunk_node": [
                "u32 payload_size",
                "payload bytes",
                "u32 anonymous_child_count",
                "recursive anonymous children",
            ],
            "sync_buffer": [
                "root chunk node",
                "u32 named_child_count",
                "NUL-terminated length-prefixed name plus recursive SyncBuffer per child",
            ],
        },
        "region_layout_chunks": [
            {
                "index": index,
                "name": name,
                "kind": kind,
                **({"expected_type_id": expected_type} if expected_type is not None else {}),
            }
            for index, name, kind, expected_type in REGION_LAYOUT_CHUNKS
        ],
        "files": [build_entry(label, path, type_names) for label, path in inputs],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "file_count": len(output["files"]),
                "total_bytes": sum(entry["size"] for entry in output["files"]),
                "total_nodes": sum(
                    entry["anonymous_node_count"] for entry in output["files"]
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
