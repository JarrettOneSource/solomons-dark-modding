#!/usr/bin/env python3
"""Inspect Solomon Dark's recursive SyncBuffer-based .boneyard container."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class ChunkNode:
    offset: int
    payload_offset: int
    payload: bytes
    children: tuple["ChunkNode", ...]


@dataclass(frozen=True)
class SyncBuffer:
    offset: int
    root: ChunkNode
    named_children: tuple[tuple[str, "SyncBuffer"], ...]


class Cursor:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def read_u32(self) -> int:
        if self.offset + 4 > len(self.data):
            raise ParseError(f"truncated u32 at 0x{self.offset:X}")
        value = struct.unpack_from("<I", self.data, self.offset)[0]
        self.offset += 4
        return value

    def read_bytes(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise ParseError(
                f"truncated byte range at 0x{self.offset:X}: "
                f"need {size}, have {len(self.data) - self.offset}"
            )
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def read_string(self) -> str:
        size = self.read_u32()
        raw = self.read_bytes(size)
        if not raw or raw[-1] != 0:
            raise ParseError(f"non-NUL-terminated string ending at 0x{self.offset:X}")
        return raw[:-1].decode("utf-8")


def parse_chunk_node(cursor: Cursor) -> ChunkNode:
    offset = cursor.offset
    payload_size = cursor.read_u32()
    payload_offset = cursor.offset
    payload = cursor.read_bytes(payload_size)
    child_count = cursor.read_u32()
    children = tuple(parse_chunk_node(cursor) for _ in range(child_count))
    return ChunkNode(
        offset=offset,
        payload_offset=payload_offset,
        payload=payload,
        children=children,
    )


def parse_sync_buffer(cursor: Cursor) -> SyncBuffer:
    offset = cursor.offset
    root = parse_chunk_node(cursor)
    named_child_count = cursor.read_u32()
    named_children = tuple(
        (cursor.read_string(), parse_sync_buffer(cursor))
        for _ in range(named_child_count)
    )
    return SyncBuffer(offset=offset, root=root, named_children=named_children)


def walk_nodes(node: ChunkNode, path: tuple[int, ...] = ()):
    yield path, node
    for index, child in enumerate(node.children):
        yield from walk_nodes(child, path + (index,))


def parse_node_path(value: str) -> tuple[int, ...]:
    if value in {"", "root"}:
        return ()
    try:
        path = tuple(int(part) for part in value.split("."))
        if any(index < 0 for index in path):
            raise ValueError
        return path
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "node paths must be dot-separated child indexes, such as 0.12.0"
        ) from error


def resolve_node(root: ChunkNode, path: tuple[int, ...]) -> ChunkNode:
    node = root
    for depth, index in enumerate(path):
        if index < 0 or index >= len(node.children):
            parent = ".".join(map(str, path[:depth])) or "root"
            raise ParseError(
                f"node {parent} has {len(node.children)} children; "
                f"index {index} does not exist"
            )
        node = node.children[index]
    return node


def walk_buffers(buffer: SyncBuffer, path: tuple[str, ...] = ()):
    yield path, buffer
    for name, child in buffer.named_children:
        yield from walk_buffers(child, path + (name,))


def printable_preview(payload: bytes, limit: int) -> str:
    text = "".join(chr(value) if 32 <= value < 127 else "." for value in payload[:limit])
    return text


def build_summary(path: Path, data: bytes, root: SyncBuffer) -> dict:
    buffers = []
    total_nodes = 0
    total_payload_bytes = 0
    maximum_node_depth = 0
    for buffer_path, buffer in walk_buffers(root):
        nodes = list(walk_nodes(buffer.root))
        node_payload_bytes = sum(len(node.payload) for _, node in nodes)
        total_nodes += len(nodes)
        total_payload_bytes += node_payload_bytes
        maximum_node_depth = max(
            maximum_node_depth,
            max((len(node_path) for node_path, _ in nodes), default=0),
        )
        buffers.append(
            {
                "path": "/".join(buffer_path) or "/",
                "offset": buffer.offset,
                "anonymous_node_count": len(nodes),
                "payload_bytes": node_payload_bytes,
                "named_child_count": len(buffer.named_children),
            }
        )
    return {
        "path": path.as_posix(),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "sync_buffer_count": len(buffers),
        "anonymous_node_count": total_nodes,
        "payload_bytes": total_payload_bytes,
        "maximum_anonymous_node_depth": maximum_node_depth,
        "buffers": buffers,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", action="store_true", help="emit the summary as JSON")
    parser.add_argument(
        "--nodes",
        action="store_true",
        help="list every anonymous chunk node and its payload preview",
    )
    parser.add_argument(
        "--node",
        type=parse_node_path,
        help="inspect only this anonymous node subtree (for example 0.12.0)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        help="limit --nodes output to this many levels below the selected node",
    )
    parser.add_argument("--preview-bytes", type=int, default=48)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data = args.path.read_bytes()
    cursor = Cursor(data)
    root = parse_sync_buffer(cursor)
    if cursor.offset != len(data):
        raise ParseError(
            f"unparsed data starts at 0x{cursor.offset:X} "
            f"({len(data) - cursor.offset} bytes remain)"
        )

    summary = build_summary(args.path, data, root)
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print(
        f"{args.path}: size={summary['size']} sha256={summary['sha256']} "
        f"buffers={summary['sync_buffer_count']} "
        f"nodes={summary['anonymous_node_count']} "
        f"payload_bytes={summary['payload_bytes']} "
        f"max_node_depth={summary['maximum_anonymous_node_depth']}"
    )
    for buffer_path, buffer in walk_buffers(root):
        nodes = list(walk_nodes(buffer.root))
        rendered_buffer_path = "/".join(buffer_path) or "/"
        print(
            f"buffer {rendered_buffer_path} offset=0x{buffer.offset:X} "
            f"nodes={len(nodes)} "
            f"payload_bytes={sum(len(node.payload) for _, node in nodes)} "
            f"named_children={len(buffer.named_children)}"
        )
        if not args.nodes and args.node is None:
            continue
        selected_path = args.node or ()
        selected_node = resolve_node(buffer.root, selected_path)
        for relative_path, node in walk_nodes(selected_node):
            if args.max_depth is not None and len(relative_path) > args.max_depth:
                continue
            node_path = selected_path + relative_path
            rendered_node_path = ".".join(map(str, node_path)) or "root"
            preview = node.payload[: args.preview_bytes].hex(" ")
            printable = printable_preview(node.payload, args.preview_bytes)
            print(
                f"  node {rendered_node_path} offset=0x{node.offset:X} "
                f"payload=0x{node.payload_offset:X}+{len(node.payload)} "
                f"hex=[{preview}] ascii=[{printable}]"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
