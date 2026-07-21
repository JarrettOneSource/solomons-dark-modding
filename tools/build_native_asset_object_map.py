#!/usr/bin/env python3
"""Join atlas record destinations to native RTTI classes and virtual slots."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


DestinationKey = tuple[str, str, int, int, int | None]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--atlas-consumers", type=Path, required=True)
    parser.add_argument("--class-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def destination_key(destination: dict[str, Any]) -> DestinationKey:
    return (
        destination["destination_kind"],
        destination["object_field"],
        destination["first_record"],
        destination["last_record"],
        destination.get("aux_group"),
    )


def inventory_destinations(atlas: dict[str, Any]) -> list[dict[str, Any]]:
    result = [dict(destination) for destination in atlas["builder_trace"]["destinations"]]
    result.extend(
        {
            **destination,
            "destination_kind": "aux",
            "aux_group": destination["group"],
        }
        for destination in atlas["builder_trace"]["aux_destinations"]
    )
    return result


def build_function_relations(
    catalog: dict[str, Any],
) -> tuple[dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
    slots: dict[str, list[dict[str, str]]] = defaultdict(list)
    references: dict[str, list[dict[str, str]]] = defaultdict(list)
    for class_entry in catalog["classes"]:
        class_identity = {
            "class": class_entry["name"],
            "vtable": class_entry["vtable"],
        }
        for slot in class_entry["slots"]:
            slots[slot["function"]].append(
                {
                    **class_identity,
                    "slot": slot["offset"],
                }
            )
        for reference in class_entry["vtable_references"]:
            references[reference["function"]].append(class_identity)

    for relation_map in (slots, references):
        for relations in relation_map.values():
            relations.sort(key=lambda item: tuple(item.values()))
    return slots, references


def build_map(
    inventory: dict[str, Any],
    consumers: dict[str, Any],
    catalog: dict[str, Any],
    sources: dict[str, str],
) -> dict[str, Any]:
    consumers_by_atlas = {atlas["name"]: atlas for atlas in consumers["atlases"]}
    function_slots, function_references = build_function_relations(catalog)

    output_atlases: list[dict[str, Any]] = []
    all_consumer_functions: set[str] = set()
    class_mapped_functions: set[str] = set()
    destination_count = 0
    destinations_with_consumers = 0

    for inventory_atlas in inventory["atlases"]:
        name = inventory_atlas["name"]
        if name not in consumers_by_atlas:
            raise ValueError("consumer map is missing atlas %s" % name)
        consumer_atlas = consumers_by_atlas[name]

        destinations: dict[DestinationKey, dict[str, Any]] = {}
        for destination in inventory_destinations(inventory_atlas):
            entry = {
                "destination_kind": destination["destination_kind"],
                "object_field": destination["object_field"],
                "first_record": destination["first_record"],
                "last_record": destination["last_record"],
                "record_count": destination["last_record"] - destination["first_record"] + 1,
                **(
                    {"aux_group": destination["aux_group"]}
                    if "aux_group" in destination
                    else {}
                ),
                "consumer_functions": [],
            }
            key = destination_key(entry)
            if key in destinations:
                raise ValueError("duplicate destination for %s: %r" % (name, key))
            destinations[key] = entry

        for function in consumer_atlas["consumers"]:
            if not function["mapped_destinations"]:
                continue
            address = function["address"]
            all_consumer_functions.add(address)
            slots = function_slots.get(address, [])
            references = function_references.get(address, [])
            if slots or references:
                class_mapped_functions.add(address)
            function_entry = {
                "address": address,
                "name": function["name"],
                "vtable_slots": slots,
                "vtable_install_references": references,
            }
            for mapped_destination in function["mapped_destinations"]:
                key = destination_key(mapped_destination)
                if key not in destinations:
                    raise ValueError(
                        "consumer destination absent from inventory for %s: %r"
                        % (name, key)
                    )
                destinations[key]["consumer_functions"].append(function_entry)

        destination_entries = sorted(
            destinations.values(),
            key=lambda entry: (
                entry["first_record"],
                entry["last_record"],
                entry["object_field"],
            ),
        )
        for destination in destination_entries:
            unique_functions = {
                entry["address"]: entry for entry in destination["consumer_functions"]
            }
            destination["consumer_functions"] = [
                unique_functions[address] for address in sorted(unique_functions)
            ]
            destination["consumer_function_count"] = len(unique_functions)
            destination_count += 1
            if unique_functions:
                destinations_with_consumers += 1

        output_atlases.append(
            {
                "name": name,
                "singleton": consumer_atlas["singleton"],
                "builder": inventory_atlas["builder"],
                "record_count": inventory_atlas["record_count"],
                "destinations": destination_entries,
            }
        )

    return {
        "schema": "solomon-dark-native-asset-object-map-v1",
        "source": sources,
        "summary": {
            "atlas_count": len(output_atlases),
            "destination_count": destination_count,
            "destination_with_consumer_count": destinations_with_consumers,
            "direct_consumer_function_count": len(all_consumer_functions),
            "consumer_function_with_class_relation_count": len(class_mapped_functions),
        },
        "atlases": output_atlases,
    }


def main() -> int:
    args = parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    consumers = json.loads(args.atlas_consumers.read_text(encoding="utf-8"))
    catalog = json.loads(args.class_catalog.read_text(encoding="utf-8"))
    output = build_map(
        inventory,
        consumers,
        catalog,
        {
            "inventory": str(args.inventory),
            "atlas_consumers": str(args.atlas_consumers),
            "class_catalog": str(args.class_catalog),
        },
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(output["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
