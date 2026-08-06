"""Static contracts for the G10 native-save and launcher persistence boundary."""

from __future__ import annotations

import ast
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
    parse_syncbuffer,
    reencode_fixture_entry,
)


DOC = ROOT / "docs/reverse-engineering/native-save-format.md"
FIXTURE = ROOT / "tests/fixtures/webgame/save-format-goldens.json"
TOOL = ROOT / "tools/native_save_format.py"
RECORDER = ROOT / "tests/re/record_live_save_format_goldens.py"
HUB_DOC = ROOT / "docs/reverse-engineering/native-hub-and-economy.md"
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

EXPECTED_BINARY_SHA256 = (
    "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
)
EXPECTED_FIXTURE_SHA256 = (
    "eff14fb768603abfb47c6d94006a71d04dd2b77954c2458703ca06d773373b8d"
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


def test_native_save_fresh_defaults_and_runtime_offsets_are_pinned() -> str:
    expected_defaults = {
        "profile_gold": 500,
        "class_available": [False, True, True, True, False, True, True, False, False, True],
        "stock_tutorial_pending": True,
        "class_enabled": [True] * 10,
        "class_display_order": [9, 1, 0, 2, 7, 4, 3, 8, 5, 6],
        "profile_stat_0xf4": 1000,
        "class_canonical_order": list(range(10)),
        "next_portrait_index": 100,
        "last_portrait_index": 0,
        "profile_flag_0x105": False,
        "hagatha_bulk_selectors": [],
        "hagatha_first_mix_flags_before_first_serialization": [False] * 30,
        "settled_persisted_hagatha_flags": [index == 27 for index in range(30)],
        "serializer_initialized_flag_index": 27,
        "shlorio_fee": {"minimum": 500, "maximum": 950, "step": 50},
    }
    _require(
        FRESH_PROFILE_DEFAULTS == expected_defaults,
        "native missing-profile defaults no longer match the retail initializer and first serializer",
    )

    expected_groups = (
        ("profile_gold", 0, 4, "i32", 0x58),
        *((f"class_available[{i}]", 4 + i, 1, "bool", 0x90 + i) for i in range(10)),
        ("stock_tutorial_pending", 14, 1, "bool", 0x104),
        *((f"class_enabled[{i}]", 15 + i, 1, "bool", 0x9A + i) for i in range(10)),
        *((f"class_display_order[{i}]", 25 + i * 4, 4, "i32", 0xA4 + i * 4) for i in range(10)),
        ("profile_stat_0xf4", 65, 4, "i32", 0xF4),
        *((f"class_canonical_order[{i}]", 69 + i * 4, 4, "i32", 0xCC + i * 4) for i in range(10)),
        ("next_portrait_index", 109, 4, "i32", 0xF8),
        ("last_portrait_index", 113, 4, "i32", 0xFC),
        ("profile_flag_0x105", 117, 1, "bool", 0x105),
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
        actual_groups == expected_groups and len(actual_groups) == 46,
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
    _require(
        tree.get("offset") == 0
        and tree.get("end_offset") == 220
        and tree["root"].get("offset") == 0
        and tree["root"].get("payload_length") == 0
        and len(children) == 6
        and [row["offset"] for row in children] == [8, 134, 146, 158, 196, 208]
        and [row["payload_offset"] for row in children] == [12, 138, 150, 162, 200, 212]
        and [row["payload_length"] for row in children] == [118, 4, 4, 30, 4, 0],
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
    _require(
        "StageSandboxCompatibilityLinks.Materialize(configuration.Workspace.StageRootPath);"
        in stage_builder
        and "StageSandboxCompatibilityLinks.Materialize(stage.StageRootPath, options.SavegamesRootPath);"
        in staged_launcher
        and 'var stageSavegamesPath = Path.Combine(stageRootPath, "savegames");'
        in stage_links
        and "return RecreateDirectoryJunction(stageSavegamesPath, savegamesTargetPath);"
        in stage_links,
        "launcher selected-slot source no longer matches the live-proven stage/savegames-only routing gap",
    )

    document = _read_text(
        DOC,
        "launcher save/account seam disappeared from the native save document",
    )
    for witness, consequence in (
        ("### Current selected-slot routing defect", "live selected-slot defect"),
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


TESTS = [
    test_native_save_container_codec_and_layout_are_pinned,
    test_native_save_goldens_round_trip_all_committed_files,
    test_native_save_fresh_defaults_and_runtime_offsets_are_pinned,
    test_native_save_recorder_is_self_provenanced_settled_bounded_and_owned,
    test_native_save_lifecycle_and_failure_semantics_are_pinned,
    test_launcher_save_layer_and_account_seam_are_pinned,
    test_native_save_fixture_provenance_hashes_the_committed_recording,
]


if __name__ == "__main__":
    for test in TESTS:
        print(f"PASS: {test.__name__}: {test()}")
