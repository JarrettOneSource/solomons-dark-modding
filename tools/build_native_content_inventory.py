#!/usr/bin/env python3
"""Build a deterministic inventory of a Solomon Dark installation tree.

The output deliberately records both disk assets and the compiled atlas-builder
layout recovered by trace_bundle_sprite_loads.py. It contains no timestamps or
absolute paths, so two inventories of identical game data compare cleanly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from PIL import Image

from extract_bundles import parse_bundle


DEFAULT_GAME_ROOT = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/Solomon Dark/"
    "SolomonDarkAbandonware"
)

ATLAS_BUILDERS = {
    "BadGuys": "0x004E0DD0",
    "Bonedit": "0x004E41C0",
    "Clothes": "0x004E4CA0",
    "College": "0x004E6450",
    "ControlPanel": "0x004E7EF0",
    "Controls": "0x004E84E0",
    "Create": "0x004E8680",
    "DeadHawg": "0x004E8A90",
    "Demon": "0x004E9AC0",
    "Faculty": "0x004E9EA0",
    "Fonts": "0x004EA3D0",
    "GameOver": "0x004EA650",
    "Golem": "0x004EA7C0",
    "Heartmonger": "0x004EADD0",
    "Inventory": "0x004EB0F0",
    "LevelPicker": "0x004EBA90",
    "Library": "0x004EBCC0",
    "Loader": "0x004EC1F0",
    "Memoratorium": "0x004EC3B0",
    "NPCs": "0x004EC890",
    "Office": "0x004ECDC0",
    "Skills": "0x004ED280",
    "Solomon": "0x004ED980",
    "SolomonRiff": "0x004EDE70",
    "Storage": "0x004F2EB0",
    "Title": "0x004F3210",
    "UI": "0x004F3590",
    "Unholy": "0x004F4750",
}

TRACE_RANGE_RE = re.compile(
    r"^(INLINE|ARRAY) call=([0-9A-Fa-f]+) "
    r"destination=(object|array)\+(0x[0-9A-Fa-f]+) "
    r"count=(\d+) records=(\d+)\.\.(\d+)$"
)
TRACE_TOTAL_RE = re.compile(r"^TOTAL_RECORDS (\d+)$")
AUX_TRACE_RE = re.compile(
    r"^AUX_GROUP call=([0-9A-Fa-f]+) "
    r"destination=(object|array|inline|unknown)\+(0x[0-9A-Fa-f]+|\?) "
    r"group=(\d+)$"
)
AUX_TOTAL_RE = re.compile(r"^TOTAL_AUX_GROUPS (\d+)$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".bundle":
        return "sprite_bundle"
    if suffix in {".png", ".gif", ".jpg", ".thumb"}:
        return "image"
    if suffix == ".boneyard":
        return "boneyard"
    if suffix == ".cfg":
        return "config"
    if suffix == ".wav":
        return "audio"
    if suffix == ".mo3":
        return "music_archive"
    if suffix == ".exe":
        return "executable"
    if suffix == ".dll":
        return "library"
    if suffix == ".raw":
        return "raw_image"
    if suffix == ".cached":
        return "cached_image"
    if suffix == ".sav":
        return "save"
    if suffix in {".txt", ".dat"}:
        return "text_or_table"
    return suffix.removeprefix(".") or "extensionless"


def inventory_files(root: Path) -> tuple[list[dict[str, object]], Counter[str]]:
    rows: list[dict[str, object]] = []
    extension_counts: Counter[str] = Counter()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        suffix = path.suffix.lower().removeprefix(".") or "extensionless"
        extension_counts[suffix] += 1
        relative_path = relative(path, root)
        rows.append(
            {
                "path": relative_path,
                "scope": (
                    "runtime_mutable" if relative_path.startswith("sandbox/")
                    else "installed_content"
                ),
                "kind": file_kind(path),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return rows, extension_counts


def image_row(path: Path, root: Path) -> dict[str, object]:
    with Image.open(path) as image:
        return {
            "path": relative(path, root),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
        }


def parse_trace(path: Path) -> dict[str, object]:
    ranges: list[dict[str, object]] = []
    aux_destinations: list[dict[str, object]] = []
    traced_total = None
    traced_aux_total = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = TRACE_RANGE_RE.match(line.strip())
        if match:
            ranges.append(
                {
                    "destination_kind": match.group(1).lower(),
                    "call": f"0x{match.group(2).upper()}",
                    "object_field": match.group(4).upper().replace("X", "x"),
                    "count": int(match.group(5)),
                    "first_record": int(match.group(6)),
                    "last_record": int(match.group(7)),
                }
            )
            continue
        match = TRACE_TOTAL_RE.match(line.strip())
        if match:
            traced_total = int(match.group(1))
            continue
        match = AUX_TRACE_RE.match(line.strip())
        if match:
            aux_destinations.append(
                {
                    "call": f"0x{match.group(1).upper()}",
                    "destination_kind": match.group(2),
                    "object_field": (
                        None if match.group(3) == "?"
                        else match.group(3).upper().replace("X", "x")
                    ),
                    "group": int(match.group(4)),
                }
            )
            continue
        match = AUX_TOTAL_RE.match(line.strip())
        if match:
            traced_aux_total = int(match.group(1))
    if traced_total is None:
        raise ValueError(f"trace has no TOTAL_RECORDS line: {path}")
    if traced_aux_total is None:
        traced_aux_total = 0
    if traced_aux_total != len(aux_destinations):
        raise ValueError(
            f"trace auxiliary total mismatch in {path}: "
            f"{traced_aux_total} != {len(aux_destinations)}"
        )
    return {
        "direct_record_count": traced_total,
        "destinations": ranges,
        "aux_group_count": traced_aux_total,
        "aux_destinations": aux_destinations,
    }


def inventory_atlases(
    root: Path, trace_dir: Path | None
) -> list[dict[str, object]]:
    images_dir = root / "images"
    rows: list[dict[str, object]] = []
    for bundle_path in sorted(images_dir.glob("*.bundle")):
        name = bundle_path.stem
        records, aux_groups = parse_bundle(bundle_path)
        aux_record_count = sum(group.glyph_count for group in aux_groups)
        page_paths = sorted(images_dir.glob(f"{name}.png"))
        page_paths.extend(sorted(images_dir.glob(f"{name}-[0-9]*.png")))
        row: dict[str, object] = {
            "name": name,
            "builder": ATLAS_BUILDERS[name],
            "bundle_path": relative(bundle_path, root),
            "bundle_bytes": bundle_path.stat().st_size,
            "bundle_sha256": sha256(bundle_path),
            "record_count": len(records),
            "direct_common_record_count": len(records) - aux_record_count,
            "aux_record_count": aux_record_count,
            "aux_group_count": len(aux_groups),
            "point_count": sum(record.point_count for record in records),
            "rotation_counts": dict(
                sorted(Counter(record.rotated for record in records).items())
            ),
            "pages": [image_row(path, root) for path in page_paths],
        }
        if aux_groups:
            next_record = len(records) - aux_record_count
            aux_rows = []
            for group_index, group in enumerate(aux_groups):
                first_record = next_record
                last_record = first_record + group.glyph_count - 1
                aux_rows.append({
                    "group": group_index,
                    "offset": f"0x{group.offset:X}",
                    "header": list(group.header),
                    "kerning_count": group.kerning_count,
                    "glyph_count": group.glyph_count,
                    "first_record": first_record,
                    "last_record": last_record,
                    "glyph_ids": list(group.glyph_ids),
                    "kerning_pairs": [list(pair) for pair in group.kerning_pairs],
                })
                next_record = last_record + 1
            row["aux_groups"] = aux_rows
        if trace_dir is not None:
            trace_path = trace_dir / f"trace-{name}.log"
            if not trace_path.is_file():
                raise FileNotFoundError(f"missing builder trace: {trace_path}")
            trace = parse_trace(trace_path)
            if trace["direct_record_count"] != row["direct_common_record_count"]:
                raise ValueError(
                    f"{name} direct trace count {trace['direct_record_count']} "
                    f"!= parsed common count {row['direct_common_record_count']}"
                )
            if trace["aux_group_count"] != row["aux_group_count"]:
                raise ValueError(
                    f"{name} auxiliary trace count {trace['aux_group_count']} "
                    f"!= parsed group count {row['aux_group_count']}"
                )
            if aux_groups:
                aux_by_index = {
                    aux_row["group"]: aux_row for aux_row in row["aux_groups"]
                }
                for destination in trace["aux_destinations"]:
                    group = aux_by_index[destination["group"]]
                    destination["glyph_count"] = group["glyph_count"]
                    destination["first_record"] = group["first_record"]
                    destination["last_record"] = group["last_record"]
            row["builder_trace"] = trace
        rows.append(row)
    unknown_builders = sorted(set(ATLAS_BUILDERS) - {row["name"] for row in rows})
    if unknown_builders:
        raise ValueError(f"builder table has no matching bundle: {unknown_builders}")
    return rows


def inventory_loose_images(root: Path, atlas_names: set[str]) -> list[dict[str, object]]:
    rows = []
    for path in sorted((root / "images").glob("*.png")):
        if path.stem not in atlas_names:
            rows.append(image_row(path, root))
    return rows


def build_inventory(root: Path, trace_dir: Path | None) -> dict[str, object]:
    files, extension_counts = inventory_files(root)
    atlases = inventory_atlases(root, trace_dir)
    atlas_names = {str(row["name"]) for row in atlases}
    loose_images = inventory_loose_images(root, atlas_names)
    installed_files = [row for row in files if row["scope"] == "installed_content"]
    mutable_files = [row for row in files if row["scope"] == "runtime_mutable"]
    return {
        "schema": "solomon-dark-native-content-inventory/v1",
        "source": {
            "root_label": "SolomonDarkAbandonware",
            "executable_path": "SolomonDark.exe",
            "executable_sha256": sha256(root / "SolomonDark.exe"),
        },
        "summary": {
            "file_count": len(files),
            "installed_content_file_count": len(installed_files),
            "runtime_mutable_file_count": len(mutable_files),
            "extension_counts": dict(sorted(extension_counts.items())),
            "atlas_count": len(atlases),
            "sprite_record_count": sum(int(row["record_count"]) for row in atlases),
            "loose_image_count": len(loose_images),
        },
        "atlases": atlases,
        "loose_images": loose_images,
        "files": files,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    parser.add_argument(
        "--trace-dir",
        type=Path,
        help="directory containing trace-<Atlas>.log Ghidra outputs",
    )
    parser.add_argument("--output", type=Path, help="write JSON here instead of stdout")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inventory = build_inventory(args.game_root.resolve(), args.trace_dir)
    encoded = json.dumps(inventory, indent=2, sort_keys=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
