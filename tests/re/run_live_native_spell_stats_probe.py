#!/usr/bin/env python3
"""Fresh staged acceptance probe for semantic bot loadout details.

The probe owns exactly one launcher-returned staged process. It validates the
address-free ``sd.bots.get_loadout_details`` contract against live native
progression state: an unwelded primary, eight occupied secondary costs,
Phasing/Teleport cooldown units and transitions, a generation-captured weld,
and repeated observation reads that do not mutate the active primary vector.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from owned_process_ledger import (  # noqa: E402
    OwnedProcessError,
    register_owned_launch,
    stop_owned_process_ids,
)
import cast_state_probe as csp  # noqa: E402
import verify_local_multiplayer_sync as local_sync  # noqa: E402


OUTPUT_PATH = ROOT / "runtime" / "live_native_spell_stats_probe.json"
RUNTIME_ROOT = ROOT / "runtime" / "ml-bot-policy-v2-phase2-live"
RUNTIME_BINARY_LAYOUT_PATH = (
    ROOT / "runtime" / "stage" / ".sdmod" / "config" /
    "binary-layout.ini"
)
ACTIVE_BOTS_CONFIG_PATH = (
    ROOT / "mods" / "lua_bots" / "config" / "active_bots.txt"
)
SOLO_LAUNCHER = ROOT / "scripts" / "Launch-LocalSoloSession.ps1"
MOD_LAUNCHER = ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"
if os.name == "nt":
    GAME_DIRECTORY = Path(
        "C:/Users/User/Documents/GitHub/SB Modding/"
        "Solomon Dark/SolomonDarkAbandonware"
    )
else:
    GAME_DIRECTORY = Path(
        "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
        "Solomon Dark/SolomonDarkAbandonware"
    )

PROBE_MOD_ID = "sample.lua.bots"
PROBE_BOT_NAME = "ML Policy V2 Native Probe"
PRIMARY_SKILLS = [
    {"name": "fire", "element_id": 0, "skill_id": 0x3F3},
    {"name": "water", "element_id": 1, "skill_id": 0x3F4},
    {"name": "earth", "element_id": 2, "skill_id": 0x3F6},
    {"name": "air", "element_id": 3, "skill_id": 0x3F5},
    {"name": "ether", "element_id": 4, "skill_id": 0x3F2},
]
PROBE_SECONDARIES = (15, 48, 49, 50, 51, 54, 72, 73)
PROBE_LEARNED_ROWS = (8, 9, 10, 15, 16, 17, 18, *PROBE_SECONDARIES)
WELD_PAIRS = {
    1000: (8, 16),
    1001: (8, 32),
    1002: (8, 24),
    1003: (16, 24),
    1004: (32, 24),
    1005: (16, 32),
    1006: (8, 40),
    1007: (16, 40),
    1008: (32, 40),
    1009: (24, 40),
}
FORBIDDEN_PORTS = (50611, 50612, 49511, 49512)
BAD_LOG_TOKENS = (
    "native skill choices roll failed",
    "native special skill choice post-apply path failed",
    "native bot skill choice apply failed",
)


class LiveNativeSpellStatsProbeFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise LiveNativeSpellStatsProbeFailure(message)


def as_bool(value: object) -> bool:
    return str(value).strip().lower() == "true"


def as_int(value: object, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(str(value), 0)
    except ValueError:
        return int(float(str(value)))


def as_float(value: object, default: float = math.nan) -> float:
    if value is None or value == "":
        return default
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def read_runtime_layout_offset(name: str) -> int:
    text = RUNTIME_BINARY_LAYOUT_PATH.read_text(
        encoding="utf-8",
        errors="replace",
    )
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return int(value.strip(), 0)
    raise LiveNativeSpellStatsProbeFailure(
        f"Unable to find {name!r} in {RUNTIME_BINARY_LAYOUT_PATH}"
    )


def force_bot_mana(
    bot_id: int,
    current: float,
    maximum: float,
) -> dict[str, str]:
    mp_offset = read_runtime_layout_offset("progression_mp")
    max_mp_offset = read_runtime_layout_offset("progression_max_mp")
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local bot = sd.bots.get_state({bot_id})
local function emit(key, value)
  print(key .. "=" .. tostring(value))
end
if type(bot) ~= 'table' then
  emit('ok', false)
  emit('error', 'bot_not_found')
  return
end
local progression =
  tonumber(bot.progression_runtime_state_address) or 0
if progression == 0 then
  emit('ok', false)
  emit('error', 'missing_progression_runtime')
  return
end
emit('before_mp', bot.mp)
emit('before_max_mp', bot.max_mp)
emit(
  'mp_ok',
  sd.debug.write_float(progression + {mp_offset}, {current}))
emit(
  'max_mp_ok',
  sd.debug.write_float(
    progression + {max_mp_offset},
    {maximum}))
local refreshed = sd.bots.get_state({bot_id}) or {{}}
emit('after_mp', refreshed.mp)
emit('after_max_mp', refreshed.max_mp)
emit(
  'ok',
  refreshed.mp ~= nil and refreshed.max_mp ~= nil)
""".strip()
        )
    )


def queue_skill(
    bot_id: int,
    skill_id: int,
    target_x: float,
    target_y: float,
    *,
    target_actor_address: int = 0,
) -> dict[str, str]:
    target_actor_line = (
        f"  target_actor_address = {target_actor_address},\n"
        if target_actor_address
        else ""
    )
    return csp.parse_key_values(
        csp.run_lua(
            f"""
print('ok=' .. tostring(sd.bots.cast({{
  id = {bot_id},
  kind = 'primary',
  skill_id = {skill_id},
{target_actor_line}  target = {{ x = {target_x}, y = {target_y} }},
}})))
""".strip()
        )
    )


def queue_default_primary(
    bot_id: int,
    target_x: float,
    target_y: float,
) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
print('ok=' .. tostring(sd.bots.cast({{
  id = {bot_id},
  kind = 'primary',
  target = {{ x = {target_x}, y = {target_y} }},
}})))
""".strip()
        )
    )


def tail_loader_log(limit: int = 220) -> list[str]:
    return csp.tail_loader_log(limit)


def set_lua_bot_tick_enabled(enabled: bool) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
lua_bots_disable_tick = {"false" if enabled else "true"}
print('ok=true')
print(
  'lua_bots_disable_tick=' ..
  tostring(lua_bots_disable_tick))
""".strip()
        )
    )


def start_testrun_without_waves() -> dict[str, str]:
    scene = csp.query_scene_state()
    if csp.is_settled_scene(scene, "testrun"):
        return {"ok": "true", "already_in_testrun": "true"}
    values = csp.parse_key_values(
        csp.run_lua(
            "print('ok='..tostring(sd.hub.start_testrun()))"
        )
    )
    if values.get("ok") != "true":
        raise LiveNativeSpellStatsProbeFailure(
            f"sd.hub.start_testrun failed: {values}"
        )
    csp.wait_for_scene("testrun", timeout_s=45.0)
    return values


