#!/usr/bin/env python3
"""Parse stock items.cfg and bind recipes/effects to the recovered native ABI."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from build_native_skill_catalog import SKILL_NAMES


ITEM_TYPE_IDS = {
    "ring": 0x1B5A,
    "amulet": 0x1B5B,
    "staff": 0x1B5C,
    "hat": 0x1B5D,
    "robe": 0x1B5E,
    "wand": 0x1B63,
}

RARITY_IDS = {"COMMON": 0, "RARE": 1, "EPIC": 2}

CLASS_IDS = {
    "ether": 0,
    "fire": 1,
    "air": 2,
    "water": 3,
    "earth": 4,
    "body": 5,
    "mind": 6,
    "arcane": 7,
}

FX_KIND_NAMES = [
    "FX_SPELLDAMAGE",
    "FX_SPELLCLASSDAMAGE",
    "FX_MELEEDAMAGE",
    "FX_GRANTSKILL",
    "FX_BOOSTSKILL",
    "FX_BOOSTSKILLCLASS",
    "FX_ADDSKILL",
    "FX_ALLSKILLS",
    "FX_MANARECOVERY",
    "FX_MANACOST",
    "FX_SPELLCLASSMANACOST",
    "FX_CASTSPEED",
    "FX_SPELLCLASSCASTSPEED",
    "FX_GOLDBONUS",
    "FX_ORBPULL",
    "FX_HPRECOVERY",
    "FX_WALKSPEED",
    "FX_RESISTDAMAGE",
    "FX_RESISTMAGIC",
    "FX_RESISTPOISON",
    "FX_RECHARGE",
    "FX_RECHARGECLASS",
    "FX_MAXHP",
    "FX_MAXMANA",
    "FX_ONESPELLDAMAGE",
    "FX_MAXLEVIATHAN",
    "FX_MAXMAGICSTORM",
    "FX_MAXRINGOFFIRE",
    "FX_MAXGOLEM",
    "FX_MAXRINGOFICE",
    "FX_MAXEMBERSTOIMPS",
    "FX_MAXDISINTEGRATION",
    "FX_MAXETHERCHARGE",
    "FX_MAXHARDEN",
    "FX_MAXROCKSURGE",
    "FX_MINDBLAST",
    "FX_MAXWELD",
    "FX_WELDEFFECT",
    "FX_WELDCALLING",
]

FX_DISPLAY_NAMES = [
    "Spell Damage (All Spells)",
    "Spell Damage (Spell Class)",
    "Melee Damage",
    "Grant Skill",
    "Boost Skill",
    "Boost Skill Class",
    "Add Skill",
    "Modify All Skills",
    "Mana Recovery",
    "Mana Cost (All Spells)",
    "Mana Cost (Spell Class)",
    "Cast Speed (All Spells)",
    "Cast Speed (Spell Class)",
    "Gold Bonus",
    "Pull Orbs",
    "Recover Health",
    "Walk Speed",
    "Resist Physical Damage",
    "Resist Magical Damage",
    "Resist Poison Damage",
    "Recharge Speed (All Spells)",
    "Recharge Speed (Spell Class)",
    "Modify Max Health",
    "Modify Max Mana",
    "Spell Damage (Specific Spell)",
    "Maximize Leviathan",
    "Maximize Magic Storm",
    "Maximize Ring of Fire",
    "Maximize Golem",
    "Maximize Ring of Ice",
    "Maximize Embers To Imps",
    "Maximize Disintegration",
    "Maximize EtherCharge",
    "Maximize Harden",
    "Maximize Rock Surge",
    "Emit Mindblast on Levelup",
    "Energize Weld Components",
    "Enhance Weld Effect",
    "+Bias Skills for Welding",
]

FX_KIND_IDS = {name: index + 1 for index, name in enumerate(FX_KIND_NAMES)}
SKILL_IDS = {name.casefold(): index for index, name in enumerate(SKILL_NAMES)}

NUMBER_RE = re.compile(r"^(?P<prefix>[+*-]?)(?P<number>(?:\d+(?:\.\d*)?|\.\d+))(?P<percent>%?)$")


ART_BINDINGS: dict[str, dict[str, Any]] = {
    "ring": {
        "inventory_atlas": "Inventory",
        "selector_range": [0, 11],
        "inventory_record_formula": "52 + IMAGE",
        "attachment": None,
    },
    "amulet": {
        "inventory_atlas": "Inventory",
        "selector_range": [0, 11],
        "inventory_record_formula": "18 + IMAGE; secondary 30 + floor(IMAGE / 6)",
        "attachment": None,
    },
    "staff": {
        "inventory_atlas": "Inventory",
        "selector_range": [0, 5],
        "inventory_record_formula": "72 + IMAGE",
        "attachment": {
            "atlas": "Clothes",
            "selector_records": "5..10",
            "optional_glow_records": "11..12",
            "pose_banks": ["3244..3483", "3484..3723"],
            "renderer": "0x00578D20",
            "attachment_point_helpers": ["0x005795E0", "0x00579680"],
            "note": "An optional glow-color argument adds records 11..12 and a generated four-vertex colored/flickering quad; native animation/frame tables select the pose-bank records and attachment points.",
        },
    },
    "hat": {
        "inventory_atlas": "Inventory",
        "selector_range": [0, 3],
        "inventory_record_formula": "34 + IMAGE and 38 + IMAGE",
        "attachment": {
            "atlas": "Clothes",
            "records": "dynamic selector/frame tables at DAT_00B2E9A4 and DAT_00B2E9B4",
            "renderer": "0x005758F0",
            "note": "Primary and secondary layers are tinted independently from item +0x88/+0x98.",
        },
    },
    "robe": {
        "inventory_atlas": "Inventory",
        "selector_range": [0, 2],
        "inventory_record_formula": "64 + IMAGE and 67 + IMAGE",
        "attachment": {
            "atlas": "Clothes",
            "records": ["5..10", "220..315", "1588..3243"],
            "renderer": "0x00577DA0",
            "note": "Primary and secondary layers are tinted independently from item +0x88/+0x98.",
        },
    },
    "wand": {
        "inventory_atlas": "Inventory",
        "selector_range": [0, 5],
        "inventory_record_formula": "78 + IMAGE",
        "attachment": {
            "atlas": "Clothes",
            "records": [15],
            "renderer": "0x00579820",
            "note": "The wand beam/line geometry is assembled dynamically around the attachment point.",
        },
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--source-label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def element_text(element: ET.Element) -> str:
    return "".join(element.itertext()).strip()


def parse_number(token: str) -> dict[str, Any] | None:
    match = NUMBER_RE.fullmatch(token)
    if match is None:
        return None
    value = float(match.group("number"))
    prefix = match.group("prefix")
    if prefix == "-":
        value = -value
    if value.is_integer():
        value = int(value)
    percentage = bool(match.group("percent"))
    if prefix == "*":
        operator_id = 1
        operator_name = "multiply"
    elif percentage:
        operator_id = 2
        operator_name = "percentage"
    else:
        operator_id = 0
        operator_name = "flat"
    return {
        "operator_id": operator_id,
        "operator": operator_name,
        "magnitude": value,
        "token": token,
    }


def parse_fx(raw: str, source_index: int, scope: str, owner: str) -> dict[str, Any]:
    tokens = shlex.split(raw, posix=True)
    if not tokens:
        raise ValueError("empty FX declaration")
    kind = tokens.pop(0).upper()
    if kind not in FX_KIND_IDS:
        raise ValueError(f"unknown native FX kind: {kind}")

    numeric: dict[str, Any] | None = None
    class_name: str | None = None
    class_id: int | None = None
    skill_name: str | None = None
    skill_id: int | None = None
    unparsed: list[str] = []

    for token in tokens:
        parsed_number = parse_number(token)
        if parsed_number is not None and numeric is None:
            numeric = parsed_number
            continue
        folded = token.casefold()
        if folded in CLASS_IDS and class_name is None:
            class_name = folded.title()
            class_id = CLASS_IDS[folded]
            continue
        if folded in SKILL_IDS and skill_name is None:
            skill_id = SKILL_IDS[folded]
            skill_name = SKILL_NAMES[skill_id]
            continue
        unparsed.append(token)

    if numeric is None:
        numeric = {
            "operator_id": 0,
            "operator": "flat",
            "magnitude": 0,
            "token": None,
        }

    target_kind: str | None = None
    target_id: int | None = None
    target_name: str | None = None
    if skill_id is not None:
        target_kind, target_id, target_name = "skill", skill_id, skill_name
    elif class_id is not None:
        target_kind, target_id, target_name = "class", class_id, class_name

    return {
        "source_index": source_index,
        "scope": scope,
        "owner": owner,
        "raw": raw,
        "kind": kind,
        "kind_id": FX_KIND_IDS[kind],
        "display_name": FX_DISPLAY_NAMES[FX_KIND_IDS[kind] - 1],
        "operator": numeric["operator"],
        "operator_id": numeric["operator_id"],
        "magnitude": numeric["magnitude"],
        "magnitude_declared": numeric["token"] is not None,
        "magnitude_token": numeric["token"],
        "target_kind": target_kind,
        "target_id": target_id,
        "target_name": target_name,
        "unparsed_tokens": unparsed,
    }


def parse_color(raw: str) -> dict[str, Any]:
    components = [float(part.strip()) for part in raw.split(",")]
    if len(components) not in (3, 4):
        raise ValueError(f"color must have three or four components: {raw!r}")
    rgba = components + ([255.0] if len(components) == 3 else [])
    normalized = [component / 255.0 if component > 1.0 else component for component in rgba]
    source_components = [int(value) if value.is_integer() else value for value in components]
    return {
        "raw": raw,
        "source_components": source_components,
        "normalized_rgba": normalized,
    }


def inventory_records(item_type: str, image: int) -> list[int]:
    if item_type == "ring":
        return [52 + image]
    if item_type == "amulet":
        return [18 + image, 30 + image // 6]
    if item_type == "staff":
        return [72 + image]
    if item_type == "hat":
        return [34 + image, 38 + image]
    if item_type == "robe":
        return [64 + image, 67 + image]
    if item_type == "wand":
        return [78 + image]
    raise ValueError(f"unsupported item type: {item_type}")


def parse_document(raw_bytes: bytes, source_label: str) -> dict[str, Any]:
    text = raw_bytes.decode("utf-8-sig")
    root = ET.fromstring("<ROOT>" + text + "</ROOT>")
    sets: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    all_fx: list[dict[str, Any]] = []
    comments: list[str] = []

    def add_fx(raw: str, scope: str, owner: str) -> dict[str, Any]:
        effect = parse_fx(raw, len(all_fx), scope, owner)
        all_fx.append(effect)
        return effect

    def add_item(element: ET.Element, parent_set_index: int | None) -> int:
        fields: dict[str, list[str]] = {}
        for child in element:
            fields.setdefault(child.tag.upper(), []).append(element_text(child))
        if "TYPE" not in fields or "NAME" not in fields:
            raise ValueError("ITEM requires TYPE and NAME")
        item_type = fields["TYPE"][-1].casefold()
        if item_type not in ITEM_TYPE_IDS:
            raise ValueError(f"unsupported stock recipe type: {item_type}")
        name = fields["NAME"][-1]
        image_declarations = [int(value, 10) for value in fields.get("IMAGE", [])]
        image = image_declarations[-1] if image_declarations else 0
        lower, upper = ART_BINDINGS[item_type]["selector_range"]
        if not lower <= image <= upper:
            raise ValueError(f"{name}: IMAGE {image} is outside {item_type} range {lower}..{upper}")
        rarity = fields.get("RARITY", ["COMMON"])[-1].upper()
        if rarity not in RARITY_IDS:
            raise ValueError(f"{name}: unknown rarity {rarity}")
        level = int(fields.get("LEVEL", ["0"])[-1], 10)
        item_fx = [add_fx(raw, "item", name) for raw in fields.get("FX", [])]
        color1_values = [parse_color(raw) for raw in fields.get("COLOR1", [])]
        color2_values = [parse_color(raw) for raw in fields.get("COLOR2", [])]
        source_index = len(items)
        parent_name = sets[parent_set_index]["name"] if parent_set_index is not None else None
        entry = {
            "source_index": source_index,
            "source_index_is_runtime_recipe_uid": False,
            "parent_set_index": parent_set_index,
            "parent_set_name": parent_name,
            "type": item_type,
            "native_type_id": ITEM_TYPE_IDS[item_type],
            "native_type_id_hex": f"0x{ITEM_TYPE_IDS[item_type]:04X}",
            "name": name,
            "description": fields.get("DESCRIPTION", [""])[-1],
            "image_declarations": image_declarations,
            "effective_image": image,
            "duplicate_image_declaration": len(image_declarations) > 1,
            "level": level,
            "rarity": rarity.title(),
            "rarity_id": RARITY_IDS[rarity],
            "color1_declarations": color1_values,
            "effective_color1": color1_values[-1] if color1_values else None,
            "color2_declarations": color2_values,
            "effective_color2": color2_values[-1] if color2_values else None,
            "fx": item_fx,
            "art": {
                "inventory_atlas": "Inventory",
                "inventory_records": inventory_records(item_type, image),
                "inventory_renderer": {
                    "ring": "0x005788B0",
                    "amulet": "0x00578910",
                    "staff": "0x00578A90",
                    "hat": "0x005779B0",
                    "robe": "0x00577B90",
                    "wand": "0x00579720",
                }[item_type],
                "attachment_binding": item_type if ART_BINDINGS[item_type]["attachment"] else None,
            },
        }
        items.append(entry)
        return source_index

    for element in root:
        tag = element.tag.upper()
        if tag == "COMMENT":
            comments.append(element_text(element))
            continue
        if tag == "IGNORE":
            continue
        if tag == "ITEM":
            add_item(element, None)
            continue
        if tag != "ITEMSET":
            raise ValueError(f"unexpected top-level element: {element.tag}")
        name_element = element.find("NAME")
        if name_element is None:
            raise ValueError("ITEMSET requires NAME")
        set_index = len(sets)
        set_name = element_text(name_element)
        set_entry = {
            "source_index": set_index,
            "name": set_name,
            "fx": [],
            "item_source_indexes": [],
        }
        sets.append(set_entry)
        for child in element:
            child_tag = child.tag.upper()
            if child_tag == "FX":
                set_entry["fx"].append(add_fx(element_text(child), "set", set_name))
            elif child_tag == "ITEM":
                set_entry["item_source_indexes"].append(add_item(child, set_index))
            elif child_tag != "NAME":
                raise ValueError(f"{set_name}: unexpected ITEMSET element {child.tag}")

    type_counts = Counter(item["type"] for item in items)
    rarity_counts = Counter(item["rarity"] for item in items)
    effect_counts = Counter(effect["kind"] for effect in all_fx)
    set_member_count = sum(len(entry["item_source_indexes"]) for entry in sets)
    unparsed = [effect for effect in all_fx if effect["unparsed_tokens"]]
    if unparsed:
        raise ValueError(f"unparsed stock FX tokens: {unparsed!r}")

    return {
        "schema": "solomon-dark-native-item-catalog-v1",
        "source": {
            "label": source_label,
            "size": len(raw_bytes),
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "native_itemset_parser": "0x00574D60",
            "native_recipe_parser": "0x00573570",
            "native_fx_parser": "0x005722A0",
            "native_recipe_uid_counter": "0x005B98C0 / Game.ItemRecipeUID",
            "native_live_object_uid_counter": "0x005B9870 / Game.UID",
            "source_order_is_not_runtime_recipe_uid": True,
        },
        "summary": {
            "item_set_count": len(sets),
            "item_count": len(items),
            "set_member_item_count": set_member_count,
            "top_level_item_count": len(items) - set_member_count,
            "fx_count": len(all_fx),
            "item_fx_count": sum(len(item["fx"]) for item in items),
            "set_fx_count": sum(len(entry["fx"]) for entry in sets),
            "type_counts": dict(sorted(type_counts.items())),
            "rarity_counts": dict(sorted(rarity_counts.items())),
            "fx_kind_counts": dict(sorted(effect_counts.items())),
            "image_declaration_count": sum(len(item["image_declarations"]) for item in items),
            "duplicate_image_item_count": sum(item["duplicate_image_declaration"] for item in items),
        },
        "comments": comments,
        "class_ids": {name.title(): value for name, value in CLASS_IDS.items()},
        "fx_kinds": [
            {"kind_id": index + 1, "token": token, "display_name": FX_DISPLAY_NAMES[index]}
            for index, token in enumerate(FX_KIND_NAMES)
        ],
        "art_bindings": ART_BINDINGS,
        "item_sets": sets,
        "items": items,
    }


def build_catalog(path: Path, source_label: str) -> dict[str, Any]:
    return parse_document(path.read_bytes(), source_label)


def main() -> int:
    args = parse_args()
    catalog = build_catalog(args.input, args.source_label)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(catalog["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
