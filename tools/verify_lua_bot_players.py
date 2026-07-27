#!/usr/bin/env python3
"""Live acceptance for host-owned synthetic multiplayer participants."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import multiplayer_frame_capture
import verify_local_multiplayer_sync as local_sync


ROOT = Path(__file__).resolve().parents[1]
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
EVIDENCE_ROOT = Path(
    "/mnt/d/codex-evidence/bot-players-20260726"
)
INSTANCE_PREFIX = "bot"
HOST_PORT = 48811
CLIENT_PORT = 48812
HOST_PIPE = "SolomonDarkModLoader_LuaExec_bot-host"
CLIENT_PIPE = "SolomonDarkModLoader_LuaExec_bot-client"
BOT_NAME = "Ember"
BOT_CLASS = "fire"
EXACT_MOD_ID = "sample.lua.ui_sandbox_lab"


class BotAcceptanceFailure(RuntimeError):
    pass


def _number(values: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(values.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def _integer(values: dict[str, str], key: str, default: int = 0) -> int:
    return int(_number(values, key, float(default)))


def _bot_probe(participant_id: int) -> str:
    return f"""
local participant_id = {participant_id}
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local scene = sd.world.get_scene()
emit("scene", scene and (scene.name or scene.kind) or "")
local bot = sd.bots.get_participant_state(participant_id)
emit("bot.available", bot ~= nil and bot.available)
emit("bot.id", bot and bot.id or 0)
emit("bot.name", bot and bot.name or "")
emit("bot.kind", bot and bot.participant_kind or "")
emit("bot.controller", bot and bot.controller_kind or "")
emit("bot.materialized", bot ~= nil and bot.entity_materialized)
emit("bot.transform", bot ~= nil and bot.transform_valid)
emit("bot.actor", bot and bot.actor_address or 0)
emit("bot.slot", bot and bot.gameplay_slot or -1)
emit("bot.x", bot and bot.x or 0)
emit("bot.y", bot and bot.y or 0)
emit("bot.hp", bot and bot.hp or 0)
emit("bot.max_hp", bot and bot.max_hp or 0)
local nameplate = bot and bot.actor_address and
  sd.bots.get_nameplate(bot.actor_address) or nil
emit("bot.nameplate", nameplate and nameplate.name or "")

local remote_count = 0
local materialized_count = 0
local slot_mask = 0
for _, candidate in ipairs(sd.bots.get_participants() or {{}}) do
  remote_count = remote_count + 1
  if candidate.entity_materialized then
    materialized_count = materialized_count + 1
  end
  local slot = tonumber(candidate.gameplay_slot) or -1
  if slot >= 1 and slot <= 3 then
    slot_mask = slot_mask + 2 ^ slot
  end
end
emit("remote.count", remote_count)
emit("remote.materialized_count", materialized_count)
emit("remote.slot_mask", slot_mask)

local state = sd.runtime.get_multiplayer_state()
local member = nil
for _, candidate in ipairs(state and state.participants or {{}}) do
  if tonumber(candidate.participant_id) == participant_id then
    member = candidate
    break
  end
end
emit("member.found", member ~= nil)
emit("member.name", member and member.name or "")
emit("member.kind", member and member.participant_kind or "")
emit("member.controller", member and member.controller_kind or "")
emit("member.ready", member ~= nil and member.ready)
emit("member.connected", member ~= nil and member.transport_connected)
emit("member.runtime_valid", member ~= nil and member.runtime_valid)
emit("member.in_run", member ~= nil and member.in_run)
emit("member.run_nonce", member and member.run_nonce or 0)
"""


def _enemy_target_probe(participant_id: int) -> str:
    return f"""
local participant_id = {participant_id}
local snapshot = sd.world.get_replicated_actors()
local live = 0
local targeted = 0
local first_id = 0
for _, actor in ipairs(snapshot and snapshot.actors or {{}}) do
  if not actor.dead and (tonumber(actor.hp) or 0) > 0.05 then
    live = live + 1
    if tonumber(actor.target_participant_id) == participant_id then
      targeted = targeted + 1
      if first_id == 0 then
        first_id = tonumber(actor.network_actor_id) or 0
      end
    end
  end
