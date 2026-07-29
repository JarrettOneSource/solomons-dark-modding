#!/usr/bin/env python3
"""Live loopback acceptance for structured mod settings and bot rosters."""

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
    "/mnt/d/codex-evidence/mod-settings-v2-20260727"
)
INSTANCE_PREFIX = "ms2"
HOST_PORT = 49211
CLIENT_PORT = 49212
HOST_PIPE = "SolomonDarkModLoader_LuaExec_ms2-host"
CLIENT_PIPE = "SolomonDarkModLoader_LuaExec_ms2-client"
EXACT_MOD_ID = "bot.brain"

INITIAL_ROSTER = [
    {
        "name": "Ward", "element": "water", "discipline": "mind",
        "behavior": "guardian",
    },
    {
        "name": "Spark", "element": "air", "discipline": "body",
        "behavior": "striker",
    },
]
RECONCILED_ROSTER = [
    {
        "name": "Spark", "element": "earth", "discipline": "arcane",
        "behavior": "striker",
    },
]
SKIRMISHER_ROSTER = [
    {
        "name": "Spark", "element": "earth", "discipline": "arcane",
        "behavior": "skirmisher",
    },
]
EXHAUSTED_ROSTER = [
    {
        "name": "Spark", "element": "earth", "discipline": "arcane",
        "behavior": "skirmisher",
    },
    {
        "name": "Bulwark", "element": "water", "discipline": "mind",
        "behavior": "guardian",
    },
    {
        "name": "Needle", "element": "air", "discipline": "body",
        "behavior": "striker",
    },
]
ELEMENT_IDS = {
    "fire": 0,
    "water": 1,
    "earth": 2,
    "air": 3,
    "ether": 4,
}


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


def _settings_values(roster: list[dict[str, str]], think: str) -> dict[str, object]:
    return {
        "kite_radius": 340,
        "offense_enabled": True,
        "roster": roster,
        "think_profile": think,
        "focus_bot_key": "NONE",
    }


def _seed_persisted_values(evidence_dir: Path) -> None:
    host_path = _atomic_write_settings(
        "host",
        _settings_values(INITIAL_ROSTER, "standard"),
    )
    client_path = _atomic_write_settings(
        "client",
        _settings_values(
            [
                {
                    "name": "ClientLocal",
                    "element": "fire",
                    "discipline": "arcane",
                    "behavior": "skirmisher",
                }
            ],
            "relaxed",
        ),
    )
    shutil.copy2(host_path, evidence_dir / "host-settings-initial.json")
    shutil.copy2(client_path, evidence_dir / "client-settings-initial.json")


