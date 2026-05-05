#!/usr/bin/env python3
"""Live regression proving bot skill upgrades feed the default combat cast path."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cast_state_probe as csp  # noqa: E402
import probe_bot_skill_choice_stress as stress  # noqa: E402
from run_live_native_spell_stats_probe import (  # noqa: E402
    force_bot_mana,
    list_bot_states,
    queue_default_primary,
)


OUTPUT_PATH = ROOT / "runtime" / "live_bot_skill_upgrade_combat_flow_probe.json"
FIRE_ELEMENT_ID = 0
FIRE_PRIMARY_ENTRY_INDEX = 0x10
FIREBALL_OPTION_ID = 0x10
FIREBALL_BUILD_SKILL_ID = 0x3F3
FORCED_MANA = 999.0
CAST_SIGNAL_TIMEOUT_SECONDS = 8.0
DEFAULT_MAX_LEVEL_STEPS = 25
PRIMARY_STAT_OUTPUT_LIMIT = 6

MANA_PREPARED_RE = re.compile(
    r"mana prepared\. bot_id=(?P<bot_id>\d+) skill_id=(?P<skill_id>-?\d+) "
    r"kind=(?P<kind>[a-z_]+) progression_level=(?P<level>\d+) "
    r"cost=(?P<cost>[0-9.+\-eE]+) progression_runtime=(?P<progression>0x[0-9A-Fa-f]+|\d+)"
)
LOADOUT_RE = re.compile(
    r"skills_wizard_loadout begin progression=(?P<progression>0x[0-9A-Fa-f]+|\d+) "
    r"primary_entry=(?P<primary>\d+) combo_entry=(?P<combo>\d+) spell_id=(?P<spell_id>\d+)"
)
BAD_LOG_TOKENS = (
    "failed to resolve native spell mana",
    "cast rejected for unknown mana cost",
)


class BotSkillUpgradeCombatFlowProbeFailure(RuntimeError):
    pass


def parse_int_text(value: object, default: int = 0) -> int:
    text = str(value or "").strip()
    if not text:
        return default
    try:
        return int(text, 0)
    except ValueError:
        return int(float(text))


def read_loader_log_lines() -> list[str]:
    if not csp.LOADER_LOG.exists():
        return []
    return csp.LOADER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()


def parse_mana_prepared(line: str) -> dict[str, Any] | None:
    match = MANA_PREPARED_RE.search(line)
    if not match:
        return None
    return {
        "line": line,
        "bot_id": int(match.group("bot_id")),
        "skill_id": int(match.group("skill_id")),
        "kind": match.group("kind"),
        "progression_level": int(match.group("level")),
        "cost": float(match.group("cost")),
        "progression_runtime": parse_int_text(match.group("progression")),
    }


def parse_loadout(line: str) -> dict[str, Any] | None:
    match = LOADOUT_RE.search(line)
    if not match:
        return None
    return {
        "line": line,
        "progression_runtime": parse_int_text(match.group("progression")),
        "primary_entry": int(match.group("primary")),
        "combo_entry": int(match.group("combo")),
        "spell_id": int(match.group("spell_id")),
    }


def float_text(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def query_primary_stat_output(progression_runtime: int) -> dict[str, Any]:
    values_offset = csp.read_runtime_layout_offset("progression_primary_stat_values")
    count_offset = csp.read_runtime_layout_offset("progression_primary_stat_count")
    values = csp.parse_key_values(
        csp.run_lua(
            f"""
local progression = {progression_runtime}
local values_offset = {values_offset}
local count_offset = {count_offset}
local limit = {PRIMARY_STAT_OUTPUT_LIMIT}
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
local values = progression ~= 0 and (tonumber(sd.debug.read_u32(progression + values_offset)) or 0) or 0
local count = progression ~= 0 and (tonumber(sd.debug.read_i32(progression + count_offset)) or 0) or 0
emit('progression', progression)
emit('values_address', values)
emit('count', count)
emit('available', progression ~= 0 and values ~= 0 and count >= 2)
if values ~= 0 and count > 0 then
  for index = 0, math.min(count, limit) - 1 do
    emit('value_' .. tostring(index), sd.debug.read_float(values + (index * 4)))
  end
