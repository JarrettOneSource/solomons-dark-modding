#!/usr/bin/env python3
"""Build an unrotated Solomon Dark sprite bundle from a JSON frame list."""

from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path
from typing import Any


MAX_FRAMES = 4096
MAX_POINTS_PER_FRAME = 4096
MAX_FRAME_GEOMETRY = 16_384
MAX_BUNDLE_BYTES = 16 * 1024 * 1024
FRAME_FIELDS = {
    "x",
    "y",
    "width",
    "height",
    "logical_width",
    "logical_height",
    "content_width",
    "content_height",
    "center_offset_x",
    "center_offset_y",
    "points",
}


def _finite_number(frame: dict[str, Any], name: str, default: Any = None) -> float:
    raw = frame.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"frame {name!r} must be a number")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"frame {name!r} must be finite")
    return value


def _bounded_number(
    frame: dict[str, Any],
    name: str,
    default: Any = None,
    *,
    positive: bool = False,
) -> float:
    value = _finite_number(frame, name, default)
    if abs(value) > MAX_FRAME_GEOMETRY or (positive and value <= 0):
        if positive:
            raise ValueError(
                f"frame {name!r} must be greater than 0 and at most "
                f"{MAX_FRAME_GEOMETRY}"
            )
        raise ValueError(
            f"frame {name!r} must be from {-MAX_FRAME_GEOMETRY} through "
            f"{MAX_FRAME_GEOMETRY}"
        )
    return value


def _integer(frame: dict[str, Any], name: str, maximum: int) -> int:
    raw = frame.get(name)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"frame {name!r} must be an integer")
    if raw <= 0 or raw > maximum:
        raise ValueError(f"frame {name!r} must be from 1 through {maximum}")
    return raw


def encode_frame(frame: Any, index: int) -> bytes:
    if not isinstance(frame, dict):
        raise ValueError(f"frame {index} must be an object")
    unknown = sorted(set(frame) - FRAME_FIELDS)
    if unknown:
        raise ValueError(f"frame {index} has unknown fields: {', '.join(unknown)}")

    x = _bounded_number(frame, "x")
    y = _bounded_number(frame, "y")
    width = _bounded_number(frame, "width", positive=True)
    height = _bounded_number(frame, "height", positive=True)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError(f"frame {index} rectangle must be positive and nonnegative")
    logical_width = _integer(frame, "logical_width", MAX_FRAME_GEOMETRY)
    logical_height = _integer(frame, "logical_height", MAX_FRAME_GEOMETRY)
    content_width = _bounded_number(
        frame, "content_width", width, positive=True
    )
    content_height = _bounded_number(
        frame, "content_height", height, positive=True
    )
    center_offset_x = _bounded_number(frame, "center_offset_x", 0)
    center_offset_y = _bounded_number(frame, "center_offset_y", 0)

    raw_points = frame.get("points", [])
    if not isinstance(raw_points, list) or len(raw_points) > MAX_POINTS_PER_FRAME:
        raise ValueError(
            f"frame {index} points must be a list of at most "
            f"{MAX_POINTS_PER_FRAME} pairs"
        )
    points: list[tuple[float, float]] = []
    for point_index, point in enumerate(raw_points):
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError(f"frame {index} point {point_index} must be [x, y]")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in point):
            raise ValueError(f"frame {index} point {point_index} must be numeric")
        pair = (float(point[0]), float(point[1]))
        if not all(
            math.isfinite(value) and abs(value) <= MAX_FRAME_GEOMETRY
            for value in pair
        ):
            raise ValueError(
                f"frame {index} point {point_index} must be finite and within "
                f"{-MAX_FRAME_GEOMETRY} through {MAX_FRAME_GEOMETRY}"
            )
        points.append(pair)

    encoded = bytearray(
        struct.pack(
            "<ffffiIffffBI",
            x,
            y,
            width,
            height,
            logical_width,
            logical_height,
            content_width,
            content_height,
            center_offset_x,
            center_offset_y,
            0,
            len(points),
        )
    )
    for point in points:
        encoded.extend(struct.pack("<ff", *point))
    return bytes(encoded)


def build_bundle(document: Any) -> bytes:
    if not isinstance(document, dict) or set(document) != {"frames"}:
        raise ValueError("descriptor must contain exactly one 'frames' field")
    frames = document["frames"]
    if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_FRAMES:
        raise ValueError(f"frames must contain 1 through {MAX_FRAMES} entries")
    encoded_frames: list[bytes] = []
    encoded_size = 0
    for index, frame in enumerate(frames):
        encoded = encode_frame(frame, index)
        encoded_size += len(encoded)
        if encoded_size > MAX_BUNDLE_BYTES:
            raise ValueError(
                f"bundle exceeds the {MAX_BUNDLE_BYTES}-byte runtime limit"
            )
        encoded_frames.append(encoded)
    return b"".join(encoded_frames)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("descriptor", type=Path, help="JSON frame descriptor")
    parser.add_argument("output", type=Path, help="destination .bundle file")
    args = parser.parse_args()
    if args.output.suffix.lower() != ".bundle":
        parser.error("output path must end in .bundle")

    document = json.loads(args.descriptor.read_text(encoding="utf-8"))
    payload = build_bundle(document)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(
        json.dumps(
            {
                "ok": True,
                "descriptor": str(args.descriptor),
                "output": str(args.output),
                "frame_count": len(document["frames"]),
                "bundle_bytes": len(payload),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
