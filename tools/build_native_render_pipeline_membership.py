#!/usr/bin/env python3
"""Join native renderer xrefs to RTTI/vtables and atlas consumers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XREFS = ROOT / "docs/reverse-engineering/native-full-render-pipeline-xrefs.json"
DEFAULT_CLASSES = ROOT / "docs/reverse-engineering/native-class-catalog.json"
DEFAULT_ATLASES = ROOT / "docs/reverse-engineering/native-atlas-consumers.json"
DEFAULT_OUTPUT = ROOT / "docs/reverse-engineering/native-full-render-pipeline-membership.json"
RENDER_SLOTS = frozenset({"0x0C", "0x24", "0x28"})


def load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def class_relations(catalog: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    relations: dict[str, list[dict[str, Any]]] = {}
    for native_class in catalog["classes"]:
        for slot in native_class["slots"]:
            relation = {
                "category": native_class["category"],
                "class": native_class["name"],
                "function_name": slot["name"],
                "render_slot": slot["offset"] in RENDER_SLOTS,
                "slot": slot["offset"],
                "vtable": native_class["vtable"],
            }
            relations.setdefault(slot["function"], []).append(relation)
    for values in relations.values():
        values.sort(key=lambda value: (value["class"], value["vtable"], value["slot"]))
    return relations


def atlas_relations(catalog: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    relations: dict[str, list[dict[str, Any]]] = {}
    for atlas in catalog["atlases"]:
        for consumer in atlas["consumers"]:
            destinations = [
                {
                    "destination_kind": destination["destination_kind"],
                    "first_record": destination["first_record"],
                    "last_record": destination["last_record"],
                    "object_field": destination["object_field"],
                }
                for destination in consumer["mapped_destinations"]
            ]
            relations.setdefault(consumer["address"], []).append({
                "atlas": atlas["name"],
                "destinations": destinations,
                "direct_mapping": bool(destinations),
            })
    for values in relations.values():
        values.sort(key=lambda value: value["atlas"])
    return relations


def disposition(
    address: str,
    pipeline_targets: frozenset[str],
    classes: list[dict[str, Any]],
    atlases: list[dict[str, Any]],
) -> str:
    if address in pipeline_targets:
        return "pipeline-internal"
    if any(relation["render_slot"] for relation in classes):
        return "vtable-render-member"
    if classes:
        return "class-owned-render-helper"
    if atlases:
        return "atlas-owned-render-helper"
    return "free-render-helper"


def state_write_disposition(write: dict[str, Any]) -> str:
    field = write["field"]
    source = (write.get("source") or "").upper()
    if field == "blend_selector":
        return {
            "0X0": "normal-srcalpha-invsrcalpha",
            "0X1": "additive-srcalpha-one",
            "0X2": "multiply-zero-srccolor",
        }.get(source, "dynamic-exact-selector")
    if field == "texture_color_selector":
        return {
            "0X0": "textured-modulate",
            "0X1": "untextured-diffuse",
        }.get(source, "dynamic-exact-selector")
    if field == "texture_address_selector":
        return {
            "0X0": "clamp",
            "0X1": "wrap",
        }.get(source, "dynamic-exact-selector")
    if field == "arena_saturation_request_from_app_base":
        return "arena-saturation-request"
    raise ValueError(f"unknown renderer state field: {field}")


def build(
    xrefs: dict[str, Any],
    class_catalog: dict[str, Any],
    atlas_catalog: dict[str, Any],
) -> dict[str, Any]:
    classes_by_function = class_relations(class_catalog)
    atlases_by_function = atlas_relations(atlas_catalog)
    target_addresses = frozenset(
        target["address"]
        for group in xrefs["groups"]
        for target in group["targets"]
    )

    callers = []
    for caller in xrefs["callers"]:
        address = caller["address"]
        classes = classes_by_function.get(address, [])
        atlases = atlases_by_function.get(address, [])
        callers.append({
            "address": address,
            "atlas_relations": atlases,
            "class_relations": classes,
            "disposition": disposition(address, target_addresses, classes, atlases),
            "name": caller["name"],
            "targets": caller["targets"],
        })

    orphan_references = sorted(
        (
            {
                "disposition": "data-or-vtable-reference",
                "group": group["name"],
                "site": site,
                "target": target["address"],
                "target_name": target["semantic_name"],
            }
            for group in xrefs["groups"]
            for target in group["targets"]
            for site in target["orphan_sites"]
        ),
        key=lambda value: (value["site"], value["target"]),
    )
    renderer_state_writes = [
        {
            **write,
            "class_relations": classes_by_function.get(write["function"], []),
            "disposition": state_write_disposition(write),
        }
        for write in xrefs["renderer_state_writes"]
    ]
    state_writes_by_function: dict[str, list[dict[str, Any]]] = {}
    for write in renderer_state_writes:
        state_writes_by_function.setdefault(write["function"], []).append({
            "address": write["address"],
            "disposition": write["disposition"],
            "field": write["field"],
            "source": write["source"],
        })
    class_state_programs = []
    for function, writes in sorted(state_writes_by_function.items()):
        for relation in classes_by_function.get(function, []):
            if not relation["render_slot"]:
                continue
            class_state_programs.append({
                "category": relation["category"],
                "class": relation["class"],
                "function": function,
                "function_name": relation["function_name"],
                "slot": relation["slot"],
                "vtable": relation["vtable"],
                "writes": writes,
            })

    disposition_counts: dict[str, int] = {}
    for caller in callers:
        key = caller["disposition"]
        disposition_counts[key] = disposition_counts.get(key, 0) + 1

    render_classes = sorted(
        {
            (
                relation["class"],
                relation["category"],
                relation["vtable"],
                relation["slot"],
                caller["address"],
                caller["name"],
            )
            for caller in callers
            for relation in caller["class_relations"]
            if relation["render_slot"]
        }
    )

    return {
        "schema": "solomon-dark-native-full-render-pipeline-membership-v1",
        "program": xrefs["program"],
        "executable_sha256": xrefs["executable_sha256"],
        "image_base": xrefs["image_base"],
        "graphics_subobject_offset": xrefs["graphics_subobject_offset"],
        "source_schemas": {
            "atlas_consumers": atlas_catalog["schema"],
            "class_catalog": class_catalog["schema"],
            "render_xrefs": xrefs["schema"],
        },
        "summary": {
            "caller_count": len(callers),
            "class_relation_count": sum(len(caller["class_relations"]) for caller in callers),
            "class_state_program_count": len(class_state_programs),
            "atlas_relation_count": sum(len(caller["atlas_relations"]) for caller in callers),
            "orphan_reference_count": len(orphan_references),
            "render_class_count": len(render_classes),
            "renderer_state_write_count": len(renderer_state_writes),
            "dispositions": dict(sorted(disposition_counts.items())),
        },
        "render_classes": [
            {
                "class": item[0],
                "category": item[1],
                "vtable": item[2],
                "slot": item[3],
                "function": item[4],
                "function_name": item[5],
                "disposition": "native-render-member",
            }
            for item in render_classes
        ],
        "class_state_programs": class_state_programs,
        "orphan_references": orphan_references,
        "renderer_state_writes": renderer_state_writes,
        "callers": callers,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xrefs", type=Path, default=DEFAULT_XREFS)
    parser.add_argument("--classes", type=Path, default=DEFAULT_CLASSES)
    parser.add_argument("--atlases", type=Path, default=DEFAULT_ATLASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    result = build(load(args.xrefs), load(args.classes), load(args.atlases))
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, separators=(",", ": ")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
