#!/usr/bin/env python3
"""Byte-faithful bridge from the shipped Python decoders to the web asset build."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = REPO_ROOT / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import decode_boneyard_scripts  # noqa: E402
import extract_bundles  # noqa: E402
import inspect_boneyard  # noqa: E402


PLACEABLE_TYPES = {
    2001: ("Tree", 5),
    2009: ("Monument", 2),
    2029: ("Gravestone", 20),
    2040: ("Building", 2),
    2061: ("Goodie", 12),
}


class AssetDecodeError(ValueError):
    """Raised when retail bytes do not match a documented recovered layout."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def finite(values: list[float], label: str) -> list[float]:
    if not all(math.isfinite(value) for value in values):
        raise AssetDecodeError(f"{label}: non-finite float")
    return values


def chunk_bytes(chunk: inspect_boneyard.Chunk) -> bytes:
    return b"".join(
        (
            struct.pack("<I", len(chunk.payload)),
            chunk.payload,
            struct.pack("<I", len(chunk.children)),
            *(chunk_bytes(child) for child in chunk.children),
        )
    )


def preserved_chunk(chunk: inspect_boneyard.Chunk) -> dict[str, Any]:
    encoded = chunk_bytes(chunk)
    return {
        "sourceOffset": chunk.offset,
        "sourceLength": len(encoded),
        "sourceBytesSha256": sha256(encoded),
        "rawBase64": b64(encoded),
    }


def provenance(filename: str, record_index: int, data: bytes) -> dict[str, Any]:
    return {
        "sourceBundleFilename": filename,
        "recordIndex": record_index,
        "sourceBytesSha256": sha256(data),
    }


def require_length(data: bytes, length: int, label: str, offset: int) -> None:
    if len(data) != length:
        raise AssetDecodeError(
            f"{label} at byte {offset}: expected {length} bytes, found {len(data)}"
        )


def require_no_children(
    chunk: inspect_boneyard.Chunk,
    label: str,
) -> None:
    if chunk.children:
        raise AssetDecodeError(
            f"{label} at byte {chunk.offset}: expected no child chunks, "
            f"found {len(chunk.children)}"
        )


def decode_bundle(source: dict[str, Any]) -> dict[str, Any]:
    name = source["name"]
    source_path = Path(source["path"])
    relative_path = source["relativePath"]
    data = source_path.read_bytes()
    records, groups = extract_bundles.parse_bundle(source_path)

    decoded_records: list[dict[str, Any]] = []
    for record_index, record in enumerate(records):
        record_data = data[record.offset : record.end]
        points = [
            list(
                finite(
                    list(struct.unpack_from("<2f", data, record.offset + 45 + point * 8)),
                    f"{relative_path} record {record_index} point {point}",
                )
            )
            for point in range(record.point_count)
        ]
        decoded_records.append(
            {
                "recordIndex": record_index,
                "sourceOffset": record.offset,
                "sourceLength": record.end - record.offset,
                "x": record.x,
                "y": record.y,
                "width": record.width,
                "height": record.height,
                "logicalWidth": record.logical_width,
                "logicalHeight": record.logical_height,
                "contentWidth": record.content_width,
                "contentHeight": record.content_height,
                "centerOffsetX": record.center_offset_x,
                "centerOffsetY": record.center_offset_y,
                "rotated": bool(record.rotated),
                "points": points,
                "sourceBytesSha256": sha256(record_data),
            }
        )

    glyph_total = sum(group.glyph_count for group in groups)
    direct_count = len(records) - glyph_total
    if direct_count < 0:
        raise AssetDecodeError(f"{relative_path}: auxiliary glyph count exceeds records")
    decoded_groups: list[dict[str, Any]] = []
    first_record = direct_count
    for group_index, group in enumerate(groups):
        next_group = groups[group_index + 1] if group_index + 1 < len(groups) else None
        group_end = len(data) if next_group is None else next_group.offset
        group_data = data[group.offset : group_end]
        last_record = first_record + group.glyph_count - 1
        if group.glyph_count == 0:
            raise AssetDecodeError(
                f"{relative_path} auxiliary group {group_index} at byte {group.offset} "
                "contains no glyph records"
            )
        decoded_groups.append(
            {
                "groupIndex": group_index,
                "sourceOffset": group.offset,
                "sourceLength": group_end - group.offset,
                "sourceBytesSha256": sha256(group_data),
                "firstRecord": first_record,
                "lastRecord": last_record,
                "metrics": list(group.header),
                "kerningPairs": [
                    {
                        "leftGlyphId": left,
                        "rightGlyphId": right,
                        "adjustment": adjustment,
                    }
                    for left, right, adjustment in group.kerning_pairs
                ],
                "glyphIds": list(group.glyph_ids),
            }
        )
        first_record = last_record + 1
    if first_record != len(records):
        raise AssetDecodeError(
            f"{relative_path}: auxiliary groups account for records through "
            f"{first_record - 1}, but parser returned {len(records)} records"
        )
    return {
        "name": name,
        "relativePath": relative_path,
        "bytes": len(data),
        "sha256": sha256(data),
        "records": decoded_records,
        "fontGroups": decoded_groups,
    }


