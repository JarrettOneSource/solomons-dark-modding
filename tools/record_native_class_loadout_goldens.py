#!/usr/bin/env python3
"""Record native class/loadout initialization for every Create choice."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from owned_process_ledger import (
    OwnedProcessIdentity,
    OwnedProcessLedger,
)
from verify_local_multiplayer_sync import (
    VerifyFailure,
    _kill_lua_daemon,
    activate_native_ui_action,
    lua,
    parse_key_values,
    query_native_create_state,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "tests" / "fixtures" / "webgame" / "class-loadout-goldens.json"
DEFAULT_EVIDENCE = Path(r"D:\codex-evidence\loadre-20260805\live-class-loadouts")
DEFAULT_GAME_DIRECTORY = Path(
    r"D:\sd-archive\sd-atc-landing-20260801\runtime\stage"
)
CLASS_CATALOG = ROOT / "docs" / "reverse-engineering" / "native-class-catalog.json"
SKILL_CATALOG = ROOT / "docs" / "reverse-engineering" / "native-skill-catalog.json"
ASSET_MAP = ROOT / "docs" / "reverse-engineering" / "native-asset-object-map.json"
BINARY_LAYOUT = ROOT / "config" / "binary-layout.ini"
RELEASE_LOADER = ROOT / "bin" / "Release" / "Win32" / "SolomonDarkModLoader.dll"
STAGED_LOADER = ROOT / "dist" / "launcher" / "SolomonDarkModLoader.dll"
LAUNCHER = ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"
LAUNCH_SCRIPT = ROOT / "scripts" / "Launch-LocalSoloSession.ps1"
RECORDER = Path(__file__).resolve()

MOD_ID = "sample.lua.ui_sandbox_lab"
LOCAL_PORT = 52411
UNUSED_REMOTE_PORT = 52412
SETTLE_MIN_SAMPLES = 40
SETTLE_MIN_SECONDS = 2.0
BOOK_ENTRY_COUNT = 83
BOOK_ENTRY_STRIDE = 0x70
BOOK_BYTE_COUNT = BOOK_ENTRY_COUNT * BOOK_ENTRY_STRIDE
DYNAMIC_RUNTIME_STAT_FIELDS = ("meditation_recovery_ramp_ticks",)

ELEMENTS: tuple[dict[str, Any], ...] = (
    {
        "key": "ether",
        "name": "Ether",
        "create_raw_id": 0,
        "profile_element_id": 4,
        "root_row": 0,
        "primary_row": 8,
        "primary_name": "Magic Missile",
        "secondary_row": 11,
        "secondary_name": "Call Leviathan",
        "portrait_native_id": "Create.9",
        "portrait_atlas_record": 9,
    },
    {
        "key": "fire",
        "name": "Fire",
        "create_raw_id": 1,
        "profile_element_id": 0,
        "root_row": 1,
        "primary_row": 16,
        "primary_name": "Fireball",
        "secondary_row": 21,
        "secondary_name": "Ring of Fire",
        "portrait_native_id": "Create.10",
        "portrait_atlas_record": 10,
    },
    {
        "key": "air",
        "name": "Air",
        "create_raw_id": 2,
        "profile_element_id": 3,
        "root_row": 2,
        "primary_row": 24,
        "primary_name": "Lightning",
        "secondary_row": 27,
        "secondary_name": "Magic Storm",
        "portrait_native_id": "Create.11",
        "portrait_atlas_record": 11,
    },
    {
        "key": "water",
        "name": "Water",
        "create_raw_id": 3,
        "profile_element_id": 1,
        "root_row": 3,
        "primary_row": 32,
        "primary_name": "Frost Jet",
        "secondary_row": 35,
        "secondary_name": "Ring of Ice",
        "portrait_native_id": "Create.12",
        "portrait_atlas_record": 12,
    },
    {
        "key": "earth",
        "name": "Earth",
        "create_raw_id": 4,
        "profile_element_id": 2,
        "root_row": 4,
        "primary_row": 40,
        "primary_name": "Boulder",
        "secondary_row": 45,
        "secondary_name": "Raise Golem",
        "portrait_native_id": "Create.13",
        "portrait_atlas_record": 13,
    },
)

DISCIPLINES: tuple[dict[str, Any], ...] = (
    {
        "key": "arcane",
        "name": "Arcane",
        "create_raw_id": 0,
        "profile_discipline_id": 2,
        "root_row": 7,
        "art_native_id": "Create.0",
        "art_atlas_record": 0,
    },
    {
        "key": "body",
        "name": "Body",
        "create_raw_id": 1,
        "profile_discipline_id": 1,
        "root_row": 5,
        "art_native_id": "Create.1",
        "art_atlas_record": 1,
    },
    {
        "key": "mind",
        "name": "Mind",
        "create_raw_id": 2,
        "profile_discipline_id": 0,
        "root_row": 6,
        "art_native_id": "Create.5",
        "art_atlas_record": 5,
    },
)

# kind is the native storage type used for both the value and exact raw bits.
STAT_FIELDS: tuple[tuple[str, int, str], ...] = (
    ("level", 0x30, "i32"),
    ("experience", 0x34, "f32"),
    ("previous_experience_threshold", 0x38, "f32"),
    ("next_experience_threshold", 0x3C, "f32"),
    ("nonlocal_mode_flag", 0x40, "u8"),
    ("unknown_0x68", 0x68, "f32"),
    ("base_hp", 0x6C, "f32"),
    ("hp", 0x70, "f32"),
    ("max_hp", 0x74, "f32"),
    ("base_mp", 0x78, "f32"),
    ("mp", 0x7C, "f32"),
    ("max_mp", 0x80, "f32"),
    ("spell_damage_base_additive", 0x84, "f32"),
    ("unknown_0x88", 0x88, "f32"),
    ("unknown_0x8c", 0x8C, "f32"),
    ("move_speed", 0x90, "f32"),
    ("cast_speed_multiplier", 0x94, "f32"),
    ("mana_recovery_multiplier", 0x98, "f32"),
    ("health_regeneration", 0x9C, "f32"),
    ("unknown_0xa0", 0xA0, "f32"),
    ("resist_magic_fraction", 0xA4, "f32"),
    ("resist_poison_fraction", 0xA8, "f32"),
    ("unknown_0xac", 0xAC, "f32"),
    ("unknown_0xb0", 0xB0, "f32"),
    ("unknown_0xb4", 0xB4, "f32"),
    ("deflect_chance", 0xB8, "f32"),
    ("unknown_0xbc", 0xBC, "f32"),
    ("unknown_0xc0", 0xC0, "f32"),
    ("staff_melee_damage_a", 0xC4, "f32"),
    ("staff_melee_damage_b", 0xC8, "f32"),
    ("pickup_range", 0xCC, "f32"),
    ("secondary_recharge_multiplier", 0xD0, "f32"),
    ("spell_damage_global_multiplier", 0xF4, "f32"),
    ("offensive_damage_multiplier", 0xF8, "f32"),
    ("spell_damage_global_flat", 0xFC, "f32"),
    ("offensive_mana_multiplier", 0x3D4, "f32"),
    ("melee_damage_multiplier", 0x6F4, "f32"),
    ("hoarded_mp", 0x740, "f32"),
    ("current_spell_id", 0x750, "i32"),
    ("push_strength", 0x818, "f32"),
    ("cheat_death_enabled", 0x81C, "u8"),
    ("cheat_death_charges", 0x820, "i32"),
    ("damage_x4_remaining_ticks", 0x824, "i32"),
    ("element_skill_row", 0x82C, "i32"),
    ("discipline_skill_row", 0x830, "i32"),
    ("serialized_class_slot_0x834", 0x834, "i32"),
    ("local_skill_picker_flag", 0x839, "u8"),
    ("special_choice_argument", 0x844, "i32"),
    ("primary_skill_row", 0x86C, "i32"),
    ("secondary_skill_row", 0x870, "i32"),
    ("meditation_idle_ticks", 0x884, "i32"),
    ("meditation_idle_elapsed_ticks", 0x888, "i32"),
    ("meditation_recovery_ramp_ticks", 0x88C, "i32"),
    ("meditation_recovery_bonus", 0x890, "f32"),
)

EQUIPMENT_SLOTS = (
    "primary",
    "secondary",
    "attachment",
    "hat",
    "robe",
    "weapon",
    "amulet",
    "ring_1",
    "ring_2",
)

EXPECTED_COMMON_STAT_BITS: dict[str, int] = {
    "level": 1,
    "experience": 0x00000000,
    "previous_experience_threshold": 0x00000000,
    "next_experience_threshold": 0x42B40000,
    "nonlocal_mode_flag": 0,
    "unknown_0x68": 0x43160000,
    "base_hp": 0x42480000,
    "hp": 0x42480000,
    "max_hp": 0x42480000,
    "base_mp": 0x42C80000,
    "mp": 0x42C80000,
    "max_mp": 0x42C80000,
    "spell_damage_base_additive": 0x00000000,
    "unknown_0x88": 0x00000000,
    "unknown_0x8c": 0x00000000,
    "move_speed": 0x3F733333,
    "cast_speed_multiplier": 0x3F800000,
    "mana_recovery_multiplier": 0x41200000,
    "health_regeneration": 0x3F800000,
    "unknown_0xa0": 0x00000000,
    "resist_magic_fraction": 0x00000000,
    "resist_poison_fraction": 0x00000000,
    "unknown_0xac": 0x00000000,
    "unknown_0xb0": 0x00000000,
    "unknown_0xb4": 0x3F800000,
    "deflect_chance": 0x00000000,
    "unknown_0xbc": 0x3F800000,
    "unknown_0xc0": 0x3F800000,
    "staff_melee_damage_a": 0x3F000000,
    "staff_melee_damage_b": 0x3F800000,
    "pickup_range": 0x3FA00000,
    "secondary_recharge_multiplier": 0x3F800000,
    "spell_damage_global_multiplier": 0x3F800000,
    "offensive_damage_multiplier": 0x3F800000,
    "spell_damage_global_flat": 0x00000000,
    "offensive_mana_multiplier": 0x3F800000,
    "melee_damage_multiplier": 0x3F800000,
    "hoarded_mp": 0x00000000,
    "push_strength": 0x41400000,
    "cheat_death_enabled": 0,
    "cheat_death_charges": 0,
    "damage_x4_remaining_ticks": 0,
}


class CaptureFailure(RuntimeError):
    pass


class SnapshotNotReady(CaptureFailure):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CaptureFailure(message)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git_text(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    require(
        completed.returncode == 0,
        f"git {' '.join(arguments)} failed: {completed.stdout}",
    )
    return completed.stdout.strip()


def source_revision() -> dict[str, Any]:
    status = git_text("status", "--porcelain", "--untracked-files=all")
    require(not status, "capture source tree is dirty; commit the recorder before recording")
    return {
        "sha": git_text("rev-parse", "HEAD"),
        "branch": git_text("branch", "--show-current"),
        "dirty": False,
    }


def write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"expected a JSON object at {path}")
    return value


def build_class_definitions(skill_catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    skills = skill_catalog.get("skills")
    require(isinstance(skills, list), "native skill catalog has no skill rows")
    by_id: dict[int, dict[str, Any]] = {}
    for skill_id in range(82):
        matches = [row for row in skills if row.get("id") == skill_id]
        require(
            len(matches) == 1,
            f"native skill catalog row {skill_id} is ambiguous: {len(matches)} candidates",
        )
        by_id[skill_id] = matches[0]

    definitions: list[dict[str, Any]] = []
    for element in ELEMENTS:
        require(
            by_id[element["root_row"]]["name"] == f"Element of {element['name']}",
            f"native skill catalog changed the {element['name']} element root",
        )
        require(
            by_id[element["primary_row"]]["name"] == element["primary_name"],
            f"native skill catalog changed the {element['name']} primary spell",
        )
        require(
            by_id[element["secondary_row"]]["name"] == element["secondary_name"],
            f"native skill catalog changed the {element['name']} secondary spell",
        )
        for discipline in DISCIPLINES:
            require(
                by_id[discipline["root_row"]]["name"]
                == f"{discipline['name']} Discipline",
                f"native skill catalog changed the {discipline['name']} discipline root",
            )
            definitions.append(
                {
                    "class_key": f"{element['key']}-{discipline['key']}",
                    "display_name": f"{element['name']} / {discipline['name']}",
                    "native_identity": {
                        "combined_scalar_id": None,
                        "create_element_raw_id": element["create_raw_id"],
                        "create_discipline_raw_id": discipline["create_raw_id"],
                        "profile_element_id": element["profile_element_id"],
                        "profile_discipline_id": discipline[
                            "profile_discipline_id"
                        ],
                    },
                    "native_art": {
                        "element_portrait_id": element["portrait_native_id"],
                        "element_portrait_atlas_record": element[
                            "portrait_atlas_record"
                        ],
                        "discipline_art_id": discipline["art_native_id"],
                        "discipline_art_atlas_record": discipline[
                            "art_atlas_record"
                        ],
                    },
                    "starting_kit": {
                        "selected_element_root": {
                            "row": element["root_row"],
                            "name": by_id[element["root_row"]]["name"],
                            "rank": 1,
                        },
                        "selected_discipline_root": {
                            "row": discipline["root_row"],
                            "name": by_id[discipline["root_row"]]["name"],
                            "rank": 1,
                        },
                        "all_root_rows_granted": list(range(8)),
                        "root_rank": 1,
                        "primary_spell": {
                            "row": element["primary_row"],
                            "name": element["primary_name"],
                            "rank": 1,
                        },
                        "secondary_spell": {
                            "row": element["secondary_row"],
                            "name": element["secondary_name"],
                            "rank": 1,
                        },
                        "equipment_type_ids": {
                            "robe": 7006,
                            "hat": 7005,
                            "weapon": 7004,
                        },
                        "inventory_type_ids": [7001, 7001],
                        "inventory_slots": [0, 1],
                    },
                    "definition_to_actor_fields": {
                        "element_root": {
                            "progression_offset": "0x82C",
                            "value": element["root_row"],
                        },
                        "discipline_root": {
                            "progression_offset": "0x830",
                            "value": discipline["root_row"],
                        },
                        "primary_spell": {
                            "progression_offset": "0x86C",
                            "value": element["primary_row"],
                        },
                        "secondary_spell": {
                            "progression_offset": "0x870",
                            "value": element["secondary_row"],
                        },
                    },
                    "unlock": {
                        "initially_unlocked": True,
                        "condition": "always",
                        "persistent_unlock_key": None,
                    },
                }
            )
    require(len(definitions) == 15, "compiled Create product did not produce 15 classes")
    return definitions


def validate_class_catalog(class_catalog: Mapping[str, Any]) -> None:
    summary = class_catalog.get("summary") or {}
    require(summary.get("class_count") == 598, "native class catalog no longer has 598 entries")
    classes = class_catalog.get("classes") or []
    matches = [row for row in classes if row.get("name") == "CreateWizardMenu"]
    require(
        len(matches) == 1,
        f"CreateWizardMenu catalog lookup is ambiguous: {len(matches)} candidates",
    )
    create = matches[0]
    require(create.get("vtable") == "0x00797B7C", "CreateWizardMenu vtable changed")
    slots = create.get("slots") or []
    tick = [slot for slot in slots if slot.get("offset") == "0x08"]
    click = [slot for slot in slots if slot.get("offset") == "0x64"]
    require(len(tick) == 1 and tick[0].get("function") == "0x0058A820", "Create commit tick slot changed")
    require(len(click) == 1 and click[0].get("function") == "0x0058BCE0", "Create selection click slot changed")


def committed_source_hashes() -> dict[str, dict[str, str]]:
    paths = (RECORDER, CLASS_CATALOG, SKILL_CATALOG, ASSET_MAP, BINARY_LAYOUT)
    records: dict[str, dict[str, str]] = {}
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        git_text("ls-files", "--error-unmatch", relative)
        records[relative] = {"sha256": sha256_file(path)}
    return records


def _powershell_json(script: str) -> Any:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30.0,
        check=False,
    )
    require(
        completed.returncode == 0,
        f"Windows process probe failed: {completed.stderr or completed.stdout}",
    )
    text = completed.stdout.strip()
    require(text, "Windows process probe returned no JSON")
    return json.loads(text)


def process_and_port_probe(executable_path: Path) -> dict[str, Any]:
    escaped = str(executable_path).replace("'", "''")
    script = f"""
