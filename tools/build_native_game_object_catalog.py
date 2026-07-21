#!/usr/bin/env python3
"""Join factory types, RTTI virtuals, and class-owned atlas record ranges."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factory-catalog", type=Path, required=True)
    parser.add_argument("--class-catalog", type=Path, required=True)
    parser.add_argument("--asset-object-map", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def collect_class_art_uses(asset_map: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    class_uses: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = {}
    for atlas in asset_map["atlases"]:
        for destination in atlas["destinations"]:
            for function in destination["consumer_functions"]:
                for relation_kind, relations in (
                    ("vtable_slot", function["vtable_slots"]),
                    ("vtable_install_reference", function["vtable_install_references"]),
                ):
                    for relation in relations:
                        class_name = relation["class"]
                        key = (
                            atlas["name"],
                            destination["destination_kind"],
                            destination["object_field"],
                            destination["first_record"],
                            destination["last_record"],
                            function["address"],
                            relation_kind,
                            relation.get("slot"),
                        )
                        class_uses.setdefault(class_name, {})[key] = {
                            "atlas": atlas["name"],
                            "destination_kind": destination["destination_kind"],
                            "object_field": destination["object_field"],
                            "first_record": destination["first_record"],
                            "last_record": destination["last_record"],
                            "consumer_function": function["address"],
                            "consumer_function_name": function["name"],
                            "relation": relation_kind,
                            **({"vtable_slot": relation["slot"]} if "slot" in relation else {}),
                        }
    return {
        class_name: [uses[key] for key in sorted(uses)]
        for class_name, uses in class_uses.items()
    }


def type_band(type_id: int) -> str:
    if type_id <= 2:
        return "core_actor"
    if 0x3E8 <= type_id <= 0x3F5:
        return "enemy"
    if 0x7D0 <= type_id <= 0x80F:
        return "world_object_projectile_or_loot"
    if 0xBBA <= type_id <= 0xBC6:
        return "game_system_or_world_component"
    if 0xFA0 <= type_id <= 0xFA6:
        return "region"
    if 0x1389 <= type_id <= 0x13A0:
        return "npc_or_hub_object"
    if 0x1771 <= type_id <= 0x1778:
        return "recipe_or_script_data"
    if 0x1B58 <= type_id <= 0x1B64:
        return "item"
    if 0x1B68 <= type_id <= 0x1B79:
        return "status_modifier"
    return "other"


def build_catalog(
    factory: dict[str, Any], catalog: dict[str, Any], asset_map: dict[str, Any]
) -> dict[str, Any]:
    classes = {entry["name"]: entry for entry in catalog["classes"]}
    class_art_uses = collect_class_art_uses(asset_map)
    output_types: list[dict[str, Any]] = []
    band_counts: dict[str, int] = {}

    for factory_type in factory["types"]:
        class_name = factory_type["class"]
        if class_name not in classes:
            raise ValueError("class catalog is missing %s" % class_name)
        class_entry = classes[class_name]
        band = type_band(factory_type["type_id"])
        band_counts[band] = band_counts.get(band, 0) + 1
        slots = class_entry["slots"]
        slot_by_offset = {slot["offset"]: slot for slot in slots}
        output_types.append(
            {
                **factory_type,
                "band": band,
                "vtable_slot_bytes": class_entry.get("slot_bytes"),
                "vtable_slots": slots,
                "lifecycle_anchors": {
                    label: slot_by_offset.get(offset)
                    for label, offset in (
                        ("deleting_destructor", "0x00"),
                        ("initialize", "0x04"),
                        ("tick", "0x08"),
                        ("virtual_0c", "0x0C"),
                        ("type_id", "0x14"),
                        ("virtual_1c", "0x1C"),
                    )
                },
                "class_art_uses": class_art_uses.get(class_name, []),
            }
        )

    return {
        "schema": "solomon-dark-native-game-object-catalog-v1",
        "source": {
            "factory_catalog": factory["source"],
            "class_catalog": catalog["source_log"],
            "asset_object_map": asset_map["source"],
        },
        "summary": {
            "type_count": len(output_types),
            "band_counts": dict(sorted(band_counts.items())),
            "type_with_direct_class_art_use_count": sum(
                bool(entry["class_art_uses"]) for entry in output_types
            ),
        },
        "types": output_types,
    }


def main() -> int:
    args = parse_args()
    factory = json.loads(args.factory_catalog.read_text(encoding="utf-8"))
    catalog = json.loads(args.class_catalog.read_text(encoding="utf-8"))
    asset_map = json.loads(args.asset_object_map.read_text(encoding="utf-8"))
    output = build_catalog(factory, catalog, asset_map)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(output["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
