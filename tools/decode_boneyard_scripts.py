#!/usr/bin/env python3
"""Decode Solomon Dark Trigger, TimeLine, and recipe data from a .boneyard file."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

import inspect_boneyard


TRIGGER_TYPES = {
    1: "START GAME",
    2: "START WAVE",
    3: "END WAVE",
    4: "END GAME",
    5: "WIN GAME",
    6: "LOSE GAME",
    7: "PLAYER STEPS ON",
    8: "MANUAL",
    9: "INTERVAL",
    10: "PLAYER PRESSURE",
    11: "MONSTER DIES HERE",
    12: "BOSS HP",
    13: "LEVEL UP",
    14: "FIND SOLOMON",
    15: "SOLOMON RUNS",
}

PREDICATES = {
    1: "WAVE NUMBER IS",
    2: "OBJECT IS AT",
    3: "PLAYER HAS ITEM",
    4: "FLAG IS",
    5: "COUNTER IS",
    6: "GAME DATA IS",
    7: "PLAYER LEVEL IS",
    8: "PLAYER ELEMENT IS",
    9: "PLAYER DISCIPLINE IS",
    10: "PLAYER SKILL LEVEL IS",
    11: "PLAYER GOLD IS",
    12: "PLAYER HEALTH IS",
    13: "PLAYER MANA IS",
    14: "RANDOM ROLL",
}

# TriggerEditor_BuildLogic (0x004B6750) registers all of these. IDs 1005 and
# 1043 are each shown in two editor categories, yielding 94 menu entries but
# 92 unique IDs. Runtime-only 1014 and the unused gaps are deliberately absent.
ACTIONS = {
    1001: "ECHO",
    1002: "SLEEP",
    1003: "START NEXT WAVE",
    1004: "START NEXT WAVE WHEN",
    1005: "FORCE SPAWNS",
    1006: "SPAWN CUSTOM MONSTER",
    1007: "SPAWN CUSTOM MONSTER GROUP",
    1008: "DROP ITEM",
    1009: "DISABLE TRIGGER",
    1010: "ENABLE TRIGGER",
    1011: "TRIP TRIGGER",
    1012: "TRY TRIGGER",
    1013: "DELETE TRIGGER",
    1015: "DROP RANDOM ITEM",
    1016: "DROP GOLD",
    1017: "DROP RANDOM GOLD",
    1018: "LIMIT DROPS",
    1019: "FORTIFY MONSTER RECIPE",
    1020: "SPAWN PARTIAL MONSTER GROUP",
    1023: "AUTO LEVELUP ON/OFF",
    1024: "INVENTORY BUTTON ON/OFF",
    1025: "SPELLBOOK BUTTON ON/OFF",
    1026: "BELT BUTTONS ON/OFF",
    1027: "PLAYER MOVING ON/OFF",
    1028: "PLAYER CASTING ON/OFF",
    1029: "INVOKE INVENTORY",
    1030: "INVOKE SPELLBOOK",
    1031: "INVOKE SKILL PICKER",
    1032: "LOOP",
    1033: "END LOOP",
    1034: "INCREASE PLAYER SKILL",
    1035: "TELEPORT PLAYER",
    1036: "PUT ITEM IN INVENTORY",
    1037: "TAKE ITEM FROM INVENTORY",
    1038: "CALL SCRIPT",
    1039: "SPAWN NPC",
    1040: "SLEEP UNTIL",
    1041: "REFERENCE NPCS",
    1042: "REMOVE NPCS",
    1043: "CLEAR REFERENCES",
    1044: "NPCS LOOK AT",
    1045: "MOVE NPCS",
    1046: "SET NPC IDLE BEHAVIOR",
    1047: "NPCS NEED HELP",
    1048: "PLACE SOLOMON DIGGING",
    1049: "NPCS FLEE",
    1051: "SYSTEM / DARK CODE",
    1052: "MONSTER FLAIR",
    1053: "REFERENCE MONSTERS",
    1054: "SET FLAG",
    1055: "SET COUNTER",
    1056: "INCREMENT COUNTER",
    1057: "DECREMENT COUNTER",
    1058: "FORCE SKILL PICK",
    1059: "DROP POTION",
    1060: "DO EXPLOSION AT",
    1061: "START FIRE AT",
    1062: "WIN LEVEL",
    1063: "LOSE LEVEL",
    1064: "CHANGE WEATHER",
    1065: "LOCK/UNLOCK CAMERA",
    1066: "DESTROY OFF-CAMERA OBJECTS",
    1067: "START TIMELINE",
    1068: "STOP TIMELINE",
    1069: "PAUSE/UNPAUSE TIMELINE",
    1070: "JUMP TO LABEL",
    1071: "JUMP TO NEXT EVENT",
    1072: "DISABLE SKILL PICK",
    1073: "ENABLE SKILL PICK",
    1074: "TAKE GOLD FROM INVENTORY",
    1075: "REJUVENATE",
    1076: "ENDIF",
    1077: "LABEL",
    1078: "GOTO",
    1079: "LEVEL UP PLAYER",
    1080: "XP ACCUMULATION ON/OFF",
    1081: "GRANT XP",
    1082: "SPAWN DEFAULT MONSTER",
    1083: "SOLOMON DRIVE-BY",
    1084: "RUN SOLOMON AWAY",
    1085: "SLEEP UNTIL SOLOMON IS GONE",
    1086: "DROP KEY",
    1087: "ENABLE/DISABLE DROPS",
    1088: "REMOVE UNSEEN MONSTERS",
    1089: "REMOVE OFFSCREEN MONSTERS",
    1090: "MODIFY XP ACCUMULATION",
    1091: "PREVENT LULLS",
    1092: "OFFSCREEN MAGIC",
    1093: "CHANGE NPCS TO TARGETS",
    1094: "SET MUSIC",
    1095: "CHANGE NPCS TO ALLIES",
    1096: "REDUCE REFERENCED MONSTER HP",
}

TIMELINE_EVENT_TYPES = {
    0: "SPAWN EVENT",
    1: "TRIGGER EVENT",
    2: "PAUSE TIME LINE",
    3: "ADVANCE WAVE",
    4: "LABEL",
    5: "JUMP TO LABEL",
    6: "SPAWN LOCATING",
    7: "RUNTIME SPAWN EVENT",
}

SPAWN_RECORD_TYPES = {
    3001: "DEFAULT MONSTER",
    3002: "CUSTOM MONSTER RECIPE",
    3003: "MONSTER UID GROUP",
}

OPERAND_TYPES = {
    0: "none",
    1: "int",
    2: "float",
    3: "string",
    4: "float2",
    5: "uid",
}

RECIPE_TYPES = {
    6001: "MonsterRecipe",
    6002: "UIDGroup",
    6003: "ItemRecipe",
    6004: "NPCRecipe",
    6005: "ItemSet",
}


class ScriptDecodeError(ValueError):
    """Raised when a scripting payload violates the recovered native layout."""


class PayloadReader:
    def __init__(self, payload: bytes, label: str) -> None:
        self.payload = payload
        self.label = label
        self.offset = 0

    def _take(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.payload):
            raise ScriptDecodeError(
                f"{self.label}: need {size} bytes at payload +0x{self.offset:X}, "
                f"only {len(self.payload) - self.offset} remain"
            )
        value = self.payload[self.offset:end]
        self.offset = end
        return value

    def u8(self) -> int:
        return self._take(1)[0]

    def i8(self) -> int:
        return struct.unpack("<b", self._take(1))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self._take(4))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self._take(4))[0]

    def string(self) -> str:
        size = self.u32()
        if size == 0:
            raise ScriptDecodeError(
                f"{self.label}: native String has zero size at payload +0x{self.offset - 4:X}"
            )
        raw = self._take(size)
        if raw[-1] != 0 or b"\0" in raw[:-1]:
            raise ScriptDecodeError(
                f"{self.label}: native String must contain exactly one terminal NUL"
            )
        try:
            return raw[:-1].decode("utf-8")
        except UnicodeDecodeError as error:
            raise ScriptDecodeError(f"{self.label}: invalid UTF-8 native String") from error

    def float2(self) -> list[float]:
        return [self.f32(), self.f32()]

    def rect4(self) -> list[float]:
        return [self.f32(), self.f32(), self.f32(), self.f32()]

    def finish(self) -> None:
        if self.offset != len(self.payload):
            raise ScriptDecodeError(
                f"{self.label}: {len(self.payload) - self.offset} unparsed payload bytes "
                f"start at +0x{self.offset:X}"
            )


def _object_manager(
    node: inspect_boneyard.Chunk,
    label: str,
) -> tuple[list[int], tuple[inspect_boneyard.Chunk, ...]]:
    reader = PayloadReader(node.payload, label)
    count = reader.u32()
    type_ids = [reader.u32() for _ in range(count)]
    reader.finish()
    if len(node.children) != count:
        raise ScriptDecodeError(
            f"{label}: manager declares {count} objects but has {len(node.children)} children"
        )
    return type_ids, node.children


def _counted_u32(node: inspect_boneyard.Chunk, label: str) -> list[int]:
    reader = PayloadReader(node.payload, label)
    values = [reader.u32() for _ in range(reader.u32())]
    reader.finish()
    if node.children:
        raise ScriptDecodeError(f"{label}: scalar array unexpectedly has children")
    return values


def _counted_u8(node: inspect_boneyard.Chunk, label: str) -> list[int]:
    reader = PayloadReader(node.payload, label)
    values = [reader.u8() for _ in range(reader.u32())]
    reader.finish()
    if node.children:
        raise ScriptDecodeError(f"{label}: scalar array unexpectedly has children")
    return values


def _counted_f32(node: inspect_boneyard.Chunk, label: str) -> list[float]:
    reader = PayloadReader(node.payload, label)
    values = [reader.f32() for _ in range(reader.u32())]
    reader.finish()
    if node.children:
        raise ScriptDecodeError(f"{label}: scalar array unexpectedly has children")
    return values


def _counted_strings(node: inspect_boneyard.Chunk, label: str) -> list[str]:
    reader = PayloadReader(node.payload, label)
    values = [reader.string() for _ in range(reader.u32())]
    reader.finish()
    if node.children:
        raise ScriptDecodeError(f"{label}: String array unexpectedly has children")
    return values


def _code_name(code_id: int) -> str:
    if code_id in PREDICATES:
        return PREDICATES[code_id]
    if code_id in ACTIONS:
        return ACTIONS[code_id]
    if code_id in SPAWN_RECORD_TYPES:
        return SPAWN_RECORD_TYPES[code_id]
    if code_id == 1014:
        return "LEGACY RUNTIME ACTION 1014"
    return "UNKNOWN"


def _decode_code_body(
    node: inspect_boneyard.Chunk,
    label: str,
) -> dict[str, Any]:
    # Every pointer-held CodeLine gets an empty wrapper chunk; the embedded
    # Trigger CodeLine is synchronized directly and therefore has no wrapper.
    if not node.payload and len(node.children) == 1:
        node = node.children[0]
    reader = PayloadReader(node.payload, label)
    operand_count = reader.u32()
    operands: list[dict[str, Any]] = []
    for index in range(operand_count):
        operand_type = reader.u8()
        if operand_type == 0:
            value = None
        elif operand_type == 1 or operand_type == 5:
            value: Any = reader.u32()
        elif operand_type == 2:
            value = reader.f32()
        elif operand_type == 3:
            value = reader.string()
        elif operand_type == 4:
            value = reader.float2()
        else:
            raise ScriptDecodeError(
                f"{label}: operand {index} has unknown type {operand_type}"
            )
        operands.append(
            {
                "type": operand_type,
                "typeName": OPERAND_TYPES[operand_type],
                "value": value,
            }
        )

    has_nested = bool(reader.u8())
    nested_count = reader.u32() if has_nested else 0
    reader.finish()
    expected_children = nested_count * 2
    if len(node.children) != expected_children:
        raise ScriptDecodeError(
            f"{label}: nested flag/count require {expected_children} children, "
            f"found {len(node.children)}"
        )
    nested = [
        _decode_code_line_pair(
            node.children[index * 2],
            node.children[index * 2 + 1],
            f"{label}.nested[{index}]",
        )
        for index in range(nested_count)
    ]
    return {"operands": operands, "nested": nested}


def _decode_code_line_pair(
    header: inspect_boneyard.Chunk,
    body: inspect_boneyard.Chunk,
    label: str,
) -> dict[str, Any]:
    if header.children:
        raise ScriptDecodeError(f"{label}: CodeLine header unexpectedly has children")
    reader = PayloadReader(header.payload, f"{label}.header")
    code_id = reader.u32()
    flags = reader.u32()
    reader.finish()
    decoded = {
        "id": code_id,
        "name": _code_name(code_id),
        "flags": flags,
        "negated": bool(flags & 1) if code_id in PREDICATES else False,
    }
    decoded.update(_decode_code_body(body, f"{label}.body"))
    return decoded


def _decode_code_list(
    node: inspect_boneyard.Chunk,
    label: str,
) -> list[dict[str, Any]]:
    reader = PayloadReader(node.payload, label)
    count = reader.u32()
    reader.finish()
    if len(node.children) != count * 2:
        raise ScriptDecodeError(
            f"{label}: declares {count} CodeLines but has {len(node.children)} children"
        )
    return [
        _decode_code_line_pair(
            node.children[index * 2],
            node.children[index * 2 + 1],
            f"{label}[{index}]",
        )
        for index in range(count)
    ]


def _decode_trigger(
    wrapper: inspect_boneyard.Chunk,
    index: int,
) -> dict[str, Any]:
    label = f"Trigger[{index}]"
    if len(wrapper.children) != 2:
        raise ScriptDecodeError(f"{label}: wrapper requires main and condition-list children")

    main = wrapper.children[0]
    if len(main.children) != 2:
        raise ScriptDecodeError(f"{label}: main chunk requires parameter and embedded-line children")
    reader = PayloadReader(main.payload, f"{label}.main")
    uid = reader.u32()
    name = reader.string()
    trigger_type = reader.u32()
    connective = reader.u32()
    trip_limit = reader.u32()
    initially_enabled = bool(reader.u8())
    trip_limit_enabled = bool(reader.u8())
    deleted = bool(reader.u8())
    reader.finish()

    parameters = PayloadReader(main.children[0].payload, f"{label}.parameters")
    parameter_values = {
        "timerOrInterval": parameters.u32(),
        "primaryScriptUid": parameters.u32(),
        "regionLeft": parameters.f32(),
        "regionTop": parameters.f32(),
        "regionRight": parameters.f32(),
        "regionBottom": parameters.f32(),
        "point": parameters.float2(),
        "radius": parameters.f32(),
        "targetSelector": parameters.u8(),
        "secondaryScriptUid": parameters.u32(),
    }
    parameters.finish()
    if main.children[0].children:
        raise ScriptDecodeError(f"{label}: parameter chunk unexpectedly has children")
    embedded = _decode_code_body(main.children[1], f"{label}.embeddedCodeLine")

    tail = PayloadReader(wrapper.payload, f"{label}.tail")
    pressure_active = bool(tail.u8())
    global_scope = bool(tail.u8())
    pressure_seconds = tail.f32()
    pressure_countdown = tail.u32()
    stationary_required = bool(tail.u8())
    tail.finish()

    return {
        "uid": uid,
        "name": name,
        "type": trigger_type,
        "typeName": TRIGGER_TYPES.get(trigger_type, "MISC"),
        "conditionMode": "ALL" if connective == 0 else "ANY",
        "conditionModeRaw": connective,
        "tripLimit": trip_limit,
        "initiallyEnabled": initially_enabled,
        "tripLimitEnabled": trip_limit_enabled,
        "deleted": deleted,
        **parameter_values,
        "embeddedCodeLine": embedded,
        "conditions": _decode_code_list(wrapper.children[1], f"{label}.conditions"),
        "pressureActive": pressure_active,
        "global": global_scope,
        "pressureSeconds": pressure_seconds,
        "pressureCountdown": pressure_countdown,
        "stationaryRequired": stationary_required,
    }


def _decode_script_state(node: inspect_boneyard.Chunk) -> dict[str, Any]:
    if node.children:
        raise ScriptDecodeError("TriggerControl script-state chunk unexpectedly has children")
    reader = PayloadReader(node.payload, "TriggerControl.scriptState")
    flag_count = reader.u32()
    flags = [
        {"name": reader.string(), "value": reader.string()}
        for _ in range(flag_count)
    ]
    counter_count = reader.u32()
    counters = [
        {"name": reader.string(), "value": reader.u32()}
        for _ in range(counter_count)
    ]
    reader.finish()
    return {"flags": flags, "counters": counters}


def _decode_trigger_control(node: inspect_boneyard.Chunk) -> dict[str, Any]:
    if node.payload or len(node.children) != 3:
        raise ScriptDecodeError("TriggerControl must be an empty chunk with three children")

    trigger_list = node.children[0]
    trigger_reader = PayloadReader(trigger_list.payload, "TriggerControl.triggers")
    trigger_count = trigger_reader.u32()
    trigger_reader.finish()
    if len(trigger_list.children) != trigger_count:
        raise ScriptDecodeError("TriggerControl trigger count does not match child count")
    triggers = [
        _decode_trigger(wrapper, index)
        for index, wrapper in enumerate(trigger_list.children)
    ]

    script_list = node.children[1]
    script_reader = PayloadReader(script_list.payload, "TriggerControl.scripts")
    script_count = script_reader.u32()
    script_reader.finish()
    if len(script_list.children) != script_count * 2 + 1:
        raise ScriptDecodeError(
            "TriggerControl script list requires metadata/line pairs plus one state chunk"
        )
    scripts: list[dict[str, Any]] = []
    for index in range(script_count):
        metadata_node = script_list.children[index * 2]
        if metadata_node.children:
            raise ScriptDecodeError(f"Script[{index}] metadata unexpectedly has children")
        metadata = PayloadReader(metadata_node.payload, f"Script[{index}].metadata")
        uid = metadata.u32()
        name = metadata.string()
        metadata.finish()
        scripts.append(
            {
                "uid": uid,
                "name": name,
                "lines": _decode_code_list(
                    script_list.children[index * 2 + 1],
                    f"Script[{index}].lines",
                ),
            }
        )

    runtime_types, runtime_children = _object_manager(
        node.children[2], "TriggerControl.runtimeThreads"
    )
    return {
        "triggers": triggers,
        "scripts": scripts,
        **_decode_script_state(script_list.children[-1]),
        "serializedRuntimeThreadTypes": runtime_types,
        "serializedRuntimeThreadPayloads": [
            child.payload.hex() for child in runtime_children
        ],
    }


def _decode_timeline_event(
    node: inspect_boneyard.Chunk,
    timeline_index: int,
    event_index: int,
) -> dict[str, Any]:
    label = f"TimeLine[{timeline_index}].event[{event_index}]"
    if len(node.children) != 6:
        raise ScriptDecodeError(f"{label}: TimeLineEvent requires exactly six children")
    reader = PayloadReader(node.payload, label)
    uid = reader.u32()
    event_type = reader.u32()
    graph_x = reader.f32()
    graph_y = reader.f32()
    one_shot = bool(reader.u8())
    fired = bool(reader.u8())
    runtime_flag = reader.u8()
    reader.finish()
    return {
        "uid": uid,
        "type": event_type,
        "typeName": TIMELINE_EVENT_TYPES.get(event_type, "UNKNOWN"),
        "time": graph_x,
        "graphY": graph_y,
        "oneShot": one_shot,
        "fired": fired,
        "runtimeFlag": runtime_flag,
        "uidValues": _counted_u32(node.children[0], f"{label}.uidValues"),
        "byteValues": _counted_u8(node.children[1], f"{label}.byteValues"),
        "floatValues": _counted_f32(node.children[2], f"{label}.floatValues"),
        "intValues": _counted_u32(node.children[3], f"{label}.intValues"),
        "stringValues": _counted_strings(node.children[4], f"{label}.stringValues"),
        "records": _decode_code_list(node.children[5], f"{label}.records"),
    }


def _decode_timeline(
    node: inspect_boneyard.Chunk,
    index: int,
) -> dict[str, Any]:
    label = f"TimeLine[{index}]"
    reader = PayloadReader(node.payload, label)
    name = reader.string()
    uid = reader.u32()
    enabled = bool(reader.u8())
    event_count = reader.u32()
    event_type_ids = [reader.u32() for _ in range(event_count)]
    current_time = reader.f32()
    next_event_index = reader.u32()
    pause_mode = reader.u8()
    pause_parameter = reader.u32()
    default_location = reader.u8()
    default_position = reader.u8()
    lull_threshold = reader.u32()
    spawner_count = reader.u32()
    spawner_type_ids = [reader.u32() for _ in range(spawner_count)]
    reader.finish()
    expected_children = event_count + spawner_count
    if len(node.children) != expected_children:
        raise ScriptDecodeError(
            f"{label}: declares {expected_children} event/spawner children, "
            f"found {len(node.children)}"
        )
    if any(type_id != 6007 for type_id in event_type_ids):
        raise ScriptDecodeError(f"{label}: event manager contains a non-TimeLineEvent type")
    if any(type_id != 6008 for type_id in spawner_type_ids):
        raise ScriptDecodeError(f"{label}: spawner manager contains a non-Spawner type")
    return {
        "uid": uid,
        "name": name,
        "enabled": enabled,
        "currentTime": current_time,
        "nextEventIndex": next_event_index,
        "pauseMode": pause_mode,
        "pauseParameter": pause_parameter,
        "defaultSpawnLocation": default_location,
        "defaultSpawnPosition": default_position,
        "lullMonsterThreshold": lull_threshold,
        "events": [
            _decode_timeline_event(child, index, event_index)
            for event_index, child in enumerate(node.children[:event_count])
        ],
        "serializedSpawners": [
            _decode_spawner(child, f"{label}.spawner[{spawner_index}]")
            for spawner_index, child in enumerate(node.children[event_count:])
        ],
    }


def _decode_spawner(node: inspect_boneyard.Chunk, label: str) -> dict[str, Any]:
    reader = PayloadReader(node.payload, label)
    result = {
        "eventUid": reader.u32(),
        "remaining": reader.u32(),
        "countdown": reader.u32(),
        "interval": reader.u32(),
        "spreadDuration": reader.u32(),
        "steady": bool(reader.u8()),
        "groupTotal": bool(reader.u8()),
        "groupIndex": reader.u32(),
        "groupMemberIndex": reader.u32(),
        "spawnLocation": reader.u32(),
        "spawnPosition": reader.u32(),
    }
    reader.finish()
    if node.children:
        raise ScriptDecodeError(f"{label}: Spawner unexpectedly has child chunks")
    return result


def _decode_monster_recipe(node: inspect_boneyard.Chunk, label: str) -> dict[str, Any]:
    reader = PayloadReader(node.payload, label)
    result = {
        "enemyType": reader.u32(),
        "name": reader.string(),
        "uid": reader.u32(),
        "maxHp": reader.f32(),
        "primaryDamage": reader.f32(),
        "chaseSpeed": reader.f32(),
        "moveSpeedScale": reader.f32(),
        "variantMode": reader.u32(),
        "projectileMode": reader.u32(),
        "auraMode": reader.u32(),
        "headgearMode": reader.u8(),
        "unknown81": reader.u8(),
        "unknown82": reader.u8(),
        "randomVariant": reader.u8(),
        "archetype": reader.string(),
        "hasLinkedUid": bool(reader.u8()),
        "linkedUid": reader.u32(),
        "behaviorCount": reader.u32(),
        "behaviorMin": reader.u32(),
        "behaviorMax": reader.u32(),
        "flanking": bool(reader.u8()),
        "pathfindingMode": reader.u8(),
        "dropOrbs": reader.u8(),
        "dropPowerups": reader.u8(),
        "dropItems": reader.u8(),
        "dropSpecificItems": reader.u8(),
        "dropGold": reader.u8(),
        "dropPotions": reader.u8(),
        "specialSpawnMode": reader.u8(),
        "attackSpeed": reader.f32(),
        "xpBonus": reader.f32(),
        "secondaryDamage": reader.f32(),
        "shield": bool(reader.u8()),
        "shieldOthers": bool(reader.u8()),
        "unknown96": bool(reader.u8()),
        "burning": bool(reader.u8()),
        "tertiaryDamage": reader.f32(),
        "extraDamage": reader.f32(),
        "behaviorTimer": reader.u32(),
        "rect98": reader.rect4(),
        "rectA8": reader.rect4(),
        "castMode": reader.u8(),
    }
    reader.finish()
    if node.children:
        raise ScriptDecodeError(f"{label}: MonsterRecipe unexpectedly has children")
    return result


def _decode_uid_group(node: inspect_boneyard.Chunk, label: str) -> dict[str, Any]:
    reader = PayloadReader(node.payload, label)
    name = reader.string()
    uid = reader.u32()
    members = [reader.u32() for _ in range(reader.u32())]
    result = {
        "name": name,
        "uid": uid,
        "memberUids": members,
        "field58": reader.u32(),
        "field5C": reader.u32(),
        "field60": reader.u32(),
        "field34": reader.u32(),
    }
    reader.finish()
    if node.children:
        raise ScriptDecodeError(f"{label}: UIDGroup unexpectedly has children")
    return result


def _decode_item_recipe(node: inspect_boneyard.Chunk, label: str) -> dict[str, Any]:
    reader = PayloadReader(node.payload, label)
    uid = reader.u32()
    reference_name = reader.string()
    display_name = reader.string()
    description = reader.string()
    fx_count = reader.u32()
    fx_type_ids = [reader.u32() for _ in range(fx_count)]
    result = {
        "uid": uid,
        "referenceName": reference_name,
        "displayName": display_name,
        "description": description,
        "fxTypeIds": fx_type_ids,
        "field84": reader.u32(),
        "field88": reader.u8(),
        "rect8C": reader.rect4(),
        "rect9C": reader.rect4(),
        "classification": reader.u8(),
        "itemLevel": reader.i8(),
        "fxPayloads": [child.payload.hex() for child in node.children],
    }
    reader.finish()
    if len(node.children) != fx_count:
        raise ScriptDecodeError(
            f"{label}: declares {fx_count} FX children, found {len(node.children)}"
        )
    return result


def _decode_npc_recipe(node: inspect_boneyard.Chunk, label: str) -> dict[str, Any]:
    reader = PayloadReader(node.payload, label)
    result = {
        "npcType": reader.u32(),
        "referenceName": reader.string(),
        "displayName": reader.string(),
        "uid": reader.u32(),
        "idleBehavior": reader.u8(),
        "canTalk": bool(reader.u8()),
        "link0Selector": reader.u8(),
        "link0Uid": reader.u32(),
        "link1Selector": reader.u8(),
        "link1Uid": reader.u32(),
        "link2Selector": reader.u8(),
        "link2Uid": reader.u32(),
        "sayText": reader.string(),
        "doneAfterTalkingTo": reader.u8(),
        "removeSelector": reader.u8(),
        "removeWhenDone": bool(reader.u8()),
        "variantBytes": [reader.u8() for _ in range(4)],
        "wizardSettings": [reader.u32() for _ in range(4)],
        "wizardSettingEnabled": [bool(reader.u8()) for _ in range(4)],
        "rectB4": reader.rect4(),
        "rectC4": reader.rect4(),
        "talkSpeed": reader.u32(),
    }
    reader.finish()
    if node.children:
        raise ScriptDecodeError(f"{label}: NPCRecipe unexpectedly has children")
    return result


def _decode_recipe_manager(
    node: inspect_boneyard.Chunk,
    expected_type: int,
    label: str,
) -> list[dict[str, Any]]:
    type_ids, children = _object_manager(node, label)
    if any(type_id != expected_type for type_id in type_ids):
        raise ScriptDecodeError(
            f"{label}: expected only type {expected_type}, found {type_ids}"
        )
    decoder = {
        6001: _decode_monster_recipe,
        6002: _decode_uid_group,
        6003: _decode_item_recipe,
        6004: _decode_npc_recipe,
    }.get(expected_type)
    if expected_type == 6005:
        for index, child in enumerate(children):
            if child.payload or child.children:
                raise ScriptDecodeError(
                    f"{label}[{index}]: ItemSet has no subclass Sync payload"
                )
        return [{"type": "ItemSet"} for _ in children]
    assert decoder is not None
    return [decoder(child, f"{label}[{index}]") for index, child in enumerate(children)]


def decode_boneyard(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    boneyard = inspect_boneyard.parse_boneyard(data, str(path))
    region = boneyard.region_layout.children
    timeline_types, timeline_nodes = _object_manager(region[13], "TimeLineManager")
    if any(type_id != 6006 for type_id in timeline_types):
        raise ScriptDecodeError("TimeLine manager contains a non-TimeLine object")
    return {
        "path": path.as_posix(),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "triggerControl": _decode_trigger_control(region[1]),
        "recipes": {
            "monsterRecipes": _decode_recipe_manager(
                region[3], 6001, "MonsterRecipeManager"
            ),
            "uidGroups": _decode_recipe_manager(region[4], 6002, "UIDGroupManager"),
            "itemRecipes": _decode_recipe_manager(
                region[7], 6003, "ItemRecipeManager"
            ),
            "itemSets": _decode_recipe_manager(region[8], 6005, "ItemSetManager"),
            "npcRecipes": _decode_recipe_manager(
                region[9], 6004, "NPCRecipeManager"
            ),
        },
        "timelines": [
            _decode_timeline(node, index)
            for index, node in enumerate(timeline_nodes)
        ],
    }


def _format_operand(operand: dict[str, Any]) -> str:
    value = operand["value"]
    if operand["typeName"] == "none":
        rendered = "-"
    elif operand["typeName"] == "string":
        rendered = json.dumps(value, ensure_ascii=False)
    elif operand["typeName"] == "float2":
        rendered = f"({value[0]:g}, {value[1]:g})"
    else:
        rendered = f"{value:g}" if isinstance(value, float) else str(value)
    return f"{operand['typeName']}:{rendered}"


def _format_code_line(line: dict[str, Any], indent: str = "") -> list[str]:
    operands = ", ".join(_format_operand(value) for value in line["operands"])
    negate = " NOT" if line["negated"] else ""
    rendered = [
        f"{indent}{line['id']} {line['name']}{negate}({operands}) flags=0x{line['flags']:X}"
    ]
    for nested in line["nested"]:
        rendered.extend(_format_code_line(nested, indent + "  "))
    return rendered


def render_text(decoded: dict[str, Any]) -> str:
    control = decoded["triggerControl"]
    lines = [
        "BONEYARD SCRIPT DECODE",
        f"path: {decoded['path']}",
        f"size: {decoded['size']}",
        f"sha256: {decoded['sha256']}",
        "",
        f"TRIGGERS ({len(control['triggers'])})",
    ]
    for trigger in control["triggers"]:
        lines.append(
            f"- uid={trigger['uid']} name={json.dumps(trigger['name'])} "
            f"type={trigger['type']}:{trigger['typeName']} "
            f"script={trigger['primaryScriptUid']} secondary={trigger['secondaryScriptUid']} "
            f"enabled={str(trigger['initiallyEnabled']).lower()} "
            f"global={str(trigger['global']).lower()} "
            f"conditions={trigger['conditionMode']}:{len(trigger['conditions'])}"
        )
        for condition in trigger["conditions"]:
            lines.extend(_format_code_line(condition, "    "))

    lines.extend(["", f"SCRIPTS ({len(control['scripts'])})"])
    for script in control["scripts"]:
        lines.append(
            f"- uid={script['uid']} name={json.dumps(script['name'])} "
            f"lines={len(script['lines'])}"
        )
        for code_line in script["lines"]:
            lines.extend(_format_code_line(code_line, "    "))
    lines.append(f"flags: {json.dumps(control['flags'], ensure_ascii=False)}")
    lines.append(f"counters: {json.dumps(control['counters'], ensure_ascii=False)}")

    lines.extend(["", f"TIMELINES ({len(decoded['timelines'])})"])
    for timeline in decoded["timelines"]:
        lines.append(
            f"- uid={timeline['uid']} name={json.dumps(timeline['name'])} "
            f"enabled={str(timeline['enabled']).lower()} events={len(timeline['events'])} "
            f"cursor={timeline['currentTime']:g} next={timeline['nextEventIndex']} "
            f"pause={timeline['pauseMode']}:{timeline['pauseParameter']}"
        )
        for event_index, event in enumerate(timeline["events"]):
            lines.append(
                f"    [{event_index:02d}] uid={event['uid']} "
                f"type={event['type']}:{event['typeName']} time={event['time']:g} "
                f"graphY={event['graphY']:g} oneShot={str(event['oneShot']).lower()} "
                f"fired={str(event['fired']).lower()}"
            )
            lines.append(
                "         "
                f"uids={event['uidValues']} bytes={event['byteValues']} "
                f"floats={event['floatValues']} ints={event['intValues']} "
                f"strings={event['stringValues']}"
            )
            for record in event["records"]:
                lines.extend(_format_code_line(record, "         "))

    recipes = decoded["recipes"]
    lines.extend(["", "RECIPES"])
    for key in (
        "monsterRecipes",
        "uidGroups",
        "itemRecipes",
        "itemSets",
        "npcRecipes",
    ):
        lines.append(f"- {key} ({len(recipes[key])})")
        for recipe in recipes[key]:
            lines.append("    " + json.dumps(recipe, ensure_ascii=False, sort_keys=True))
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    decoded = decode_boneyard(args.path)
    if args.json:
        print(json.dumps(decoded, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(render_text(decoded), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
