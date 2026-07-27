#!/usr/bin/env python3
"""Force and verify remote primary-projectile snapshot materialization."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import multiplayer_frame_capture as frame_capture
import verify_local_multiplayer_sync as local_sync
import verify_multiplayer_replicated_audio_events as audio


ROOT = Path(__file__).resolve().parents[1]
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
BOULDER_TYPE_ID = 0x7D5
CLIENT_ID = local_sync.CLIENT_ID
CLIENT_NAME = local_sync.CLIENT_NAME


def values(pipe_name: str, code: str, *, timeout: float = 8.0) -> dict[str, str]:
    return local_sync.parse_key_values(
        local_sync.lua(pipe_name, code, timeout=timeout)
    )


def configure_endpoints(host_pipe: str, client_pipe: str) -> None:
    local_sync.HOST_PIPE = host_pipe
    local_sync.CLIENT_PIPE = client_pipe


def wait_for_run(host_pipe: str, client_pipe: str) -> dict[str, object]:
    local_sync.wait_for_remote(
        host_pipe,
        CLIENT_ID,
        CLIENT_NAME,
        "hub",
    )
    local_sync.wait_for_remote(
        client_pipe,
        local_sync.HOST_ID,
        local_sync.HOST_NAME,
        "hub",
    )
    local_sync.start_host_testrun_and_wait_for_clients(timeout=45.0)
    local_sync.wait_for_remote(
        host_pipe,
        CLIENT_ID,
        CLIENT_NAME,
        "testrun",
    )
    local_sync.wait_for_remote(
        client_pipe,
        local_sync.HOST_ID,
        local_sync.HOST_NAME,
        "testrun",
    )
    for pipe_name in (host_pipe, client_pipe):
        result = values(
            pipe_name,
            "lua_bots_disable_tick=true; sd.bots.clear(); "
            "print('count=' .. tostring(sd.bots.get_count()))",
        )
        if result.get("count") != "0":
            raise local_sync.VerifyFailure(
                f"failed to disable companion bots on {pipe_name}: {result}"
            )
    local_sync.hold_player_heading(host_pipe, 90.0)
    local_sync.hold_player_heading(client_pipe, 90.0)
    host_place = local_sync.place_player(host_pipe, 1600.0, 1800.0, 90.0)
    client_place = local_sync.place_player(
        client_pipe,
        1664.0,
        1800.0,
        90.0,
    )
    time.sleep(1.0)
    return {
        "host_place": host_place,
        "client_place": client_place,
    }


def queue_client_boulder(client_pipe: str, frames: int) -> dict[str, str]:
    result = values(
        client_pipe,
        f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local player = sd.player.get_state()
if player == nil or tonumber(player.actor_address) == 0 then
  error("client player actor unavailable")
end
local actor = tonumber(player.actor_address)
local ox = sd.debug.layout_offset("actor_position_x")
local oy = sd.debug.layout_offset("actor_position_y")
local oh = sd.debug.layout_offset("actor_heading")
local oaimx = sd.debug.layout_offset("actor_aim_target_x")
local oaimy = sd.debug.layout_offset("actor_aim_target_y")
local x = sd.debug.read_float(actor + ox)
local y = sd.debug.read_float(actor + oy)
emit("heading", sd.debug.write_float(actor + oh, 90.0))
emit("aim_x", sd.debug.write_float(actor + oaimx, x + 320.0))
emit("aim_y", sd.debug.write_float(actor + oaimy, y))
emit("queued", sd.input.hold_mouse_left_frames({frames}))
""",
    )
    if any(result.get(key) != "true" for key in ("heading", "aim_x", "aim_y", "queued")):
        raise local_sync.VerifyFailure(
            f"failed to queue client Earth cast: {result}"
        )
    return result