end
print("authority=" .. tostring(sd.state.is_authority()))
print("live=" .. tostring(live))
print("targeted=" .. tostring(targeted))
print("first_id=" .. tostring(first_id))
"""


def _wait(
    probe,
    predicate,
    *,
    timeout: float,
    label: str,
    interval: float = 0.25,
):
    deadline = time.monotonic() + timeout
    last: Any = None
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = probe()
            last_error = ""
            if predicate(last):
                return last
        except (
            BotAcceptanceFailure,
            local_sync.VerifyFailure,
            TimeoutError,
        ) as exc:
            last_error = str(exc)
        time.sleep(interval)
    detail = f" last={last!r}"
    if last_error:
        detail += f" error={last_error}"
    raise BotAcceptanceFailure(f"{label} timed out.{detail}")


def _query_bot(pipe_name: str, participant_id: int) -> dict[str, str]:
    return local_sync.parse_key_values(
        local_sync.lua(
            pipe_name,
            _bot_probe(participant_id),
            timeout=7.5,
        )
    )


def _bot_is_materialized(values: dict[str, str], scene: str) -> bool:
    slot = _integer(values, "bot.slot", -1)
    return (
        values.get("scene") == scene
        and values.get("bot.available") == "true"
        and values.get("bot.name") == BOT_NAME
        and values.get("bot.kind") == "RemoteParticipant"
        and values.get("bot.controller") == "LuaBrain"
        and values.get("bot.materialized") == "true"
        and values.get("bot.transform") == "true"
        and _integer(values, "bot.actor") > 0
        and 1 <= slot <= 3
        and values.get("bot.nameplate") == BOT_NAME
        and _number(values, "bot.hp") > 0.0
        and _number(values, "bot.max_hp") > 0.0
        and _integer(values, "remote.count") == 2
        and _integer(values, "remote.materialized_count") == 2
        and values.get("member.found") == "true"
        and values.get("member.name") == BOT_NAME
        and values.get("member.controller") == "LuaBrain"
        and values.get("member.ready") == "true"
        and values.get("member.connected") == "true"
        and values.get("member.runtime_valid") == "true"
    )


def _start_testrun() -> None:
    last_error = ""
    for _ in range(60):
        try:
            local_sync.start_testrun(HOST_PIPE)
            return
        except local_sync.VerifyFailure as exc:
            last_error = str(exc)
            if "still settling" not in last_error:
                raise
            time.sleep(0.25)
    raise BotAcceptanceFailure(
        f"host could not enter the test run: {last_error}"
    )


def _wait_for_enemy_target(
    pipe_name: str,
    participant_id: int,
    *,
    expected_authority: bool,
    timeout: float = 25.0,
) -> dict[str, str]:
    expected = "true" if expected_authority else "false"
    return _wait(
        lambda: local_sync.parse_key_values(
            local_sync.lua(
                pipe_name,
                _enemy_target_probe(participant_id),
                timeout=7.5,
            )
        ),
        lambda values: (
            values.get("authority") == expected
            and _integer(values, "live") > 0
            and _integer(values, "targeted") > 0
            and _integer(values, "first_id") > 0
        ),
        timeout=timeout,
        label=f"native enemy targeting on {pipe_name}",
    )


def _wait_for_target_identity(
    pipe_name: str,
    participant_id: int,
    network_actor_id: int,
    *,
    timeout: float = 10.0,
) -> dict[str, str]:
    code = f"""
local participant_id = {participant_id}
local network_actor_id = {network_actor_id}
local snapshot = sd.world.get_replicated_actors()
local found = false
local target = 0
local dead = false
for _, actor in ipairs(snapshot and snapshot.actors or {{}}) do
  if tonumber(actor.network_actor_id) == network_actor_id then
    found = true
    target = tonumber(actor.target_participant_id) or 0
    dead = actor.dead == true
    break
  end
end
print("found=" .. tostring(found))
print("target=" .. tostring(target))
print("dead=" .. tostring(dead))
"""
    return _wait(
        lambda: local_sync.parse_key_values(
            local_sync.lua(pipe_name, code, timeout=7.5)
        ),
        lambda values: (
            values.get("found") == "true"
            and values.get("dead") == "false"
            and _integer(values, "target") == participant_id
        ),
        timeout=timeout,
        label=f"enemy target identity {network_actor_id} on {pipe_name}",
    )


def _wait_for_despawn(pipe_name: str, participant_id: int) -> dict[str, str]:
    code = f"""
local participant_id = {participant_id}
local found = false
for _, candidate in ipairs(sd.bots.get_participants() or {{}}) do
  if tonumber(candidate.id) == participant_id then
    found = true
    break
  end
