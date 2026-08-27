"""Static contracts for the G10 native-save and launcher persistence boundary."""

from __future__ import annotations

import ast
import base64
from copy import deepcopy
import hashlib
import json
import re
import struct
from pathlib import Path
from typing import Any, Callable

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    assert_recorded_hash_matches_file,
    read_text,
)

from native_save_format import (
    DARKDATA_CORE_FIELDS,
    DARKDATA_KEY,
    FRESH_PROFILE_DEFAULTS,
    SYNCBUFFER_ENDIANNESS,
    SYNCBUFFER_MAGIC,
    SYNCBUFFER_VERSION,
    SaveFormatError,
    apply_portable_profile,
    decode_darkdata_fields,
    decode_gamestate_boast,
    decode_gamestate_local_wizard,
    decode_native_belt,
    decode_native_binding_state,
    decode_native_game_footer,
    decode_darkdata,
    parse_syncbuffer,
    portable_profile_from_buffers,
    validate_portable_profile,
    reencode_fixture_entry,
)


DOC = ROOT / "docs/reverse-engineering/native-save-format.md"
FIXTURE = ROOT / "tests/fixtures/webgame/save-format-goldens.json"
PORTABLE_FIXTURE = (
    ROOT / "tests/fixtures/webgame/portable-profile-template.json"
)
TOOL = ROOT / "tools/native_save_format.py"
RECORDER = ROOT / "tests/re/record_live_save_format_goldens.py"
HUB_DOC = ROOT / "docs/reverse-engineering/native-hub-and-economy.md"
MEMORIAL_DOC = (
    ROOT / "docs/reverse-engineering/native-hall-of-fame-and-memoratorium.md"
)
SKILL_DOC = ROOT / "docs/re/skills-concentration-discipline.md"
LOCAL_SAVE_CATALOG = (
    ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/LocalSaveCatalog.cs"
)
SAVE_DIRECTORY_MIRROR = (
    ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/SaveDirectoryMirror.cs"
)
CLOUD_SAVE_ARCHIVE = (
    ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/CloudSaveArchive.cs"
)
CLOUD_SAVE_CLIENT = (
    ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/CloudSaveClient.cs"
)
CLOUD_BACKUP_COORDINATOR = (
    ROOT
    / "SolomonDarkModLauncher.UI/src/Infrastructure/CloudSaveBackupCoordinator.cs"
)
STEAM_WEBSITE_SESSION = (
    ROOT
    / "SolomonDarkModLauncher.UI/src/Infrastructure/SteamWebsiteSessionClient.cs"
)
UI_SETTINGS_STORE = (
    ROOT / "SolomonDarkModLauncher.UI/src/Infrastructure/LauncherUiSettingsStore.cs"
)
STAGE_BUILDER = ROOT / "SolomonDarkModLauncher/src/Staging/StageBuilder.cs"
STAGE_LINKS = (
    ROOT / "SolomonDarkModLauncher/src/Staging/StageSandboxCompatibilityLinks.cs"
)
STAGED_LAUNCHER = ROOT / "SolomonDarkModLauncher/src/Launch/StagedGameLauncher.cs"
NATIVE_RESUME_SELECTOR = (
    ROOT / "SolomonDarkModLauncher/src/Launch/NativeResumeSelector.cs"
)

EXPECTED_BINARY_SHA256 = (
    "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
)
EXPECTED_FIXTURE_SHA256 = (
    "0c99d595dce635ca0f9793f8f2c1535ab2026216f25a26db7b82475c752c593b"
)
EXPECTED_KEY_SHA256 = (
    "27c0dc1eb34b7d60a2f79cbb60cab0a2da05e336dbf8d75ff8b68d4fad5d0cf3"
)
EXPECTED_CAPTURE_IDS = (
    "fresh_profile",
    "mid_progression_after_scripted_run",
    "post_unlock",
)
EXPECTED_DARKDATA_HASHES = {
    "fresh_profile": "acd77847db8ffdcb6915184eeaa77656e9d127502ff7858542d4dadf7db1a5c9",
    "mid_progression_after_scripted_run": "7d870123ceb96050a0a437f51188855b15a643742a27693595232c724536359e",
    "post_unlock": "01c95c269093610fdb31a9a1857bff5f23a134555318032609c0fe0435ba10e2",
}
EXPECTED_GOLD = {
    "fresh_profile": 500,
    "mid_progression_after_scripted_run": 875,
    "post_unlock": 250,
}

