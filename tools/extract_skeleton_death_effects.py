#!/usr/bin/env python3
"""Extract the BadGuys atlas records used by the skeleton death presenter."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from extract_bundles import parse_bundle, rounded_clamped_box


TOOLS_DIR = Path(__file__).resolve().parent
MOD_LOADER_DIR = TOOLS_DIR.parent
DEFAULT_IMAGES_DIR = MOD_LOADER_DIR.parent / "SolomonDarkAbandonware" / "images"
DEFAULT_OUTPUT_DIR = MOD_LOADER_DIR / "docs" / "assets" / "skeleton-death-effects"

BASE_SHARD_INDICES = tuple(range(113, 122))
NORMAL_BASE_SEQUENCE = (113, 115, 118, 121, 120, 119, 116, 117, 117)
ENHANCED_BASE_SEQUENCE = (
    113,
    113,
    113,
    115,
    118,
    121,
    120,
    119,
    116,
    121,
    120,
    119,
    116,
    117,
    117,
    117,
    117,
    117,
)


@dataclass(frozen=True)
class Asset:
    record_index: int
    name: str
    use: str


ASSETS = (
    Asset(15, "additive-flash", "extra-variant flag and special weapon variant 5"),
    Asset(55, "special-weapon-fragment", "seven bouncers for weapon variant 5"),
    Asset(86, "unbind-flash", "always-spawned rotating fade"),
    *(Asset(index, f"body-variant-{index - 92:02d}", "actor byte +0x230") for index in range(92, 100)),
    *(
        Asset(index, f"extra-variant-{index - 100:02d}", "actor flag +0x233")
        for index in range(100, 110)
    ),
    *(Asset(index, f"base-shard-{index - 113:02d}", "base shuffled shatter") for index in BASE_SHARD_INDICES),
    *(Asset(index, f"skull-{index - 1819:02d}", "one random skull is always spawned") for index in range(1819, 1823)),
    Asset(2063, "weapon-01-sword", "actor byte +0x231 value 1"),
    Asset(2064, "weapon-02-mace", "actor byte +0x231 value 2"),
    Asset(2065, "weapon-03-flail", "actor byte +0x231 value 3"),
    Asset(2066, "weapon-04-axe", "actor byte +0x231 value 4"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract and verify the stock skeleton death-effect sprites."
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preview_image(crop: Image.Image, width: int, height: int) -> Image.Image:
    scale = max(1, min(width // crop.width, height // crop.height))
    preview = crop.resize(
        (crop.width * scale, crop.height * scale),
        Image.Resampling.NEAREST,
    )
    if preview.width > width or preview.height > height:
        preview.thumbnail((width, height), Image.Resampling.LANCZOS)
    return preview


def main() -> int:
    args = parse_args()
    images_dir = args.images_dir.resolve()
    output_dir = args.output_dir.resolve()
    bundle_path = images_dir / "BadGuys.bundle"
    atlas_path = images_dir / "BadGuys.png"

    records, auxiliary_groups = parse_bundle(bundle_path)
    if auxiliary_groups:
        raise ValueError("BadGuys.bundle unexpectedly contains auxiliary groups")
    if len(records) != 2509:
        raise ValueError(
            f"BadGuys.bundle has {len(records)} records; expected the retail 2509"
        )

    with Image.open(atlas_path) as source:
        atlas = source.convert("RGBA")

    output_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[tuple[Asset, Image.Image]] = []
    manifest_assets: list[dict[str, object]] = []

    for asset in ASSETS:
        record = records[asset.record_index]
        if record.rotated != 0 or record.point_count != 0:
            raise ValueError(
                f"BadGuys[{asset.record_index}] has unsupported rotation/point metadata"
            )
        box, warnings = rounded_clamped_box(record, *atlas.size)
        if warnings:
            raise ValueError(
                f"BadGuys[{asset.record_index}] metadata warning: {warnings[0]}"
            )

        crop = atlas.crop(box)
        output_name = f"badguys-{asset.record_index:04d}-{asset.name}.png"
        output_path = output_dir / output_name
        crop.save(output_path)
        with Image.open(output_path) as saved:
            if saved.convert("RGBA").tobytes() != crop.tobytes():
                raise ValueError(f"pixel verification failed for {output_name}")

        manifest_assets.append(
            {
                "name": asset.name,
                "use": asset.use,
                "record_index": asset.record_index,
                "bundle_offset": record.offset,
                "output": output_name,
                "atlas_crop": {
                    "x": box[0],
                    "y": box[1],
                    "width": box[2] - box[0],
                    "height": box[3] - box[1],
                },
            }
        )
        extracted.append((asset, crop))

    columns = 7
    cell_width = 170
    cell_height = 150
    rows = (len(extracted) + columns - 1) // columns
    contact = Image.new(
        "RGBA",
        (columns * cell_width, rows * cell_height),
        (44, 44, 44, 255),
    )
    draw = ImageDraw.Draw(contact)
    font = ImageFont.load_default()
    for item_index, (asset, crop) in enumerate(extracted):
        column = item_index % columns
        row = item_index // columns
        cell_x = column * cell_width
        cell_y = row * cell_height
        preview = preview_image(crop, cell_width - 18, cell_height - 42)
        image_x = cell_x + (cell_width - preview.width) // 2
        image_y = cell_y + 22 + (cell_height - 42 - preview.height) // 2
        contact.alpha_composite(preview, (image_x, image_y))
        draw.text(
            (cell_x + 6, cell_y + 5),
            f"{asset.record_index}: {asset.name}",
            fill="white",
            font=font,
        )
        draw.rectangle(
            (cell_x, cell_y, cell_x + cell_width - 1, cell_y + cell_height - 1),
            outline=(96, 96, 96, 255),
        )
    contact.save(output_dir / "contact-sheet.png")

    manifest = {
        "sources": {
            "atlas": atlas_path.name,
            "atlas_sha256": sha256(atlas_path),
            "bundle": bundle_path.name,
            "bundle_sha256": sha256(bundle_path),
            "atlas_size": {"width": atlas.width, "height": atlas.height},
            "bundle_record_count": len(records),
        },
        "native_references": {
            "skeleton_vftable": "0x00786604",
            "death_presenter_slot": "0x50",
            "death_presenter": "0x0048D2A0",
            "badguys_builder": "0x004E0DD0",
            "anim_bouncer_ctor": "0x00453060",
            "anim_bouncer_tick": "0x00456720",
            "anim_bouncer_render": "0x00456A60",
        },
        "runtime_groups": {
            "base_shatter": {
                "bundle_object_offset": "0x46CC",
                "records": list(BASE_SHARD_INDICES),
                "normal_spawn_sequence_before_shuffle": list(NORMAL_BASE_SEQUENCE),
                "enhanced_spawn_sequence_before_shuffle": list(ENHANCED_BASE_SEQUENCE),
            },
            "body_variant": {
                "actor_field": "+0x230",
                "bundle_object_offset": "0x46AC",
                "records": list(range(92, 100)),
            },
            "extra_variant": {
                "actor_field": "+0x233",
                "bundle_object_offset": "0x46AC",
                "records": list(range(100, 110)),
            },
            "skull": {
                "bundle_object_offset": "0x49FC",
                "records": list(range(1819, 1823)),
            },
            "weapon": {
                "actor_field": "+0x231",
                "bundle_object_offset": "0x4AAC",
                "records": list(range(2063, 2067)),
            },
            "inline": {
                "additive_flash": {"object_offset": "0x0BB4", "record": 15},
                "special_weapon_fragment": {"object_offset": "0x2A54", "record": 55},
                "unbind_flash": {"object_offset": "0x4210", "record": 86},
            },
        },
        "assets": manifest_assets,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"Extracted and pixel-verified {len(extracted)} skeleton death-effect "
        f"sprites into {output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