end
local member = false
local state = sd.runtime.get_multiplayer_state()
for _, candidate in ipairs(state and state.participants or {{}}) do
  if tonumber(candidate.participant_id) == participant_id then
    member = true
    break
  end
end
local snapshot = sd.bots.get_participant_state(participant_id)
print("found=" .. tostring(found))
print("member=" .. tostring(member))
print("available=" .. tostring(snapshot ~= nil and snapshot.available))
"""
    return _wait(
        lambda: local_sync.parse_key_values(
            local_sync.lua(pipe_name, code, timeout=7.5)
        ),
        lambda values: (
            values.get("found") == "false"
            and values.get("member") == "false"
            and values.get("available") == "false"
        ),
        timeout=12.0,
        label=f"synthetic participant retirement on {pipe_name}",
    )


def _copy_runtime_evidence(
    launch: dict[str, object],
    output_directory: Path,
) -> dict[str, str]:
    copied: dict[str, str] = {}
    for role in ("host", "client"):
        executable = launch.get(f"{role}ExecutablePath")
        if not isinstance(executable, str) or not executable:
            continue
        stage_path = (
            ROOT
            / "runtime"
            / "instances"
            / f"{INSTANCE_PREFIX}-{role}"
            / "stage"
        )
        for relative, label in (
            (
                Path(".sdmod/logs/solomondarkmodloader.log"),
                f"{role}-solomondarkmodloader.log",
            ),
            (
                Path(".sdmod/startup-status.json"),
                f"{role}-startup-status.json",
            ),
            (
                Path(".sdmod/multiplayer-session-status.json"),
                f"{role}-multiplayer-session-status.json",
            ),
        ):
            source = stage_path / relative
            if not source.is_file():
                continue
            destination = output_directory / label
            shutil.copy2(source, destination)
            copied[label] = str(destination)
    return copied


def verify_lifecycle(
    *,
    game_directory: Path,
    evidence_directory: Path,
    launcher_path: Path,
) -> dict[str, Any]:
    evidence_directory.mkdir(parents=True, exist_ok=True)
    launch: dict[str, object] = {}
    result: dict[str, Any] = {
        "phase": "participant_lifecycle",
        "instancePrefix": INSTANCE_PREFIX,
        "ports": {"host": HOST_PORT, "client": CLIENT_PORT},
        "audioExpectedDisabled": True,
    }
    failure: BaseException | None = None
    try:
        launch = local_sync.launch_pair(
            instance_prefix=INSTANCE_PREFIX,
            host_port=HOST_PORT,
            client_port=CLIENT_PORT,
            temporary_host_profile=True,
            kill_existing=False,
            god_mode=True,
            exact_mod_id=EXACT_MOD_ID,
            launcher_path=launcher_path,
            game_directory=game_directory,
            enable_audio=False,
        )
        result["launch"] = launch
        if launch.get("audioDisabled") is not True:
            raise BotAcceptanceFailure(
                f"pair did not launch with audio disabled: {launch}"
            )
        if (
            int(launch.get("hostPort", 0)) != HOST_PORT
            or int(launch.get("clientPort", 0)) != CLIENT_PORT
        ):
            raise BotAcceptanceFailure(
                f"pair launched on unexpected ports: {launch}"
            )

        time.sleep(2.0)
        spawn = local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
                f"""
_G.bot_acceptance = assert(
  sd.bots.spawn{{name={json.dumps(BOT_NAME)}, class={json.dumps(BOT_CLASS)}}})
print("participant_id=" ..
  tostring(_G.bot_acceptance:participant_id()))
