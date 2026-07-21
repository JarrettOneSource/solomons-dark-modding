#!/usr/bin/env python3
"""Parse every shipped wizard-skill CFG and bind it to the native skill IDs."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import operator
import re
from pathlib import Path
from typing import Any


SKILL_NAMES = [
    "Element of Ether", "Element of Fire", "Element of Air", "Element of Water",
    "Element of Earth", "Body Discipline", "Mind Discipline", "Arcane Discipline",
    "Magic Missile", "Smart Missiles", "More Missiles", "Call Leviathan",
    "Planewalker", "Piercing", "Ether Blast", "Phasing",
    "Fireball", "Embers", "Explode", "Embers to Imps", "Immolate",
    "Ring of Fire", "Burn", "Firewalker", "Lightning", "Chaining", "Stun",
    "Magic Storm", "Magic Tornado", "Hurricane", "Prismatic Shock", "Disintegrate",
    "Frost Jet", "Chill Wind", "Cone of Ice", "Ring of Ice", "Harden",
    "Cold Aura", "Hail", "Permafrost", "Boulder", "Earthquake", "Hasten Rocks",
    "Bind Rocks", "Rock Surge", "Raise Golem", "Stoneskin", "Gargantuan",
    "Teleport", "Magic Circle", "Magic Trap", "Dampen", "Spell Welding", "Flash",
    "Magic Shield", "Explosive Shield", "Mana Up", "Channel Mana", "Meditation",
    "Battle Mage", "Focus", "Siege Mage", "Resist Magic", "Creativity", "Health Up",
    "Enchant Staff", "Telekinesis", "Rush", "Deflect", "Resist Poison",
    "Faster Caster", "Fortunate Flailing", "Acid Rain", "Fire Wall", "Ether Drain",
    "Iron Golem", "Call Comet", "Turn Undead", "Mindstar", "Regenerate",
    "Plane Orb", "Reserved",
]


SAFE_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
SAFE_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def filename_for_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") + ".cfg"


def evaluate_number(expression: str) -> int | float:
    def evaluate(node: ast.AST) -> int | float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in SAFE_BINARY_OPERATORS:
            return SAFE_BINARY_OPERATORS[type(node.op)](
                evaluate(node.left), evaluate(node.right)
            )
        if isinstance(node, ast.UnaryOp) and type(node.op) in SAFE_UNARY_OPERATORS:
            return SAFE_UNARY_OPERATORS[type(node.op)](evaluate(node.operand))
        raise ValueError("unsupported numeric expression: %s" % expression)

    value = evaluate(ast.parse(expression, mode="eval"))
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def split_top_level(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quoted = False
    escaped = False
    for index, character in enumerate(value):
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
        elif character == "," and depth == 0:
            item = value[start:index].strip()
            if item:
                parts.append(item)
            start = index + 1
    tail = value[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def parse_value(value: str) -> Any:
    value = value.strip()
    if value.startswith("{") and value.endswith("}"):
        return [parse_value(item) for item in split_top_level(value[1:-1])]
    if value.startswith('"') and value.endswith('"'):
        return bytes(value[1:-1], "utf-8").decode("unicode_escape")
    return evaluate_number(value)


def scan_assignments(text: str) -> dict[str, dict[str, Any]]:
    assignments: dict[str, dict[str, Any]] = {}
    assignment_re = re.compile(r"(?m)^\s*(m[A-Za-z0-9_]+)\s*=")
    for match in assignment_re.finditer(text):
        key = match.group(1)
        index = match.end()
        depth = 0
        quoted = False
        escaped = False
        while index < len(text):
            character = text[index]
            if quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quoted = False
            elif character == '"':
                quoted = True
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
            elif character == ";" and depth == 0:
                break
            index += 1
        if index == len(text):
            raise ValueError("unterminated assignment %s" % key)
        raw_value = text[match.end():index].strip()
        if key in assignments:
            raise ValueError("duplicate assignment %s" % key)
        assignments[key] = {"value": parse_value(raw_value), "raw": raw_value}
    return assignments


def skill_family(skill_id: int) -> str:
    if skill_id < 5:
        return "element"
    if skill_id < 8:
        return "discipline"
    if skill_id < 16:
        return "ether"
    if skill_id < 24:
        return "fire"
    if skill_id < 32:
        return "air"
    if skill_id < 40:
        return "water"
    if skill_id < 48:
        return "earth"
    if skill_id < 56:
        return "arcane"
    if skill_id < 64:
        return "mind"
    if skill_id < 72:
        return "body"
    if skill_id < 80:
        return "advanced"
    return "runtime_only"


def build_catalog(skill_dir: Path) -> dict[str, Any]:
    if len(SKILL_NAMES) != 82:
        raise AssertionError("native resolver must contain 82 IDs")
    expected_files = {filename_for_name(name) for name in SKILL_NAMES[:80]}
    actual_files = {path.name.lower() for path in skill_dir.glob("*.cfg")}
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        extra = sorted(actual_files - expected_files)
        raise ValueError("skill CFG mismatch: missing=%r extra=%r" % (missing, extra))

    skills: list[dict[str, Any]] = []
    property_counts: dict[str, int] = {}
    for skill_id, name in enumerate(SKILL_NAMES):
        entry: dict[str, Any] = {
            "id": skill_id,
            "name": name,
            "family": skill_family(skill_id),
            "skills_atlas_icon_record": 27 + skill_id,
        }
        if skill_id >= 80:
            entry["config_path"] = None
            entry["config"] = None
            skills.append(entry)
            continue

        filename = filename_for_name(name)
        path = skill_dir / filename
        raw_bytes = path.read_bytes()
        assignments = scan_assignments(raw_bytes.decode("utf-8"))
        config = {key: assignment["value"] for key, assignment in assignments.items()}
        raw_values = {key: assignment["raw"] for key, assignment in assignments.items()}
        for key in config:
            property_counts[key] = property_counts.get(key, 0) + 1

        entry.update(
            {
                "config_path": "data/wizardskills/" + filename,
                "config_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "config": config,
                "raw_values": raw_values,
            }
        )
        skills.append(entry)

    return {
        "schema": "solomon-dark-native-skill-catalog-v1",
        "source": {
            "skill_directory": str(skill_dir),
            "native_name_resolver": "0x00657C00",
            "native_catalog_constructor": "0x00674EE0",
            "entry_stride": "0x70",
            "skills_atlas_icon_array_records": [27, 122],
        },
        "summary": {
            "native_skill_id_count": len(SKILL_NAMES),
            "shipped_config_count": len(actual_files),
            "runtime_only_id_count": 2,
            "config_property_count": len(property_counts),
            "config_property_file_counts": dict(sorted(property_counts.items())),
        },
        "skills": skills,
    }


def main() -> int:
    args = parse_args()
    output = build_catalog(args.skill_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(output["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