@contextmanager
def temporary_active_bots_config(active_bot_keys: str):
    """Select legacy probe profiles through the mod-local config file."""
    with csp.temporary_required_lua_mods(csp.LUA_BOT_MOD_ID):
        if not active_bot_keys or active_bot_keys == "default":
            yield
            return

        existed = ACTIVE_BOTS_CONFIG_PATH.exists()
        original_text = (
            ACTIVE_BOTS_CONFIG_PATH.read_text(encoding="utf-8")
            if existed
            else None
        )
        ACTIVE_BOTS_CONFIG_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        ACTIVE_BOTS_CONFIG_PATH.write_text(
            f"{active_bot_keys}\n",
            encoding="utf-8",
        )
        try:
            yield
        finally:
            if existed and original_text is not None:
                ACTIVE_BOTS_CONFIG_PATH.write_text(
                    original_text,
                    encoding="utf-8",
                )
            else:
                ACTIVE_BOTS_CONFIG_PATH.unlink(missing_ok=True)


def list_bot_states() -> list[dict[str, str]]:
    values = csp.parse_key_values(
        csp.run_lua(
            """
local bots =
  sd.bots and sd.bots.get_state and
  sd.bots.get_state() or {}
local contexts = rawget(_G, "lua_bots_debug")
contexts =
  type(contexts) == "table" and
  type(contexts.bots) == "table" and
  contexts.bots or {}
local function emit(key, value)
  print(key .. "=" .. tostring(value))
end
local function context_for_bot(bot_id)
  for _, context in ipairs(contexts) do
    if tostring(context.bot_id) == tostring(bot_id) then
      return context
    end
  end
  return nil
end
emit("count", #bots)
for index, bot in ipairs(bots) do
  local prefix = "bot." .. tostring(index) .. "."
  local context = context_for_bot(bot.id)
  local profile =
    type(context) == "table" and
    context.bot_profile or nil
  for _, key in ipairs({
    "id", "actor_address",
    "progression_runtime_state_address",
    "progression_handle_address",
    "equip_handle_address",
    "equip_runtime_state_address",
    "gameplay_slot", "actor_slot",
    "hp", "max_hp", "mp", "max_mp",
    "x", "y", "state"
  }) do
    emit(prefix .. key, bot[key])
  end
  emit(
    prefix .. "bot_name",
    type(context) == "table" and
      context.bot_name or nil)
  emit(
    prefix .. "profile_element_id",
    type(profile) == "table" and
      profile.element_id or nil)
  emit(
    prefix .. "profile_discipline_id",
    type(profile) == "table" and
      profile.discipline_id or nil)
end
""".strip()
        )
    )
    bots: list[dict[str, str]] = []
    for index in range(1, csp.int_value(values, "count") + 1):
        prefix = f"bot.{index}."
        bot = {
            key[len(prefix):]: value
            for key, value in values.items()
            if key.startswith(prefix)
        }
        if bot:
            bots.append(bot)
    return bots


def wait_for_materialized_bots(
    min_count: int,
    timeout_s: float = 45.0,
) -> list[dict[str, str]]:
    deadline = time.time() + timeout_s
    last: list[dict[str, str]] = []
    while time.time() < deadline:
        last = [
            bot
            for bot in list_bot_states()
            if csp.int_value(bot, "actor_address") != 0
        ]
        if len(last) >= min_count:
            return last
        time.sleep(0.25)
    raise LiveNativeSpellStatsProbeFailure(
        f"Timed out waiting for {min_count} materialized bots. "
        f"Last={last}"
    )


def find_bot_for_element(
    bots: list[dict[str, str]],
    element_id: int,
) -> dict[str, str]:
    for bot in bots:
        if csp.int_value(bot, "profile_element_id") == element_id:
            return bot
    raise LiveNativeSpellStatsProbeFailure(
        f"No materialized bot owns element_id={element_id}. Bots={bots}"
    )


def drive_to_materialized_bots(
    element: str,
    discipline: str,
    active_bot_keys: str,
    min_count: int,
    *,
    start_waves: bool = True,
    post_testrun_settle_seconds: float = 0.0,
) -> dict[str, Any]:
    result: dict[str, Any] = {"navigation": []}
    result["launcher_freshness"] = csp.ensure_launcher_bundle_fresh()

    csp.stop_game()
    csp.clear_loader_log()
    with temporary_active_bots_config(active_bot_keys):
        csp.launch_game()
        process_id = csp.wait_for_game_process()
        result["process_id"] = process_id
        csp.wait_for_lua_pipe()
        result["navigation"].append(
            {"step": "launch", "process_id": process_id}
        )

        csp.drive_new_game_flow(
            process_id,
            element=element,
            discipline=discipline,
        )
        result["navigation"].append(
            {"step": "hub_ready", "flow": {"mode": "new_game"}}
        )
        if start_waves:
            csp.start_run_and_waves()
            csp.boost_player_survival()
            result["navigation"].append(
                {"step": "testrun_started_with_waves"}
            )
        else:
            result["testrun_start"] = start_testrun_without_waves()
            result["navigation"].append(
                {"step": "testrun_started_without_waves"}
            )

        if post_testrun_settle_seconds > 0.0:
            time.sleep(post_testrun_settle_seconds)

        bots = wait_for_materialized_bots(min_count)
    result["bots_initial"] = bots
    result["bot_initial"] = bots[0]
    return result


def local_path_from_windows(value: str) -> Path:
    if os.name == "nt":
        return Path(value)
    completed = subprocess.run(
        ["wslpath", "-u", value],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=False,
    )
    converted = completed.stdout.strip()
    if completed.returncode != 0 or not converted:
        raise LiveNativeSpellStatsProbeFailure(
            f"could not convert Windows path {value!r}"
        )
    return Path(converted)


