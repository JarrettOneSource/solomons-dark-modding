#!/usr/bin/env python3
"""Decode and byte-exactly re-encode Solomon Dark native persistence files.

The retail game writes recursive ``SyncBuffer`` trees.  ``darkdata.cfg`` wraps
that tree in a repeating-key XOR followed by the game's marker/LZ codec; the
other binary persistence files store the tree directly.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import struct
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Iterator


SYNCBUFFER_ENDIANNESS = "little"
SYNCBUFFER_MAGIC = None
SYNCBUFFER_VERSION = None
SYNCBUFFER_MAX_DEPTH = 128
SYNCBUFFER_MAX_NODES = 1_000_000
SYNCBUFFER_MAX_BYTES = 64 * 1024 * 1024
DARKDATA_MAX_DECOMPRESSED_BYTES = 32 * 1024 * 1024
NATIVE_WIZARD_SKILL_ROW_COUNT = 83
NATIVE_HAGATHA_OWNERSHIP_COUNT = 50
NATIVE_HAGATHA_FIRST_MIX_COUNT = 30
NATIVE_GAMESTATE_ROOT_CHILD_COUNT = 8
PORTABLE_PROFILE_FORMAT = "solomon-dark-portable-profile"
PORTABLE_PROFILE_VERSION = 1
RETAIL_EXECUTABLE_SHA256 = (
    "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
)
PORTABLE_NATIVE_ATTACHMENT_MAX_BYTES = 8 * 1024 * 1024
SAFE_RUN_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
DARKDATA_KEY = (
    b'MagicEncryptionWord="SolomonDarkEncryption"'
    b"|there$w#st w&187sfj21\t89n4v 1984x98mn12xc39931c87241@@@@@@"
)
NATIVE_BOAST_STATEMENTS = (
    '"I can do this entire mission without drinking a single potion of any kind!"',
    '"A true magician does not wear magical clothing, rings, or other implements!"',
    '"The learned wizard need not cast secondary spells at all!"',
    '"A master sorceror does not choose magic, the magic chooses him!"',
    '"A profound practicioner of magic never allows his mana pool to empty!"',
)


class SaveFormatError(ValueError):
    """Raised when bytes cannot be decoded without guessing."""


@dataclass(frozen=True)
class ChunkNode:
    offset: int
    payload_offset: int
    payload: bytes
    children: tuple["ChunkNode", ...]


@dataclass(frozen=True)
class NamedBuffer:
    name: str
    name_offset: int
    buffer: "SyncBuffer"


@dataclass(frozen=True)
class SyncBuffer:
    offset: int
    root: ChunkNode
    named_buffers: tuple[NamedBuffer, ...]
    end_offset: int


@dataclass(frozen=True)
class DarkdataField:
    name: str
    file_offset: int
    size: int
    value_type: str
    runtime_offset: int | None
    semantics: str


class PayloadCursor:
    """Strict little-endian reader for one recovered native node payload."""

    def __init__(self, data: bytes, claim: str) -> None:
        self.data = data
        self.claim = claim
        self.offset = 0

    def _read(self, size: int, field: str) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise SaveFormatError(
                f"truncated {self.claim} {field} at 0x{self.offset:X}: "
                f"need {size} bytes, have {len(self.data) - self.offset}"
            )
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def u8(self, field: str) -> int:
        return self._read(1, field)[0]

    def boolean(self, field: str) -> bool:
        value = self.u8(field)
        if value not in (0, 1):
            raise SaveFormatError(
                f"{self.claim} {field} contains non-boolean byte {value}"
            )
        return bool(value)

    def u16(self, field: str) -> int:
        return struct.unpack("<H", self._read(2, field))[0]

    def u32(self, field: str) -> int:
        return struct.unpack("<I", self._read(4, field))[0]

    def i32(self, field: str) -> int:
        return struct.unpack("<i", self._read(4, field))[0]

    def f32(self, field: str) -> float:
        return struct.unpack("<f", self._read(4, field))[0]

    def i32_list(self, count: int, field: str) -> list[int]:
        if count < 0 or count > (len(self.data) - self.offset) // 4:
            raise SaveFormatError(
                f"{self.claim} {field} count {count} exceeds its payload"
            )
        return [self.i32(f"{field}[{index}]") for index in range(count)]

    def f32_list(self, count: int, field: str) -> list[float]:
        if count < 0 or count > (len(self.data) - self.offset) // 4:
            raise SaveFormatError(
                f"{self.claim} {field} count {count} exceeds its payload"
            )
        return [self.f32(f"{field}[{index}]") for index in range(count)]

    def finish(self) -> None:
        if self.offset != len(self.data):
            raise SaveFormatError(
                f"{self.claim} ended at 0x{self.offset:X} with "
                f"{len(self.data) - self.offset} unclaimed bytes"
            )


class Cursor:
    def __init__(self, data: bytes) -> None:
        if len(data) > SYNCBUFFER_MAX_BYTES:
            raise SaveFormatError(
                f"SyncBuffer input is {len(data)} bytes; limit is "
                f"{SYNCBUFFER_MAX_BYTES}"
            )
        self.data = data
        self.offset = 0
        self.node_count = 0

    def read_u32(self, claim: str) -> int:
        if self.offset + 4 > len(self.data):
            raise SaveFormatError(
                f"truncated {claim} u32 at 0x{self.offset:X}: "
                f"need 4 bytes, have {len(self.data) - self.offset}"
            )
        value = struct.unpack_from("<I", self.data, self.offset)[0]
        self.offset += 4
        return value

    def read_bytes(self, size: int, claim: str) -> bytes:
        if size < 0:
            raise SaveFormatError(f"negative {claim} byte count {size}")
        end = self.offset + size
        if end > len(self.data):
            raise SaveFormatError(
                f"truncated {claim} at 0x{self.offset:X}: "
                f"need {size} bytes, have {len(self.data) - self.offset}"
            )
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def read_string(self, claim: str) -> tuple[int, str]:
        offset = self.offset
        size = self.read_u32(f"{claim} length")
        raw = self.read_bytes(size, claim)
        if not raw or raw[-1] != 0:
            raise SaveFormatError(
                f"{claim} at 0x{offset:X} is not NUL-terminated"
            )
        try:
            return offset, raw[:-1].decode("utf-8")
        except UnicodeDecodeError as error:
            raise SaveFormatError(
                f"{claim} at 0x{offset:X} is not UTF-8: {error}"
            ) from error


def _parse_chunk(cursor: Cursor, depth: int) -> ChunkNode:
    if depth > SYNCBUFFER_MAX_DEPTH:
        raise SaveFormatError(
            f"SyncBuffer nesting exceeds {SYNCBUFFER_MAX_DEPTH} levels"
        )
    cursor.node_count += 1
    if cursor.node_count > SYNCBUFFER_MAX_NODES:
        raise SaveFormatError(
            f"SyncBuffer node count exceeds {SYNCBUFFER_MAX_NODES}"
        )
    offset = cursor.offset
    payload_size = cursor.read_u32("node payload length")
    payload_offset = cursor.offset
    payload = cursor.read_bytes(payload_size, "node payload")
    child_count = cursor.read_u32("node child count")
    remaining = len(cursor.data) - cursor.offset
    if child_count > remaining // 8:
        raise SaveFormatError(
            f"node at 0x{offset:X} declares {child_count} children but only "
            f"{remaining} bytes remain"
        )
    children = tuple(_parse_chunk(cursor, depth + 1) for _ in range(child_count))
    return ChunkNode(offset, payload_offset, payload, children)


def _parse_buffer(cursor: Cursor, depth: int) -> SyncBuffer:
    offset = cursor.offset
    root = _parse_chunk(cursor, depth)
    named_count = cursor.read_u32("named-buffer count")
    remaining = len(cursor.data) - cursor.offset
    if named_count > remaining // 13:
        raise SaveFormatError(
            f"buffer at 0x{offset:X} declares {named_count} named buffers but "
            f"only {remaining} bytes remain"
        )
    named: list[NamedBuffer] = []
    seen: set[str] = set()
    for index in range(named_count):
        name_offset, name = cursor.read_string(f"named buffer {index} name")
        if name in seen:
            raise SaveFormatError(
                f"buffer at 0x{offset:X} has ambiguous duplicate name {name!r}"
            )
        seen.add(name)
        named.append(NamedBuffer(name, name_offset, _parse_buffer(cursor, depth + 1)))
    return SyncBuffer(offset, root, tuple(named), cursor.offset)


def parse_syncbuffer(data: bytes) -> SyncBuffer:
    """Parse one complete SyncBuffer stream and refuse trailing ambiguity."""

    cursor = Cursor(data)
    result = _parse_buffer(cursor, 0)
    if cursor.offset != len(data):
        raise SaveFormatError(
            f"SyncBuffer ended at 0x{cursor.offset:X} with "
            f"{len(data) - cursor.offset} unclaimed bytes"
        )
    return result


def _encode_chunk(node: ChunkNode) -> bytes:
    return b"".join(
        (
            struct.pack("<I", len(node.payload)),
            node.payload,
            struct.pack("<I", len(node.children)),
            *(_encode_chunk(child) for child in node.children),
        )
    )


def encode_syncbuffer(buffer: SyncBuffer) -> bytes:
    names: set[str] = set()
    encoded_named: list[bytes] = []
    for item in buffer.named_buffers:
        if item.name in names:
            raise SaveFormatError(
                f"cannot encode ambiguous duplicate named buffer {item.name!r}"
            )
        names.add(item.name)
        raw_name = item.name.encode("utf-8") + b"\0"
        encoded_named.append(
            struct.pack("<I", len(raw_name))
            + raw_name
            + encode_syncbuffer(item.buffer)
        )
    return (
        _encode_chunk(buffer.root)
        + struct.pack("<I", len(encoded_named))
        + b"".join(encoded_named)
    )


def xor_darkdata(data: bytes) -> bytes:
    return bytes(value ^ DARKDATA_KEY[index % len(DARKDATA_KEY)] for index, value in enumerate(data))


def _decode_varint(data: bytes, offset: int, claim: str) -> tuple[int, int]:
    value = 0
    start = offset
    for _ in range(5):
        if offset >= len(data):
            raise SaveFormatError(f"truncated {claim} varint at 0x{start:X}")
        byte = data[offset]
        offset += 1
        if value > 0x01FFFFFF:
            raise SaveFormatError(f"overflowing {claim} varint at 0x{start:X}")
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, offset
    raise SaveFormatError(f"overlong {claim} varint at 0x{start:X}")


def decompress_darkdata(data: bytes) -> bytes:
    if not data:
        raise SaveFormatError("darkdata codec input is empty")
    marker = data[0]
    offset = 1
    output = bytearray()
    while offset < len(data):
        value = data[offset]
        offset += 1
        if value != marker:
            output.append(value)
        else:
            if offset >= len(data):
                raise SaveFormatError(
                    f"truncated marker command at 0x{offset - 1:X}"
                )
            if data[offset] == 0:
                output.append(marker)
                offset += 1
            else:
                length, offset = _decode_varint(data, offset, "match length")
                distance, offset = _decode_varint(data, offset, "match distance")
                if length == 0:
                    raise SaveFormatError("back-reference has zero length")
                if distance == 0 or distance > len(output):
                    raise SaveFormatError(
                        f"back-reference distance {distance} exceeds "
                        f"decoded prefix {len(output)}"
                    )
                if len(output) + length > DARKDATA_MAX_DECOMPRESSED_BYTES:
                    raise SaveFormatError(
                        "darkdata decompression exceeds the native 32 MiB ceiling"
                    )
                for _ in range(length):
                    output.append(output[-distance])
        if len(output) > DARKDATA_MAX_DECOMPRESSED_BYTES:
            raise SaveFormatError(
                "darkdata decompression exceeds the native 32 MiB ceiling"
            )
    return bytes(output)


def _encode_varint(value: int) -> bytes:
    if value < 0 or value > 0xFFFFFFFF:
        raise SaveFormatError(f"varint value {value} does not fit u32")
    groups = [value & 0x7F]
    value >>= 7
    while value:
        groups.append(value & 0x7F)
        value >>= 7
    groups.reverse()
    return bytes(
        group | (0x80 if index + 1 < len(groups) else 0)
        for index, group in enumerate(groups)
    )


def compress_darkdata(data: bytes) -> bytes:
    """Reproduce retail ``0x004258B0`` including its greedy tie-breaking."""

    if not data:
        return b""
    frequencies = [0] * 256
    for value in data:
        frequencies[value] += 1
    marker = min(range(256), key=lambda value: (frequencies[value], value))

    previous = [-1] * len(data)
    heads = [-1] * 65536
    for index in range(max(0, len(data) - 1)):
        key = (data[index] << 8) | data[index + 1]
        previous[index] = heads[key]
        heads[key] = index

    output = bytearray((marker,))
    position = 0
    remaining = len(data)
    while remaining > 3:
        candidate = previous[position]
        best_length = 3
        best_distance = 0
        while candidate != -1:
            distance = position - candidate
            if distance > 99_999:
                break
            if data[candidate + 3] == data[position + 3]:
                limit = min(distance, remaining)
                match_length = 2
                while (
                    match_length < limit
                    and data[candidate + match_length]
                    == data[position + match_length]
                ):
                    match_length += 1
                if match_length > best_length:
                    best_length = match_length
                    best_distance = distance
            candidate = previous[candidate]

        accept = best_length >= 8
        if best_length == 4:
            accept = best_distance <= 0x7F
        elif best_length == 5:
            accept = best_distance <= 0x3FFF
        elif best_length == 6:
            accept = best_distance <= 0x1FFFFF
        elif best_length == 7:
            accept = best_distance <= 0x0FFFFFFF

        if accept:
            output.append(marker)
            output.extend(_encode_varint(best_length))
            output.extend(_encode_varint(best_distance))
            position += best_length
            remaining -= best_length
        else:
            value = data[position]
            output.append(value)
            if value == marker:
                output.append(0)
            position += 1
            remaining -= 1

    while position < len(data):
        value = data[position]
        output.append(value)
        if value == marker:
            output.append(0)
        position += 1
    return bytes(output)


def decode_darkdata(data: bytes) -> tuple[bytes, SyncBuffer]:
    plain = xor_darkdata(decompress_darkdata(data))
    return plain, parse_syncbuffer(plain)


def encode_darkdata(buffer: SyncBuffer) -> bytes:
    return compress_darkdata(xor_darkdata(encode_syncbuffer(buffer)))


def _walk_nodes(
    node: ChunkNode, path: tuple[int, ...] = ()
) -> Iterator[tuple[tuple[int, ...], ChunkNode]]:
    yield path, node
    for index, child in enumerate(node.children):
        yield from _walk_nodes(child, path + (index,))


def _walk_buffers(
    buffer: SyncBuffer, path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], SyncBuffer]]:
    yield path, buffer
    for item in buffer.named_buffers:
        yield from _walk_buffers(item.buffer, path + (item.name,))


def buffer_to_fixture(buffer: SyncBuffer) -> dict[str, Any]:
    def node_value(node: ChunkNode) -> dict[str, Any]:
        return {
            "offset": node.offset,
            "payload_offset": node.payload_offset,
            "payload_length": len(node.payload),
            "payload_hex": node.payload.hex(),
            "children": [node_value(child) for child in node.children],
        }

    return {
        "offset": buffer.offset,
        "end_offset": buffer.end_offset,
        "root": node_value(buffer.root),
        "named_buffers": [
            {
                "name": item.name,
                "name_offset": item.name_offset,
                "buffer": buffer_to_fixture(item.buffer),
            }
            for item in buffer.named_buffers
        ],
    }


def buffer_from_fixture(value: dict[str, Any]) -> SyncBuffer:
    def parse_node(node: dict[str, Any]) -> ChunkNode:
        payload = bytes.fromhex(str(node["payload_hex"]))
        declared = int(node["payload_length"])
        if len(payload) != declared:
            raise SaveFormatError(
                f"fixture node at {node.get('offset')} declares {declared} "
                f"payload bytes but embeds {len(payload)}"
            )
        return ChunkNode(
            int(node["offset"]),
            int(node["payload_offset"]),
            payload,
            tuple(parse_node(child) for child in node["children"]),
        )

    named: list[NamedBuffer] = []
    seen: set[str] = set()
    for item in value["named_buffers"]:
        name = str(item["name"])
        if name in seen:
            raise SaveFormatError(
                f"fixture contains ambiguous duplicate named buffer {name!r}"
            )
        seen.add(name)
        named.append(
            NamedBuffer(
                name,
                int(item["name_offset"]),
                buffer_from_fixture(item["buffer"]),
            )
        )
    return SyncBuffer(
        int(value["offset"]),
        parse_node(value["root"]),
        tuple(named),
        int(value["end_offset"]),
    )


DARKDATA_CORE_FIELDS: tuple[DarkdataField, ...] = (
    DarkdataField("profile_gold", 0, 4, "i32", 0x58, "persistent profile gold"),
    *(
        DarkdataField(
            f"memorial_marker[{index}]",
            4 + index,
            1,
            "bool",
            0x90 + index,
            "Memoratorium record-8 urn-marker bit",
        )
        for index in range(10)
    ),
    DarkdataField(
        "stock_tutorial_pending",
        14,
        1,
        "bool",
        0x104,
        "stock tutorial/game-over gate",
    ),
    *(
        DarkdataField(
            f"hub_help_pending[{index}]",
            15 + index,
            1,
            "bool",
            0x9A + index,
            "durable Hub help/onboarding flag",
        )
        for index in range(10)
    ),
    *(
        DarkdataField(
            f"memorial_slot_ages[{index}]",
            25 + index * 4,
            4,
            "i32",
            0xA4 + index * 4,
            "Memoratorium Painting-slot FIFO age",
        )
        for index in range(10)
    ),
    DarkdataField(
        "portrait_age_counter",
        65,
        4,
        "i32",
        0xF4,
        "portrait age counter incremented after each raw capture",
    ),
    *(
        DarkdataField(
            f"memorial_portrait_ids[{index}]",
            69 + index * 4,
            4,
            "i32",
            0xCC + index * 4,
            "Memoratorium Painting-slot portrait id",
        )
        for index in range(10)
    ),
    DarkdataField(
        "next_portrait_index",
        109,
        4,
        "i32",
        0xF8,
        "next Portraits/portrait%d.raw index",
    ),
    DarkdataField(
        "last_portrait_index",
        113,
        4,
        "i32",
        0xFC,
        "most recently written portrait index",
    ),
    DarkdataField(
        "librarian_lace_read",
        117,
        1,
        "bool",
        0x105,
        "durable BOOK25_LACE one-shot",
    ),
)


FRESH_PROFILE_DEFAULTS: dict[str, Any] = {
    "profile_gold": 500,
    "memorial_marker": [False, True, True, True, False, True, True, False, False, True],
    "stock_tutorial_pending": True,
    "hub_help_pending": [True] * 10,
    "memorial_slot_ages": [9, 1, 0, 2, 7, 4, 3, 8, 5, 6],
    "portrait_age_counter": 1000,
    "memorial_portrait_ids": list(range(10)),
    "next_portrait_index": 100,
    "last_portrait_index": 0,
    "librarian_lace_read": False,
    "hagatha_bulk_selectors": [],
    "hagatha_first_mix_flags_before_first_serialization": [False] * 30,
    "settled_persisted_hagatha_flags": [
        index == 27 for index in range(30)
    ],
    "serializer_initialized_flag_index": 27,
    "shlorio_fee": {"minimum": 500, "maximum": 950, "step": 50},
}


def _read_field(payload: bytes, field: DarkdataField) -> int | bool:
    end = field.file_offset + field.size
    if end > len(payload):
        raise SaveFormatError(
            f"darkdata core field {field.name} needs bytes "
            f"0x{field.file_offset:X}..0x{end - 1:X}, payload has {len(payload)}"
        )
    if field.value_type == "bool":
        value = payload[field.file_offset]
        if value not in (0, 1):
            raise SaveFormatError(
                f"darkdata field {field.name} contains non-boolean byte {value}"
            )
        return bool(value)
    if field.value_type == "i32":
        return struct.unpack_from("<i", payload, field.file_offset)[0]
    raise AssertionError(f"unsupported field type {field.value_type}")


def decode_darkdata_fields(buffer: SyncBuffer) -> dict[str, Any]:
    root = buffer.root
    if root.payload:
        raise SaveFormatError(
            f"darkdata root payload is {len(root.payload)} bytes; expected zero"
        )
    if len(root.children) != 6:
        raise SaveFormatError(
            f"darkdata root has {len(root.children)} children; expected six"
        )
    core = root.children[0].payload
    if len(core) != 118:
        raise SaveFormatError(
            f"darkdata core payload is {len(core)} bytes; expected 118"
        )
    fields = [
        {
            "name": field.name,
            "payload_offset": field.file_offset,
            "payload_offset_hex": f"0x{field.file_offset:02X}",
            "size": field.size,
            "type": field.value_type,
            "runtime_offset_hex": (
                f"0x{field.runtime_offset:03X}"
                if field.runtime_offset is not None
                else None
            ),
            "value": _read_field(core, field),
            "semantics": field.semantics,
        }
        for field in DARKDATA_CORE_FIELDS
    ]

    bulk = root.children[2].payload
    if len(bulk) < 4:
        raise SaveFormatError("darkdata Hagatha selector payload is truncated")
    count = struct.unpack_from("<I", bulk, 0)[0]
    if len(bulk) != 4 + count * 4:
        raise SaveFormatError(
            f"darkdata Hagatha selector count {count} claims {4 + count * 4} "
            f"bytes but payload has {len(bulk)}"
        )
    selectors = list(struct.unpack_from(f"<{count}i", bulk, 4)) if count else []

    mix = root.children[3].payload
    if len(mix) != 30 or any(value not in (0, 1) for value in mix):
        raise SaveFormatError(
            "darkdata Hagatha first-mix payload must be 30 boolean bytes"
        )
    fee_payload = root.children[4].payload
    if len(fee_payload) != 4:
        raise SaveFormatError(
            f"darkdata Shlorio fee payload is {len(fee_payload)} bytes; expected 4"
        )
    if root.children[5].payload or root.children[5].children:
        raise SaveFormatError("darkdata reserved child 5 is no longer empty")

    return {
        "core_payload_length": len(core),
        "core_fields": fields,
        "luthacus_storage": {
            "payload_length": len(root.children[1].payload),
            "payload_hex": root.children[1].payload.hex(),
            "child_count": len(root.children[1].children),
            "status": "polymorphic inventory payload; byte-exact but semantically opaque",
        },
        "hagatha_bulk_selectors": selectors,
        "hagatha_first_mix_flags": [bool(value) for value in mix],
        "serializer_initialized_flag_index": 27,
        "shlorio_fee": struct.unpack("<i", fee_payload)[0],
        "reserved_child_5": "empty",
    }


def _decode_counted_i32_payload(payload: bytes, claim: str) -> list[int]:
    cursor = PayloadCursor(payload, claim)
    count = cursor.u32("count")
    values = cursor.i32_list(count, "values")
    cursor.finish()
    return values


def _decode_primary_stat_payload(payload: bytes) -> list[float]:
    cursor = PayloadCursor(payload, "native primary-stat vector")
    count = cursor.u32("count")
    values = cursor.f32_list(count, "values")
    cursor.finish()
    return values


def _decode_progression_collections(payload: bytes) -> dict[str, Any]:
    cursor = PayloadCursor(payload, "native progression collections")
    perk_count = cursor.u32("perk selector count")
    perk_selectors = cursor.i32_list(perk_count, "perk selectors")
    hagatha_ownership = [
        cursor.boolean(f"Hagatha ownership[{index}]")
        for index in range(NATIVE_HAGATHA_OWNERSHIP_COUNT)
    ]
    learned_count = cursor.u32("learned-order count")
    learned_order = cursor.i32_list(learned_count, "learned order")
    cursor.finish()
    return {
        "perk_selectors": perk_selectors,
        "hagatha_ownership": hagatha_ownership,
        "learned_order": learned_order,
    }


def decode_progression_node(node: ChunkNode) -> dict[str, Any]:
    """Decode the complete common ``Skills`` disk node at vslot ``+0x14``."""

    if len(node.children) != 2:
        raise SaveFormatError(
            f"native progression node has {len(node.children)} children; expected two"
        )
    cursor = PayloadCursor(node.payload, "native progression payload")
    row_count = cursor.u32("skill row count")
    if row_count != NATIVE_WIZARD_SKILL_ROW_COUNT:
        raise SaveFormatError(
            f"native wizard progression has {row_count} skill rows; "
            f"expected {NATIVE_WIZARD_SKILL_ROW_COUNT}"
        )

    descending_rows: list[dict[str, Any]] = []
    for row_id in range(row_count - 1, -1, -1):
        descending_rows.append(
            {
                "id": row_id,
                "permanent_rank": cursor.u16(f"row {row_id} permanent rank"),
                "effective_rank": cursor.u16(f"row {row_id} effective rank"),
                "current_cooldown": cursor.f32(f"row {row_id} current cooldown"),
                "cooldown_cap": cursor.f32(f"row {row_id} cooldown cap"),
            }
        )
    rows = list(reversed(descending_rows))

    result: dict[str, Any] = {
        "row_count": row_count,
        "rows": rows,
        "pending_skill_choices": cursor.i32("pending skill choices"),
        "level": cursor.i32("level"),
        "experience": cursor.f32("experience"),
        "previous_threshold": cursor.f32("previous threshold"),
        "next_threshold": cursor.f32("next threshold"),
        "global_cooldown": cursor.f32("global cooldown"),
        "unknown_0x68": cursor.f32("unknown +0x68"),
        "current_health": cursor.f32("current health"),
        "maximum_health": cursor.f32("maximum health"),
        "current_mana": cursor.f32("current mana"),
        "maximum_mana": cursor.f32("maximum mana"),
        "movement_speed": cursor.f32("movement speed"),
        "cast_speed": cursor.f32("cast speed"),
        "mana_recovery": cursor.f32("mana recovery"),
        "health_regeneration": cursor.f32("health regeneration"),
        "secondary_recharge": cursor.f32("secondary recharge"),
        "unknown_0xA0": cursor.f32("unknown +0xA0"),
        "magic_resistance": cursor.f32("magic resistance"),
        "poison_resistance": cursor.f32("poison resistance"),
        "deflect_chance": cursor.f32("deflect chance"),
        "unknown_0x14": cursor.i32("unknown +0x14"),
        "unknown_0xBC": cursor.f32("unknown +0xBC"),
        "unknown_0xC0": cursor.f32("unknown +0xC0"),
        "current_spell_id": cursor.i32("current spell id"),
    }

    integer_vector_count = cursor.u32("integer-vector count")
    result["integer_vector_0x784"] = cursor.i32_list(
        integer_vector_count, "integer vector +0x784"
    )
    result.update(
        {
            "unknown_0x7A0": cursor.f32("unknown +0x7A0"),
            "staff_damage_a": cursor.f32("staff damage A"),
            "staff_damage_b": cursor.f32("staff damage B"),
            "integers_0x7A4_0x7B8": [
                cursor.i32(f"integer +0x{0x7A4 + index * 4:X}")
                for index in range(6)
            ],
            "unknown_0xAC": cursor.f32("unknown +0xAC"),
            "unknown_0xB0": cursor.f32("unknown +0xB0"),
            "unknown_0xB4": cursor.f32("unknown +0xB4"),
            "offensive_mana_factor": cursor.f32("offensive mana factor"),
            "offensive_damage_factor": cursor.f32("offensive damage factor"),
            "pickup_range": cursor.f32("pickup range"),
            "element_root": cursor.i32("element root"),
            "discipline_root": cursor.i32("discipline root"),
            "offer_seed": cursor.i32("offer seed"),
            "skill_screen_flag": cursor.boolean("skill-screen flag +0x838"),
            "weld_offer_marker": cursor.i32("weld offer marker +0x840"),
            "offer_cycle": cursor.i32("offer cycle +0x848"),
            "deferred_skill_choices": cursor.i32("deferred skill choices"),
            "sorcerors_charm_available": cursor.boolean(
                "Sorceror action available +0x839"
            ),
            "starting_secondary": cursor.i32("starting secondary"),
        }
    )
    forced_offer_count = cursor.u32("forced-offer count")
    result["forced_offer_skill_ids"] = cursor.i32_list(
        forced_offer_count, "forced offer skill ids"
    )
    result.update(
        {
            "offensive_damage_flat": cursor.f32("offensive damage flat"),
            "mana_cost_reduction": cursor.f32("mana cost reduction"),
            "experience_bonus": cursor.f32("experience bonus"),
            "push_strength": cursor.f32("push strength"),
            "unknown_0x804": cursor.f32("unknown +0x804"),
            "unknown_0x808": cursor.f32("unknown +0x808"),
            "unknown_0x80C": cursor.f32("unknown +0x80C"),
            "unknown_0x810": cursor.f32("unknown +0x810"),
            "flag_0x814": cursor.boolean("flag +0x814"),
            "starting_primary": cursor.i32("starting primary"),
            "cheat_death_enabled": cursor.boolean("cheat-death enabled"),
            "cheat_death_charges": cursor.i32("cheat-death charges"),
            "hoarded_mana": cursor.f32("hoarded mana"),
            "experience_enabled": cursor.boolean("local experience admission +0x2C"),
            "random_boast_active": cursor.boolean("random-choice Boast +0x2D"),
            "perk_capacity": cursor.i32("perk capacity"),
            "poison_immunity_ticks": cursor.i32("poison immunity ticks"),
        }
    )
    cursor.finish()
    result["primary_stat_vector"] = _decode_primary_stat_payload(
        node.children[0].payload
    )
    result.update(_decode_progression_collections(node.children[1].payload))
    return result


def decode_wizard_disk_extension(node: ChunkNode) -> dict[str, Any]:
    if node.children:
        raise SaveFormatError("native wizard disk extension unexpectedly has children")
    cursor = PayloadCursor(node.payload, "native wizard disk extension")
    result = {
        "meditation_idle_delay": cursor.i32("Meditation idle delay"),
        "firewalker_active": cursor.boolean("Firewalker active"),
        "weld_effect": cursor.f32("weld-effect scalar"),
    }
    cursor.finish()
    return result


def decode_gamestate_local_wizard(buffer: SyncBuffer) -> dict[str, Any]:
    """Decode the structurally unique local-wizard branch in retail gamestate."""

    if buffer.named_buffers:
        raise SaveFormatError("native gamestate unexpectedly has named buffers")
    root = buffer.root
    if len(root.children) != NATIVE_GAMESTATE_ROOT_CHILD_COUNT:
        raise SaveFormatError(
            f"native gamestate root has {len(root.children)} children; "
            f"expected {NATIVE_GAMESTATE_ROOT_CHILD_COUNT}"
        )
    wizard = root.children[0]
    if len(wizard.children) < 2:
        raise SaveFormatError(
            f"native local wizard has {len(wizard.children)} children; expected at least two"
        )
    cursor = PayloadCursor(wizard.payload, "native local-wizard header")
    header_a = cursor.i32("header A")
    header_b = cursor.i32("header B")
    name_length = cursor.u32("name byte count")
    if name_length < 2 or name_length > 256:
        raise SaveFormatError(
            f"native local-wizard name length {name_length} is outside 2..256"
        )
    raw_name = cursor._read(name_length, "name")
    if raw_name[-1] != 0:
        raise SaveFormatError("native local-wizard name is not NUL-terminated")
    try:
        name = raw_name[:-1].decode("utf-8")
    except UnicodeDecodeError as error:
        raise SaveFormatError(
            f"native local-wizard name is not UTF-8: {error}"
        ) from error
    if not name:
        raise SaveFormatError("native local-wizard name is empty")
    trailing_value = cursor.i32("trailing value")
    cursor.finish()
    return {
        "node_offset": wizard.offset,
        "header_a": header_a,
        "header_b": header_b,
        "name": name,
        "name_byte_count": name_length,
        "trailing_value": trailing_value,
        "progression": decode_progression_node(wizard.children[0]),
        "wizard_extension": decode_wizard_disk_extension(wizard.children[1]),
        "opaque_sibling_count": len(wizard.children) - 2,
    }


def _darkdata_core_value_map(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        str(row["name"]): row["value"]
        for row in fields["core_fields"]
    }


def _native_retained_path_is_safe(path: str) -> bool:
    parts = path.split("/")
    return (
        0 < len(path) <= 512
        and path.lower().startswith("solomondark/")
        and path.lower() != "solomondark/darkdata.cfg"
        and path.lower() != "solomondark/settings.txt"
        and "\\" not in path
        and ":" not in path
        and not path.startswith("/")
        and not path.endswith("/")
        and all(part and part not in (".", "..") for part in parts)
        and all(
            ord(character) >= 0x20
            and not 0x7F <= ord(character) <= 0x9F
            for character in path
        )
        and not (
            len(parts) >= 4
            and parts[0].lower() == "solomondark"
            and parts[1].lower() == "savegames"
            and parts[-1].lower() == "gamestate.sav"
        )
    )


def portable_profile_from_buffers(
    darkdata_bytes: bytes,
    gamestate_bytes: bytes,
    run_name: str,
    retained_files: Iterable[tuple[str, bytes]] = (),
) -> dict[str, Any]:
    if not SAFE_RUN_NAME.fullmatch(run_name):
        raise SaveFormatError(f"native run name is unsafe: {run_name!r}")
    retained_rows: list[dict[str, Any]] = []
    retained_paths: set[str] = set()
    total_bytes = len(darkdata_bytes) + len(gamestate_bytes)
    for path, data in retained_files:
        canonical = path.lower()
        if not _native_retained_path_is_safe(path) or canonical in retained_paths:
            raise SaveFormatError(f"native retained file path is invalid: {path!r}")
        retained_paths.add(canonical)
        total_bytes += len(data)
        retained_rows.append(
            {
                "path": path,
                "base64": base64.b64encode(data).decode("ascii"),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    if len(retained_rows) > 253 or total_bytes > PORTABLE_NATIVE_ATTACHMENT_MAX_BYTES:
        raise SaveFormatError("native portable attachment exceeds the 8 MiB limit")

    _, darkdata_buffer = decode_darkdata(darkdata_bytes)
    darkdata = decode_darkdata_fields(darkdata_buffer)
    gamestate_buffer = parse_syncbuffer(gamestate_bytes)
    wizard = decode_gamestate_local_wizard(gamestate_buffer)
    boast = decode_gamestate_boast(gamestate_buffer)
    progression = wizard["progression"]
    extension = wizard["wizard_extension"]
    core = _darkdata_core_value_map(darkdata)
    permanent_ranks = [int(row["permanent_rank"]) for row in progression["rows"]]
    if not progression["experience_enabled"] or progression[
        "random_boast_active"
    ] != (boast["selected"] == 3):
        raise SaveFormatError(
            "native local wizard and Boast progression flags disagree"
        )

    portable = {
        "format": PORTABLE_PROFILE_FORMAT,
        "version": PORTABLE_PROFILE_VERSION,
        "retailExecutableSha256": RETAIL_EXECUTABLE_SHA256,
        "profile": {
            "boast": boast,
            "gold": int(core["profile_gold"]),
            "tutorialPending": bool(core["stock_tutorial_pending"]),
            "helpPending": [
                bool(core[f"hub_help_pending[{index}]"])
                for index in range(10)
            ],
            "librarianLaceRead": bool(core["librarian_lace_read"]),
            "hagathaBundleSelectors": list(darkdata["hagatha_bulk_selectors"]),
            "firstMixed": list(darkdata["hagatha_first_mix_flags"]),
            "dowsingFee": int(darkdata["shlorio_fee"]),
            "nativeStorage": {
                "payloadLength": int(darkdata["luthacus_storage"]["payload_length"]),
                "childCount": int(darkdata["luthacus_storage"]["child_count"]),
                "materializedInWeb": False,
            },
        },
        "wizard": {
            "name": wizard["name"],
            "level": int(progression["level"]),
            "experience": float(progression["experience"]),
            "previousThreshold": float(progression["previous_threshold"]),
            "nextThreshold": float(progression["next_threshold"]),
            "permanentRanks": permanent_ranks,
            "learnedOrder": list(progression["learned_order"]),
            "elementRoot": int(progression["element_root"]),
            "disciplineRoot": int(progression["discipline_root"]),
            "startingPrimary": int(progression["starting_primary"]),
            "startingSecondary": int(progression["starting_secondary"]),
            "offerSeed": int(progression["offer_seed"]),
            "pendingSkillChoices": int(progression["pending_skill_choices"]),
            "deferredSkillChoices": int(progression["deferred_skill_choices"]),
            "perkSelectors": list(progression["perk_selectors"]),
            "hagathaOwnership": list(progression["hagatha_ownership"]),
            "perkCapacity": int(progression["perk_capacity"]),
            "currentHealth": float(progression["current_health"]),
            "maximumHealth": float(progression["maximum_health"]),
            "currentMana": float(progression["current_mana"]),
            "maximumMana": float(progression["maximum_mana"]),
            "offensiveDamageFlat": float(progression["offensive_damage_flat"]),
            "manaCostReduction": float(progression["mana_cost_reduction"]),
            "experienceBonus": float(progression["experience_bonus"]),
            "cheatDeathEnabled": bool(progression["cheat_death_enabled"]),
            "cheatDeathCharges": int(progression["cheat_death_charges"]),
            "poisonImmunityTicks": int(progression["poison_immunity_ticks"]),
            "firewalkerActive": bool(extension["firewalker_active"]),
            "meditationIdleDelay": int(extension["meditation_idle_delay"]),
            "weldEffect": float(extension["weld_effect"]),
            "advancedUnlocks": [
                permanent_ranks[skill_id] > 0 for skill_id in range(72, 80)
            ],
        },
        "nativeSource": {
            "runName": run_name,
            "darkdataSha256": hashlib.sha256(darkdata_bytes).hexdigest(),
            "gamestateSha256": hashlib.sha256(gamestate_bytes).hexdigest(),
            "darkdataBase64": base64.b64encode(darkdata_bytes).decode("ascii"),
            "gamestateBase64": base64.b64encode(gamestate_bytes).decode("ascii"),
            "retainedFiles": retained_rows,
        },
        "warnings": [
            "Native Luthacus storage is retained byte-for-byte but is not materialized in the web inventory bridge.",
            "Machinimbus purchase-only unlocks are not stored by retail; only already learned advanced rows can cross.",
            "Serendipity and Reverie active-until-hurt flags are not retail disk members and start inactive after import.",
            "Retail omits Unforge base HP/MP bonuses; import rebuilds maximum vitals and preserves only the saved current/max ratios.",
            "The portable wizard starts in a settled Hub; in-flight native Arena and Region objects remain in the native attachment.",
            *(
                [f"{len(retained_rows)} opaque native slot file(s) will be retained for stock export but are not web authority."]
                if retained_rows
                else []
            ),
            *(
                ["Unknown native Hagatha ownership rows remain byte-preserved but are not materialized in web play."]
                if progression["hagatha_ownership"][8]
                or any(progression["hagatha_ownership"][28:])
                else []
            ),
        ],
    }
    validate_portable_profile(portable)
    return portable


def _require_record(value: Any, claim: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SaveFormatError(f"{claim} must be an object")
    return value


def _require_int(value: Any, claim: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SaveFormatError(f"{claim} must be an integer")
    if value < minimum or value > maximum:
        raise SaveFormatError(
            f"{claim} {value} is outside {minimum}..{maximum}"
        )
    return value


def _require_float(value: Any, claim: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SaveFormatError(f"{claim} must be numeric")
    result = float(value)
    if not (minimum <= result <= maximum):
        raise SaveFormatError(
            f"{claim} {result} is outside {minimum}..{maximum}"
        )
    return result


def _require_bool_list(value: Any, claim: str, count: int) -> list[bool]:
    if (
        not isinstance(value, list)
        or len(value) != count
        or any(not isinstance(item, bool) for item in value)
    ):
        raise SaveFormatError(f"{claim} must contain {count} booleans")
    return list(value)


def _require_int_list(
    value: Any,
    claim: str,
    maximum_count: int,
    minimum_value: int,
    maximum_value: int,
    *,
    unique: bool = False,
) -> list[int]:
    if not isinstance(value, list) or len(value) > maximum_count:
        raise SaveFormatError(f"{claim} is not a bounded array")
    result = [
        _require_int(item, f"{claim}[{index}]", minimum_value, maximum_value)
        for index, item in enumerate(value)
    ]
    if unique and len(set(result)) != len(result):
        raise SaveFormatError(f"{claim} contains duplicate values")
    return result


def _require_hagatha_outcomes(value: Any) -> list[int]:
    outcomes = _require_int_list(
        value,
        "portable perk selectors",
        11,
        0,
        27,
    )
    ordinary = [selector for selector in outcomes if selector != 27]
    if (
        8 in outcomes
        or len(set(ordinary)) != len(ordinary)
        or outcomes.count(27) > 2
    ):
        raise SaveFormatError(
            "portable perk selectors are not a native Hagatha outcome list"
        )
    return outcomes


def validate_portable_profile(value: Any) -> tuple[dict[str, Any], bytes, bytes]:
    root = _require_record(value, "portable profile")
    if root.get("format") != PORTABLE_PROFILE_FORMAT:
        raise SaveFormatError("portable profile format is not supported")
    if root.get("version") != PORTABLE_PROFILE_VERSION:
        raise SaveFormatError("portable profile version is not supported")
    if root.get("retailExecutableSha256") != RETAIL_EXECUTABLE_SHA256:
        raise SaveFormatError("portable profile retail executable identity is invalid")

    profile = _require_record(root.get("profile"), "portable profile state")
    boast = _require_record(profile.get("boast"), "portable Boast state")
    selected_boast = boast.get("selected")
    if selected_boast is not None:
        selected_boast = _require_int(
            selected_boast, "portable selected Boast", 0, 4
        )
    if not isinstance(boast.get("failed"), bool) or not isinstance(
        boast.get("succeeded"), bool
    ):
        raise SaveFormatError("portable Boast terminal state must be boolean")
    if (
        selected_boast is None
        and (boast["failed"] or boast["succeeded"])
    ) or (selected_boast == 3 and boast["failed"]) or (
        boast["failed"] and boast["succeeded"]
    ):
        raise SaveFormatError("portable Boast lifecycle is inconsistent")
    _require_int(profile.get("gold"), "portable gold", 0, 2_147_483_647)
    if not isinstance(profile.get("tutorialPending"), bool):
        raise SaveFormatError("portable Tutorial state must be boolean")
    _require_bool_list(profile.get("helpPending"), "portable help state", 10)
    if not isinstance(profile.get("librarianLaceRead"), bool):
        raise SaveFormatError("portable Lace state must be boolean")
    _require_int_list(
        profile.get("hagathaBundleSelectors"),
        "portable Hagatha bundle",
        30,
        -1,
        49,
        unique=True,
    )
    _require_bool_list(profile.get("firstMixed"), "portable first-mix state", 30)
    _require_int(profile.get("dowsingFee"), "portable Dowsing fee", 0, 2_147_483_647)

    wizard = _require_record(root.get("wizard"), "portable wizard")
    name = wizard.get("name")
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 64
        or len(name.encode("utf-8")) > 255
        or any(ord(character) < 0x20 for character in name)
    ):
        raise SaveFormatError("portable wizard name is invalid")
    _require_int(wizard.get("level"), "portable wizard level", 1, 75)
    _require_float(wizard.get("experience"), "portable wizard experience", 0, 10_000_000)
    _require_float(wizard.get("previousThreshold"), "portable previous threshold", 0, 10_000_000)
    _require_float(wizard.get("nextThreshold"), "portable next threshold", 0, 10_000_000)
    ranks = _require_int_list(
        wizard.get("permanentRanks"),
        "portable permanent ranks",
        NATIVE_WIZARD_SKILL_ROW_COUNT,
        0,
        0xFFFF,
    )
    if len(ranks) != NATIVE_WIZARD_SKILL_ROW_COUNT:
        raise SaveFormatError(
            f"portable permanent ranks must contain {NATIVE_WIZARD_SKILL_ROW_COUNT} rows"
        )
    _require_int_list(
        wizard.get("learnedOrder"),
        "portable learned order",
        72,
        8,
        79,
        unique=True,
    )
    _require_int(wizard.get("elementRoot"), "portable element root", 0, 4)
    _require_int(wizard.get("disciplineRoot"), "portable discipline root", 5, 7)
    _require_int(wizard.get("startingPrimary"), "portable starting primary", 8, 79)
    _require_int(wizard.get("startingSecondary"), "portable starting secondary", 8, 79)
    _require_int(wizard.get("offerSeed"), "portable offer seed", 0, 999_999)
    _require_int(wizard.get("pendingSkillChoices"), "portable pending choices", 0, 1_000)
    _require_int(wizard.get("deferredSkillChoices"), "portable deferred choices", 0, 1_000)
    perk_selectors = _require_hagatha_outcomes(wizard.get("perkSelectors"))
    ownership = _require_bool_list(
        wizard.get("hagathaOwnership"),
        "portable Hagatha ownership",
        NATIVE_HAGATHA_OWNERSHIP_COUNT,
    )
    perk_capacity = _require_int(
        wizard.get("perkCapacity"), "portable perk capacity", 3, 9
    )
    tonic_purchases = perk_selectors.count(27)
    ordinary_perks = set(perk_selectors) - {27}
    if (
        perk_capacity != 3 + tonic_purchases * 3
        or len(ordinary_perks) > perk_capacity
        or any(
            selector != 8 and ownership[selector] != (selector in ordinary_perks)
            for selector in range(27)
        )
        or ownership[27] != (tonic_purchases > 0)
    ):
        raise SaveFormatError(
            "portable Hagatha outcomes and ownership are inconsistent"
        )
    for key in (
        "currentHealth",
        "maximumHealth",
        "currentMana",
        "maximumMana",
        "offensiveDamageFlat",
        "manaCostReduction",
        "experienceBonus",
        "weldEffect",
    ):
        _require_float(wizard.get(key), f"portable {key}", -1_000_000, 1_000_000)
    for key in ("cheatDeathEnabled", "firewalkerActive"):
        if not isinstance(wizard.get(key), bool):
            raise SaveFormatError(f"portable {key} must be boolean")
    _require_int(wizard.get("cheatDeathCharges"), "portable cheat-death charges", 0, 1_000)
    _require_int(wizard.get("poisonImmunityTicks"), "portable poison immunity", 0, 10_000_000)
    _require_int(wizard.get("meditationIdleDelay"), "portable Meditation delay", -1, 10_000_000)
    _require_bool_list(wizard.get("advancedUnlocks"), "portable advanced unlocks", 8)

    source = _require_record(root.get("nativeSource"), "portable native source")
    run_name = source.get("runName")
    if not isinstance(run_name, str) or not SAFE_RUN_NAME.fullmatch(run_name):
        raise SaveFormatError("portable native run name is invalid")
    try:
        darkdata_bytes = base64.b64decode(
            str(source.get("darkdataBase64", "")), validate=True
        )
        gamestate_bytes = base64.b64decode(
            str(source.get("gamestateBase64", "")), validate=True
        )
    except (ValueError, TypeError) as error:
        raise SaveFormatError("portable native attachment is not valid base64") from error
    retained_values = source.get("retainedFiles")
    if not isinstance(retained_values, list) or len(retained_values) > 253:
        raise SaveFormatError("portable retained files are invalid")
    retained_paths: set[str] = set()
    retained_bytes = 0
    for index, value in enumerate(retained_values):
        file = _require_record(value, f"portable retained file {index}")
        path = file.get("path")
        encoded = file.get("base64")
        sha256 = file.get("sha256")
        if (
            not isinstance(path, str)
            or not _native_retained_path_is_safe(path)
            or path.lower() in retained_paths
            or not isinstance(encoded, str)
            or not isinstance(sha256, str)
            or not re.fullmatch(r"[a-f0-9]{64}", sha256)
        ):
            raise SaveFormatError(f"portable retained file {index} is invalid")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as error:
            raise SaveFormatError(
                f"portable retained file {index} is not valid base64"
            ) from error
        if (
            base64.b64encode(decoded).decode("ascii") != encoded
            or hashlib.sha256(decoded).hexdigest() != sha256
        ):
            raise SaveFormatError(
                f"portable retained file {index} hash is invalid"
            )
        retained_paths.add(path.lower())
        retained_bytes += len(decoded)
    if not darkdata_bytes or not gamestate_bytes:
        raise SaveFormatError("portable native attachment is empty")
    if (
        base64.b64encode(darkdata_bytes).decode("ascii")
        != source.get("darkdataBase64")
        or base64.b64encode(gamestate_bytes).decode("ascii")
        != source.get("gamestateBase64")
    ):
        raise SaveFormatError("portable native attachment base64 is not canonical")
    if (
        len(darkdata_bytes) + len(gamestate_bytes) + retained_bytes
        > PORTABLE_NATIVE_ATTACHMENT_MAX_BYTES
    ):
        raise SaveFormatError("portable native attachment exceeds the 8 MiB limit")
    if hashlib.sha256(darkdata_bytes).hexdigest() != source.get("darkdataSha256"):
        raise SaveFormatError("portable darkdata attachment hash is invalid")
    if hashlib.sha256(gamestate_bytes).hexdigest() != source.get("gamestateSha256"):
        raise SaveFormatError("portable gamestate attachment hash is invalid")
    decode_darkdata_fields(decode_darkdata(darkdata_bytes)[1])
    gamestate_buffer = parse_syncbuffer(gamestate_bytes)
    decode_gamestate_local_wizard(gamestate_buffer)
    decode_gamestate_boast(gamestate_buffer)
    return root, darkdata_bytes, gamestate_bytes


def _replace_node_child(node: ChunkNode, index: int, child: ChunkNode) -> ChunkNode:
    children = list(node.children)
    children[index] = child
    return replace(node, children=tuple(children))


def apply_portable_darkdata(buffer: SyncBuffer, portable: dict[str, Any]) -> SyncBuffer:
    decode_darkdata_fields(buffer)
    profile = portable["profile"]
    root = buffer.root
    core_node = root.children[0]
    core = bytearray(core_node.payload)
    struct.pack_into("<i", core, 0, int(profile["gold"]))
    core[14] = int(bool(profile["tutorialPending"]))
    core[15:25] = bytes(int(value) for value in profile["helpPending"])
    core[117] = int(bool(profile["librarianLaceRead"]))

    selectors = [int(value) for value in profile["hagathaBundleSelectors"]]
    bulk_payload = struct.pack("<I", len(selectors)) + b"".join(
        struct.pack("<i", value) for value in selectors
    )
    first_mix_payload = bytes(int(value) for value in profile["firstMixed"])
    fee_payload = struct.pack("<i", int(profile["dowsingFee"]))

    next_root = _replace_node_child(root, 0, replace(core_node, payload=bytes(core)))
    next_root = _replace_node_child(
        next_root, 2, replace(root.children[2], payload=bulk_payload)
    )
    next_root = _replace_node_child(
        next_root, 3, replace(root.children[3], payload=first_mix_payload)
    )
    next_root = _replace_node_child(
        next_root, 4, replace(root.children[4], payload=fee_payload)
    )
    result = replace(buffer, root=next_root)
    decode_darkdata_fields(parse_syncbuffer(encode_syncbuffer(result)))
    return result


def _progression_payload_offsets(payload: bytes) -> dict[str, int]:
    """Return offsets after structurally walking both variable inline vectors."""

    cursor = PayloadCursor(payload, "native progression offset walk")
    offsets: dict[str, int] = {}

    def mark_i32(name: str) -> None:
        offsets[name] = cursor.offset
        cursor.i32(name)

    def mark_f32(name: str) -> None:
        offsets[name] = cursor.offset
        cursor.f32(name)

    def mark_bool(name: str) -> None:
        offsets[name] = cursor.offset
        cursor.boolean(name)

    row_count = cursor.u32("row count")
    if row_count != NATIVE_WIZARD_SKILL_ROW_COUNT:
        raise SaveFormatError("native progression row count drifted")
    cursor._read(row_count * 12, "row payloads")
    mark_i32("pendingSkillChoices")
    mark_i32("level")
    mark_f32("experience")
    mark_f32("previousThreshold")
    mark_f32("nextThreshold")
    cursor._read(4 * 2, "global cooldown and unknown +0x68")
    mark_f32("currentHealth")
    mark_f32("maximumHealth")
    mark_f32("currentMana")
    mark_f32("maximumMana")
    cursor._read(4 * 13, "common scalar prefix remainder")
    integer_count = cursor.u32("integer vector count")
    cursor._read(integer_count * 4, "integer vector")
    cursor._read(4 * 9, "inline scalar/vector tail prefix")
    cursor._read(4 * 6, "unknown/offensive scalar block")
    mark_i32("elementRoot")
    mark_i32("disciplineRoot")
    mark_i32("offerSeed")
    cursor._read(1 + 4 + 4, "offer marker fields")
    mark_i32("deferredSkillChoices")
    cursor._read(1, "Sorceror action flag")
    mark_i32("startingSecondary")
    forced_count = cursor.u32("forced-offer count")
    cursor._read(forced_count * 4, "forced-offer vector")
    mark_f32("offensiveDamageFlat")
    mark_f32("manaCostReduction")
    mark_f32("experienceBonus")
    cursor._read(4 * 5, "late scalar block")
    mark_bool("flag0x814")
    mark_i32("startingPrimary")
    mark_bool("cheatDeathEnabled")
    mark_i32("cheatDeathCharges")
    cursor._read(4, "hoarded mana")
    mark_bool("experienceEnabled")
    mark_bool("randomBoastActive")
    mark_i32("perkCapacity")
    mark_i32("poisonImmunityTicks")
    cursor.finish()
    return offsets


def _native_string_span(payload: bytes, length_offset: int) -> tuple[int, str] | None:
    if length_offset < 0 or length_offset + 4 > len(payload):
        return None
    length = struct.unpack_from("<I", payload, length_offset)[0]
    start = length_offset + 4
    end = start + length
    if end > len(payload):
        return None
    if length == 0:
        return end, ""
    if payload[end - 1] != 0:
        return None
    try:
        return end, payload[start:end - 1].decode("utf-8")
    except UnicodeDecodeError:
        return None


def _native_boneyard_span(node: ChunkNode) -> tuple[int, int, str]:
    candidates: list[tuple[int, int, str]] = []
    for length_offset in range(max(0, len(node.payload) - 4)):
        span = _native_string_span(node.payload, length_offset)
        if span is not None and span[1].lower().endswith(".boneyard"):
            candidates.append((length_offset, span[0], span[1]))
    if len(candidates) != 1:
        raise SaveFormatError(
            f"native gamestate has {len(candidates)} selected Boneyard path candidates"
        )
    return candidates[0]


def _native_boast_statement(selected: int | None) -> str:
    if selected is None:
        return ""
    if selected < 0 or selected >= len(NATIVE_BOAST_STATEMENTS):
        raise SaveFormatError(f"native Boast {selected} is invalid")
    return NATIVE_BOAST_STATEMENTS[selected]


def _native_game_layout(node: ChunkNode) -> dict[str, int]:
    path_offset, path_end, _ = _native_boneyard_span(node)
    candidates: list[dict[str, int]] = []
    for selected_offset in range(max(0, path_offset - 1_024), path_offset):
        raw_selected = node.payload[selected_offset]
        if raw_selected != 0xFF and raw_selected > 4:
            continue
        selected = None if raw_selected == 0xFF else raw_selected
        boast_span = _native_string_span(node.payload, selected_offset + 1)
        if boast_span is None or boast_span[1] != _native_boast_statement(selected):
            continue
        bridge_span = _native_string_span(node.payload, boast_span[0])
        if bridge_span is None or bridge_span[0] != path_offset:
            continue
        candidates.append(
            {
                "selected_offset": selected_offset,
                "boast_end": boast_span[0],
                "bridge_end": bridge_span[0],
            }
        )
    if len(candidates) != 1:
        raise SaveFormatError(
            f"native gamestate has {len(candidates)} Boast layout candidates"
        )
    layout = candidates[0]
    post_path_span = _native_string_span(node.payload, path_end + 8)
    if post_path_span is None or post_path_span[0] + 6 > len(node.payload):
        raise SaveFormatError("native gamestate Boast tail is truncated")
    layout.update(
        {
            "path_offset": path_offset,
            "path_end": path_end,
            "failure_offset": post_path_span[0] + 4,
            "success_offset": post_path_span[0] + 5,
        }
    )
    if any(
        node.payload[layout[key]] not in (0, 1)
        for key in ("failure_offset", "success_offset")
    ):
        raise SaveFormatError("native gamestate Boast state is not boolean")
    return layout


def decode_gamestate_boast(buffer: SyncBuffer) -> dict[str, Any]:
    if len(buffer.root.children) != NATIVE_GAMESTATE_ROOT_CHILD_COUNT:
        raise SaveFormatError("native gamestate root membership is invalid")
    node = buffer.root.children[5]
    layout = _native_game_layout(node)
    raw_selected = node.payload[layout["selected_offset"]]
    selected = None if raw_selected == 0xFF else raw_selected
    failed = bool(node.payload[layout["failure_offset"]])
    succeeded = bool(node.payload[layout["success_offset"]])
    if (
        (selected is None and (failed or succeeded))
        or (selected == 3 and failed)
        or (failed and succeeded)
    ):
        raise SaveFormatError("native gamestate Boast lifecycle is inconsistent")
    return {"selected": selected, "failed": failed, "succeeded": succeeded}


def _native_string_bytes(value: str) -> bytes:
    if not value:
        return struct.pack("<I", 0)
    encoded = value.encode("utf-8") + b"\0"
    return struct.pack("<I", len(encoded)) + encoded


def _portable_game_node(node: ChunkNode, boast: dict[str, Any]) -> ChunkNode:
    selected = boast["selected"]
    failed = bool(boast["failed"])
    succeeded = bool(boast["succeeded"])
    if (
        (selected is None and (failed or succeeded))
        or (selected == 3 and failed)
        or (failed and succeeded)
    ):
        raise SaveFormatError("native Boast patch is inconsistent")
    layout = _native_game_layout(node)
    tail = bytearray(node.payload[layout["path_end"]:])
    tail[layout["failure_offset"] - layout["path_end"]] = int(failed)
    tail[layout["success_offset"] - layout["path_end"]] = int(succeeded)
    bridge = node.payload[layout["boast_end"]:layout["bridge_end"]]
    return replace(
        node,
        payload=(
            node.payload[:layout["selected_offset"]]
            + bytes([0xFF if selected is None else int(selected)])
            + _native_string_bytes(_native_boast_statement(selected))
            + bridge
            + _native_string_bytes("data\\levels\\survival.boneyard")
            + bytes(tail)
        ),
    )


def apply_portable_gamestate(buffer: SyncBuffer, portable: dict[str, Any]) -> SyncBuffer:
    existing = decode_gamestate_local_wizard(buffer)
    wizard_values = portable["wizard"]
    root = buffer.root
    wizard_node = root.children[0]
    progression_node = wizard_node.children[0]
    progression_payload = bytearray(progression_node.payload)
    offsets = _progression_payload_offsets(progression_node.payload)

    ranks = [int(value) for value in wizard_values["permanentRanks"]]
    for row_id, rank in enumerate(ranks):
        row_offset = 4 + (NATIVE_WIZARD_SKILL_ROW_COUNT - 1 - row_id) * 12
        struct.pack_into("<H", progression_payload, row_offset, rank)
        struct.pack_into("<H", progression_payload, row_offset + 2, rank)

    integer_fields = (
        "pendingSkillChoices",
        "level",
        "elementRoot",
        "disciplineRoot",
        "offerSeed",
        "deferredSkillChoices",
        "startingSecondary",
        "startingPrimary",
        "cheatDeathCharges",
        "perkCapacity",
        "poisonImmunityTicks",
    )
    for field in integer_fields:
        struct.pack_into(
            "<i", progression_payload, offsets[field], int(wizard_values[field])
        )
    float_fields = (
        "experience",
        "previousThreshold",
        "nextThreshold",
        "currentHealth",
        "maximumHealth",
        "currentMana",
        "maximumMana",
        "offensiveDamageFlat",
        "manaCostReduction",
        "experienceBonus",
    )
    for field in float_fields:
        struct.pack_into(
            "<f", progression_payload, offsets[field], float(wizard_values[field])
        )
    progression_payload[offsets["cheatDeathEnabled"]] = int(
        bool(wizard_values["cheatDeathEnabled"])
    )
    progression_payload[offsets["experienceEnabled"]] = 1
    progression_payload[offsets["randomBoastActive"]] = int(
        portable["profile"]["boast"]["selected"] == 3
    )

    collection_node = progression_node.children[1]
    perk_selectors = [int(value) for value in wizard_values["perkSelectors"]]
    ownership = bytes(int(value) for value in wizard_values["hagathaOwnership"])
    learned_order = [int(value) for value in wizard_values["learnedOrder"]]
    collection_payload = (
        struct.pack("<I", len(perk_selectors))
        + b"".join(struct.pack("<i", value) for value in perk_selectors)
        + ownership
        + struct.pack("<I", len(learned_order))
        + b"".join(struct.pack("<i", value) for value in learned_order)
    )
    next_progression = replace(
        progression_node,
        payload=bytes(progression_payload),
        children=(
            progression_node.children[0],
            replace(collection_node, payload=collection_payload),
        ),
    )

    extension_node = wizard_node.children[1]
    extension = bytearray(extension_node.payload)
    struct.pack_into("<i", extension, 0, int(wizard_values["meditationIdleDelay"]))
    extension[4] = int(bool(wizard_values["firewalkerActive"]))
    struct.pack_into("<f", extension, 5, float(wizard_values["weldEffect"]))

    name_bytes = str(wizard_values["name"]).encode("utf-8") + b"\0"
    header_payload = (
        struct.pack("<iiI", existing["header_a"], existing["header_b"], len(name_bytes))
        + name_bytes
        + struct.pack("<i", existing["trailing_value"])
    )
    wizard_children = list(wizard_node.children)
    wizard_children[0] = next_progression
    wizard_children[1] = replace(extension_node, payload=bytes(extension))
    next_wizard = replace(
        wizard_node,
        payload=header_payload,
        children=tuple(wizard_children),
    )
    next_root = _replace_node_child(root, 0, next_wizard)
    next_root = _replace_node_child(
        next_root,
        5,
        _portable_game_node(next_root.children[5], portable["profile"]["boast"]),
    )
    result = replace(buffer, root=next_root)
    decode_gamestate_local_wizard(parse_syncbuffer(encode_syncbuffer(result)))
    decode_gamestate_boast(parse_syncbuffer(encode_syncbuffer(result)))
    return result


def apply_portable_profile(value: Any) -> tuple[bytes, bytes, dict[str, Any]]:
    portable, darkdata_bytes, gamestate_bytes = validate_portable_profile(value)
    darkdata_buffer = decode_darkdata(darkdata_bytes)[1]
    gamestate_buffer = parse_syncbuffer(gamestate_bytes)
    encoded_darkdata = encode_darkdata(apply_portable_darkdata(darkdata_buffer, portable))
    encoded_gamestate = encode_syncbuffer(
        apply_portable_gamestate(gamestate_buffer, portable)
    )
    _, verified_darkdata = decode_darkdata(encoded_darkdata)
    verified_gamestate = parse_syncbuffer(encoded_gamestate)
    verified_wizard = decode_gamestate_local_wizard(verified_gamestate)
    verified_boast = decode_gamestate_boast(verified_gamestate)
    receipt = {
        "format": PORTABLE_PROFILE_FORMAT,
        "version": PORTABLE_PROFILE_VERSION,
        "runName": portable["nativeSource"]["runName"],
        "darkdataSha256": hashlib.sha256(encoded_darkdata).hexdigest(),
        "gamestateSha256": hashlib.sha256(encoded_gamestate).hexdigest(),
        "wizardName": verified_wizard["name"],
        "wizardLevel": verified_wizard["progression"]["level"],
        "boast": verified_boast,
        "retainedFileCount": len(portable["nativeSource"]["retainedFiles"]),
        "darkdataRoundTrip": encode_darkdata(verified_darkdata) == encoded_darkdata,
        "gamestateRoundTrip": (
            encode_syncbuffer(parse_syncbuffer(encoded_gamestate)) == encoded_gamestate
        ),
    }
    return encoded_darkdata, encoded_gamestate, receipt


def build_file_census(buffer: SyncBuffer) -> dict[str, Any]:
    buffers = list(_walk_buffers(buffer))
    nodes = [
        (buffer_path, node_path, node)
        for buffer_path, nested in buffers
        for node_path, node in _walk_nodes(nested.root)
    ]
    return {
        "buffer_count": len(buffers),
        "node_count": len(nodes),
        "payload_bytes": sum(len(node.payload) for _, _, node in nodes),
        "maximum_node_depth": max((len(path) for _, path, _ in nodes), default=0),
        "named_buffer_paths": ["/".join(path) or "/" for path, _ in buffers],
    }


def decode_save_bytes(data: bytes, kind: str) -> dict[str, Any]:
    if kind == "darkdata":
        plain, buffer = decode_darkdata(data)
        encoded = encode_darkdata(buffer)
        codec = {
            "kind": "xor_then_native_marker_lz",
            "compressed_marker": data[0],
            "compressed_length": len(data),
            "syncbuffer_length": len(plain),
            "xor_key_sha256": hashlib.sha256(DARKDATA_KEY).hexdigest(),
        }
        fields: dict[str, Any] | None = decode_darkdata_fields(buffer)
    elif kind in ("syncbuffer", "gamestate"):
        buffer = parse_syncbuffer(data)
        encoded = encode_syncbuffer(buffer)
        codec = {"kind": "plain_syncbuffer", "syncbuffer_length": len(data)}
        fields = (
            {
                "local_wizard": decode_gamestate_local_wizard(buffer),
                "boast": decode_gamestate_boast(buffer),
            }
            if kind == "gamestate"
            else None
        )
    else:
        raise SaveFormatError(f"unknown persistence kind {kind!r}")
    return {
        "raw_length": len(data),
        "raw_sha256": hashlib.sha256(data).hexdigest(),
        "round_trip_identical": encoded == data,
        "round_trip_sha256": hashlib.sha256(encoded).hexdigest(),
        "codec": codec,
        "census": build_file_census(buffer),
        "tree": buffer_to_fixture(buffer),
        "decoded_fields": fields,
    }


def reencode_fixture_entry(entry: dict[str, Any]) -> bytes:
    kind = entry["codec"]["kind"]
    if kind == "xor_then_native_marker_lz":
        buffer = buffer_from_fixture(entry["tree"])
        return encode_darkdata(buffer)
    if kind == "plain_syncbuffer":
        buffer = buffer_from_fixture(entry["tree"])
        return encode_syncbuffer(buffer)
    if kind == "key_value_text":
        newline = {
            "crlf": "\r\n",
            "lf": "\n",
            "cr": "\r",
            "mixed_or_none": "",
        }.get(str(entry["codec"]["newline"]))
        if newline is None or (
            newline == "" and len(entry.get("entries", [])) > 1
        ):
            raise SaveFormatError(
                "fixture text newline policy cannot reproduce multiple lines"
            )
        lines: list[str] = []
        for row in entry["entries"]:
            row_kind = row["kind"]
            if row_kind == "setting":
                lines.append(f"{row['key']}={row['value']}")
            elif row_kind == "literal":
                lines.append(str(row["text"]))
            else:
                raise SaveFormatError(
                    f"fixture contains unknown text row kind {row_kind!r}"
                )
        text = newline.join(lines)
        if entry.get("final_newline"):
            text += newline
        encoding = str(entry["codec"]["encoding"])
        return text.encode(encoding)
    if kind == "opaque":
        return bytes.fromhex(str(entry["opaque_hex"]))
    raise SaveFormatError(f"fixture contains unknown codec kind {kind!r}")


def _kind_from_path(path: Path) -> str:
    name = path.name.lower()
    if name == "darkdata.cfg":
        return "darkdata"
    if name == "gamestate.sav":
        return "gamestate"
    return "syncbuffer"


def _command_decode(args: argparse.Namespace) -> int:
    path = args.path.resolve()
    result = decode_save_bytes(path.read_bytes(), args.kind or _kind_from_path(path))
    print(json.dumps(result, indent=2, sort_keys=False))
    return 0


def _command_roundtrip(args: argparse.Namespace) -> int:
    path = args.path.resolve()
    data = path.read_bytes()
    result = decode_save_bytes(data, args.kind or _kind_from_path(path))
    if not result["round_trip_identical"]:
        raise SaveFormatError(
            f"decode/re-encode changed {path}: {result['raw_sha256']} -> "
            f"{result['round_trip_sha256']}"
        )
    print(
        json.dumps(
            {
                "path": str(path),
                "bytes": len(data),
                "sha256": result["raw_sha256"],
                "round_trip_identical": True,
            },
            indent=2,
        )
    )
    return 0


def _resolve_native_profile_root(path: Path) -> Path:
    path = path.resolve()
    candidates = (
        path,
        path / "solomondark",
        path / "savegames" / "solomondark",
    )
    for candidate in candidates:
        if (candidate / "darkdata.cfg").is_file():
            if candidate.is_symlink() or any(parent.is_symlink() for parent in candidate.parents):
                raise SaveFormatError("native profile source may not traverse a symlink")
            return candidate
    raise SaveFormatError(
        f"could not find solomondark/darkdata.cfg beneath {path}"
    )


def _resolve_native_run(profile_root: Path, requested: str | None) -> tuple[str, Path]:
    runs_root = profile_root / "savegames"
    if requested is not None:
        if not SAFE_RUN_NAME.fullmatch(requested):
            raise SaveFormatError(f"native run name is unsafe: {requested!r}")
        candidate = runs_root / requested / "gamestate.sav"
        if not candidate.is_file():
            raise SaveFormatError(f"native run {requested!r} has no gamestate.sav")
        return requested, candidate
    candidates = sorted(
        (
            child.name,
            child / "gamestate.sav",
        )
        for child in runs_root.iterdir()
        if child.is_dir()
        and not child.is_symlink()
        and SAFE_RUN_NAME.fullmatch(child.name)
        and (child / "gamestate.sav").is_file()
    ) if runs_root.is_dir() else []
    if len(candidates) != 1:
        raise SaveFormatError(
            f"native profile has {len(candidates)} resumable runs; pass --run-name"
        )
    return candidates[0]


def _atomic_write_text(path: Path, value: str) -> None:
    path = path.resolve()
    if path.exists():
        raise SaveFormatError(f"refusing to overwrite existing output {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _retained_native_files(
    profile_root: Path,
    selected_gamestate: Path,
) -> list[tuple[str, bytes]]:
    retained: list[tuple[str, bytes]] = []
    for path in sorted(profile_root.rglob("*")):
        if path.is_symlink():
            raise SaveFormatError(f"native profile contains a symlink: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(profile_root).as_posix()
        if relative.lower() == "darkdata.cfg":
            continue
        if relative.lower().endswith("/gamestate.sav"):
            if path.resolve() != selected_gamestate.resolve():
                raise SaveFormatError(
                    "native portable profile cannot retain a second gamestate run"
                )
            continue
        retained.append((f"solomondark/{relative}", path.read_bytes()))
    return retained


def _command_export_profile(args: argparse.Namespace) -> int:
    profile_root = _resolve_native_profile_root(args.path)
    run_name, gamestate_path = _resolve_native_run(profile_root, args.run_name)
    portable = portable_profile_from_buffers(
        (profile_root / "darkdata.cfg").read_bytes(),
        gamestate_path.read_bytes(),
        run_name,
        _retained_native_files(profile_root, gamestate_path),
    )
    encoded = json.dumps(portable, indent=2, sort_keys=False) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        _atomic_write_text(args.output, encoded)
        print(
            json.dumps(
                {
                    "output": str(args.output.resolve()),
                    "runName": run_name,
                    "wizardName": portable["wizard"]["name"],
                    "wizardLevel": portable["wizard"]["level"],
                },
                indent=2,
            )
        )
    return 0


def _command_apply_profile(args: argparse.Namespace) -> int:
    source = args.path.resolve()
    if source.stat().st_size > 16 * 1024 * 1024:
        raise SaveFormatError("portable profile JSON exceeds 16 MiB")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SaveFormatError(f"portable profile is not valid UTF-8 JSON: {error}") from error
    portable, _, _ = validate_portable_profile(value)
    darkdata_bytes, gamestate_bytes, receipt = apply_portable_profile(portable)
    output = args.output.resolve()
    if output.exists():
        raise SaveFormatError(f"refusing to replace existing output directory {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent)
    )
    try:
        profile_root = temporary / "solomondark"
        run_root = profile_root / "savegames" / receipt["runName"]
        run_root.mkdir(parents=True)
        (profile_root / "darkdata.cfg").write_bytes(darkdata_bytes)
        (run_root / "gamestate.sav").write_bytes(gamestate_bytes)
        for file in portable["nativeSource"]["retainedFiles"]:
            relative = Path(*str(file["path"]).split("/")[1:])
            retained_path = profile_root / relative
            retained_path.parent.mkdir(parents=True, exist_ok=True)
            retained_path.write_bytes(
                base64.b64decode(str(file["base64"]), validate=True)
            )
        (temporary / "portable-profile-receipt.json").write_text(
            json.dumps(receipt, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    print(json.dumps({"output": str(output), **receipt}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("decode", _command_decode), ("roundtrip", _command_roundtrip)):
        child = subparsers.add_parser(name)
        child.add_argument("path", type=Path)
        child.add_argument(
            "--kind", choices=("darkdata", "gamestate", "syncbuffer")
        )
        child.set_defaults(handler=handler)
    export_profile = subparsers.add_parser(
        "export-profile",
        help="strictly decode one native profile/current wizard into portable JSON",
    )
    export_profile.add_argument("path", type=Path)
    export_profile.add_argument("--run-name")
    export_profile.add_argument("--output", type=Path)
    export_profile.set_defaults(handler=_command_export_profile)

    apply_profile = subparsers.add_parser(
        "apply-profile",
        help="apply portable JSON to its preserved native base in a new savegames tree",
    )
    apply_profile.add_argument("path", type=Path)
    apply_profile.add_argument("--output", type=Path, required=True)
    apply_profile.set_defaults(handler=_command_apply_profile)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except SaveFormatError as error:
        raise SystemExit(f"save-format error: {error}") from error


if __name__ == "__main__":
    raise SystemExit(main())
