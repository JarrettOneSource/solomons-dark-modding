#!/usr/bin/env python3
"""Loopback acceptance for manifest-backed Lua mod settings."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import verify_local_multiplayer_sync as local_sync


ROOT = Path(__file__).resolve().parents[1]
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
FORBIDDEN_OWNER_INSTALL = Path(
    "/mnt/c/Users/User/Downloads/"
    "SolomonDarkMultiplayerBeta-v0.1.0-beta.12"
)
EVIDENCE_ROOT = Path(
    "/mnt/d/codex-evidence/mod-settings-20260727"
)
INSTANCE_PREFIX = "mset"
HOST_PORT = 49011
CLIENT_PORT = 49012
HOST_PIPE = "SolomonDarkModLoader_LuaExec_mset-host"
CLIENT_PIPE = "SolomonDarkModLoader_LuaExec_mset-client"
EXACT_MOD_ID = "bot.brain"
INITIAL_KITE_RADIUS = 100
RELOADED_KITE_RADIUS = 900
INITIAL_PERSONA = "MsetBot"
RESTART_PERSONA = "RestartedBot"


class ModSettingsLifecycleFailure(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stage_root(role: str) -> Path:
    return (
        ROOT
        / "runtime"
        / "instances"
        / f"{INSTANCE_PREFIX}-{role}"
        / "stage"
    )


def _settings_path(role: str) -> Path:
    return (
        _stage_root(role)
        / ".sdmod"
        / "mod-settings"
        / f"{EXACT_MOD_ID}.json"
    )


def _atomic_write_settings(
    role: str,
    values: dict[str, object],
) -> Path:
    """Write a verifier fixture with the launcher's temp-and-rename contract."""
    path = _settings_path(role)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    )
    payload = {"schemaVersion": 1, "values": values}
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _seed_persisted_values(evidence_dir: Path) -> None:
    host_values: dict[str, object] = {
        "kite_radius": INITIAL_KITE_RADIUS,
        "offense_enabled": False,
        "persona_name": INITIAL_PERSONA,
        "think_profile": "standard",
        "focus_bot_key": "NONE",
    }
    client_values: dict[str, object] = {
        "kite_radius": 700,
        "offense_enabled": True,
        "persona_name": "ClientLocalBot",
        "think_profile": "relaxed",
        "focus_bot_key": "NONE",
    }
    host_path = _atomic_write_settings("host", host_values)
    client_path = _atomic_write_settings("client", client_values)
    shutil.copy2(host_path, evidence_dir / "host-settings-initial.json")
    shutil.copy2(client_path, evidence_dir / "client-settings-initial.json")


PROBE = """
local function emit(key, value)
  if value == nil then
    value = ""
  end
  print(key .. "=" .. tostring(value))
end

local scene = sd.world.get_scene()
emit("scene", scene and (scene.name or scene.kind) or "")
emit("authority", sd.state.is_authority())
for _, key in ipairs({
  "kite_radius",
  "offense_enabled",
  "persona_name",
  "think_profile",
  "focus_bot_key"
}) do
  local value, error_message = sd.settings.get(key)
  emit("setting." .. key, value)
  emit("setting_error." .. key, error_message or "")
end

local bots = sd.bots.list() or {}
local bot = bots[1]
local participant_id = bot and tonumber(bot:participant_id()) or 0
emit("bot.count", #bots)
emit("bot.participant_id", participant_id)
if bot ~= nil then
  local ok, x, y = pcall(function() return bot:position() end)
  emit("bot.position_ok", ok and x ~= nil and y ~= nil)
  emit("bot.x", x or 0)
  emit("bot.y", y or 0)
end

local multiplayer = sd.runtime.get_multiplayer_state()
local bot_member = nil
for _, participant in ipairs(multiplayer and multiplayer.participants or {}) do
  if tonumber(participant.participant_id) == participant_id then
    bot_member = participant
  end
end
emit("bot.name", bot_member and bot_member.name or "")
emit(
  "bot.controller",
  bot_member and bot_member.controller_kind or "")

local debug_state = rawget(_G, "bot_brain_debug")
for _, key in ipairs({
  "active",
  "mode",
  "live_enemy_count",
  "threat_count",
  "nearest_enemy_distance",
  "kite_radius",
  "offense_enabled",
  "think_profile",
  "persona_name",
  "settings_change_count",
  "last_settings_change_key",
  "respawn_action_count"
}) do
  local value = ""
  if type(debug_state) == "table" then
    value = debug_state[key]
  end
  emit("brain." .. key, value)
end
"""