SAVE_DOCUMENT_TABLE_CLAIM = "native save document table claim"
EXPECTED_FRESH_PROFILE_DEFAULTS = {
    "profile_gold": 500,
    "memorial_marker": [False, True, True, True, False, True, True, False, False, True],
    "stock_tutorial_pending": True,
    "hub_help_pending": [True] * 10,
    "memorial_slot_ages": [9, 1, 0, 2, 7, 4, 3, 8, 5, 6],
    "portrait_age_counter": 1000,
    "memorial_portrait_ids": list(range(10)),
    "next_portrait_index": 100,
    "last_portrait_index": 0,
    "librarian_lace_read": False,
    "hagatha_bulk_selectors": [],
    "hagatha_first_mix_flags_before_first_serialization": [False] * 30,
    "settled_persisted_hagatha_flags": [index == 27 for index in range(30)],
    "serializer_initialized_flag_index": 27,
    "shlorio_fee": {"minimum": 500, "maximum": 950, "step": 50},
}
EXPECTED_CORE_FIELD_LAYOUT = (
    ("profile_gold", 0, 4, "i32", 0x58),
    *((f"memorial_marker[{i}]", 4 + i, 1, "bool", 0x90 + i) for i in range(10)),
    ("stock_tutorial_pending", 14, 1, "bool", 0x104),
    *((f"hub_help_pending[{i}]", 15 + i, 1, "bool", 0x9A + i) for i in range(10)),
    *((f"memorial_slot_ages[{i}]", 25 + i * 4, 4, "i32", 0xA4 + i * 4) for i in range(10)),
    ("portrait_age_counter", 65, 4, "i32", 0xF4),
    *((f"memorial_portrait_ids[{i}]", 69 + i * 4, 4, "i32", 0xCC + i * 4) for i in range(10)),
    ("next_portrait_index", 109, 4, "i32", 0xF8),
    ("last_portrait_index", 113, 4, "i32", 0xFC),
    ("librarian_lace_read", 117, 1, "bool", 0x105),
)
EXPECTED_DARKDATA_NODE_ROWS = (
    (0, "fixed 118-byte core, detailed below", "profile object `0x0081A330`", "gold, class/profile state, portrait/stat fields", 118),
    (1, "polymorphic inventory serialization", "profile `+0x8C` (`DAT_0081A3BC`)", "Luthacus Scavenged Goods storage", 4),
    (2, "`u32 count`, then `i32 selector[count]`", "profile `+0x60/+0x64`", "Hagatha bulk selector list", 4),
    (3, "`bool first_mix[30]`", "profile `+0x6C..+0x89`", "per-selector first-mix/purchase flags", 30),
    (4, "one `i32`", "profile `+0x100` (`DAT_0081A430`)", "current Shlorio Dowsing fee", 4),
    (5, "empty payload, zero children", "reserved", "retail writes an empty reserved node", 0),
)
EXPECTED_FIRST_PROFILE_STREAM_ROWS: tuple[dict[str, Any], ...] = (
    {
        "location": "`0x000`",
        "contents": "root payload length `0`, then child count `6`",
        "root_offset": 0,
        "root_payload_length": 0,
        "child_count": 6,
    },
    {
        "location": "`0x008`, payload `0x00C..0x081`",
        "contents": "child 0, 118-byte core",
        "child": 0,
        "offset": 0x008,
        "payload_offset": 0x00C,
        "payload_length": 118,
    },
    {
        "location": "`0x086`, payload `0x08A..0x08D`",
        "contents": "child 1, `00 00 00 00`",
        "child": 1,
        "offset": 0x086,
        "payload_offset": 0x08A,
        "payload_length": 4,
    },
    {
        "location": "`0x092`, payload `0x096..0x099`",
        "contents": "child 2, selector count `0`",
        "child": 2,
        "offset": 0x092,
        "payload_offset": 0x096,
        "payload_length": 4,
    },
    {
        "location": "`0x09E`, payload `0x0A2..0x0BF`",
        "contents": "child 3, 30 flags; only index 27 is `01`",
        "child": 3,
        "offset": 0x09E,
        "payload_offset": 0x0A2,
        "payload_length": 30,
    },
    {
        "location": "`0x0C4`, payload `0x0C8..0x0CB`",
        "contents": "child 4, fee `F4 01 00 00`",
        "child": 4,
        "offset": 0x0C4,
        "payload_offset": 0x0C8,
        "payload_length": 4,
    },
    {
        "location": "`0x0D0`",
        "contents": "empty child 5",
        "child": 5,
        "offset": 0x0D0,
        "payload_offset": 0x0D4,
        "payload_length": 0,
    },
    {
        "location": "`0x0D8`",
        "contents": "root named-buffer count `0`; stream ends at `0x0DC`",
        "named_buffer_count": 0,
        "end_offset": 0x0DC,
    },
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StaticReTestFailure(message)


def _read_text(path: Path, consequence: str) -> str:
    _require(path.is_file(), consequence)
    return read_text(path)


def _read_json(path: Path, consequence: str) -> dict[str, Any]:
    try:
        value = json.loads(_read_text(path, consequence))
    except json.JSONDecodeError as error:
        raise StaticReTestFailure(f"{consequence}: {error}") from error
    _require(isinstance(value, dict), consequence)
    return value


def _require_save_error(
    action: Callable[[], object], expected_fragment: str, message: str
) -> None:
    try:
        action()
    except SaveFormatError as error:
        _require(expected_fragment in str(error), message)
        return
    raise StaticReTestFailure(message)


def _function(tree: ast.Module, name: str, consequence: str) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    _require(len(matches) == 1, consequence)
    return matches[0]


def _called_names(node: ast.AST) -> set[str]:
    calls: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            calls.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            calls.add(child.func.attr)
    return calls


def _darkdata_entry(capture: dict[str, Any]) -> dict[str, Any]:
    matches = [
        row
        for row in capture["files"]
        if row.get("relative_path") == "savegames/solomondark/darkdata.cfg"
    ]
    _require(
        len(matches) == 1,
        f"save golden {capture.get('id')} no longer has one unambiguous darkdata file",
    )
    return matches[0]


def _core_values(entry: dict[str, Any]) -> dict[str, object]:
    fields = entry.get("decoded_fields", {}).get("core_fields", [])
    _require(
        len(fields) == len(DARKDATA_CORE_FIELDS),
        "save golden darkdata field sweep no longer reaches the complete 46-field core",
    )
    return {str(row["name"]): row["value"] for row in fields}


def test_native_save_container_codec_and_layout_are_pinned() -> str:
    _require(
        (SYNCBUFFER_ENDIANNESS, SYNCBUFFER_MAGIC, SYNCBUFFER_VERSION)
        == ("little", None, None),
        "native save container no longer pins little-endian and the absence of magic/version",
    )
    _require(
        hashlib.sha256(DARKDATA_KEY).hexdigest() == EXPECTED_KEY_SHA256,
        "darkdata repeating XOR key no longer matches the retail codec",
    )
    _require(
        DARKDATA_KEY
        == (
            b'MagicEncryptionWord="SolomonDarkEncryption"'
            b"|there$w#st w&187sfj21\t89n4v 1984x98mn12xc39931c87241@@@@@@"
        ),
        "darkdata repeating XOR bytes no longer preserve the embedded TAB and full retail key",
    )

    empty = struct.pack("<III", 0, 0, 0)
    parsed = parse_syncbuffer(empty)
    _require(
        parsed.offset == 0
        and parsed.end_offset == len(empty)
        and parsed.root.payload == b""
        and not parsed.root.children
        and not parsed.named_buffers,
        "SyncBuffer parser no longer consumes the exact headerless empty-tree envelope",
    )
    _require_save_error(
        lambda: parse_syncbuffer(b"\0"),
        "truncated node payload length",
        "SyncBuffer parser no longer refuses a truncated first u32",
    )
    _require_save_error(
        lambda: parse_syncbuffer(empty + b"x"),
        "unclaimed bytes",
        "SyncBuffer parser no longer refuses unclaimed trailing bytes",
    )
    duplicate = (
        struct.pack("<III", 0, 0, 2)
        + struct.pack("<I", 2)
        + b"x\0"
        + empty
        + struct.pack("<I", 2)
        + b"x\0"
        + empty
    )
    _require_save_error(
        lambda: parse_syncbuffer(duplicate),
        "ambiguous duplicate name 'x'",
        "SyncBuffer parser can silently choose between duplicate named buffers",
    )

    tool_text = _read_text(
        TOOL,
        "native save codec implementation disappeared from the repository",
    )
    for witness in (
        'struct.unpack_from("<I"',
        'struct.pack("<I"',
        "marker = min(range(256), key=lambda value: (frequencies[value], value))",
        "if distance > 99_999:",
        "DARKDATA_MAX_DECOMPRESSED_BYTES = 32 * 1024 * 1024",
    ):
        _require(
            witness in tool_text,
            f"native save codec no longer proves retail mechanism witness {witness!r}",
        )
    return "native save container, XOR, marker/LZ, and ambiguity refusal are pinned"


def test_native_save_goldens_round_trip_all_committed_files() -> str:
    fixture = _read_json(
        FIXTURE,
        "native save round-trip fixture is missing or unreadable",
    )
    provenance = fixture.get("provenance")
    _require(
        isinstance(provenance, dict)
        and provenance.get("schema") == "solomon-dark-save-format-goldens-v1",
        "native save fixture no longer carries the G10 provenance schema",
    )
    captures = fixture.get("captures")
    _require(
        isinstance(captures, list)
        and tuple(row.get("id") for row in captures) == EXPECTED_CAPTURE_IDS,
        "native save fixture no longer has the exact fresh, mid-run, and post-unlock witnesses",
    )

    visited_paths: set[tuple[str, str]] = set()
    for capture in captures:
        capture_id = str(capture["id"])
        files = capture.get("files")
        _require(
            isinstance(files, list) and len(files) == 3,
            f"save golden {capture_id} no longer contains darkdata, one Region cache, and settings",
        )
        relative_paths = [str(row.get("relative_path")) for row in files]
        _require(
            "savegames/solomondark/darkdata.cfg" in relative_paths
            and "settings.txt" in relative_paths
            and len([path for path in relative_paths if path.endswith("Region4._cache")]) == 1,
            f"save golden {capture_id} lost a required real persistence-file witness",
        )
        for entry in files:
            path = str(entry["relative_path"])
            visited_paths.add((capture_id, path))
            encoded = reencode_fixture_entry(entry)
            _require(
                len(encoded) == entry.get("length") == entry.get("raw_length"),
                f"save golden {capture_id}/{path} no longer re-encodes to its native byte length",
            )
            encoded_hash = hashlib.sha256(encoded).hexdigest()
            _require(
                encoded_hash
                == entry.get("sha256")
                == entry.get("raw_sha256")
                == entry.get("round_trip_sha256"),
                f"save golden {capture_id}/{path} no longer re-encodes to its raw SHA-256",
            )
            _require(
                entry.get("round_trip_identical") is True,
                f"save golden {capture_id}/{path} no longer records byte-identical round trip",
            )

        darkdata = _darkdata_entry(capture)
        _require(
            darkdata.get("sha256") == EXPECTED_DARKDATA_HASHES[capture_id],
            f"save golden {capture_id} no longer pins its distinct native darkdata recording",
        )
        values = _core_values(darkdata)
        _require(
            values.get("profile_gold") == EXPECTED_GOLD[capture_id],
            f"save golden {capture_id} no longer proves its decoded progression checkpoint",
        )
        expected_mix = [index == 27 for index in range(30)]
        if capture_id == "post_unlock":
            expected_mix[0] = True
        _require(
            darkdata["decoded_fields"].get("hagatha_first_mix_flags")
            == expected_mix,
            f"save golden {capture_id} no longer proves its native unlock flags",
        )

    _require(
        len(visited_paths) == 9,
        "native save round-trip sweep did not examine all nine committed file recordings",
    )
    return "three live saves and all nine decoded files round-trip to exact native hashes"


def test_native_memoratorium_fifo_profile_fields_are_named_and_closed() -> str:
    document = _read_text(
        MEMORIAL_DOC,
        "native Memoratorium FIFO report disappeared",
    )
    for witness in (
        "0x0051549F..0x00515547",
        "0x005BF3B6..0x005BF3CD",
        "0x005CF85A..0x005CF88A",
        "0x00513090",
        "0x00518620",
        "9,1,0,2,7,4,3,8,5,6",
        "2,1,3,6,5,8,9,4,7,0",
        "marker[slot] = Integer(5) != 3",
        "This is FIFO eviction by persisted age",
    ):
        _require(
            witness in document,
            f"native Memoratorium FIFO report lost evidence witness {witness!r}",
        )
    fields = {field.name: field.semantics for field in DARKDATA_CORE_FIELDS}
    _require(
        [fields[f"memorial_marker[{index}]"] for index in range(10)]
        == ["Memoratorium record-8 urn-marker bit"] * 10,
        "darkdata decoder no longer names all ten Memoratorium marker bits",
    )
    _require(
        [fields[f"memorial_slot_ages[{index}]"] for index in range(10)]
        == ["Memoratorium Painting-slot FIFO age"] * 10,
        "darkdata decoder no longer names all ten Memoratorium FIFO ages",
    )
    _require(
        fields.get("portrait_age_counter")
        == "portrait age counter incremented after each raw capture",
        "darkdata decoder lost the portrait age counter",
    )
    _require(
        [fields[f"memorial_portrait_ids[{index}]"] for index in range(10)]
        == ["Memoratorium Painting-slot portrait id"] * 10,
        "darkdata decoder no longer names all ten Memoratorium portrait ids",
    )
    _require(
        fields.get("librarian_lace_read") == "durable BOOK25_LACE one-shot",
        "darkdata decoder lost the durable Lace one-shot",
    )
    return "Memoratorium strict-min FIFO, ten-id ring, reveal, and profile fields are pinned"


def test_native_portable_profile_progression_and_opaque_round_trip_are_exact() -> str:
    fixture = _read_json(
        PORTABLE_FIXTURE,
        "controlled native portable-profile template disappeared",
    )
    files = fixture.get("files")
    expected = fixture.get("expected")
    _require(isinstance(files, dict), "portable template has no file table")
    _require(isinstance(expected, dict), "portable template has no expected-state table")
    try:
        darkdata = base64.b64decode(files["darkdata"]["base64"], validate=True)
        gamestate = base64.b64decode(files["gamestate"]["base64"], validate=True)
    except (KeyError, TypeError, ValueError) as error:
        raise StaticReTestFailure(
            f"portable template does not contain valid base64 files: {error}"
        ) from error
    for name, data in (("darkdata", darkdata), ("gamestate", gamestate)):
        row = files[name]
        _require(
            row.get("bytes") == len(data)
            and row.get("sha256") == hashlib.sha256(data).hexdigest(),
            f"portable template {name} length/hash no longer matches its bytes",
        )

    portable = portable_profile_from_buffers(
        darkdata,
        gamestate,
        str(expected["runName"]),
    )
    validate_portable_profile(portable)
    wizard = portable["wizard"]
    _require(
        wizard["name"] == expected["wizardName"]
        and wizard["level"] == expected["level"]
        and wizard["experience"] == expected["experience"]
        and wizard["elementRoot"] == expected["elementRoot"]
        and wizard["disciplineRoot"] == expected["disciplineRoot"]
        and wizard["startingPrimary"] == expected["startingPrimary"]
        and wizard["startingSecondary"] == expected["startingSecondary"]
        and len(wizard["permanentRanks"]) == expected["progressionRows"],
        "portable template no longer decodes its exact local wizard/progression",
    )
    decoded_base = decode_gamestate_local_wizard(parse_syncbuffer(gamestate))
    _require(
        decoded_base["progression"]["row_count"] == 83
        and len(parse_syncbuffer(gamestate).root.children) == expected["rootChildren"],
        "portable template lost the eight-child/83-row structural witness",
    )

    changed = deepcopy(portable)
    changed["profile"].update(
        {
            "boast": {"selected": 3, "failed": False, "succeeded": True},
            "gold": 12_345,
            "tutorialPending": True,
            "librarianLaceRead": True,
            "hagathaBundleSelectors": [2, 5],
            "firstMixed": [index in (2, 5, 27) for index in range(30)],
            "dowsingFee": 950,
        }
    )
    changed["profile"]["helpPending"][0] = False
    changed["wizard"].update(
        {
            "name": "PORTABILIS",
            "level": 2,
            "experience": 100.0,
            "previousThreshold": 90.0,
            "nextThreshold": 160.0,
            "pendingSkillChoices": 1,
            "deferredSkillChoices": 1,
            "perkSelectors": [5, 27, 0, 27],
            "hagathaOwnership": [index in (0, 5, 27) for index in range(50)],
            "perkCapacity": 9,
            "firewalkerActive": True,
            "concentrationSkillIds": [57, None],
            "nextConcentrationSlot": 1,
            "selectedPrimarySkillId": 16,
            "skillQuickbar": [21, 16, None, None, None, None, None, None],
        }
    )
    changed["wizard"]["permanentRanks"][9] = 2
    changed["wizard"]["permanentRanks"][57] = 1
    changed["wizard"]["learnedOrder"].extend((9, 57))
    retained = b"portrait"
    changed["nativeSource"]["retainedFiles"] = [
        {
            "path": "solomondark/Portraits/portrait100.raw",
            "base64": base64.b64encode(retained).decode("ascii"),
            "sha256": hashlib.sha256(retained).hexdigest(),
        }
    ]
    encoded_darkdata, encoded_gamestate, receipt = apply_portable_profile(changed)
    _require(
        receipt["darkdataRoundTrip"] is True
        and receipt["gamestateRoundTrip"] is True
        and receipt["retainedFileCount"] == 1,
        "portable application no longer re-parses and byte-round-trips its outputs",
    )
    decoded_darkdata = {
        row["name"]: row["value"]
        for row in decode_darkdata_fields(
            decode_darkdata(encoded_darkdata)[1]
        )["core_fields"]
    }
    decoded_wizard = decode_gamestate_local_wizard(parse_syncbuffer(encoded_gamestate))
    decoded_boast = decode_gamestate_boast(parse_syncbuffer(encoded_gamestate))
    _require(
        decoded_darkdata["profile_gold"] == 12_345
        and decoded_darkdata["librarian_lace_read"] is True
        and decoded_wizard["name"] == "PORTABILIS"
        and decoded_wizard["progression"]["level"] == 2
        and decoded_wizard["progression"]["rows"][9]["permanent_rank"] == 2
        and decoded_wizard["progression"]["learned_order"][-1] == 9
        and decoded_wizard["progression"]["perk_selectors"] == [5, 27, 0, 27]
        and decoded_wizard["progression"]["perk_capacity"] == 9
        and decoded_wizard["progression"]["experience_enabled"] is True
        and decoded_wizard["progression"]["random_boast_active"] is True
        and decoded_wizard["selected_primary_skill_id"] == 16
        and decoded_wizard["concentration_skill_ids"] == [57, None]
        and decoded_wizard["next_concentration_slot"] == 1
        and decoded_wizard["skill_quickbar"] == [
            21, 16, None, None, None, None, None, None
        ]
        and decoded_boast == {"selected": 3, "failed": False, "succeeded": True}
        and decoded_wizard["wizard_extension"]["firewalker_active"] is True,
        "portable application did not patch every requested profile/progression member",
    )

    base_dark = decode_darkdata(darkdata)[1]
    next_dark = decode_darkdata(encoded_darkdata)[1]
    _require(
        base_dark.root.children[1] == next_dark.root.children[1]
        and base_dark.root.children[5] == next_dark.root.children[5]
        and base_dark.root.children[0].payload[4:14]
        == next_dark.root.children[0].payload[4:14]
        and base_dark.root.children[0].payload[25:117]
        == next_dark.root.children[0].payload[25:117],
        "portable darkdata application changed opaque storage or memorial siblings",
    )
    base_game = parse_syncbuffer(gamestate)
    next_game = parse_syncbuffer(encoded_gamestate)
    base_binding = decode_native_binding_state(base_game.root)
    next_binding = decode_native_binding_state(next_game.root)
    binding_offsets = {
        int(base_binding["integer_offset"]) + index * 4 + byte
        for index in (12, 16, 20)
        for byte in range(4)
    }
    base_belt = decode_native_belt(base_game.root)
    next_belt = decode_native_belt(next_game.root)
    base_footer = decode_native_game_footer(base_game.root)
    next_footer = decode_native_game_footer(next_game.root)
    footer_offsets = {
        int(base_footer["concentration_cursor_offset"]) + byte
        for byte in range(4)
    }
    _require(
        all(
            base_game.root.children[index] == next_game.root.children[index]
            for index in range(8)
            if index not in (0, 1, 5, 7)
        )
        and all(
            left == right
            for index, (left, right) in enumerate(zip(
                base_binding["node"].payload,
                next_binding["node"].payload,
                strict=True,
            ))
            if index not in binding_offsets
        )
        and base_game.root.children[1].children[1:]
        == next_game.root.children[1].children[1:]
        and all(
            base_game.root.payload[base_belt["entries"][slot]["start"]:
                                   base_belt["entries"][slot]["end"]]
            == next_game.root.payload[next_belt["entries"][slot]["start"]:
                                      next_belt["entries"][slot]["end"]]
            for slot in range(2, 8)
        )
        and all(
            left == right
            for index, (left, right) in enumerate(zip(
                base_footer["node"].payload,
                next_footer["node"].payload,
                strict=True,
            ))
            if index not in footer_offsets
        )
        and base_game.root.children[7].children
        == next_game.root.children[7].children
        and base_game.root.children[0].children[2:]
        == next_game.root.children[0].children[2:]
        and base_game.root.children[0].children[0].children[0]
        == next_game.root.children[0].children[0].children[0],
        "portable gamestate application changed non-wizard or opaque wizard siblings",
    )
    _require(
        b"data\\levels\\survival.boneyard\0"
        in next_game.root.children[5].payload
        and b"native-save-progression-20260826"
        not in next_game.root.children[5].payload,
        "portable gamestate did not normalize the controlled absolute Boneyard path",
    )

    malformed = deepcopy(portable)
    malformed["wizard"]["permanentRanks"].pop()
    _require_save_error(
        lambda: validate_portable_profile(malformed),
        "must contain 83 rows",
        "portable profile accepted a short permanent-rank table",
    )
    malformed_boast = deepcopy(portable)
    malformed_boast["profile"]["boast"] = {
        "selected": None,
        "failed": True,
        "succeeded": False,
    }
    _require_save_error(
        lambda: validate_portable_profile(malformed_boast),
        "Boast lifecycle",
        "portable profile accepted an impossible Boast terminal state",
    )
    third_tonic = deepcopy(changed)
    third_tonic["wizard"]["perkSelectors"].append(27)
    _require_save_error(
        lambda: validate_portable_profile(third_tonic),
        "native Hagatha outcome list",
        "portable profile accepted a third Tonic outcome",
    )
    unsafe_retained = deepcopy(changed)
    unsafe_retained["nativeSource"]["retainedFiles"][0]["path"] = (
        "solomondark/../outside.raw"
    )
    _require_save_error(
        lambda: validate_portable_profile(unsafe_retained),
        "retained file 0 is invalid",
        "portable profile accepted a retained-file traversal",
    )
    trailing = deepcopy(portable)
    trailing_bytes = gamestate + b"x"
    trailing["nativeSource"]["gamestateBase64"] = base64.b64encode(
        trailing_bytes
    ).decode("ascii")
    trailing["nativeSource"]["gamestateSha256"] = hashlib.sha256(
        trailing_bytes
    ).hexdigest()
    _require_save_error(
        lambda: validate_portable_profile(trailing),
        "unclaimed bytes",
        "portable profile accepted a native gamestate with trailing ambiguity",
    )
    return "controlled native Hub, all 83 progression rows, portable mutations, corrupt rejection, and opaque preservation are exact"


def _core_layout_groups() -> list[list[tuple[str, int, int, str, int]]]:
    _require(
        len(EXPECTED_CORE_FIELD_LAYOUT) == 46
        and EXPECTED_CORE_FIELD_LAYOUT[0][0] == "profile_gold"
        and EXPECTED_CORE_FIELD_LAYOUT[-1][0] == "librarian_lace_read",
        f"{SAVE_DOCUMENT_TABLE_CLAIM}: expected core constants lost the first, last, or 46-field census witness",
    )
    groups: list[list[tuple[str, int, int, str, int]]] = []
    for field in EXPECTED_CORE_FIELD_LAYOUT:
        base_name = field[0].split("[", 1)[0]
        if not groups or groups[-1][0][0].split("[", 1)[0] != base_name:
            groups.append([])
        groups[-1].append(field)
    _require(
        len(groups) == 10,
        f"{SAVE_DOCUMENT_TABLE_CLAIM}: core payload constants no longer form ten concrete contiguous rows",
    )
    return groups


def _fresh_group_values(group: list[tuple[str, int, int, str, int]]) -> list[int]:
    values: list[int] = []
    for name, *_ in group:
        if "[" in name:
            base, raw_index = name[:-1].split("[", 1)
            value = EXPECTED_FRESH_PROFILE_DEFAULTS[base][int(raw_index)]
        else:
            value = EXPECTED_FRESH_PROFILE_DEFAULTS[name]
        _require(
            isinstance(value, (bool, int)),
            f"{SAVE_DOCUMENT_TABLE_CLAIM}: {name} has no scalar fresh-value contract",
        )
        values.append(int(value))
    return values


def _parse_hex_span(cell: str, row_label: str) -> tuple[int, int]:
    match = re.fullmatch(r"0x([0-9A-F]+)(?:\.\.0x([0-9A-F]+))?", cell)
    _require(
        match is not None,
        f"{SAVE_DOCUMENT_TABLE_CLAIM}: {row_label} payload span lost its explicit hexadecimal shape",
    )
    start = int(match.group(1), 16)
    end = int(match.group(2), 16) if match.group(2) is not None else start
    return start, end


def test_native_save_document_node_and_payload_tables_are_exact() -> str:
    document = _read_text(
        DOC,
        f"{SAVE_DOCUMENT_TABLE_CLAIM}: native save implementation document disappeared",
    )

    node_table_matches = list(
        re.finditer(
            r"^\| Root child \| Payload layout \| Runtime source \| Meaning \|[ \t]*\r?\n"
            r"^\| ---: \| --- \| --- \| --- \|[ \t]*\r?\n"
            r"(?P<rows>(?:^\|[^\r\n]*\|[ \t]*(?:\r?\n|$))+)",
            document,
            flags=re.MULTILINE,
        )
    )
    _require(
        len(node_table_matches) == 1,
        f"{SAVE_DOCUMENT_TABLE_CLAIM}: the root-child node-format table must be unique and contiguous, found {len(node_table_matches)}",
    )
    node_rows_text = node_table_matches[0].group("rows")
    node_matches = list(
        re.finditer(
            r"^\| (?P<id>\d+) \| (?P<layout>[^|\r\n]+?) \| "
            r"(?P<runtime>[^|\r\n]+?) \| (?P<meaning>[^|\r\n]+?) \|$",
            node_rows_text,
            flags=re.MULTILINE,
        )
    )
    node_ids = [int(match.group("id")) for match in node_matches]
    duplicate_nodes = sorted({node for node in node_ids if node_ids.count(node) > 1})
    _require(
        not duplicate_nodes,
        f"{SAVE_DOCUMENT_TABLE_CLAIM}: duplicate darkdata node rows {duplicate_nodes} make payload decoding ambiguous",
    )
    _require(
        node_ids == list(range(6)),
        f"{SAVE_DOCUMENT_TABLE_CLAIM}: node-format table must enumerate root children 0 through 5 exactly once, observed {node_ids}",
    )
    for node_id, layout, runtime, meaning, _ in EXPECTED_DARKDATA_NODE_ROWS:
        expected_row = f"| {node_id} | {layout} | {runtime} | {meaning} |"
        matches = list(
            re.finditer(rf"^{re.escape(expected_row)}$", node_rows_text, flags=re.MULTILINE)
        )
        _require(
            len(matches) == 1,
            f"{SAVE_DOCUMENT_TABLE_CLAIM}: darkdata node {node_id} doc row no longer pins format {layout!r} and profile source {runtime!r}",
        )

    core_table_matches = list(
        re.finditer(
            r"^\| Payload bytes \| Type \| Runtime field \| Portable meaning \| Fresh value \|[ \t]*\r?\n"
            r"^\| ---: \| --- \| ---: \| --- \| --- \|[ \t]*\r?\n"
            r"(?P<rows>(?:^\|[^\r\n]*\|[ \t]*(?:\r?\n|$))+)",
            document,
            flags=re.MULTILINE,
        )
    )
    _require(
        len(core_table_matches) == 1,
        f"{SAVE_DOCUMENT_TABLE_CLAIM}: the core payload-offset table must be unique and contiguous, found {len(core_table_matches)}",
    )
    core_rows_text = core_table_matches[0].group("rows")
    core_matches = list(
        re.finditer(
            r"^\| `(?P<payload>0x[0-9A-F]+(?:\.\.0x[0-9A-F]+)?)` \| "
            r"`(?P<type>[^`\r\n]+)` \| (?P<runtime>[^|\r\n]+?) \| "
            r"(?P<meaning>[^|\r\n]+?) \| (?P<fresh>[^|\r\n]+?) \|$",
            core_rows_text,
            flags=re.MULTILINE,
        )
    )
    payload_spans = [match.group("payload") for match in core_matches]
    duplicate_spans = sorted(
        {span for span in payload_spans if payload_spans.count(span) > 1}
    )
    _require(
        not duplicate_spans,
        f"{SAVE_DOCUMENT_TABLE_CLAIM}: duplicate core payload rows {duplicate_spans} make field decoding ambiguous",
    )
    expected_groups = _core_layout_groups()
    _require(
        len(core_matches) == len(expected_groups),
        f"{SAVE_DOCUMENT_TABLE_CLAIM}: core payload table exposes {len(core_matches)} structural rows for {len(expected_groups)} expected field groups",
    )
    for match, group in zip(core_matches, expected_groups, strict=True):
        label = group[0][0].split("[", 1)[0]
        actual_start, actual_end = _parse_hex_span(match.group("payload"), label)
        expected_start = group[0][1]
        expected_end = group[-1][1] + group[-1][2] - 1
        _require(
            (actual_start, actual_end) == (expected_start, expected_end),
            f"{SAVE_DOCUMENT_TABLE_CLAIM}: {label} doc row payload span is 0x{actual_start:02X}..0x{actual_end:02X}, expected 0x{expected_start:02X}..0x{expected_end:02X}",
        )
        expected_type = group[0][3] + (f"[{len(group)}]" if len(group) > 1 else "")
        _require(
            match.group("type") == expected_type,
            f"{SAVE_DOCUMENT_TABLE_CLAIM}: {label} doc row type is {match.group('type')!r}, expected {expected_type!r}",
        )
        runtime_offsets = [
            int(value, 16)
            for value in re.findall(r"\+0x([0-9A-F]+)", match.group("runtime"))
        ]
        expected_runtime = [group[0][4]]
        if len(group) > 1:
            expected_runtime.append(group[-1][4] + group[-1][2] - 1)
        _require(
            runtime_offsets == expected_runtime,
            f"{SAVE_DOCUMENT_TABLE_CLAIM}: {label} doc row profile offsets are {runtime_offsets}, expected {expected_runtime}",
        )
        documented_values = (
            [1] * 10
            if match.group("fresh") == "ten `1` bytes"
            else [int(value) for value in re.findall(r"-?\d+", match.group("fresh"))]
        )
        expected_values = _fresh_group_values(group)
        _require(
            documented_values == expected_values,
            f"{SAVE_DOCUMENT_TABLE_CLAIM}: {label} doc row fresh payload values are {documented_values}, expected {expected_values}",
        )

    stream_table_matches = list(
        re.finditer(
            r"^\| Decoded stream location \| Contents \|[ \t]*\r?\n"
            r"^\| ---: \| --- \|[ \t]*\r?\n"
            r"(?P<rows>(?:^\|[^\r\n]*\|[ \t]*(?:\r?\n|$))+)",
            document,
            flags=re.MULTILINE,
        )
    )
    _require(
        len(stream_table_matches) == 1,
        f"{SAVE_DOCUMENT_TABLE_CLAIM}: the first-profile stream-offset table must be unique and contiguous, found {len(stream_table_matches)}",
    )
    stream_rows_text = stream_table_matches[0].group("rows")
    stream_locations = re.findall(
        r"^\| (?P<location>[^|\r\n]+?) \| (?P<contents>[^|\r\n]+?) \|$",
        stream_rows_text,
        flags=re.MULTILINE,
    )
    location_cells = [location for location, _ in stream_locations]
    duplicate_locations = sorted(
        {location for location in location_cells if location_cells.count(location) > 1}
    )
    _require(
        not duplicate_locations,
        f"{SAVE_DOCUMENT_TABLE_CLAIM}: duplicate first-profile stream rows {duplicate_locations} make offsets ambiguous",
    )
    _require(
        len(stream_locations) == len(EXPECTED_FIRST_PROFILE_STREAM_ROWS),
        f"{SAVE_DOCUMENT_TABLE_CLAIM}: first-profile stream table exposes {len(stream_locations)} rows for {len(EXPECTED_FIRST_PROFILE_STREAM_ROWS)} expected offsets",
    )
    for expected in EXPECTED_FIRST_PROFILE_STREAM_ROWS:
        expected_row = f"| {expected['location']} | {expected['contents']} |"
        matches = list(
            re.finditer(rf"^{re.escape(expected_row)}$", stream_rows_text, flags=re.MULTILINE)
        )
        _require(
            len(matches) == 1,
            f"{SAVE_DOCUMENT_TABLE_CLAIM}: decoded stream row {expected['location']} no longer pins {expected['contents']}",
        )

    return "darkdata nodes 0..5, all ten core payload ranges, and all eight first-profile stream offsets are exact"


def test_native_save_fresh_defaults_and_runtime_offsets_are_pinned() -> str:
    _require(
        FRESH_PROFILE_DEFAULTS == EXPECTED_FRESH_PROFILE_DEFAULTS,
        "native missing-profile defaults no longer match the retail initializer and first serializer",
    )

    actual_groups = tuple(
        (
            field.name,
            field.file_offset,
            field.size,
            field.value_type,
            field.runtime_offset,
        )
        for field in DARKDATA_CORE_FIELDS
    )
    _require(
        actual_groups == EXPECTED_CORE_FIELD_LAYOUT and len(actual_groups) == 46,
        "native darkdata core no longer pins all 46 field offsets, types, and runtime mappings",
    )

    fixture = _read_json(
        FIXTURE,
        "native save defaults lost their machine-recorded fixture",
    )
    _require(
        fixture.get("fresh_profile_defaults") == FRESH_PROFILE_DEFAULTS,
        "embedded save defaults and the standalone format implementation disagree",
    )
    format_contract = fixture.get("format_contract")
    expected_format_fields = [
        {
            "name": field.name,
            "payload_offset": field.file_offset,
            "size": field.size,
            "type": field.value_type,
            "runtime_offset": field.runtime_offset,
        }
        for field in DARKDATA_CORE_FIELDS
    ]
    _require(
        format_contract
        == {
            "endianness": "little",
            "magic": None,
            "version": None,
            "darkdata_xor_key_utf8": DARKDATA_KEY.decode("utf-8"),
            "darkdata_core_fields": expected_format_fields,
        },
        "fixture format header and executable decoder no longer agree on magic, version, key, or fields",
    )

    fresh = fixture["captures"][0]
    _require(
        fresh.get("id") == "fresh_profile",
        "fresh-profile defaults no longer resolve through an unambiguous capture witness",
    )
    darkdata = _darkdata_entry(fresh)
    tree = darkdata["tree"]
    children = tree["root"]["children"]
    stream_children = {
        int(row["child"]): row
        for row in EXPECTED_FIRST_PROFILE_STREAM_ROWS
        if "child" in row
    }
    _require(
        len(stream_children) == 6 and set(stream_children) == set(range(6)),
        "native save expected stream constants lost a concrete child row",
    )
    _require(
        [row[4] for row in EXPECTED_DARKDATA_NODE_ROWS]
        == [stream_children[index]["payload_length"] for index in range(6)],
        "native save node formats and first-profile stream constants disagree on child payload lengths",
    )
    _require(
        tree.get("offset") == EXPECTED_FIRST_PROFILE_STREAM_ROWS[0]["root_offset"]
        and tree.get("end_offset") == EXPECTED_FIRST_PROFILE_STREAM_ROWS[-1]["end_offset"]
        and tree["root"].get("offset")
        == EXPECTED_FIRST_PROFILE_STREAM_ROWS[0]["root_offset"]
        and tree["root"].get("payload_length")
        == EXPECTED_FIRST_PROFILE_STREAM_ROWS[0]["root_payload_length"]
        and len(children) == EXPECTED_FIRST_PROFILE_STREAM_ROWS[0]["child_count"]
        and [row["offset"] for row in children]
        == [stream_children[index]["offset"] for index in range(6)]
        and [row["payload_offset"] for row in children]
        == [stream_children[index]["payload_offset"] for index in range(6)]
        and [row["payload_length"] for row in children]
        == [stream_children[index]["payload_length"] for index in range(6)],
        "fresh native profile no longer pins the byte-exact six-child SyncBuffer tree",
    )
    _require(
        children[3]["payload_hex"]
        == "000000000000000000000000000000000000000000000000000000010000",
        "first persisted profile no longer distinguishes initializer flags from serializer-set index 27",
    )
    _require(
        darkdata.get("length") == 211
        and darkdata["codec"].get("syncbuffer_length") == 220
        and darkdata.get("sha256") == EXPECTED_DARKDATA_HASHES["fresh_profile"],
        "fresh profile no longer reifies the exact 220-byte tree as the 211-byte retail file",
    )
    return "fresh defaults, 46 field mappings, and the first serialized tree are exact"


def test_native_save_recorder_is_self_provenanced_settled_bounded_and_owned() -> str:
    source = _read_text(
        RECORDER,
        "native save recorder disappeared, so live provenance cannot be regenerated",
    )
    try:
        tree = ast.parse(source, filename=str(RECORDER))
    except SyntaxError as error:
        raise StaticReTestFailure(
            f"native save recorder is not parseable for provenance review: {error}"
        ) from error

    record = _function(
        tree,
        "record",
        "native save recorder lost its one unambiguous top-level recording flow",
    )
    record_calls = _called_names(record)
    _require(
        {
            "git_output",
            "windows_sha256",
            "snapshot_owned_processes",
            "capture_scenario",
            "validate_capture_set",
        }.issubset(record_calls),
        "native save recorder no longer derives provenance, captures scenarios, validates them, and proves cleanup",
    )
    capture = _function(
        tree,
        "capture_scenario",
        "native save recorder lost its one unambiguous per-scenario flow",
    )
    _require(
        {
            "wait_for_pipe",
            "wait_for_profile",
            "settle_persistence",
            "copy_settled_files",
            "decode_copied_file",
            "validate_live_vs_decoded",
            "close",
        }.issubset(_called_names(capture)),
        "native save scenario no longer runs readiness, settle, copy, decode, cross-check, and cleanup end to end",
    )
    finally_close = any(
        isinstance(node, ast.Try)
        and any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "close"
            for statement in node.finalbody
            for child in ast.walk(statement)
        )
        for node in ast.walk(capture)
    )
    _require(
        finally_close,
        "native save recorder no longer closes exact owned processes from a finally path",
    )

    main = _function(
        tree,
        "main",
        "native save recorder lost its one unambiguous CLI boundary",
    )
    option_names = [
        argument.value
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        for argument in node.args[:1]
        if isinstance(argument, ast.Constant)
        and isinstance(argument.value, str)
        and argument.value.startswith("--")
    ]
    _require(
        option_names == ["--output"],
        "native save recorder exposes provenance, binary, instance, or port override arguments",
    )

    for witness, consequence in (
        ('environment["SDMOD_DISABLE_AUDIO"] = "1"', "child-process audio disable"),
        ('instance.startswith("sav-")', "sav-* instance restriction"),
        ("ALLOWED_PORTS = tuple(range(52401, 52409))", "G10 UDP range restriction"),
        ("SETTLE_SAMPLE_COUNT = 40", "forty-sample settle floor"),
        ("SETTLE_MINIMUM_SECONDS = 2.0", "two-second settle floor"),
        ("Get-FileHash -LiteralPath", "Windows-derived file provenance"),
        ("relative_path = $_.FullName.Substring", "structural path settle payload"),
        ("length = [long]$_.Length", "structural length settle payload"),
        ("sha256 = (Get-FileHash", "structural hash settle payload"),
        ("BROKEN: owned process disappeared", "broken-process stop condition"),
        ("BUSY_TIMEOUT: persistence files never reached", "bounded busy settle condition"),
        ("owner_saves_opened\": False", "owner-save exclusion provenance"),
        ("raw_files_location\": \"evidence only\"", "raw evidence exclusion"),
    ):
        _require(
            witness in source,
            f"native save recorder no longer proves {consequence}",
        )

    fixture = _read_json(
        FIXTURE,
        "native save recorder contract lost the produced fixture",
    )
    provenance = fixture["provenance"]
    _require(
        re.fullmatch(r"[0-9a-f]{40}", str(provenance.get("source_revision", "")))
        is not None
        and provenance.get("retail_executable", {}).get("sha256")
        == EXPECTED_BINARY_SHA256
        and re.fullmatch(
            r"[0-9a-f]{64}", str(provenance.get("loader", {}).get("sha256", ""))
        )
        is not None,
        "native save fixture no longer identifies its exact source and executable inputs",
    )
    contract = provenance.get("capture_contract")
    _require(
        isinstance(contract, dict)
        and contract.get("instances") == ["sav-fresh", "sav-mid", "sav-unlock"]
        and contract.get("allowed_udp_ports") == list(range(52401, 52409))
        and contract.get("audio_disabled") is True
        and contract.get("owner_saves_opened") is False
        and contract.get("raw_files_location") == "evidence only"
        and contract.get("settle_samples") == 40
        and contract.get("settle_minimum_seconds") == 2.0,
        "native save fixture no longer proves isolated ownership and settle provenance",
    )
    captures = fixture.get("captures")
    _require(
        isinstance(captures, list) and len(captures) == 3,
        "native save settle sweep reached no complete three-scenario corpus",
    )
    for row in captures:
        settle = row.get("settle_gate", {})
        _require(
            settle.get("sample_count", 0) >= 40
            and settle.get("stable_seconds", 0.0) >= 2.0
            and settle.get("animated_elements") == [],
            f"native save capture {row.get('id')} no longer proves structural settle",
        )
    return "live recorder derives provenance, distinguishes broken/busy, settles, and cleans exact ownership"


