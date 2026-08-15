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

EXPECTED_TRIGGER_ASSET_CELLS = {
    "cast.ether.release": r"57 `sounds\magicmissile`, pitch+gain one-shot",
    "cast.fire.release": r"97 `sounds\throwfire`, pitch+gain one-shot",
    "cast.air.channel_start": r"54 `sounds\lightningstart`; start 162 `sounds\lightningloop__loop`",
    "cast.air.channel_hold": "no new request",
    "cast.air.channel_stop": "stop 162",
    "cast.water.channel_start": r"44 `sounds\icestart`; start 161 `sounds\iceloop__loop`",
    "cast.water.channel_hold": "no new request",
    "cast.water.channel_stop": "stop 161",
    "cast.earth.charge_start": r"start 159 `sounds\gatherrocksloop__loop`",
    "cast.earth.boulder_created": r"87 `sounds\startboulder`",
    "cast.earth.charge_hold": "no new request",
    "cast.earth.release": r"stop 159",
    "projectile.ether.flight": r"57 `sounds\magicmissile`",
    "projectile.ether.impact": r"58 `sounds\magicmissilehit`",
    "projectile.fire.flight": r"97 `sounds\throwfire`",
    "projectile.fire.impact": r"30 `sounds\fireballhit`",
    "projectile.air.flight": r"uniform pool 224 `sounds\throwlightning\1`, 225 `...\2`",
    "projectile.air.impact": r"uniform pool 203..205 `sounds\Shock\s1..s3`",
    "projectile.water.flight": r"38 `sounds\frostmissile`",
    "projectile.water.impact": r"36 `sounds\freeze`; then 44 `sounds\icestart` when that branch creates the ice effect",
    "projectile.earth.flight": r"start 168 `sounds\rollingstoneloop__loop`",
    "projectile.earth.flight_end": "stop 168",
    "projectile.earth.impact": r"77 `sounds\rockhit`",
    "melee.player.swing": r"86 `sounds\staffswoosh`",
    "melee.player.hit_world": r"85 `sounds\staffhitwood`",
    "melee.enemy.hit": r"uniform pool 220..221 `sounds\SwordStrike\strike1..2`",
    "movement.footstep.wood": r"104 `sounds\woodstep`",
    "movement.footstep.stone": r"uniform pool 214..215 `sounds\Step\step1..2`",
    "movement.footstep.splash": r"uniform pool 216..219 `sounds\stepsplash\step1..4`",
    "damage.player.taken": r"uniform pool 228..230 `sounds\Wizard_Ouch\SAY_OUCH1..3`",
    "death.player": r"stream 118 `sounds\DeathGuitar__Stream`; immediate song `death`",
    "death.skeleton": r"79 `sounds\skeleton_die`",
    "death.zombie": r"105 `zombiedie`; 108 `zombiepoisonsplat`; conditional 110 `zombie_die_groan`",
    "death.banshee": r"8 `sounds\bansheedie`; preceding terminal flash uses 34 at `0x004960DF`",
    "death.unholy": r"stream 146 `UnholyDie__Stream`; 54 `lightningstart`; 59 `magicshieldexplode`",
    "death.demon": r"20 `sounds\demondies`",
    "death.imp": r"31 `sounds\fireydeath`",
    "death.spider": r"82 `sounds\SpiderDie`",
    "death.golem": r"89 `stonebreak`; 33 `flamelashstart`; stream 125 `GolemDie__Stream`; 77 `rockhit`",
    "death.faculty": r"stream 121 `FacultyDie__Stream`",
    "death.heartmonger": r"pool 179..180 `Chain\clank1..2`; stream 111 `BreakHeartmonger__Stream`",
    "death.portal": r"75 `sounds\PortalDie`",
    "death.coffin": r"15 `sounds\coffinbreak`",
    "death.crow": r"uniform pool 183..184 `sounds\Crow\crow1..2`",
    "death.maggot": r"uniform pool 199..200 `sounds\MaggotSqueak\squeak1..2`",
    "pickup.coin": r"69 `sounds\pickupcoin`",
    "pickup.bag": r"68 `sounds\pickupbag`",
    "pickup.orb": r"2 `sounds\gotorb`",
    "pickup.potion": r"68 `sounds\pickupbag`",
    "pickup.magic_book": r"stream 129 `magicbookget__stream`",
    "potion.use": r"24 `sounds\drink`",
    "potion.invalid": r"6 `sounds\badaction`",
    "level.up": r"52 `sounds\levelup`",
    "skill.turn_undead.cast": r"52 `sounds\levelup`, twice",
    "skill.unlock": r"102 `sounds\unlockskill`",
    "wave.start": "Music transition to song `combat`, track `combat`",
    "wave.end": "Music crossfade to empty song",
    "dig.shovel": r"uniform pool 209..210 `sounds\shovel\shovel1..2`",
    "dig.throw_dirt": r"uniform pool 222..223 `sounds\throwdirt\throwdirt1..2`",
    "shop.purchase": r"25 `sounds\dropcoins`",
    "shop.purchase_rejected": r"6 `sounds\badaction`",
    "shop.storage_transfer": r"4 `backpack_close`, then 0 `click`",
    "ui.focus": "no request",
    "ui.confirm": r"0 `sounds\click`",
    "ui.back": r"4 `sounds\backpack_close`",
    "music.menu_transition": "`prelude`, `selection`, or `academy` through `Music::PlayCrossfade`",
}

