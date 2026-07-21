#!/usr/bin/env python3
"""Extract every Solomon Dark sprite bundle into individual PNG files."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DEFAULT_IMAGES_DIR = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/Solomon Dark/"
    "SolomonDarkAbandonware/images"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "out"

COMMON_HEADER_SIZE = 45
POINT_SIZE = 8
THUMB_SIZE = 80
CONTACT_PADDING = 5
CONTACT_LABEL_HEIGHT = 18
CONTACT_CELL_WIDTH = THUMB_SIZE + 2 * CONTACT_PADDING
CONTACT_CELL_HEIGHT = THUMB_SIZE + CONTACT_LABEL_HEIGHT + 2 * CONTACT_PADDING
CONTACT_BACKGROUND = (128, 128, 128)


class BundleFormatError(ValueError):
    """Raised when a bundle cannot be consumed with the known stream grammar."""


@dataclass(frozen=True)
class SpriteRecord:
    offset: int
    end: int
    x: float
    y: float
    width: float
    height: float
    logical_width: int
    logical_height: int
    content_width: float
    content_height: float
    center_offset_x: float
    center_offset_y: float
    rotated: int
    point_count: int
    raw_meta_hex: str


@dataclass(frozen=True)
class AuxGroup:
    offset: int
    header: tuple[float, float, float]
    kerning_count: int
    glyph_count: int
    kerning_pairs: tuple[tuple[int, int, float], ...]
    glyph_ids: tuple[int, ...]


def require_bytes(data: bytes, offset: int, size: int, context: str) -> None:
    if offset < 0 or offset + size > len(data):
        raise BundleFormatError(
            f"{context} at 0x{offset:x} needs {size} bytes; "
            f"file ends at 0x{len(data):x}"
        )


def parse_common_record(data: bytes, offset: int) -> SpriteRecord:
    require_bytes(data, offset, COMMON_HEADER_SIZE, "common sprite header")

    x, y, width, height = struct.unpack_from("<4f", data, offset)
    logical_width = struct.unpack_from("<i", data, offset + 0x10)[0]
    logical_height = struct.unpack_from("<I", data, offset + 0x14)[0]
    content_width, content_height, center_offset_x, center_offset_y = (
        struct.unpack_from("<4f", data, offset + 0x18)
    )
    rotated = data[offset + 0x28]
    point_count = struct.unpack_from("<I", data, offset + 0x29)[0]

    if rotated not in (0, 1):
        raise BundleFormatError(
            f"invalid rotation byte {rotated} in sprite header at 0x{offset:x}"
        )

    end = offset + COMMON_HEADER_SIZE + point_count * POINT_SIZE
    if end > len(data):
        raise BundleFormatError(
            f"sprite header at 0x{offset:x} declares {point_count} points "
            f"and ends at 0x{end:x}, beyond file end 0x{len(data):x}"
        )

    numeric_fields = (
        x,
        y,
        width,
        height,
        content_width,
        content_height,
        center_offset_x,
        center_offset_y,
    )
    for point_index in range(point_count):
        numeric_fields += struct.unpack_from(
            "<2f", data, offset + COMMON_HEADER_SIZE + point_index * POINT_SIZE
        )
    if not all(math.isfinite(value) for value in numeric_fields):
        raise BundleFormatError(f"non-finite float in sprite record at 0x{offset:x}")

    return SpriteRecord(
        offset=offset,
        end=end,
        x=x,
        y=y,
        width=width,
        height=height,
        logical_width=logical_width,
        logical_height=logical_height,
        content_width=content_width,
        content_height=content_height,
        center_offset_x=center_offset_x,
        center_offset_y=center_offset_y,
        rotated=rotated,
        point_count=point_count,
        raw_meta_hex=data[offset + 0x10 : end].hex(),
    )


def parse_aux_groups(
    data: bytes, offset: int
) -> tuple[list[SpriteRecord], list[AuxGroup]]:
    """Parse the font-table wrapper used by Fonts and ControlPanel."""

    records: list[SpriteRecord] = []
    groups: list[AuxGroup] = []

    while offset < len(data):
        group_offset = offset
        require_bytes(data, offset, 12, "auxiliary group header")
        header = struct.unpack_from("<3f", data, offset)
        if not all(math.isfinite(value) for value in header):
            raise BundleFormatError(
                f"non-finite auxiliary header at 0x{group_offset:x}"
            )
        offset += 12

        kerning_pairs: list[tuple[int, int, float]] = []
        while True:
            require_bytes(data, offset, 4, "kerning pair or terminator")
            left_id, right_id = struct.unpack_from("<HH", data, offset)
            if left_id == 0 and right_id == 0:
                offset += 4
                break
            require_bytes(data, offset, 8, "kerning entry")
            adjustment = struct.unpack_from("<f", data, offset + 4)[0]
            if not math.isfinite(adjustment):
                raise BundleFormatError(
                    f"non-finite kerning adjustment at 0x{offset:x}"
                )
            offset += 8
            kerning_pairs.append((left_id, right_id, adjustment))

        glyph_ids: list[int] = []
        while True:
            require_bytes(data, offset, 2, "glyph id or terminator")
            glyph_id = struct.unpack_from("<H", data, offset)[0]
            if glyph_id == 0:
                offset += 2
                break

            require_bytes(data, offset, 14, "glyph id and metrics")
            glyph_metrics = struct.unpack_from("<3f", data, offset + 2)
            if not all(math.isfinite(value) for value in glyph_metrics):
                raise BundleFormatError(f"non-finite glyph metric at 0x{offset:x}")

            record = parse_common_record(data, offset + 14)
            records.append(record)
            glyph_ids.append(glyph_id)
            offset = record.end

        groups.append(
            AuxGroup(
                offset=group_offset,
                header=header,
                kerning_count=len(kerning_pairs),
                glyph_count=len(glyph_ids),
                kerning_pairs=tuple(kerning_pairs),
                glyph_ids=tuple(glyph_ids),
            )
        )

    return records, groups


def parse_bundle(path: Path) -> tuple[list[SpriteRecord], list[AuxGroup]]:
    data = path.read_bytes()
    records: list[SpriteRecord] = []
    offset = 0
    prefix_error: BundleFormatError | None = None

    while offset < len(data):
        try:
            record = parse_common_record(data, offset)
        except BundleFormatError as error:
            prefix_error = error
            break
        records.append(record)
        offset = record.end

    if offset == len(data):
        return records, []

    try:
        aux_records, groups = parse_aux_groups(data, offset)
    except BundleFormatError as aux_error:
        raise BundleFormatError(
            f"{path.name}: common stream stopped at 0x{offset:x} "
            f"({prefix_error}); auxiliary parse also failed ({aux_error})"
        ) from aux_error

    records.extend(aux_records)
    return records, groups


def load_label_font() -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", 12)
    except OSError:
        return ImageFont.load_default()


def contact_grid(record_count: int) -> tuple[int, int]:
    columns = max(
        1,
        math.ceil(
            math.sqrt(record_count * CONTACT_CELL_HEIGHT / CONTACT_CELL_WIDTH)
        ),
    )
    rows = math.ceil(record_count / columns)
    return columns, rows


def rounded_clamped_box(
    record: SpriteRecord,
    atlas_width: int,
    atlas_height: int,
) -> tuple[tuple[int, int, int, int], list[str]]:
    if record.width <= 0 or record.height <= 0:
        raise BundleFormatError(
            f"record at 0x{record.offset:x} has non-positive size "
            f"{record.width} x {record.height}"
        )

    x = int(round(record.x))
    y = int(round(record.y))
    width = int(round(record.width))
    height = int(round(record.height))
    if width <= 0 or height <= 0:
        raise BundleFormatError(
            f"record at 0x{record.offset:x} rounds to non-positive size "
            f"{width} x {height}"
        )

    raw_box = (x, y, x + width, y + height)
    box = (
        min(max(raw_box[0], 0), atlas_width),
        min(max(raw_box[1], 0), atlas_height),
        min(max(raw_box[2], 0), atlas_width),
        min(max(raw_box[3], 0), atlas_height),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        raise BundleFormatError(
            f"record at 0x{record.offset:x} has no pixels after clamping "
            f"{raw_box} to {atlas_width} x {atlas_height}"
        )

    warnings: list[str] = []
    if box != raw_box:
        warnings.append(
            f"rect {raw_box} was clamped to {box} for atlas "
            f"{atlas_width} x {atlas_height}"
        )
    if (
        record.content_width != record.width
        or record.content_height != record.height
    ):
        warnings.append(
            "stored content dimensions do not match the atlas rectangle: "
            f"{record.content_width} x {record.content_height} versus "
            f"{record.width} x {record.height}"
        )
    if record.logical_width <= 0 or record.logical_height <= 0:
        warnings.append(
            f"non-positive logical canvas {record.logical_width} x "
            f"{record.logical_height}"
        )

    return box, warnings


def add_to_contact_sheet(
    sheet: Image.Image,
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    sprite: Image.Image,
    index: int,
    columns: int,
) -> None:
    column = index % columns
    row = index // columns
    cell_x = column * CONTACT_CELL_WIDTH
    cell_y = row * CONTACT_CELL_HEIGHT

    thumbnail = sprite.copy()
    thumbnail.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
    image_x = cell_x + CONTACT_PADDING + (THUMB_SIZE - thumbnail.width) // 2
    image_y = cell_y + CONTACT_PADDING + (THUMB_SIZE - thumbnail.height) // 2
    sheet.paste(thumbnail, (image_x, image_y), thumbnail)

    label = str(index)
    label_box = draw.textbbox((0, 0), label, font=font)
    label_width = label_box[2] - label_box[0]
    label_x = cell_x + (CONTACT_CELL_WIDTH - label_width) // 2
    label_y = cell_y + CONTACT_PADDING + THUMB_SIZE + 1
    draw.text((label_x, label_y), label, fill=(20, 20, 20), font=font)
    draw.rectangle(
        (
            cell_x,
            cell_y,
            cell_x + CONTACT_CELL_WIDTH - 1,
            cell_y + CONTACT_CELL_HEIGHT - 1,
        ),
        outline=(108, 108, 108),
        width=1,
    )


def extract_atlas(
    bundle_path: Path,
    output_dir: Path,
) -> tuple[int, int, int, list[str], list[AuxGroup]]:
    png_path = bundle_path.with_suffix(".png")
    if not png_path.is_file():
        raise FileNotFoundError(f"missing sibling atlas: {png_path}")

    records, aux_groups = parse_bundle(bundle_path)
    if not records:
        raise BundleFormatError(f"{bundle_path.name} contains no sprite records")

    atlas_name = bundle_path.stem
    atlas_output_dir = output_dir / atlas_name
    if atlas_output_dir.exists():
        shutil.rmtree(atlas_output_dir)
    atlas_output_dir.mkdir(parents=True)

    manifest: list[dict[str, int | str]] = []
    warnings: list[str] = []
    digits = max(2, len(str(len(records) - 1)))
    columns, rows = contact_grid(len(records))
    contact_sheet = Image.new(
        "RGB",
        (columns * CONTACT_CELL_WIDTH, rows * CONTACT_CELL_HEIGHT),
        CONTACT_BACKGROUND,
    )
    contact_draw = ImageDraw.Draw(contact_sheet)
    contact_font = load_label_font()

    with Image.open(png_path) as source_image:
        atlas = source_image.convert("RGBA")
    atlas_width, atlas_height = atlas.size

    point_total = 0
    for index, record in enumerate(records):
        box, record_warnings = rounded_clamped_box(
            record, atlas_width, atlas_height
        )
        for warning in record_warnings:
            warnings.append(f"sprite {index}: {warning}")

        sprite = atlas.crop(box)
        sprite_path = atlas_output_dir / f"sprite_{index:0{digits}d}.png"
        sprite.save(sprite_path)
        add_to_contact_sheet(
            contact_sheet,
            contact_draw,
            contact_font,
            sprite,
            index,
            columns,
        )

        manifest.append(
            {
                "index": index,
                "x": box[0],
                "y": box[1],
                "w": box[2] - box[0],
                "h": box[3] - box[1],
                "raw_meta_hex": record.raw_meta_hex,
            }
        )
        point_total += record.point_count

    manifest_path = atlas_output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    contact_sheet.save(output_dir / f"{atlas_name}_contact.png")

    return len(records), point_total, len(aux_groups), warnings, aux_groups


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract Solomon Dark .bundle sprite records and contact sheets."
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=DEFAULT_IMAGES_DIR,
        help=f"source directory (default: {DEFAULT_IMAGES_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"destination directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    images_dir = args.images_dir.resolve()
    output_dir = args.output_dir.resolve()

    bundle_paths = sorted(images_dir.glob("*.bundle"), key=lambda path: path.name)
    if not bundle_paths:
        print(f"error: no .bundle files in {images_dir}", file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    total_records = 0
    total_warnings = 0

    for bundle_path in bundle_paths:
        try:
            record_count, point_total, group_count, warnings, groups = extract_atlas(
                bundle_path, output_dir
            )
        except (BundleFormatError, FileNotFoundError, OSError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1

        total_records += record_count
        total_warnings += len(warnings)
        suffix = f", {group_count} auxiliary group(s)" if group_count else ""
        print(
            f"{bundle_path.stem}: {record_count} sprites, "
            f"{point_total} extra points{suffix}"
        )
        if groups:
            print(
                "  group glyph counts: "
                + ", ".join(str(group.glyph_count) for group in groups)
            )
        for warning in warnings:
            print(f"  warning: {warning}", file=sys.stderr)

    print(
        f"Extracted {total_records} sprites from {len(bundle_paths)} bundles; "
        f"warnings: {total_warnings}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
