#!/usr/bin/env python3
"""Build the complete stock UI building-block membership catalog.

The catalog joins the exhaustive bundle inventory to the static atlas-consumer
map.  It deliberately keeps screen state machines outside the building-block
system: the kit owns source art, font ABI, composition primitives, geometry,
and teardown; existing screen owners continue to own behavior.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "docs/reverse-engineering/native-content-inventory.json"
DEFAULT_CONSUMERS = ROOT / "docs/reverse-engineering/native-atlas-consumers.json"
DEFAULT_OUTPUT = ROOT / "docs/reverse-engineering/native-ui-kit-catalog.json"

RETAIL_SHA256 = "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
UI_ATLASES = (
    "Bonedit",
    "ControlPanel",
    "Controls",
    "Create",
    "Fonts",
    "GameOver",
    "Inventory",
    "LevelPicker",
    "Loader",
    "Skills",
    "Title",
    "UI",
)
KNOWN_DORMANT_RECORDS = {
    "ControlPanel": frozenset((1, 2, 3, 6, 7)),
    "Controls": frozenset((3,)),
    "Create": frozenset((8,)),
    "Fonts": frozenset((0,)),
    "GameOver": frozenset((2,)),
    "Loader": frozenset((4,)),
    "Skills": frozenset((*range(123, 127), *range(156, 164), 165)),
    "UI": frozenset((35, 36, 38, 60, 67, 83)),
}
FONT_NAMES = {
    ("ControlPanel", 0): "control-panel",
    ("Fonts", 0): "body",
    ("Fonts", 1): "medium",
    ("Fonts", 2): "special-uppercase",
    ("Fonts", 3): "menu",
    ("Fonts", 4): "heading",
    ("Fonts", 5): "skill-uppercase",
    ("Fonts", 6): "world-and-roster",
    ("Fonts", 7): "timeline",
    ("Fonts", 8): "belt",
}

LAYOUTS = (
    "native-loader",
    "loading-screen",
    "beta-notice",
    "control-scheme-picker",
    "main-menu-root",
    "profile-save-select",
    "create-element",
    "create-discipline",
    "hub_pristine_second_new_game",
    "hub_new_game",
    "hub_resumed",
    "game-settings-title",
    "game-settings-gameplay",
    "game-settings-dark-cloud",
    "controls",
    "performance",
    "dark-cloud-browser",
    "dark-cloud-recent",
    "dark-cloud-online-levels",
    "dark-cloud-my-levels",
    "dark-cloud-search",
    "dark-cloud-sort",
    "dark-cloud-options",
    "dark-cloud-login-settings",
    "dark-cloud-menu",
    "pause-menu",
    "skill-picker",
    "map-picker",
    "game-over",
    "hall-of-fame",
)

PRIMITIVES = (
    {
        "id": "atlas-sprite",
        "contract": "one exact atlas record with logical size and trim origin",
    },
    {
        "id": "bitmap-text",
        "contract": "finite glyph set, wrapper metrics, kerning, alignment, wrapping, tint",
    },
    {
        "id": "tiled-and-clipped-fill",
        "contract": "record-backed repeated or clipped fill without resampling the source ABI",
    },
    {
        "id": "mirrored-frame-and-nine-slice",
        "contract": "mirrored corners plus exact edge slices and deterministic painter order",
    },
    {
        "id": "button",
        "contract": "UI.101 idle, UI.102 pressed, UI.54 ends, Fonts group 3 label; disabled art/text alpha 0.5 plus gray rect alpha 0.25",
    },
    {
        "id": "tab-strip",
        "contract": "UI.13 bracket pairs; selected label rises 8 px and bracket span grows 51 to 65 px",
    },
    {
        "id": "message-box",
        "contract": "UI.107-110 outer corners, UI.10/79 edges, UI.49 fill, UI.17 inner frame, UI.18 header, UI.8 arrows",
    },
    {
        "id": "simple-menu",
        "contract": "stock frame, authored rows, semantic hit bounds, opening/closing presentation supplied by the owner",
    },
)


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def indexed_atlases(document: dict[str, Any], path: Path) -> dict[str, dict[str, Any]]:
    rows = document.get("atlases")
    if not isinstance(rows, list):
        raise ValueError(f"{path} has no atlas list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise ValueError(f"{path} has an invalid atlas row")
        name = row["name"]
        if name in result:
            raise ValueError(f"{path} repeats atlas {name}")
        result[name] = row
    return result


def direct_consumers(row: dict[str, Any], record_count: int) -> list[list[dict[str, str]]]:
    result: list[dict[tuple[str, str], dict[str, str]]] = [dict() for _ in range(record_count)]
    for consumer in row.get("consumers", []):
        if not isinstance(consumer, dict):
            continue
        address = consumer.get("address")
        name = consumer.get("name")
        if not isinstance(address, str) or not isinstance(name, str):
            continue
        witness = {"address": address, "name": name}
        for destination in consumer.get("mapped_destinations", []):
            if not isinstance(destination, dict):
                continue
            first = destination.get("first_record")
            last = destination.get("last_record")
            if not isinstance(first, int) or not isinstance(last, int):
                continue
            if first < 0 or last < first or last >= record_count:
                raise ValueError(f"invalid {row.get('name')} destination {first}..{last}")
            for record in range(first, last + 1):
                result[record][(address, name)] = witness
    return [
        [values[key] for key in sorted(values)]
        for values in result
    ]


def build_catalog(inventory_path: Path, consumers_path: Path) -> dict[str, Any]:
    inventory = load_object(inventory_path)
    consumers = load_object(consumers_path)
    inventory_rows = indexed_atlases(inventory, inventory_path)
    consumer_rows = indexed_atlases(consumers, consumers_path)
    source_sha = ((inventory.get("source") or {}).get("executable_sha256"))
    if source_sha != RETAIL_SHA256:
        raise ValueError("native content inventory is not bound to retail 0.72.5")

    atlases: list[dict[str, Any]] = []
    font_wrappers: list[dict[str, Any]] = []
    total_records = 0
    for atlas_name in UI_ATLASES:
        source = inventory_rows.get(atlas_name)
        consumer_source = consumer_rows.get(atlas_name)
        if source is None or consumer_source is None:
            raise ValueError(f"missing native UI atlas {atlas_name}")
        record_count = source.get("record_count")
        if not isinstance(record_count, int) or record_count <= 0:
            raise ValueError(f"invalid record count for {atlas_name}")
        page = (source.get("pages") or [None])[0]
        if not isinstance(page, dict):
            raise ValueError(f"missing page identity for {atlas_name}")
        consumers_by_record = direct_consumers(consumer_source, record_count)
        dormant = KNOWN_DORMANT_RECORDS.get(atlas_name, frozenset())
        records = []
        for record in range(record_count):
            native_evidence = (
                "compiled-dormant"
                if record in dormant
                else "direct-literal-consumer"
                if consumers_by_record[record]
                else "indirect-or-screen-owned-consumer"
            )
            records.append(
                {
                    "record": record,
                    "disposition": "exact-ported",
                    "native_evidence": native_evidence,
                    "direct_consumers": consumers_by_record[record],
                }
            )
        atlas_row = {
            "name": atlas_name,
            "builder": source.get("builder"),
            "singleton": consumer_source.get("singleton"),
            "bundle": {
                "path": source.get("bundle_path"),
                "sha256": source.get("bundle_sha256"),
            },
            "page": {
                "path": page.get("path"),
                "sha256": page.get("sha256"),
                "width": page.get("width"),
                "height": page.get("height"),
            },
            "record_count": record_count,
            "disposition": "exact-ported",
            "records": records,
        }
        atlases.append(atlas_row)
        total_records += record_count

        for group in source.get("aux_groups", []):
            if not isinstance(group, dict) or not isinstance(group.get("group"), int):
                raise ValueError(f"invalid font wrapper in {atlas_name}")
            group_index = group["group"]
            name = FONT_NAMES.get((atlas_name, group_index))
            if name is None:
                raise ValueError(f"unnamed font wrapper {atlas_name}.{group_index}")
            font_wrappers.append(
                {
                    "id": name,
                    "atlas": atlas_name,
                    "group": group_index,
                    "records": [group.get("first_record"), group.get("last_record")],
                    "metrics": group.get("header"),
                    "glyph_count": group.get("glyph_count"),
                    "kerning_count": group.get("kerning_count"),
                    "glyph_ids": group.get("glyph_ids"),
                    "kerning": group.get("kerning_pairs"),
                    "disposition": "exact-ported",
                }
            )

    screen_reason = (
        "out-of-system: screen state, input, transition, and lifecycle remain owned by the existing scene; "
        "the building-block layer supplies exact art and composition only"
    )
    screen_consumers = [
        {"id": layout, "kind": "layout", "disposition": screen_reason}
        for layout in LAYOUTS
    ]
    screen_consumers.extend(
        (
            {
                "id": "dark_cloud_settings_credentials",
                "kind": "overlay",
                "disposition": screen_reason,
            },
            {
                "id": "beta_notice_first_boot",
                "kind": "composite",
                "disposition": screen_reason,
            },
        )
    )
    return {
        "schema": "solomon-dark-native-ui-kit-catalog-v1",
        "source": {
            "program": "SolomonDark.exe",
            "version": "0.72.5",
            "preferred_image_base": "0x00400000",
            "sha256": RETAIL_SHA256,
            "inventory": inventory_path.relative_to(ROOT).as_posix(),
            "consumer_map": consumers_path.relative_to(ROOT).as_posix(),
        },
        "boundary": (
            "stock presentation atlas records, bitmap-font ABI, reusable composition primitives, "
            "semantic hit geometry, and renderer teardown"
        ),
        "summary": {
            "atlas_count": len(atlases),
            "record_count": total_records,
            "font_wrapper_count": len(font_wrappers),
            "primitive_count": len(PRIMITIVES),
            "layout_consumer_count": len(LAYOUTS),
            "overlay_consumer_count": 1,
            "composite_consumer_count": 1,
            "blocked_by_platform_count": 0,
        },
        "atlases": atlases,
        "font_wrappers": font_wrappers,
        "primitives": [
            {**primitive, "disposition": "exact-ported"}
            for primitive in PRIMITIVES
        ],
        "screen_consumers": screen_consumers,
    }


def encoded(catalog: dict[str, Any]) -> bytes:
    return (json.dumps(catalog, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--consumers", type=Path, default=DEFAULT_CONSUMERS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = encoded(build_catalog(args.inventory.resolve(), args.consumers.resolve()))
    output = args.output.resolve()
    if args.check:
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"{output} is stale; regenerate with {Path(__file__).name}")
        return 0
    output.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
