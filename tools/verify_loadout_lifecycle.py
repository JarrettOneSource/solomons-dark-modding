#!/usr/bin/env python3
"""Verify multiplayer loadout ordering and fresh-run selection semantics."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from multiplayer_defense_behavior_harness import invoke_native_magic_hit_trial
from multiplayer_frame_capture import capture_game_backbuffer
from owned_process_ledger import register_owned_launch
from verify_game_over_session_semantics import (
    _apply_authoritative_remote_lethal_hit,
    _click_owned_window,
    _path_for_local_python,
    _wait_for_state,
    capture_native_game_over,
    query_session_state,
    terminal_game_over_state_matches,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    HOST_ID,
    HOST_NAME,
    ROOT,
    VerifyFailure,
    activate_native_ui_action,
    launch_pair,
    parse_int_text,
    query_native_create_state,
    stop_exact_game_processes,
    wait_for_remote,
    wait_for_scene,
    lua,
    parse_key_values,
    path_for_powershell,
    start_testrun,
    stop_game_processes,
)
from verify_player_health_death_sync import set_local_player_vitals


CREATE_ELEMENT_IDS = {
    "ether": 0,
    "fire": 1,
    "air": 2,
    "water": 3,
    "earth": 4,
}
CREATE_DISCIPLINE_IDS = {
    "mind": 2,
    "body": 1,
    "arcane": 0,
}

LOADOUT_STATE_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local scene = sd.world.get_scene()
local player = sd.player.get_state()
local ui = sd.ui and sd.ui.get_snapshot and sd.ui.get_snapshot() or nil
local mp = sd.runtime and sd.runtime.get_multiplayer_state and
  sd.runtime.get_multiplayer_state() or nil
local loading = mp and mp.loading_screen or nil
local local_row = nil
local remote_row = nil
for _, participant in ipairs(mp and mp.participants or {}) do
  if participant.is_owner then
    local_row = participant
  elseif participant.transport_connected then
    remote_row = participant
  end
end
emit("scene", scene and (scene.name or scene.kind) or "")
emit("scene_kind", scene and scene.kind or "")
emit("world_address", scene and scene.world_address or 0)
emit("gameplay_scene_address", scene and scene.gameplay_scene_address or 0)
emit("surface", ui and ui.surface_id or "")
emit("player_valid", player and player.valid or false)
emit("player_actor", player and player.actor_address or 0)
emit("session_status", mp and mp.session_status or "")
emit("session_state", mp and mp.session_state or "")
emit("participant_count", mp and mp.participant_count or 0)
emit("local_runtime_valid", local_row and local_row.runtime_valid or false)
emit("local_scene_kind", local_row and local_row.scene_kind or "")
emit("local_run_nonce", local_row and local_row.run_nonce or 0)
emit("local_wave", local_row and local_row.wave or 0)
emit("local_loadout_generation",
  local_row and local_row.loadout_pick_generation or 0)
emit("local_loadout_state",
  local_row and local_row.loadout_pick_state or "")
emit("local_element_id",
  player and player.profile and player.profile.element_id or -1)
emit("local_discipline_id",
  player and player.profile and player.profile.discipline_id or -1)
emit("remote_present", remote_row ~= nil)
emit("remote_runtime_valid", remote_row and remote_row.runtime_valid or false)
emit("remote_scene_kind", remote_row and remote_row.scene_kind or "")
emit("remote_run_nonce", remote_row and remote_row.run_nonce or 0)
emit("remote_wave", remote_row and remote_row.wave or 0)
emit("remote_loadout_generation",
  remote_row and remote_row.loadout_pick_generation or 0)
emit("remote_loadout_state",
  remote_row and remote_row.loadout_pick_state or "")
emit("loading_active", loading and loading.active or false)
emit("loading_flow", loading and loading.flow or 0)
emit("loading_stage", loading and loading.stage or 0)
emit("loading_progress", loading and loading.progress or 0)
emit("loading_progress_bar_visible",
  loading and loading.progress_bar_visible or false)
emit("loading_stage_id", loading and loading.stage_id or "")
emit("loading_label", loading and loading.label or "")
"""


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10.0,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(f"could not resolve source SHA: {completed.stdout}")
    return completed.stdout.strip()


def query_loadout_state(pipe_name: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, LOADOUT_STATE_PROBE, timeout=8.0))


def wait_for_create(pipe_name: str, timeout: float = 45.0) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_native_create_state(pipe_name)
        if (
            last.get("ui") == "create"
            and parse_int_text(last.get("owner"), 0) != 0
        ):
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        f"stock Create surface did not become ready on {pipe_name}: {last}"
    )


