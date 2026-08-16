#!/usr/bin/env python3
"""Record the G5 native-audio event census through the silent dispatch tap.

This recorder launches one disposable solo instance.  Every sample/stream/loop
request uses the real stock wrapper while ``SDMOD_DISABLE_AUDIO=1`` keeps the
BASS engine gate clear.  Event-class labels and native call sites come from the
read-only Ghidra census; the observed registry identity and parameters come
back from the live wrapper hook.  Silent phases are timestamped against a live
dispatch marker and are identified explicitly rather than invented as sounds.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import struct
import sys
import time
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import record_native_sim_goldens as native_sim  # noqa: E402


INSTANCE = "aud-g5"
PORTS = (52377, 52378)
OUTPUT = ROOT / "tests/fixtures/webgame/audio-event-goldens.json"
CATALOG = ROOT / "docs/reverse-engineering/native-audio-catalog.json"
RECORDER = ROOT / "tools/record_audio_event_goldens.py"
RUNTIME_ROOT = ROOT / "runtime/audiore-live"
GAME_DIRECTORY_WINDOWS = (
    r"C:\Users\User\Documents\GitHub\SB Modding\Solomon Dark"
    r"\SolomonDarkAbandonware"
)


@dataclass(frozen=True)
class DispatchRequest:
    registry_index: int
    operation: str
    call_site: str
    gain: float = 1.0
    pitch: float = 1.0
    pool: tuple[int, ...] = ()
    selection: str = "fixed"
    rng: str = "none"
    parameter_logic: str = "fixed gain=1, pitch=1"


@dataclass(frozen=True)
class EventSpec:
    event_class: str
    trigger: str
    requests: tuple[DispatchRequest, ...] = ()
    silent_reason: str = ""


def request(
    registry_index: int,
    operation: str,
    call_site: str,
    *,
    gain: float = 1.0,
    pitch: float = 1.0,
    pool: tuple[int, ...] = (),
    selection: str = "fixed",
    rng: str = "none",
    parameter_logic: str = "fixed gain=1, pitch=1",
) -> DispatchRequest:
    return DispatchRequest(
        registry_index,
        operation,
        call_site,
        gain,
        pitch,
        pool,
        selection,
        rng,
        parameter_logic,
    )


GAMEPLAY_RNG = (
    "active gameplay stream at DAT_00818B08; G1 App-tick seed and draw order"
)


EVENT_SPECS: tuple[EventSpec, ...] = (
    EventSpec(
        "cast.ether.release",
        "primary Magic Missile emission",
        (request(57, "play_pitch_gain", "0x0053D9CA", parameter_logic="cast-computed pitch and point gain"),),
    ),
    EventSpec(
        "cast.fire.release",
        "primary Fire Missile emission",
        (request(97, "play_pitch_gain", "0x0053E4E0", parameter_logic="cast-computed pitch and point gain"),),
    ),
    EventSpec(
        "cast.air.channel_start",
        "primary selector transition 0 -> Air (0x18)",
        (
            request(54, "play_gain", "0x005497EF", parameter_logic="world point gain"),
            request(162, "loop_start", "0x00549800"),
        ),
    ),
    EventSpec(
        "cast.air.channel_hold",
        "Air remains selected",
        silent_reason="the already-started lightning loop persists; hold ticks issue no new dispatch",
    ),
    EventSpec(
        "cast.air.channel_stop",
        "primary selector transition Air (0x18) -> other/idle",
        (request(162, "loop_stop", "0x00549714", gain=0.0),),
    ),
    EventSpec(
        "cast.water.channel_start",
        "primary selector transition 0 -> Water (0x20)",
        (
            request(44, "play_gain", "0x00549BA1", parameter_logic="world point gain"),
            request(161, "loop_start", "0x00549BB2"),
        ),
    ),
    EventSpec(
        "cast.water.channel_hold",
        "Water remains selected",
        silent_reason="the already-started ice loop persists; hold ticks issue no new dispatch",
    ),
    EventSpec(
        "cast.water.channel_stop",
        "primary selector transition Water (0x20) -> other/idle",
        (request(161, "loop_stop", "0x00549725", gain=0.0),),
    ),
    EventSpec(
        "cast.earth.charge_start",
        "primary selector transition 0 -> Earth (0x28)",
        (request(159, "loop_start", "0x00549F57"),),
    ),
    EventSpec(
        "cast.earth.boulder_created",
        "Earth dispatcher allocates, registers, and stores the native Boulder actor",
        (request(87, "play_gain", "0x00544FA8", parameter_logic="world point gain"),),
    ),
    EventSpec(
        "cast.earth.charge_hold",
        "Earth boulder remains held while charge grows",
        silent_reason="gatherrocks remains live from its transition edge; charge ticks issue no new dispatch",
    ),
    EventSpec(
        "cast.earth.release",
        "bounded Earth release and native selector transition 0x28 -> 0",
        (request(159, "loop_stop", "0x00549758", gain=0.0),),
    ),
    EventSpec(
        "projectile.ether.flight",
        "Magic Missile birth",
        (request(57, "play_pitch_gain", "0x0053D9CA", parameter_logic="launch request shared with cast release"),),
    ),
    EventSpec(
        "projectile.ether.impact",
        "Magic Missile contact handler",
        (request(58, "play_pitch_gain", "0x005F1FF2", parameter_logic="contact point gain plus gameplay-RNG pitch"),),
    ),
    EventSpec(
        "projectile.fire.flight",
        "Fire Missile birth",
        (request(97, "play_pitch_gain", "0x0053E4E0", parameter_logic="launch request shared with cast release"),),
    ),
    EventSpec(
        "projectile.fire.impact",
        "Fire Missile contact handler",
        (request(30, "play_pitch_gain", "0x005E4D80", parameter_logic="contact point gain plus gameplay-RNG pitch"),),
    ),
    EventSpec(
        "projectile.air.flight",
        "Ball Lightning cast emission",
        (
            request(
                224,
                "play_pitch_gain",
                "0x0053F155",
                pool=(224, 225),
                selection="uniform Integer(2)",
                rng=GAMEPLAY_RNG,
                parameter_logic="cast-computed point gain and pitch",
            ),
        ),
    ),
    EventSpec(
        "projectile.air.impact",
        "electric contact/shock spawn",
        (
            request(
                203,
                "play_pitch_gain",
                "0x005F365A",
                pool=(203, 204, 205),
                selection="uniform Integer(3)",
                rng=GAMEPLAY_RNG,
                parameter_logic="contact point gain plus gameplay-RNG pitch",
            ),
        ),
    ),
    EventSpec(
        "projectile.water.flight",
        "Frost Missile cast emission",
        (request(38, "play_pitch_gain", "0x0053F741", parameter_logic="cast-computed point gain and pitch"),),
    ),
    EventSpec(
        "projectile.water.impact",
        "Frost Missile contact handler",
        (request(36, "play_pitch_gain", "0x005F26F2", parameter_logic="contact point gain plus gameplay-RNG pitch"),),
    ),
    EventSpec(
        "projectile.earth.flight",
        "Boulder flight requests global rollingstone ambience",
        (request(168, "loop_start", "0x0040B161", parameter_logic="AmbientSound zero-to-positive edge; producer 0x00620B60 supplies gain"),),
    ),
    EventSpec(
        "projectile.earth.flight_end",
        "Boulder stops renewing rollingstone ambience",
        (request(168, "loop_stop", "0x0040B189", gain=0.0),),
    ),
    EventSpec(
        "projectile.earth.impact",
        "Boulder terminal terrain/contact branch",
        (request(77, "play_gain", "0x0062141B", parameter_logic="world point gain"),),
    ),
    EventSpec(
        "melee.player.swing",
        "player staff swing action",
        (request(86, "play_pitch_gain", "0x0055024A", parameter_logic="gameplay-RNG pitch and local gain"),),
    ),
    EventSpec(
        "melee.player.hit_world",
        "staff contact with wood/world",
        (request(85, "play_gain", "0x0053BE4F", parameter_logic="hit-point attenuation"),),
    ),
    EventSpec(
        "melee.enemy.hit",
        "sword-family damage contact",
        (
            request(
                220,
                "play_pitch_gain",
                "0x00477832",
                pool=(220, 221),
                selection="uniform Integer(2)",
                rng=GAMEPLAY_RNG,
                parameter_logic="hit-point attenuation plus gameplay-RNG pitch",
            ),
        ),
    ),
    EventSpec(
        "movement.footstep.wood",
        "player movement cadence on the wood-material branch",
        (request(104, "play_pitch_gain", "0x0054AF92", parameter_logic="world point gain times footstep scalar plus gameplay-RNG pitch"),),
    ),
    EventSpec(
        "movement.footstep.stone",
        "player movement cadence on the default ground branch",
        (request(214, "play_gain", "0x0054AFEC", pool=(214, 215), selection="uniform Integer(2)", rng=GAMEPLAY_RNG, parameter_logic="world point gain times footstep scalar"),),
    ),
    EventSpec(
        "movement.footstep.splash",
        "movement cadence on a water/splash material branch",
        (request(216, "play_gain", "0x0047634D", pool=(216, 217, 218, 219), selection="uniform Integer(4)", rng=GAMEPLAY_RNG, parameter_logic="world point gain"),),
    ),
    EventSpec(
        "damage.player.taken",
        "nonlethal positive player HP loss after cooldown",
        (
            request(
                228,
                "play_pitch_gain",
                "0x0053074A",
                pool=(228, 229, 230),
                selection="uniform Integer(3); next delay is inclusive Integer(20,60)",
                rng=GAMEPLAY_RNG,
                parameter_logic="distance gain times 0.25..1 low-life envelope; gameplay-RNG pitch",
            ),
        ),
    ),
    EventSpec("death.player", "native player death action", (request(118, "stream_play", "0x004757DD"),)),
    EventSpec("death.skeleton", "skeleton terminal branch", (request(79, "play_gain", "0x0048D368", parameter_logic="world point gain"),)),
    EventSpec("death.zombie", "zombie terminal branch", (request(105, "play_gain", "0x00494AEE", parameter_logic="world point gain; poison branches also request 108 and groan branch 110"),)),
    EventSpec("death.banshee", "banshee/wraith terminal branch", (request(8, "play_gain", "0x0049612B", parameter_logic="world point gain"),)),
    EventSpec("death.unholy", "Unholy/DemonSkull terminal branch", (request(146, "stream_play", "0x0049645C", parameter_logic="stream gain from world point"),)),
    EventSpec("death.demon", "demon terminal branch", (request(20, "play_gain", "0x0048760F", parameter_logic="world point gain"),)),
    EventSpec("death.imp", "imp terminal fire branch", (request(31, "play_pitch_gain", "0x00482A41", parameter_logic="world point gain plus gameplay-RNG pitch"),)),
    EventSpec("death.spider", "spider terminal branch", (request(82, "play_pitch_gain", "0x00482E13", parameter_logic="world point gain plus gameplay-RNG pitch"),)),
    EventSpec("death.golem", "golem terminal branch", (request(125, "stream_play", "0x0049A74B", parameter_logic="stream gain from world point; same branch also requests stonebreak and rockhit"),)),
    EventSpec("death.faculty", "Faculty terminal branch", (request(121, "stream_play", "0x0049D19B", parameter_logic="stream gain from world point"),)),
    EventSpec("death.heartmonger", "Heartmonger terminal branch", (request(111, "stream_play", "0x004A0B6F", parameter_logic="stream gain from world point; chain pool precedes terminal stream"),)),
    EventSpec("death.portal", "portal terminal branch", (request(75, "play_gain", "0x004A2034", parameter_logic="world point gain"),)),
    EventSpec("death.coffin", "coffin terminal branch", (request(15, "play_gain", "0x0049B549", parameter_logic="world point gain"),)),
    EventSpec(
        "death.crow",
        "crow terminal/retirement branch",
        (request(183, "play_pitch_gain", "0x00489226", pool=(183, 184), selection="uniform Integer(2)", rng=GAMEPLAY_RNG, parameter_logic="world point gain plus gameplay-RNG pitch"),),
    ),
    EventSpec(
        "death.maggot",
        "maggot terminal branch",
        (request(199, "play_pitch_gain", "0x0049C9C6", pool=(199, 200), selection="uniform Integer(2)", rng=GAMEPLAY_RNG, parameter_logic="world point gain plus gameplay-RNG pitch"),),
    ),
    EventSpec("pickup.coin", "coin pickup accepted", (request(69, "play_gain", "0x005E6A1B"),)),
    EventSpec("pickup.bag", "loot bag pickup accepted", (request(68, "play_gain", "0x005E6D20"),)),
    EventSpec("pickup.orb", "orb pickup accepted", (request(2, "play_gain", "0x005E659F"),)),
    EventSpec("pickup.potion", "potion loot enters the generic bag pickup path", (request(68, "play_gain", "0x005E6D20"),)),
    EventSpec("pickup.magic_book", "magic-book acquisition stream", (request(129, "stream_play", "0x0056D471"),)),
    EventSpec("potion.use", "potion effect accepted and consumed", (request(24, "play_gain", "0x0056D246"),)),
    EventSpec("potion.invalid", "potion/action rejected", (request(6, "play_gain", "0x0056D3D2"),)),
    EventSpec(
        "level.up",
        "one local level-award invocation crosses at least one threshold",
        (
            request(
                52,
                "play_gain",
                "0x00528A3E",
                parameter_logic="fixed gain=1; once after the complete local threshold loop",
            ),
        ),
    ),
    EventSpec(
        "skill.turn_undead.cast",
        "accepted Turn Undead cast enters the skill handler before its target query",
        (
            request(
                52,
                "play_pitch_gain",
                "0x00647F6B",
                pitch=2.0,
                parameter_logic="fixed pitch=2; point-derived gain",
            ),
            request(
                52,
                "play_pitch_gain",
                "0x00647FBE",
                pitch=3.0,
                parameter_logic="fixed pitch=3; separately recomputed point-derived gain",
            ),
        ),
    ),
    EventSpec("skill.unlock", "skill purchase/unlock accepted", (request(102, "play_gain", "0x00670CD3"),)),
    EventSpec(
        "wave.start",
        "first arena wave enters combat music",
        silent_reason="Music_Transition requests song combat/track combat at 0x00465D22; covered by the natural music witness because registry probes do not fabricate native Strings",
    ),
    EventSpec(
        "wave.end",
        "terminal arena completion",
        silent_reason="Music_PlayCrossfade requests the empty song at 0x00467AA0; there is no wave-complete one-shot",
    ),
    EventSpec(
        "dig.shovel",
        "accepted dig strike",
        (request(209, "play_pitch_gain", "0x0048207A", pool=(209, 210), selection="uniform Integer(2)", rng=GAMEPLAY_RNG, parameter_logic="world point gain plus gameplay-RNG pitch"),),
    ),
    EventSpec(
        "dig.throw_dirt",
        "dig debris emission",
        (request(222, "play_pitch_gain", "0x004820FE", pool=(222, 223), selection="uniform Integer(2)", rng=GAMEPLAY_RNG, parameter_logic="world point gain plus gameplay-RNG pitch"),),
    ),
    EventSpec("shop.purchase", "purchase debit and transfer succeed", (request(25, "play_gain", "0x0056C10E"),)),
    EventSpec("shop.purchase_rejected", "purchase precondition fails", (request(6, "play_gain", "0x0056C1A6"),)),
    EventSpec(
        "shop.storage_return_double",
        "selected storage item is second-activated into the backpack",
        (
            request(0, "play_gain", "0x0055F054"),
            request(4, "play_gain", "0x0056CE80"),
        ),
    ),
    EventSpec(
        "shop.storage_drag_start",
        "storage item crosses the drag threshold",
        (request(0, "play_gain", "0x0056CF1A"),),
    ),
    EventSpec(
        "shop.storage_drag_drop",
        "storage drag release is accepted",
        (request(0, "play_pitch_gain", "0x0056F55A", pitch=0.75),),
    ),
    EventSpec(
        "shop.dowsing_roll",
        "DOWSE fee is accepted and result generation begins",
        (
            request(1, "play_gain", "0x00408550", gain=1.0, parameter_logic="SoundEcho tick 0 gain 1"),
            request(1, "play_gain", "0x00408550", gain=0.25, parameter_logic="SoundEcho tick 25 gain 0.25"),
            request(1, "play_gain", "0x00408550", gain=0.0625, parameter_logic="SoundEcho tick 50 gain 0.0625"),
            request(1, "play_gain", "0x00408550", gain=0.015625, parameter_logic="SoundEcho tick 75 gain 0.015625"),
            request(23, "play_pitch_gain", "0x0055FE17", pitch=0.8, parameter_logic="pitch 0.8 + Float(0.1,false), after the SoundEcho start and before offer-count Integer(2)"),
        ),
    ),
    EventSpec(
        "shop.dowsing_purchase",
        "Dowsing offer purchase succeeds",
        (
            request(25, "play_gain", "0x0056C10E"),
            request(23, "play_pitch_gain", "0x0056D18B", pitch=1.0, parameter_logic="next-fee Integer(10), then pitch 1.0 + Float(0.1,false)"),
        ),
    ),
    EventSpec(
        "ui.focus",
        "pointer hover/focus changes without activation",
        silent_reason="stock pointer focus has no audio dispatch",
    ),
    EventSpec("ui.confirm", "Game Over continue/button activation", (request(0, "play_gain", "0x005CF7BA"),)),
    EventSpec("ui.shop_close", "common Shop DONE closes the service", (request(64, "play_gain", "0x0055EFA8"),)),
    EventSpec("ui.inventory_close", "standalone InventoryScreen closes", (request(64, "play_gain", "0x00555853"),)),
    EventSpec(
        "music.menu_transition",
        "native menu/scene music selection",
        silent_reason="the timeline substitutes a natural Music dispatch captured during this launch",
    ),
)


EXPECTED_EVENT_CLASSES = tuple(spec.event_class for spec in EVENT_SPECS)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise native_sim.CaptureFailure(message)


def load_catalog() -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    document = json.loads(CATALOG.read_text(encoding="utf-8"))
    rows = document.get("compiled_registry")
    require(isinstance(rows, list) and len(rows) == 233, "audio catalog does not contain the 233-slot registry")
    by_index: dict[int, dict[str, Any]] = {}
    for row in rows:
        require(isinstance(row, dict), "audio catalog registry row is not an object")
        index = row.get("registry_index")
        require(isinstance(index, int), "audio catalog registry row has no integer index")
        require(index not in by_index, f"audio catalog registry index {index} is ambiguous")
        by_index[index] = row
    require(set(by_index) == set(range(233)), "audio catalog registry is not exactly contiguous 0..232")
    return document, by_index


def parse_bool(value: str) -> bool:
    require(value in {"true", "false"}, f"dispatch event contains invalid boolean {value!r}")
    return value == "true"


def read_dispatch_events(session: native_sim.OwnedSoloSession) -> tuple[bool, list[dict[str, Any]]]:
    output = session.lua(
        r"""