end
""".strip()
        )
    )
    count = parse_int_text(values.get("count"))
    output_values = [
        float_text(values.get(f"value_{index}"))
        for index in range(min(count, PRIMARY_STAT_OUTPUT_LIMIT))
    ]
    return {
        "available": values.get("available") == "true",
        "progression": parse_int_text(values.get("progression")),
        "values_address": parse_int_text(values.get("values_address")),
        "count": count,
        "values": output_values,
        "damage": output_values[0] if len(output_values) > 0 else 0.0,
        "mana_cost": output_values[1] if len(output_values) > 1 else 0.0,
    }


def find_bot_summary_by_element(summary: dict[str, str], element_id: int) -> dict[str, int | str]:
    for index in range(1, stress.int_value(summary, "bot.count") + 1):
        if stress.int_value(summary, f"bot.{index}.element_id", -1) == element_id:
            return {
                "index": index,
                "id": stress.int_value(summary, f"bot.{index}.id"),
                "name": summary.get(f"bot.{index}.name", ""),
                "element_id": element_id,
                "primary_entry_index": stress.int_value(summary, f"bot.{index}.primary_entry_index"),
                "progression": stress.int_value(summary, f"bot.{index}.progression"),
            }
    raise BotSkillUpgradeCombatFlowProbeFailure(
        f"no materialized bot found for element_id={element_id}: {summary}"
    )


def find_live_bot(bot_id: int) -> dict[str, str]:
    for bot in list_bot_states():
        if stress.int_value(bot, "id") == bot_id:
            return bot
    raise BotSkillUpgradeCombatFlowProbeFailure(f"bot {bot_id} is not present in live bot state")


def wait_for_cast_evidence(
    bot_id: int,
    progression_runtime: int,
    start_line_count: int,
) -> dict[str, Any]:
    deadline = time.time() + CAST_SIGNAL_TIMEOUT_SECONDS
    last_tail: list[str] = []
    while time.time() < deadline:
        lines = read_loader_log_lines()
        last_tail = lines[-80:]
        prepared_matches: list[dict[str, Any]] = []
        loadout_matches: list[dict[str, Any]] = []
        for line in lines[start_line_count:]:
            prepared = parse_mana_prepared(line)
            if (
                prepared is not None
                and prepared["bot_id"] == bot_id
                and prepared["skill_id"] == FIREBALL_BUILD_SKILL_ID
                and prepared["progression_runtime"] == progression_runtime
            ):
                prepared_matches.append(prepared)

            loadout = parse_loadout(line)
            if (
                loadout is not None
                and loadout["progression_runtime"] == progression_runtime
                and loadout["primary_entry"] == FIRE_PRIMARY_ENTRY_INDEX
                and loadout["combo_entry"] == FIRE_PRIMARY_ENTRY_INDEX
                and loadout["spell_id"] == FIREBALL_BUILD_SKILL_ID
            ):
                loadout_matches.append(loadout)

        if prepared_matches:
            return {
                "mana_prepared": prepared_matches[-1],
                "skills_wizard_loadout": loadout_matches[-1] if loadout_matches else None,
            }
        time.sleep(0.15)

    raise BotSkillUpgradeCombatFlowProbeFailure(
        "timed out waiting for Fireball mana-prepared evidence; "
        f"tail={json.dumps(last_tail[-20:], indent=2)}"
    )


def queue_default_fire_cast(bot_id: int, progression_runtime: int) -> dict[str, Any]:
    bot = find_live_bot(bot_id)
    bot_x = stress.float_value(bot, "x")
    bot_y = stress.float_value(bot, "y")
    if bot_x != bot_x or bot_y != bot_y:
        raise BotSkillUpgradeCombatFlowProbeFailure(f"bot {bot_id} has invalid coordinates: {bot}")

    forced = force_bot_mana(bot_id, FORCED_MANA, FORCED_MANA)
    if forced.get("ok") != "true":
        raise BotSkillUpgradeCombatFlowProbeFailure(f"failed to force bot mana: {forced}")

    start_line_count = len(read_loader_log_lines())
    cast = queue_default_primary(bot_id, bot_x + 160.0, bot_y)
    if cast.get("ok") != "true":
        raise BotSkillUpgradeCombatFlowProbeFailure(f"default primary cast was rejected: {cast}")

    evidence = wait_for_cast_evidence(bot_id, progression_runtime, start_line_count)
    if evidence.get("skills_wizard_loadout") is None:
        raise BotSkillUpgradeCombatFlowProbeFailure(
            f"default Fireball cast did not log Skills_Wizard loadout projection: {evidence}"
        )
    return {
        "bot_state": bot,
        "force_mana": forced,
        "cast": cast,
        "primary_stat_output": query_primary_stat_output(progression_runtime),
        **evidence,
    }


def option_is_fireball_upgrade(option: dict[str, Any]) -> bool:
    return (
        parse_int_text(option.get("id"), -1) == FIREBALL_OPTION_ID
        or str(option.get("skill_file") or "") == "fireball.cfg"
        or str(option.get("name") or "").lower() == "fireball"
    )


def choose_level_options_until_fireball(
    bot_ids: list[int],
    fire_bot_id: int,
    source_progression: int,
    max_level_steps: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    level_steps: list[dict[str, Any]] = []
    selected_fireball: dict[str, Any] | None = None

    for step in range(1, max_level_steps + 1):
        fire_stats = stress.query_progression_stats(fire_bot_id)
        target_level = int(fire_stats["level"]) + 1
        target_xp = int(float(fire_stats["next_xp_threshold"]) + 10.0)
        stress.debug_sync_level_up(target_level, target_xp, source_progression)

        step_record: dict[str, Any] = {
            "step": step,
            "target_level": target_level,
            "target_xp": target_xp,
            "applications": [],
        }
        for bot_id in bot_ids:
            choices = stress.query_choices(bot_id)
            if not choices["pending"] or int(choices["count"]) <= 0:
                raise BotSkillUpgradeCombatFlowProbeFailure(
                    f"bot {bot_id} did not receive pending choices at level {target_level}: {choices}"
                )

            enriched = stress.enrich_choice_options(bot_id, choices)
            option_index = 1
            matched_fireball = False
            if bot_id == fire_bot_id:
                for index, option in enumerate(enriched, start=1):
                    if option_is_fireball_upgrade(option):
                        option_index = index
                        matched_fireball = True
                        break

            selected = enriched[option_index - 1]
            option_id = parse_int_text(selected.get("id"), -1)
            entry_before = stress.query_entry_state(bot_id, option_id)
            stats_before = stress.query_progression_stats(bot_id)
            stress.assert_bot_owned_progression_mode(bot_id, stats_before, f"before_apply_step_{step}")
            loadout_before = stress.query_bot_loadout(bot_id)

            apply_result = stress.choose_skill(bot_id, option_index, int(choices["generation"]))
            entry_after = stress.query_entry_state(bot_id, option_id)
            stats_after = stress.query_progression_stats(bot_id)
            stress.assert_bot_owned_progression_mode(bot_id, stats_after, f"after_apply_step_{step}")
            loadout_after = stress.query_bot_loadout(bot_id)
            profile_after = stress.query_bot_profile(bot_id)

            application = {
                "bot_id": bot_id,
                "generation": choices["generation"],
                "selected_index": option_index,
                "selected_option": selected,
                "apply_result": apply_result,
                "entry_before": entry_before,
                "entry_after": entry_after,
                "entry_byte_diff": stress.diff_hex_bytes(
                    str(entry_before.get("bytes", "")),
                    str(entry_after.get("bytes", "")),
                ),
                "stats_before": stats_before,
                "stats_after": stats_after,
                "stats_diff": stress.diff_dict(stats_before, stats_after),
                "loadout_before": loadout_before,
                "loadout_after": loadout_after,
                "loadout_diff": stress.diff_dict(loadout_before, loadout_after),
                "profile_after": profile_after,
                "matched_fireball_upgrade": matched_fireball,
            }
            step_record["applications"].append(application)
            if matched_fireball:
                selected_fireball = application

        level_steps.append(step_record)
        if selected_fireball is not None:
            return selected_fireball, level_steps

    raise BotSkillUpgradeCombatFlowProbeFailure(
        f"Fireball upgrade was not offered within {max_level_steps} level-up steps"
    )


def validate_result(result: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    baseline = result.get("baseline_cast", {}).get("mana_prepared", {})
    post = result.get("post_upgrade_cast", {}).get("mana_prepared", {})
    baseline_stats_output = result.get("baseline_cast", {}).get("primary_stat_output", {})
    post_stats_output = result.get("post_upgrade_cast", {}).get("primary_stat_output", {})
    selected = result.get("selected_fireball_upgrade", {})
    entry_before = selected.get("entry_before", {})
    entry_after = selected.get("entry_after", {})
    stats_after = selected.get("stats_after", {})
    profile_after = selected.get("profile_after", {})

    baseline_cost = float(baseline.get("cost", 0.0))
    post_cost = float(post.get("cost", 0.0))
    baseline_damage = float(baseline_stats_output.get("damage", 0.0))
    post_damage = float(post_stats_output.get("damage", 0.0))
    post_level = int(post.get("progression_level", 0))
    expected_level = int(stats_after.get("level", 0))

    if int(baseline.get("skill_id", 0)) != FIREBALL_BUILD_SKILL_ID:
        failures.append(f"baseline cast did not use Fireball build skill {FIREBALL_BUILD_SKILL_ID}: {baseline}")
    if int(post.get("skill_id", 0)) != FIREBALL_BUILD_SKILL_ID:
        failures.append(f"post-upgrade cast did not use Fireball build skill {FIREBALL_BUILD_SKILL_ID}: {post}")
    if baseline_cost <= 0.0 or post_cost <= 0.0:
        failures.append(f"native mana costs were not positive: baseline={baseline_cost} post={post_cost}")
    if post_cost <= baseline_cost + 0.001:
        failures.append(f"Fireball native mana cost did not increase after upgrade: baseline={baseline_cost} post={post_cost}")
    if not baseline_stats_output.get("available") or not post_stats_output.get("available"):
        failures.append(
            "Fireball native primary stat output was not readable: "
            f"baseline={baseline_stats_output} post={post_stats_output}"
        )
    if abs(float(baseline_stats_output.get("mana_cost", 0.0)) - baseline_cost) > 0.001:
        failures.append(
            "baseline mana-prepared cost does not match native stat output: "
            f"prepared={baseline_cost} output={baseline_stats_output}"
        )
    if abs(float(post_stats_output.get("mana_cost", 0.0)) - post_cost) > 0.001:
        failures.append(
            "post-upgrade mana-prepared cost does not match native stat output: "
            f"prepared={post_cost} output={post_stats_output}"
        )
    if baseline_damage <= 0.0 or post_damage <= 0.0:
        failures.append(f"native Fireball damage outputs were not positive: baseline={baseline_damage} post={post_damage}")
    if post_damage <= baseline_damage + 0.001:
        failures.append(f"Fireball native damage did not increase after upgrade: baseline={baseline_damage} post={post_damage}")
    if post_level != expected_level:
        failures.append(f"post-upgrade cast used level {post_level}, expected live progression level {expected_level}")
    if int(entry_after.get("active", 0)) <= int(entry_before.get("active", 0)):
        failures.append(f"Fireball progression active count did not increase: before={entry_before} after={entry_after}")
    if int(entry_after.get("visible", 0)) < int(entry_before.get("visible", 0)):
        failures.append(f"Fireball progression visible count regressed: before={entry_before} after={entry_after}")
    if int(profile_after.get("primary_entry_index", 0)) != FIRE_PRIMARY_ENTRY_INDEX:
        failures.append(f"Fireball choice did not leave the bot primary loadout on Fireball: {profile_after}")
    if int(profile_after.get("primary_combo_entry_index", 0)) != FIRE_PRIMARY_ENTRY_INDEX:
        failures.append(f"Fireball choice did not leave the bot primary combo loadout on Fireball: {profile_after}")

    all_log = "\n".join(result.get("loader_log_tail", []))
    for token in BAD_LOG_TOKENS:
        if token in all_log:
            failures.append(f"loader log contains failure token: {token}")

    summary = {
        "fire_bot_id": result.get("fire_bot", {}).get("id"),
        "baseline_level": baseline.get("progression_level"),
        "post_upgrade_level": post.get("progression_level"),
        "baseline_cost": baseline_cost,
        "post_upgrade_cost": post_cost,
        "baseline_damage": baseline_damage,
        "post_upgrade_damage": post_damage,
        "selected_option": selected.get("selected_option", {}).get("name"),
        "selected_option_id": selected.get("selected_option", {}).get("id"),
        "level_steps": len(result.get("level_steps", [])),
        "active_bots": result.get("active_bots"),
    }
    if failures:
        raise BotSkillUpgradeCombatFlowProbeFailure(json.dumps({"summary": summary, "failures": failures}, indent=2))
    return summary


def run_probe(active_bots: str, max_level_steps: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "active_bots": active_bots,
        "max_level_steps": max_level_steps,
        "fresh_bundle": csp.ensure_launcher_bundle_fresh(),
    }

    csp.stop_game()
    csp.clear_loader_log()
    with stress.temporary_active_bots_config(active_bots):
        csp.launch_game()
        pid = csp.wait_for_game_process()
        result["pid"] = pid
        csp.wait_for_lua_pipe(timeout_s=60.0)
        result["hub_flow"] = csp.drive_new_game_flow(pid, element="ether", discipline="mind")
        values = stress.lua_values("print('ok='..tostring(sd.hub.start_testrun()))")
        if not stress.lua_bool(values.get("ok")):
            raise BotSkillUpgradeCombatFlowProbeFailure(f"sd.hub.start_testrun failed: {values}")
        csp.wait_for_scene("testrun", timeout_s=45.0)
        time.sleep(2.0)
        summary = stress.wait_for_materialized_bots(timeout_s=90.0)

    result["bot_summary_before"] = summary
    result["tick_gate"] = stress.set_lua_bot_tick_enabled(False)
    source_progression = stress.int_value(summary, "player.progression")
    bot_count = stress.int_value(summary, "bot.count")
    bot_ids = [stress.int_value(summary, f"bot.{index}.id") for index in range(1, bot_count + 1)]
    fire_bot = find_bot_summary_by_element(summary, FIRE_ELEMENT_ID)
    fire_bot_id = int(fire_bot["id"])
    fire_progression = int(fire_bot["progression"])
    result["fire_bot"] = fire_bot

    baseline_stats = stress.query_progression_stats(fire_bot_id)
    stress.assert_bot_owned_progression_mode(fire_bot_id, baseline_stats, "baseline")
    result["baseline_stats"] = baseline_stats
    result["baseline_loadout"] = stress.query_bot_loadout(fire_bot_id)
    result["baseline_cast"] = queue_default_fire_cast(fire_bot_id, fire_progression)

    selected_fireball, level_steps = choose_level_options_until_fireball(
        bot_ids,
        fire_bot_id,
        source_progression,
        max_level_steps,
    )
    result["selected_fireball_upgrade"] = selected_fireball
    result["level_steps"] = level_steps

    result["post_upgrade_stats"] = stress.query_progression_stats(fire_bot_id)
    result["post_upgrade_loadout"] = stress.query_bot_loadout(fire_bot_id)
    result["post_upgrade_cast"] = queue_default_fire_cast(fire_bot_id, fire_progression)
    result["loader_log_tail"] = read_loader_log_lines()[-220:]
    result["summary"] = validate_result(result)
    result["passed"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-bots", default="all")
    parser.add_argument("--max-level-steps", type=int, default=DEFAULT_MAX_LEVEL_STEPS)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()

    exit_code = 0
    try:
        result = run_probe(args.active_bots, args.max_level_steps)
    except Exception as exc:  # noqa: BLE001 - preserve live diagnostics.
        result = {
            "passed": False,
            "error": str(exc),
            "loader_log_tail": read_loader_log_lines()[-220:],
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
        summary = result["summary"]
        print(
            "PASS: live bot Fireball upgrade affects combat flow "
            f"level={summary['baseline_level']}->{summary['post_upgrade_level']} "
            f"cost={summary['baseline_cost']:.3f}->{summary['post_upgrade_cost']:.3f}"
        )
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live bot skill-upgrade combat flow probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
