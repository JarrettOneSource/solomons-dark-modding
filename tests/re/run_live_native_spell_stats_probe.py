#!/usr/bin/env python3
"""Live RE probe for native live bot mana resolution.

This test intentionally uses the mod launcher's staged runtime and the Lua
memory bridge. It verifies that bot primary mana resolution is backed by the
live Skills_Wizard progression stat output, not staged wizard-skill files or
loader-owned mana tables.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cast_state_probe as csp  # noqa: E402


OUTPUT_PATH = ROOT / "runtime" / "live_native_spell_stats_probe.json"
RUNTIME_BINARY_LAYOUT_PATH = ROOT / "runtime/stage/.sdmod/config/binary-layout.ini"
ACTIVE_BOTS_CONFIG_PATH = ROOT / "mods/lua_bots/config/active_bots.txt"

PRIMARY_SKILLS = [
    {"name": "fire", "element_id": 0, "skill_id": 0x3F3},
    {"name": "water", "element_id": 1, "skill_id": 0x3F4},
    {"name": "earth", "element_id": 2, "skill_id": 0x3F6},
    {"name": "air", "element_id": 3, "skill_id": 0x3F5},
    {"name": "ether", "element_id": 4, "skill_id": 0x3F2},
]

BAD_LOG_TOKENS = (
    "failed to resolve native spell mana",
    "failed to resolve native spell mana",
    "cast rejected for unknown mana cost",
)

class LiveNativeSpellStatsProbeFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class SkillProbeResult:
    name: str
    skill_id: int
    mana_write: dict[str, str]
    cast_result: dict[str, str]


def float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(str(value))
    except (TypeError, ValueError):
        return None


def read_runtime_layout_offset(name: str) -> int:
    text = RUNTIME_BINARY_LAYOUT_PATH.read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return int(value.strip(), 0)
    raise LiveNativeSpellStatsProbeFailure(f"Unable to find {name!r} in {RUNTIME_BINARY_LAYOUT_PATH}")


def force_bot_mana(bot_id: int, current: float, maximum: float) -> dict[str, str]:
    mp_offset = read_runtime_layout_offset("progression_mp")
    max_mp_offset = read_runtime_layout_offset("progression_max_mp")
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local bot = sd.bots.get_state({bot_id})
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(bot) ~= 'table' then
  emit('ok', false)
  emit('error', 'bot_not_found')
  return
end
local progression = tonumber(bot.progression_runtime_state_address) or 0
if progression == 0 then
  emit('ok', false)
  emit('error', 'missing_progression_runtime')
  return
end
emit('before_mp', bot.mp)
emit('before_max_mp', bot.max_mp)
emit('mp_ok', sd.debug.write_float(progression + {mp_offset}, {current}))
emit('max_mp_ok', sd.debug.write_float(progression + {max_mp_offset}, {maximum}))
local refreshed = sd.bots.get_state({bot_id}) or {{}}
emit('after_mp', refreshed.mp)
emit('after_max_mp', refreshed.max_mp)
emit('ok', refreshed.mp ~= nil and refreshed.max_mp ~= nil)
""".strip()
        )
    )


def force_bot_resources(
    bot_id: int,
    hp: float,
    max_hp: float,
    mp: float,
    max_mp: float,
) -> dict[str, str]:
    hp_offset = read_runtime_layout_offset("progression_hp")
    max_hp_offset = read_runtime_layout_offset("progression_max_hp")
    mp_offset = read_runtime_layout_offset("progression_mp")
    max_mp_offset = read_runtime_layout_offset("progression_max_mp")
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local bot = sd.bots.get_state({bot_id})
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(bot) ~= 'table' then
  emit('ok', false)
  emit('error', 'bot_not_found')
  return
end
local progression = tonumber(bot.progression_runtime_state_address) or 0
if progression == 0 then
  emit('ok', false)
  emit('error', 'missing_progression_runtime')
  return