PROBE = """
local function emit(key, value)
  if value == nil then value = "" end
  print(key .. "=" .. tostring(value))
end

local scene = sd.world.get_scene()
emit("scene", scene and (scene.name or scene.kind) or "")
emit("authority", sd.state.is_authority())
emit("setting.think_profile", sd.settings.get("think_profile"))

local first = sd.settings.get("roster") or {}
local original_name = first[1] and first[1].name or ""
if first[1] then first[1].name = "mutated-copy" end
local effective = sd.settings.get("roster") or {}
emit(
  "setting.roster.copy_isolated",
  (effective[1] and effective[1].name or "") == original_name)
emit("setting.roster.count", #effective)
for index = 1, 3 do
  local row = effective[index] or {}
  emit("setting.roster." .. index .. ".name", row.name or "")
  emit("setting.roster." .. index .. ".element", row.element or "")
  emit(
    "setting.roster." .. index .. ".discipline",
    row.discipline or "")
  emit(
    "setting.roster." .. index .. ".behavior",
    row.behavior or "")
end

local handles = sd.bots.list() or {}
local active_ids = {}
emit("actual.count", #handles)
for index, handle in ipairs(handles) do
  local participant_id = tonumber(handle:participant_id()) or 0
  active_ids[#active_ids + 1] = tostring(participant_id)
  local snapshot = sd.bots.get_participant_state(participant_id)
  emit("actual." .. index .. ".participant_id", participant_id)
  emit("actual." .. index .. ".name", snapshot and snapshot.name or "")
  emit(
    "actual." .. index .. ".element_id",
    snapshot and snapshot.profile and snapshot.profile.element_id or -1)
end
emit("actual.participant_ids", table.concat(active_ids, ","))

local debug_state = rawget(_G, "bot_brain_debug")
emit(
  "brain.settings_change_count",
  debug_state and debug_state.settings_change_count or 0)
emit(
  "brain.last_settings_change_key",
  debug_state and debug_state.last_settings_change_key or "")
emit(
  "brain.last_roster_new_size",
  debug_state and debug_state.last_roster_new_size or -1)
emit(
  "brain.last_roster_old_size",
  debug_state and debug_state.last_roster_old_size or -1)
emit(
  "brain.reconciliation_error_count",
  debug_state and debug_state.reconciliation_error_count or 0)
emit(
  "brain.last_reconciliation_error",
  debug_state and debug_state.last_reconciliation_error or "")
emit(
  "brain.roster_size",
  debug_state and debug_state.roster_size or 0)
for index = 1, 3 do
  local item =
    debug_state and debug_state.bots and debug_state.bots[index] or {}
  local brain_participant_id = tonumber(item.participant_id) or 0
  local brain_snapshot = brain_participant_id > 0 and
    sd.bots.get_participant_state(brain_participant_id) or nil
  emit(
    "brain.bot." .. index .. ".actual_element_id",
    brain_snapshot and brain_snapshot.profile and
      brain_snapshot.profile.element_id or -1)
  for _, key in ipairs({
    "name",
    "element",
    "discipline",
    "behavior",
    "participant_id",
    "active",
    "mode",
    "hp_ratio",
    "think_count",
    "move_accepted",
    "cast_accepted",
    "attack_window_max",
    "flee_threshold",
    "flee_recovery_threshold",
    "cast_interval_ms",
    "engage_radius",
    "guardian_leash_radius",
    "guardian_ward_distance",
    "guardian_human_participant_id",
    "guardian_engaging",
    "last_error"
  }) do
    emit("brain.bot." .. index .. "." .. key, item[key])
  end
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


def _participant_ids(values: dict[str, str]) -> set[int]:
    result: set[int] = set()
    for value in values.get("actual.participant_ids", "").split(","):
        try:
            participant_id = int(value)
        except ValueError:
            continue
        if participant_id > 0:
            result.add(participant_id)
    return result


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
for key, message in pairs(result.entry_errors or {{}}) do
  print("entry_error." .. key .. "=" .. tostring(message))
end
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


def _roster_matches(
    values: dict[str, str],
    expected: list[dict[str, str]],
) -> bool:
    if (
        _integer(values, "setting.roster.count") != len(expected)
        or values.get("setting.roster.copy_isolated") != "true"
    ):
        return False
    for index, row in enumerate(expected, start=1):
        prefix = f"setting.roster.{index}."
        if any(values.get(prefix + key) != row[key] for key in row):
            return False
    return True


def _brain_roster_matches(
    values: dict[str, str],
    expected: list[dict[str, str]],
) -> bool:
    if _integer(values, "brain.roster_size") != len(expected):
        return False
    for index, row in enumerate(expected, start=1):
        prefix = f"brain.bot.{index}."
        if any(values.get(prefix + key) != row[key] for key in row):
            return False
    return True


def _initial_values_converged(
    views: dict[str, dict[str, str]],
) -> bool:
    host = views["host"]
    client = views["client"]
    host_ids = [
        _integer(host, f"brain.bot.{index}.participant_id")
        for index in (1, 2)
    ]
    client_ids = [
        _integer(client, f"brain.bot.{index}.participant_id")
        for index in (1, 2)
    ]
    return (
        host.get("scene") == "hub"
        and client.get("scene") == "hub"
        and host.get("authority") == "true"
        and client.get("authority") == "false"
        and host.get("setting.think_profile") == "standard"
        and client.get("setting.think_profile") == "relaxed"
        and _roster_matches(host, INITIAL_ROSTER)
        and _roster_matches(client, INITIAL_ROSTER)
        and _brain_roster_matches(host, INITIAL_ROSTER)
        and _brain_roster_matches(client, INITIAL_ROSTER)
        and _integer(host, "actual.count") == 2
        and _integer(client, "actual.count") == 2
        and len(set(host_ids)) == 2
        and min(host_ids) > 0
        and client_ids == host_ids
        and _integer(
            host,
            "brain.bot.1.actual_element_id",
        ) == ELEMENT_IDS["water"]
        and _integer(
            host,
            "brain.bot.2.actual_element_id",
        ) == ELEMENT_IDS["air"]
        and _integer(
            client,
            "brain.bot.1.actual_element_id",
        ) == ELEMENT_IDS["water"]
        and _integer(
            client,
            "brain.bot.2.actual_element_id",
        ) == ELEMENT_IDS["air"]
    )


def _behaviors_measurable(values: dict[str, str]) -> bool:
    guardian = "brain.bot.1."
    striker = "brain.bot.2."
    leash = _number(values, guardian + "guardian_leash_radius")
    ward_distance = _number(values, guardian + "guardian_ward_distance")
    return (
        values.get("scene") == "testrun"
        and values.get(guardian + "active") == "true"
        and values.get(striker + "active") == "true"
        and _integer(
            values,
            guardian + "guardian_human_participant_id",
        ) > 0
        and leash > 0
        and 0 < ward_distance <= leash
        and math.isclose(
            _number(values, guardian + "flee_threshold"),
            0.35,
        )
        and math.isclose(
            _number(values, striker + "flee_threshold"),
            0.20,
        )
        and _integer(values, guardian + "cast_interval_ms") == 500
        and _integer(values, striker + "cast_interval_ms") == 300
        and _number(values, striker + "engage_radius") <
            _number(values, guardian + "engage_radius")
        and _number(values, guardian + "attack_window_max") > 0
        and _number(values, striker + "attack_window_max") > 0
        and _integer(values, guardian + "move_accepted") > 0
        and _integer(values, striker + "move_accepted") > 0
    )


def _write_roster(
    roster: list[dict[str, str]],
    evidence_dir: Path,
    label: str,
) -> Path:
    path = _atomic_write_settings(
        "host",
        _settings_values(roster, "standard"),
    )
    shutil.copy2(path, evidence_dir / f"host-settings-{label}.json")
    return path


def _stage_crash_artifacts(started_at: float) -> list[str]:
    artifacts: list[str] = []
    for role in ("host", "client"):
        log_dir = _stage_root(role) / ".sdmod" / "logs"
        if not log_dir.is_dir():
            continue
        for path in log_dir.glob("*crash*"):
            stat = path.stat()
            if stat.st_size > 0 and stat.st_mtime >= started_at:
                artifacts.append(str(path))
    return artifacts


def _require_owned_stage_paths(launch: dict[str, object]) -> None:
    for role in ("host", "client"):
        raw = str(launch.get(f"{role}ExecutablePath") or "")
        expected = local_sync.path_for_powershell(
            _stage_root(role) / "SolomonDark.exe"
        )
        if raw.replace("/", "\\").casefold() != (
            expected.replace("/", "\\").casefold()
        ):
            raise ModSettingsLifecycleFailure(
                f"{role} executable escaped the exact verifier stage: "
                f"expected={expected} actual={raw}"
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
            if source.is_file():
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
    started_at = time.time()
    result: dict[str, Any] = {
        "contract": "mod-settings-structured-list-v2",
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
            god_mode=False,
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
        _require_owned_stage_paths(launch)

        initial = _wait(
            lambda: {
                "host": _query(HOST_PIPE),
                "client": _query(CLIENT_PIPE),
            },
            _initial_values_converged,
            timeout=45.0,
            label="two-row startup roster and host replication",
        )
        result["initialRoster"] = initial
        old_ids = {
            _integer(
                initial["host"],
                f"brain.bot.{index}.participant_id",
            )
            for index in (1, 2)
        }

        _start_testrun()
        local_sync.wait_for_scene(HOST_PIPE, "testrun", timeout=45.0)
        local_sync.wait_for_scene(CLIENT_PIPE, "testrun", timeout=45.0)
        behaviors = _wait(
            lambda: _query(HOST_PIPE),
            _behaviors_measurable,
            timeout=timeout_seconds,
            label="guardian leash and striker behavior profile",
        )
        result["behaviorProfiles"] = behaviors
        host_changes = _integer(
            behaviors,
            "brain.settings_change_count",
        )
        client_changes = _integer(
            _query(CLIENT_PIPE),
            "brain.settings_change_count",
        )

        _write_roster(
            RECONCILED_ROSTER,
            evidence_dir,
            "reconciled",
        )
        reconciliation_reload = _reload(HOST_PIPE)
        result["reconciliationReload"] = reconciliation_reload
        if (
            reconciliation_reload.get("ok") != "true"
            or reconciliation_reload.get("changed") != "roster"
            or reconciliation_reload.get("error", "") != ""
        ):
            raise ModSettingsLifecycleFailure(
                "remove-and-edit reload failed: "
                f"{reconciliation_reload}"
            )

        reconciled = _wait(
            lambda: {
                "host": _query(HOST_PIPE),
                "client": _query(CLIENT_PIPE),
            },
            lambda views: (
                _roster_matches(views["host"], RECONCILED_ROSTER)
                and _roster_matches(
                    views["client"],
                    RECONCILED_ROSTER,
                )
                and _brain_roster_matches(
                    views["host"],
                    RECONCILED_ROSTER,
                )
                and _brain_roster_matches(
                    views["client"],
                    RECONCILED_ROSTER,
                )
                and _integer(views["host"], "actual.count") == 1
                and _integer(views["client"], "actual.count") == 1
                and not (
                    _participant_ids(views["host"]) & old_ids
                )
                and _integer(
                    views["host"],
                    "brain.bot.1.participant_id",
                ) > 0
                and _integer(
                    views["client"],
                    "brain.bot.1.participant_id",
                ) == _integer(
                    views["host"],
                    "brain.bot.1.participant_id",
                )
                and _integer(
                    views["host"],
                    "brain.bot.1.actual_element_id",
                ) == ELEMENT_IDS["earth"]
                and _integer(
                    views["client"],
                    "brain.bot.1.actual_element_id",
                ) == ELEMENT_IDS["earth"]
                and _integer(
                    views["host"],
                    "brain.settings_change_count",
                ) == host_changes + 1
                and _integer(
                    views["client"],
                    "brain.settings_change_count",
                ) == client_changes + 1
                and _integer(
                    views["host"],
                    "brain.last_roster_old_size",
                ) == 2
                and _integer(
                    views["host"],
                    "brain.last_roster_new_size",
                ) == 1
                and _integer(
                    views["client"],
                    "brain.last_roster_old_size",
                ) == 2
                and _integer(
                    views["client"],
                    "brain.last_roster_new_size",
                ) == 1
            ),
            timeout=30.0,
            label="ordered despawn, element respawn, and list replication",
        )
        result["reconciledRoster"] = reconciled
        striker_id = _integer(
            reconciled["host"],
            "brain.bot.1.participant_id",
        )

        _write_roster(
            SKIRMISHER_ROSTER,
            evidence_dir,
            "skirmisher",
        )
        skirmisher_reload = _reload(HOST_PIPE)
        result["skirmisherReload"] = skirmisher_reload
        if (
            skirmisher_reload.get("ok") != "true"
            or skirmisher_reload.get("changed") != "roster"
        ):
            raise ModSettingsLifecycleFailure(
                f"skirmisher reload failed: {skirmisher_reload}"
            )
        skirmisher = _wait(
            lambda: _query(HOST_PIPE),
            lambda values: (
                _brain_roster_matches(values, SKIRMISHER_ROSTER)
                and _integer(
                    values,
                    "brain.bot.1.participant_id",
                ) > 0
                and _integer(
                    values,
                    "brain.bot.1.participant_id",
                ) != striker_id
                and values.get("brain.bot.1.active") == "true"
                and math.isclose(
                    _number(
                        values,
                        "brain.bot.1.flee_threshold",
                    ),
                    0.35,
                )
                and _integer(
                    values,
                    "brain.bot.1.cast_interval_ms",
                ) == 500
                and _number(
                    values,
                    "brain.bot.1.engage_radius",
                ) == 340
                and _integer(
                    values,
                    "brain.bot.1.move_accepted",
                ) > 0
            ),
            timeout=30.0,
            label="shipped skirmisher profile after Behavior respawn",
        )
        result["skirmisherBehavior"] = skirmisher

        _write_roster(
            EXHAUSTED_ROSTER,
            evidence_dir,
            "slot-exhaustion",
        )
        exhausted_reload = _reload(HOST_PIPE)
        result["slotExhaustionReload"] = exhausted_reload
        if (
            exhausted_reload.get("ok") != "true"
            or exhausted_reload.get("changed") != "roster"
            or exhausted_reload.get("error", "") != ""
        ):
            raise ModSettingsLifecycleFailure(
                "capacity-valid roster reload failed before reconciliation: "
                f"{exhausted_reload}"
            )

        survived = _wait(
            lambda: {
                "host": _query(HOST_PIPE),
                "client": _query(CLIENT_PIPE),
            },
            lambda views: (
                _roster_matches(views["host"], EXHAUSTED_ROSTER)
                and _roster_matches(
                    views["client"],
                    EXHAUSTED_ROSTER,
                )
                and _brain_roster_matches(
                    views["host"],
                    EXHAUSTED_ROSTER,
                )
                and _integer(views["host"], "actual.count") == 2
                and _integer(views["client"], "actual.count") == 2
                and _integer(
                    views["host"],
                    "brain.bot.3.participant_id",
                ) == 0
                and views["host"].get(
                    "brain.bot.3.last_error",
                ) == "lobby full"
            ),
            timeout=20.0,
            label="configured-capacity refusal and roster survival",
        )
        result["slotExhaustionSurvived"] = survived
        crashes = _stage_crash_artifacts(started_at)
        result["newCrashArtifacts"] = crashes
        if crashes:
            raise ModSettingsLifecycleFailure(
                f"new exact-stage crash artifacts appeared: {crashes}"
            )
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
        print(f"SUCCESS={result['success']} RESULT={result_path}")

    if failure is not None:
        raise failure
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-dir", type=Path, default=GAME_DIRECTORY)
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
