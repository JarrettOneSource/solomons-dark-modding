"""Native audio trigger-census, playback, and ownership contracts."""

from __future__ import annotations

import ast
from collections import Counter
import json
import re
from pathlib import Path
from typing import Any

from static_multiplayer_contract_support import read_source_unit
from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    assert_recorded_hash_matches_file,
    read_text,
)


FIXTURE = ROOT / "tests/fixtures/webgame/audio-event-goldens.json"
DOCUMENT = ROOT / "docs/reverse-engineering/native-audio-events.md"
CATALOG = ROOT / "docs/reverse-engineering/native-audio-catalog.json"
RECORDER = ROOT / "tools/record_audio_event_goldens.py"
AUDIO_SOURCE = ROOT / "SolomonDarkModLoader/src/native_audio_observability.cpp"
PENDING_CAST_PROCESSING = (
    ROOT
    / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/"
    "pending_cast_processing.inl"
)
WORLD_SNAPSHOT_RECONCILIATION = (
    ROOT
    / "SolomonDarkModLoader/src/mod_loader_gameplay/"
    "world_snapshot_reconciliation.inl"
)

GAME_BINARY_SHA256 = (
    "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
)

EXPECTED_EVENT_CLASSES = (
    "cast.ether.release",
    "cast.fire.release",
    "cast.air.channel_start",
    "cast.air.channel_hold",
    "cast.air.channel_stop",
    "cast.water.channel_start",
    "cast.water.channel_hold",
    "cast.water.channel_stop",
    "cast.earth.charge_start",
    "cast.earth.charge_hold",
    "cast.earth.release",
    "projectile.ether.flight",
    "projectile.ether.impact",
    "projectile.fire.flight",
    "projectile.fire.impact",
    "projectile.air.flight",
    "projectile.air.impact",
    "projectile.water.flight",
    "projectile.water.impact",
    "projectile.earth.flight",
    "projectile.earth.flight_end",
    "projectile.earth.impact",
    "melee.player.swing",
    "melee.player.hit_world",
    "melee.enemy.hit",
    "movement.footstep.wood",
    "movement.footstep.stone",
    "movement.footstep.splash",
    "damage.player.taken",
    "death.player",
    "death.skeleton",
    "death.zombie",
    "death.banshee",
    "death.unholy",
    "death.demon",
    "death.imp",
    "death.spider",
    "death.golem",
    "death.faculty",
    "death.heartmonger",
    "death.portal",
    "death.coffin",
    "death.crow",
    "death.maggot",
    "pickup.coin",
    "pickup.bag",
    "pickup.orb",
    "pickup.potion",
    "pickup.magic_book",
    "potion.use",
    "potion.invalid",
    "level.up",
    "skill.unlock",
    "wave.start",
    "wave.end",
    "dig.shovel",
    "dig.throw_dirt",
    "shop.purchase",
    "shop.purchase_rejected",
    "shop.storage_transfer",
    "ui.focus",
    "ui.confirm",
    "ui.back",
    "music.menu_transition",
)

SILENT_EVENT_CLASSES = frozenset(
    {
        "cast.air.channel_hold",
        "cast.water.channel_hold",
        "cast.earth.charge_hold",
        "ui.focus",
    }
)

