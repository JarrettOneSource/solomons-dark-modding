#!/usr/bin/env python3
"""Live RE probe for removal of hardcoded wizard source-profile buffers.

The probe records the finalized local player and a materialized standalone bot,
then checks the temporary clone-source lifecycle in the loader log. A passing
run proves finalized actors keep `actor+0x178 == 0` and bot materialization uses
a transient native-derived source profile instead of hardcoded element colors.
"""

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


OUTPUT_PATH = ROOT / "runtime" / "live_source_profile_negative_probe.json"
BOT_NAME = "Source Profile Negative Probe"

SOURCE_KIND_OFFSET = csp.read_runtime_layout_offset("actor_hub_visual_source_kind")
SOURCE_PROFILE_OFFSET = csp.read_runtime_layout_offset("actor_hub_visual_source_profile")
ATTACHMENT_OFFSET = csp.read_runtime_layout_offset("actor_hub_visual_attachment_ptr")
DESCRIPTOR_OFFSET = csp.read_runtime_layout_offset("actor_hub_visual_descriptor_block")
VARIANT_PRIMARY_OFFSET = csp.read_runtime_layout_offset("actor_render_variant_primary")
VARIANT_SECONDARY_OFFSET = csp.read_runtime_layout_offset("actor_render_variant_secondary")
WEAPON_TYPE_OFFSET = csp.read_runtime_layout_offset("actor_render_weapon_type")
RENDER_SELECTION_OFFSET = csp.read_runtime_layout_offset("actor_render_selection_byte")
VARIANT_TERTIARY_OFFSET = csp.read_runtime_layout_offset("actor_render_variant_tertiary")

LOG_REQUIRED_TOKENS = (
    "native_derived_visual_seed_before",
    "native_derived_visual_seed_after",
    "native-derived source profile",
    "native-derived clone-source seeded",
    "clone_source_ready",
)


class LiveSourceProfileProbeFailure(RuntimeError):
    pass


def visual_state_lua(prefix: str, table_name: str) -> str:
    return f"""
local function emit_{prefix}(key, value)
  if value == nil then
    print('{prefix}.' .. key .. '=')
  else
    print('{prefix}.' .. key .. '=' .. tostring(value))
  end
end

emit_{prefix}('available', type({table_name}) == 'table')
if type({table_name}) == 'table' then
  for _, key in ipairs({{
    'id', 'name', 'actor_address', 'render_subject_address',
    'entity_materialized', 'participant_kind', 'controller_kind',
    'gameplay_slot', 'actor_slot', 'hub_visual_attachment_ptr',
    'hub_visual_source_profile_address', 'hub_visual_source_kind',
    'hub_visual_descriptor_signature',
    'render_subject_hub_visual_attachment_ptr',
    'render_subject_hub_visual_source_profile_address',
    'render_subject_hub_visual_source_kind',
    'render_subject_hub_visual_descriptor_signature',
    'render_variant_primary', 'render_variant_secondary',
    'render_weapon_type', 'render_selection_byte',
    'render_variant_tertiary', 'x', 'y'
  }}) do
    emit_{prefix}(key, {table_name}[key])
  end

  local actor = tonumber({table_name}.actor_address) or 0
  emit_{prefix}('raw.available', actor ~= 0)
  if actor ~= 0 then
    emit_{prefix}('raw.actor_address', actor)
    emit_{prefix}('raw.hub_visual_source_kind', sd.debug.read_i32(actor + {SOURCE_KIND_OFFSET}))
    emit_{prefix}('raw.hub_visual_source_profile_address', sd.debug.read_ptr(actor + {SOURCE_PROFILE_OFFSET}))
    emit_{prefix}('raw.hub_visual_attachment_ptr', sd.debug.read_ptr(actor + {ATTACHMENT_OFFSET}))
    emit_{prefix}('raw.descriptor_first_u32', sd.debug.read_u32(actor + {DESCRIPTOR_OFFSET}))
    emit_{prefix}('raw.render_variant_primary', sd.debug.read_u8(actor + {VARIANT_PRIMARY_OFFSET}))
    emit_{prefix}('raw.render_variant_secondary', sd.debug.read_u8(actor + {VARIANT_SECONDARY_OFFSET}))
    emit_{prefix}('raw.render_weapon_type', sd.debug.read_u8(actor + {WEAPON_TYPE_OFFSET}))
    emit_{prefix}('raw.render_selection_byte', sd.debug.read_u8(actor + {RENDER_SELECTION_OFFSET}))
    emit_{prefix}('raw.render_variant_tertiary', sd.debug.read_u8(actor + {VARIANT_TERTIARY_OFFSET}))
  end
end
""".strip()


