#!/usr/bin/env python3
"""Decode and byte-exactly re-encode Solomon Dark native persistence files.

The retail game writes recursive ``SyncBuffer`` trees.  ``darkdata.cfg`` wraps
that tree in a repeating-key XOR followed by the game's marker/LZ codec; the
other binary persistence files store the tree directly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator


SYNCBUFFER_ENDIANNESS = "little"
SYNCBUFFER_MAGIC = None
SYNCBUFFER_VERSION = None
SYNCBUFFER_MAX_DEPTH = 128
SYNCBUFFER_MAX_NODES = 1_000_000
SYNCBUFFER_MAX_BYTES = 64 * 1024 * 1024
DARKDATA_MAX_DECOMPRESSED_BYTES = 32 * 1024 * 1024
DARKDATA_KEY = (
    b'MagicEncryptionWord="SolomonDarkEncryption"'
    b"|there$w#st w&187sfj21\t89n4v 1984x98mn12xc39931c87241@@@@@@"
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
            f"class_available[{index}]",
            4 + index,
            1,
            "bool",
            0x90 + index,
            "class availability flag; selector identity not yet reversed",
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
            f"class_enabled[{index}]",
            15 + index,
            1,
            "bool",
            0x9A + index,
            "class selection flag; selector identity not yet reversed",
        )
        for index in range(10)
    ),
    *(
        DarkdataField(
            f"class_display_order[{index}]",
            25 + index * 4,
            4,
            "i32",
            0xA4 + index * 4,
            "class selector permutation; names not yet reversed",
        )
        for index in range(10)
    ),
    DarkdataField(
        "profile_stat_0xf4",
        65,
        4,
        "i32",
        0xF4,
        "opaque profile statistic; default 1000",
    ),
    *(
        DarkdataField(
            f"class_canonical_order[{index}]",
            69 + index * 4,
            4,
            "i32",
            0xCC + index * 4,
            "class selector permutation; names not yet reversed",
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
        "profile_flag_0x105",
        117,
        1,
        "bool",
        0x105,
        "opaque profile flag",
    ),
)


FRESH_PROFILE_DEFAULTS: dict[str, Any] = {
    "profile_gold": 500,
    "class_available": [False, True, True, True, False, True, True, False, False, True],
    "stock_tutorial_pending": True,
    "class_enabled": [True] * 10,
    "class_display_order": [9, 1, 0, 2, 7, 4, 3, 8, 5, 6],
    "profile_stat_0xf4": 1000,
    "class_canonical_order": list(range(10)),
    "next_portrait_index": 100,
    "last_portrait_index": 0,
    "profile_flag_0x105": False,
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
    elif kind == "syncbuffer":
        buffer = parse_syncbuffer(data)
        encoded = encode_syncbuffer(buffer)
        codec = {"kind": "plain_syncbuffer", "syncbuffer_length": len(data)}
        fields = None
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
    return "darkdata" if path.name.lower() == "darkdata.cfg" else "syncbuffer"


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("decode", _command_decode), ("roundtrip", _command_roundtrip)):
        child = subparsers.add_parser(name)
        child.add_argument("path", type=Path)
        child.add_argument("--kind", choices=("darkdata", "syncbuffer"))
        child.set_defaults(handler=handler)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except SaveFormatError as error:
        raise SystemExit(f"save-format error: {error}") from error


if __name__ == "__main__":
    raise SystemExit(main())
