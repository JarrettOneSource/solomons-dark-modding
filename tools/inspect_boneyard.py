#!/usr/bin/env python3
"""Validate and summarize Solomon Dark Boneyard SyncBuffer files."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_CHUNKS = 1_000_000
MAX_NAMED_BUFFERS = 65_536
MAX_NAME_BYTES = 1024 * 1024
MAX_DEPTH = 512
ARENA_SECTION_COUNT = 13
REGION_LAYOUT_SECTION_COUNT = 14

REGION_LAYOUT_SECTIONS = (
    "world_objects",
    "trigger_control",
    "region_geometry",
    "monster_recipes",
    "uid_groups",
    "roads",
    "fences",
    "item_recipes",
    "item_sets",
    "npc_recipes",
    "layout_flag",
    "dead_hawg_sprite_placements",
    "terrain",
    "timelines",
)

OBJECT_MANAGER_SECTIONS = frozenset({0, 3, 4, 5, 6, 7, 8, 9, 12, 13})

TYPE_NAMES = {
    2001: "Tree",
    2009: "Monument",
    2029: "Gravestone",
    2040: "Building",
    2061: "Goodie",
    3004: "Road",
    3005: "Fence",
    3006: "Fencepost",
    3007: "FenceGrate",
    3009: "Terrain",
    6001: "MonsterRecipe",
    6002: "UIDGroup",
    6003: "ItemRecipe",
    6004: "NPCRecipe",
    6005: "ItemSet",
    6006: "TimeLine",
}


class BoneyardFormatError(ValueError):
    """Raised when a file does not match the retail Boneyard envelope."""


@dataclass(frozen=True)
class Chunk:
    offset: int
    payload: bytes
    children: tuple["Chunk", ...]

    @property
    def chunk_count(self) -> int:
        return 1 + sum(child.chunk_count for child in self.children)

    @property
    def max_depth(self) -> int:
        return 0 if not self.children else 1 + max(child.max_depth for child in self.children)


@dataclass(frozen=True)
class NamedBuffer:
    name: bytes
    root: Chunk
    named_buffers: tuple["NamedBuffer", ...]


@dataclass(frozen=True)
class Boneyard:
    path: str
    data: bytes
    root: Chunk
    named_buffers: tuple[NamedBuffer, ...]

    @property
    def arena(self) -> Chunk:
        return self.root.children[0]

    @property
    def region_layout(self) -> Chunk:
        return self.arena.children[12].children[0]


class _Reader:
    def __init__(self, data: bytes, label: str) -> None:
        if len(data) > MAX_FILE_BYTES:
            raise BoneyardFormatError(f"{label}: Boneyards may not exceed 256 MiB")
        self.data = data
        self.label = label
        self.offset = 0
        self.chunk_count = 0
        self.named_buffer_count = 0

    def invalid(self, reason: str, offset: int | None = None) -> BoneyardFormatError:
        location = self.offset if offset is None else offset
        return BoneyardFormatError(f"{self.label}: invalid at byte {location}: {reason}")

    def read(self, length: int) -> bytes:
        end = self.offset + length
        if end > len(self.data):
            raise self.invalid("truncated SyncBuffer")
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def chunk(self, depth: int = 0) -> Chunk:
        if depth > MAX_DEPTH:
            raise self.invalid(f"SyncBuffer nesting exceeds {MAX_DEPTH} levels")
        if self.chunk_count == MAX_CHUNKS:
            raise self.invalid(f"SyncBuffer contains more than {MAX_CHUNKS} chunks")

        self.chunk_count += 1
        offset = self.offset
        payload = self.read(self.u32())
        child_count = self.u32()
        if child_count > MAX_CHUNKS - self.chunk_count:
            raise self.invalid(f"SyncBuffer contains more than {MAX_CHUNKS} chunks")
        children = tuple(self.chunk(depth + 1) for _ in range(child_count))
        return Chunk(offset, payload, children)

    def buffer(self, depth: int = 0) -> tuple[Chunk, tuple[NamedBuffer, ...]]:
        root = self.chunk(depth)
        named_count = self.u32()
        if named_count > MAX_NAMED_BUFFERS - self.named_buffer_count:
            raise self.invalid(f"SyncBuffer contains more than {MAX_NAMED_BUFFERS} named buffers")

        named_buffers: list[NamedBuffer] = []
        for _ in range(named_count):
            self.named_buffer_count += 1
            name_length = self.u32()
            if name_length == 0 or name_length > MAX_NAME_BYTES:
                raise self.invalid("invalid named-buffer string length", self.offset - 4)
            name = self.read(name_length)
            if name[-1] != 0 or b"\0" in name[:-1]:
                raise self.invalid("named-buffer strings require one terminal NUL byte")
            child_root, children = self.buffer(depth + 1)
            named_buffers.append(NamedBuffer(name[:-1], child_root, children))
        return root, tuple(named_buffers)


def parse_boneyard(data: bytes, label: str = "<memory>") -> Boneyard:
    reader = _Reader(data, label)
    root, named_buffers = reader.buffer()
    if reader.offset != len(data):
        raise reader.invalid("trailing data follows the SyncBuffer")

    if len(root.payload) != 0 or len(root.children) != 1:
        raise reader.invalid("the root chunk must contain exactly one arena chunk", root.offset)
    arena = root.children[0]
    if len(arena.payload) != 0 or len(arena.children) != ARENA_SECTION_COUNT:
        raise reader.invalid(
            f"the arena chunk must contain exactly {ARENA_SECTION_COUNT} sections",
            arena.offset,
        )
    region = arena.children[12]
    if len(region.payload) != 0 or len(region.children) != 1:
        raise reader.invalid(
            "the Arena Region section must contain exactly one RegionLayout chunk",
            region.offset,
        )
    region_layout = region.children[0]
    if len(region_layout.payload) != 0 or len(region_layout.children) != REGION_LAYOUT_SECTION_COUNT:
        raise reader.invalid(
            f"the RegionLayout chunk must contain exactly {REGION_LAYOUT_SECTION_COUNT} sections",
            region_layout.offset,
        )

    return Boneyard(label, data, root, named_buffers)


def load_boneyard(path: Path) -> Boneyard:
    return parse_boneyard(path.read_bytes(), str(path))


def _object_manager(section: Chunk) -> dict[str, Any] | None:
    if len(section.payload) < 4:
        return None
    count = struct.unpack_from("<I", section.payload)[0]
    if len(section.payload) != 4 + count * 4:
        return None
    type_ids = struct.unpack_from(f"<{count}I", section.payload, 4) if count else ()
    counts = Counter(type_ids)
    return {
        "count": count,
        "types": [
            {
                "id": type_id,
                "name": TYPE_NAMES.get(type_id),
                "count": type_count,
            }
            for type_id, type_count in sorted(counts.items())
        ],
    }


def summarize(boneyard: Boneyard) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    for index, (name, section) in enumerate(
        zip(REGION_LAYOUT_SECTIONS, boneyard.region_layout.children, strict=True)
    ):
        item: dict[str, Any] = {
            "index": index,
            "name": name,
            "offset": section.offset,
            "payloadBytes": len(section.payload),
            "directChildren": len(section.children),
            "subtreeChunks": section.chunk_count,
        }
        if index in OBJECT_MANAGER_SECTIONS:
            item["objectManager"] = _object_manager(section)
        elif index == 11 and len(section.payload) >= 4:
            count = struct.unpack_from("<I", section.payload)[0]
            if len(section.payload) == 4 + count * 25:
                item["recordCount"] = count
                item["recordBytes"] = 25
        sections.append(item)

    return {
        "path": boneyard.path,
        "size": len(boneyard.data),
        "sha256": hashlib.sha256(boneyard.data).hexdigest(),
        "syncBuffer": {
            "chunks": boneyard.root.chunk_count,
            "maxDepth": boneyard.root.max_depth,
            "namedBuffers": len(boneyard.named_buffers),
        },
        "arenaSections": len(boneyard.arena.children),
        "regionLayoutSections": sections,
    }


def _print_summary(summary: dict[str, Any]) -> None:
    sync = summary["syncBuffer"]
    print(summary["path"])
    print(f"  size={summary['size']} sha256={summary['sha256']}")
    print(
        f"  chunks={sync['chunks']} max_depth={sync['maxDepth']} "
        f"named_buffers={sync['namedBuffers']}"
    )
    for section in summary["regionLayoutSections"]:
        detail = ""
        manager = section.get("objectManager")
        if manager is not None:
            rendered_types = ", ".join(
                f"{item['name'] or item['id']}:{item['count']}" for item in manager["types"]
            )
            detail = f" count={manager['count']}"
            if rendered_types:
                detail += f" types=[{rendered_types}]"
        elif "recordCount" in section:
            detail = (
                f" records={section['recordCount']} "
                f"record_bytes={section['recordBytes']}"
            )
        print(
            f"  [{section['index']:02d}] {section['name']}: "
            f"payload={section['payloadBytes']} children={section['directChildren']} "
            f"subtree={section['subtreeChunks']}{detail}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    summaries: list[dict[str, Any]] = []
    failed = False
    for path in args.paths:
        try:
            summaries.append(summarize(load_boneyard(path)))
        except (OSError, BoneyardFormatError) as exception:
            failed = True
            print(str(exception), file=sys.stderr)

    if args.json:
        print(json.dumps(summaries, indent=2))
    else:
        for index, summary in enumerate(summaries):
            if index:
                print()
            _print_summary(summary)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