local events, enabled = sd.debug.get_native_audio_dispatch_events()
print('CAPTURE\t' .. tostring(enabled))
for _, event in ipairs(events) do
  print(table.concat({
    'EVENT',
    string.format('%.0f', event.event_sequence),
    string.format('%.0f', event.native_tick),
    string.format('%.0f', event.monotonic_ms),
    string.format('0x%08X', event.object_address),
    string.format('0x%08X', event.caller_return_address),
    tostring(event.registry_index),
    tostring(event.native_reference_count),
    string.format('%.9g', event.gain),
    string.format('%.9g', event.pitch),
    string.format('%.9g', event.transition_ticks),
    tostring(event.engine_enabled),
    tostring(event.caller_in_game_image),
    event.native_class,
    event.operation,
    'name:' .. event.requested_name,
    'track:' .. event.requested_track
  }, '\t'))
end
"""
    )
    enabled: bool | None = None
    events: list[dict[str, Any]] = []
    for line in output.splitlines():
        if line.startswith("CAPTURE\t"):
            require(enabled is None, "dispatch snapshot emitted duplicate capture state")
            enabled = parse_bool(line.split("\t", 1)[1])
            continue
        if not line.startswith("EVENT\t"):
            continue
        fields = line.split("\t")
        require(len(fields) == 17, f"dispatch event has {len(fields)} fields instead of 17: {line!r}")
        require(
            fields[15].startswith("name:") and fields[16].startswith("track:"),
            "dispatch event lost its explicit empty-string field framing",
        )
        events.append(
            {
                "event_sequence": int(fields[1]),
                "native_tick": int(fields[2]),
                "monotonic_ms": int(fields[3]),
                "object_address": fields[4],
                "caller_return_address": fields[5],
                "registry_index": int(fields[6]),
                "native_reference_count": int(fields[7]),
                "gain": float(fields[8]),
                "pitch": float(fields[9]),
                "transition_ticks": float(fields[10]),
                "engine_enabled": parse_bool(fields[11]),
                "caller_in_game_image": parse_bool(fields[12]),
                "native_class": fields[13],
                "operation": fields[14],
                "requested_name": fields[15][len("name:"):],
                "requested_track": fields[16][len("track:"):],
            }
        )
    require(enabled is not None, "dispatch snapshot returned no capture state; tap is broken, not busy")
    return enabled, events


def clear_dispatch_events(session: native_sim.OwnedSoloSession) -> int:
    value = session.lua("return tostring(sd.debug.clear_native_audio_dispatch_events())").strip()
    require(re.fullmatch(r"\d+", value) is not None, f"dispatch clear returned malformed count {value!r}")
    return int(value)


def dispatch_probe(
    session: native_sim.OwnedSoloSession,
    probe: DispatchRequest,
) -> dict[str, Any]:
    result = session.values(
        f"""
