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

from multiplayer_frame_capture import capture_game_backbuffer
from verify_game_over_session_semantics import (
    _path_for_local_python,
    query_session_state,
)
from verify_local_multiplayer_sync import (
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
)


CREATE_ELEMENT_IDS = {
    "ether": 0,
    "fire": 1,
    "air": 2,
    "water": 3,
    "earth": 4,
}
CREATE_DISCIPLINE_IDS = {
    "mind": 0,
    "body": 1,
    "arcane": 2,
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
emit("remote_present", remote_row ~= nil)
emit("remote_runtime_valid", remote_row and remote_row.runtime_valid or false)
emit("remote_scene_kind", remote_row and remote_row.scene_kind or "")
emit("remote_run_nonce", remote_row and remote_row.run_nonce or 0)
emit("loading_active", loading and loading.active or false)
emit("loading_flow", loading and loading.flow or 0)
emit("loading_stage", loading and loading.stage or 0)
emit("loading_progress", loading and loading.progress or 0)
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
        choices=("baseline-client-first",),
        default="baseline-client-first",
    )
    parser.add_argument("--instance-prefix", required=True)
    parser.add_argument("--host-port", type=int, required=True)
    parser.add_argument("--client-port", type=int, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--game-directory", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_baseline(args)
    except (OSError, ValueError, VerifyFailure) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