def decode_native_string(data: bytes, label: str) -> tuple[str, int]:
    if len(data) < 4:
        raise AssetDecodeError(f"{label}: native String is truncated")
    size = struct.unpack_from("<I", data)[0]
    end = 4 + size
    if size == 0 or end > len(data):
        raise AssetDecodeError(f"{label}: native String length {size} is invalid")
    raw = data[4:end]
    if raw[-1] != 0 or b"\0" in raw[:-1]:
        raise AssetDecodeError(f"{label}: native String lacks one terminal NUL")
    try:
        return raw[:-1].decode("utf-8"), end
    except UnicodeDecodeError as error:
        raise AssetDecodeError(f"{label}: native String is not UTF-8") from error


def decode_arena_header(chunk: inspect_boneyard.Chunk, filename: str) -> dict[str, Any]:
    require_no_children(chunk, f"{filename} Arena section 0")
    name, cursor = decode_native_string(chunk.payload, f"{filename} Arena section 0")
    remaining = len(chunk.payload) - cursor
    if remaining not in (535, 536):
        raise AssetDecodeError(
            f"{filename} Arena section 0 at byte {chunk.offset}: expected 535 or "
            f"536 bytes after the native String, found {remaining}"
        )
    flags = list(chunk.payload[cursor : cursor + 6])
    compatibility = chunk.payload[cursor + 6 : cursor + 518]
    environment = chunk.payload[cursor + 518]
    bounds = finite(
        list(struct.unpack_from("<4f", chunk.payload, cursor + 519)),
        f"{filename} Arena bounds",
    )
    trailer = chunk.payload[cursor + 535 :]
    return {
        "levelName": name,
        "flags": flags,
        "arenaRuleMode": flags[2],
        "sessionFlag": flags[5],
        "compatibilityBlockBase64": b64(compatibility),
        "environmentMode": environment,
        "bounds": bounds,
        "savePathTrailer": None if not trailer else trailer[0],
        **preserved_chunk(chunk),
    }


def decode_common_a(chunk: inspect_boneyard.Chunk, label: str) -> dict[str, Any]:
    require_length(chunk.payload, 41, f"{label} common A", chunk.offset)
    require_no_children(chunk, f"{label} common A")
    values = finite(
        list(struct.unpack_from("<7f", chunk.payload, 0)),
        f"{label} common A",
    )
    return {
        "position": values[0:2],
        "secondaryState": values[2:4],
        "baseLifetime": values[4],
        "stateScalar": values[5],
        "radius": values[6],
        "stateValue0": struct.unpack_from("<I", chunk.payload, 0x1C)[0],
        "stateFlag": chunk.payload[0x20],
        "stateValue1": struct.unpack_from("<I", chunk.payload, 0x21)[0],
        "commonFlags": struct.unpack_from("<I", chunk.payload, 0x25)[0],
        **preserved_chunk(chunk),
    }