# registry -> (asset, Hz, channels, bits, frames, smpl ranges)
EXPECTED_LOOP_FORMATS = {
    151: ("sounds\\beam__loop", 44100, 2, 16, 220500, ()),
    152: ("sounds\\comet__loop", 44100, 1, 16, 27230, ()),
    153: ("sounds\\deepthunder__loop", 44100, 2, 16, 93246, ()),
    154: ("sounds\\earthquake__loop", 22050, 1, 16, 84504, ()),
    155: ("sounds\\eerie__loop", 44100, 1, 16, 203197, ()),
    156: ("sounds\\electric__loop", 22255, 1, 8, 15763, ()),
    157: ("sounds\\fire__loop", 33557, 1, 16, 75763, ()),
    158: ("sounds\\flyblown__loop", 11025, 1, 8, 39976, ()),
    159: ("sounds\\gatherrocksloop__loop", 44100, 2, 16, 108620, ()),
    160: ("sounds\\icebeam__loop", 44100, 1, 16, 57835, ()),
    161: ("sounds\\iceloop__loop", 11025, 1, 16, 45845, ()),
    162: ("sounds\\lightningloop__loop", 22050, 1, 16, 58956, ()),
    163: ("sounds\\lowfire__loop", 44100, 2, 8, 450560, ()),
    164: ("sounds\\maggots__loop", 44100, 2, 16, 290305, ((0, 290304),)),
    165: ("sounds\\meteor__loop", 44100, 1, 16, 27230, ()),
    166: ("sounds\\PlaneCross__Loop", 44100, 1, 16, 38011, ()),
    167: ("sounds\\rainfall__loop", 22050, 1, 16, 63207, ()),
    168: ("sounds\\rollingstoneloop__loop", 11025, 1, 16, 32431, ()),
    169: ("sounds\\shockblast__loop", 22255, 1, 8, 10509, ()),
    170: ("sounds\\Soul__Loop", 44100, 2, 16, 420589, ()),
    171: ("sounds\\steadywind__loop", 44100, 2, 16, 49116, ()),
    172: ("sounds\\steam__loop", 22050, 1, 16, 26093, ()),
}


def _require(condition: bool, consequence: str) -> None:
    if not condition:
        raise StaticReTestFailure(consequence)


def _read_json(path: Path, consequence: str) -> dict[str, Any]:
    _require(path.is_file(), consequence)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StaticReTestFailure(f"{consequence}: {exc}") from exc
    _require(isinstance(document, dict), consequence)
    return document


