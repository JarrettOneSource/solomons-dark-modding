#!/usr/bin/env python3
"""Verify presentation-local Lua draw ownership across a disposable pair."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from multiplayer_lua_probe import DEFAULT_CLIENTS, parse_client, run_lua_client
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    disable_bots,
    game_process_ids,
    launch_pair,
    stop_game_processes,
    wait_for_remote,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_draw_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.hud_showcase"
HOST_LABEL = "HOST DRAW LOCAL"
CLIENT_LABEL = "CLIENT DRAW LOCAL"
HOST_X = 24
CLIENT_X = 344


CONTRACT_PROBE = f"""
local mod = assert(sd.runtime.get_mod())
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local scene = assert(sd.world.get_scene(), "live scene required")
local owner_count = 0
for _, participant in ipairs(multiplayer.participants or {{}}) do
  if participant.is_owner then owner_count = owner_count + 1 end
end

local namespace_count = 0
local namespace_exact = true
for name, value in pairs(sd.draw) do
  namespace_count = namespace_count + 1
  if (name ~= "text" and name ~= "rect" and name ~= "line" and
      name ~= "sprite" and name ~= "world_to_screen" and
      name ~= "get_viewport" and name ~= "get_sprite_info" and
      name ~= "get_limits") or type(value) ~= "function" then
    namespace_exact = false
  end
end
namespace_exact = namespace_exact and namespace_count == 8

local limits = sd.draw.get_limits()
local limit_fields = 0
local limits_schema_exact = true
local allowed_limits = {{
  commands_per_mod_frame = true,
  text_bytes_per_mod_frame = true,
  text_bytes_per_command = true,
  stock_atlas_count = true,
}}
for key, _ in pairs(limits) do
  limit_fields = limit_fields + 1
  if not allowed_limits[key] then limits_schema_exact = false end
end
limits_schema_exact = limits_schema_exact and limit_fields == 4

local viewport = assert(sd.draw.get_viewport())
local viewport_fields = 0
local viewport_schema_exact = true
for key, _ in pairs(viewport) do
  viewport_fields = viewport_fields + 1
  if key ~= "width" and key ~= "height" then
    viewport_schema_exact = false
  end
end
viewport_schema_exact =
  viewport_schema_exact and viewport_fields == 2

local sprite, sprite_error = sd.draw.get_sprite_info("title", 9)
local sprite_fields = 0
local sprite_schema_exact = true
local allowed_sprite = {{
  atlas = true, record = true, atlas_x = true, atlas_y = true,
  packed_width = true, packed_height = true,
  logical_width = true, logical_height = true,
  content_width = true, content_height = true,
  center_offset_x = true, center_offset_y = true, rotated = true,
}}
for key, _ in pairs(sprite or {{}}) do
  sprite_fields = sprite_fields + 1
  if not allowed_sprite[key] then sprite_schema_exact = false end
end
sprite_schema_exact =
  sprite_schema_exact and sprite_fields == 13 and
  sprite.native_address == nil and sprite.pointer == nil

local missing_sprite, missing_error =
  sd.draw.get_sprite_info("missing-atlas", 0)
local outside_tick_ok = pcall(
  sd.draw.text, "outside tick", 0, 0)
local bad_record_ok = pcall(
  sd.draw.get_sprite_info, "Title", -1)