def query_boulder_binding(host_pipe: str) -> dict[str, str]:
    return values(
        host_pipe,
        f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local state = sd.world.get_replicated_spell_effects()
local apply = state and state.apply or {{}}
emit("cumulative_primary_create_count",
     apply.cumulative_primary_create_count or 0)
emit("cumulative_primary_transfer_count",
     apply.cumulative_primary_transfer_count or 0)
emit("found", false)
for _, binding in ipairs(apply.bindings or {{}}) do
  if tonumber(binding.owner_participant_id) == {CLIENT_ID}
     and tonumber(binding.native_type_id) == {BOULDER_TYPE_ID}
     and binding.active == true
     and binding.terminal ~= true then
    emit("found", true)
    emit("effect_serial", binding.effect_serial or 0)
    emit("actor_address", binding.local_actor_address or 0)
    emit("actor_slot", binding.local_actor_slot or -1)
    emit("snapshot_materialized",
         binding.snapshot_materialized == true)
    emit("position_error", binding.position_error or -1)
    break
  end
end
""",
    )


def wait_for_boulder_binding(
    host_pipe: str,
    *,
    snapshot_materialized: bool | None,
    excluded_address: int = 0,
    timeout: float = 8.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    expected = (
        None
        if snapshot_materialized is None
        else ("true" if snapshot_materialized else "false")
    )
    while time.monotonic() < deadline:
        last = query_boulder_binding(host_pipe)
        address = int(float(last.get("actor_address", "0") or "0"))
        if (
            last.get("found") == "true"
            and (
                expected is None
                or last.get("snapshot_materialized") == expected
            )
            and address != 0
            and address != excluded_address
        ):
            return last
        time.sleep(0.02)
    raise local_sync.VerifyFailure(
        "remote Boulder binding did not reach expected materialization "
        f"state={expected or 'either'}; last={last}"
    )


def retire_bound_boulder(
    host_pipe: str,
    expected_address: int,
) -> dict[str, str]:
    result = values(
        host_pipe,
        f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local address = {expected_address}
local pending = sd.debug.layout_offset("actor_pending_remove")
emit("address", address)
emit("pending_offset", pending or 0)
emit("write", sd.debug.write_u8(address + pending, 1))
emit("pending_after", sd.debug.read_u8(address + pending) or 0)
""",
    )
    if result.get("write") != "true" or result.get("pending_after") != "1":
        raise local_sync.VerifyFailure(
            f"failed to retire natural remote Boulder: {result}"
        )
    return result


def clear_client_cast(client_pipe: str) -> dict[str, str]:
    result = values(
        client_pipe,
        "print('cleared=' .. tostring(sd.input.clear_local_cast_state()))",
    )
    if result.get("cleared") != "true":
        raise local_sync.VerifyFailure(
            f"failed to clear client cast state: {result}"
        )
    return result


def run_trial(
    trial: int,
    *,
    host_pipe: str,
    client_pipe: str,
    evidence_root: Path,
) -> dict[str, Any]:
    before = query_boulder_binding(host_pipe)
    queued = queue_client_boulder(client_pipe, 900)
    initial = wait_for_boulder_binding(
        host_pipe,
        snapshot_materialized=None,
    )
    if initial.get("snapshot_materialized") == "true":
        natural: dict[str, str] | None = None
        retirement: dict[str, str] = {
            "required": "false",
            "reason": "native_replay_actor_missing",
        }
        fallback = initial
    else:
        natural = initial
        natural_address = int(float(natural["actor_address"]))
        retirement = retire_bound_boulder(host_pipe, natural_address)
        retirement["required"] = "true"
        fallback = wait_for_boulder_binding(
            host_pipe,
            snapshot_materialized=True,
            excluded_address=natural_address,
        )
    if (
        int(fallback.get("cumulative_primary_create_count", "0"))
        <= int(before.get("cumulative_primary_create_count", "0"))
    ):
        raise local_sync.VerifyFailure(
            "primary create counter did not advance after forced native loss: "
            f"before={before} fallback={fallback}"
        )
    time.sleep(1.0)
    trial_root = evidence_root / f"trial-{trial:02d}"
    screenshots = {
        "host": frame_capture.capture_game_backbuffer(
            host_pipe,
            trial_root / "host-observer.png",
        ),
        "client": frame_capture.capture_game_backbuffer(
            client_pipe,
            trial_root / "client-caster.png",
        ),
    }
    cleared = clear_client_cast(client_pipe)
    time.sleep(0.1)
    return {
        "trial": trial,
        "queued": queued,
        "natural": natural,
        "retirement": retirement,
        "fallback": fallback,
        "screenshots": screenshots,
        "cleared": cleared,
        "ok": True,
    }