end
emit('before_hp', sd.debug.read_float(progression + {hp_offset}))
emit('before_max_hp', sd.debug.read_float(progression + {max_hp_offset}))
emit('before_mp', sd.debug.read_float(progression + {mp_offset}))
emit('before_max_mp', sd.debug.read_float(progression + {max_mp_offset}))
emit('hp_ok', sd.debug.write_float(progression + {hp_offset}, {hp}))
emit('max_hp_ok', sd.debug.write_float(progression + {max_hp_offset}, {max_hp}))
emit('mp_ok', sd.debug.write_float(progression + {mp_offset}, {mp}))
emit('max_mp_ok', sd.debug.write_float(progression + {max_mp_offset}, {max_mp}))
emit('after_hp', sd.debug.read_float(progression + {hp_offset}))
emit('after_max_hp', sd.debug.read_float(progression + {max_hp_offset}))
emit('after_mp', sd.debug.read_float(progression + {mp_offset}))
emit('after_max_mp', sd.debug.read_float(progression + {max_mp_offset}))
emit('ok', true)
""".strip()
        )
    )


def query_bot_resources(bot_id: int) -> dict[str, str]:
    hp_offset = read_runtime_layout_offset("progression_hp")
    max_hp_offset = read_runtime_layout_offset("progression_max_hp")
    mp_offset = read_runtime_layout_offset("progression_mp")
    max_mp_offset = read_runtime_layout_offset("progression_max_mp")
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local bot = sd.bots.get_state({bot_id})
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
if type(bot) ~= 'table' then
  emit('ok', false)
  emit('error', 'bot_not_found')
  return
end
local progression = tonumber(bot.progression_runtime_state_address) or 0
if progression == 0 then
  emit('ok', false)
  emit('error', 'missing_progression_runtime')
  return
end
emit('hp', sd.debug.read_float(progression + {hp_offset}))
emit('max_hp', sd.debug.read_float(progression + {max_hp_offset}))
emit('mp', sd.debug.read_float(progression + {mp_offset}))
emit('max_mp', sd.debug.read_float(progression + {max_mp_offset}))
emit('ok', true)
""".strip()
        )
    )


def queue_skill(bot_id: int, skill_id: int, target_x: float, target_y: float) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit('ok', sd.bots.cast({{
  id = {bot_id},
  kind = 'primary',
  skill_id = {skill_id},
  target = {{ x = {target_x}, y = {target_y} }},
}}))
""".strip()
        )
    )


def queue_default_primary(bot_id: int, target_x: float, target_y: float) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
end
emit('ok', sd.bots.cast({{
  id = {bot_id},
  kind = 'primary',
  target = {{ x = {target_x}, y = {target_y} }},
}}))
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
print('lua_bots_disable_tick=' .. tostring(lua_bots_disable_tick))
""".strip()
        )
    )


def start_testrun_without_waves() -> dict[str, str]:
    scene = csp.query_scene_state()
    if csp.is_settled_scene(scene, "testrun"):
        return {"ok": "true", "already_in_testrun": "true"}
    values = csp.parse_key_values(csp.run_lua("print('ok='..tostring(sd.hub.start_testrun()))"))
    if values.get("ok") != "true":
        raise LiveNativeSpellStatsProbeFailure(f"sd.hub.start_testrun failed: {values}")
    csp.wait_for_scene("testrun", timeout_s=45.0)
    return values


def reject_bad_log_tokens(log_tail: list[str]) -> None:
    joined = "\n".join(log_tail)
    for token in BAD_LOG_TOKENS:
        if token in joined:
            raise LiveNativeSpellStatsProbeFailure(f"loader log contains resolver failure token: {token}")


@contextmanager
def temporary_active_bots_config(active_bot_keys: str):
    """Select probe bot profiles through the mod-local config file.

    The Windows-launched game does not inherit Python's WSL environment, but
    the Lua bot mod reliably reads this repo-local config during startup.
    """
    with csp.temporary_required_lua_mods(csp.LUA_BOT_MOD_ID):
        if not active_bot_keys or active_bot_keys == "default":
            yield
            return

        existed = ACTIVE_BOTS_CONFIG_PATH.exists()
        original_text = ACTIVE_BOTS_CONFIG_PATH.read_text(encoding="utf-8") if existed else None
        ACTIVE_BOTS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ACTIVE_BOTS_CONFIG_PATH.write_text(f"{active_bot_keys}\n", encoding="utf-8")
        try:
            yield
        finally:
            if existed and original_text is not None:
                ACTIVE_BOTS_CONFIG_PATH.write_text(original_text, encoding="utf-8")
            else:
                ACTIVE_BOTS_CONFIG_PATH.unlink(missing_ok=True)