def test_native_save_lifecycle_and_failure_semantics_are_pinned() -> str:
    document = _read_text(
        DOC,
        "native save lifecycle document disappeared from the browser rebuild contract",
    )
    section_order = re.search(
        r"^## Files\s.*?^## Binary format\s.*?"
        r"^## `darkdata\.cfg` field census\s.*?^## Content semantics and runtime mapping\s.*?"
        r"^## Lifecycle\s.*?^## Corruption behavior\s.*?^## Launcher layer\s.*?"
        r"^## Account linkage and the P6 seam\s.*?^## Golden corpus\s.*?"
        r"^## Browser implementation contract\s.*?^## Not Yet Reversed\s",
        document,
        flags=re.MULTILINE | re.DOTALL,
    )
    _require(
        section_order is not None,
        "native save document no longer presents files, bytes, semantics, lifecycle, failure, launcher, account, and residuals in reviewable order",
    )

    required_files = (
        "`settings.txt`",
        "`savegames\\solomondark\\darkdata.cfg`",
        "`savegames\\solomondark\\halloffame.dat`",
        "`savegames\\solomondark\\savegames\\<RUN-NAME>\\gamestate.sav`",
        "`savegames\\solomondark\\savegames\\<RUN-NAME>\\Region<N>._cache`",
        "`Portraits\\portrait<N>.raw`",
    )
    missing_files = [path for path in required_files if path not in document]
    _require(
        not missing_files,
        f"native save file census no longer covers persistence path(s): {missing_files}",
    )
    for witness, consequence in (
        ("direct create/truncate and one write", "non-atomic native overwrite"),
        ("no magic", "absence of a native magic header"),
        ("no version", "absence of native schema versioning"),
        ("no checksum", "absence of native integrity checks"),
        ("0x005BE320", "completed-run archival writer"),
        ("0x005CF920", "hub-return cleanup boundary"),
        ("0x005CD3A0", "quit-time multi-file hazard"),
        ("[`State crossing the hub/run boundary`]", "G8 persistence citation"),
        ("G6's dedicated progression campaign was not landed", "G6 non-speculation boundary"),
    ):
        _require(
            witness in document,
            f"native save lifecycle no longer documents {consequence}",
        )

    corrupt_sequence = re.search(
        r"one-byte `darkdata\.cfg`.*?did not reject it;.*?"
        r"loaded zeroed profile fields.*?later overwrote the file with a normalized 135-byte save",
        document,
        flags=re.DOTALL,
    )
    _require(
        corrupt_sequence is not None,
        "native save failure contract no longer distinguishes truncated zero-fill from missing-profile defaults",
    )
    importer_sequence = re.search(
        r"browser migration boundary should still fail closed: strict-decode a copied\s+"
        r"source, report the corrupt/truncated field and offset, and do not create or\s+"
        r"replace a web save",
        document,
    )
    _require(
        importer_sequence is not None,
        "native save migration boundary no longer refuses corrupt input without overwriting either save",
    )
    _require(
        "The complete object-to-node semantic maps for `gamestate.sav`" in document
        and "Live failure matrices for corrupt/truncated gamestate" in document,
        "native save document guesses unresolved polymorphic or corruption behavior instead of bounding it",
    )
    _require(
        "participant's gold, backpack, equipment, progression" in _read_text(
            HUB_DOC,
            "G8 hub persistence authority disappeared",
        ),
        "G10 lifecycle citation no longer resolves to G8's persistent state witness",
    )
    _require(
        "progression serializer `0x0065EE80` stores ranks" in _read_text(
            SKILL_DOC,
            "landed skill persistence boundary disappeared",
        ),
        "G10 skill boundary no longer resolves to the landed progression serializer witness",
    )
    return "native persistence files, lifecycle, corrupt behavior, G8 citation, and bounded residuals are pinned"