def _query(pipe_name: str) -> dict[str, str]:
    return local_sync.parse_key_values(
        local_sync.lua(pipe_name, PROBE, timeout=10.0)
    )


def _number(
    values: dict[str, str],
    key: str,
    default: float = 0.0,
) -> float:
    try:
        return float(values.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def _integer(
    values: dict[str, str],
    key: str,
    default: int = 0,
) -> int:
    raw = values.get(key, str(default))
    try:
        return int(raw, 10)
    except (TypeError, ValueError):
        return int(_number(values, key, float(default)))


def _wait(
    probe: Callable[[], Any],
    predicate: Callable[[Any], bool],
    *,
    timeout: float,
    label: str,
    interval: float = 0.25,
) -> Any:
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
            local_sync.VerifyFailure,
            TimeoutError,
            ValueError,
        ) as exc:
            last_error = str(exc)
        time.sleep(interval)
    suffix = f" last={last!r}"
    if last_error:
        suffix += f" error={last_error}"
    raise ModSettingsLifecycleFailure(f"{label} timed out.{suffix}")


def _reload(pipe_name: str) -> dict[str, str]:
    code = f"""
local result = sd.__settings_reload("{EXACT_MOD_ID}")
print("ok=" .. tostring(result.ok))
print("changed=" .. table.concat(result.changed or {{}}, ","))
print("error=" .. tostring(result.error or ""))
"""
    return local_sync.parse_key_values(
        local_sync.lua(pipe_name, code, timeout=10.0)
    )