def decode_common_b(chunk: inspect_boneyard.Chunk, label: str) -> dict[str, Any]:
    require_length(chunk.payload, 101, f"{label} common B", chunk.offset)
    if chunk.children:
        raise AssetDecodeError(
            f"{label} common B at byte {chunk.offset}: smart-action manager has "
            f"{len(chunk.children)} unsupported child record(s)"
        )
    smart_action_count = struct.unpack_from("<I", chunk.payload, 0x55)[0]
    if smart_action_count != 0:
        raise AssetDecodeError(
            f"{label} common B at byte {chunk.offset}: smart-action manager declares "
            f"{smart_action_count} unsupported record(s)"
        )
    return {
        "stateByte": chunk.payload[0],
        "stateU16": struct.unpack_from("<H", chunk.payload, 1)[0],
        "categoryFlags": struct.unpack_from("<I", chunk.payload, 3)[0],
        "stateFlag0": chunk.payload[7],
        "commonState": finite(
            list(struct.unpack_from("<6f", chunk.payload, 8)),
            f"{label} common B commonState",
        ),
        "colorScale0": finite(
            list(struct.unpack_from("<4f", chunk.payload, 0x20)),
            f"{label} common B colorScale0",
        ),
        "stateFlag1": chunk.payload[0x30],
        "drawSortYAdjustment": struct.unpack_from("<f", chunk.payload, 0x31)[0],
        "lightingScalar": struct.unpack_from("<f", chunk.payload, 0x35)[0],
        "stateFlags": list(chunk.payload[0x39:0x3D]),
        "stateValue0": struct.unpack_from("<I", chunk.payload, 0x3D)[0],
        "stateScalar": struct.unpack_from("<f", chunk.payload, 0x41)[0],
        "colorScale1": finite(
            list(struct.unpack_from("<4f", chunk.payload, 0x45)),
            f"{label} common B colorScale1",
        ),
        "smartActionCount": smart_action_count,
        "stateValue1": struct.unpack_from("<I", chunk.payload, 0x59)[0],
        "stateValue2": struct.unpack_from("<I", chunk.payload, 0x5D)[0],
        "stateValue3": struct.unpack_from("<I", chunk.payload, 0x61)[0],
        **preserved_chunk(chunk),
    }


def decode_placeable_subclass(
    type_id: int,
    chunk: inspect_boneyard.Chunk,
    label: str,
) -> dict[str, Any]:
    type_name, expected_length = PLACEABLE_TYPES[type_id]
    require_length(chunk.payload, expected_length, label, chunk.offset)
    require_no_children(chunk, label)
    if type_id == 2001:
        fields = {
            "variant": struct.unpack_from("<H", chunk.payload, 0)[0],
            "secondaryVariant": struct.unpack_from("<H", chunk.payload, 2)[0],
            "secondaryVisible": chunk.payload[4],
        }
    elif type_id in (2009, 2040):
        fields = {"variant": struct.unpack_from("<H", chunk.payload, 0)[0]}
    elif type_id == 2029:
        fields = {
            "variant": struct.unpack_from("<H", chunk.payload, 0)[0],
            "overlayVariant": struct.unpack_from("<H", chunk.payload, 2)[0],
            "tint": finite(
                list(struct.unpack_from("<4f", chunk.payload, 4)),
                f"{label} tint",
            ),
        }
    elif type_id == 2061:
        fields = {
            "subtype": struct.unpack_from("<H", chunk.payload, 0)[0],
            "phase": chunk.payload[2],
            "active": chunk.payload[3],
            "timer": struct.unpack_from("<I", chunk.payload, 4)[0],
            "rewardSeed": struct.unpack_from("<I", chunk.payload, 8)[0],
        }
    else:
        raise AssertionError(f"unhandled placeable type {type_id}")
    return {
        "nativeTypeId": type_id,
        "nativeTypeName": type_name,
        **fields,
        **preserved_chunk(chunk),
    }