def test_launcher_save_layer_and_account_seam_are_pinned() -> str:
    catalog = _read_text(
        LOCAL_SAVE_CATALOG,
        "launcher local-save catalog disappeared from the G10 seam",
    )
    mirror = _read_text(
        SAVE_DIRECTORY_MIRROR,
        "launcher recoverable directory replacement disappeared from the G10 seam",
    )
    archive = _read_text(
        CLOUD_SAVE_ARCHIVE,
        "launcher cloud archive validator disappeared from the G10 seam",
    )
    cloud = _read_text(
        CLOUD_SAVE_CLIENT,
        "launcher cloud API client disappeared from the G10 seam",
    )
    backup = _read_text(
        CLOUD_BACKUP_COORDINATOR,
        "launcher automatic backup coordinator disappeared from the G10 seam",
    )
    session = _read_text(
        STEAM_WEBSITE_SESSION,
        "launcher Steam-to-website session client disappeared from the G10 seam",
    )
    settings = _read_text(
        UI_SETTINGS_STORE,
        "launcher Settings save-slot owner disappeared from the G10 seam",
    )

    _require(
        "public const int SlotCount = 8;" in catalog
        and 'Path.Combine(settings_.SavesRoot, $"slot-{slot + 1}")' in catalog
        and 'Path.Combine(GetSlotRoot(slot), "savegames")' in catalog,
        "launcher Settings no longer owns exactly eight isolated native save roots",
    )
    import_guard = re.search(
        r"public LocalSaveSlot Import\(.*?"
        r"if \(!Directory\.Exists\(Path\.Combine\(sourceSavegamesRootPath, \"solomondark\"\)\)\)"
        r".*?SaveDirectoryMirror\.Replace\(\s*sourceSavegamesRootPath,\s*"
        r"Path\.Combine\(GetSlotRoot\(slot\), \"savegames\"\)\);",
        catalog,
        flags=re.DOTALL,
    )
    _require(
        import_guard is not None,
        "launcher import no longer requires one unambiguous savegames/solomondark source before replacement",
    )
    metadata_swap = re.search(
        r"var temporaryPath = path \+ \"\.tmp\";\s*"
        r"File\.WriteAllText\(temporaryPath,.*?\);\s*"
        r"File\.Move\(temporaryPath, path, overwrite: true\);",
        catalog,
        flags=re.DOTALL,
    )
    _require(
        metadata_swap is not None
        and 'var temporaryPath = settingsPath_ + ".tmp";' in settings
        and "File.Move(temporaryPath, settingsPath_, overwrite: true);" in settings,
        "launcher slot metadata or active-slot settings no longer use temporary-file replacement",
    )
    mirror_sequence = re.search(
        r"CopyDirectory\(sourcePath, incomingPath\);\s*"
        r"if \(Directory\.Exists\(destinationPath\)\)\s*\{\s*"
        r"Directory\.Move\(destinationPath, previousPath\);\s*\}\s*"
        r"Directory\.Move\(incomingPath, destinationPath\);\s*"
        r"if \(Directory\.Exists\(previousPath\) && Directory\.Exists\(destinationPath\)\)\s*"
        r"\{\s*Directory\.Delete\(previousPath, recursive: true\);",
        mirror,
        flags=re.DOTALL,
    )
    _require(
        mirror_sequence is not None,
        "launcher save replacement no longer stages incoming, preserves previous, swaps, then retires previous in order",
    )
    rollback = re.search(
        r"catch\s*\{\s*if \(!Directory\.Exists\(destinationPath\) && Directory\.Exists\(previousPath\)\)"
        r"\s*\{\s*Directory\.Move\(previousPath, destinationPath\);",
        mirror,
        flags=re.DOTALL,
    )
    _require(
        rollback is not None,
        "launcher save directory swap no longer restores the previous tree when publication fails",
    )

    for witness, consequence in (
        ("public const int FormatVersion = 1;", "archive schema version"),
        ("16 * 1024 * 1024", "compressed archive ceiling"),
        ("64L * 1024 * 1024", "expanded archive ceiling"),
        ("public const int MaxFiles = 256;", "file-count ceiling"),
        ('CreateEntry("manifest.json"', "manifest entry"),
        ("Cloud save archives contain duplicate paths.", "duplicate-path refusal"),
        ("A cloud save file failed its integrity check.", "per-file hash refusal"),
        ("catalog.ReplaceFromRestore(slot, savegamesRoot);", "validated restore swap"),
    ):
        _require(
            witness in archive,
            f"launcher cloud archive no longer enforces {consequence}",
        )
    for endpoint in (
        '"api/saves"',
        '$"api/saves/{slot}"',
    ):
        _require(
            endpoint in cloud,
            f"launcher cloud account seam no longer exposes endpoint {endpoint}",
        )
    _require(
        "HttpMethod.Get" in cloud
        and "HttpMethod.Put" in cloud
        and "HttpMethod.Delete" in cloud
        and 'new HttpRequestMessage(HttpMethod.Delete, "api/auth/steam")' in session,
        "launcher account seam no longer covers authenticated list/upload/restore/delete and unlink operations",
    )
    _require(
        "private static readonly TimeSpan BackupDebounce = TimeSpan.FromSeconds(3);"
        in backup
        and "SaveDirectoryMirror.Replace(" in backup
        and "await BackupCoreAsync(cancellationToken);" in backup,
        "launcher automatic backup no longer debounces native writes and performs final mirror/upload",
    )

    stage_builder = _read_text(
        STAGE_BUILDER,
        "launcher stage construction disappeared from selected-slot routing proof",
    )
    stage_links = _read_text(
        STAGE_LINKS,
        "launcher stage savegames link implementation disappeared from routing proof",
    )
    staged_launcher = _read_text(
        STAGED_LAUNCHER,
        "launcher selected-slot launch call disappeared from routing proof",
    )
    resume_selector = _read_text(
        NATIVE_RESUME_SELECTOR,
        "launcher native Resume selector materializer disappeared",
    )
    _require(
        "StageSandboxCompatibilityLinks.Materialize(configuration.Workspace.StageRootPath);"
        in stage_builder
        and "StageSandboxCompatibilityLinks.PrepareForStageBuild(" in stage_builder
        and stage_builder.find("StageSandboxCompatibilityLinks.PrepareForStageBuild(")
        < stage_builder.find("FileTreeMirror.Synchronize(")
        and "StageSandboxCompatibilityLinks.Materialize(stage.StageRootPath, options.SavegamesRootPath);"
        in staged_launcher
        and "NativeResumeSelector.Materialize(" in staged_launcher
        and 'var sandboxSavegamesPath = Path.Combine(stageRootPath, "sandbox", "savegames");'
        in stage_links
        and 'var stageSavegamesPath = Path.Combine(stageRootPath, "savegames");'
        in stage_links
        and "RecreateDirectoryJunction(sandboxSavegamesPath, savegamesTargetPath);"
        in stage_links
        and 'Path.Combine(stage.StageRoot, "sandbox", "savegames")' in backup,
        "launcher selected slot no longer routes the retail writer and Wine mirror through stage/sandbox/savegames",
    )
    _require(
        'private const string ResumeKey = "Game.Resume";' in resume_selector
        and "ExistingRunName(lines[resumeIndex], runsRoot)" in resume_selector
        and "selectedRun ??= UnambiguousRunName(runsRoot);" in resume_selector
        and "runs.Length == 1 ? runs[0] : null" in resume_selector
        and 'settingsPath + ".resume.tmp"' in resume_selector
        and "File.Move(temporaryPath, settingsPath, overwrite: true);" in resume_selector,
        "launcher Resume bridge no longer preserves a valid run, refuses ambiguity, and replaces settings transactionally",
    )

    document = _read_text(
        DOC,
        "launcher save/account seam disappeared from the native save document",
    )
    for witness, consequence in (
        ("### Historical selected-slot routing defect", "live selected-slot defect and supersession"),
        ("`stage\\sandbox\\savegames` itself the selected-slot junction", "native-path routing closure"),
        ("`NativeResumeSelector` closes the adjacent archive seam", "resume-selector closure"),
        ("stage\\sandbox\\savegames", "actual native write root"),
        ("stage\\savegames", "reported junction root"),
        ("GET api/saves", "account save list seam"),
        ("PUT api/saves/{slot}", "account upload seam"),
        ("GET api/saves/{slot}", "account restore seam"),
        ("DELETE api/saves/{slot}", "account delete seam"),
        ("not add website routes, database tables, or publication", "no-website scope boundary"),
        ("credentials from native `settings.txt` are excluded", "credential exclusion"),
    ):
        _require(
            witness in document,
            f"G10 launcher/account documentation no longer pins {consequence}",
        )
    return "launcher slot swaps, archive integrity, live routing gap, and authenticated P6 seam are pinned"