$expected = [System.IO.Path]::GetFullPath('{escaped}')
$processes = @(
  Get-CimInstance -ClassName Win32_Process |
    Where-Object {{
      $null -ne $_.ExecutablePath -and
      [string]::Equals(
        [System.IO.Path]::GetFullPath($_.ExecutablePath),
        $expected,
        [System.StringComparison]::OrdinalIgnoreCase)
    }} |
    ForEach-Object {{ [int]$_.ProcessId }}
)
$ports = @({LOCAL_PORT}, {UNUSED_REMOTE_PORT})
$bindings = @(
  foreach ($port in $ports) {{
    Get-NetUDPEndpoint -LocalPort $port -ErrorAction SilentlyContinue |
      ForEach-Object {{
        [ordered]@{{ port = [int]$port; pid = [int]$_.OwningProcess }}
      }}
  }}
)
[ordered]@{{
  executable = $expected
  process_ids = @($processes)
  udp_bindings = @($bindings)
}} | ConvertTo-Json -Depth 4 -Compress
""".strip()
    value = _powershell_json(script)
    require(isinstance(value, dict), "Windows process probe did not return an object")
    value["process_ids"] = [int(item) for item in value.get("process_ids") or []]
    bindings = value.get("udp_bindings") or []
    if isinstance(bindings, dict):
        bindings = [bindings]
    value["udp_bindings"] = bindings
    return value


def loaded_loader_from_startup_log(
    launch: Mapping[str, Any],
    pipe_name: str,
) -> dict[str, Any]:
    log_path = Path(str(launch.get("startupLogPath", "")))
    require(log_path.is_file(), f"live loader published no startup log: {log_path}")
    lines = log_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    attached = [line for line in lines if line.endswith("SolomonDarkModLoader attached.")]
    release = [line for line in lines if line.endswith("Build flavor: Release.")]
    module_lines = [line for line in lines if "] Module path: " in line]
    pipe_lines = [
        line
        for line in lines
        if line.endswith(
            f"[lua-exec-pipe] server started. name=\\\\.\\pipe\\{pipe_name}"
        )
    ]
    require(
        len(attached) == 1,
        f"live loader attachment receipt is ambiguous: {len(attached)} candidates",
    )
    require(
        len(release) == 1,
        f"live Release-build receipt is ambiguous: {len(release)} candidates",
    )
    require(
        len(module_lines) == 1,
        f"live loader module-path receipt is ambiguous: {len(module_lines)} candidates",
    )
    require(
        len(pipe_lines) == 1,
        f"live lua-exec server receipt is ambiguous: {len(pipe_lines)} candidates",
    )
    path = Path(module_lines[0].split("] Module path: ", 1)[1])
    require(path.is_file(), f"loaded loader module is not readable: {path}")
    return {
        "evidence_source": "live injected loader startup log",
        "path": str(path),
        "sha256": sha256_file(path),
        "startup_log_path": str(log_path),
        "attachment_receipt": attached[0],
        "release_receipt": release[0],
        "lua_exec_receipt": pipe_lines[0],
    }


def launch_instance(
    definition: Mapping[str, Any],
    index: int,
    evidence_directory: Path,
    game_directory: Path,
) -> tuple[dict[str, Any], Path, Path]:
    class_key = str(definition["class_key"])
    instance = f"load-gold-{index:02d}-{class_key}"
    result_path = evidence_directory / "launch" / f"{class_key}.json"
    log_path = evidence_directory / "launch" / f"{class_key}.log"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    participant_id = 0x2000000000006A00 + index
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(LAUNCH_SCRIPT),
        "-Instance",
        instance,
        "-Preset",
        "create_manual",
        "-LocalPort",
        str(LOCAL_PORT),
        "-UnusedRemotePort",
        str(UNUSED_REMOTE_PORT),
        "-ParticipantId",
        f"0x{participant_id:016X}",
        "-PlayerName",
        f"Loadout {index:02d} {class_key}",
        "-GameDirectory",
        str(game_directory),
        "-ExactModIds",
        MOD_ID,
        "-LuaExecTargetModId",
        MOD_ID,
        "-ResultOutputPath",
        str(result_path),
        "-ProcessIdOutputPath",
        str(result_path),
    ]
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=120.0,
            check=False,
        )
    require(completed.returncode == 0, f"{class_key} launch failed; see {log_path}")
    require(result_path.is_file(), f"{class_key} launch returned no result JSON")
    launch = read_json(result_path)
    require(launch.get("success") is True, f"{class_key} launcher reported failure")
    require(launch.get("instance") == instance, f"{class_key} launcher changed instance identity")
    require(launch.get("audioDisabled") is True, f"{class_key} launch did not disable audio")
    require(
        launch.get("localPort") == LOCAL_PORT
        and launch.get("unusedRemotePort") == UNUSED_REMOTE_PORT,
        f"{class_key} launch escaped the reserved UDP ports",
    )
    return launch, result_path, log_path


def _is_retryable_pipe_failure(error: Exception) -> bool:
    message = str(error).lower()
    return any(
        token in message
        for token in (
            "cannot connect to pipe",
            "pipe closed",
            "closed unexpectedly",
            "timed out",
            "waitnamedpipe",
        )
    )


def require_live_owned_process(ledger: OwnedProcessLedger, context: str) -> list[dict[str, Any]]:
    state = ledger.inspect()
    require(state, f"BROKEN: {context}; launcher-owned game process exited")
    return state


def wait_for_lua_runnable(pipe_name: str, ledger: OwnedProcessLedger) -> dict[str, Any]:
    deadline = time.monotonic() + 45.0
    last_busy = "pipe not attempted"
    while time.monotonic() < deadline:
        try:
            output = lua(
                pipe_name,
                "return tostring(type(sd)=='table' and type(sd.debug)=='table' and type(sd.ui)=='table')",
                timeout=3.0,
            ).strip()
            require(output == "true", f"BROKEN: live Lua API returned {output!r}")
            return {
                "runnable": True,
                "end_to_end_query": output,
                "proved_at_utc": utc_now(),
            }
        except (VerifyFailure, subprocess.TimeoutExpired) as error:
            require_live_owned_process(ledger, "Lua exec readiness failed")
            if not _is_retryable_pipe_failure(error):
                raise CaptureFailure(f"BROKEN: Lua exec probe ran but failed: {error}") from error
            last_busy = str(error)
        time.sleep(0.1)
    raise CaptureFailure(f"BUSY: Lua exec pipe never became ready: {last_busy}")


def query_ui_surface(pipe_name: str) -> dict[str, str]:
    return parse_key_values(
        lua(
            pipe_name,
            r"""