def _invoke_action(pipe_name: str) -> dict[str, str]:
    code = f"""
local result = sd.__settings_invoke_action(
  "{EXACT_MOD_ID}",
  "respawn_bot")
print("ok=" .. tostring(result.ok))
print("error=" .. tostring(result.error or ""))
"""
    return local_sync.parse_key_values(
        local_sync.lua(pipe_name, code, timeout=10.0)
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
    raise ModSettingsLifecycleFailure(
        f"host could not enter the test run: {last_error}"
    )


def _start_waves() -> dict[str, str]:
    response = local_sync.parse_key_values(
        local_sync.lua(
            HOST_PIPE,
            """
print("prelude=" ..
  tostring(sd.gameplay.enable_combat_prelude()))
print("waves=" ..
  tostring(sd.gameplay.start_waves()))
""",
            timeout=10.0,
        )
    )
    if (
        response.get("prelude") != "true"
        or response.get("waves") != "true"
    ):
        raise ModSettingsLifecycleFailure(
            f"stock waves did not start: {response}"
        )
    return response


def _initial_values_converged(
    views: dict[str, dict[str, str]],
) -> bool:
    host = views["host"]
    client = views["client"]
    participant_id = _integer(host, "bot.participant_id")
    return (
        host.get("scene") == "hub"
        and client.get("scene") == "hub"
        and host.get("authority") == "true"
        and client.get("authority") == "false"
        and _number(host, "setting.kite_radius") ==
            INITIAL_KITE_RADIUS
        and _number(client, "setting.kite_radius") ==
            INITIAL_KITE_RADIUS
        and host.get("setting.offense_enabled") == "false"
        and client.get("setting.offense_enabled") == "false"
        and host.get("setting.persona_name") == INITIAL_PERSONA
        and client.get("setting.persona_name") == INITIAL_PERSONA
        and host.get("setting.think_profile") == "standard"
        and client.get("setting.think_profile") == "relaxed"
        and host.get("brain.persona_name") == INITIAL_PERSONA
        and host.get("brain.offense_enabled") == "false"
        and _number(host, "brain.kite_radius") ==
            INITIAL_KITE_RADIUS
        and participant_id > 0
        and _integer(client, "bot.participant_id") == participant_id
        and host.get("bot.name") == INITIAL_PERSONA
        and client.get("bot.name") == INITIAL_PERSONA
        and host.get("bot.controller") == "LuaBrain"
        and client.get("bot.controller") == "LuaBrain"
    )


def _copy_runtime_evidence(evidence_dir: Path) -> dict[str, str]:
    copied: dict[str, str] = {}
    for role in ("host", "client"):
        stage = _stage_root(role)
        for relative, output_name in (
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
            (
                Path(f".sdmod/mod-settings/{EXACT_MOD_ID}.json"),
                f"{role}-settings-final.json",
            ),
        ):
            source = stage / relative
            if not source.is_file():
                continue
            destination = evidence_dir / output_name
            shutil.copy2(source, destination)
            copied[output_name] = str(destination)
    return copied


def verify_lifecycle(
    *,
    evidence_dir: Path,
    game_directory: Path,
    launcher_path: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _seed_persisted_values(evidence_dir)
    launch: dict[str, object] = {}
    result: dict[str, Any] = {
        "contract": "mod-settings-lifecycle-v1",
        "startedUtc": _utc_now(),
        "instancePrefix": INSTANCE_PREFIX,
        "ports": {"host": HOST_PORT, "client": CLIENT_PORT},
        "exactModId": EXACT_MOD_ID,
        "audioExpectedDisabled": True,
        "success": False,
    }
    failure: BaseException | None = None
    try:
        os.environ["SDMOD_ENABLE_AUDIO"] = "0"
        os.environ["SDMOD_DISABLE_AUDIO"] = "1"
        launch = local_sync.launch_pair(
            instance_prefix=INSTANCE_PREFIX,
            host_port=HOST_PORT,
            client_port=CLIENT_PORT,
            temporary_host_profile=True,
            kill_existing=False,
            god_mode=True,
            tile_windows=False,
            allow_focus_steal=False,
            exact_mod_id=EXACT_MOD_ID,
            launcher_path=launcher_path,
            game_directory=game_directory,
            runtime_root=ROOT / "runtime",
            enable_audio=False,
        )
        result["launch"] = launch
        if (
            launch.get("audioDisabled") is not True
            or int(launch.get("hostPort", 0)) != HOST_PORT
            or int(launch.get("clientPort", 0)) != CLIENT_PORT
        ):
            raise ModSettingsLifecycleFailure(
                f"isolated launch contract failed: {launch}"
            )

        initial = _wait(
            lambda: {
                "host": _query(HOST_PIPE),
                "client": _query(CLIENT_PIPE),
            },
            _initial_values_converged,
            timeout=30.0,
            label="persisted startup values and host replication",
        )
        result["initial"] = initial

        _start_testrun()
        local_sync.wait_for_scene(HOST_PIPE, "testrun", timeout=45.0)
        local_sync.wait_for_scene(CLIENT_PIPE, "testrun", timeout=45.0)
        result["waveStart"] = _start_waves()

        before = _wait(
            lambda: _query(HOST_PIPE),
            lambda values: (
                values.get("scene") == "testrun"
                and values.get("brain.active") == "true"
                and values.get("brain.mode") == "approach"
                and _integer(values, "brain.live_enemy_count") > 0
                and _integer(values, "brain.threat_count") == 0
                and INITIAL_KITE_RADIUS <
                    _number(values, "brain.nearest_enemy_distance")
                    <= RELOADED_KITE_RADIUS
                and _number(values, "brain.kite_radius") ==
                    INITIAL_KITE_RADIUS
            ),
            timeout=timeout_seconds,
            label="pre-reload kite telemetry",
        )
        result["behaviorBeforeReload"] = before
        host_change_count = _integer(
            before,
            "brain.settings_change_count",
        )
        client_before = _query(CLIENT_PIPE)
        client_change_count = _integer(
            client_before,
            "brain.settings_change_count",
        )

        reloaded_values: dict[str, object] = {
            "kite_radius": RELOADED_KITE_RADIUS,
            "offense_enabled": False,
            "persona_name": RESTART_PERSONA,
            "think_profile": "standard",
            "focus_bot_key": "NONE",
        }
        reloaded_path = _atomic_write_settings(
            "host",
            reloaded_values,
        )
        shutil.copy2(
            reloaded_path,
            evidence_dir / "host-settings-reloaded.json",
        )
        reload_result = _reload(HOST_PIPE)
        result["reload"] = reload_result
        if (
            reload_result.get("ok") != "true"
            or reload_result.get("changed") != "kite_radius"
            or reload_result.get("error", "") != ""
        ):
            raise ModSettingsLifecycleFailure(
                f"live reload returned an unexpected result: {reload_result}"
            )

        after = _wait(
            lambda: {
                "host": _query(HOST_PIPE),
                "client": _query(CLIENT_PIPE),
            },
            lambda views: (
                _number(
                    views["host"],
                    "setting.kite_radius",
                ) == RELOADED_KITE_RADIUS
                and _number(
                    views["client"],
                    "setting.kite_radius",
                ) == RELOADED_KITE_RADIUS
                and _number(
                    views["host"],
                    "brain.kite_radius",
                ) == RELOADED_KITE_RADIUS
                and _integer(
                    views["host"],
                    "brain.settings_change_count",
                ) > host_change_count
                and _integer(
                    views["client"],
                    "brain.settings_change_count",
                ) > client_change_count
                and _integer(
                    views["host"],
                    "brain.threat_count",
                ) > 0
                and 0 < _number(
                    views["host"],
                    "brain.nearest_enemy_distance",
                ) <= RELOADED_KITE_RADIUS
                and views["host"].get("setting.persona_name") ==
                    INITIAL_PERSONA
                and views["client"].get("setting.persona_name") ==
                    INITIAL_PERSONA
                and views["host"].get("brain.persona_name") ==
                    INITIAL_PERSONA
            ),
            timeout=20.0,
            label="live apply, callback, behavior delta, and replication",
        )
        result["behaviorAfterReload"] = after
        persisted_after_reload = json.loads(
            reloaded_path.read_text(encoding="utf-8")
        )
        if (
            persisted_after_reload["values"]["persona_name"]
            != RESTART_PERSONA
        ):
            raise ModSettingsLifecycleFailure(
                "requires_restart value was not persisted"
            )
        result["requiresRestart"] = {
            "persisted": RESTART_PERSONA,
            "hostEffective": after["host"]["setting.persona_name"],
            "clientEffective": after["client"]["setting.persona_name"],
            "liveChangedKeys": reload_result["changed"],
        }

        old_participant_id = _integer(
            after["host"],
            "bot.participant_id",
        )
        old_action_count = _integer(
            after["host"],
            "brain.respawn_action_count",
        )
        client_action = _invoke_action(CLIENT_PIPE)
        result["clientAction"] = client_action
        if (
            client_action.get("ok") != "false"
            or "session authority" not in
                client_action.get("error", "").lower()
        ):
            raise ModSettingsLifecycleFailure(
                f"client host action was not rejected: {client_action}"
            )

        host_action = _invoke_action(HOST_PIPE)
        result["hostAction"] = host_action
        if (
            host_action.get("ok") != "true"
            or host_action.get("error", "") != ""
        ):
            raise ModSettingsLifecycleFailure(
                f"host action failed: {host_action}"
            )
        respawned = _wait(
            lambda: {
                "host": _query(HOST_PIPE),
                "client": _query(CLIENT_PIPE),
            },
            lambda views: (
                _integer(
                    views["host"],
                    "brain.respawn_action_count",
                ) > old_action_count
                and _integer(
                    views["host"],
                    "bot.participant_id",
                ) > 0
                and _integer(
                    views["host"],
                    "bot.participant_id",
                ) != old_participant_id
                and _integer(
                    views["client"],
                    "bot.participant_id",
                ) == _integer(
                    views["host"],
                    "bot.participant_id",
                )
            ),
            timeout=25.0,
            label="host action respawn round trip",
        )
        result["respawned"] = respawned
        result["success"] = True
    except BaseException as exc:
        failure = exc
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["success"] = False
    finally:
        result["finishedUtc"] = _utc_now()
        if launch:
            try:
                result["runtimeEvidence"] = _copy_runtime_evidence(
                    evidence_dir
                )
            except BaseException as evidence_error:
                result["evidenceError"] = (
                    f"{type(evidence_error).__name__}: {evidence_error}"
                )
                if failure is None:
                    failure = evidence_error
                    result["success"] = False
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
        result_path = evidence_dir / "result.json"
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            f"SUCCESS={result['success']} RESULT={result_path}"
        )

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
        "--launcher",
        type=Path,
        default=ROOT / "dist" / "launcher" /
            "SolomonDarkModLauncher.exe",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=EVIDENCE_ROOT,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=120.0,
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    game_directory = args.game_dir.resolve()
    if game_directory == FORBIDDEN_OWNER_INSTALL.resolve():
        raise SystemExit("the owner's real install is forbidden")
    if not (game_directory / "SolomonDark.exe").is_file():
        raise SystemExit(
            f"source game directory is invalid: {game_directory}"
        )
    launcher_path = args.launcher.resolve()
    if not launcher_path.is_file():
        raise SystemExit(f"launcher does not exist: {launcher_path}")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")

    result = verify_lifecycle(
        evidence_dir=args.evidence_dir.resolve(),
        game_directory=game_directory,
        launcher_path=launcher_path,
        timeout_seconds=args.timeout_seconds,
    )
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