def decode_object_manager(
    section: inspect_boneyard.Chunk,
    filename: str,
) -> list[dict[str, Any]]:
    if len(section.payload) < 4:
        raise AssetDecodeError(
            f"{filename} world-object manager at byte {section.offset}: missing count"
        )
    count = struct.unpack_from("<I", section.payload)[0]
    require_length(
        section.payload,
        4 + count * 4,
        f"{filename} world-object manager",
        section.offset,
    )
    if len(section.children) != count * 3:
        raise AssetDecodeError(
            f"{filename} world-object manager at byte {section.offset}: {count} records "
            f"require {count * 3} chunks, found {len(section.children)}"
        )
    type_ids = struct.unpack_from(f"<{count}I", section.payload, 4) if count else ()
    output: list[dict[str, Any]] = []
    for index, type_id in enumerate(type_ids):
        if type_id not in PLACEABLE_TYPES:
            raise AssetDecodeError(
                f"{filename} world-object record {index} at byte "
                f"{section.children[index * 3].offset}: native type {type_id} is Not Yet Reversed"
            )
        chunks = section.children[index * 3 : index * 3 + 3]
        raw = b"".join(chunk_bytes(chunk) for chunk in chunks)
        label = f"{filename} world-object record {index} type {type_id}"
        output.append(
            {
                "recordIndex": index,
                "commonA": decode_common_a(chunks[0], label),
                "commonB": decode_common_b(chunks[1], label),
                "subclass": decode_placeable_subclass(type_id, chunks[2], label),
                "provenance": provenance(filename, index, raw),
                "sourceOffset": chunks[0].offset,
                "sourceLength": len(raw),
                "rawBase64": b64(raw),
            }
        )
    return output


def decode_single_chunk_manager(
    section: inspect_boneyard.Chunk,
    filename: str,
    expected_type: int,
    label: str,
) -> tuple[inspect_boneyard.Chunk, ...]:
    if len(section.payload) < 4:
        raise AssetDecodeError(f"{filename} {label} at byte {section.offset}: missing count")
    count = struct.unpack_from("<I", section.payload)[0]
    require_length(section.payload, 4 + count * 4, f"{filename} {label}", section.offset)
    type_ids = struct.unpack_from(f"<{count}I", section.payload, 4) if count else ()
    for index, type_id in enumerate(type_ids):
        if type_id != expected_type:
            raise AssetDecodeError(
                f"{filename} {label} record {index} at byte {section.offset}: "
                f"expected native type {expected_type}, found {type_id}"
            )
    if len(section.children) != count:
        raise AssetDecodeError(
            f"{filename} {label} at byte {section.offset}: {count} records require "
            f"{count} chunks, found {len(section.children)}"
        )
    return section.children


def point2(data: bytes, offset: int, label: str) -> list[float]:
    return finite(list(struct.unpack_from("<2f", data, offset)), label)


def decode_roads(section: inspect_boneyard.Chunk, filename: str) -> list[dict[str, Any]]:
    children = decode_single_chunk_manager(section, filename, 3004, "Road manager")
    output: list[dict[str, Any]] = []
    for index, child in enumerate(children):
        label = f"{filename} Road record {index}"
        require_length(child.payload, 69, label, child.offset)
        require_no_children(child, label)
        raw = chunk_bytes(child)
        output.append(
            {
                "points": [point2(child.payload, 0, label), point2(child.payload, 8, label)],
                "uid": struct.unpack_from("<I", child.payload, 0x10)[0],
                "previousUid": struct.unpack_from("<I", child.payload, 0x14)[0],
                "nextUid": struct.unpack_from("<I", child.payload, 0x18)[0],
                "quad": [point2(child.payload, 0x1C + offset * 8, label) for offset in range(4)],
                "style": child.payload[0x3C],
                "startWidthScale": struct.unpack_from("<f", child.payload, 0x3D)[0],
                "endWidthScale": struct.unpack_from("<f", child.payload, 0x41)[0],
                "provenance": provenance(filename, index, raw),
                **preserved_chunk(child),
            }
        )
    return output


def decode_fences(section: inspect_boneyard.Chunk, filename: str) -> list[dict[str, Any]]:
    children = decode_single_chunk_manager(section, filename, 3005, "Fence manager")
    output: list[dict[str, Any]] = []
    for index, child in enumerate(children):
        label = f"{filename} Fence record {index}"
        require_length(child.payload, 29, label, child.offset)
        require_no_children(child, label)
        raw = chunk_bytes(child)
        output.append(
            {
                "points": [point2(child.payload, 0, label), point2(child.payload, 8, label)],
                "uid": struct.unpack_from("<I", child.payload, 0x10)[0],
                "startPostVariant": struct.unpack_from("<I", child.payload, 0x14)[0],
                "endPostVariant": struct.unpack_from("<I", child.payload, 0x18)[0],
                "segmentCode": child.payload[0x1C],
                "provenance": provenance(filename, index, raw),
                **preserved_chunk(child),
            }
        )
    return output