local ok, err = sd.debug.dispatch_native_audio_census_probe(
  {probe.registry_index}, {probe.operation!r}, {probe.gain!r}, {probe.pitch!r})
print('ok=' .. tostring(ok))
print('error=' .. tostring(err or ''))
"""
    )
    require(result.get("ok") == "true", f"dispatch probe is broken, not busy: {result.get('error', '')}")
    enabled, events = read_dispatch_events(session)
    require(enabled, "dispatch capture disabled after a successful probe")
    matching = [
        event
        for event in events
        if event["registry_index"] == probe.registry_index
        and event["operation"] == probe.operation
    ]
    require(
        len(matching) == 1,
        f"dispatch probe for registry {probe.registry_index}/{probe.operation} is ambiguous: {len(matching)} matches",
    )
    event = matching[0]
    require(not event["engine_enabled"], "dispatch probe crossed an enabled audio engine")
    require(not event["caller_in_game_image"], "census-probe caller was misreported as a retail trigger site")
    require(event["caller_return_address"] == "0x00000000", "out-of-image census-probe caller was not normalized to zero")
    return event


def dispatch_empty_music_probe(session: native_sim.OwnedSoloSession) -> dict[str, Any]:
    result = session.values(
        """
local ok, err = sd.debug.dispatch_native_audio_census_probe(
  -1, 'music_crossfade_empty', -1, 1)