def choose_create(
    pipe_name: str,
    *,
    element: str,
    discipline: str,
    timeout: float = 30.0,
) -> list[dict[str, str]]:
    if element not in CREATE_ELEMENT_IDS:
        raise VerifyFailure(f"unsupported element: {element}")
    if discipline not in CREATE_DISCIPLINE_IDS:
        raise VerifyFailure(f"unsupported discipline: {discipline}")

    actions: list[dict[str, str]] = []
    phases = (
        (
            f"create.select_element_{element}",
            "element_enabled",
            "element_selected",
            CREATE_ELEMENT_IDS[element],
        ),
        (
            f"create.select_discipline_{discipline}",
            "discipline_enabled",
            "discipline_selected",
            CREATE_DISCIPLINE_IDS[discipline],
        ),
    )
    for action_id, enabled_key, selected_key, expected_id in phases:
        deadline = time.monotonic() + timeout
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            last = query_native_create_state(pipe_name, action_id)
            if (
                last.get("ui") == "create"
                and parse_int_text(last.get("owner"), 0) != 0
                and parse_int_text(last.get(enabled_key), 0) != 0
                and last.get("action_found") == "true"
            ):
                actions.append(
                    activate_native_ui_action(pipe_name, action_id, "create")
                )
                break
            time.sleep(0.1)
        else:
            raise VerifyFailure(
                f"stock Create action never became ready: {action_id}: {last}"
            )

        latch_deadline = time.monotonic() + 12.0
        while time.monotonic() < latch_deadline:
            last = query_native_create_state(pipe_name)
            if last.get("ui") != "create":
                break
            if parse_int_text(last.get(selected_key), -1) == expected_id:
                break
            time.sleep(0.1)
        else:
            raise VerifyFailure(
                f"stock Create action did not latch {expected_id}: "
                f"{action_id}: {last}"
            )
    return actions


def choose_retained_create_element(
    pipe_name: str,
    *,
    element: str,
    discipline: str,
    timeout: float = 30.0,
) -> dict[str, dict[str, str]]:
    if element not in CREATE_ELEMENT_IDS:
        raise VerifyFailure(f"unsupported element: {element}")
    if discipline not in CREATE_DISCIPLINE_IDS:
        raise VerifyFailure(f"unsupported discipline: {discipline}")
    action_id = f"create.select_element_{element}"
    expected_id = CREATE_ELEMENT_IDS[element]
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_native_create_state(pipe_name, action_id)
        if (
            last.get("ui") == "create"
            and parse_int_text(last.get("owner"), 0) != 0
            and parse_int_text(last.get("element_enabled"), 0) != 0
            and last.get("action_found") == "true"
        ):
            element_action = activate_native_ui_action(
                pipe_name,
                action_id,
                "create",
            )
            break
        time.sleep(0.1)
    else:
        raise VerifyFailure(
            f"retained Create element never became ready: {action_id}: {last}"
        )

    latch_deadline = time.monotonic() + 12.0
    while time.monotonic() < latch_deadline:
        last = query_native_create_state(pipe_name)
        if (
            last.get("ui") == "create"
            and parse_int_text(last.get("element_selected"), -1) == expected_id
            and parse_int_text(last.get("discipline_selected"), -1)
            in (-1, 0xFFFFFFFF)
        ):
            break
        time.sleep(0.1)
    else:
        raise VerifyFailure(
            f"retained Create element did not latch {expected_id}: "
            f"{action_id}: {last}"
        )

    discipline_action_id = f"create.select_discipline_{discipline}"
    discipline_deadline = time.monotonic() + 12.0
    while time.monotonic() < discipline_deadline:
        last = query_native_create_state(pipe_name, discipline_action_id)
        if (
            last.get("ui") == "create"
            and parse_int_text(last.get("discipline_enabled"), 0) != 0
            and last.get("action_found") == "true"
        ):
            discipline_action = activate_native_ui_action(
                pipe_name,
                discipline_action_id,
                "create",
            )
            return {
                "element": element_action,
                "discipline": discipline_action,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "retained Create discipline never became ready after element "
        f"change: {discipline_action_id}: {last}"
    )


def _start_acceptance_wave(host_pipe: str) -> dict[str, str]:
    wave_start = parse_key_values(
        lua(
            host_pipe,
            "print('ok=' .. tostring(sd.gameplay.start_waves()))",
            timeout=8.0,
        )
    )
    if wave_start.get("ok") != "true":
        raise VerifyFailure(
            f"host could not start the acceptance wave: {wave_start}"
        )
    return wave_start