def decode_terrain(section: inspect_boneyard.Chunk, filename: str) -> list[dict[str, Any]]:
    children = decode_single_chunk_manager(section, filename, 3009, "Terrain manager")
    output: list[dict[str, Any]] = []
    for index, child in enumerate(children):
        label = f"{filename} Terrain record {index}"
        require_no_children(child, label)
        data = child.payload
        if len(data) < 28:
            raise AssetDecodeError(f"{label} at byte {child.offset}: payload is truncated")
        style, reserved, point_count = struct.unpack_from("<3I", data)
        cursor = 12
        point_bytes = point_count * 8
        if cursor + point_bytes + 8 > len(data):
            raise AssetDecodeError(f"{label} at byte {child.offset}: point array is truncated")
        points = [point2(data, cursor + point * 8, label) for point in range(point_count)]
        cursor += point_bytes
        uid, profile_count = struct.unpack_from("<2I", data, cursor)
        cursor += 8
        expected_length = cursor + profile_count * 4 + 4
        require_length(data, expected_length, label, child.offset)
        profile = finite(
            list(struct.unpack_from(f"<{profile_count}f", data, cursor)) if profile_count else [],
            f"{label} profile",
        )
        cursor += profile_count * 4
        side_sign = struct.unpack_from("<f", data, cursor)[0]
        finite([side_sign], f"{label} sideSign")
        raw = chunk_bytes(child)
        output.append(
            {
                "style": style,
                "reserved": reserved,
                "points": points,
                "uid": uid,
                "profileSamples": profile,
                "sideSign": side_sign,
                "provenance": provenance(filename, index, raw),
                **preserved_chunk(child),
            }
        )
    return output


def decode_compact(section: inspect_boneyard.Chunk, filename: str) -> list[dict[str, Any]]:
    require_no_children(section, f"{filename} compact-decoration section")
    if len(section.payload) < 4:
        raise AssetDecodeError(
            f"{filename} compact-decoration section at byte {section.offset}: missing count"
        )
    count = struct.unpack_from("<I", section.payload)[0]
    require_length(
        section.payload,
        4 + count * 25,
        f"{filename} compact-decoration section",
        section.offset,
    )
    output: list[dict[str, Any]] = []
    for index in range(count):
        offset = 4 + index * 25
        raw = section.payload[offset : offset + 25]
        atlas_entry = struct.unpack_from("<I", raw)[0]
        if atlas_entry > 30:
            raise AssetDecodeError(
                f"{filename} compact-decoration record {index} at byte "
                f"{section.offset + 8 + offset}: atlas entry {atlas_entry} exceeds 30"
            )
        values = finite(list(struct.unpack_from("<5f", raw, 4)), f"{filename} compact {index}")
        output.append(
            {
                "atlasEntry": atlas_entry,
                "deadHawgEntry": 114 + atlas_entry,
                "position": values[0:2],
                "rotationDeg": values[2],
                "scale": values[3],
                "alpha": values[4],
                "flags": raw[24],
                "provenance": provenance(filename, index, raw),
                "sourceOffset": section.offset + 8 + offset,
                "sourceLength": len(raw),
                "rawBase64": b64(raw),
            }
        )
    return output


def decode_region_geometry(section: inspect_boneyard.Chunk, filename: str) -> dict[str, Any]:
    require_length(section.payload, 12, f"{filename} region geometry", section.offset)
    require_no_children(section, f"{filename} region geometry")
    values = finite(list(struct.unpack("<3f", section.payload)), f"{filename} region geometry")
    return {
        "playerSpawn": values[0:2],
        "playerSpawnFacingDeg": values[2],
        **preserved_chunk(section),
    }


def decode_layout_flag(section: inspect_boneyard.Chunk, filename: str) -> dict[str, Any]:
    require_length(section.payload, 1, f"{filename} layout flag", section.offset)
    require_no_children(section, f"{filename} layout flag")
    return {"value": section.payload[0], **preserved_chunk(section)}