""",
                timeout=10.0,
            )
        )
        participant_id = _integer(spawn, "participant_id")
        if participant_id <= 0:
            raise BotAcceptanceFailure(
                f"spawn did not return a participant handle: {spawn}"
            )
        result["spawn"] = {
            "name": BOT_NAME,
            "class": BOT_CLASS,
            "participantId": participant_id,
        }

        hub_host = _wait(
            lambda: _query_bot(HOST_PIPE, participant_id),
            lambda values: _bot_is_materialized(values, "hub"),
            timeout=15.0,
            label="host hub synthetic participant",
        )
        hub_client = _wait(
            lambda: _query_bot(CLIENT_PIPE, participant_id),
            lambda values: _bot_is_materialized(values, "hub"),
            timeout=15.0,
            label="client hub synthetic participant",
        )
        result["hub"] = {
            "host": hub_host,
            "client": hub_client,
        }

        _start_testrun()
        local_sync.wait_for_scene(HOST_PIPE, "testrun", timeout=45.0)
        local_sync.wait_for_scene(CLIENT_PIPE, "testrun", timeout=45.0)
        run_host = _wait(
            lambda: _query_bot(HOST_PIPE, participant_id),
            lambda values: _bot_is_materialized(values, "testrun"),
            timeout=20.0,
            label="host run synthetic participant",
        )
        run_client = _wait(
            lambda: _query_bot(CLIENT_PIPE, participant_id),
            lambda values: _bot_is_materialized(values, "testrun"),
            timeout=20.0,
            label="client run synthetic participant",
        )
        result["run"] = {
            "host": run_host,
            "client": run_client,
            "slotPolicy": (
                "peer-local stock slot allocation; each synthetic avatar "
                "occupies one ordinary remote slot in 1..3"
            ),
        }

        wave_start = local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
                """
print("prelude=" ..
  tostring(sd.gameplay.enable_combat_prelude()))
print("waves=" .. tostring(sd.gameplay.start_waves()))
""",
                timeout=10.0,
            )
        )
        if (
            wave_start.get("prelude") != "true"
            or wave_start.get("waves") != "true"
        ):
            raise BotAcceptanceFailure(
                f"stock waves did not start: {wave_start}"
            )
        host_target = _wait_for_enemy_target(
            HOST_PIPE,
            participant_id,
            expected_authority=True,
        )
        target_network_actor_id = _integer(
            host_target,
            "first_id",
        )
        client_target = _wait_for_target_identity(
            CLIENT_PIPE,
            participant_id,
            target_network_actor_id,
        )
        result["nativeTargeting"] = {
            "host": host_target,
            "client": client_target,
            "networkActorId": target_network_actor_id,
        }

        screenshots = {
            "host": multiplayer_frame_capture.capture_game_backbuffer(
                HOST_PIPE,
                evidence_directory / "host-bot-mid-fight.png",
            ),
            "client": multiplayer_frame_capture.capture_game_backbuffer(
                CLIENT_PIPE,
                evidence_directory / "client-bot-mid-fight.png",
            ),
        }
        result["screenshots"] = screenshots

        despawn = local_sync.parse_key_values(
            local_sync.lua(
                HOST_PIPE,
                """
local ok, err = _G.bot_acceptance:despawn()
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
""",
                timeout=10.0,
            )
        )
        if despawn.get("ok") != "true":
            raise BotAcceptanceFailure(
                f"host bot handle did not despawn cleanly: {despawn}"
            )
        result["despawn"] = {
            "request": despawn,
            "host": _wait_for_despawn(
                HOST_PIPE,
                participant_id,
            ),
            "client": _wait_for_despawn(
                CLIENT_PIPE,
                participant_id,
            ),
        }
        result["success"] = True
    except BaseException as exc:
        result["success"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        failure = exc
    finally:
        if launch:
            try:
                result["runtimeEvidence"] = _copy_runtime_evidence(
                    launch,
                    evidence_directory,
                )
            except BaseException as copy_error:
                result["evidenceCopyError"] = (
                    f"{type(copy_error).__name__}: {copy_error}"
                )
            try:
                result["cleanup"] = (
                    local_sync.stop_exact_game_processes(launch)
                )
            except BaseException as cleanup_error:
                result["cleanupError"] = (
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )
                if failure is None:
                    failure = cleanup_error
                    result["success"] = False

        result_path = evidence_directory / "result.json"
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        print(f"RESULT={result_path}")

    if failure is not None:
        raise failure
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=GAME_DIRECTORY,
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=EVIDENCE_ROOT / "phase1",
    )
    parser.add_argument(
        "--launcher",
        type=Path,
        default=ROOT / "dist/launcher/SolomonDarkModLauncher.exe",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not (args.game_dir / "SolomonDark.exe").is_file():
        raise SystemExit(
            f"source game directory is invalid: {args.game_dir}"
        )
    if not args.launcher.is_file():
        raise SystemExit(f"launcher does not exist: {args.launcher}")
    verify_lifecycle(
        game_directory=args.game_dir.resolve(),
        evidence_directory=args.evidence_dir.resolve(),
        launcher_path=args.launcher.resolve(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