def query_player_visual_state() -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local player = sd.player and sd.player.get_state and sd.player.get_state()
{visual_state_lua('player', 'player')}
""".strip()
        )
    )


def create_shared_hub_bot() -> int:
    output = csp.run_lua(
        f"""
local function emit(key, value)
  if value == nil then
    print(key .. '=')
  else
    print(key .. '=' .. tostring(value))
  end
end
if type(sd.bots.clear) == 'function' then
  sd.bots.clear()
end
local player = sd.player.get_state()
if type(player) ~= 'table' then
  emit('ok', false)
  emit('error', 'missing_player')
  return
end
local id = sd.bots.create({{
  name = {json.dumps(BOT_NAME)},
  profile = {{
    element_id = 4,
    discipline_id = 1,
    level = 1,
    experience = 0,
  }},
  scene = {{ kind = 'shared_hub' }},
  ready = true,
  heading = 90.0,
  position = {{
    x = (tonumber(player.x) or 0.0) + 96.0,
    y = tonumber(player.y) or 0.0,
  }},
}})
emit('ok', id ~= nil)
emit('bot_id', id)
""".strip()
    )
    values = csp.parse_key_values(output)
    if values.get("ok") != "true":
        raise LiveSourceProfileProbeFailure(f"sd.bots.create failed: {values}")
    bot_id = csp.int_value(values, "bot_id")
    if bot_id == 0:
        raise LiveSourceProfileProbeFailure(f"sd.bots.create returned invalid id: {values}")
    return bot_id


def query_bot_visual_state(bot_id: int) -> dict[str, str]:
    return csp.parse_key_values(
        csp.run_lua(
            f"""
local bot = sd.bots.get_state({bot_id})
if type(bot) ~= 'table' then
  local bots = sd.bots.get_state()
  if type(bots) == 'table' then
    for _, candidate in ipairs(bots) do
      if type(candidate) == 'table' and tonumber(candidate.id) == {bot_id} then
        bot = candidate
        break
      end
    end
  end