def _assignment_value(module: ast.Module, name: str) -> ast.expr:
    values: list[ast.expr] = []
    for node in module.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                values.append(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            values.append(node.value)
    _require(
        len(values) == 1,
        f"audio recorder {name} has no single unambiguous definition",
    )
    return values[0]


def _recorder_event_classes(module: ast.Module) -> tuple[str, ...]:
    value = _assignment_value(module, "EVENT_SPECS")
    _require(
        isinstance(value, (ast.Tuple, ast.List)),
        "audio recorder event census is no longer a static reviewable sequence",
    )
    classes: list[str] = []
    for element in value.elts:
        _require(
            isinstance(element, ast.Call)
            and isinstance(element.func, ast.Name)
            and element.func.id == "EventSpec"
            and bool(element.args)
            and isinstance(element.args[0], ast.Constant)
            and isinstance(element.args[0].value, str),
            "audio recorder event census contains an unreviewable dynamic label",
        )
        classes.append(element.args[0].value)
    _require(
        bool(classes),
        "audio recorder event census reached no real EventSpec entries",
    )
    return tuple(classes)


def _documented_event_classes(text: str) -> tuple[str, ...]:
    candidates = re.findall(
        r"^\| `([a-z][a-z0-9_.]+)` \|",
        text,
        flags=re.MULTILINE,
    )
    expected = set(EXPECTED_EVENT_CLASSES)
    return tuple(candidate for candidate in candidates if candidate in expected)


def test_native_audio_event_census_and_dispatch_golden_are_pinned() -> str:
    fixture = _read_json(
        FIXTURE,
        "audio event census lost its committed live dispatch fixture",
    )
    _require(
        fixture.get("schema") == "solomon-dark-native-audio-event-goldens-v1",
        "audio event census fixture no longer identifies the dispatch-golden schema",
    )

    header = fixture.get("header")
    _require(
        isinstance(header, dict),
        "audio event census fixture lost its standard provenance header",
    )
    expected_header = {
        "instance": "aud-g5",
        "ports": [52377, 52378],
        "audio_disabled": True,
        "fixture_is_machine_recorded": True,
        "worktree_dirty_at_capture_start": False,
        "game_binary_sha256": GAME_BINARY_SHA256,
        "catalog_path": "docs/reverse-engineering/native-audio-catalog.json",
        "recorder_path": "tools/record_audio_event_goldens.py",
    }
    mismatches = {
        key: header.get(key)
        for key, expected in expected_header.items()
        if header.get(key) != expected
    }
    _require(
        not mismatches,
        f"audio dispatch golden no longer proves a quiet isolated machine capture: {mismatches}",
    )
    _require(
        re.fullmatch(r"[0-9a-f]{40}", str(header.get("source_commit_sha", "")))
        is not None
        and re.fullmatch(r"[0-9a-f]{40}", str(header.get("source_tree_sha", "")))
        is not None,
        "audio dispatch golden no longer names an exact clean source revision",
    )
    _require(
        re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
            str(header.get("captured_utc", "")),
        )
        is not None,
        "audio dispatch golden no longer records its capture time",
    )
    _require(
        header.get("loader_sha256") == header.get("build_loader_sha256")
        and re.fullmatch(r"[0-9a-f]{64}", str(header.get("loader_sha256", "")))
        is not None,
        "audio dispatch golden was not staged with its exact Release build",
    )
    cleanup = header.get("cleanup")
    _require(
        isinstance(cleanup, list) and len(cleanup) == 1,
        "audio dispatch golden lost its one owned-process cleanup receipt",
    )
    cleanup_entry = cleanup[0]
    _require(
        isinstance(cleanup_entry, dict)
        and cleanup_entry.get("instance") == "aud-g5"
        and cleanup_entry.get("processId") == header.get("process_id")
        and cleanup_entry.get("expectedPath") == header.get("executable_path")
        and cleanup_entry.get("actualPath") == header.get("executable_path")
        and cleanup_entry.get("pathMatched") is True
        and cleanup_entry.get("stopped") is True,
        "audio dispatch golden no longer proves exact PID and executable cleanup",
    )
    assert_recorded_hash_matches_file(
        str(header.get("catalog_sha256", "")),
        CATALOG,
        "audio dispatch golden catalog provenance",
    )
    assert_recorded_hash_matches_file(
        str(header.get("recorder_sha256", "")),
        RECORDER,
        "audio dispatch golden recorder provenance",
    )

    recorder_text = read_text(RECORDER)
    recorder_tree = ast.parse(recorder_text, filename=str(RECORDER))
    _require(
        _recorder_event_classes(recorder_tree) == EXPECTED_EVENT_CLASSES,
        "audio recorder lost required trigger classes or changed their stable order",
    )
    source_calls = [
        node
        for node in ast.walk(recorder_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "native_sim"
        and node.func.attr == "source_revision"
    ]
    _require(
        len(source_calls) == 1
        and not source_calls[0].args
        and not source_calls[0].keywords,
        "audio recorder can accept caller-supplied source provenance",
    )
    main_functions = [
        node
        for node in recorder_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "main"
    ]
    _require(
        len(main_functions) == 1
        and not main_functions[0].args.args
        and main_functions[0].args.vararg is None
        and main_functions[0].args.kwarg is None,
        "audio recorder exposes a provenance or launch override through main",
    )
    for token in (
        'os.environ["SDMOD_DISABLE_AUDIO"] = "1"',
        'os.environ["SDMOD_ENABLE_AUDIO"] = "0"',
        'os.environ["SDMOD_CAPTURE_AUDIO_EVENTS"] = "1"',
        'require(not source["worktree_dirty"]',
        "tap is broken, not busy",
        "scene transition is broken, not busy",
    ):
        _require(
            token in recorder_text,
            f"quiet audio recorder can no longer prove {token!r}",
        )

    audio_source = read_source_unit(AUDIO_SOURCE)
    capture_guard = re.search(
        r'if\s*\(\s*capture_requested\s*&&\s*'
        r'!IsEnvironmentFlagSet\("SDMOD_DISABLE_AUDIO"\)\s*\)\s*\{'
        r'.*?SDMOD_DISABLE_AUDIO=1.*?return false;\s*\}',
        audio_source,
        flags=re.DOTALL,
    )
    _require(
        capture_guard is not None,
        "native audio dispatch capture can run with audible output enabled",
    )
    for token in (
        "HookSoundPlayWithPitch",
        "HookSoundStreamPlay",
        "HookSoundLoopStart",
        "HookMusicTransition",
        "event.engine_enabled = ReadEngineEnabled();",
        "kMaximumCapturedDispatchEvents = 4096",
        "match_count != 1",
        "round_trip_index != registry_index",
    ):
        _require(
            token in audio_source,
            f"native dispatch tap no longer proves {token!r}",
        )

    boundary = fixture.get("dispatch_boundary")
    _require(
        isinstance(boundary, dict)
        and boundary.get("environment")
        == {
            "SDMOD_DISABLE_AUDIO": "1",
            "SDMOD_ENABLE_AUDIO": "0",
            "SDMOD_CAPTURE_AUDIO_EVENTS": "1",
        }
        and boundary.get("relative_position")
        == "tap is upstream of the disable point's mixer/device output boundary"
        and "BASS_Init" in str(boundary.get("disable_point", ""))
        and "before" in str(boundary.get("tap_point", ""))
        and "broken, not busy" in str(boundary.get("zero_event_interpretation", "")),
        "audio fixture no longer distinguishes a quiet upstream tap from a disabled trigger path",
    )

    event_classes = fixture.get("event_classes")
    _require(
        event_classes == list(EXPECTED_EVENT_CLASSES),
        "audio event census lost required trigger classes",
    )
    timeline = fixture.get("timeline")
    _require(
        isinstance(timeline, list) and len(timeline) >= len(EXPECTED_EVENT_CLASSES),
        "audio dispatch timeline did not reach every required event class",
    )
    _require(
        all(isinstance(row, dict) for row in timeline),
        "audio dispatch timeline contains an uninspectable row",
    )
    required_row_keys = {
        "tick",
        "event_class",
        "trigger",
        "native_trigger_site",
        "dispatch_operation",
        "requested_asset_id",
        "parameters",
        "capture_kind",
        "engine_enabled",
        "timeline_sequence",
    }
    _require(
        all(required_row_keys <= set(row) for row in timeline),
        "audio dispatch timeline lost tick, trigger-site, asset, or parameter shape",
    )
    timeline_counts = Counter(row["event_class"] for row in timeline)
    _require(
        set(timeline_counts) == set(EXPECTED_EVENT_CLASSES)
        and all(timeline_counts[event_class] >= 1 for event_class in EXPECTED_EVENT_CLASSES),
        "audio dispatch timeline no longer covers every census class at least once",
    )
    _require(
        timeline_counts["cast.earth.release"] == 2
        and timeline_counts["cast.water.channel_start"] == 2
        and timeline_counts["wave.start"] == 1
        and timeline_counts["wave.end"] == 1,
        "audio dispatch timeline lost multi-request cast phases or unique wave transitions",
    )
    _require(
        [row["timeline_sequence"] for row in timeline]
        == list(range(1, len(timeline) + 1))
        and all(isinstance(row["tick"], int) and row["tick"] >= 0 for row in timeline),
        "audio dispatch timeline no longer has ordered native-tick samples",
    )
    _require(
        all(row["engine_enabled"] is False for row in timeline),
        "audio dispatch golden crossed an enabled mixer/device boundary",
    )
    silent_rows = [row for row in timeline if row["requested_asset_id"] is None]
    sounded_rows = [row for row in timeline if row["requested_asset_id"] is not None]
    _require(
        {row["event_class"] for row in silent_rows} == SILENT_EVENT_CLASSES
        and all(
            row["capture_kind"] == "live_silent_phase_checkpoint"
            and row.get("silent_reason")
            for row in silent_rows
        ),
        "audio census can no longer distinguish intentional silent phases from missing captures",
    )
    _require(
        bool(sounded_rows)
        and all(
            row["capture_kind"]
            in {"live_stock_wrapper_probe", "natural_stock_dispatch"}
            and isinstance(row["native_trigger_site"], str)
            and re.fullmatch(r"0x[0-9A-F]{8}", row["native_trigger_site"])
            is not None
            for row in sounded_rows
        ),
        "sounded census rows no longer bind live dispatches to exact native call sites",
    )
    _require(
        all(
            not str(row["requested_asset_id"]).startswith("registry:")
            or (
                isinstance(row.get("requested_asset"), dict)
                and row["requested_asset"].get("registry_index")
                == int(str(row["requested_asset_id"]).split(":", 1)[1])
                and row["requested_asset"] in row.get("selection_pool", [])
            )
            for row in sounded_rows
        ),
        "audio dispatch timeline can disagree with its requested registry asset",
    )

    natural = fixture.get("natural_dispatch_witnesses")
    _require(
        isinstance(natural, list)
        and [
            (
                event.get("caller_return_address"),
                event.get("operation"),
                event.get("requested_name"),
                event.get("requested_track"),
                event.get("engine_enabled"),
            )
            for event in natural
        ]
        == [
            ("0x0058A038", "music_play_crossfade", "prelude", "", False),
            ("0x00470EA2", "music_transition", "combat", "combat", False),
        ],
        "audio dispatch golden lost its two exact in-image stock music witnesses",
    )

    catalog = _read_json(
        CATALOG,
        "audio event census lost the committed native asset catalog",
    )
    _require(
        fixture.get("music_catalog") == catalog.get("music"),
        "audio fixture music catalog disagrees with the committed asset catalog",
    )
    songs = (fixture.get("music_catalog") or {}).get("songs")
    _require(
        isinstance(songs, list)
        and [(song.get("name"), song.get("module_offset")) for song in songs]
        == [
            ("prelude", 0),
            ("combatprelude", 5),
            ("combat", 6),
            ("boss_aggressive", 58),
            ("boss_squirmy", 70),
            ("boss_gargantuan", 82),
            ("solomondarktheme", 95),
            ("selection", 116),
            ("academy", 101),
            ("death", 118),
            ("deathguitar", 122),
            ("academyold", 126),
        ]
        and sum(len(song.get("tracks", [])) for song in songs) == 19,
        "audio music census lost a song order or channel-track set",
    )

    documented = _documented_event_classes(read_text(DOCUMENT))
    _require(
        Counter(documented) == Counter(EXPECTED_EVENT_CLASSES),
        "native audio document no longer maps every event class exactly once",
    )
    return (
        "64 gameplay/UI event classes retain clean quiet provenance, exact "
        "dispatch sites, requested assets, parameters, and music witnesses"
    )


def _documented_loop_formats(text: str) -> dict[int, tuple[Any, ...]]:
    pattern = re.compile(
        r"^\| (?P<index>\d+) \| `(?P<asset>[^`]+)` \| "
        r"(?P<hz>\d+) \| (?P<channels>\d+) \| (?P<bits>\d+) \| "
        r"(?P<frames>\d+) \| (?P<smpl>none|`\d+\.\.\d+` inclusive) \| "
        r"`\[0,(?P<end>\d+)\)` \|$",
        flags=re.MULTILINE,
    )
    rows: dict[int, tuple[Any, ...]] = {}
    matches = list(pattern.finditer(text))
    _require(
        bool(matches),
        "native audio document loop-table parser reached no real rows",
    )
    for match in matches:
        index = int(match.group("index"))
        _require(
            index not in rows,
            f"native audio document has ambiguous duplicate loop registry {index}",
        )
        smpl_text = match.group("smpl")
        smpl: tuple[tuple[int, int], ...] = ()
        if smpl_text != "none":
            smpl_match = re.fullmatch(r"`(\d+)\.\.(\d+)` inclusive", smpl_text)
            _require(
                smpl_match is not None,
                f"loop registry {index} has unparseable WAV smpl metadata",
            )
            smpl = ((int(smpl_match.group(1)), int(smpl_match.group(2))),)
        rows[index] = (
            match.group("asset"),
            int(match.group("hz")),
            int(match.group("channels")),
            int(match.group("bits")),
            int(match.group("frames")),
            smpl,
            int(match.group("end")),
        )
    return rows


def test_native_audio_loop_points_and_playback_semantics_are_pinned() -> str:
    fixture = _read_json(
        FIXTURE,
        "native audio loop contract lost its committed live fixture",
    )
    loops = fixture.get("looping_assets")
    _require(
        isinstance(loops, list) and bool(loops),
        "native audio loop contract reached no real looping assets",
    )
    _require(
        all(isinstance(row, dict) for row in loops),
        "native audio loop contract contains an uninspectable row",
    )
    by_index: dict[int, dict[str, Any]] = {}
    for row in loops:
        index = row.get("registry_index")
        _require(
            isinstance(index, int) and index not in by_index,
            "native audio loop contract contains an absent or ambiguous registry index",
        )
        by_index[index] = row
    _require(
        set(by_index) == set(EXPECTED_LOOP_FORMATS),
        "native audio loop-point table lost one of registry slots 151 through 172",
    )
    _require(
        164 in by_index
        and by_index[164].get("asset_path") == "sounds\\maggots__loop",
        "native audio loop-point sweep missed the only WAV smpl witness",
    )

    catalog = _read_json(
        CATALOG,
        "native audio loop contract lost the committed asset catalog",
    )
    catalog_rows = catalog.get("compiled_registry")
    _require(
        isinstance(catalog_rows, list)
        and len(catalog_rows) == 233
        and all(isinstance(row, dict) for row in catalog_rows),
        "native audio loop contract no longer reaches the complete 233-slot catalog",
    )
    catalog_by_index = {row.get("registry_index"): row for row in catalog_rows}
    _require(
        len(catalog_by_index) == 233
        and set(catalog_by_index) == set(range(233))
        and catalog_by_index[164].get("path_without_extension")
        == "sounds\\maggots__loop",
        "native audio catalog lookup can silently choose a duplicate or miss the smpl witness",
    )

    for index, expected in EXPECTED_LOOP_FORMATS.items():
        row = by_index[index]
        asset, hz, channels, bits, frames, smpl = expected
        actual_smpl = tuple(
            (point.get("start_frame"), point.get("end_frame_inclusive"))
            for point in row.get("wav_smpl_loop_points", [])
        )
        _require(
            (
                row.get("asset_path"),
                row.get("sample_rate_hz"),
                row.get("channels"),
                row.get("bits_per_sample"),
                row.get("sample_frames"),
                actual_smpl,
            )
            == expected,
            f"loop registry {index} no longer matches its exact native WAV format",
        )
        effective = row.get("stock_effective_loop")
        _require(
            isinstance(effective, dict)
            and effective.get("start_frame") == 0
            and effective.get("end_frame_exclusive") == frames
            and "BASS_SAMPLE_LOOP" in str(effective.get("reason", "")),
            f"loop registry {index} no longer restarts over its whole decoded buffer",
        )
        catalog_row = catalog_by_index[index]
        catalog_file = catalog_row.get("file")
        _require(
            isinstance(catalog_file, dict)
            and row.get("native_class") == "SoundLoop"
            and row.get("asset_path") == catalog_row.get("path_without_extension")
            and row.get("file_path") == catalog_file.get("path")
            and row.get("file_sha256") == catalog_file.get("sha256")
            and re.fullmatch(r"[0-9a-f]{64}", str(row.get("file_sha256", "")))
            is not None,
            f"loop registry {index} fixture identity disagrees with the committed catalog",
        )

    documented = _documented_loop_formats(read_text(DOCUMENT))
    expected_documented = {
        index: (*values, values[4])
        for index, values in EXPECTED_LOOP_FORMATS.items()
    }
    _require(
        documented == expected_documented,
        "documented loop-point table disagrees with the standalone live fixture",
    )

    document_text = read_text(DOCUMENT)
    for token in (
        "maximum of ten simultaneous channel records",
        "at ten it drops the new trigger",
        "There is no oldest/quietest/priority stealing",
        "reference transition `0 -> 1`",
        "one channel per `SoundLoop`",
        "one handle per `SoundStream`",
        "two lanes in the single `Music` object",
        "linear_falloff(d, 0.25W, 1.1W)",
        "linear_falloff(d, 0.1W, 0.5W)",
        "No native stereo pan request",
        "`Music::PlayImmediate (0x00409A10)`",
        "`PlayCrossfade (0x00409CD0)`",
        "`Transition (0x00409FA0)`",
    ):
        _require(
            token in document_text,
            f"native audio playback contract no longer pins {token!r}",
        )
    return (
        "all 22 SoundLoop WAV formats, whole-buffer loop points, channel "
        "limits, attenuation, retriggering, and music lanes are exact"
    )


def test_native_audio_multiplayer_ownership_is_stock_transition_owned() -> str:
    document_text = read_text(DOCUMENT)
    ownership_claims = (
        "Receiving or applying a network snapshot is never an audio trigger.",
        "The network packet does not call `Sound`, `SoundLoop`, `SoundStream`, `Music`, or BASS directly.",
        "Repeated snapshots update that actor; they do not construct a new audio owner.",
        "one accepted press edge, at most one stock loop start",
        "one accepted release edge, and a stock-balanced stop",
        "repeatedly called `gatherrocksloop__loop`",
        "leaves transition fields stock-owned",
    )
    missing_claims = [claim for claim in ownership_claims if claim not in document_text]
    _require(
        not missing_claims,
        f"multiplayer audio ownership rule lost consequences: {missing_claims}",
    )

    pending = read_text(PENDING_CAST_PROCESSING)
    _require(
        "bool ProcessPendingBotCast(" in pending,
        "multiplayer audio ownership sweep did not reach ProcessPendingBotCast",
    )
    rearm = re.search(
        r"const bool rearm_missing_startup\s*=\s*"
        r"ongoing\.startup_in_progress\s*&&\s*"
        r"ongoing\.uses_dispatcher_skill_id\s*&&\s*"
        r"!ongoing\.post_stock_dispatch_attempted\s*&&\s*"
        r"!native_activity_after_stock;\s*"
        r"if\s*\(rearm_missing_startup\)\s*\{\s*"
        r"\(void\)memory\.TryWriteField<std::int32_t>\(\s*"
        r"actor_address,\s*kActorPrimarySkillIdOffset,\s*"
        r"ongoing\.dispatcher_skill_id\);\s*\}",
        pending,
        flags=re.DOTALL,
    )
    _require(
        rearm is not None,
        "remote cast startup can replay stock audio transitions after native activity",
    )
    pending_without_guarded_rearm = pending[: rearm.start()] + pending[rearm.end() :]
    _require(
        "kActorPrimarySkillIdOffset" not in pending_without_guarded_rearm
        and "kActorPreviousPrimarySkillIdOffset" not in pending,
        "remote held-cast processing can rewrite current or previous primary transition state",
    )
    dispatcher_hold = re.search(
        r"if\s*\(ongoing\.uses_dispatcher_skill_id\s*&&\s*"
        r"refresh_ongoing_target_state\)\s*\{\s*"
        r"ReapplyOngoingCastSelectionState\(binding, actor_address, ongoing, true\);\s*\}",
        pending,
        flags=re.DOTALL,
    )
    retry_without_activity = re.search(
        r"else if\s*\(\s*ongoing\.uses_dispatcher_skill_id\s*&&\s*"
        r"!native_activity_after_stock\)\s*\{.*?"
        r"ReapplyOngoingCastSelectionState\(binding, actor_address, ongoing, true\);\s*\}",
        pending,
        flags=re.DOTALL,
    )
    _require(
        dispatcher_hold is not None and retry_without_activity is not None,
        "dispatcher selection retries are no longer bounded to held targeting or missing native activity",
    )

    snapshot_source = read_source_unit(WORLD_SNAPSHOT_RECONCILIATION)
    _require(
        "void ApplyReplicatedWorldSnapshotIfActiveImpl(" in snapshot_source,
        "multiplayer audio ownership sweep did not reach real snapshot application",
    )
    forbidden_snapshot_triggers = (
        "DispatchNativeAudioCensusProbe",
        "HookSoundLoopStart",
        "HookSoundLoopStop",
        "gatherrocksloop__loop",
        "music_play_crossfade",
    )
    leaked = [
        trigger
        for trigger in forbidden_snapshot_triggers
        if trigger in snapshot_source
    ]
    _require(
        not leaked,
        f"network snapshot application directly owns audio dispatch: {leaked}",
    )
    return (
        "each peer hears only stock transitions consumed by its local "
        "materialized actors; snapshots never dispatch or replay sound"
    )
