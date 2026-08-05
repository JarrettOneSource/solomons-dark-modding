#!/usr/bin/env python3
"""Record the G13 native session-flow timeline and transition graph live."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from multiplayer_defense_behavior_harness import invoke_native_magic_hit_trial
from verify_game_over_session_semantics import (
    ACCEPTANCE_MOD_ID,
    _disable_bots,
    _owned_solo_processes,
    _path_for_local_python,
    _start_testrun_when_ready,
    advance_stock_boneyard_game_over,
    capture_native_game_over,
    launch_solo,
    stop_owned_processes,
    validate_owned_processes,
)
from verify_local_multiplayer_sync import (
    VerifyFailure,
    lua,
    parse_key_values,
    path_for_powershell,
    wait_for_scene,
)
from verify_player_health_death_sync import set_local_player_vitals


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "tests" / "fixtures" / "webgame" / "session-flow-goldens.json"
DEFAULT_EVIDENCE = Path("/mnt/d/codex-evidence/flowre-20260805/live-session-flow")
LOADER = ROOT / "bin" / "Release" / "Win32" / "SolomonDarkModLoader.dll"
STAGED_LOADER = ROOT / "dist" / "launcher" / "SolomonDarkModLoader.dll"

SNAPSHOT_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local scene = sd.scene and sd.scene.get_state and sd.scene.get_state() or {}
local world_scene = sd.world and sd.world.get_scene and sd.world.get_scene() or {}
local actors = sd.world and sd.world.list_actors and sd.world.list_actors() or {}
local player = sd.player and sd.player.get_state and sd.player.get_state() or {}
local multiplayer = sd.runtime and sd.runtime.get_multiplayer_state and
  sd.runtime.get_multiplayer_state() or {}
local loading = multiplayer.loading_screen or {}
local barrier = multiplayer.run_loading_barrier or {}
local combat = sd.gameplay and sd.gameplay.get_combat_state and
  sd.gameplay.get_combat_state() or {}
local ui = sd.ui and sd.ui.get_snapshot and sd.ui.get_snapshot() or {}
emit("scene", world_scene.name or world_scene.kind or scene.name or scene.kind or "")
emit("scene_kind", scene.kind or "")
emit("region_index", scene.region_index or -1)
emit("transitioning", scene.transitioning or false)
emit("entity_count", #actors)
emit("tick", player.local_player_tick_count or 0)
emit("session_state", multiplayer.session_state or "")
emit("participant_count", multiplayer.participant_count or 0)
emit("input_sealed", loading.active or false)
emit("loading_stage", loading.stage_id or "")
emit("barrier_released", barrier.released or false)
emit("barrier_timed_out", barrier.timed_out or false)
emit("wave_index", combat.wave_index or -1)
emit("wave_counter", combat.wave_counter or -1)
emit("surface", ui.surface_id or "")
"""


class CaptureFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CaptureFailure(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_text(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    require(completed.returncode == 0, f"git {' '.join(arguments)} failed: {completed.stdout}")
    return completed.stdout.strip()


def source_revision(*, allow_dirty: bool) -> dict[str, Any]:
    status = git_text("status", "--porcelain", "--untracked-files=all")
    require(allow_dirty or not status, "capture source tree is dirty; commit the recorder before recording")
    return {
        "sha": git_text("rev-parse", "HEAD"),
        "dirty": bool(status),
        "branch": git_text("branch", "--show-current"),
    }


def _integer(values: Mapping[str, str], key: str) -> int:
    try:
        return int(values.get(key, ""), 0)
    except ValueError as error:
        raise CaptureFailure(f"live snapshot field {key!r} is not an integer: {values.get(key)!r}") from error


def snapshot(pipe_name: str, label: str) -> dict[str, Any]:
    values = parse_key_values(lua(pipe_name, SNAPSHOT_PROBE, timeout=8.0))
    return {
        "label": label,
        "tick": _integer(values, "tick"),
        "scene": values.get("scene", ""),
        "scene_kind": values.get("scene_kind", ""),
        "region_index": _integer(values, "region_index"),
        "transitioning": values.get("transitioning") == "true",
        "entity_count": _integer(values, "entity_count"),
        "session_state": values.get("session_state", ""),
        "participant_count": _integer(values, "participant_count"),
        "input_sealed": values.get("input_sealed") == "true",
        "loading_stage": values.get("loading_stage", ""),
        "barrier_released": values.get("barrier_released") == "true",
        "barrier_timed_out": values.get("barrier_timed_out") == "true",
        "wave_index": _integer(values, "wave_index"),
        "wave_counter": _integer(values, "wave_counter"),
        "surface": values.get("surface", ""),
    }


def wait_snapshot(
    pipe_name: str,
    owned: Mapping[int, str],
    predicate: Callable[[dict[str, Any]], bool],
    description: str,
    *,
    timeout: float = 45.0,
    stable_for: float = 0.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    last: dict[str, Any] = {}
    last_busy = ""
    while time.monotonic() < deadline:
        try:
            last = snapshot(pipe_name, description)
            if predicate(last):
                if stable_since is None:
                    stable_since = time.monotonic()
                if time.monotonic() - stable_since >= stable_for:
                    return last
                last_busy = f"predicate stable for {time.monotonic() - stable_since:.3f}s of {stable_for:.3f}s"
            else:
                stable_since = None
                last_busy = f"predicate not ready: {last}"
        except (VerifyFailure, CaptureFailure, subprocess.TimeoutExpired) as error:
            stable_since = None
            last_busy = str(error)
            # A live exact-path process means the pipe may still be busy. A
            # missing or path-mismatched process is broken and must stop now.
            validate_owned_processes(owned)
        time.sleep(0.1)
    raise CaptureFailure(f"timed out waiting for {description}; busy={last_busy}; last={last}")


def request_region(pipe_name: str, region_index: int) -> str:
    result = lua(
        pipe_name,
        f"return tostring(sd.scene.switch_region({region_index}))",
        timeout=8.0,
    ).strip()
    require(result == "true", f"region {region_index} request was not accepted: {result!r}")
    return result


def read_events(path: Path) -> list[dict[str, Any]]:
    require(path.is_file(), f"native recorder published no event stream: {path}")
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(events, "native recorder event stream is empty")
    require(events[0].get("step") == "capture.ready", "native recorder never proved end-to-end runnability")
    sequences = [int(event["sequence"]) for event in events]
    require(sequences == list(range(1, len(events) + 1)), "native recorder event sequence has a gap or duplicate")
    return events


def find_unique_event(
    events: list[dict[str, Any]],
    *,
    step: str,
    current_region: int | None = None,
    target_region: int | None = None,
    after_sequence: int = 0,
) -> dict[str, Any]:
    candidates = [
        event
        for event in events
        if event.get("step") == step
        and int(event.get("sequence", 0)) > after_sequence
        and (current_region is None or event.get("current_region") == current_region)
        and (target_region is None or event.get("target_region") == target_region)
    ]
    require(
        len(candidates) == 1,
        f"live event lookup for {step} current={current_region} target={target_region} is ambiguous: {len(candidates)} candidates",
    )
    return candidates[0]


def compact_event(event: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "sequence": event["sequence"],
        "tick": event["simulation_tick"],
        "step": event["step"],
        "current_region": event["current_region"],
        "target_region": event["target_region"],
        "pending_region": event["pending_region"],
        "input_sealed": event["input_sealed"],
        "object": event["object"],
        "native_argument": event["native_argument"],
    }
    for key in ("fade_alpha_before", "fade_alpha_after", "fade_rate_before", "fade_rate_after"):
        if key in event:
            result[key] = event[key]
    return result


def switch_lifecycle(
    events: list[dict[str, Any]],
    enter: Mapping[str, Any],
) -> list[dict[str, Any]]:
    start = int(enter["sequence"])
    later_switches = [
        int(event["sequence"])
        for event in events
        if event.get("step") == "switch.enter" and int(event["sequence"]) > start
    ]
    boundary = min(later_switches, default=len(events) + 1)
    window = [event for event in events if start <= int(event["sequence"]) < boundary]
    endpoints = [
        int(event["sequence"])
        for event in window
        if event.get("step") in {"presentation.fade_in.endpoint", "input.unseal"}
    ]
    require(endpoints, f"switch transition {enter['transition_id']} never reached a presentation/input endpoint")
    end = max(endpoints)
    return [compact_event(event) for event in window if int(event["sequence"]) <= end]


def timeline_transition(
    *,
    source: str,
    edge: str,
    trigger: str,
    destination: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    steps: list[dict[str, Any]],
    edge_path: tuple[str, ...] = (),
) -> dict[str, Any]:
    require(steps, f"timeline transition {edge} has no live lifecycle steps")
    require(
        isinstance(before.get("entity_count"), int) and isinstance(after.get("entity_count"), int),
        f"timeline transition {edge} lacks live before/after entity counts",
    )
    sequences = [int(step["sequence"]) for step in steps]
    require(
        sequences == sorted(set(sequences)),
        f"timeline transition {edge} lifecycle sequence is duplicated or out of order",
    )
    step_ticks = [int(step["tick"]) for step in steps]
    require(
        int(before["tick"]) <= min(step_ticks) <= max(step_ticks) <= int(after["tick"]),
        f"timeline transition {edge} lifecycle ticks fall outside its live before/after snapshots",
    )
    transition = {
        "source": source,
        "edge": edge,
        "trigger": trigger,
        "destination": destination,
        "before": dict(before),
        "ordered_lifecycle_steps": steps,
        "after": dict(after),
    }
    if edge_path:
        transition["native_edge_path"] = list(edge_path)
    return transition


def build_fixture(
    *,
    header: dict[str, Any],
    events: list[dict[str, Any]],
    graph: dict[str, Any],
    snapshots: dict[str, dict[str, Any]],
    receipts: dict[str, Any],
) -> dict[str, Any]:
    startup_office = find_unique_event(events, step="switch.enter", current_region=-1, target_region=4)
    startup_hub = find_unique_event(
        events,
        step="switch.enter",
        current_region=4,
        target_region=0,
        after_sequence=int(startup_office["sequence"]),
    )
    to_library = find_unique_event(events, step="switch.enter", current_region=0, target_region=2)
    from_library = find_unique_event(events, step="switch.enter", current_region=2, target_region=0)
    to_arena = find_unique_event(events, step="switch.enter", current_region=0, target_region=5)
    wave_begin = find_unique_event(events, step="run.wave.start.begin")
    wave_end = find_unique_event(events, step="run.wave.start.end", after_sequence=int(wave_begin["sequence"]))
    death_begin = find_unique_event(events, step="run.death.terminal_callback", after_sequence=int(wave_end["sequence"]))
    game_over = find_unique_event(events, step="overlay.game_over.installed", after_sequence=int(death_begin["sequence"]))

    startup_hub_steps = switch_lifecycle(events, startup_hub)
    startup_end_sequence = int(startup_hub_steps[-1]["sequence"])
    startup_steps = [
        compact_event(event)
        for event in events
        if int(startup_office["sequence"]) <= int(event["sequence"]) <= startup_end_sequence
    ]

    title = {
        "label": "native_recorder_ready_before_gameplay",
        "tick": events[0]["simulation_tick"],
        "scene": "title/front-end",
        "scene_kind": "frontend",
        "region_index": -1,
        "entity_count": 0,
        "entity_count_source": "live capture.ready with gameplay=0 and active_region=0",
        "session_state": "not-in-game",
        "input_sealed": events[0]["input_sealed"],
    }
    death_steps = [
        compact_event(event)
        for event in events
        if int(death_begin["sequence"]) <= int(event["sequence"]) <= int(game_over["sequence"])
    ]
    return_steps = [
        compact_event(event)
        for event in events
        if int(event["sequence"]) > int(game_over["sequence"])
        and event.get("step") != "capture.shutdown"
    ]
    require(return_steps, "stock Game Over return produced no native lifecycle events")

    transitions = [
        timeline_transition(
            source="frontend.shell",
            edge="startup_office_then_return_courtyard",
            trigger="launcher QuickStart accepted the landed Create flow and native onboarding completed",
            destination="gameplay.courtyard",
            before=title,
            after=snapshots["hub_initial"],
            steps=startup_steps,
            edge_path=("startup_office", "return_courtyard"),
        ),
        timeline_transition(
            source="gameplay.courtyard",
            edge="enter_library",
            trigger="accepted authority sd.scene.switch_region(2) probe",
            destination="gameplay.library",
            before=snapshots["hub_before_library"],
            after=snapshots["library"],
            steps=switch_lifecycle(events, to_library),
        ),
        timeline_transition(
            source="gameplay.library",
            edge="return_courtyard",
            trigger="accepted authority sd.scene.switch_region(0) probe",
            destination="gameplay.courtyard",
            before=snapshots["library"],
            after=snapshots["hub_after_library"],
            steps=switch_lifecycle(events, from_library),
        ),
        timeline_transition(
            source="gameplay.courtyard",
            edge="start_run_pipeline",
            trigger="accepted host start_testrun action",
            destination="gameplay.arena",
            before=snapshots["hub_before_run"],
            after=snapshots["arena_ready"],
            steps=switch_lifecycle(events, to_arena),
            edge_path=("start_run", "arena_materialized"),
        ),
        timeline_transition(
            source="gameplay.arena",
            edge="terminal_death",
            trigger="native magic-hit trial reduced the sole participant to zero life",
            destination="overlay.game_over",
            before=snapshots["arena_before_death"],
            after=snapshots["game_over"],
            steps=death_steps,
        ),
        timeline_transition(
            source="overlay.game_over",
            edge="stock_boneyard_return_pipeline",
            trigger="exact-PID stock window input followed by retained Create confirmation",
            destination="gameplay.courtyard",
            before=snapshots["game_over"],
            after=snapshots["hub_final"],
            steps=return_steps,
            edge_path=(
                "boneyard_completion",
                "open_hall_of_fame",
                "continue_to_frontend",
                "startup_hub",
            ),
        ),
    ]
    wave_observation = {
        "source": "gameplay.arena",
        "event": "wave_start_same_room",
        "trigger": "native Arena wake/start pipeline before input unseal",
        "destination": "gameplay.arena",
        "is_state_transition": False,
        "ordered_lifecycle_steps": [compact_event(wave_begin), compact_event(wave_end)],
        "live_same_room_confirmation": snapshots["arena_after_wave_start"],
        "finding": "wave progression does not change the native region; Boneyard is one Arena room",
    }
    return {
        "schema_version": 1,
        "session_timeline": {
            "header": header,
            "transitions": transitions,
            "non_transition_observations": [wave_observation],
            "action_receipts": receipts,
        },
        "transition_graph": {
            "header": {
                **header,
                "capture_method": "live injected native graph emitter; no edge was hand-entered into the fixture",
            },
            "states": graph["states"],
            "edges": graph["edges"],
            "illegal_edge_classes": graph["illegal_edge_classes"],
        },
    }


def write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence-directory", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--instance", default="flw-g13-a")
    parser.add_argument("--local-port", type=int, default=52321)
    parser.add_argument("--unused-remote-port", type=int, default=52322)
    parser.add_argument("--game-directory", type=Path, required=True)
    parser.add_argument("--launcher-path", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    require(args.instance.startswith("flw-"), "instance must use the isolated flw-* namespace")
    ports = (args.local_port, args.unused_remote_port)
    require(len(set(ports)) == 2 and all(52321 <= port <= 52328 for port in ports), "ports must be distinct and inside UDP 52321..52328")
    require(args.overwrite or not args.output.exists(), f"fixture already exists: {args.output}")
    require(not args.evidence_directory.exists(), f"evidence directory already exists: {args.evidence_directory}")
    require(LOADER.is_file() and STAGED_LOADER.is_file(), "Release and staged loader DLLs must exist")
    require(sha256_file(LOADER) == sha256_file(STAGED_LOADER), "staged loader does not match the Release build")

    revision = source_revision(allow_dirty=args.allow_dirty)
    args.evidence_directory.mkdir(parents=True)
    capture_path_windows = path_for_powershell(args.evidence_directory)
    old_capture = os.environ.get("SDMOD_NATIVE_SESSION_FLOW_CAPTURE_DIRECTORY")
    old_disable_audio = os.environ.get("SDMOD_DISABLE_AUDIO")
    old_wslenv = os.environ.get("WSLENV")
    capture_environment_names = {
        "SDMOD_NATIVE_SESSION_FLOW_CAPTURE_DIRECTORY",
        "SDMOD_DISABLE_AUDIO",
    }
    wslenv_entries = [
        entry
        for entry in (old_wslenv or "").split(":")
        if entry and entry.split("/", 1)[0] not in capture_environment_names
    ]
    wslenv_entries.extend(
        (
            "SDMOD_NATIVE_SESSION_FLOW_CAPTURE_DIRECTORY/p",
            "SDMOD_DISABLE_AUDIO",
        )
    )
    os.environ["WSLENV"] = ":".join(wslenv_entries)
    os.environ["SDMOD_NATIVE_SESSION_FLOW_CAPTURE_DIRECTORY"] = str(args.evidence_directory.resolve())
    os.environ["SDMOD_DISABLE_AUDIO"] = "1"

    launch: dict[str, object] | None = None
    owned: dict[int, str] = {}
    snapshots: dict[str, dict[str, Any]] = {}
    receipts: dict[str, Any] = {}
    try:
        launch = launch_solo(
            instance=args.instance,
            local_port=ports[0],
            unused_remote_port=ports[1],
            game_directory=args.game_directory,
            launcher_path=args.launcher_path,
            exact_mod_ids=(ACCEPTANCE_MOD_ID,),
        )
        owned = _owned_solo_processes(launch)
        receipts["owned_processes_before"] = validate_owned_processes(owned)
        pipe_name = str(launch["luaPipe"])
        wait_for_scene(pipe_name, "hub", 45.0)
        snapshots["hub_initial"] = wait_snapshot(
            pipe_name,
            owned,
            lambda value: (
                value["scene"] == "hub"
                and value["region_index"] == 0
                and value["session_state"] == "in-hub"
                and not value["input_sealed"]
            ),
            "hub_initial",
            stable_for=1.0,
        )
        receipts["bots_disabled"] = _disable_bots([pipe_name])

        snapshots["hub_before_library"] = snapshot(pipe_name, "hub_before_library")
        receipts["enter_library"] = request_region(pipe_name, 2)
        snapshots["library"] = wait_snapshot(
            pipe_name,
            owned,
            lambda value: value["region_index"] == 2 and not value["transitioning"],
            "library",
            stable_for=1.0,
        )
        receipts["return_hub"] = request_region(pipe_name, 0)
        snapshots["hub_after_library"] = wait_snapshot(
            pipe_name,
            owned,
            lambda value: value["scene"] == "hub" and value["region_index"] == 0,
            "hub_after_library",
            stable_for=1.0,
        )

        snapshots["hub_before_run"] = snapshot(pipe_name, "hub_before_run")
        _start_testrun_when_ready(pipe_name)
        wait_for_scene(pipe_name, "testrun", 45.0)
        snapshots["arena_ready"] = wait_snapshot(
            pipe_name,
            owned,
            lambda value: (
                value["region_index"] == 5
                and value["session_state"] == "in-boneyard"
                and value["barrier_released"]
                and not value["barrier_timed_out"]
                and not value["input_sealed"]
            ),
            "arena_ready_and_unsealed",
        )
        snapshots["arena_after_wave_start"] = wait_snapshot(
            pipe_name,
            owned,
            lambda value: value["region_index"] == 5 and value["wave_index"] >= 1,
            "arena_after_wave_start_same_room",
        )

        snapshots["arena_before_death"] = snapshot(pipe_name, "arena_before_death")
        receipts["primed_vitals"] = set_local_player_vitals(pipe_name, 1.0, 25.0)
        receipts["lethal_hit"] = invoke_native_magic_hit_trial(
            pipe_name,
            projectile_damage=0.0,
            magic_damage=1000.0,
            attempts=2,
            label="G13 solo native Game Over",
            timeout=8.0,
        )
        receipts["game_over_presentation"] = capture_native_game_over(
            pipe_name,
            args.evidence_directory / "game-over.png",
            timeout=20.0,
            allow_boneyard_mode=True,
        )
        snapshots["game_over"] = snapshot(pipe_name, "game_over")
        receipts["stock_return"] = advance_stock_boneyard_game_over(
            {pipe_name: next(iter(owned))},
            {pipe_name: ("fire", "mind")},
        )
        snapshots["hub_final"] = wait_snapshot(
            pipe_name,
            owned,
            lambda value: (
                value["scene"] == "hub"
                and value["session_state"] == "in-hub"
                and not value["input_sealed"]
            ),
            "hub_final",
            stable_for=1.0,
        )
        receipts["owned_processes_after"] = validate_owned_processes(owned)
    finally:
        if old_capture is None:
            os.environ.pop("SDMOD_NATIVE_SESSION_FLOW_CAPTURE_DIRECTORY", None)
        else:
            os.environ["SDMOD_NATIVE_SESSION_FLOW_CAPTURE_DIRECTORY"] = old_capture
        if old_disable_audio is None:
            os.environ.pop("SDMOD_DISABLE_AUDIO", None)
        else:
            os.environ["SDMOD_DISABLE_AUDIO"] = old_disable_audio
        if old_wslenv is None:
            os.environ.pop("WSLENV", None)
        else:
            os.environ["WSLENV"] = old_wslenv
        if owned:
            receipts["cleanup"] = stop_owned_processes(owned)

    require(launch is not None, "solo launch did not complete")
    events_path = args.evidence_directory / "session-flow-events.jsonl"
    graph_path = args.evidence_directory / "session-flow-native-graph.json"
    status_path = args.evidence_directory / "session-flow-status.json"
    events = read_events(events_path)
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    status = json.loads(status_path.read_text(encoding="utf-8"))
    require(status.get("initialized") is True and status.get("runnable") is True, f"recorder ended non-runnable: {status}")
    require(len(graph.get("states", [])) == 12, "live native graph did not contain 12 enumerated states")
    require(len(graph.get("edges", [])) == 23, "live native graph did not contain all 23 legal edges")

    executable_path = _path_for_local_python(str(launch["executablePath"]))
    captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    header = {
        "instance": args.instance,
        "source_sha": revision["sha"],
        "source_branch": revision["branch"],
        "source_dirty": revision["dirty"],
        "captured_at_utc": captured_at,
        "capture_method": "live solo Windows instance; injected read-only recorder plus existing lua-exec and exact-PID stock input",
        "process_id": next(iter(owned)),
        "udp_ports": list(ports),
        "audio_disabled": launch.get("audioDisabled"),
        "executable_sha256": sha256_file(executable_path),
        "loader_sha256": sha256_file(STAGED_LOADER),
        "raw_events_sha256": sha256_file(events_path),
        "raw_graph_sha256": sha256_file(graph_path),
        "raw_status_sha256": sha256_file(status_path),
        "raw_evidence_directory": path_for_powershell(args.evidence_directory),
    }
    fixture = build_fixture(
        header=header,
        events=events,
        graph=graph,
        snapshots=snapshots,
        receipts=receipts,
    )
    write_json(args.output, fixture)
    write_json(
        args.evidence_directory / "capture-summary.json",
        {"header": header, "snapshots": snapshots, "action_receipts": receipts},
    )
    print(json.dumps({"ok": True, "output": str(args.output), "header": header}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