def wait_until_not_create(
    pipe_name: str,
    timeout: float = 30.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_loadout_state(pipe_name)
        if last.get("surface") != "create":
            return last
        time.sleep(0.1)
    raise VerifyFailure(f"Create surface did not close on {pipe_name}: {last}")


def wait_for_host_loadout_barrier(
    pipe_name: str,
    timeout: float = 20.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = query_loadout_state(pipe_name)
        if (
            last.get("loading_active") == "true"
            and last.get("loading_stage_id") == "waiting_for_host_loadout"
            and last.get("loading_label") ==
                "Waiting for host to pick loadout"
            and last.get("loading_progress_bar_visible") == "false"
            and last.get("local_loadout_state") == "picked"
        ):
            return last
        time.sleep(0.05)
    raise VerifyFailure(
        f"host-loadout barrier did not become visible on {pipe_name}: {last}"
    )


def start_testrun_when_ready(
    host_pipe: str,
    timeout: float = 30.0,
) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            start_testrun(host_pipe)
            return
        except VerifyFailure as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise VerifyFailure(
        f"host testrun never reached stock readiness: {last_error}"
    )


def wait_for_run_convergence(
    host_pipe: str,
    client_pipe: str,
    timeout: float = 45.0,
    *,
    start_wave: bool = True,
    require_wave: bool = True,
) -> dict[str, Any]:
    wait_for_scene(host_pipe, "testrun", timeout)
    wait_for_scene(client_pipe, "testrun", timeout)
    relationships = {
        "hostObservesClient": wait_for_remote(
            host_pipe,
            CLIENT_ID,
            CLIENT_NAME,
            "testrun",
            timeout,
        ),
        "clientObservesHost": wait_for_remote(
            client_pipe,
            HOST_ID,
            HOST_NAME,
            "testrun",
            timeout,
        ),
    }
    wave_start = _start_acceptance_wave(host_pipe) if start_wave else None
    deadline = time.monotonic() + timeout
    last: dict[str, dict[str, str]] = {}
    while time.monotonic() < deadline:
        last = {
            "host": query_loadout_state(host_pipe),
            "client": query_loadout_state(client_pipe),
        }
        host_nonce = parse_int_text(last["host"].get("local_run_nonce"), 0)
        client_nonce = parse_int_text(last["client"].get("local_run_nonce"), 0)
        if (
            host_nonce > 0
            and host_nonce == client_nonce
            and (
                not require_wave
                or (
                    parse_int_text(last["host"].get("local_wave"), 0) >= 1
                    and parse_int_text(
                        last["client"].get("local_wave"),
                        0,
                    ) >= 1
                )
            )
            and last["host"].get("loading_active") == "false"
            and last["client"].get("loading_active") == "false"
        ):
            return {
                "relationships": relationships,
                "waveStart": wave_start,
                "states": last,
                "runNonce": host_nonce,
            }
        time.sleep(0.1)
    raise VerifyFailure(f"two-peer run did not converge on an active wave: {last}")


def _validate_run_arguments(args: argparse.Namespace) -> str:
    if not re.fullmatch(r"ldt[A-Za-z0-9._-]{0,44}", args.instance_prefix):
        raise VerifyFailure("instance prefix must begin with 'ldt'")
    actual_sha = _git_sha()
    if actual_sha != args.expected_sha:
        raise VerifyFailure(
            f"source SHA changed: expected={args.expected_sha} actual={actual_sha}"
        )
    if args.evidence_root.exists():
        raise VerifyFailure(f"evidence root must be new: {args.evidence_root}")
    if args.runtime_root.exists():
        raise VerifyFailure(f"runtime root must be new: {args.runtime_root}")
    args.evidence_root.mkdir(parents=True, exist_ok=False)
    return actual_sha


def _launch_manual_pair(
    args: argparse.Namespace,
    *,
    directory_url: str | None = None,
    god_mode: bool = False,
) -> dict[str, object]:
    launch = launch_pair(
        host_preset="pair_manual",
        client_preset="pair_manual",
        temporary_host_profile=True,
        fresh_install=False,
        god_mode=god_mode,
        tile_windows=True,
        allow_focus_steal=False,
        kill_existing=False,
        instance_prefix=args.instance_prefix,
        host_port=args.host_port,
        client_port=args.client_port,
        game_directory=args.game_directory,
        launcher_path=args.launcher,
        runtime_root=args.runtime_root,
        directory_url=directory_url,
        test_survival_boneyard_override=(
            ROOT / "tests/fixtures/boneyards/flat_multiplayer_test.boneyard"
        ),
        test_wave_override=(
            ROOT / "tests/fixtures/waves/death_spectator_respawn_test.txt"
        ),
        exact_mod_id="sample.lua.ui_sandbox_lab",
        quick_start=True,
        no_lua_automation=False,
        enable_audio=False,
    )
    if launch.get("audioDisabled") is not True:
        raise VerifyFailure(f"loadout pair did not disable audio: {launch}")
    return launch


def run_client_first(args: argparse.Namespace) -> dict[str, Any]:
    actual_sha = _validate_run_arguments(args)
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "ok": False,
        "mode": "client-first",
        "sourceSha": actual_sha,
        "instancePrefix": args.instance_prefix,
        "ports": [args.host_port, args.client_port],
        "audioDisabledRequired": True,
    }
    launch: dict[str, object] | None = None
    try:
        launch = _launch_manual_pair(args)
        result["launch"] = launch
        host_pipe = str(launch["hostLuaPipe"])
        client_pipe = str(launch["clientLuaPipe"])
        result["initialCreate"] = {
            "host": wait_for_create(host_pipe),
            "client": wait_for_create(client_pipe),
        }

        result["clientPickActions"] = choose_create(
            client_pipe,
            element="water",
            discipline="body",
        )
        result["clientBarrier"] = wait_for_host_loadout_barrier(client_pipe)
        time.sleep(0.25)
        host_still_picking = query_loadout_state(host_pipe)
        if host_still_picking.get("surface") != "create":
            raise VerifyFailure(
                f"host picker closed before host selection: {host_still_picking}"
            )
        result["hostStillPicking"] = host_still_picking
        result["barrierCapture"] = capture_game_backbuffer(
            client_pipe,
            args.evidence_root / "screenshots" /
                "client-waiting-for-host-no-bar.png",
        )

        result["hostPickActions"] = choose_create(
            host_pipe,
            element="fire",
            discipline="mind",
        )
        wait_for_scene(host_pipe, "hub", 45.0)
        wait_for_scene(client_pipe, "hub", 45.0)
        start_testrun_when_ready(host_pipe)
        result["runConvergence"] = wait_for_run_convergence(
            host_pipe,
            client_pipe,
        )
        result["runCaptures"] = {
            "host": capture_game_backbuffer(
                host_pipe,
                args.evidence_root / "screenshots" /
                    "host-client-first-wave.png",
            ),
            "client": capture_game_backbuffer(
                client_pipe,
                args.evidence_root / "screenshots" /
                    "client-client-first-wave.png",
            ),
        }
        result["logCopies"] = _copy_logs(launch, args.evidence_root / "logs")
        result["ok"] = True
        return result
    finally:
        if launch is not None:
            try:
                result["cleanup"] = stop_exact_game_processes(launch)
            finally:
                _copy_logs(launch, args.evidence_root / "logs")
        _write_json(args.evidence_root / "result.json", result)


def _wait_for_host_solo_play(
    host_pipe: str,
    client_pipe: str,
    timeout: float = 45.0,
) -> dict[str, Any]:
    wait_for_scene(host_pipe, "testrun", timeout)
    wave_start = _start_acceptance_wave(host_pipe)
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = {
            "host": query_loadout_state(host_pipe),
            "client": query_loadout_state(client_pipe),
            "clientCreate": query_native_create_state(client_pipe),
        }
        if (
            last["host"].get("local_scene_kind") == "Run"
            and parse_int_text(last["host"].get("local_wave"), 0) >= 1
            and last["host"].get("loading_active") == "false"
            and last["client"].get("surface") == "create"
            and last["client"].get("local_loadout_state") == "picking"
            and last["clientCreate"].get("ui") == "create"
        ):
            return {"waveStart": wave_start, "states": last}
        time.sleep(0.1)
    raise VerifyFailure(
        "host did not play while the client remained in Create: "
        f"{last}"
    )


def run_host_first_trickle(args: argparse.Namespace) -> dict[str, Any]:
    actual_sha = _validate_run_arguments(args)
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "ok": False,
        "mode": "host-first-trickle",
        "sourceSha": actual_sha,
        "instancePrefix": args.instance_prefix,
        "ports": [args.host_port, args.client_port],
        "audioDisabledRequired": True,
    }
    launch: dict[str, object] | None = None
    try:
        launch = _launch_manual_pair(args, god_mode=True)
        result["launch"] = launch
        host_pipe = str(launch["hostLuaPipe"])
        client_pipe = str(launch["clientLuaPipe"])
        result["initialCreate"] = {
            "host": wait_for_create(host_pipe),
            "client": wait_for_create(client_pipe),
        }
        result["hostPickActions"] = choose_create(
            host_pipe,
            element="fire",
            discipline="mind",
        )
        wait_for_scene(host_pipe, "hub", 45.0)
        client_still_picking = query_loadout_state(client_pipe)
        if client_still_picking.get("surface") != "create":
            raise VerifyFailure(
                "client picker closed before its selection: "
                f"{client_still_picking}"
            )
        result["clientStillPickingBeforeRun"] = client_still_picking
        start_testrun_when_ready(host_pipe)
        result["hostSoloRun"] = _wait_for_host_solo_play(
            host_pipe,
            client_pipe,
        )
        time.sleep(0.5)
        result["hostSoloCaptures"] = {
            "hostPlaying": capture_game_backbuffer(
                host_pipe,
                args.evidence_root / "screenshots" /
                    "host-mid-wave-client-still-picking.png",
            ),
            "clientPicking": capture_game_backbuffer(
                client_pipe,
                args.evidence_root / "screenshots" /
                    "client-picker-host-mid-wave.png",
            ),
        }
        result["clientLatePickActions"] = choose_create(
            client_pipe,
            element="water",
            discipline="body",
        )
        result["trickleConvergence"] = wait_for_run_convergence(
            host_pipe,
            client_pipe,
            start_wave=False,
        )
        result["trickleCaptures"] = {
            "host": capture_game_backbuffer(
                host_pipe,
                args.evidence_root / "screenshots" /
                    "host-after-client-trickle.png",
            ),
            "client": capture_game_backbuffer(
                client_pipe,
                args.evidence_root / "screenshots" /
                    "client-after-trickle.png",
            ),
        }
        result["logCopies"] = _copy_logs(launch, args.evidence_root / "logs")
        result["ok"] = True
        return result
    finally:
        if launch is not None:
            try:
                result["cleanup"] = stop_exact_game_processes(launch)
            finally:
                _copy_logs(launch, args.evidence_root / "logs")
        _write_json(args.evidence_root / "result.json", result)