local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or {}
local ui = sd.ui and sd.ui.get_snapshot and sd.ui.get_snapshot() or {}
print('scene=' .. tostring(scene.name or scene.kind or ''))
print('surface=' .. tostring(ui.surface_id or ''))
""".strip(),
            timeout=8.0,
        )
    )


def wait_for_create(pipe_name: str, ledger: OwnedProcessLedger) -> list[dict[str, str]]:
    receipts: list[dict[str, str]] = []
    deadline = time.monotonic() + 45.0
    last: dict[str, str] = {}
    control_scheme_submitted = False
    while time.monotonic() < deadline:
        try:
            last = query_ui_surface(pipe_name)
            surface = last.get("surface", "")
            if surface == "control_scheme_picker" and not control_scheme_submitted:
                receipts.append(
                    activate_native_ui_action(
                        pipe_name,
                        "control_scheme_picker.select_wasd",
                        "control_scheme_picker",
                    )
                )
                control_scheme_submitted = True
            elif surface == "create":
                return receipts
        except VerifyFailure as error:
            require_live_owned_process(ledger, "Create UI readiness failed")
            if not _is_retryable_pipe_failure(error):
                raise CaptureFailure(f"BROKEN: Create UI probe failed: {error}") from error
        time.sleep(0.1)
    raise CaptureFailure(f"BUSY: Create UI never became ready: {last}")


def select_class(
    pipe_name: str,
    ledger: OwnedProcessLedger,
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    class_key = str(definition["class_key"])
    element_key, discipline_key = class_key.split("-", 1)
    identity = definition["native_identity"]
    receipts: dict[str, Any] = {
        "bootstrap": wait_for_create(pipe_name, ledger),
    }
    phases = (
        (
            "element",
            f"create.select_element_{element_key}",
            "element_enabled",
            "element_selected",
            int(identity["create_element_raw_id"]),
        ),
        (
            "discipline",
            f"create.select_discipline_{discipline_key}",
            "discipline_enabled",
            "discipline_selected",
            int(identity["create_discipline_raw_id"]),
        ),
    )
    for phase, action_id, enabled_key, selected_key, expected_id in phases:
        deadline = time.monotonic() + 20.0
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            try:
                last = query_native_create_state(pipe_name, action_id)
            except VerifyFailure as error:
                require_live_owned_process(ledger, f"{class_key} {phase} readiness failed")
                if not _is_retryable_pipe_failure(error):
                    raise CaptureFailure(
                        f"BROKEN: {class_key} {phase} probe failed: {error}"
                    ) from error
                time.sleep(0.1)
                continue
            selected = _parse_int(last.get(selected_key), default=-1)
            if (
                last.get("ui") == "create"
                and _parse_int(last.get("owner"), default=0) != 0
                and _parse_int(last.get(enabled_key), default=0) != 0
                and selected in (-1, 0xFFFFFFFF)
                and last.get("action_found") == "true"
            ):
                receipts[phase] = activate_native_ui_action(
                    pipe_name,
                    action_id,
                    "create",
                )
                break
            time.sleep(0.1)
        else:
            raise CaptureFailure(
                f"BUSY: {class_key} {phase} choice never became actionable: {last}"
            )

        latch_deadline = time.monotonic() + 12.0
        while time.monotonic() < latch_deadline:
            last = query_native_create_state(pipe_name)
            if phase == "discipline" and last.get("scene") == "hub":
                break
            if _parse_int(last.get(selected_key), default=-1) == expected_id:
                break
            time.sleep(0.05)
        else:
            raise CaptureFailure(
                f"BROKEN: {class_key} {phase} did not latch native raw id {expected_id}: {last}"
            )
    return receipts


def _parse_int(value: Any, *, default: int | None = None) -> int:
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        if default is not None:
            return default
        raise CaptureFailure(f"live integer field is invalid: {value!r}")


def _bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def _compact_hex(value: str, byte_count: int, claim: str) -> str:
    tokens = value.strip().split()
    require(
        len(tokens) == byte_count,
        f"{claim} returned {len(tokens)} bytes instead of {byte_count}",
    )
    require(
        all(re.fullmatch(r"[0-9A-Fa-f]{2}", token) for token in tokens),
        f"{claim} contains a non-byte token",
    )
    return "".join(tokens).lower()


def _f32_from_bits(bits: int) -> float:
    return struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]


def _snapshot_probe(participant_id: int | None) -> str:
    selector = "nil" if participant_id is None else str(participant_id)
    stat_rows = "\n".join(
        f"  {{ name={json.dumps(name)}, offset=0x{offset:X}, kind={json.dumps(kind)} }},"
        for name, offset, kind in STAT_FIELDS
    )
    equipment_rows = "\n".join(
        f"emit_equipment({json.dumps(slot)}, "
        + (
            f"rings[{slot[-1]}])"
            if slot.startswith("ring_")
            else f"equipment.{slot})"
        )
        for slot in EQUIPMENT_SLOTS
    )
    return rf"""
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
local function safe_u32(address)
  local ok, value = pcall(sd.debug.read_u32, address)
  return ok and (tonumber(value) or 0) or 0
