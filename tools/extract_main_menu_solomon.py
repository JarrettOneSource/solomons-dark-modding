#!/usr/bin/env python3
"""Extract the title-screen Solomon layers used by the stock main menu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from extract_bundles import parse_bundle, rounded_clamped_box


TOOLS_DIR = Path(__file__).resolve().parent
MOD_LOADER_DIR = TOOLS_DIR.parent
DEFAULT_IMAGES_DIR = MOD_LOADER_DIR.parent / "SolomonDarkAbandonware" / "images"
DEFAULT_OUTPUT_DIR = (
    MOD_LOADER_DIR / "docs" / "assets" / "main-menu-solomon"
)

LAYERS = (
    (3, "body"),
    (8, "eyes"),
    (11, "cloak-0"),
    (12, "cloak-1"),
    (13, "cloak-2"),
    (14, "cloak-3"),
    (15, "cloak-4"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract the stock main-menu Solomon layers from Title.bundle."
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=DEFAULT_IMAGES_DIR,
        help=f"game images directory (default: {DEFAULT_IMAGES_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"destination directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


def trim_origin(
    logical_size: int,
    content_size: float,
    center_offset: float,
) -> float:
    return (logical_size - content_size) / 2.0 + center_offset


def main() -> int:
    args = parse_args()
    images_dir = args.images_dir.resolve()
    output_dir = args.output_dir.resolve()
    bundle_path = images_dir / "Title.bundle"
    atlas_path = images_dir / "Title.png"

    records, auxiliary_groups = parse_bundle(bundle_path)
    if auxiliary_groups:
        raise ValueError("Title.bundle unexpectedly contains auxiliary groups")
    if len(records) != 25:
        raise ValueError(
            f"Title.bundle has {len(records)} records; expected the retail 25"
        )

    with Image.open(atlas_path) as source:
        atlas = source.convert("RGBA")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    extracted: list[tuple[str, Image.Image]] = []

    for index, name in LAYERS:
        record = records[index]
        if record.rotated != 0 or record.point_count != 0:
            raise ValueError(
                f"Title[{index}] has unsupported rotation/point metadata"
            )

        box, warnings = rounded_clamped_box(record, *atlas.size)
        if warnings:
            raise ValueError(f"Title[{index}] metadata warning: {warnings[0]}")

        crop = atlas.crop(box)
        output_name = f"{name}.png"
        output_path = output_dir / output_name
        crop.save(output_path)

        with Image.open(output_path) as saved:
            if saved.convert("RGBA").tobytes() != crop.tobytes():
                raise ValueError(f"pixel verification failed for {output_name}")

        trim_x = trim_origin(
            record.logical_width,
            record.content_width,
            record.center_offset_x,
        )
        trim_y = trim_origin(
            record.logical_height,
            record.content_height,
            record.center_offset_y,
        )
        manifest.append(
            {
                "name": name,
                "record_index": index,
                "bundle_offset": record.offset,
                "output": output_name,
                "atlas_crop": {
                    "x": box[0],
                    "y": box[1],
                    "width": box[2] - box[0],
                    "height": box[3] - box[1],
                },
                "logical_canvas": {
                    "width": record.logical_width,
                    "height": record.logical_height,
                },
                "center_offset": {
                    "x": record.center_offset_x,
                    "y": record.center_offset_y,
                },
                "trim_origin": {"x": trim_x, "y": trim_y},
            }
        )
        extracted.append((name, crop))

    cell_width = 240
    cell_height = 370
    columns = 4
    rows = 2
    contact = Image.new(
        "RGBA",
        (columns * cell_width, rows * cell_height),
        (44, 44, 44, 255),
    )
    draw = ImageDraw.Draw(contact)
    font = ImageFont.load_default()
    for item_index, (name, crop) in enumerate(extracted):
        column = item_index % columns
        row = item_index // columns
        cell_x = column * cell_width
        cell_y = row * cell_height
        preview = crop.copy()
        preview.thumbnail((cell_width - 20, cell_height - 45))
        image_x = cell_x + (cell_width - preview.width) // 2
        image_y = cell_y + 10 + (cell_height - 45 - preview.height) // 2
        contact.alpha_composite(preview, (image_x, image_y))
        label = f"Title[{LAYERS[item_index][0]}] {name}"
        draw.text((cell_x + 8, cell_y + cell_height - 25), label, fill="white", font=font)
        draw.rectangle(
            (
                cell_x,
                cell_y,
                cell_x + cell_width - 1,
                cell_y + cell_height - 1,
            ),
            outline=(96, 96, 96, 255),
        )
    contact.save(output_dir / "contact-sheet.png")

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_atlas": "Title.png",
                "source_bundle": "Title.bundle",
                "atlas_size": {"width": atlas.width, "height": atlas.height},
                "layers": manifest,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"Extracted and pixel-verified {len(extracted)} layers into {output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