def _terminal_two_peer_game_over(
    host_pipe: str,
    client_pipe: str,
) -> dict[str, Any]:
    client_death = _apply_authoritative_remote_lethal_hit(
        host_pipe,
        CLIENT_ID,
        "loadout lifecycle client death",
    )
    time.sleep(0.25)
    client_after_death = query_session_state(client_pipe)
    host_vitals = set_local_player_vitals(host_pipe, 1.0, 25.0)
    host_death = invoke_native_magic_hit_trial(
        host_pipe,
        projectile_damage=0.0,
        magic_damage=1000.0,
        attempts=2,
        label="loadout lifecycle host terminal death",
        timeout=8.0,
    )
    terminal = {
        "host": _wait_for_state(
            host_pipe,
            terminal_game_over_state_matches,
            timeout=12.0,
            description="host authority-scoped Game Over",
        ),
        "client": _wait_for_state(
            client_pipe,
            terminal_game_over_state_matches,
            timeout=12.0,
            description="client authority-scoped Game Over",
        ),
    }
    return {
        "clientDeath": client_death,
        "clientAfterDeath": client_after_death,
        "hostPrimedVitals": host_vitals,
        "hostDeath": host_death,
        "terminalStates": terminal,
    }


def _advance_game_over_to_create(
    pipe_name: str,
    process_id: int,
    *,
    timeout: float = 60.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    next_click_at = 0.0
    clicks: list[str] = []
    last_state: dict[str, str] = {}
    last_create: dict[str, str] = {}
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_click_at:
            clicks.append(_click_owned_window(process_id, 0.5, 0.5))
            next_click_at = now + 0.5
        last_state = query_loadout_state(pipe_name)
        last_create = query_native_create_state(pipe_name)
        if (
            last_state.get("surface") == "create"
            and last_state.get("local_loadout_state") == "picking"
            and parse_int_text(
                last_state.get("local_loadout_generation"),
                0,
            ) >= 2
            and last_create.get("ui") == "create"
            and parse_int_text(last_create.get("owner"), 0) != 0
        ):
            return {
                "processId": process_id,
                "clicks": clicks,
                "loadoutState": last_state,
                "createState": last_create,
            }
        time.sleep(0.05)
    raise VerifyFailure(
        "stock Game Over did not advance to the next-generation Create "
        f"surface on {pipe_name}: state={last_state} create={last_create}"
    )


def _assert_retained_preselection(
    label: str,
    state: dict[str, Any],
    *,
    element: str,
    discipline: str,
) -> None:
    create = state["createState"]
    actual = (
        parse_int_text(create.get("element_selected"), -1),
        parse_int_text(create.get("discipline_selected"), -1),
    )
    expected = (
        CREATE_ELEMENT_IDS[element],
        CREATE_DISCIPLINE_IDS[discipline],
    )
    if actual != expected:
        raise VerifyFailure(
            f"{label} previous loadout was not preselected: "
            f"expected={expected} actual={actual} state={state}"
        )


def _remote_element_id(
    convergence: dict[str, Any],
    relationship: str,
    participant_id: int,
) -> int:
    values = convergence["relationships"][relationship]
    key = f"peer.{participant_id}.element_id"
    element_id = parse_int_text(values.get(key), -1)
    if element_id < 0:
        raise VerifyFailure(
            f"remote element was unavailable for {relationship}: {values}"
        )
    return element_id


def run_game_over_repick(args: argparse.Namespace) -> dict[str, Any]:
    actual_sha = _validate_run_arguments(args)
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "ok": False,
        "mode": "game-over-repick",
        "sourceSha": actual_sha,
        "instancePrefix": args.instance_prefix,
        "ports": [args.host_port, args.client_port],
        "audioDisabledRequired": True,
    }
    launch: dict[str, object] | None = None
    try:
        launch = _launch_manual_pair(args)
        result["launch"] = launch
        host_pipe = str(launch["hostLuaPipe"])
        client_pipe = str(launch["clientLuaPipe"])
        wait_for_create(host_pipe)
        wait_for_create(client_pipe)
        result["initialPicks"] = {
            "host": choose_create(
                host_pipe,
                element="fire",
                discipline="mind",
            ),
            "client": choose_create(
                client_pipe,
                element="water",
                discipline="body",
            ),
        }
        wait_for_scene(host_pipe, "hub", 45.0)
        wait_for_scene(client_pipe, "hub", 45.0)
        start_testrun_when_ready(host_pipe)
        first_run = wait_for_run_convergence(
            host_pipe,
            client_pipe,
            start_wave=False,
            require_wave=False,
        )
        result["firstRun"] = first_run
        first_elements = {
            "hostObservedClient": _remote_element_id(
                first_run,
                "hostObservesClient",
                CLIENT_ID,
            ),
            "clientObservedHost": _remote_element_id(
                first_run,
                "clientObservesHost",
                HOST_ID,
            ),
        }
        result["firstRunObservedElements"] = first_elements
        result["gameOverTransition"] = _terminal_two_peer_game_over(
            host_pipe,
            client_pipe,
        )
        result["gameOverCaptures"] = {
            "host": capture_native_game_over(
                host_pipe,
                args.evidence_root / "screenshots" / "host-game-over.png",
                allow_boneyard_mode=True,
            ),
            "client": capture_native_game_over(
                client_pipe,
                args.evidence_root / "screenshots" / "client-game-over.png",
                allow_boneyard_mode=True,
            ),
        }
        repick = {
            "host": _advance_game_over_to_create(
                host_pipe,
                int(launch["hostProcessId"]),
            ),
            "client": _advance_game_over_to_create(
                client_pipe,
                int(launch["clientProcessId"]),
            ),
        }
        _assert_retained_preselection(
            "host",
            repick["host"],
            element="fire",
            discipline="mind",
        )
        _assert_retained_preselection(
            "client",
            repick["client"],
            element="water",
            discipline="body",
        )
        result["repickPreselection"] = repick
        time.sleep(0.25)
        result["repickCaptures"] = {
            "host": capture_game_backbuffer(
                host_pipe,
                args.evidence_root / "screenshots" /
                    "host-repick-fire-mind-preselected.png",
            ),
            "client": capture_game_backbuffer(
                client_pipe,
                args.evidence_root / "screenshots" /
                    "client-repick-water-body-preselected.png",
            ),
        }
        result["changedElementPicks"] = {
            "host": choose_retained_create_element(
                host_pipe,
                element="earth",
                discipline="mind",
            ),
            "client": choose_retained_create_element(
                client_pipe,
                element="air",
                discipline="body",
            ),
        }
        wait_for_scene(host_pipe, "hub", 45.0)
        wait_for_scene(client_pipe, "hub", 45.0)
        start_testrun_when_ready(host_pipe)
        second_run = wait_for_run_convergence(host_pipe, client_pipe)
        result["secondRun"] = second_run
        second_elements = {
            "hostObservedClient": _remote_element_id(
                second_run,
                "hostObservesClient",
                CLIENT_ID,
            ),
            "clientObservedHost": _remote_element_id(
                second_run,
                "clientObservesHost",
                HOST_ID,
            ),
        }
        changed = {
            label: second_elements[label] != first_elements[label]
            for label in first_elements
        }
        if not all(changed.values()):
            raise VerifyFailure(
                "changed repick elements did not replicate to both observers: "
                f"first={first_elements} second={second_elements}"
            )
        result["secondRunObservedElements"] = second_elements
        result["replicatedElementChangeAssertions"] = changed
        result["secondRunCaptures"] = {
            "host": capture_game_backbuffer(
                host_pipe,
                args.evidence_root / "screenshots" /
                    "host-second-run-earth.png",
            ),
            "client": capture_game_backbuffer(
                client_pipe,
                args.evidence_root / "screenshots" /
                    "client-second-run-air.png",
            ),
        }
        result["logCopies"] = _copy_logs(launch, args.evidence_root / "logs")
        result["ok"] = True
        return result
    finally:
        if launch is not None:
            try:
                result["cleanup"] = stop_exact_game_processes(launch)
            finally:
                _copy_logs(launch, args.evidence_root / "logs")
        _write_json(args.evidence_root / "result.json", result)