end
local function safe_i32(address)
  local ok, value = pcall(sd.debug.read_i32, address)
  return ok and (tonumber(value) or 0) or 0
end
local function safe_u16(address)
  local ok, value = pcall(sd.debug.read_u16, address)
  return ok and (tonumber(value) or 0) or 0
end
local function safe_u8(address)
  local ok, value = pcall(sd.debug.read_u8, address)
  return ok and (tonumber(value) or 0) or 0
end
local function safe_float(address)
  local ok, value = pcall(sd.debug.read_float, address)
  return ok and (tonumber(value) or 0) or 0
end
local function safe_bytes(address, count)
  local ok, value = pcall(sd.debug.read_bytes, address, count)
  return ok and value or ''
end

local requested = {selector}
local player = sd.player and sd.player.get_state and sd.player.get_state() or nil
local bot = requested ~= nil and sd.bots and sd.bots.get_participant_state and
  sd.bots.get_participant_state(requested) or nil
local public_bot = requested ~= nil and sd.bots and sd.bots.get_state and
  sd.bots.get_state(requested) or nil
local profile = bot and bot.profile or public_bot and public_bot.profile or {{}}
local profile_loadout = profile.loadout or {{}}
local actor = requested == nil and tonumber(player and player.actor_address) or
  tonumber(bot and bot.actor_address)
actor = actor or 0
local progression = requested == nil and
  tonumber(player and player.progression_address) or
  tonumber(bot and bot.progression_runtime_state_address)
progression = progression or 0
local api_handle = requested == nil and
  tonumber(player and player.progression_handle_address) or
  tonumber(bot and bot.progression_handle_address)
api_handle = api_handle or 0
local actor_direct = actor ~= 0 and safe_u32(actor + 0x200) or 0
local actor_handle = actor ~= 0 and safe_u32(actor + 0x300) or 0
local actor_handle_inner = actor_handle ~= 0 and safe_u32(actor_handle) or 0

local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or {{}}
local mp = sd.runtime and sd.runtime.get_multiplayer_state and
  sd.runtime.get_multiplayer_state() or {{}}
local loading = mp.loading_screen or {{}}
local runtime_participant = nil
local participant_matches = 0
for _, participant in ipairs(mp.participants or {{}}) do
  local matches = requested == nil and participant.is_owner or
    (requested ~= nil and tonumber(participant.participant_id) == requested)
  if matches then
    participant_matches = participant_matches + 1
    runtime_participant = participant
  end
end
local owned = runtime_participant and runtime_participant.owned_progression or {{}}