end
{visual_state_lua('bot', 'bot')}
""".strip()
        )
    )


def wait_for_bot_visual_state(bot_id: int, *, timeout_s: float = 30.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last: dict[str, str] = {}
    while time.time() < deadline:
        last = query_bot_visual_state(bot_id)
        if (
            last.get("bot.available") == "true"
            and last.get("bot.entity_materialized") == "true"
            and csp.int_value(last, "bot.actor_address") != 0
        ):
            return last
        time.sleep(0.25)
    raise LiveSourceProfileProbeFailure(f"timed out waiting for bot materialization. Last={last}")


def require_present(sample: dict[str, str], label: str, key: str) -> None:
    if key not in sample:
        raise LiveSourceProfileProbeFailure(f"{label}: missing {key}: {sample}")


def require_nonzero_address(sample: dict[str, str], label: str, key: str) -> None:
    require_present(sample, label, key)
    if csp.int_value(sample, key) == 0:
        raise LiveSourceProfileProbeFailure(f"{label}: expected nonzero {key}: {sample}")


def require_zero_address(sample: dict[str, str], label: str, key: str) -> None:
    require_present(sample, label, key)
    value = csp.int_value(sample, key)
    if value != 0:
        raise LiveSourceProfileProbeFailure(f"{label}: expected {key}=0, got 0x{value:X}: {sample}")


def validate_finalized_actor_source_profile(label: str, sample: dict[str, str], prefix: str) -> None:
    if sample.get(f"{prefix}.available") != "true":
        raise LiveSourceProfileProbeFailure(f"{label}: visual state unavailable: {sample}")
    require_nonzero_address(sample, label, f"{prefix}.actor_address")
    require_zero_address(sample, label, f"{prefix}.hub_visual_source_profile_address")
    require_zero_address(sample, label, f"{prefix}.raw.hub_visual_source_profile_address")
    if f"{prefix}.render_subject_hub_visual_source_profile_address" in sample:
        require_zero_address(sample, label, f"{prefix}.render_subject_hub_visual_source_profile_address")
    require_present(sample, label, f"{prefix}.hub_visual_descriptor_signature")
    require_present(sample, label, f"{prefix}.render_selection_byte")


def collect_source_profile_log_evidence(log_tail: list[str]) -> dict[str, Any]:
    joined = "\n".join(log_tail)
    missing_tokens = [token for token in LOG_REQUIRED_TOKENS if token not in joined]
    if missing_tokens:
        raise LiveSourceProfileProbeFailure(
            "loader log is missing native clone-source lifecycle token(s): " + ", ".join(missing_tokens)
        )
    if "source_kind=3" not in joined:
        raise LiveSourceProfileProbeFailure("loader log did not capture source_kind=3 clone-source evidence")
    if "native_visual_actor=" not in joined or "render_selection=" not in joined:
        raise LiveSourceProfileProbeFailure("loader log did not capture native-derived visual evidence")

    source_lines = [
        line
        for line in log_tail
        if "native_derived_visual_seed_" in line
        or "native-derived" in line
        or "clone_source_ready" in line
    ]

    return {
        "required_tokens": list(LOG_REQUIRED_TOKENS),
        "line_count": len(source_lines),
        "lines": source_lines[-40:],
    }


def run_probe() -> dict[str, Any]:
    result: dict[str, Any] = {
        "launcher_freshness": csp.ensure_launcher_bundle_fresh(),
        "layout_offsets": {
            "actor_hub_visual_source_kind": SOURCE_KIND_OFFSET,
            "actor_hub_visual_source_profile": SOURCE_PROFILE_OFFSET,
            "actor_hub_visual_attachment_ptr": ATTACHMENT_OFFSET,
            "actor_hub_visual_descriptor_block": DESCRIPTOR_OFFSET,
            "actor_render_variant_primary": VARIANT_PRIMARY_OFFSET,
            "actor_render_variant_secondary": VARIANT_SECONDARY_OFFSET,
            "actor_render_weapon_type": WEAPON_TYPE_OFFSET,
            "actor_render_selection_byte": RENDER_SELECTION_OFFSET,
            "actor_render_variant_tertiary": VARIANT_TERTIARY_OFFSET,
        },
        "navigation": [],
        "negative_ghidra_evidence": {
            "0x005B7080": "factory dispatch creates type 0x1397 source actors only",
            "0x005E9A90": "GameNPC/source actor constructor zeroes actor+0x174 and actor+0x178",
            "0x005E3080": "native consumer of an already prepared actor+0x178 profile",
            "0x0061AA00": "native clone-from-source actor consumer of a prepared source actor",
        },
    }

    csp.stop_game()
    csp.clear_loader_log()
    csp.launch_game()
    process_id = csp.wait_for_game_process()
    csp.wait_for_lua_pipe()
    result["process_id"] = process_id
    result["navigation"].append({"step": "launch", "process_id": process_id})

    hub_flow = csp.drive_hub_flow(process_id, element="fire", discipline="mind", prefer_resume=False)
    result["navigation"].append({"step": "hub_ready", "flow": hub_flow})

    player_sample = query_player_visual_state()
    validate_finalized_actor_source_profile("player", player_sample, "player")

    bot_id = create_shared_hub_bot()
    result["bot_id"] = bot_id
    bot_sample = wait_for_bot_visual_state(bot_id)
    time.sleep(0.5)
    bot_settled_sample = query_bot_visual_state(bot_id)
    validate_finalized_actor_source_profile("bot.initial", bot_sample, "bot")
    validate_finalized_actor_source_profile("bot.settled", bot_settled_sample, "bot")

    log_tail = csp.tail_loader_log(260)
    log_evidence = collect_source_profile_log_evidence(log_tail)

    result["player_sample"] = player_sample
    result["bot_initial_sample"] = bot_sample
    result["bot_settled_sample"] = bot_settled_sample
    result["source_profile_log_evidence"] = log_evidence
    result["loader_log_tail"] = log_tail
    result["conclusion"] = (
        "Finalized player and standalone bot actors keep actor+0x178 at zero; "
        "the only nonzero source-profile pointer observed is the temporary synthetic "
        "input staged for the native descriptor consumer."
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--json", action="store_true", help="Only print structured JSON.")
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()

    exit_code = 0
    try:
        result = run_probe()
        result["passed"] = True
    except Exception as exc:  # noqa: BLE001 - probe preserves diagnostics in JSON.
        result = {
            "passed": False,
            "error": str(exc),
            "loader_log_tail": csp.tail_loader_log(260),
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
        print("PASS: live source-profile negative probe confirmed no stable actor+0x178 producer seam")
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live source-profile negative probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