def recipe_provenance(
    section: inspect_boneyard.Chunk,
    filename: str,
    expected_type: int,
    records: list[dict[str, Any]],
    label: str,
) -> list[dict[str, Any]]:
    children = decode_single_chunk_manager(section, filename, expected_type, label)
    if len(children) != len(records):
        raise AssetDecodeError(
            f"{filename} {label}: semantic decoder returned {len(records)} records for "
            f"{len(children)} source chunks"
        )
    output: list[dict[str, Any]] = []
    for index, (record, child) in enumerate(zip(records, children, strict=True)):
        raw = chunk_bytes(child)
        output.append(
            {
                **record,
                "provenance": provenance(filename, index, raw),
                **preserved_chunk(child),
            }
        )
    return output


def decode_boneyard(source: dict[str, Any], record_index: int) -> dict[str, Any]:
    path = Path(source["path"])
    filename = source["relativePath"]
    data = path.read_bytes()
    parsed = inspect_boneyard.parse_boneyard(data, filename)
    semantic = decode_boneyard_scripts.decode_boneyard(path)
    region = parsed.region_layout.children
    recipes = semantic.pop("recipes")
    semantic.pop("path", None)
    semantic.pop("size", None)
    semantic.pop("sha256", None)
    arena_sections = parsed.arena.children
    if len(arena_sections) != 13 or len(region) != 14:
        raise AssetDecodeError(f"{filename}: validated envelope changed after parsing")
    return {
        "filename": filename,
        "bytes": len(data),
        "provenance": provenance(filename, record_index, data),
        "sourceFileBase64": b64(data),
        "arena": {
            "header": decode_arena_header(arena_sections[0], filename),
            "preservedSections": [
                {"sectionIndex": index, **preserved_chunk(arena_sections[index])}
                for index in range(1, 12)
            ],
        },
        "layout": {
            "worldObjects": decode_object_manager(region[0], filename),
            "regionGeometry": decode_region_geometry(region[2], filename),
            "roads": decode_roads(region[5], filename),
            "fences": decode_fences(region[6], filename),
            "layoutFlag": decode_layout_flag(region[10], filename),
            "compactDecorations": decode_compact(region[11], filename),
            "terrain": decode_terrain(region[12], filename),
        },
        "triggerControl": semantic["triggerControl"],
        "timelines": semantic["timelines"],
        "scriptProvenance": {
            "triggerControl": preserved_chunk(region[1]),
            "timelines": preserved_chunk(region[13]),
        },
        "recipes": {
            "monsterRecipes": recipe_provenance(
                region[3], filename, 6001, recipes["monsterRecipes"], "MonsterRecipe manager"
            ),
            "uidGroups": recipe_provenance(
                region[4], filename, 6002, recipes["uidGroups"], "UIDGroup manager"
            ),
            "itemRecipes": recipe_provenance(
                region[7], filename, 6003, recipes["itemRecipes"], "ItemRecipe manager"
            ),
            "itemSets": recipe_provenance(
                region[8], filename, 6005, recipes["itemSets"], "ItemSet manager"
            ),
            "npcRecipes": recipe_provenance(
                region[9], filename, 6004, recipes["npcRecipes"], "NPCRecipe manager"
            ),
        },
    }


def main() -> int:
    try:
        request = json.load(sys.stdin)
        command = request.get("command")
        sources = request.get("sources")
        if not isinstance(sources, list) or not sources:
            raise AssetDecodeError("bridge request must contain a non-empty sources array")
        if command == "bundles":
            result: Any = [decode_bundle(source) for source in sources]
        elif command == "boneyards":
            result = [decode_boneyard(source, index) for index, source in enumerate(sources)]
        else:
            raise AssetDecodeError(f"unsupported bridge command: {command!r}")
        json.dump(result, sys.stdout, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        sys.stdout.write("\n")
        return 0
    except (
        AssetDecodeError,
        decode_boneyard_scripts.ScriptDecodeError,
        extract_bundles.BundleFormatError,
        inspect_boneyard.BoneyardFormatError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        print(f"asset decode failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