local app_slot = sd.debug.resolve_game_address(0x00B401A8)
local app = safe_u32(app_slot)
emit('scene', scene.name or scene.kind or '')
emit('scene_kind', scene.kind or '')
emit('region_index', scene.region_index or -1)
emit('session_state', mp.session_state or '')
emit('input_sealed', loading.active or false)
emit('participant_count', mp.participant_count or 0)
emit('participant_matches', participant_matches)
emit('tick', player and player.local_player_tick_count or 0)
emit('app_tick', app ~= 0 and safe_u32(app + 0x28) or 0)
emit('actor', actor)
emit('progression', progression)
emit('api_progression_handle', api_handle)
emit('actor_progression_direct', actor_direct)
emit('actor_progression_handle', actor_handle)
emit('actor_progression_handle_inner', actor_handle_inner)
emit('bot_available', requested == nil or bot ~= nil)
emit('bot_profile.element_id', profile.element_id or -1)
emit('bot_profile.discipline_id', profile.discipline_id or -1)
emit('bot_profile.level', profile.level or -1)
emit('bot_profile.experience', profile.experience or -1)
emit('bot_profile.loadout.primary_entry_index', profile_loadout.primary_entry_index or -1)
emit('bot_profile.loadout.primary_combo_entry_index', profile_loadout.primary_combo_entry_index or -1)
local appearance_choices = {{}}
for _, value in ipairs(profile.appearance_choice_ids or {{}}) do
  appearance_choices[#appearance_choices + 1] = tostring(value)
end
emit('bot_profile.appearance_choice_ids', table.concat(appearance_choices, ','))
local secondary_entries = {{}}
for _, value in ipairs(profile_loadout.secondary_entry_indices or {{}}) do
  secondary_entries[#secondary_entries + 1] = tostring(value)
end
emit('bot_profile.loadout.secondary_entry_indices', table.concat(secondary_entries, ','))

emit('participant.id', runtime_participant and runtime_participant.participant_id or 0)
emit('participant.name', runtime_participant and runtime_participant.name or '')
emit('participant.kind', runtime_participant and runtime_participant.kind or '')
emit('participant.is_owner', runtime_participant and runtime_participant.is_owner or false)
emit('participant.level', runtime_participant and runtime_participant.level or 0)
emit('participant.experience', runtime_participant and runtime_participant.experience_current or 0)
emit('participant.life_current', runtime_participant and runtime_participant.life_current or 0)
emit('participant.life_max', runtime_participant and runtime_participant.life_max or 0)
emit('participant.mana_current', runtime_participant and runtime_participant.mana_current or 0)
emit('participant.mana_max', runtime_participant and runtime_participant.mana_max or 0)
emit('participant.move_speed', runtime_participant and runtime_participant.move_speed or 0)
emit('owned.initialized', owned.initialized or false)
emit('owned.spellbook_revision', owned.spellbook_revision or 0)
emit('owned.statbook_revision', owned.statbook_revision or 0)
emit('owned.loadout_revision', owned.loadout_revision or 0)
emit('owned.inventory_revision', owned.inventory_revision or 0)
emit('owned.equipment_revision', owned.equipment_revision or 0)
emit('owned.book_entry_count', owned.progression_book_entry_count or 0)
emit('owned.book_entry_total_count', owned.progression_book_entry_total_count or 0)
emit('owned.book_truncated', owned.progression_book_truncated or false)
emit('owned.inventory_item_count', owned.inventory_item_count or 0)
emit('owned.inventory_item_total_count', owned.inventory_item_total_count or 0)
emit('owned.inventory_truncated', owned.inventory_truncated or false)
for index, item in ipairs(owned.inventory_items or {{}}) do
  local prefix = 'owned.inventory.' .. tostring(index) .. '.'
  emit(prefix .. 'type_id', item.type_id or 0)
  emit(prefix .. 'recipe_uid', item.recipe_uid or 0)
  emit(prefix .. 'slot', item.slot or -1)
  emit(prefix .. 'stack_count', item.stack_count or 0)
end
local equipment = runtime_participant and runtime_participant.equipment or {{}}
emit('equipment.valid', equipment.valid or false)
emit('equipment.revision', equipment.revision or 0)
local rings = equipment.rings or {{}}
local function emit_equipment(name, item)
  item = item or {{}}
  emit('equipment.' .. name .. '.type_id', item.type_id or 0)
  emit('equipment.' .. name .. '.recipe_uid', item.recipe_uid or 0)
end
{equipment_rows}

local inventory = requested == nil and sd.player and sd.player.get_inventory_state and
  sd.player.get_inventory_state() or nil
emit('native_inventory.valid', inventory and inventory.valid or false)
emit('native_inventory.raw_item_count', inventory and inventory.raw_item_count or 0)
emit('native_inventory.item_count', inventory and inventory.item_count or 0)
emit('native_inventory.enumerated_item_count', inventory and inventory.enumerated_item_count or 0)
emit('native_inventory.truncated', inventory and inventory.truncated or false)
for index, item in ipairs(inventory and inventory.items or {{}}) do
  local prefix = 'native_inventory.item.' .. tostring(index) .. '.'
  emit(prefix .. 'type_id', item.type_id or 0)
  emit(prefix .. 'recipe_uid', item.recipe_uid or 0)
  emit(prefix .. 'slot', item.slot or -1)
  emit(prefix .. 'stack_count', item.stack_count or 0)
end

if progression == 0 then return end
local stat_fields = {{
{stat_rows}
}}
for _, field in ipairs(stat_fields) do
  local address = progression + field.offset
  emit('stat.' .. field.name .. '.offset', field.offset)
  emit('stat.' .. field.name .. '.kind', field.kind)
  if field.kind == 'f32' then
    emit('stat.' .. field.name .. '.value', safe_float(address))
    emit('stat.' .. field.name .. '.raw_u32', safe_u32(address))
  elseif field.kind == 'i32' then
    emit('stat.' .. field.name .. '.value', safe_i32(address))
    emit('stat.' .. field.name .. '.raw_u32', safe_u32(address))
  else
    emit('stat.' .. field.name .. '.value', safe_u8(address))
    emit('stat.' .. field.name .. '.raw_u32', safe_u32(address))
  end
end

local table_address = safe_u32(progression + 0x20)
local table_count = safe_i32(progression + 0x24)
emit('book.table', table_address)
emit('book.count', table_count)
if table_address == 0 or table_count ~= {BOOK_ENTRY_COUNT} then return end
for index = 0, table_count - 1 do
  local row = table_address + index * 0x70
  local statbook = safe_u32(row + 0x6C)
  local max_level = -1
  if statbook ~= 0 then
    local ok, value = pcall(sd.debug.read_i32, statbook + 0x5C)
    if ok then max_level = tonumber(value) or -1 end
  end
  local prefix = 'row.' .. tostring(index) .. '.'
  emit(prefix .. 'family_root', safe_u16(row + 0x1C))
  emit(prefix .. 'unknown_0x1e', safe_u16(row + 0x1E))
  emit(prefix .. 'base_rank', safe_u16(row + 0x20))
  emit(prefix .. 'effective_rank', safe_u16(row + 0x22))
  emit(prefix .. 'unknown_0x24', safe_u8(row + 0x24))
  emit(prefix .. 'unknown_0x25', safe_u8(row + 0x25))
  emit(prefix .. 'category', safe_u8(row + 0x26))
  emit(prefix .. 'flags_0x27', safe_u8(row + 0x27))
  emit(prefix .. 'cooldown_current', safe_float(row + 0x64))
  emit(prefix .. 'cooldown_current_raw_u32', safe_u32(row + 0x64))
  emit(prefix .. 'cooldown_cap', safe_float(row + 0x68))
  emit(prefix .. 'cooldown_cap_raw_u32', safe_u32(row + 0x68))
  emit(prefix .. 'statbook', statbook)
  emit(prefix .. 'statbook_max_level', max_level)
end
emit('raw.constructor_scalar', safe_bytes(progression + 0x30, 0xA4))
emit('raw.class_selection', safe_bytes(progression + 0x82C, 0x48))
emit('raw.progression_book', safe_bytes(table_address, {BOOK_BYTE_COUNT}))
""".strip()


def _parse_items(values: Mapping[str, str], prefix: str, count: int) -> list[dict[str, int]]:
    rows: list[dict[str, int]] = []
    for index in range(1, count + 1):
        row_prefix = f"{prefix}.{index}."
        rows.append(
            {
                "type_id": _parse_int(values.get(row_prefix + "type_id"), default=0),
                "recipe_uid": _parse_int(values.get(row_prefix + "recipe_uid"), default=0),
                "slot": _parse_int(values.get(row_prefix + "slot"), default=-1),
                "stack_count": _parse_int(
                    values.get(row_prefix + "stack_count"), default=0
                ),
            }
        )
    return rows


def _parse_int_csv(value: str) -> list[int]:
    if not value:
        return []
    return [_parse_int(item) for item in value.split(",")]


def parse_snapshot(values: Mapping[str, str], participant_id: int | None) -> dict[str, Any]:
    progression_address = _parse_int(values.get("progression"), default=0)
    table_count = _parse_int(values.get("book.count"), default=0)
    if progression_address == 0:
        raise SnapshotNotReady("per-entity progression is not materialized yet")
    if table_count != BOOK_ENTRY_COUNT:
        raise SnapshotNotReady(
            f"per-entity progression book has {table_count} of {BOOK_ENTRY_COUNT} rows"
        )
    if not values.get("raw.progression_book"):
        raise SnapshotNotReady("per-entity progression book bytes are not readable yet")

    stats: dict[str, dict[str, Any]] = {}
    for name, expected_offset, kind in STAT_FIELDS:
        prefix = f"stat.{name}."
        offset = _parse_int(values.get(prefix + "offset"), default=-1)
        require(offset == expected_offset, f"live stat {name} omitted native offset 0x{expected_offset:X}")
        require(values.get(prefix + "kind") == kind, f"live stat {name} changed storage type")
        raw = _parse_int(values.get(prefix + "raw_u32"), default=-1)
        if kind == "f32":
            value: int | float = _f32_from_bits(raw)
        else:
            value = _parse_int(values.get(prefix + "value"), default=0)
        stats[name] = {
            "offset": f"0x{offset:X}",
            "storage": kind,
            "value": value,
            "raw_u32": f"0x{raw & 0xFFFFFFFF:08X}",
        }

    rows: list[dict[str, Any]] = []
    for index in range(table_count):
        prefix = f"row.{index}."
        rows.append(
            {
                "entry_index": index,
                "family_root_u16": _parse_int(values.get(prefix + "family_root"), default=-1),
                "unknown_0x1e_u16": _parse_int(values.get(prefix + "unknown_0x1e"), default=-1),
                "base_rank_u16": _parse_int(values.get(prefix + "base_rank"), default=-1),
                "effective_rank_u16": _parse_int(values.get(prefix + "effective_rank"), default=-1),
                "unknown_0x24_u8": _parse_int(values.get(prefix + "unknown_0x24"), default=-1),
                "unknown_0x25_u8": _parse_int(values.get(prefix + "unknown_0x25"), default=-1),
                "category_u8": _parse_int(values.get(prefix + "category"), default=-1),
                "flags_0x27_u8": _parse_int(values.get(prefix + "flags_0x27"), default=-1),
                "cooldown_current": _f32_from_bits(
                    _parse_int(values.get(prefix + "cooldown_current_raw_u32"), default=0)
                ),
                "cooldown_current_raw_u32": (
                    f"0x{_parse_int(values.get(prefix + 'cooldown_current_raw_u32'), default=0):08X}"
                ),
                "cooldown_cap": _f32_from_bits(
                    _parse_int(values.get(prefix + "cooldown_cap_raw_u32"), default=0)
                ),
                "cooldown_cap_raw_u32": f"0x{_parse_int(values.get(prefix + 'cooldown_cap_raw_u32'), default=0):08X}",
                "statbook_address": _parse_int(values.get(prefix + "statbook"), default=0),
                "statbook_max_level": _parse_int(
                    values.get(prefix + "statbook_max_level"), default=-1
                ),
            }
        )

    constructor_hex = _compact_hex(
        values.get("raw.constructor_scalar", ""),
        0xA4,
        "constructor scalar region",
    )
    selection_hex = _compact_hex(
        values.get("raw.class_selection", ""),
        0x48,
        "class selection region",
    )
    book_hex = _compact_hex(
        values.get("raw.progression_book", ""),
        BOOK_BYTE_COUNT,
        "per-entity progression book",
    )
    normalized_book = bytearray.fromhex(book_hex)
    for index in range(BOOK_ENTRY_COUNT):
        start = index * BOOK_ENTRY_STRIDE + 0x6C
        normalized_book[start : start + 4] = b"\x00\x00\x00\x00"
    normalized_book_hex = normalized_book.hex()

    owned_item_count = _parse_int(values.get("owned.inventory_item_count"), default=0)
    native_item_count = _parse_int(values.get("native_inventory.item_count"), default=0)
    equipment: dict[str, dict[str, int]] = {}
    for slot in EQUIPMENT_SLOTS:
        prefix = f"equipment.{slot}."
        equipment[slot] = {
            "type_id": _parse_int(values.get(prefix + "type_id"), default=0),
            "recipe_uid": _parse_int(values.get(prefix + "recipe_uid"), default=0),
        }
    return {
        "requested_participant_id": participant_id,
        "observed": {
            "scene": values.get("scene", ""),
            "scene_kind": values.get("scene_kind", ""),
            "region_index": _parse_int(values.get("region_index"), default=-1),
            "session_state": values.get("session_state", ""),
            "input_sealed": _bool(values.get("input_sealed")),
            "tick": _parse_int(values.get("tick"), default=0),
            "app_tick": _parse_int(values.get("app_tick"), default=0),
            "participant_count": _parse_int(values.get("participant_count"), default=0),
        },
        "entity": {
            "actor_address": _parse_int(values.get("actor"), default=0),
            "progression_address": progression_address,
            "api_progression_handle_address": _parse_int(
                values.get("api_progression_handle"), default=0
            ),
            "actor_plus_0x200_progression": _parse_int(
                values.get("actor_progression_direct"), default=0
            ),
            "actor_plus_0x300_handle": _parse_int(
                values.get("actor_progression_handle"), default=0
            ),
            "actor_plus_0x300_handle_inner": _parse_int(
                values.get("actor_progression_handle_inner"), default=0
            ),
            "progression_book_address": _parse_int(values.get("book.table"), default=0),
            "progression_book_entry_count": table_count,
        },
        "participant": {
            "match_count": _parse_int(values.get("participant_matches"), default=0),
            "participant_id": _parse_int(values.get("participant.id"), default=0),
            "name": values.get("participant.name", ""),
            "kind": values.get("participant.kind", ""),
            "is_owner": _bool(values.get("participant.is_owner")),
            "level": _parse_int(values.get("participant.level"), default=0),
            "experience": _parse_int(values.get("participant.experience"), default=0),
            "life_current": float(values.get("participant.life_current") or 0),
            "life_max": float(values.get("participant.life_max") or 0),
            "mana_current": float(values.get("participant.mana_current") or 0),
            "mana_max": float(values.get("participant.mana_max") or 0),
            "move_speed": float(values.get("participant.move_speed") or 0),
            "owned_progression": {
                "initialized": _bool(values.get("owned.initialized")),
                "spellbook_revision": _parse_int(values.get("owned.spellbook_revision"), default=0),
                "statbook_revision": _parse_int(values.get("owned.statbook_revision"), default=0),
                "loadout_revision": _parse_int(values.get("owned.loadout_revision"), default=0),
                "inventory_revision": _parse_int(values.get("owned.inventory_revision"), default=0),
                "equipment_revision": _parse_int(values.get("owned.equipment_revision"), default=0),
                "book_entry_count": _parse_int(values.get("owned.book_entry_count"), default=0),
                "book_entry_total_count": _parse_int(
                    values.get("owned.book_entry_total_count"), default=0
                ),
                "book_truncated": _bool(values.get("owned.book_truncated")),
                "inventory_item_count": owned_item_count,
                "inventory_item_total_count": _parse_int(
                    values.get("owned.inventory_item_total_count"), default=0
                ),
                "inventory_truncated": _bool(values.get("owned.inventory_truncated")),
                "inventory_items": _parse_items(
                    values, "owned.inventory", owned_item_count
                ),
            },
            "equipment": {
                "valid": _bool(values.get("equipment.valid")),
                "revision": _parse_int(values.get("equipment.revision"), default=0),
                "slots": equipment,
            },
        },
        "bot_profile": {
            "element_id": _parse_int(values.get("bot_profile.element_id"), default=-1),
            "discipline_id": _parse_int(
                values.get("bot_profile.discipline_id"), default=-1
            ),
            "level": _parse_int(values.get("bot_profile.level"), default=-1),
            "experience": _parse_int(
                values.get("bot_profile.experience"), default=-1
            ),
            "appearance_choice_ids": _parse_int_csv(
                values.get("bot_profile.appearance_choice_ids", "")
            ),
            "loadout": {
                "primary_entry_index": _parse_int(
                    values.get("bot_profile.loadout.primary_entry_index"), default=-1
                ),
                "primary_combo_entry_index": _parse_int(
                    values.get("bot_profile.loadout.primary_combo_entry_index"),
                    default=-1,
                ),
                "secondary_entry_indices": _parse_int_csv(
                    values.get("bot_profile.loadout.secondary_entry_indices", "")
                ),
            },
        },
        "native_inventory": {
            "valid": _bool(values.get("native_inventory.valid")),
            "raw_item_count": _parse_int(
                values.get("native_inventory.raw_item_count"), default=0
            ),
            "item_count": native_item_count,
            "enumerated_item_count": _parse_int(
                values.get("native_inventory.enumerated_item_count"), default=0
            ),
            "truncated": _bool(values.get("native_inventory.truncated")),
            "items": _parse_items(values, "native_inventory.item", native_item_count),
        },
        "stats": stats,
        "progression_book": {
            "entry_stride": "0x70",
            "entry_count": table_count,
            "entries": rows,
        },
        "raw_regions": {
            "constructor_scalar": {
                "progression_offset": "0x30",
                "byte_count": 0xA4,
                "hex": constructor_hex,
                "sha256": hashlib.sha256(bytes.fromhex(constructor_hex)).hexdigest(),
            },
            "class_selection": {
                "progression_offset": "0x82C",
                "byte_count": 0x48,
                "hex": selection_hex,
                "sha256": hashlib.sha256(bytes.fromhex(selection_hex)).hexdigest(),
            },
            "progression_book": {
                "address_source": "progression+0x20",
                "byte_count": BOOK_BYTE_COUNT,
                "hex": book_hex,
                "sha256": hashlib.sha256(bytes.fromhex(book_hex)).hexdigest(),
                "pointer_normalization": "zero each row's +0x6C..+0x6F StatBook pointer",
                "normalized_hex": normalized_book_hex,
                "normalized_sha256": hashlib.sha256(normalized_book).hexdigest(),
            },
        },
    }


def snapshot(pipe_name: str, participant_id: int | None) -> dict[str, Any]:
    values = parse_key_values(
        lua(pipe_name, _snapshot_probe(participant_id), timeout=15.0)
    )
    return parse_snapshot(values, participant_id)


def snapshot_ready(value: Mapping[str, Any], participant_id: int | None) -> tuple[bool, str]:
    observed = value["observed"]
    entity = value["entity"]
    participant = value["participant"]
    owned = participant["owned_progression"]
    if observed["scene"] != "hub" or observed["region_index"] != 0:
        return False, f"scene not hub/0: {observed}"
    if observed["session_state"] != "in-hub":
        return False, f"run-entry session is not in-hub: {observed}"
    if observed["input_sealed"]:
        return False, "input remains sealed"
    if entity["actor_address"] == 0 or entity["progression_address"] == 0:
        return False, f"actor/progression missing: {entity}"
    if entity["progression_book_entry_count"] != BOOK_ENTRY_COUNT:
        return False, f"native book has {entity['progression_book_entry_count']} rows"
    if participant["match_count"] != 1:
        return False, f"participant lookup returned {participant['match_count']} matches"
    if participant_id is None:
        if not owned["initialized"]:
            return False, "participant-owned progression ledger is not initialized"
        if owned["book_entry_total_count"] != BOOK_ENTRY_COUNT or owned["book_truncated"]:
            return False, f"participant-owned book is incomplete: {owned}"
        inventory = value["native_inventory"]
        if not inventory["valid"] or inventory["truncated"] or inventory["item_count"] < 2:
            return False, f"native starter inventory is incomplete: {inventory}"
    elif value["bot_profile"]["element_id"] < 0 or value["bot_profile"]["discipline_id"] < 0:
        return False, f"bot profile is not populated: {value['bot_profile']}"
    return True, "complete"


def structural_payload(snapshot_value: Mapping[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(snapshot_value))
    value["observed"].pop("tick", None)
    value["observed"].pop("app_tick", None)
    for field in DYNAMIC_RUNTIME_STAT_FIELDS:
        value["stats"].pop(field, None)
    return value


def structural_digest(snapshot_value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        structural_payload(snapshot_value),
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_text(encoded)


def class_state_digest(snapshot_value: Mapping[str, Any]) -> str:
    normalized = structural_payload(snapshot_value)
    payload = {
        "entity": normalized["entity"],
        "stats": normalized["stats"],
        "progression_book": normalized["progression_book"],
        "raw_regions": normalized["raw_regions"],
        "native_inventory": normalized["native_inventory"],
        "equipment": normalized["participant"]["equipment"],
    }
    return sha256_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )


def _first_difference(left: Any, right: Any, path: str = "root") -> str:
    if type(left) is not type(right):
        return f"{path}: type {type(left).__name__} -> {type(right).__name__}"
    if isinstance(left, dict):
        keys = sorted(set(left) | set(right))
        for key in keys:
            if key not in left or key not in right:
                return f"{path}.{key}: membership changed"
            difference = _first_difference(left[key], right[key], f"{path}.{key}")
            if difference:
                return difference
        return ""
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: length {len(left)} -> {len(right)}"
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            difference = _first_difference(left_item, right_item, f"{path}[{index}]")
            if difference:
                return difference
        return ""
    return "" if left == right else f"{path}: {left!r} -> {right!r}"


def capture_settled_snapshot(
    pipe_name: str,
    ledger: OwnedProcessLedger,
    participant_id: int | None,
    evidence_path: Path,
) -> dict[str, Any]:
    deadline = time.monotonic() + 60.0
    first: dict[str, Any] | None = None
    last_busy = "snapshot not attempted"
    while time.monotonic() < deadline:
        try:
            candidate = snapshot(pipe_name, participant_id)
            ready, detail = snapshot_ready(candidate, participant_id)
            if ready:
                first = candidate
                break
            last_busy = detail
        except SnapshotNotReady as error:
            require_live_owned_process(ledger, "class initialization is not ready")
            last_busy = str(error)
        except (VerifyFailure, CaptureFailure, subprocess.TimeoutExpired) as error:
            require_live_owned_process(ledger, "class initialization snapshot failed")
            if isinstance(error, CaptureFailure) or not _is_retryable_pipe_failure(error):
                raise CaptureFailure(f"BROKEN: class snapshot probe failed: {error}") from error
            last_busy = str(error)
        time.sleep(0.05)
    require(first is not None, f"BUSY: class initialization never became complete: {last_busy}")

    first_payload = structural_payload(first)
    digest = structural_digest(first)
    samples = [
        {
            "sample_index": 1,
            "tick": first["observed"]["tick"],
            "app_tick": first["observed"]["app_tick"],
            "structural_sha256": digest,
            "dynamic_runtime_stats": {
                field: first["stats"][field]
                for field in DYNAMIC_RUNTIME_STAT_FIELDS
            },
        }
    ]
    settle_started = time.monotonic()
    while (
        len(samples) < SETTLE_MIN_SAMPLES
        or time.monotonic() - settle_started < SETTLE_MIN_SECONDS
    ):
        time.sleep(0.05)
        candidate = snapshot(pipe_name, participant_id)
        ready, detail = snapshot_ready(candidate, participant_id)
        require(ready, f"live class surface lost completeness while settling: {detail}")
        candidate_digest = structural_digest(candidate)
        if candidate_digest != digest:
            instability = {
                "status": "unstable",
                "first_tick": first["observed"]["tick"],
                "changed_tick": candidate["observed"]["tick"],
                "first_sha256": digest,
                "changed_sha256": candidate_digest,
                "first_difference": _first_difference(
                    first_payload, structural_payload(candidate)
                ),
                "first": first,
                "changed": candidate,
            }
            write_json(evidence_path.with_suffix(".instability.json"), instability)
            raise CaptureFailure(
                "live class initialization changed after its first complete controllable tick: "
                + instability["first_difference"]
            )
        samples.append(
            {
                "sample_index": len(samples) + 1,
                "tick": candidate["observed"]["tick"],
                "app_tick": candidate["observed"]["app_tick"],
                "structural_sha256": candidate_digest,
                "dynamic_runtime_stats": {
                    field: candidate["stats"][field]
                    for field in DYNAMIC_RUNTIME_STAT_FIELDS
                },
            }
        )

    settle_seconds = time.monotonic() - settle_started
    dynamic_runtime_fields: dict[str, Any] = {}
    for field in DYNAMIC_RUNTIME_STAT_FIELDS:
        observed_values = [sample["dynamic_runtime_stats"][field] for sample in samples]
        raw_values = [value["raw_u32"] for value in observed_values]
        numeric_values = [value["value"] for value in observed_values]
        dynamic_runtime_fields[field] = {
            "classification": "runtime counter; retained at first tick but excluded from structural digest",
            "first": observed_values[0],
            "last": observed_values[-1],
            "minimum_value": min(numeric_values),
            "maximum_value": max(numeric_values),
            "distinct_raw_u32": list(dict.fromkeys(raw_values)),
        }
    result = {
        "first_complete_controllable_snapshot": first,
        "settle_gate": {
            "required_minimum_consecutive_samples": SETTLE_MIN_SAMPLES,
            "required_minimum_span_seconds": SETTLE_MIN_SECONDS,
            "consecutive_sample_count": len(samples),
            "measured_span_seconds": settle_seconds,
            "first_tick": samples[0]["tick"],
            "last_tick": samples[-1]["tick"],
            "first_app_tick": samples[0]["app_tick"],
            "last_app_tick": samples[-1]["app_tick"],
            "structural_sha256": digest,
            "dynamic_runtime_fields": dynamic_runtime_fields,
            "samples": samples,
        },
    }
    write_json(evidence_path, result)
    return result


def validate_class_snapshot(
    definition: Mapping[str, Any],
    settled: Mapping[str, Any],
) -> None:
    class_key = str(definition["class_key"])
    value = settled["first_complete_controllable_snapshot"]
    entity = value["entity"]
    progression = entity["progression_address"]
    direct = entity["actor_plus_0x200_progression"]
    handle_inner = entity["actor_plus_0x300_handle_inner"]
    require(
        progression in {direct, handle_inner},
        f"{class_key} actor does not own the captured per-entity progression",
    )
    mapping = definition["definition_to_actor_fields"]
    expected_mapping = {
        "element_skill_row": mapping["element_root"]["value"],
        "discipline_skill_row": mapping["discipline_root"]["value"],
        "primary_skill_row": mapping["primary_spell"]["value"],
        "secondary_skill_row": mapping["secondary_spell"]["value"],
    }
    for stat_name, expected in expected_mapping.items():
        actual = value["stats"][stat_name]["value"]
        require(actual == expected, f"{class_key} definition did not map {stat_name}: {actual} != {expected}")
    stat_kinds = {name: kind for name, _, kind in STAT_FIELDS}
    for stat_name, expected_bits in EXPECTED_COMMON_STAT_BITS.items():
        if stat_kinds[stat_name] == "f32":
            actual = int(value["stats"][stat_name]["raw_u32"], 0)
        else:
            actual = int(value["stats"][stat_name]["value"])
        require(
            actual == expected_bits,
            f"{class_key} starting stat {stat_name} changed: "
            f"0x{actual & 0xFFFFFFFF:08X} != 0x{expected_bits:08X}",
        )

    primary = int(mapping["primary_spell"]["value"])
    secondary = int(mapping["secondary_spell"]["value"])
    active = {
        row["entry_index"]
        for row in value["progression_book"]["entries"]
        if row["base_rank_u16"] != 0 or row["effective_rank_u16"] != 0
    }
    expected_active = set(range(8)) | {primary, secondary}
    require(active == expected_active, f"{class_key} starting active rows changed: {sorted(active)}")
    for row in value["progression_book"]["entries"]:
        expected_rank = 1 if row["entry_index"] in expected_active else 0
        require(
            row["base_rank_u16"] == expected_rank
            and row["effective_rank_u16"] == expected_rank,
            f"{class_key} row {row['entry_index']} starting rank changed",
        )

    equipment = value["participant"]["equipment"]["slots"]
    expected_equipment = definition["starting_kit"]["equipment_type_ids"]
    for slot, type_id in expected_equipment.items():
        require(
            equipment[slot]["type_id"] == type_id,
            f"{class_key} starter {slot} type changed: {equipment[slot]}",
        )
    inventory = value["native_inventory"]["items"]
    potion_rows = sorted(
        (item["type_id"], item["slot"])
        for item in inventory
        if item["type_id"] == 7001
    )
    require(
        potion_rows == [(7001, 0), (7001, 1)],
        f"{class_key} starter potion rows changed: {potion_rows}",
    )


def validate_bot_class_snapshot(
    definition: Mapping[str, Any],
    settled: Mapping[str, Any],
) -> None:
    class_key = str(definition["class_key"])
    value = settled["first_complete_controllable_snapshot"]
    entity = value["entity"]
    require(
        entity["progression_address"]
        in {
            entity["actor_plus_0x200_progression"],
            entity["actor_plus_0x300_handle_inner"],
        },
        f"{class_key} bot actor does not own its captured progression book",
    )
    identity = definition["native_identity"]
    profile = value["bot_profile"]
    require(
        profile["element_id"] == identity["profile_element_id"]
        and profile["discipline_id"] == identity["profile_discipline_id"],
        f"{class_key} bot profile lost its semantic class identity: {profile}",
    )
    mapping = definition["definition_to_actor_fields"]
    primary = int(mapping["primary_spell"]["value"])
    discipline = int(mapping["discipline_root"]["value"])
    require(
        value["stats"]["element_skill_row"]["value"] == -1
        and value["stats"]["discipline_skill_row"]["value"] == discipline
        and value["stats"]["primary_skill_row"]["value"] == -1
        and value["stats"]["secondary_skill_row"]["value"] == -1,
        f"{class_key} bot native selection priming changed",
    )
    active = {
        row["entry_index"]
        for row in value["progression_book"]["entries"]
        if row["base_rank_u16"] != 0 or row["effective_rank_u16"] != 0
    }
    expected_active = set(range(8)) | {primary}
    require(
        active == expected_active,
        f"{class_key} bot active progression rows changed: {sorted(active)}",
    )
    for row in value["progression_book"]["entries"]:
        expected_rank = 1 if row["entry_index"] in expected_active else 0
        require(
            row["base_rank_u16"] == expected_rank
            and row["effective_rank_u16"] == expected_rank,
            f"{class_key} bot row {row['entry_index']} starting rank changed",
        )


def spawn_mixed_bot(pipe_name: str) -> int:
    values = parse_key_values(
        lua(
            pipe_name,
            r"""
local player = assert(sd.player.get_state(), 'local player unavailable')
local bot_id = sd.bots.create({
  name = 'Loadout Earth Body Bot',
  profile = {
    element_id = 2,
    discipline_id = 1,
    level = 1,
    experience = 0,
  },
  ready = true,
  position = {
    x = (tonumber(player.x) or 0) + 80,
    y = tonumber(player.y) or 0,
  },
  heading = 180,
})
assert(bot_id ~= nil, 'sd.bots.create returned nil')
print('bot_id=' .. tostring(bot_id))
""".strip(),
            timeout=10.0,
        )
    )
    bot_id = _parse_int(values.get("bot_id"), default=0)
    require(bot_id != 0, f"mixed-class bot returned no participant id: {values}")
    return bot_id


def capture_one_class(
    definition: Mapping[str, Any],
    index: int,
    evidence_directory: Path,
    game_directory: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
    class_key = str(definition["class_key"])
    instance = f"load-gold-{index:02d}-{class_key}"
    expected_executable = ROOT / "runtime" / "instances" / instance / "stage" / "SolomonDark.exe"
    before = process_and_port_probe(expected_executable)
    require(
        not before["process_ids"] and not before["udp_bindings"],
        f"{class_key} preflight found an existing exact process or reserved-port owner: {before}",
    )

    ledger = OwnedProcessLedger()
    launch: dict[str, Any] | None = None
    pipe_name = ""
    receipt: dict[str, Any] = {
        "class_key": class_key,
        "preflight": before,
        "started_at_utc": utc_now(),
    }
    capture: dict[str, Any] | None = None
    mixed: dict[str, Any] | None = None
    loaded_module: dict[str, Any] | None = None
    error: Exception | None = None
    try:
        launch, result_path, log_path = launch_instance(
            definition,
            index,
            evidence_directory,
            game_directory,
        )
        ledger.acquire_launch(launch)
        receipt["launch"] = launch
        receipt["launch_result_path"] = str(result_path)
        receipt["launch_log_path"] = str(log_path)
        receipt["owned_processes_before"] = ledger.inspect()
        pipe_name = str(launch["luaPipe"])
        receipt["lua_readiness"] = wait_for_lua_runnable(pipe_name, ledger)
        loaded_module = loaded_loader_from_startup_log(launch, pipe_name)
        require(
            loaded_module["sha256"] == sha256_file(STAGED_LOADER),
            f"{class_key} live process loaded a different loader DLL",
        )
        receipt["loaded_loader"] = loaded_module
        receipt["selection"] = select_class(pipe_name, ledger, definition)
        capture_path = evidence_directory / "snapshots" / f"{class_key}.json"
        capture = capture_settled_snapshot(pipe_name, ledger, None, capture_path)
        validate_class_snapshot(definition, capture)

        if class_key == "fire-mind":
            local_before = capture["first_complete_controllable_snapshot"]
            bot_id = spawn_mixed_bot(pipe_name)
            bot_capture = capture_settled_snapshot(
                pipe_name,
                ledger,
                bot_id,
                evidence_directory / "snapshots" / "mixed-earth-body-bot.json",
            )
            local_after_capture = capture_settled_snapshot(
                pipe_name,
                ledger,
                None,
                evidence_directory / "snapshots" / "mixed-fire-mind-local-after.json",
            )
            local_after = local_after_capture["first_complete_controllable_snapshot"]
            require(
                class_state_digest(local_before) == class_state_digest(local_after),
                "mixed Earth/Body bot creation changed the local Fire/Mind class book",
            )
            earth_body_matches = [
                item
                for item in build_class_definitions(read_json(SKILL_CATALOG))
                if item["class_key"] == "earth-body"
            ]
            require(
                len(earth_body_matches) == 1,
                f"Earth/Body mixed-case lookup is ambiguous: {len(earth_body_matches)} candidates",
            )
            validate_bot_class_snapshot(earth_body_matches[0], bot_capture)
            bot_snapshot = bot_capture["first_complete_controllable_snapshot"]
            require(
                bot_snapshot["entity"]["progression_address"]
                != local_after["entity"]["progression_address"],
                "mixed-class actors unexpectedly share one progression object",
            )
            require(
                bot_snapshot["entity"]["progression_book_address"]
                != local_after["entity"]["progression_book_address"],
                "mixed-class actors unexpectedly share one progression book",
            )
            mixed = {
                "case_key": "fire-mind-local__earth-body-bot",
                "local_class_key": "fire-mind",
                "bot_class_key": "earth-body",
                "bot_participant_id": bot_id,
                "local_before_bot_class_state_sha256": class_state_digest(local_before),
                "local_after_bot_class_state_sha256": class_state_digest(local_after),
                "local_after_bot": local_after_capture,
                "bot": bot_capture,
                "independence": {
                    "distinct_actor_addresses": True,
                    "distinct_progression_addresses": True,
                    "distinct_progression_book_addresses": True,
                    "local_book_unchanged_by_bot_creation": True,
                },
            }
    except Exception as caught:  # noqa: BLE001 - preserve evidence, then re-raise.
        error = caught
        receipt["failure"] = {"type": type(caught).__name__, "message": str(caught)}
    finally:
        if pipe_name:
            _kill_lua_daemon(pipe_name)
        if not ledger.snapshot() and launch is not None:
            try:
                ledger.acquire_launch(launch)
            except Exception as cleanup_acquire_error:  # noqa: BLE001
                receipt["cleanup_acquire_failure"] = str(cleanup_acquire_error)
        if not ledger.snapshot():
            fallback = process_and_port_probe(expected_executable)
            receipt["cleanup_fallback_probe"] = fallback
            fallback_ids = fallback["process_ids"]
            require(
                len(fallback_ids) <= 1,
                f"{class_key} cleanup fallback found ambiguous exact-stage PIDs: {fallback_ids}",
            )
            if fallback_ids:
                ledger.acquire(
                    [
                        OwnedProcessIdentity(
                            role="host",
                            process_id=fallback_ids[0],
                            executable_path=str(expected_executable),
                            instance=instance,
                        )
                    ]
                )
        receipt["cleanup"] = ledger.stop() if ledger.snapshot() else []
        if launch is not None:
            startup_log = Path(str(launch.get("startupLogPath", "")))
            if startup_log.is_file():
                receipt["startup_log_final"] = {
                    "path": str(startup_log),
                    "sha256": sha256_file(startup_log),
                }
        after = process_and_port_probe(expected_executable)
        receipt["after_cleanup"] = after
        receipt["finished_at_utc"] = utc_now()
        write_json(evidence_directory / "runs" / f"{class_key}.json", receipt)
        require(
            not after["process_ids"] and not after["udp_bindings"],
            f"{class_key} cleanup left an exact process or reserved-port owner: {after}",
        )
    if error is not None:
        raise error
    require(capture is not None and loaded_module is not None, f"{class_key} capture did not complete")
    capture["run_provenance"] = {
        "instance": instance,
        "process_id": launch["processId"],
        "participant_id": launch["participantId"],
        "udp_ports": [LOCAL_PORT, UNUSED_REMOTE_PORT],
        "audio_disabled": launch["audioDisabled"],
        "loaded_loader": loaded_module,
        "evidence_file": str(evidence_directory / "snapshots" / f"{class_key}.json"),
        "evidence_sha256": sha256_file(
            evidence_directory / "snapshots" / f"{class_key}.json"
        ),
        "cleanup_proved": True,
    }
    return capture, mixed, loaded_module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence-directory", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--game-directory", type=Path, default=DEFAULT_GAME_DIRECTORY)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    require(os.name == "nt", "native class golden recorder must run under Windows Python")
    require(args.overwrite or not args.output.exists(), f"fixture already exists: {args.output}")
    require(
        not args.evidence_directory.exists(),
        f"evidence directory already exists: {args.evidence_directory}",
    )
    require(
        LOCAL_PORT != UNUSED_REMOTE_PORT
        and 52411 <= LOCAL_PORT <= 52418
        and 52411 <= UNUSED_REMOTE_PORT <= 52418,
        "recorder ports must be distinct and inside UDP 52411..52418",
    )
    required_files = (
        args.game_directory / "SolomonDark.exe",
        CLASS_CATALOG,
        SKILL_CATALOG,
        ASSET_MAP,
        BINARY_LAYOUT,
        RELEASE_LOADER,
        STAGED_LOADER,
        LAUNCHER,
        LAUNCH_SCRIPT,
    )
    for path in required_files:
        require(path.is_file(), f"required capture input is missing: {path}")
    require(
        sha256_file(RELEASE_LOADER) == sha256_file(STAGED_LOADER),
        "Release loader and launcher-staged loader differ",
    )

    revision = source_revision()
    class_catalog = read_json(CLASS_CATALOG)
    skill_catalog = read_json(SKILL_CATALOG)
    validate_class_catalog(class_catalog)
    definitions = build_class_definitions(skill_catalog)
    args.evidence_directory.mkdir(parents=True)
    capture_started = utc_now()

    captures: list[dict[str, Any]] = []
    mixed_case: dict[str, Any] | None = None
    loaded_loader_hashes: set[str] = set()
    for index, definition in enumerate(definitions, start=1):
        print(f"[{index:02d}/15] capturing {definition['class_key']}", flush=True)
        capture, candidate_mixed, loaded_module = capture_one_class(
            definition,
            index,
            args.evidence_directory,
            args.game_directory,
        )
        captures.append(
            {
                "class_key": definition["class_key"],
                **capture,
            }
        )
        loaded_loader_hashes.add(str(loaded_module["sha256"]))
        if candidate_mixed is not None:
            require(mixed_case is None, "mixed-class capture was produced more than once")
            mixed_case = candidate_mixed
        write_json(
            args.evidence_directory / "capture-progress.json",
            {
                "completed_class_keys": [row["class_key"] for row in captures],
                "mixed_case_complete": mixed_case is not None,
                "updated_at_utc": utc_now(),
            },
        )

    require(
        [row["class_key"] for row in captures]
        == [row["class_key"] for row in definitions],
        "live capture order no longer matches the complete class census",
    )
    require(mixed_case is not None, "live capture omitted the mixed-class participant case")
    require(
        len(loaded_loader_hashes) == 1,
        f"capture instances loaded different loader builds: {loaded_loader_hashes}",
    )

    executable = args.game_directory / "SolomonDark.exe"
    header = {
        "schema": "solomon-dark-class-loadout-goldens-v1",
        "source": {
            "base_commit": revision["sha"],
            "branch": revision["branch"],
            "dirty": revision["dirty"],
            "committed_file_hashes": committed_source_hashes(),
        },
        "capture": {
            "started_at_utc": capture_started,
            "completed_at_utc": utc_now(),
            "method": "live Windows retail instances driven through the opt-in lua-exec observation seam",
            "class_count": len(captures),
            "instance_namespace": "load-*",
            "udp_ports": [LOCAL_PORT, UNUSED_REMOTE_PORT],
            "audio_disabled": True,
            "settle_gate": {
                "minimum_consecutive_samples": SETTLE_MIN_SAMPLES,
                "minimum_span_seconds": SETTLE_MIN_SECONDS,
                "structural_payload": (
                    "actor mapping, every stat, all 83 rows, raw regions, "
                    "inventory, equipment, and participant-owned ledgers; ticks and the "
                    "named progression+0x88C runtime counter excluded"
                ),
            },
        },
        "native_binary": {
            "path": str(executable),
            "sha256": sha256_file(executable),
        },
        "loader": {
            "release_path": str(RELEASE_LOADER),
            "release_sha256": sha256_file(RELEASE_LOADER),
            "launcher_staged_path": str(STAGED_LOADER),
            "launcher_staged_sha256": sha256_file(STAGED_LOADER),
            "loaded_module_sha256": next(iter(loaded_loader_hashes)),
        },
    }
    fixture = {
        "header": header,
        "class_definitions": definitions,
        "unlock_conditions": [
            {"class_key": row["class_key"], **row["unlock"]}
            for row in definitions
        ],
        "captures": captures,
        "mixed_participant_case": mixed_case,
    }
    write_json(args.output, fixture)
    write_json(
        args.evidence_directory / "capture-summary.json",
        {
            "header": header,
            "class_keys": [row["class_key"] for row in captures],
            "mixed_case_key": mixed_case["case_key"],
            "fixture_path": str(args.output),
            "fixture_sha256": sha256_file(args.output),
        },
    )
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(args.output),
                "class_count": len(captures),
                "mixed_case": mixed_case["case_key"],
                "source_sha": revision["sha"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