def test_native_save_fixture_provenance_hashes_the_committed_recording() -> str:
    document = _read_text(
        DOC,
        "native save document no longer names its committed recording",
    )
    match = re.search(
        r"\[`save-format-goldens\.json`\]\(\.\./\.\./tests/fixtures/webgame/save-format-goldens\.json\),\s*"
        r"SHA-256 `([0-9a-f]{64})`",
        document,
    )
    _require(
        match is not None,
        "native save document no longer records a full SHA-256 beside the committed fixture link",
    )
    recorded = match.group(1)
    _require(
        recorded == EXPECTED_FIXTURE_SHA256,
        "native save document's fixture provenance no longer matches the reviewed G10 recording",
    )
    assert_recorded_hash_matches_file(
        recorded,
        FIXTURE,
        "G10 save-format fixture provenance",
    )
    return "the documented G10 fixture hash is checked against the committed recording"


def test_native_active_wizard_saved_run_and_tutorial_boundaries_are_pinned() -> str:
    document = _read_text(
        DOC,
        "native active-wizard save reopening disappeared",
    )
    for witness, consequence in (
        ("`0x0058E260`", "New Game current-wizard confirmation owner"),
        ("`0x0058E600`", "sole New Game confirmation caller"),
        ("`Kill character?`", "exact replacement title"),
        ("Starting a new game will kill off your current game and character", "exact replacement body"),
        ("`0x0058F500`", "separate selected-level resume owner"),
        ("`RESUME PREVIOUS GAME?`", "exact selected-level title"),
        ("`0x005AAA30`", "front-end Last Game constructor"),
        ("`MOV dword ptr [profile+0x58], 500`", "fresh profile gold instruction"),
        ("`profile+0x104 = 1`", "fresh tutorial-pending instruction"),
        ("legacy web wizards migrate pending false", "non-retroactive tutorial migration"),
        ("saved current-wizard state", "wizard save versus Boneyard run distinction"),
        ("client stream, checkpoint", "checkpoint stream identity"),
    ):
        _require(
            witness in document,
            f"native save reopening no longer pins {consequence}",
        )
    return "New Game retirement, Last Game, per-level run, 500-gold, tutorial, and checkpoint-stream boundaries are pinned"


TESTS = [
    test_native_save_container_codec_and_layout_are_pinned,
    test_native_save_goldens_round_trip_all_committed_files,
    test_native_memoratorium_fifo_profile_fields_are_named_and_closed,
    test_native_save_document_node_and_payload_tables_are_exact,
    test_native_save_fresh_defaults_and_runtime_offsets_are_pinned,
    test_native_save_recorder_is_self_provenanced_settled_bounded_and_owned,
    test_native_save_lifecycle_and_failure_semantics_are_pinned,
    test_launcher_save_layer_and_account_seam_are_pinned,
    test_native_active_wizard_saved_run_and_tutorial_boundaries_are_pinned,
    test_native_save_fixture_provenance_hashes_the_committed_recording,
]


if __name__ == "__main__":
    for test in TESTS:
        print(f"PASS: {test.__name__}: {test()}")