print("mod_id=" .. tostring(mod.id))
print("alias_exact=" .. tostring(sd.hud == sd.draw))
print("authority=" .. tostring(sd.state.is_authority()))
print("world_scene=" .. tostring(scene.name or scene.kind))
print("participant_count=" .. tostring(multiplayer.participant_count))
print("participant_rows=" .. tostring(#(multiplayer.participants or {{}})))
print("owner_count=" .. tostring(owner_count))
print("namespace_exact=" .. tostring(namespace_exact))
print("draw_capability=" .. tostring(
  sd.runtime.has_capability("draw.local.immediate")))
print("text_capability=" .. tostring(
  sd.runtime.has_capability("draw.text")))
print("primitives_capability=" .. tostring(
  sd.runtime.has_capability("draw.primitives")))
print("sprites_capability=" .. tostring(
  sd.runtime.has_capability("draw.stock_sprites")))
print("projection_capability=" .. tostring(
  sd.runtime.has_capability("draw.world_projection")))
print("limits_schema_exact=" .. tostring(limits_schema_exact))
print("commands_per_mod_frame=" .. tostring(
  limits.commands_per_mod_frame))
print("text_bytes_per_mod_frame=" .. tostring(
  limits.text_bytes_per_mod_frame))
print("text_bytes_per_command=" .. tostring(
  limits.text_bytes_per_command))
print("stock_atlas_count=" .. tostring(limits.stock_atlas_count))
print("viewport_schema_exact=" .. tostring(viewport_schema_exact))
print("viewport_width=" .. tostring(viewport.width))
print("viewport_height=" .. tostring(viewport.height))
print("sprite_schema_exact=" .. tostring(sprite_schema_exact))
print("sprite_atlas=" .. tostring(sprite and sprite.atlas or ""))
print("sprite_record=" .. tostring(sprite and sprite.record or ""))
print("sprite_error=" .. tostring(sprite_error or ""))
print("missing_sprite_nil=" .. tostring(missing_sprite == nil))
print("missing_error_present=" .. tostring(
  type(missing_error) == "string" and #missing_error > 0))
print("outside_tick_rejected=" .. tostring(not outside_tick_ok))
print("bad_record_rejected=" .. tostring(not bad_record_ok))
"""


def _setup_probe(
    *,
    label: str,
    x: int,
    red: int,
    active: bool,
) -> str:
    return f"""
if _G.__sd_draw_multiplayer_handler_registered ~= true then
  _G.__sd_draw_multiplayer_handler_registered = true
  sd.events.on("runtime.tick", function(event)
    local acceptance = _G.__sd_draw_multiplayer_acceptance
    if acceptance == nil then return end
    acceptance.observed_ticks = acceptance.observed_ticks + 1
    acceptance.last_monotonic_milliseconds =
      tonumber(event.monotonic_milliseconds) or 0
    if not acceptance.active then
      acceptance.inactive_ticks = acceptance.inactive_ticks + 1
      return
    end

    local ok, err = pcall(function()
      local viewport = assert(sd.draw.get_viewport())
      acceptance.viewport_width = viewport.width
      acceptance.viewport_height = viewport.height
      local options = {{
        color = {{
          r = acceptance.red,
          g = 96,
          b = 224,
          a = 255,
        }},
      }}
      local text_ok = sd.draw.text(
        acceptance.label, acceptance.x, 210, options)
      local rect_ok = sd.draw.rect(
        acceptance.x, 238, 250, 54, options)
      local line_ok = sd.draw.line(
        acceptance.x,
        304,
        acceptance.x + 250,
        304,
        {{thickness = 3, color = options.color}})
      local sprite_ok = sd.draw.sprite(
        "Title",
        9,
        acceptance.x + 125,
        352,
        {{width = 120, height = 58, centered = true}})
      acceptance.commands_exact =
        text_ok == true and rect_ok == true and
        line_ok == true and sprite_ok == true

      local player = sd.player.get_state()
      local projection = nil
      if type(player) == "table" then
        projection = sd.draw.world_to_screen(player.x, player.y)
      end
      acceptance.projection_available = type(projection) == "table"
      acceptance.projection_schema_exact = false
      acceptance.projection_generation = 0
      if type(projection) == "table" then
        local allowed = {{
          x = true, y = true, visible = true,
          viewport_width = true, viewport_height = true,
          generation = true,
        }}
        local field_count = 0
        local schema_exact = true
        for key, _ in pairs(projection) do
          field_count = field_count + 1
          if not allowed[key] then schema_exact = false end
        end
        acceptance.projection_schema_exact =
          schema_exact and field_count == 6 and
          projection.native_address == nil and
          projection.pointer == nil
        acceptance.projection_generation =
          tonumber(projection.generation) or 0
      end
    end)
    if ok then
      acceptance.submitted_ticks = acceptance.submitted_ticks + 1
    else
      acceptance.error = tostring(err)
      acceptance.active = false
      acceptance.deactivated_at_submitted =
        acceptance.submitted_ticks
      acceptance.inactive_ticks = 0
    end
  end)
end

_G.__sd_draw_multiplayer_acceptance = {{
  label = {json.dumps(label)},
  x = {x},
  red = {red},
  active = {"true" if active else "false"},
  observed_ticks = 0,
  submitted_ticks = 0,
  inactive_ticks = 0,
  deactivated_at_submitted = 0,
  last_monotonic_milliseconds = 0,
  viewport_width = 0,
  viewport_height = 0,
  commands_exact = false,
  projection_available = false,
  projection_schema_exact = false,
  projection_generation = 0,
  error = "",
}}
print("label=" .. tostring(
  _G.__sd_draw_multiplayer_acceptance.label))
print("x=" .. tostring(_G.__sd_draw_multiplayer_acceptance.x))
print("active=" .. tostring(
  _G.__sd_draw_multiplayer_acceptance.active))
print("ready=true")
"""


ACTIVATE_PROBE = """
local acceptance = assert(_G.__sd_draw_multiplayer_acceptance)
acceptance.active = true
acceptance.inactive_ticks = 0
acceptance.deactivated_at_submitted = -1
print("active=" .. tostring(acceptance.active))
print("label=" .. tostring(acceptance.label))
"""


DEACTIVATE_PROBE = """
local acceptance = assert(_G.__sd_draw_multiplayer_acceptance)
acceptance.active = false
acceptance.inactive_ticks = 0
acceptance.deactivated_at_submitted = acceptance.submitted_ticks
print("active=" .. tostring(acceptance.active))
print("label=" .. tostring(acceptance.label))
print("submitted_ticks=" .. tostring(acceptance.submitted_ticks))
"""


STATUS_PROBE = """
local acceptance = _G.__sd_draw_multiplayer_acceptance
print("present=" .. tostring(acceptance ~= nil))
print("label=" .. tostring(acceptance and acceptance.label or ""))
print("x=" .. tostring(acceptance and acceptance.x or 0))
print("active=" .. tostring(
  acceptance ~= nil and acceptance.active == true))
print("observed_ticks=" .. tostring(
  acceptance and acceptance.observed_ticks or 0))
print("submitted_ticks=" .. tostring(
  acceptance and acceptance.submitted_ticks or 0))
print("inactive_ticks=" .. tostring(
  acceptance and acceptance.inactive_ticks or 0))
print("release_stable=" .. tostring(
  acceptance ~= nil and acceptance.active ~= true and
  acceptance.inactive_ticks >= 2 and
  acceptance.submitted_ticks ==
    acceptance.deactivated_at_submitted))
print("last_monotonic_milliseconds=" .. tostring(
  acceptance and acceptance.last_monotonic_milliseconds or 0))
print("viewport_width=" .. tostring(
  acceptance and acceptance.viewport_width or 0))
print("viewport_height=" .. tostring(
  acceptance and acceptance.viewport_height or 0))
print("commands_exact=" .. tostring(
  acceptance ~= nil and acceptance.commands_exact == true))
print("projection_available=" .. tostring(
  acceptance ~= nil and acceptance.projection_available == true))
print("projection_schema_exact=" .. tostring(
  acceptance ~= nil and acceptance.projection_schema_exact == true))
print("projection_generation=" .. tostring(
  acceptance and acceptance.projection_generation or 0))
print("error=" .. tostring(acceptance and acceptance.error or ""))
"""


CLEANUP_PROBE = """
local present = _G.__sd_draw_multiplayer_acceptance ~= nil
_G.__sd_draw_multiplayer_acceptance = nil
print("present=" .. tostring(present))
print("cleared=" .. tostring(
  _G.__sd_draw_multiplayer_acceptance == nil))
"""


def _failed_exec(result: dict[str, Any]) -> str | None:
    if result.get("returncode") == 0:
        return None
    return str(
        result.get("stderr") or result.get("stdout") or "Lua exec failed"
    ).strip()


def _values(result: dict[str, Any]) -> dict[str, str]:
    values = result.get("values", {})
    if not isinstance(values, dict):
        raise RuntimeError(f"Lua probe returned invalid values: {result}")
    return values


def _int_value(values: dict[str, str], name: str) -> int:
    try:
        return int(values.get(name, ""))
    except ValueError as error:
        raise RuntimeError(f"invalid {name}: {values}") from error


def contract_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    try:
        return (
            values.get("mod_id") == ACCEPTANCE_MOD_ID
            and values.get("alias_exact") == "true"
            and values.get("authority") == ("true" if authority else "false")
            and values.get("world_scene") == "hub"
            and _int_value(values, "participant_count") == 2
            and _int_value(values, "participant_rows") == 2
            and _int_value(values, "owner_count") == 1
            and values.get("namespace_exact") == "true"
            and all(
                values.get(name) == "true"
                for name in (
                    "draw_capability",
                    "text_capability",
                    "primitives_capability",
                    "sprites_capability",
                    "projection_capability",
                    "limits_schema_exact",
                    "viewport_schema_exact",
                    "sprite_schema_exact",
                    "missing_sprite_nil",
                    "missing_error_present",
                    "outside_tick_rejected",
                    "bad_record_rejected",
                )
            )
            and _int_value(values, "commands_per_mod_frame") == 512
            and _int_value(values, "text_bytes_per_mod_frame") == 16384
            and _int_value(values, "text_bytes_per_command") == 1024
            and _int_value(values, "stock_atlas_count") == 28
            and _int_value(values, "viewport_width") >= 600
            and _int_value(values, "viewport_height") >= 234
            and values.get("sprite_atlas") == "Title"
            and _int_value(values, "sprite_record") == 9
            and values.get("sprite_error") == ""
        )
    except RuntimeError:
        return False


def setup_matches(
    values: dict[str, str],
    *,
    label: str,
    x: int,
    active: bool,
) -> bool:
    return (
        values.get("label") == label
        and values.get("x") == str(x)
        and values.get("active") == ("true" if active else "false")
        and values.get("ready") == "true"
    )


def status_matches(
    values: dict[str, str],
    *,
    label: str,
    x: int,
    active: bool,
    released: bool,
) -> bool:
    try:
        if (
            values.get("present") != "true"
            or values.get("label") != label
            or _int_value(values, "x") != x
            or values.get("active") != ("true" if active else "false")
            or _int_value(values, "observed_ticks") < 2
            or values.get("error") != ""
        ):
            return False
        if released:
            return (
                not active
                and values.get("release_stable") == "true"
                and _int_value(values, "inactive_ticks") >= 2
            )
        if not active:
            return (
                _int_value(values, "submitted_ticks") == 0
                and _int_value(values, "inactive_ticks") >= 2
            )
        return (
            _int_value(values, "submitted_ticks") >= 2
            and _int_value(values, "last_monotonic_milliseconds") > 0
            and _int_value(values, "viewport_width") >= 600
            and _int_value(values, "viewport_height") >= 234
            and values.get("commands_exact") == "true"
            and values.get("projection_available") == "true"
            and values.get("projection_schema_exact") == "true"
            and _int_value(values, "projection_generation") > 0
        )
    except RuntimeError:
        return False


def lifecycle_matches(
    values: dict[str, str],
    *,
    label: str,
    active: bool,
) -> bool:
    return (
        values.get("active") == ("true" if active else "false")
        and values.get("label") == label
    )


def cleanup_matches(
    values: dict[str, str],
    *,
    expected_present: bool,
) -> bool:
    return (
        values.get("present")
        == ("true" if expected_present else "false")
        and values.get("cleared") == "true"
    )


def _run_probe(
    client: tuple[str, str],
    code: str,
) -> dict[str, Any]:
    result = run_lua_client(client[0], client[1], code, timeout=12.0)
    failure = _failed_exec(result)
    if failure:
        raise RuntimeError(failure)
    return result


def _require_action(
    client: tuple[str, str],
    code: str,
    predicate: Callable[[dict[str, str]], bool],
    description: str,
) -> dict[str, Any]:
    result = _run_probe(client, code)
    if not predicate(_values(result)):
        raise RuntimeError(f"{description} failed: {result}")
    return result


def _poll_status(
    client: tuple[str, str],
    *,
    label: str,
    x: int,
    active: bool,
    released: bool,
    timeout: float,
    description: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = run_lua_client(
            client[0],
            client[1],
            STATUS_PROBE,
            timeout=12.0,
        )
        values = last.get("values", {})
        if (
            _failed_exec(last) is None
            and isinstance(values, dict)
            and status_matches(
                values,
                label=label,
                x=x,
                active=active,
                released=released,
            )
        ):
            return last
        time.sleep(0.05)
    raise RuntimeError(
        f"{description} did not converge for {client[0]}: {last}"
    )


def _cleanup_peer(client: tuple[str, str]) -> dict[str, Any]:
    try:
        return run_lua_client(
            client[0],
            client[1],
            CLEANUP_PROBE,
            timeout=5.0,
        )
    except Exception as error:  # noqa: BLE001 - process teardown is final.
        return {"returncode": 1, "error": str(error)}


def run(
    clients: list[tuple[str, str]],
    *,
    launch: bool,
    timeout: float,
) -> dict[str, Any]:
    if not launch:
        raise RuntimeError("Lua draw acceptance requires --launch-pair")
    if len(clients) != 2:
        raise RuntimeError("exactly one host and one client endpoint are required")
    host, client = clients
    result: dict[str, Any] = {
        "ok": False,
        "launched_pair": True,
        "host": host[0],
        "client": client[0],
    }
    launched_process_ids: list[int] = []
    pair_ready = False
    try:
        result["pair"] = launch_pair(
            tile_windows=False,
            kill_existing=False,
            exact_mod_id=ACCEPTANCE_MOD_ID,
        )
        launched_process_ids.extend(game_process_ids(result["pair"]))
        if len(set(launched_process_ids)) != 2:
            raise RuntimeError(
                "local pair did not report two exact process IDs: "
                f"{launched_process_ids}"
            )
        disable_bots()
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub")
        pair_ready = True

        result["contract"] = [
            _require_action(
                peer,
                CONTRACT_PROBE,
                lambda values, authority=index == 0: contract_matches(
                    values,
                    authority=authority,
                ),
                "local draw contract",
            )
            for index, peer in enumerate((host, client))
        ]
        result["setup"] = [
            _require_action(
                host,
                _setup_probe(
                    label=HOST_LABEL,
                    x=HOST_X,
                    red=232,
                    active=True,
                ),
                lambda values: setup_matches(
                    values,
                    label=HOST_LABEL,
                    x=HOST_X,
                    active=True,
                ),
                "host draw handler setup",
            ),
            _require_action(
                client,
                _setup_probe(
                    label=CLIENT_LABEL,
                    x=CLIENT_X,
                    red=48,
                    active=False,
                ),
                lambda values: setup_matches(
                    values,
                    label=CLIENT_LABEL,
                    x=CLIENT_X,
                    active=False,
                ),
                "client draw handler setup",
            ),
        ]
        result["host_only"] = [
            _poll_status(
                host,
                label=HOST_LABEL,
                x=HOST_X,
                active=True,
                released=False,
                timeout=timeout,
                description="host local draw submissions",
            ),
            _poll_status(
                client,
                label=CLIENT_LABEL,
                x=CLIENT_X,
                active=False,
                released=False,
                timeout=timeout,
                description="client isolation from host draw activation",
            ),
        ]

        result["client_activate"] = _require_action(
            client,
            ACTIVATE_PROBE,
            lambda values: lifecycle_matches(
                values,
                label=CLIENT_LABEL,
                active=True,
            ),
            "client draw activation",
        )
        result["independent_active"] = [
            _poll_status(
                host,
                label=HOST_LABEL,
                x=HOST_X,
                active=True,
                released=False,
                timeout=timeout,
                description="host retained local draw handler",
            ),
            _poll_status(
                client,
                label=CLIENT_LABEL,
                x=CLIENT_X,
                active=True,
                released=False,
                timeout=timeout,
                description="client local draw submissions",
            ),
        ]

        result["host_deactivate"] = _require_action(
            host,
            DEACTIVATE_PROBE,
            lambda values: lifecycle_matches(
                values,
                label=HOST_LABEL,
                active=False,
            ),
            "host draw deactivation",
        )
        result["host_release_isolation"] = [
            _poll_status(
                host,
                label=HOST_LABEL,
                x=HOST_X,
                active=False,
                released=True,
                timeout=timeout,
                description="host draw handler release",
            ),
            _poll_status(
                client,
                label=CLIENT_LABEL,
                x=CLIENT_X,
                active=True,
                released=False,
                timeout=timeout,
                description="client retained draw handler",
            ),
        ]

        result["client_deactivate"] = _require_action(
            client,
            DEACTIVATE_PROBE,
            lambda values: lifecycle_matches(
                values,
                label=CLIENT_LABEL,
                active=False,
            ),
            "client draw deactivation",
        )
        result["released"] = [
            _poll_status(
                peer,
                label=HOST_LABEL if index == 0 else CLIENT_LABEL,
                x=HOST_X if index == 0 else CLIENT_X,
                active=False,
                released=True,
                timeout=timeout,
                description="released local draw handler",
            )
            for index, peer in enumerate((host, client))
        ]
        result["ok"] = True
        return result
    finally:
        if pair_ready:
            result["cleanup"] = [
                _cleanup_peer(peer)
                for peer in (host, client)
            ]
        stop_game_processes(launched_process_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        action="append",
        type=parse_client,
        help="Lua endpoint as NAME=PIPE; provide exactly host then client.",
    )
    parser.add_argument(
        "--launch-pair",
        action="store_true",
        help="stage and launch the disposable local pair required by this verifier",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.launch_pair:
        result["error"] = "Lua draw acceptance requires --launch-pair"
        return_code = 2
    else:
        try:
            result = run(
                args.client or list(DEFAULT_CLIENTS),
                launch=True,
                timeout=max(1.0, args.timeout),
            )
            return_code = 0 if result.get("ok") else 1
        except Exception as error:  # noqa: BLE001 - preserve exact live evidence.
            result["error"] = str(error)
            return_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