class _DirectoryRecorder:
    def __init__(self, port: int, evidence_root: Path) -> None:
        self._port = port
        self._root = evidence_root / "mock-directory"
        self._events_path = self._root / "events.jsonl"
        self._ready_path = self._root / "ready.txt"
        self._stop_path = self._root / "stop"
        self._process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        self._root.mkdir(parents=True, exist_ok=False)
        script_path = ROOT / "tools" / "windows_lobby_directory_mock.py"
        self._process = subprocess.Popen(
            [
                "py.exe",
                "-3",
                path_for_powershell(script_path),
                "--port",
                str(self._port),
                "--events",
                path_for_powershell(self._events_path),
                "--ready",
                path_for_powershell(self._ready_path),
                "--stop",
                path_for_powershell(self._stop_path),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if self._ready_path.is_file():
                return
            if self._process.poll() is not None:
                output = self._process.stdout.read() if self._process.stdout else ""
                raise VerifyFailure(
                    "Windows lobby-directory mock exited before readiness: "
                    f"{output}"
                )
            time.sleep(0.05)
        raise VerifyFailure("Windows lobby-directory mock did not become ready")

    def stop(self) -> None:
        if self._process is None:
            return
        self._stop_path.touch()
        try:
            self._process.wait(timeout=5.0)
        except subprocess.TimeoutExpired as error:
            raise VerifyFailure(
                "Windows lobby-directory mock did not stop after its exact "
                "task-owned stop signal"
            ) from error

    def events(self) -> list[dict[str, Any]]:
        if not self._events_path.is_file():
            return []
        events: list[dict[str, Any]] = []
        for line in self._events_path.read_text(encoding="utf-8").splitlines():
            if line:
                events.append(json.loads(line))
        return events

    def wait_for_phase(
        self,
        phase: str,
        *,
        since_index: int = 0,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for event in self.events()[since_index:]:
                game = event.get("body", {}).get("game", {})
                if event["method"] == "POST" and game.get("phase") == phase:
                    return event
            time.sleep(0.05)
        raise VerifyFailure(
            f"directory mock did not receive phase {phase!r}: {self.events()}"
        )

    def wait_for_delete(self, *, timeout: float = 15.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for event in self.events():
                if event["method"] == "DELETE":
                    return event
            time.sleep(0.05)
        raise VerifyFailure(
            f"directory mock did not receive a delist: {self.events()}"
        )


def run_announce_lifecycle(args: argparse.Namespace) -> dict[str, Any]:
    actual_sha = _validate_run_arguments(args)
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "ok": False,
        "mode": "announce-lifecycle",
        "sourceSha": actual_sha,
        "instancePrefix": args.instance_prefix,
        "ports": [args.host_port, args.client_port],
        "directoryPort": args.directory_port,
        "productionTouched": False,
        "audioDisabledRequired": True,
    }
    launch: dict[str, object] | None = None
    owned_process_ids: list[int] = []
    recorder = _DirectoryRecorder(args.directory_port, args.evidence_root)
    recorder.start()
    try:
        directory_url = f"http://127.0.0.1:{args.directory_port}"
        launch = _launch_manual_pair(args, directory_url=directory_url)
        owned_process_ids = [
            identity.process_id
            for identity in register_owned_launch(launch)
        ]
        result["launch"] = launch
        host_pipe = str(launch["hostLuaPipe"])
        client_pipe = str(launch["clientLuaPipe"])
        result["initialCreate"] = {
            "host": wait_for_create(host_pipe),
            "client": wait_for_create(client_pipe),
        }
        initial = recorder.wait_for_phase("picking-loadout")
        first_post = next(
            event
            for event in recorder.events()
            if event["method"] == "POST"
            and event["path"] == "/api/lobbies/announce"
        )
        if first_post != initial:
            raise VerifyFailure(
                "the first directory publish was not Picking Loadout: "
                f"{recorder.events()}"
            )
        if initial["body"]["game"].get("statusText") != "Picking Loadout":
            raise VerifyFailure(
                f"initial directory status text was wrong: {initial}"
            )
        result["initialPickingAnnounce"] = initial
        result["hostStillPickingAtInitialAnnounce"] = query_loadout_state(
            host_pipe
        )
        result["picks"] = {
            "host": choose_create(
                host_pipe,
                element="fire",
                discipline="mind",
            ),
            "client": choose_create(
                client_pipe,
                element="water",
                discipline="body",
            ),
        }
        wait_for_scene(host_pipe, "hub", 45.0)
        wait_for_scene(client_pipe, "hub", 45.0)
        result["hubAnnounce"] = recorder.wait_for_phase("hub")
        start_testrun_when_ready(host_pipe)
        result["run"] = wait_for_run_convergence(
            host_pipe,
            client_pipe,
            start_wave=False,
            require_wave=False,
        )
        result["inMatchAnnounce"] = recorder.wait_for_phase("session")
        post_match_event_index = len(recorder.events())
        result["gameOverTransition"] = _terminal_two_peer_game_over(
            host_pipe,
            client_pipe,
        )
        result["postGameOverPickingAnnounce"] = recorder.wait_for_phase(
            "picking-loadout",
            since_index=post_match_event_index,
        )
        leave_result = lua(
            host_pipe,
            "local r=sd.__session_leave();"
            "return r.ok and '1' or '0',r.error or ''",
            timeout=8.0,
        )
        result["leaveRequestResult"] = leave_result
        result["delist"] = recorder.wait_for_delete()
        result["directoryEvents"] = recorder.events()
        result["logCopies"] = _copy_logs(launch, args.evidence_root / "logs")
        result["ok"] = True
        return result
    finally:
        if launch is not None:
            try:
                result["cleanup"] = (
                    stop_game_processes(owned_process_ids)
                    if owned_process_ids
                    else stop_exact_game_processes(launch)
                )
            finally:
                _copy_logs(launch, args.evidence_root / "logs")
        result["directoryEvents"] = recorder.events()
        recorder.stop()
        _write_json(args.evidence_root / "result.json", result)


def _copy_logs(launch: dict[str, object], destination: Path) -> dict[str, str]:
    copied: dict[str, str] = {}
    destination.mkdir(parents=True, exist_ok=True)
    for role in ("host", "client"):
        source_value = str(launch[f"{role}Log"])
        source = _path_for_local_python(source_value)
        target = destination / f"{role}-solomondarkmodloader.log"
        if source.is_file():
            shutil.copy2(source, target)
            copied[role] = str(target)
    return copied


def run_baseline(args: argparse.Namespace) -> dict[str, Any]:
    if not re.fullmatch(r"ldt[A-Za-z0-9._-]{0,44}", args.instance_prefix):
        raise VerifyFailure("instance prefix must begin with 'ldt'")
    actual_sha = _git_sha()
    if actual_sha != args.expected_sha:
        raise VerifyFailure(
            f"source SHA changed: expected={args.expected_sha} actual={actual_sha}"
        )
    if args.evidence_root.exists():
        raise VerifyFailure(f"evidence root must be new: {args.evidence_root}")
    if args.runtime_root.exists():
        raise VerifyFailure(f"runtime root must be new: {args.runtime_root}")

    args.evidence_root.mkdir(parents=True, exist_ok=False)
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "ok": False,
        "mode": "baseline-client-first",
        "sourceSha": actual_sha,
        "instancePrefix": args.instance_prefix,
        "ports": [args.host_port, args.client_port],
        "audioDisabledRequired": True,
    }
    launch: dict[str, object] | None = None
    try:
        launch = launch_pair(
            host_preset="pair_manual",
            client_preset="pair_manual",
            temporary_host_profile=True,
            fresh_install=False,
            god_mode=False,
            tile_windows=True,
            allow_focus_steal=False,
            kill_existing=False,
            instance_prefix=args.instance_prefix,
            host_port=args.host_port,
            client_port=args.client_port,
            game_directory=args.game_directory,
            launcher_path=args.launcher,
            runtime_root=args.runtime_root,
            exact_mod_id="sample.lua.ui_sandbox_lab",
            quick_start=True,
            no_lua_automation=False,
            enable_audio=False,
        )
        result["launch"] = launch
        if launch.get("audioDisabled") is not True:
            raise VerifyFailure(f"baseline pair did not disable audio: {launch}")
        host_pipe = str(launch["hostLuaPipe"])
        client_pipe = str(launch["clientLuaPipe"])
        result["initialCreate"] = {
            "host": wait_for_create(host_pipe),
            "client": wait_for_create(client_pipe),
        }

        result["clientPickActions"] = choose_create(
            client_pipe,
            element="water",
            discipline="body",
        )
        result["clientAfterPick"] = wait_until_not_create(client_pipe)
        time.sleep(2.0)
        result["clientFirstObservation"] = {
            "host": query_loadout_state(host_pipe),
            "client": query_loadout_state(client_pipe),
            "hostSession": query_session_state(host_pipe),
            "clientSession": query_session_state(client_pipe),
        }
        if result["clientFirstObservation"]["host"].get("surface") != "create":
            raise VerifyFailure("host Create surface closed before the host picked")
        result["clientFirstCaptures"] = {
            "host": capture_game_backbuffer(
                host_pipe,
                args.evidence_root / "screenshots" / "host-still-picking.png",
            ),
            "client": capture_game_backbuffer(
                client_pipe,
                args.evidence_root / "screenshots" / "client-after-pick.png",
            ),
        }

        result["hostPickActions"] = choose_create(
            host_pipe,
            element="fire",
            discipline="mind",
        )
        wait_for_scene(host_pipe, "hub", 45.0)
        wait_for_scene(client_pipe, "hub", 45.0)
        result["converged"] = {
            "hostObservesClient": wait_for_remote(
                host_pipe,
                0x2000000000001002,
                "Client Player",
                "hub",
                45.0,
            ),
            "clientObservesHost": wait_for_remote(
                client_pipe,
                0x2000000000001001,
                "Host Player",
                "hub",
                45.0,
            ),
            "host": query_loadout_state(host_pipe),
            "client": query_loadout_state(client_pipe),
        }
        result["convergedCaptures"] = {
            "host": capture_game_backbuffer(
                host_pipe,
                args.evidence_root / "screenshots" / "host-converged-hub.png",
            ),
            "client": capture_game_backbuffer(
                client_pipe,
                args.evidence_root / "screenshots" / "client-converged-hub.png",
            ),
        }
        result["logCopies"] = _copy_logs(
            launch,
            args.evidence_root / "logs",
        )
        result["ok"] = True
        return result
    finally:
        if launch is not None:
            try:
                result["cleanup"] = stop_exact_game_processes(launch)
            finally:
                _copy_logs(launch, args.evidence_root / "logs")
        _write_json(args.evidence_root / "result.json", result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=(
            "baseline-client-first",
            "client-first",
            "host-first-trickle",
            "game-over-repick",
            "announce-lifecycle",
        ),
        default="baseline-client-first",
    )
    parser.add_argument("--instance-prefix", required=True)
    parser.add_argument("--host-port", type=int, required=True)
    parser.add_argument("--client-port", type=int, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--game-directory", type=Path)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--directory-port", type=int, default=51713)
    args = parser.parse_args()
    try:
        runners = {
            "baseline-client-first": run_baseline,
            "client-first": run_client_first,
            "host-first-trickle": run_host_first_trickle,
            "game-over-repick": run_game_over_repick,
            "announce-lifecycle": run_announce_lifecycle,
        }
        result = runners[args.mode](args)
    except (OSError, ValueError, VerifyFailure) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