EXPECTED_EVENT_CLASSES = tuple(EXPECTED_TRIGGER_ASSET_CELLS)
AUDIO_TRIGGER_DOCUMENT_CLAIM = "native audio trigger document table claim"
AUDIO_TRIGGER_ROW_PATTERN = re.compile(
    r"^\| `(?P<event>[a-z][a-z0-9_.]+)` \| (?P<trigger>[^|\r\n]+?) \| "
    r"(?P<sites>[^|\r\n]+?) \| (?P<assets>[^|\r\n]+?) \| "
    r"(?P<selection>[^|\r\n]+?) \|$"
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


def _expected_registry_ids(asset_cell: str) -> tuple[int, ...]:
    without_literals = re.sub(r"`[^`]*`", "", asset_cell)
    ranges = [
        (int(start), int(end))
        for start, end in re.findall(r"\b(?:uniform )?pool (\d+)\.\.(\d+)", without_literals)
    ]
    without_ranges = re.sub(
        r"\b(?:uniform )?pool \d+\.\.\d+", "", without_literals
    )
    values = {
        int(value)
        for value in re.findall(r"(?<![.A-Za-z0-9_])\d+(?![.A-Za-z0-9_])", without_ranges)
    }
    for start, end in ranges:
        _require(
            start <= end,
            f"{AUDIO_TRIGGER_DOCUMENT_CLAIM}: expected pool range {start}..{end} is reversed",
        )
        values.update(range(start, end + 1))
    return tuple(sorted(values))


def _expected_pool_groups(asset_cell: str) -> tuple[tuple[int, ...], ...]:
    without_literals = re.sub(r"`[^`]*`", "", asset_cell)
    groups = [
        tuple(range(int(start), int(end) + 1))
        for start, end in re.findall(r"\b(?:uniform )?pool (\d+)\.\.(\d+)", without_literals)
    ]
    explicit = re.search(r"\buniform pool (\d+)\s*,\s*(\d+)\b", without_literals)
    if explicit is not None:
        groups.append((int(explicit.group(1)), int(explicit.group(2))))
    return tuple(groups)


def test_native_audio_document_trigger_asset_rows_are_exact() -> str:
    document = read_text(DOCUMENT)
    table_matches = list(
        re.finditer(
            r"^\| Event class \| Native trigger \| Exact call site\(s\) \| "
            r"Requested asset\(s\) \| Selection and parameters \|[ \t]*\r?\n"
            r"^\| --- \| --- \| --- \| --- \| --- \|[ \t]*\r?\n"
            r"(?P<rows>(?:^\|[^\r\n]*\|[ \t]*(?:\r?\n|$))+)",
            document,
            flags=re.MULTILINE,
        )
    )
    _require(
        len(table_matches) == 3,
        f"{AUDIO_TRIGGER_DOCUMENT_CLAIM}: casts, actor/death, and progression/UI trigger tables must be three structural tables, found {len(table_matches)}",
    )
    parsed_rows: list[dict[str, str]] = []
    for table in table_matches:
        for line in table.group("rows").splitlines():
            match = AUDIO_TRIGGER_ROW_PATTERN.fullmatch(line)
            _require(
                match is not None,
                f"{AUDIO_TRIGGER_DOCUMENT_CLAIM}: a trigger row lost its explicit five-column structure",
            )
            parsed_rows.append(match.groupdict())
    events = [row["event"] for row in parsed_rows]
    duplicates = sorted({event for event in events if events.count(event) > 1})
    _require(
        not duplicates,
        f"{AUDIO_TRIGGER_DOCUMENT_CLAIM}: duplicate document trigger rows {duplicates} make asset selection ambiguous",
    )
    _require(
        len(parsed_rows) == 66
        and tuple(events) == EXPECTED_EVENT_CLASSES
        and {
            "cast.air.channel_start",
            "movement.footstep.splash",
            "death.player",
            "music.menu_transition",
        }.issubset(events),
        f"{AUDIO_TRIGGER_DOCUMENT_CLAIM}: document must enumerate the exact 66 trigger rows in reviewed order",
    )
    for row in parsed_rows:
        event = row["event"]
        expected_assets = EXPECTED_TRIGGER_ASSET_CELLS[event]
        _require(
            row["assets"] == expected_assets,
            f"{AUDIO_TRIGGER_DOCUMENT_CLAIM}: {event} doc row requested assets are {row['assets']!r}, expected {expected_assets!r}; its fixed, pool, loop, or stream selection could drift from the fixture and catalog",
        )
    level_up = next(row for row in parsed_rows if row["event"] == "level.up")
    _require(
        level_up["sites"] == "`0x0067C30B -> 0x005C88B0 -> 0x00528A3E`"
        and "Gain `1.0`, once after `0x0067C250`" in level_up["selection"]
        and level_up["assets"] == r"52 `sounds\levelup`",
        "audio trigger document confuses the once-per-award level owner with Turn Undead's separate pitched registry-52 reuse",
    )
    turn_undead = next(
        row for row in parsed_rows if row["event"] == "skill.turn_undead.cast"
    )
    _require(
        turn_undead["sites"] == "`0x00647F6B`; `0x00647FBE`"
        and turn_undead["assets"] == r"52 `sounds\levelup`, twice"
        and "pitch `2.0`, then pitch `3.0`" in turn_undead["selection"]
        and "point-derived gain" in turn_undead["selection"],
        "audio trigger document lost Turn Undead's ordered pitched registry-52 reuse",
    )
    return "all 66 audio trigger rows structurally pin fixed assets, pool ranges, loop/stream ids, and music requests"


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
        timeline_counts["cast.earth.boulder_created"] == 1
        and timeline_counts["cast.earth.release"] == 1
        and timeline_counts["cast.water.channel_start"] == 2
        and timeline_counts["level.up"] == 1
        and timeline_counts["skill.turn_undead.cast"] == 2
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
    catalog_rows = catalog.get("compiled_registry")
    _require(
        isinstance(catalog_rows, list)
        and len(catalog_rows) == 233
        and all(isinstance(row, dict) for row in catalog_rows),
        "audio trigger contract no longer reaches the complete 233-slot catalog",
    )
    catalog_by_index = {row.get("registry_index"): row for row in catalog_rows}
    _require(
        len(catalog_by_index) == 233
        and set(catalog_by_index) == set(range(233)),
        "audio trigger catalog lookup can silently choose a duplicate or omit a registry slot",
    )
    _require(
        len(EXPECTED_TRIGGER_ASSET_CELLS) == 66
        and EXPECTED_TRIGGER_ASSET_CELLS["movement.footstep.splash"].startswith(
            "uniform pool 216..219"
        )
        and EXPECTED_TRIGGER_ASSET_CELLS["death.player"].startswith("stream 118"),
        "audio trigger expected constants lost a concrete pool or stream witness",
    )
    timeline_by_event = {
        event: [row for row in timeline if row.get("event_class") == event]
        for event in EXPECTED_EVENT_CLASSES
    }
    for event, asset_cell in EXPECTED_TRIGGER_ASSET_CELLS.items():
        expected_ids = _expected_registry_ids(asset_cell)
        pool_groups = _expected_pool_groups(asset_cell)
        fixture_rows = timeline_by_event[event]
        _require(
            bool(fixture_rows),
            f"audio fixture row {event} disappeared before its requested assets were checked",
        )
        observed_registry_ids: set[int] = set()
        for fixture_row in fixture_rows:
            requested = fixture_row.get("requested_asset_id")
            if not isinstance(requested, str) or not requested.startswith("registry:"):
                continue
            requested_index = int(requested.split(":", 1)[1])
            observed_registry_ids.add(requested_index)
            selection_pool = fixture_row.get("selection_pool")
            _require(
                isinstance(selection_pool, list) and bool(selection_pool),
                f"audio fixture row {event} lost the concrete selection pool for registry {requested_index}",
            )
            actual_pool = tuple(row.get("registry_index") for row in selection_pool)
            _require(
                all(isinstance(index, int) for index in actual_pool),
                f"audio fixture row {event} has an uninspectable registry selection pool",
            )
            if len(actual_pool) > 1:
                _require(
                    actual_pool in pool_groups,
                    f"audio fixture row {event} selection pool {actual_pool} disagrees with documented pool group(s) {pool_groups}",
                )
            else:
                _require(
                    actual_pool == (requested_index,),
                    f"audio fixture row {event} fixed request {requested_index} has an ambiguous selection pool {actual_pool}",
                )
            _require(
                requested_index in expected_ids,
                f"audio fixture row {event} requests registry {requested_index}, outside documented ids {expected_ids}",
            )
        if expected_ids:
            _require(
                bool(observed_registry_ids),
                f"audio fixture row {event} never dispatches any documented registry id {expected_ids}",
            )

        stream_ids = {
            int(value) for value in re.findall(r"\bstream (\d+)\b", asset_cell)
        }
        loop_ids = {
            int(value) for value in re.findall(r"\b(?:start|stop) (\d+)\b", asset_cell)
        }
        for registry_index in expected_ids:
            catalog_row = catalog_by_index[registry_index]
            expected_class = (
                "SoundStream"
                if registry_index in stream_ids
                else "SoundLoop"
                if registry_index in loop_ids
                else "Sound"
            )
            _require(
                catalog_row.get("native_class") == expected_class,
                f"audio catalog registry {registry_index} for {event} is not the documented {expected_class}",
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
    level_rows = timeline_by_event["level.up"]
    turn_rows = timeline_by_event["skill.turn_undead.cast"]
    _require(
        len(level_rows) == 1
        and level_rows[0]["dispatch_operation"] == "play_gain"
        and level_rows[0]["native_trigger_site"] == "0x00528A3E"
        and level_rows[0]["parameters"]["observed_gain"] == 1.0
        and level_rows[0]["parameters"]["observed_pitch"] == 1.0
        and "once after the complete local threshold loop"
        in level_rows[0]["parameters"]["native_parameter_logic"],
        "audio dispatch golden lost the once-per-award level-up wrapper contract",
    )
    _require(
        len(turn_rows) == 2
        and [row["request_ordinal"] for row in turn_rows] == [1, 2]
        and [row["native_trigger_site"] for row in turn_rows]
        == ["0x00647F6B", "0x00647FBE"]
        and all(row["dispatch_operation"] == "play_pitch_gain" for row in turn_rows)
        and [row["parameters"]["observed_pitch"] for row in turn_rows]
        == [2.0, 3.0]
        and all(row["parameters"]["observed_gain"] == 1.0 for row in turn_rows)
        and all(
            "point-derived gain" in row["parameters"]["native_parameter_logic"]
            for row in turn_rows
        ),
        "audio dispatch golden lost Turn Undead's ordered pitch-2/pitch-3 wrapper contract",
    )
    return (
        "66 gameplay/UI event classes retain clean quiet provenance, exact "
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