def list_bot_states() -> list[dict[str, str]]:
    values = csp.parse_key_values(
        csp.run_lua(
            """
local bots = sd.bots and sd.bots.get_state and sd.bots.get_state() or {}
local contexts = rawget(_G, "lua_bots_debug")
contexts = type(contexts) == "table" and type(contexts.bots) == "table" and contexts.bots or {}
local function emit(key, value)
  if value == nil then
    print(key .. "=")
  else
    print(key .. "=" .. tostring(value))
  end
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
  local profile = type(context) == "table" and context.bot_profile or nil
  for _, key in ipairs({
    "id","actor_address","progression_runtime_state_address","progression_handle_address",
    "equip_handle_address","equip_runtime_state_address","gameplay_slot","actor_slot",
    "hp","max_hp","mp","max_mp","x","y","state"
  }) do
    emit(prefix .. key, bot[key])
  end
  emit(prefix .. "bot_name", type(context) == "table" and context.bot_name or nil)
  emit(prefix .. "profile_element_id", type(profile) == "table" and profile.element_id or nil)
  emit(prefix .. "profile_discipline_id", type(profile) == "table" and profile.discipline_id or nil)
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


def wait_for_materialized_bots(min_count: int, timeout_s: float = 45.0) -> list[dict[str, str]]:
    deadline = time.time() + timeout_s
    last: list[dict[str, str]] = []
    while time.time() < deadline:
        last = [
            bot for bot in list_bot_states()
            if csp.int_value(bot, "actor_address") != 0
        ]
        if len(last) >= min_count:
            return last
        time.sleep(0.25)
    raise LiveNativeSpellStatsProbeFailure(
        f"Timed out waiting for {min_count} materialized bots. Last={last}"
    )


def find_bot_for_element(bots: list[dict[str, str]], element_id: int) -> dict[str, str]:
    for bot in bots:
        if csp.int_value(bot, "profile_element_id") == element_id:
            return bot
    raise LiveNativeSpellStatsProbeFailure(
        f"No materialized bot owns element_id={element_id}. Bots={bots}"
    )


def run_default_primary_refresh_probe(bot: dict[str, str]) -> dict[str, Any]:
    bot_id = csp.int_value(bot, "id")
    bot_x = csp.float_value(bot, "x")
    bot_y = csp.float_value(bot, "y")
    if bot_id == 0 or bot_x != bot_x or bot_y != bot_y:
        raise LiveNativeSpellStatsProbeFailure(f"default-primary bot has invalid state: {bot}")

    forced = force_bot_resources(bot_id, hp=37.0, max_hp=50.0, mp=90.0, max_mp=100.0)
    if forced.get("ok") != "true":
        raise LiveNativeSpellStatsProbeFailure(f"failed to force default-primary resources: {forced}")

    cast_result = queue_default_primary(bot_id, bot_x + 120.0, bot_y)
    if cast_result.get("ok") != "true":
        raise LiveNativeSpellStatsProbeFailure(f"default-primary cast failed: {cast_result}")

    time.sleep(0.45)
    after = query_bot_resources(bot_id)
    if after.get("ok") != "true":
        raise LiveNativeSpellStatsProbeFailure(f"failed to query default-primary resources: {after}")

    hp_after = float_or_none(after.get("hp"))
    max_hp_after = float_or_none(after.get("max_hp"))
    mp_after = float_or_none(after.get("mp"))
    max_mp_after = float_or_none(after.get("max_mp"))
    if hp_after is None or max_hp_after is None or mp_after is None or max_mp_after is None:
        raise LiveNativeSpellStatsProbeFailure(f"default-primary resources were unreadable: {after}")
    if abs(hp_after - 37.0) > 0.25 or abs(max_hp_after - 50.0) > 0.25:
        raise LiveNativeSpellStatsProbeFailure(
            f"default-primary refresh did not preserve HP ratio/current state: forced={forced} after={after}"
        )
    if max_mp_after <= 0.0 or mp_after < -0.001 or mp_after > max_mp_after + 0.001:
        raise LiveNativeSpellStatsProbeFailure(
            f"default-primary refresh left invalid mana state: forced={forced} after={after}"
        )

    return {
        "bot_id": bot_id,
        "force_resources": forced,
        "cast_result": cast_result,
        "resources_after": after,
    }


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
        result["navigation"].append({"step": "launch", "process_id": process_id})

        csp.drive_new_game_flow(process_id, element=element, discipline=discipline)
        result["navigation"].append({"step": "hub_ready", "flow": {"mode": "new_game"}})
        if start_waves:
            csp.start_run_and_waves()
            csp.boost_player_survival()
            result["navigation"].append({"step": "testrun_started_with_waves"})
        else:
            result["testrun_start"] = start_testrun_without_waves()
            result["navigation"].append({"step": "testrun_started_without_waves"})

        if post_testrun_settle_seconds > 0.0:
            time.sleep(post_testrun_settle_seconds)

        bots = wait_for_materialized_bots(min_count)
    result["bots_initial"] = bots
    result["bot_initial"] = bots[0]
    return result


def drive_to_materialized_bot(element: str, discipline: str) -> dict[str, Any]:
    return drive_to_materialized_bots(
        element,
        discipline,
        active_bot_keys="default",
        min_count=1,
    )


def run_probe(element: str, discipline: str) -> dict[str, Any]:
    result = drive_to_materialized_bots(
        element,
        discipline,
        active_bot_keys="all",
        min_count=len(PRIMARY_SKILLS),
        start_waves=False,
        post_testrun_settle_seconds=3.0,
    )
    bots = [dict(bot) for bot in result["bots_initial"]]
    result["tick_gate"] = set_lua_bot_tick_enabled(False)
    fire_bot = find_bot_for_element(bots, 0)
    result["default_primary_refresh_probe"] = run_default_primary_refresh_probe(fire_bot)
    skill_results: list[SkillProbeResult] = []
    for spec in PRIMARY_SKILLS:
        bot = find_bot_for_element(bots, int(spec["element_id"]))
        bot_id = csp.int_value(bot, "id")
        bot_x = csp.float_value(bot, "x")
        bot_y = csp.float_value(bot, "y")
        if bot_id == 0 or bot_x != bot_x or bot_y != bot_y:
            raise LiveNativeSpellStatsProbeFailure(f"materialized bot has invalid state: {bot}")
        target_x = bot_x + 160.0
        target_y = bot_y
        mana_write = force_bot_mana(bot_id, 999.0, 999.0)
        if mana_write.get("ok") != "true":
            raise LiveNativeSpellStatsProbeFailure(f"failed to force mana for {spec['name']}: {mana_write}")

        cast_result = queue_skill(bot_id, int(spec["skill_id"]), target_x, target_y)
        if cast_result.get("ok") not in {"true", "false"}:
            raise LiveNativeSpellStatsProbeFailure(
                f"{spec['name']} cast returned an invalid Lua result: {cast_result}"
            )

        skill_results.append(
            SkillProbeResult(
                name=str(spec["name"]),
                skill_id=int(spec["skill_id"]),
                mana_write=mana_write,
                cast_result=cast_result,
            )
        )
        time.sleep(0.35)

    log_tail = tail_loader_log()
    reject_bad_log_tokens(log_tail)
    result["skill_results"] = [entry.__dict__ for entry in skill_results]
    result["bots_final"] = list_bot_states()
    result["bot_final"] = csp.query_bot_state()
    result["loader_log_tail"] = log_tail
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--element", default="fire", choices=sorted(csp.CREATE_ELEMENT_CENTERS))
    parser.add_argument("--discipline", default="mind", choices=sorted(csp.CREATE_DISCIPLINE_CENTERS))
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true", help="Only print structured JSON.")
    parser.add_argument("--keep-running", action="store_true", help="Leave the game process running after the probe.")
    args = parser.parse_args()

    result: dict[str, Any]
    exit_code = 0
    try:
        result = run_probe(args.element, args.discipline)
        result["passed"] = True
    except Exception as exc:  # noqa: BLE001 - probe preserves diagnostics in JSON.
        result = {
            "passed": False,
            "error": str(exc),
            "loader_log_tail": tail_loader_log(),
        }
        exit_code = 1
    finally:
        if not args.keep_running:
            csp.stop_game()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result.get("passed"):
        skills = ", ".join(entry["name"] for entry in result.get("skill_results", []))
        print(f"PASS: live native spell-stat mana probe queued all primary skills: {skills}")
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live native spell-stat mana probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