def run_isolated_trial(
    trial: int,
    *,
    args: argparse.Namespace,
) -> dict[str, Any]:
    trial_result: dict[str, Any] = {
        "trial": trial,
        "ok": False,
    }
    expected: dict[int, Path] = {}
    try:
        pair = local_sync.launch_pair(
            host_preset="map_create_fire_mind_hub",
            client_preset="map_create_earth_mind_hub",
            tile_windows=False,
            kill_existing=False,
            instance_prefix=args.instance_prefix,
            host_port=args.host_port,
            client_port=args.client_port,
            game_directory=GAME_DIRECTORY,
            runtime_root=args.runtime_root.resolve(),
            exact_mod_id="sample.lua.ui_sandbox_lab",
            enable_audio=False,
            test_blank_boneyard=True,
            test_survival_boneyard_override=(
                ROOT
                / "tests/fixtures/boneyards/flat_multiplayer_test.boneyard"
            ),
            use_sandbox_preset_flow=True,
        )
        if pair.get("audioDisabled") is not True:
            raise local_sync.VerifyFailure(
                f"launcher did not confirm disabled audio: {pair}"
            )
        process_ids = local_sync.game_process_ids(pair)
        if len(process_ids) != 2:
            raise local_sync.VerifyFailure(
                f"launcher did not return exactly two game PIDs: {pair}"
            )
        expected = {
            int(pair["hostProcessId"]): audio.expected_executable(
                args.runtime_root,
                f"{args.instance_prefix}-host",
            ),
            int(pair["clientProcessId"]): audio.expected_executable(
                args.runtime_root,
                f"{args.instance_prefix}-client",
            ),
        }
        audio.validate_owned_processes(expected)
        host_pipe = str(pair["hostLuaPipe"])
        client_pipe = str(pair["clientLuaPipe"])
        configure_endpoints(host_pipe, client_pipe)
        trial_result["launch"] = pair
        trial_result["owned_processes"] = {
            str(process_id): str(path)
            for process_id, path in expected.items()
        }
        trial_result["run"] = wait_for_run(host_pipe, client_pipe)
        trial_result["verification"] = run_trial(
            trial,
            host_pipe=host_pipe,
            client_pipe=client_pipe,
            evidence_root=args.evidence_root.resolve(),
        )
        trial_result["ok"] = True
    except Exception as exc:
        trial_result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if expected:
            try:
                trial_result["cleanup"] = audio.stop_owned_processes(expected)
            except Exception as exc:
                trial_result["cleanup_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                trial_result["ok"] = False
    return trial_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--instance-prefix", default="sfx")
    parser.add_argument("--host-port", type=int, default=48611)
    parser.add_argument("--client-port", type=int, default=48612)
    parser.add_argument("--trials", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result: dict[str, Any] = {
        "ok": False,
        "trials": [],
        "audio_required": False,
        "instance_prefix": args.instance_prefix,
        "ports": [args.host_port, args.client_port],
    }
    try:
        for trial in range(1, args.trials + 1):
            trial_result = run_isolated_trial(trial, args=args)
            result["trials"].append(trial_result)
            if not trial_result["ok"]:
                break
        result["ok"] = (
            len(result["trials"]) == args.trials
            and all(trial["ok"] for trial in result["trials"])
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "ok": result.get("ok"),
                    "trial_count": len(result["trials"]),
                    "error": result.get("error"),
                    "output": str(args.output),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