class OwnedSoloSession:
    def __init__(self, instance: str) -> None:
        self.instance = instance
        self.pipe_name = f"SolomonDarkModLoader_LuaExec_{instance}"
        self.runtime_root = RUNTIME_ROOT
        self.process_ids: list[int] = []
        self.launch_result: dict[str, Any] | None = None

    @property
    def stage_root(self) -> Path:
        return (
            self.runtime_root
            / "instances"
            / self.instance.lower()
            / "stage"
        )

    @property
    def loader_log_path(self) -> Path:
        return (
            self.stage_root
            / ".sdmod"
            / "logs"
            / "solomondarkmodloader.log"
        )

    def _rescue_partial_launch(self, ledger_path: Path) -> None:
        if not ledger_path.is_file():
            return
        try:
            document = json.loads(
                ledger_path.read_text(encoding="utf-8-sig")
            )
            process_id = int(document.get("processId", 0))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return
        if process_id <= 0:
            return

        partial = {
            "processId": process_id,
            "instance": self.instance,
            "executablePath": local_sync.path_for_powershell(
                self.stage_root / "SolomonDark.exe"
            ),
        }
        try:
            identities = register_owned_launch(
                partial,
                validate=True,
                require_processes=False,
            )
            stop_owned_process_ids(
                identity.process_id for identity in identities
            )
        except OwnedProcessError:
            # Ownership is intentionally not broadened when the exact staged
            # PID/path identity cannot be proven.
            return

    def launch(self) -> dict[str, Any]:
        require(self.launch_result is None, "session was already launched")
        require(GAME_DIRECTORY.is_dir(), f"game directory missing: {GAME_DIRECTORY}")
        require(MOD_LAUNCHER.is_file(), f"launcher missing: {MOD_LAUNCHER}")

        ports = local_sync.select_available_windows_udp_ports(
            2,
            excluded_ports=FORBIDDEN_PORTS,
        )
        local_port, unused_remote_port = ports
        ledger_path = (
            self.runtime_root
            / f".phase2-probe-ledger-{self.instance}-{os.getpid()}.json"
        )
        result_path = (
            self.runtime_root
            / f".phase2-probe-result-{self.instance}-{os.getpid()}.json"
        )
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        arguments = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            local_sync.path_for_powershell(SOLO_LAUNCHER),
            "-Instance",
            self.instance,
            "-Preset",
            "map_create_ether_arcane_hub",
            "-RuntimeRoot",
            local_sync.path_for_powershell(self.runtime_root),
            "-LocalPort",
            str(local_port),
            "-UnusedRemotePort",
            str(unused_remote_port),
            "-ParticipantId",
            "0x2000000000002B01",
            "-PlayerName",
            "ML Policy V2 Probe",
            "-GameDirectory",
            local_sync.path_for_powershell(GAME_DIRECTORY),
            "-LauncherPath",
            local_sync.path_for_powershell(MOD_LAUNCHER),
            "-FreshInstall",
            "-QuickStart",
            "-QuickStartElement",
            "ether",
            "-QuickStartDiscipline",
            "arcane",
            "-ExactModIds",
            PROBE_MOD_ID,
            "-Headless",
            "-ProcessIdOutputPath",
            local_sync.path_for_powershell(ledger_path),
            "-ResultOutputPath",
            local_sync.path_for_powershell(result_path),
        ]
        environment = os.environ.copy()
        environment["SDMOD_DISABLE_AUDIO"] = "1"
        environment["SDMOD_LUA_BOTS_ACTIVE"] = "none"
        environment.pop("SDMOD_ENABLE_AUDIO", None)

        launcher_wrapper: subprocess.Popen[str] | None = None
        try:
            launcher_wrapper = subprocess.Popen(
                arguments,
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            launch_deadline = time.monotonic() + 180.0
            while (
                time.monotonic() < launch_deadline and
                not result_path.is_file()
            ):
                return_code = launcher_wrapper.poll()
                if return_code is not None:
                    require(
                        return_code == 0,
                        "solo launch failed with exit code "
                        f"{return_code}",
                    )
                    break
                time.sleep(0.1)
            require(
                result_path.is_file(),
                "solo launcher did not publish its result document",
            )
            result = json.loads(
                result_path.read_text(encoding="utf-8-sig")
            )
            require(isinstance(result, dict), "solo launch result is not an object")
            require(result.get("success") is True, f"solo launch failed: {result}")
            require(
                result.get("audioDisabled") is True,
                f"probe launch did not disable audio: {result}",
            )
            require(
                result.get("headlessEnabled") is True,
                f"probe launch was not headless: {result}",
            )
            identities = register_owned_launch(result)
            self.process_ids = [
                identity.process_id for identity in identities
            ]
            require(
                len(self.process_ids) == 1,
                f"expected one owned staged game process: {identities}",
            )
            runtime_root = result.get("runtimeRoot")
            if isinstance(runtime_root, str) and runtime_root:
                self.runtime_root = local_path_from_windows(runtime_root)
            self.launch_result = result
            return result
        except BaseException:
            if self.process_ids:
                self.close()
            else:
                self._rescue_partial_launch(ledger_path)
            raise
        finally:
            if launcher_wrapper is not None:
                if launcher_wrapper.poll() is None:
                    launcher_wrapper.terminate()
                    try:
                        launcher_wrapper.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        launcher_wrapper.kill()
                        launcher_wrapper.wait(timeout=5.0)
            ledger_path.unlink(missing_ok=True)
            result_path.unlink(missing_ok=True)

    def close(self) -> list[dict[str, Any]]:
        process_ids = list(self.process_ids)
        self.process_ids.clear()
        try:
            if not process_ids:
                return []
            return stop_owned_process_ids(process_ids)
        finally:
            local_sync._kill_lua_daemon(self.pipe_name)

    def lua(self, code: str, *, timeout: float = 15.0) -> str:
        return local_sync.lua(self.pipe_name, code, timeout=timeout)

    def values(self, code: str, *, timeout: float = 15.0) -> dict[str, str]:
        return local_sync.parse_key_values(self.lua(code, timeout=timeout))

    def wait_for_pipe(self, timeout: float = 120.0) -> None:
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            try:
                if self.lua("return 'ready'", timeout=5.0).strip() == "ready":
                    return
            except (local_sync.VerifyFailure, subprocess.TimeoutExpired) as exc:
                last_error = str(exc)
            time.sleep(0.25)
        raise LiveNativeSpellStatsProbeFailure(
            f"Lua pipe {self.pipe_name} did not become ready: {last_error}"
        )

    def wait_for_hub(self, timeout: float = 180.0) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        last: dict[str, str] = {}
        last_error = ""
        while time.monotonic() < deadline:
            try:
                last = self.values(
                    """
if type(sd) ~= 'table' or
    type(sd.world) ~= 'table' or
    type(sd.world.get_scene) ~= 'function' or
    type(sd.player) ~= 'table' or
    type(sd.player.get_state) ~= 'function' then
  print('scene=')
  print('transitioning=true')
  print('player_available=false')
  return
end
lua_bots_disable_tick = true
local scene = sd.world.get_scene() or {}
print('scene=' .. tostring(scene.name or scene.kind or ''))
print('transitioning=' .. tostring(scene.transitioning or false))
local player = sd.player.get_state()
print('player_available=' .. tostring(type(player) == 'table'))
"""
                )
            except (
                local_sync.VerifyFailure,
                subprocess.TimeoutExpired,
            ) as exc:
                last_error = str(exc)
                time.sleep(0.25)
                continue
            if (
                last.get("scene") == "hub"
                and last.get("transitioning") == "false"
                and last.get("player_available") == "true"
            ):
                return last
            time.sleep(0.25)
        raise LiveNativeSpellStatsProbeFailure(
            "quick-start session did not settle in the hub: "
            f"{last}; last_error={last_error}"
        )

    def tail_loader_log(self, limit: int = 240) -> list[str]:
        if not self.loader_log_path.is_file():
            return []
        lines = self.loader_log_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
        return lines[-limit:]


def create_probe_bot(session: OwnedSoloSession) -> int:
    secondary_literal = ", ".join(str(entry) for entry in PROBE_SECONDARIES)
    values = session.values(
        f"""
local function emit(key, value)
  print(key .. '=' .. tostring(value))
end
sd.bots.clear()
local player = sd.player.get_state()
if type(player) ~= 'table' then
  emit('ok', false)
  emit('error', 'missing_player')
  return
end
local id, err = sd.bots.create({{
  name = {json.dumps(PROBE_BOT_NAME)},
  profile = {{
    element_id = 4,
    discipline_id = 2,
    level = 1,
    experience = 0,
    loadout = {{
      primary_entry_index = 8,
      primary_combo_entry_index = 8,
      secondary_entry_indices = {{ {secondary_literal} }},
    }},
  }},
  scene = {{ kind = 'shared_hub' }},
  ready = true,
  heading = 90.0,
  position = {{
    x = (tonumber(player.x) or 0.0) + 112.0,
    y = tonumber(player.y) or 0.0,
  }},
}})
emit('ok', id ~= nil)
emit('bot_id', id or 0)
emit('error', err or '')
"""
    )
    require(values.get("ok") == "true", f"sd.bots.create failed: {values}")
    bot_id = as_int(values.get("bot_id"))
    require(bot_id > 0, f"sd.bots.create returned an invalid ID: {values}")
    return bot_id


def wait_for_materialized_bot(
    session: OwnedSoloSession,
    bot_id: int,
    timeout: float = 45.0,
) -> None:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = session.values(
            f"""
local bot = sd.bots.get_state({bot_id})
print('available=' .. tostring(type(bot) == 'table'))
print('actor_ready=' .. tostring(
  type(bot) == 'table' and
  (tonumber(bot.actor_address) or 0) ~= 0))
print('progression_ready=' .. tostring(
  type(bot) == 'table' and
  (tonumber(bot.progression_runtime_state_address) or 0) ~= 0))
"""
        )
        if (
            last.get("available") == "true"
            and last.get("actor_ready") == "true"
            and last.get("progression_ready") == "true"
        ):
            return
        time.sleep(0.25)
    raise LiveNativeSpellStatsProbeFailure(
        f"probe bot did not materialize: {last}"
    )


def prepare_native_rows(
    session: OwnedSoloSession,
    bot_id: int,
) -> dict[str, Any]:
    rows_literal = ", ".join(str(entry) for entry in PROBE_LEARNED_ROWS)
    values = session.values(
        f"""
local function emit(key, value)
  print(key .. '=' .. tostring(value))
end
local function offset(name)
  return tonumber(sd.debug.layout_offset(name)) or 0
end
local bot = sd.bots.get_state({bot_id})
local progression =
  type(bot) == 'table' and
  (tonumber(bot.progression_runtime_state_address) or 0) or 0
local table_base_offset =
  offset('standalone_wizard_progression_table_base')
local count_offset =
  offset('standalone_wizard_progression_table_count')
local stride =
  offset('standalone_wizard_progression_entry_stride')
local active_offset =
  offset('standalone_wizard_progression_active_flag')
local effective_offset =
  offset('standalone_wizard_progression_entry_effective_rank')
local table_address =
  progression ~= 0 and
  (tonumber(sd.debug.read_u32(
    progression + table_base_offset)) or 0) or 0
local count =
  progression ~= 0 and
  (tonumber(sd.debug.read_i32(
    progression + count_offset)) or 0) or 0
local writes_ok =
  progression ~= 0 and table_address ~= 0 and
    stride > 0 and active_offset > 0 and
    effective_offset > 0 and count > 0
for _, entry_id in ipairs({{ {rows_literal} }}) do
  if entry_id >= count then
    writes_ok = false
  else
    local row = table_address + entry_id * stride
    writes_ok =
      sd.debug.write_u16(row + active_offset, 1) and
      sd.debug.write_u16(row + effective_offset, 1) and
      writes_ok
  end
end
local cooldown_current_offset =
  offset('standalone_wizard_progression_cooldown_current')
local cooldown_cap_offset =
  offset('standalone_wizard_progression_cooldown_cap')
for entry_id, cap_ticks in pairs({{
  [15] = 100.0,
  [48] = 6000.0,
}}) do
  local row = table_address + entry_id * stride
  writes_ok =
    sd.debug.write_float(
      row + cooldown_current_offset,
      0.0) and
    sd.debug.write_float(
      row + cooldown_cap_offset,
      cap_ticks) and
    writes_ok
end
if 52 < count then
  local weld_row = table_address + 52 * stride
  writes_ok =
    sd.debug.write_u16(weld_row + active_offset, 0) and
    sd.debug.write_u16(weld_row + effective_offset, 0) and
    writes_ok
end
local sync_ok = sd.bots.debug_sync_level_up({{
  level = 2,
  experience = 100,
}})
emit('writes_ok', writes_ok)
emit('sync_ok', sync_ok)
emit('row_count', count)
"""
    )
    require(values.get("writes_ok") == "true", f"row preparation failed: {values}")
    require(values.get("sync_ok") == "true", f"native refresh failed: {values}")
    return {
        "learned_rows": list(PROBE_LEARNED_ROWS),
        "native_row_count": as_int(values.get("row_count")),
    }


def query_loadout_details(
    session: OwnedSoloSession,
    bot_id: int,
) -> dict[str, Any]:
    values = session.values(
        f"""
local function emit(key, value)
  print(key .. '=' .. tostring(value))
end
local details = sd.bots.get_loadout_details({bot_id})
emit('available', type(details) == 'table')
if type(details) ~= 'table' then
  return
end
emit('participant_id', details.participant_id)
local primary = details.primary or {{}}
for _, key in ipairs({{
  'entry_id', 'combo_entry_id', 'build_id',
  'build_id_resolved', 'mana_cost', 'mana_cost_resolved',
  'mana_charge_kind', 'range_min', 'range_max',
  'range_resolved', 'range_source',
}}) do
  emit('primary.' .. key, primary[key])
end
emit('secondary_count', #(details.secondaries or {{}}))
for index, row in ipairs(details.secondaries or {{}}) do
  for _, key in ipairs({{
    'slot', 'entry_id', 'mana_cost', 'mana_cost_resolved',
    'cooldown_seconds', 'cooldown_remaining_seconds',
    'cooldown_resolved',
  }}) do
    emit('secondary.' .. index .. '.' .. key, row[key])
  end
end
emit('pending_weld_build_id', details.pending_weld_build_id)
emit(
  'pending_weld_build_id_resolved',
  details.pending_weld_build_id_resolved)
local window = sd.bots.get_primary_attack_window({bot_id})
emit('window_available', type(window) == 'table')
if type(window) == 'table' then
  emit('window.min_range', window.min_range)
  emit('window.max_range', window.max_range)
  emit('window.native_backed', window.native_backed)
  emit('window.source', window.source)
end
"""
    )
    result: dict[str, Any] = {
        "available": as_bool(values.get("available")),
        "participant_id": as_int(values.get("participant_id")),
        "primary": {
            "entry_id": as_int(values.get("primary.entry_id"), -1),
            "combo_entry_id": as_int(
                values.get("primary.combo_entry_id"),
                -1,
            ),
            "build_id": as_int(values.get("primary.build_id")),
            "build_id_resolved": as_bool(
                values.get("primary.build_id_resolved")
            ),
            "mana_cost": as_float(values.get("primary.mana_cost"), 0.0),
            "mana_cost_resolved": as_bool(
                values.get("primary.mana_cost_resolved")
            ),
            "mana_charge_kind": values.get(
                "primary.mana_charge_kind",
                "",
            ),
            "range_min": as_float(values.get("primary.range_min"), 0.0),
            "range_max": as_float(values.get("primary.range_max"), 0.0),
            "range_resolved": as_bool(
                values.get("primary.range_resolved")
            ),
            "range_source": values.get("primary.range_source", ""),
        },
        "secondaries": [],
        "pending_weld_build_id": as_int(
            values.get("pending_weld_build_id")
        ),
        "pending_weld_build_id_resolved": as_bool(
            values.get("pending_weld_build_id_resolved")
        ),
        "window": {
            "available": as_bool(values.get("window_available")),
            "min_range": as_float(values.get("window.min_range"), 0.0),
            "max_range": as_float(values.get("window.max_range"), 0.0),
            "native_backed": as_bool(values.get("window.native_backed")),
            "source": values.get("window.source", ""),
        },
    }
    for index in range(1, as_int(values.get("secondary_count")) + 1):
        prefix = f"secondary.{index}."
        result["secondaries"].append(
            {
                "slot": as_int(values.get(prefix + "slot")),
                "entry_id": as_int(values.get(prefix + "entry_id"), -1),
                "mana_cost": as_float(
                    values.get(prefix + "mana_cost"),
                    0.0,
                ),
                "mana_cost_resolved": as_bool(
                    values.get(prefix + "mana_cost_resolved")
                ),
                "cooldown_seconds": as_float(
                    values.get(prefix + "cooldown_seconds"),
                    0.0,
                ),
                "cooldown_remaining_seconds": as_float(
                    values.get(prefix + "cooldown_remaining_seconds"),
                    0.0,
                ),
                "cooldown_resolved": as_bool(
                    values.get(prefix + "cooldown_resolved")
                ),
            }
        )
    return result


def query_primary_native_snapshot(
    session: OwnedSoloSession,
    bot_id: int,
) -> dict[str, Any]:
    values = session.values(
        f"""
local function emit(key, value)
  print(key .. '=' .. tostring(value))
end
local function offset(name)
  return tonumber(sd.debug.layout_offset(name)) or 0
end
local bot = sd.bots.get_state({bot_id})
local progression =
  type(bot) == 'table' and
  (tonumber(bot.progression_runtime_state_address) or 0) or 0
local current =
  sd.debug.read_i32(
    progression + offset('progression_current_spell_id'))
local values_pointer =
  sd.debug.read_u32(
    progression + offset('progression_primary_stat_values'))
local count =
  sd.debug.read_i32(
    progression + offset('progression_primary_stat_count'))
local rebuilt =
  sd.debug.resolve_native_primary_spell_stats(progression, 8, 8) or {{}}
emit('current_spell_id', current)
emit('stat_values_present',
  values_pointer ~= nil and values_pointer ~= 0)
emit('stat_count', count)
emit('rebuilt.resolved', rebuilt.resolved)
emit('rebuilt.error', rebuilt.error)
emit('rebuilt.current_spell_id', rebuilt.current_spell_id)
emit('rebuilt.mana_spend_cost', rebuilt.mana_spend_cost)
emit('rebuilt.output_count', rebuilt.output_count)
if values_pointer ~= nil and values_pointer ~= 0 and
    count ~= nil and count > 0 and count <= 64 then
  for index = 0, math.min(count - 1, 7) do
    emit(
      'stat.' .. tostring(index),
      sd.debug.read_float(values_pointer + index * 4))
  end
end
"""
    )
    count = as_int(values.get("stat_count"))
    return {
        "current_spell_id": as_int(
            values.get("current_spell_id"),
            -1,
        ),
        "stat_values_present": as_bool(
            values.get("stat_values_present")
        ),
        "stat_count": count,
        "stat_values": [
            as_float(values.get(f"stat.{index}"))
            for index in range(min(max(count, 0), 8))
        ],
        "rebuilt": {
            "resolved": as_bool(values.get("rebuilt.resolved")),
            "error": values.get("rebuilt.error", ""),
            "current_spell_id": as_int(
                values.get("rebuilt.current_spell_id"),
                -1,
            ),
            "mana_spend_cost": as_float(
                values.get("rebuilt.mana_spend_cost"),
                0.0,
            ),
            "output_count": as_int(
                values.get("rebuilt.output_count")
            ),
        },
    }


def validate_loadout_details(
    details: dict[str, Any],
    *,
    expected_build_id: int,
    expected_pair: tuple[int, int],
) -> None:
    require(details["available"], f"loadout details unavailable: {details}")
    primary = details["primary"]
    require(
        primary["build_id_resolved"]
        and primary["build_id"] == expected_build_id,
        f"primary build did not resolve to {expected_build_id}: {primary}",
    )
    require(
        (primary["entry_id"], primary["combo_entry_id"]) == expected_pair,
        f"primary pair did not resolve to {expected_pair}: {primary}",
    )
    require(
        primary["mana_cost_resolved"] and primary["mana_cost"] > 0.0,
        f"primary mana cost did not resolve: {primary}",
    )
    require(
        primary["mana_charge_kind"] in {"per_cast", "per_second"},
        f"primary mana charge kind is invalid: {primary}",
    )
    require(
        primary["range_resolved"] and primary["range_max"] > 0.0,
        f"primary attack range did not resolve: {primary}",
    )
    window = details["window"]
    require(
        window["available"]
        and window["native_backed"]
        and math.isclose(
            window["min_range"],
            primary["range_min"],
            abs_tol=1e-5,
        )
        and math.isclose(
            window["max_range"],
            primary["range_max"],
            abs_tol=1e-5,
        )
        and window["source"] == primary["range_source"],
        f"legacy attack window diverged from loadout producer: {details}",
    )
    require(
        len(details["secondaries"]) == 8,
        f"loadout details did not return eight secondary rows: {details}",
    )
    for index, (row, entry_id) in enumerate(
        zip(details["secondaries"], PROBE_SECONDARIES, strict=True),
        start=1,
    ):
        require(
            row["slot"] == index and row["entry_id"] == entry_id,
            f"secondary slot {index} identity mismatch: {row}",
        )
        require(
            row["mana_cost_resolved"] and row["mana_cost"] > 0.0,
            f"secondary slot {index} mana cost unresolved: {row}",
        )
        if entry_id in {15, 48}:
            require(
                row["cooldown_resolved"]
                and row["cooldown_seconds"] > 0.0,
                f"cooldown row {entry_id} did not resolve: {row}",
            )
        else:
            require(
                not row["cooldown_resolved"],
                f"unsupported cooldown row {entry_id} resolved unexpectedly: {row}",
            )


def wait_for_ready_loadout(
    session: OwnedSoloSession,
    bot_id: int,
    *,
    expected_build_id: int,
    expected_pair: tuple[int, int],
    timeout: float = 20.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    attempts = 0
    while time.monotonic() < deadline:
        attempts += 1
        last = query_loadout_details(session, bot_id)
        try:
            validate_loadout_details(
                last,
                expected_build_id=expected_build_id,
                expected_pair=expected_pair,
            )
            return last
        except LiveNativeSpellStatsProbeFailure:
            if attempts % 4 == 0:
                roll_next_skill_choices(session, bot_id)
            time.sleep(0.25)
    raise LiveNativeSpellStatsProbeFailure(
        "loadout details did not become fully resolved: "
        f"{last}; native_primary={query_primary_native_snapshot(session, bot_id)}"
    )


def schema_and_primary_mutation_probe(
    session: OwnedSoloSession,
    bot_id: int,
    *,
    query_count: int = 64,
) -> dict[str, Any]:
    values = session.values(
        f"""
local function emit(key, value)
  print(key .. '=' .. tostring(value))
end
local function set(values)
  local result = {{}}
  for _, value in ipairs(values) do result[value] = true end
  return result
end
local forbidden = {{'address', 'pointer', 'ptr', 'seh', 'exception'}}
local unexpected = 0
local forbidden_keys = 0
local address_strings = 0
local function validate_keys(value, expected)
  if type(value) ~= 'table' then
    unexpected = unexpected + 1
    return
  end
  for key, child in pairs(value) do
    if type(key) ~= 'string' or expected[key] ~= true then
      unexpected = unexpected + 1
    end
    if type(key) == 'string' then
      local lowered = string.lower(key)
      for _, token in ipairs(forbidden) do
        if string.find(lowered, token, 1, true) ~= nil then
          forbidden_keys = forbidden_keys + 1
        end
      end
    end
    if type(child) == 'string' and
        string.match(child, '0x%x%x%x%x%x%x') ~= nil then
      address_strings = address_strings + 1
    end
  end
end
local function validate_schema(details)
  validate_keys(details, set({{
    'participant_id', 'primary', 'secondaries',
    'pending_weld_build_id', 'pending_weld_build_id_resolved',
  }}))
  validate_keys(details.primary, set({{
    'entry_id', 'combo_entry_id', 'build_id', 'build_id_resolved',
    'mana_cost', 'mana_cost_resolved', 'mana_charge_kind',
    'range_min', 'range_max', 'range_resolved', 'range_source',
  }}))
  if type(details.secondaries) ~= 'table' or
      #details.secondaries ~= 8 then
    unexpected = unexpected + 1
    return
  end
  for index, row in ipairs(details.secondaries) do
    if index < 1 or index > 8 then unexpected = unexpected + 1 end
    validate_keys(row, set({{
      'slot', 'entry_id', 'mana_cost', 'mana_cost_resolved',
      'cooldown_seconds', 'cooldown_remaining_seconds',
      'cooldown_resolved',
    }}))
  end
end
local bot = sd.bots.get_state({bot_id})
local progression =
  type(bot) == 'table' and
  (tonumber(bot.progression_runtime_state_address) or 0) or 0
local current_offset =
  tonumber(sd.debug.layout_offset('progression_current_spell_id')) or 0
local values_offset =
  tonumber(sd.debug.layout_offset('progression_primary_stat_values')) or 0
local count_offset =
  tonumber(sd.debug.layout_offset('progression_primary_stat_count')) or 0
local before_spell = sd.debug.read_i32(progression + current_offset)
local before_pointer = sd.debug.read_u32(progression + values_offset)
local before_count = sd.debug.read_i32(progression + count_offset)
local before_values = {{}}
if before_pointer ~= nil and before_count ~= nil and
    before_pointer ~= 0 and before_count > 0 and before_count <= 64 then
  for index = 0, before_count - 1 do
    before_values[index + 1] =
      sd.debug.read_float(before_pointer + index * 4)
  end
end
local all_resolved = true
for _ = 1, {query_count} do
  local details = sd.bots.get_loadout_details({bot_id})
  if type(details) ~= 'table' or
      type(details.primary) ~= 'table' or
      details.primary.build_id_resolved ~= true or
      details.primary.mana_cost_resolved ~= true then
    all_resolved = false
  else
    validate_schema(details)
  end
end
local after_spell = sd.debug.read_i32(progression + current_offset)
local after_pointer = sd.debug.read_u32(progression + values_offset)
local after_count = sd.debug.read_i32(progression + count_offset)
local values_unchanged =
  before_count == after_count and before_count > 0 and before_count <= 64
if values_unchanged then
  for index = 0, after_count - 1 do
    local after_value =
      sd.debug.read_float(after_pointer + index * 4)
    if after_value ~= before_values[index + 1] then
      values_unchanged = false
      break
    end
  end
end
emit('all_resolved', all_resolved)
emit('unexpected_fields', unexpected)
emit('forbidden_keys', forbidden_keys)
emit('address_strings', address_strings)
emit('current_spell_id', before_spell)
emit('stat_count', before_count)
emit('spell_unchanged', before_spell == after_spell)
emit('pointer_unchanged', before_pointer == after_pointer)
emit('count_unchanged', before_count == after_count)
emit('values_unchanged', values_unchanged)
""",
        timeout=30.0,
    )
    result = {
        "query_count": query_count,
        "all_resolved": as_bool(values.get("all_resolved")),
        "unexpected_fields": as_int(values.get("unexpected_fields")),
        "forbidden_keys": as_int(values.get("forbidden_keys")),
        "address_strings": as_int(values.get("address_strings")),
        "current_spell_id": as_int(values.get("current_spell_id"), -1),
        "stat_count": as_int(values.get("stat_count")),
        "spell_unchanged": as_bool(values.get("spell_unchanged")),
        "pointer_unchanged": as_bool(values.get("pointer_unchanged")),
        "count_unchanged": as_bool(values.get("count_unchanged")),
        "values_unchanged": as_bool(values.get("values_unchanged")),
    }
    require(result["all_resolved"], f"repeated loadout query unresolved: {result}")
    require(
        result["unexpected_fields"] == 0
        and result["forbidden_keys"] == 0
        and result["address_strings"] == 0,
        f"loadout result exposed unexpected/native fields: {result}",
    )
    require(
        result["stat_count"] > 0
        and result["spell_unchanged"]
        and result["pointer_unchanged"]
        and result["count_unchanged"]
        and result["values_unchanged"],
        f"loadout observations mutated the active primary: {result}",
    )
    return result


def cooldown_transition_probe(
    session: OwnedSoloSession,
    bot_id: int,
    entry_id: int,
) -> dict[str, Any]:
    values = session.values(
        f"""
local function emit(key, value)
  print(key .. '=' .. tostring(value))
end
local function offset(name)
  return tonumber(sd.debug.layout_offset(name)) or 0
end
local function loadout_row()
  local details = sd.bots.get_loadout_details({bot_id}) or {{}}
  for _, row in ipairs(details.secondaries or {{}}) do
    if tonumber(row.entry_id) == {entry_id} then return row end
  end
  return nil
end
local bot = sd.bots.get_state({bot_id})
local progression =
  type(bot) == 'table' and
  (tonumber(bot.progression_runtime_state_address) or 0) or 0
local table_address =
  progression ~= 0 and
  (tonumber(sd.debug.read_u32(
    progression +
    offset('standalone_wizard_progression_table_base'))) or 0) or 0
local stride = offset('standalone_wizard_progression_entry_stride')
local current_offset =
  offset('standalone_wizard_progression_cooldown_current')
local cap_offset =
  offset('standalone_wizard_progression_cooldown_cap')
local row_address = table_address + {entry_id} * stride
local original_current = sd.debug.read_float(row_address + current_offset)
local raw_cap = sd.debug.read_float(row_address + cap_offset)
local write_cap =
  raw_cap ~= nil and
  sd.debug.write_float(row_address + current_offset, raw_cap)
local cap_row = loadout_row() or {{}}
emit('raw_cap', raw_cap)
emit('write_cap', write_cap)
emit('cap.seconds', cap_row.cooldown_seconds)
emit('cap.remaining', cap_row.cooldown_remaining_seconds)
local half = (tonumber(raw_cap) or 0) * 0.5
local write_half =
  sd.debug.write_float(row_address + current_offset, half)
local half_row = loadout_row() or {{}}
emit('raw_half', half)
emit('write_half', write_half)
emit('half.remaining', half_row.cooldown_remaining_seconds)
local write_zero =
  sd.debug.write_float(row_address + current_offset, 0.0)
local zero_row = loadout_row() or {{}}
emit('write_zero', write_zero)
emit('zero.remaining', zero_row.cooldown_remaining_seconds)
emit(
  'restore',
  sd.debug.write_float(
    row_address + current_offset,
    tonumber(original_current) or 0.0))
"""
    )
    raw_cap = as_float(values.get("raw_cap"))
    cap_seconds = as_float(values.get("cap.seconds"))
    cap_remaining = as_float(values.get("cap.remaining"))
    raw_half = as_float(values.get("raw_half"))
    half_remaining = as_float(values.get("half.remaining"))
    zero_remaining = as_float(values.get("zero.remaining"))
    result = {
        "entry_id": entry_id,
        "native_storage": "IEEE-754 float ticks",
        "ticks_per_second": (
            raw_cap / cap_seconds if cap_seconds > 0.0 else math.nan
        ),
        "raw_cap_ticks": raw_cap,
        "cooldown_seconds": cap_seconds,
        "transitions": [
            {
                "raw_current_ticks": raw_cap,
                "remaining_seconds": cap_remaining,
            },
            {
                "raw_current_ticks": raw_half,
                "remaining_seconds": half_remaining,
            },
            {
                "raw_current_ticks": 0.0,
                "remaining_seconds": zero_remaining,
            },
        ],
    }
    require(
        all(
            values.get(key) == "true"
            for key in ("write_cap", "write_half", "write_zero", "restore")
        ),
        f"cooldown row writes failed for {entry_id}: {values}",
    )
    require(
        math.isfinite(raw_cap)
        and raw_cap > 0.0
        and math.isclose(cap_remaining, cap_seconds, abs_tol=1e-4)
        and math.isclose(
            half_remaining,
            cap_seconds * 0.5,
            abs_tol=1e-4,
        )
        and math.isclose(zero_remaining, 0.0, abs_tol=1e-4),
        f"cooldown transitions did not track native rows: {result}",
    )
    require(
        math.isclose(result["ticks_per_second"], 100.0, abs_tol=1e-4),
        f"cooldown native units were not 100 ticks/second: {result}",
    )
    return result


def roll_next_skill_choices(
    session: OwnedSoloSession,
    bot_id: int,
) -> dict[str, Any]:
    values = session.values(
        f"""
local function emit(key, value)
  print(key .. '=' .. tostring(value))
end
local bot = sd.bots.get_state({bot_id})
local progression =
  type(bot) == 'table' and
  (tonumber(bot.progression_runtime_state_address) or 0) or 0
local level_offset =
  tonumber(sd.debug.layout_offset('progression_level')) or 0
local next_xp_offset =
  tonumber(sd.debug.layout_offset(
    'progression_next_xp_threshold')) or 0
local current_level =
  progression ~= 0 and
  (tonumber(sd.debug.read_i32(
    progression + level_offset)) or 0) or 0
local next_xp =
  progression ~= 0 and
  (tonumber(sd.debug.read_float(
    progression + next_xp_offset)) or 0) or 0
local target_level = math.max(2, current_level + 1)
local target_xp = math.max(0, math.floor(next_xp + 10))
local sync_ok = sd.bots.debug_sync_level_up({{
  level = target_level,
  experience = target_xp,
}})
local choices = sd.bots.get_skill_choices({bot_id}) or {{}}
local details = sd.bots.get_loadout_details({bot_id}) or {{}}
emit('sync_ok', sync_ok)
emit('level', target_level)
emit('experience', target_xp)
emit('pending', choices.pending)
emit('generation', choices.generation)
emit('count', #(choices.options or {{}}))
local has_weld = false
for index, option in ipairs(choices.options or {{}}) do
  emit('option.' .. index, option.id)
  if tonumber(option.id) == 52 then has_weld = true end
end
emit('has_weld', has_weld)
emit('pending_build', details.pending_weld_build_id)
emit(
  'pending_build_resolved',
  details.pending_weld_build_id_resolved)
"""
    )
    options = [
        as_int(values.get(f"option.{index}"), -1)
        for index in range(1, as_int(values.get("count")) + 1)
    ]
    result = {
        "sync_ok": as_bool(values.get("sync_ok")),
        "level": as_int(values.get("level")),
        "experience": as_int(values.get("experience")),
        "pending": as_bool(values.get("pending")),
        "generation": as_int(values.get("generation")),
        "options": options,
        "has_weld": as_bool(values.get("has_weld")),
        "pending_build": as_int(values.get("pending_build")),
        "pending_build_resolved": as_bool(
            values.get("pending_build_resolved")
        ),
    }
    require(
        result["sync_ok"]
        and result["pending"]
        and result["generation"] > 0
        and bool(result["options"]),
        f"native skill roll failed: {result}",
    )
    return result


def roll_weld_offer(
    session: OwnedSoloSession,
    bot_id: int,
    max_rolls: int = 64,
) -> dict[str, Any]:
    history: list[dict[str, Any]] = []
    for _ in range(max_rolls):
        record = roll_next_skill_choices(session, bot_id)
        history.append(record)
        if record["has_weld"]:
            require(
                record["pending_build_resolved"]
                and record["pending_build"] in WELD_PAIRS,
                f"option 52 did not carry its generation-scoped build: {record}",
            )
            return {
                "roll_count": len(history),
                "level": record["level"],
                "generation": record["generation"],
                "options": record["options"],
                "captured_build_id": record["pending_build"],
                "history": history,
            }

        preferred_primary = next(
            (
                option_id
                for option_id in (16, 24, 32, 40, 8)
                if option_id in record["options"]
            ),
            None,
        )
        selected_option = (
            preferred_primary
            if preferred_primary is not None
            else record["options"][0]
        )
        values = session.values(
            f"""
local ok, result = pcall(
  sd.bots.choose_skill,
  {{
    id = {bot_id},
    generation = {record["generation"]},
    option_id = {selected_option},
  }})
print('call_ok=' .. tostring(ok))
print('choice_ok=' .. tostring(result))
"""
        )
        require(
            as_bool(values.get("call_ok"))
            and as_bool(values.get("choice_ok")),
            "native prerequisite choice apply failed: "
            f"record={record}; result={values}",
        )
        record["applied_prerequisite_option"] = selected_option
    raise LiveNativeSpellStatsProbeFailure(
        f"native rolls did not surface option 52 in {max_rolls} attempts"
    )


def apply_captured_weld(
    session: OwnedSoloSession,
    bot_id: int,
    offer: dict[str, Any],
) -> dict[str, Any]:
    captured = int(offer["captured_build_id"])
    tampered = 1001 if captured != 1001 else 1000
    generation = int(offer["generation"])
    values = session.values(
        f"""
local function emit(key, value)
  print(key .. '=' .. tostring(value))
end
local bot = sd.bots.get_state({bot_id})
local progression =
  type(bot) == 'table' and
  (tonumber(bot.progression_runtime_state_address) or 0) or 0
local special_offset =
  tonumber(sd.debug.layout_offset(
    'progression_special_choice_argument')) or 0
local tamper_ok =
  progression ~= 0 and
  sd.debug.write_u32(
    progression + special_offset,
    {tampered})
local call_ok, choice_result = pcall(
  sd.bots.choose_skill,
  {{
    id = {bot_id},
    generation = {generation},
    option_id = 52,
  }})
local details = sd.bots.get_loadout_details({bot_id}) or {{}}
local primary = details.primary or {{}}
emit('tamper_ok', tamper_ok)
emit('choice_call_ok', call_ok)
emit('choice_result', choice_result)
emit('build_id', primary.build_id)
emit('build_id_resolved', primary.build_id_resolved)
emit('entry_id', primary.entry_id)
emit('combo_entry_id', primary.combo_entry_id)
emit('mana_cost', primary.mana_cost)
emit('mana_cost_resolved', primary.mana_cost_resolved)
emit('range_max', primary.range_max)
emit('range_resolved', primary.range_resolved)
emit('pending_resolved', details.pending_weld_build_id_resolved)
"""
    )
    result = {
        "captured_build_id": captured,
        "tampered_post_capture_value": tampered,
        "tamper_ok": as_bool(values.get("tamper_ok")),
        "choice_call_ok": as_bool(values.get("choice_call_ok")),
        "choice_result": as_bool(values.get("choice_result")),
        "build_id": as_int(values.get("build_id")),
        "build_id_resolved": as_bool(values.get("build_id_resolved")),
        "entry_id": as_int(values.get("entry_id"), -1),
        "combo_entry_id": as_int(values.get("combo_entry_id"), -1),
        "mana_cost": as_float(values.get("mana_cost"), 0.0),
        "mana_cost_resolved": as_bool(values.get("mana_cost_resolved")),
        "range_max": as_float(values.get("range_max"), 0.0),
        "range_resolved": as_bool(values.get("range_resolved")),
        "pending_resolved_after_apply": as_bool(
            values.get("pending_resolved")
        ),
    }
    expected_pair = WELD_PAIRS[captured]
    require(
        result["tamper_ok"]
        and result["choice_call_ok"]
        and result["choice_result"],
        f"captured weld application failed: {result}",
    )
    require(
        result["build_id_resolved"]
        and result["build_id"] == captured
        and result["build_id"] != tampered
        and (result["entry_id"], result["combo_entry_id"]) == expected_pair,
        f"weld apply did not use its generation capture: {result}",
    )
    require(
        result["mana_cost_resolved"]
        and result["mana_cost"] > 0.0
        and result["range_resolved"]
        and result["range_max"] > 0.0
        and not result["pending_resolved_after_apply"],
        f"welded loadout details were incomplete: {result}",
    )
    return result


def refresh_profile_and_reconstruct_weld(
    session: OwnedSoloSession,
    bot_id: int,
    details: dict[str, Any],
) -> dict[str, Any]:
    primary = details["primary"]
    secondary_literal = ", ".join(str(entry) for entry in PROBE_SECONDARIES)
    values = session.values(
        f"""
local bot = sd.bots.get_state({bot_id}) or {{}}
local profile = bot.profile or {{}}
local ok = sd.bots.update({{
  id = {bot_id},
  profile = {{
    element_id = 4,
    discipline_id = 2,
    level = tonumber(profile.level) or 1,
    experience = tonumber(profile.experience) or 0,
    loadout = {{
      primary_entry_index = {int(primary["entry_id"])},
      primary_combo_entry_index = {int(primary["combo_entry_id"])},
      secondary_entry_indices = {{ {secondary_literal} }},
    }},
  }},
}})
print('ok=' .. tostring(ok))
"""
    )
    require(values.get("ok") == "true", f"profile refresh failed: {values}")
    wait_for_materialized_bot(session, bot_id)
    rebuilt = wait_for_ready_loadout(
        session,
        bot_id,
        expected_build_id=int(primary["build_id"]),
        expected_pair=(
            int(primary["entry_id"]),
            int(primary["combo_entry_id"]),
        ),
    )
    return {
        "build_id": rebuilt["primary"]["build_id"],
        "entry_id": rebuilt["primary"]["entry_id"],
        "combo_entry_id": rebuilt["primary"]["combo_entry_id"],
        "mana_cost": rebuilt["primary"]["mana_cost"],
        "range_max": rebuilt["primary"]["range_max"],
        "reconstructed_after_profile_refresh": True,
    }


def run_probe(session: OwnedSoloSession) -> dict[str, Any]:
    launch = session.launch()
    session.wait_for_pipe()
    hub = session.wait_for_hub()
    bot_id = create_probe_bot(session)
    wait_for_materialized_bot(session, bot_id)
    preparation = prepare_native_rows(session, bot_id)

    base = wait_for_ready_loadout(
        session,
        bot_id,
        expected_build_id=8,
        expected_pair=(8, 8),
    )
    base_mutation = schema_and_primary_mutation_probe(session, bot_id)
    cooldowns = [
        cooldown_transition_probe(session, bot_id, entry_id)
        for entry_id in (15, 48)
    ]

    offer = roll_weld_offer(session, bot_id)
    captured_build = int(offer["captured_build_id"])
    pending = query_loadout_details(session, bot_id)
    require(
        pending["primary"]["build_id"] == 8
        and pending["pending_weld_build_id_resolved"]
        and pending["pending_weld_build_id"] == captured_build,
        f"pending weld changed the active primary or lost capture: {pending}",
    )
    weld_apply = apply_captured_weld(session, bot_id, offer)
    welded = wait_for_ready_loadout(
        session,
        bot_id,
        expected_build_id=captured_build,
        expected_pair=WELD_PAIRS[captured_build],
    )
    weld_mutation = schema_and_primary_mutation_probe(session, bot_id)
    reconstruction = refresh_profile_and_reconstruct_weld(
        session,
        bot_id,
        welded,
    )

    log_tail = session.tail_loader_log()
    joined_log = "\n".join(log_tail).lower()
    for token in BAD_LOG_TOKENS:
        require(
            token not in joined_log,
            f"loader log contains failure token {token!r}",
        )

    return {
        "passed": True,
        "fresh_session": True,
        "instance": session.instance,
        "process_id": session.process_ids[0],
        "audio_disabled": launch.get("audioDisabled") is True,
        "headless": launch.get("headlessEnabled") is True,
        "ports": {
            "local": as_int(launch.get("localPort")),
            "unused_remote": as_int(launch.get("unusedRemotePort")),
        },
        "hub": hub,
        "bot_id": bot_id,
        "preparation": preparation,
        "base_primary": base["primary"],
        "base_window": base["window"],
        "secondary_costs": [
            {
                "slot": row["slot"],
                "entry_id": row["entry_id"],
                "mana_cost": row["mana_cost"],
            }
            for row in base["secondaries"]
        ],
        "base_observation_safety": base_mutation,
        "cooldowns": cooldowns,
        "weld_offer": {
            key: value
            for key, value in offer.items()
            if key != "history"
        },
        "weld_apply": weld_apply,
        "welded_primary": welded["primary"],
        "welded_window": welded["window"],
        "weld_observation_safety": weld_mutation,
        "post_refresh_reconstruction": reconstruction,
        "no_exposed_addresses": (
            base_mutation["forbidden_keys"] == 0
            and base_mutation["address_strings"] == 0
            and weld_mutation["forbidden_keys"] == 0
            and weld_mutation["address_strings"] == 0
        ),
        "loader_log_tail": log_tail,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--instance",
        default=(
            f"mlp2-{os.getpid()}-"
            f"{int(time.time() * 1000) % 10_000_000}"
        ),
    )
    args = parser.parse_args()

    session = OwnedSoloSession(args.instance)
    result: dict[str, Any]
    exit_code = 0
    try:
        result = run_probe(session)
    except BaseException as exc:  # noqa: BLE001 - retain live diagnostics.
        result = {
            "passed": False,
            "fresh_session": True,
            "instance": session.instance,
            "error": str(exc),
            "loader_log_tail": session.tail_loader_log(),
        }
        exit_code = 1
    finally:
        try:
            result["cleanup"] = session.close()
        except BaseException as cleanup_exc:  # noqa: BLE001
            result["cleanup_error"] = str(cleanup_exc)
            result["passed"] = False
            exit_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result.get("passed"):
        costs = ", ".join(
            f"{entry['entry_id']}={entry['mana_cost']:g}"
            for entry in result["secondary_costs"]
        )
        cooldowns = ", ".join(
            f"{entry['entry_id']}={entry['raw_cap_ticks']:g} ticks/"
            f"{entry['cooldown_seconds']:g}s"
            for entry in result["cooldowns"]
        )
        print(
            "PASS: live semantic loadout probe; "
            f"base={result['base_primary']['mana_cost']:g}, "
            f"weld={result['welded_primary']['build_id']}:"
            f"{result['welded_primary']['mana_cost']:g}"
        )
        print(f"Secondary costs: {costs}")
        print(f"Cooldown units: {cooldowns}")
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live semantic loadout probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