print('ok=' .. tostring(ok))
print('error=' .. tostring(err or ''))
"""
    )
    require(result.get("ok") == "true", f"empty-song Music probe is broken, not busy: {result.get('error', '')}")
    enabled, events = read_dispatch_events(session)
    require(enabled, "dispatch capture disabled after empty-song Music probe")
    matching = [
        event
        for event in events
        if event["native_class"] == "Music"
        and event["operation"] == "music_play_crossfade"
        and event["requested_name"] == ""
    ]
    require(len(matching) == 1, f"empty-song Music probe is ambiguous: {len(matching)} matches")
    event = matching[0]
    require(not event["engine_enabled"], "empty-song Music probe crossed an enabled audio engine")
    require(not event["caller_in_game_image"], "empty-song Music probe caller was misreported as a retail trigger site")
    require(event["caller_return_address"] == "0x00000000", "empty-song Music probe caller was not normalized to zero")
    return event


def catalog_identity(row: dict[str, Any]) -> dict[str, Any]:
    file_info = row.get("file")
    require(isinstance(file_info, dict), "catalog row has no file metadata")
    return {
        "registry_index": row["registry_index"],
        "native_class": row["native_class"],
        "asset_path": row["path_without_extension"],
        "file_path": file_info["path"],
        "file_sha256": file_info["sha256"],
    }


def read_wave_format(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    require(len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE", f"loop asset is not a RIFF/WAVE file: {path}")
    format_values: tuple[int, int, int] | None = None
    sample_frames: int | None = None
    sample_loops: list[dict[str, int]] = []
    cursor = 12
    while cursor + 8 <= len(data):
        chunk_id = data[cursor:cursor + 4]
        chunk_size = struct.unpack_from("<I", data, cursor + 4)[0]
        payload = cursor + 8
        end = payload + chunk_size
        require(end <= len(data), f"loop asset has a truncated {chunk_id!r} chunk: {path}")
        if chunk_id == b"fmt ":
            require(chunk_size >= 16, f"loop asset has a short fmt chunk: {path}")
            format_tag, channels, sample_rate, _byte_rate, block_align, bits = struct.unpack_from("<HHIIHH", data, payload)
            require(format_tag == 1 and block_align > 0, f"loop asset is not uncompressed PCM: {path}")
            format_values = (sample_rate, channels, bits)
        elif chunk_id == b"data":
            require(format_values is not None, f"loop asset data precedes fmt: {path}")
            block_align = format_values[1] * format_values[2] // 8
            require(block_align > 0 and chunk_size % block_align == 0, f"loop asset data is not frame-aligned: {path}")
            sample_frames = chunk_size // block_align
        elif chunk_id == b"smpl":
            require(chunk_size >= 36, f"loop asset has a short smpl chunk: {path}")
            loop_count = struct.unpack_from("<I", data, payload + 28)[0]
            require(36 + loop_count * 24 <= chunk_size, f"loop asset has truncated smpl loops: {path}")
            for loop_index in range(loop_count):
                loop_offset = payload + 36 + loop_index * 24
                _identifier, _loop_type, start, end_inclusive, _fraction, _play_count = struct.unpack_from("<IIIIII", data, loop_offset)
                sample_loops.append({"start_frame": start, "end_frame_inclusive": end_inclusive})
        cursor = end + (chunk_size & 1)
    require(format_values is not None and sample_frames is not None, f"loop asset has no complete PCM format/data pair: {path}")
    return {
        "sample_rate_hz": format_values[0],
        "channels": format_values[1],
        "bits_per_sample": format_values[2],
        "sample_frames": sample_frames,
        "wav_smpl_loop_points": sample_loops,
    }


def loop_table(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    rows = catalog["compiled_registry"]
    loops = []
    for row in rows:
        if row.get("native_class") != "SoundLoop":
            continue
        file_info = row.get("file")
        require(isinstance(file_info, dict) and isinstance(file_info.get("path"), str), f"loop registry {row['registry_index']} has no installed file path")
        wave = read_wave_format(native_sim.GAME_DIRECTORY / file_info["path"])
        loops.append(
            {
                **catalog_identity(row),
                **wave,
                "stock_effective_loop": {
                    "start_frame": 0,
                    "end_frame_exclusive": wave["sample_frames"],
                    "reason": "BASS_SAMPLE_LOOP loops the whole decoded sample; stock never applies WAV smpl positions",
                },
            }
        )
    require(len(loops) == 22, f"loop table reached {len(loops)} assets instead of 22")
    require(any(row["registry_index"] == 164 for row in loops), "loop table did not reach the maggots smpl witness")
    return loops


def call_site_from_return_address(return_address: str) -> str:
    require(re.fullmatch(r"0x[0-9A-F]{8}", return_address) is not None, f"natural caller address is malformed: {return_address!r}")
    value = int(return_address, 16)
    require(value >= 5, f"natural caller address cannot contain a five-byte CALL: {return_address}")
    return f"0x{value - 5:08X}"


@contextmanager
def silent_capture_environment() -> Iterator[None]:
    names = ("SDMOD_DISABLE_AUDIO", "SDMOD_ENABLE_AUDIO", "SDMOD_CAPTURE_AUDIO_EVENTS", "WSLENV")
    previous = {name: os.environ.get(name) for name in names}
    os.environ["SDMOD_DISABLE_AUDIO"] = "1"
    os.environ["SDMOD_ENABLE_AUDIO"] = "0"
    os.environ["SDMOD_CAPTURE_AUDIO_EVENTS"] = "1"
    entries = [entry for entry in os.environ.get("WSLENV", "").split(":") if entry]
    bases = {entry.split("/", 1)[0] for entry in entries}
    for name in ("SDMOD_DISABLE_AUDIO", "SDMOD_ENABLE_AUDIO", "SDMOD_CAPTURE_AUDIO_EVENTS"):
        if name not in bases:
            entries.append(name)
    os.environ["WSLENV"] = ":".join(entries)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main() -> int:
    source = native_sim.source_revision()
    require(not source["worktree_dirty"], "audio golden recorder requires a clean committed checkout")
    catalog, by_index = load_catalog()
    require(len(EXPECTED_EVENT_CLASSES) == len(set(EXPECTED_EVENT_CLASSES)), "event-class census contains a duplicate label")

    native_sim.RUNTIME_ROOT = RUNTIME_ROOT
    native_sim.GAME_DIRECTORY = native_sim.local_path_from_windows(GAME_DIRECTORY_WINDOWS)
    native_sim.GAME_BINARY = native_sim.GAME_DIRECTORY / "SolomonDark.exe"
    session = native_sim.OwnedSoloSession(
        instance=INSTANCE,
        ports=PORTS,
        mod_id="sample.lua.rng_lab",
        participant_id="audiore-g5-solo",
        test_blank_boneyard=False,
        headless=True,
    )

    launch_result: dict[str, Any] | None = None
    cleanup_receipts: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    natural_witnesses: list[dict[str, Any]] = []
    marker_tick = -1
    with silent_capture_environment():
        try:
            launch_result = session.launch()
            session.wait_for_pipe()
            enabled, initial_events = read_dispatch_events(session)
            require(enabled, "dispatch tap did not initialize; launch is broken, not busy")
            require(initial_events, "startup produced zero dispatch events; tap is broken, not busy")
            require(all(not event["engine_enabled"] for event in initial_events), "startup dispatch crossed an enabled audio engine")
            natural_witnesses.extend(event for event in initial_events if event["caller_in_game_image"])
            clear_dispatch_events(session)

            native_sim.start_quiet_testrun(session)
            enabled, scene_events = read_dispatch_events(session)
            require(enabled, "dispatch tap disabled during scene transition")
            require(all(not event["engine_enabled"] for event in scene_events), "scene dispatch crossed an enabled audio engine")
            natural_witnesses.extend(event for event in scene_events if event["caller_in_game_image"])
            music_witnesses = [event for event in natural_witnesses if event["native_class"] == "Music"]
            require(music_witnesses, "no natural Music dispatch arrived; scene transition is broken, not busy")
            menu_music = [
                event
                for event in music_witnesses
                if event["operation"] == "music_play_crossfade"
                and event["requested_name"] == "prelude"
                and event["caller_return_address"] == "0x0058A038"
            ]
            require(len(menu_music) == 1, f"natural menu-music witness is ambiguous: {len(menu_music)} matches")
            wave_start_music = [
                event
                for event in music_witnesses
                if event["operation"] == "music_transition"
                and event["requested_name"] == "combat"
                and event["requested_track"] == "combat"
            ]
            require(len(wave_start_music) == 1, f"natural wave-start music witness is ambiguous: {len(wave_start_music)} matches")
            natural_witnesses = [menu_music[0], wave_start_music[0]]

            clear_dispatch_events(session)
            marker = dispatch_probe(session, request(0, "play_gain", "harness-marker"))
            marker_tick = marker["native_tick"]
            clear_dispatch_events(session)

            for spec in EVENT_SPECS:
                if spec.event_class == "music.menu_transition":
                    event = menu_music[0]
                    timeline.append(
                        {
                            "tick": event["native_tick"],
                            "event_class": spec.event_class,
                            "trigger": spec.trigger,
                            "native_trigger_site": call_site_from_return_address(event["caller_return_address"]),
                            "observed_caller_return_address": event["caller_return_address"],
                            "dispatch_operation": event["operation"],
                            "requested_asset_id": "music:" + event["requested_name"],
                            "requested_track": event["requested_track"],
                            "parameters": {"transition_ticks": event["transition_ticks"]},
                            "capture_kind": "natural_stock_dispatch",
                            "engine_enabled": event["engine_enabled"],
                        }
                    )
                    continue
                if spec.event_class == "wave.start":
                    event = wave_start_music[0]
                    timeline.append(
                        {
                            "tick": event["native_tick"],
                            "event_class": spec.event_class,
                            "trigger": spec.trigger,
                            "native_trigger_site": "0x00465D22",
                            "observed_caller_return_address": event["caller_return_address"],
                            "dispatch_operation": event["operation"],
                            "requested_asset_id": "music:combat",
                            "requested_track": event["requested_track"],
                            "parameters": {"transition_ticks": event["transition_ticks"]},
                            "capture_kind": "natural_stock_dispatch",
                            "engine_enabled": event["engine_enabled"],
                        }
                    )
                    continue
                if spec.event_class == "wave.end":
                    clear_dispatch_events(session)
                    event = dispatch_empty_music_probe(session)
                    timeline.append(
                        {
                            "tick": event["native_tick"],
                            "event_class": spec.event_class,
                            "trigger": spec.trigger,
                            "native_trigger_site": "0x00467AA0",
                            "observed_probe_caller": event["caller_return_address"],
                            "dispatch_operation": event["operation"],
                            "requested_asset_id": "music:<empty>",
                            "requested_track": "",
                            "parameters": {"transition_ticks": event["transition_ticks"]},
                            "capture_kind": "live_stock_wrapper_probe",
                            "engine_enabled": event["engine_enabled"],
                        }
                    )
                    continue
                if not spec.requests:
                    timeline.append(
                        {
                            "tick": marker_tick,
                            "event_class": spec.event_class,
                            "trigger": spec.trigger,
                            "native_trigger_site": None,
                            "dispatch_operation": None,
                            "requested_asset_id": None,
                            "requested_track": "",
                            "parameters": {},
                            "capture_kind": "live_silent_phase_checkpoint",
                            "silent_reason": spec.silent_reason,
                            "engine_enabled": False,
                        }
                    )
                    continue

                for ordinal, probe in enumerate(spec.requests, 1):
                    clear_dispatch_events(session)
                    event = dispatch_probe(session, probe)
                    asset = catalog_identity(by_index[probe.registry_index])
                    pool = probe.pool or (probe.registry_index,)
                    require(all(index in by_index for index in pool), f"{spec.event_class} selection pool names an absent registry slot")
                    timeline.append(
                        {
                            "tick": event["native_tick"],
                            "event_class": spec.event_class,
                            "request_ordinal": ordinal,
                            "trigger": spec.trigger,
                            "native_trigger_site": probe.call_site,
                            "observed_probe_caller": event["caller_return_address"],
                            "dispatch_operation": event["operation"],
                            "requested_asset_id": f"registry:{probe.registry_index}",
                            "requested_asset": asset,
                            "selection_pool": [catalog_identity(by_index[index]) for index in pool],
                            "selection_logic": probe.selection,
                            "rng_stream": probe.rng,
                            "parameters": {
                                "observed_gain": event["gain"],
                                "observed_pitch": event["pitch"],
                                "native_reference_count_after_dispatch": event["native_reference_count"],
                                "native_parameter_logic": probe.parameter_logic,
                            },
                            "capture_kind": "live_stock_wrapper_probe",
                            "engine_enabled": event["engine_enabled"],
                        }
                    )

            require(
                {row["event_class"] for row in timeline} == set(EXPECTED_EVENT_CLASSES),
                "live timeline does not cover the exact event-class census",
            )
            for sequence, row in enumerate(timeline, 1):
                row["timeline_sequence"] = sequence
            require(all(not row["engine_enabled"] for row in timeline), "timeline contains a dispatch with audio enabled")
        finally:
            cleanup_receipts = session.close()

    require(launch_result is not None, "solo launch did not publish provenance")
    require(cleanup_receipts, "owned game PID produced no cleanup receipt")
    require(all(receipt.get("stopped") or receipt.get("alreadyExited") for receipt in cleanup_receipts), "owned game PID did not stop cleanly")

    document = {
        "schema": "solomon-dark-native-audio-event-goldens-v1",
        "header": {
            "instance": INSTANCE,
            "ports": list(PORTS),
            "audio_disabled": True,
            "fixture_is_machine_recorded": True,
            "source_commit_sha": source["commit_sha"],
            "source_tree_sha": source["tree_sha"],
            "worktree_dirty_at_capture_start": source["worktree_dirty"],
            "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "process_id": launch_result["processId"],
            "executable_path": launch_result["executablePath"],
            "loader_sha256": native_sim.sha256_file(native_sim.STAGED_LOADER),
            "build_loader_sha256": native_sim.sha256_file(native_sim.LOADER),
            "game_binary_sha256": native_sim.sha256_file(native_sim.GAME_BINARY),
            "catalog_path": CATALOG.relative_to(ROOT).as_posix(),
            "catalog_sha256": native_sim.sha256_file(CATALOG),
            "recorder_path": RECORDER.relative_to(ROOT).as_posix(),
            "recorder_sha256": native_sim.sha256_file(RECORDER),
            "capture_method": "live stock dispatch-wrapper hooks plus explicit silent-phase checkpoints",
            "cleanup": cleanup_receipts,
        },
        "dispatch_boundary": {
            "environment": {"SDMOD_DISABLE_AUDIO": "1", "SDMOD_ENABLE_AUDIO": "0", "SDMOD_CAPTURE_AUDIO_EVENTS": "1"},
            "disable_point": "launch hook replaces BASS_Init and keeps DAT_00B40239 equal to zero",
            "tap_point": "entry hooks on Sound, SoundStream, SoundLoop, and Music request wrappers, before their DAT_00B40239-gated BASS calls",
            "relative_position": "tap is upstream of the disable point's mixer/device output boundary",
            "proof": "every natural and probed dispatch reports engine_enabled=false; startup and scene transitions still produced in-image dispatch witnesses",
            "zero_event_interpretation": "capture enabled and an owned runnable PID are tested separately; a missing marker or natural music event is reported as broken, not busy",
        },
        "event_classes": list(EXPECTED_EVENT_CLASSES),
        "timeline": timeline,
        "natural_dispatch_witnesses": natural_witnesses,
        "looping_assets": loop_table(catalog),
        "music_catalog": catalog["music"],
        "not_yet_reversed": [
            {
                "claim": "sub-frame BASS resampler interpolation and driver-specific output latency",
                "reason": "these are BASS/device behavior below the disabled engine boundary, not native trigger behavior",
            }
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"recorded {len(timeline)} timeline rows across {len(EXPECTED_EVENT_CLASSES)} event classes")
    print(f"natural dispatch witnesses: {len(natural_witnesses)}")
    print(f"output: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
