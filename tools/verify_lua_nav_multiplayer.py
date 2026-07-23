#!/usr/bin/env python3
"""Verify native-backed Lua navigation across a disposable local pair."""

from __future__ import annotations

import argparse
import json
import math
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
    start_host_testrun_and_wait_for_clients,
    stop_game_processes,
    wait_for_remote,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_nav_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.nav_lab"
SUBDIVISIONS = 2


NAV_PROBE = r"""
local mod = assert(sd.runtime.get_mod())
local player = assert(sd.player.get_state(), "live player required")
local scene = assert(sd.world.get_scene(), "live scene required")
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local owner_count = 0
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.is_owner then owner_count = owner_count + 1 end
end
local namespace_count = 0
local namespace_exact = true
for name, value in pairs(sd.nav) do
  namespace_count = namespace_count + 1
  if (name ~= "get_grid" and name ~= "test_segment") or
      type(value) ~= "function" then
    namespace_exact = false
  end
end
namespace_exact = namespace_exact and namespace_count == 2
print("mod_id=" .. tostring(mod.id))
print("capability=" .. tostring(sd.runtime.has_capability("nav.read")))
print("authority=" .. tostring(sd.state.is_authority()))
print("world_scene=" .. tostring(scene.name or scene.kind))
print("participant_count=" .. tostring(multiplayer.participant_count))
print("participant_rows=" .. tostring(#(multiplayer.participants or {})))
print("owner_count=" .. tostring(owner_count))
print("namespace_exact=" .. tostring(namespace_exact))

local grid = sd.nav.get_grid(2)
if not grid or grid.refresh_pending then
  print("ready=false")
  return
end

local function finite(value)
  return type(value) == "number" and
    value == value and value ~= math.huge and value ~= -math.huge
end

local function integer(value)
  return finite(value) and value == math.floor(value)
end

local function exact_object(value, allowed, expected)
  if type(value) ~= "table" then return false end
  local count = 0
  for key, _ in pairs(value) do
    if type(key) ~= "string" or not allowed[key] then return false end
    count = count + 1
  end
  return count == expected
end

local function exact_array(value, expected)
  if type(value) ~= "table" then return false end
  local count = 0
  for key, _ in pairs(value) do
    if not integer(key) or key < 1 or key > expected then return false end
    count = count + 1
  end
  return count == expected
end

local grid_keys = {
  width = true,
  height = true,
  cell_width = true,
  cell_height = true,
  probe_x = true,
  probe_y = true,
  subdivisions = true,
  requested_subdivisions = true,
  refresh_pending = true,
  cells = true,
}
local cell_keys = {
  grid_x = true,
  grid_y = true,
  center_x = true,
  center_y = true,
  traversable = true,
  path_traversable = true,
  samples = true,
}
local sample_keys = {
  sample_x = true,
  sample_y = true,
  world_x = true,
  world_y = true,
  traversable = true,
}

local cell_count = #grid.cells
local sample_count = 0
local traversable_count = 0
local path_traversable_count = 0
local sample_traversable_count = 0
local schema_exact =
  exact_object(grid, grid_keys, 10) and
  integer(grid.width) and grid.width > 0 and
  integer(grid.height) and grid.height > 0 and
  finite(grid.cell_width) and grid.cell_width > 0 and
  finite(grid.cell_height) and grid.cell_height > 0 and
  finite(grid.probe_x) and finite(grid.probe_y) and
  integer(grid.subdivisions) and
  integer(grid.requested_subdivisions) and
  type(grid.refresh_pending) == "boolean" and
  exact_array(grid.cells, cell_count)
local coordinates_finite =
  finite(player.x) and finite(player.y) and
  finite(grid.probe_x) and finite(grid.probe_y)
local seen_cells = {}

for _, cell in ipairs(grid.cells) do
  local cell_exact =
    exact_object(cell, cell_keys, 7) and
    integer(cell.grid_x) and cell.grid_x >= 0 and
    cell.grid_x < grid.width and
    integer(cell.grid_y) and cell.grid_y >= 0 and
    cell.grid_y < grid.height and
    finite(cell.center_x) and finite(cell.center_y) and
    type(cell.traversable) == "boolean" and
    type(cell.path_traversable) == "boolean" and
    exact_array(cell.samples, #cell.samples) and
    #cell.samples == grid.subdivisions * grid.subdivisions
  schema_exact = schema_exact and cell_exact
  coordinates_finite =
    coordinates_finite and finite(cell.center_x) and finite(cell.center_y)
  local cell_key = tostring(cell.grid_x) .. ":" .. tostring(cell.grid_y)
  if seen_cells[cell_key] then schema_exact = false end
  seen_cells[cell_key] = true
  if cell.traversable then traversable_count = traversable_count + 1 end
  if cell.path_traversable then
    path_traversable_count = path_traversable_count + 1
  end

  local seen_samples = {}
  for _, sample in ipairs(cell.samples) do
    local sample_exact =
      exact_object(sample, sample_keys, 5) and
      integer(sample.sample_x) and sample.sample_x >= 0 and
      sample.sample_x < grid.subdivisions and
      integer(sample.sample_y) and sample.sample_y >= 0 and
      sample.sample_y < grid.subdivisions and
      finite(sample.world_x) and finite(sample.world_y) and
      type(sample.traversable) == "boolean"
    schema_exact = schema_exact and sample_exact
    coordinates_finite =
      coordinates_finite and finite(sample.world_x) and finite(sample.world_y)
    local sample_key =
      tostring(sample.sample_x) .. ":" .. tostring(sample.sample_y)
    if seen_samples[sample_key] then schema_exact = false end
    seen_samples[sample_key] = true
    sample_count = sample_count + 1
    if sample.traversable then
      sample_traversable_count = sample_traversable_count + 1
    end
  end
end

schema_exact =
  schema_exact and cell_count == grid.width * grid.height and
  sample_count ==
    cell_count * grid.subdivisions * grid.subdivisions

local raw_addresses_absent = true
for _, key in ipairs({
  "world_address",
  "controller_address",
  "cells_address",
  "probe_actor_address",
  "actor_address",
  "player_address",
}) do
  if grid[key] ~= nil then raw_addresses_absent = false end
end

local segment_ok, segment_value = pcall(
  sd.nav.test_segment,
  player.x, player.y,
  player.x, player.y)
local low_ok = pcall(sd.nav.get_grid, 0)
local high_ok = pcall(sd.nav.get_grid, 5)
local fraction_ok = pcall(sd.nav.get_grid, 1.5)
local infinite_ok = pcall(
  sd.nav.test_segment,
  math.huge, player.y,
  player.x, player.y)
local nan = 0 / 0
local nan_ok = pcall(
  sd.nav.test_segment,
  nan, player.y,
  player.x, player.y)

print("ready=true")
print("width=" .. tostring(grid.width))
print("height=" .. tostring(grid.height))
print("cell_width=" .. tostring(grid.cell_width))
print("cell_height=" .. tostring(grid.cell_height))
print("probe_x=" .. tostring(grid.probe_x))
print("probe_y=" .. tostring(grid.probe_y))
print("subdivisions=" .. tostring(grid.subdivisions))
print("requested_subdivisions=" .. tostring(grid.requested_subdivisions))
print("refresh_pending=" .. tostring(grid.refresh_pending))
print("cell_count=" .. tostring(cell_count))
print("sample_count=" .. tostring(sample_count))
print("traversable_count=" .. tostring(traversable_count))
print("path_traversable_count=" .. tostring(path_traversable_count))
print("sample_traversable_count=" .. tostring(sample_traversable_count))
print("schema_exact=" .. tostring(schema_exact))
print("coordinates_finite=" .. tostring(coordinates_finite))
print("raw_addresses_absent=" .. tostring(raw_addresses_absent))
print("segment_ok=" .. tostring(segment_ok))
print("segment_type=" .. type(segment_value))
print("segment_value=" .. tostring(segment_value))
print("low_rejected=" .. tostring(not low_ok))
print("high_rejected=" .. tostring(not high_ok))
print("fraction_rejected=" .. tostring(not fraction_ok))
print("infinite_rejected=" .. tostring(not infinite_ok))
print("nan_rejected=" .. tostring(not nan_ok))
"""


def _failed_exec(result: dict[str, Any]) -> str | None:
    if result.get("returncode") == 0:
        return None
    return str(
        result.get("stderr") or result.get("stdout") or "Lua exec failed"
    ).strip()


def _int_value(values: dict[str, str], name: str) -> int:
    try:
        return int(values.get(name, ""))
    except ValueError as error:
        raise RuntimeError(f"invalid {name}: {values}") from error


def _float_value(values: dict[str, str], name: str) -> float:
    try:
        value = float(values.get(name, ""))
    except ValueError as error:
        raise RuntimeError(f"invalid {name}: {values}") from error
    if not math.isfinite(value):
        raise RuntimeError(f"non-finite {name}: {values}")
    return value


def navigation_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    try:
        width = _int_value(values, "width")
        height = _int_value(values, "height")
        cell_count = _int_value(values, "cell_count")
        sample_count = _int_value(values, "sample_count")
        traversable_count = _int_value(values, "traversable_count")
        path_traversable_count = _int_value(
            values,
            "path_traversable_count",
        )
        sample_traversable_count = _int_value(
            values,
            "sample_traversable_count",
        )
        return (
            values.get("mod_id") == ACCEPTANCE_MOD_ID
            and values.get("capability") == "true"
            and values.get("authority") == ("true" if authority else "false")
            and values.get("world_scene") == "testrun"
            and _int_value(values, "participant_count") == 2
            and _int_value(values, "participant_rows") == 2
            and _int_value(values, "owner_count") == 1
            and values.get("namespace_exact") == "true"
            and values.get("ready") == "true"
            and width > 0
            and height > 0
            and _float_value(values, "cell_width") > 0.0
            and _float_value(values, "cell_height") > 0.0
            and math.isfinite(_float_value(values, "probe_x"))
            and math.isfinite(_float_value(values, "probe_y"))
            and _int_value(values, "subdivisions") == SUBDIVISIONS
            and _int_value(values, "requested_subdivisions")
            == SUBDIVISIONS
            and values.get("refresh_pending") == "false"
            and cell_count == width * height
            and sample_count
            == cell_count * SUBDIVISIONS * SUBDIVISIONS
            and 0 <= traversable_count <= cell_count
            and 0 <= path_traversable_count <= cell_count
            and 0 <= sample_traversable_count <= sample_count
            and values.get("schema_exact") == "true"
            and values.get("coordinates_finite") == "true"
            and values.get("raw_addresses_absent") == "true"
            and values.get("segment_ok") == "true"
            and values.get("segment_type") == "boolean"
            and values.get("segment_value") in ("true", "false")
            and values.get("low_rejected") == "true"
            and values.get("high_rejected") == "true"
            and values.get("fraction_rejected") == "true"
            and values.get("infinite_rejected") == "true"
            and values.get("nan_rejected") == "true"
        )
    except RuntimeError:
        return False


def grid_geometry_matches(
    host_values: dict[str, str],
    client_values: dict[str, str],
) -> bool:
    try:
        for name in (
            "width",
            "height",
            "subdivisions",
            "requested_subdivisions",
            "cell_count",
            "sample_count",
        ):
            if _int_value(host_values, name) != _int_value(
                client_values,
                name,
            ):
                return False
        for name in ("cell_width", "cell_height"):
            if not math.isclose(
                _float_value(host_values, name),
                _float_value(client_values, name),
                rel_tol=0.0,
                abs_tol=1e-5,
            ):
                return False
        return True
    except RuntimeError:
        return False


def _poll_probe(
    client: tuple[str, str],
    predicate: Callable[[dict[str, str]], bool],
    *,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = run_lua_client(
            client[0],
            client[1],
            NAV_PROBE,
            timeout=12.0,
        )
        values = last.get("values", {})
        if (
            _failed_exec(last) is None
            and isinstance(values, dict)
            and predicate(values)
        ):
            return last
        time.sleep(0.1)
    raise RuntimeError(
        f"Lua navigation did not converge for {client[0]}: {last}"
    )


def run(
    clients: list[tuple[str, str]],
    *,
    launch: bool,
    timeout: float,
) -> dict[str, Any]:
    if not launch:
        raise RuntimeError("Lua navigation acceptance requires --launch-pair")
    if len(clients) != 2:
        raise RuntimeError("exactly one host and one client endpoint are required")
    host = clients[0]
    client = clients[1]
    peers = [host, client]
    result: dict[str, Any] = {
        "ok": False,
        "launched_pair": True,
        "host": host[0],
        "client": client[0],
    }
    launched_process_ids: list[int] = []
    try:
        result["pair"] = launch_pair(
            god_mode=True,
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

        result["run"] = start_host_testrun_and_wait_for_clients(
            timeout=timeout,
        )
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")

        snapshots = [
            _poll_probe(
                peer,
                lambda values, authority=index == 0: navigation_state_matches(
                    values,
                    authority=authority,
                ),
                timeout=timeout,
            )
            for index, peer in enumerate(peers)
        ]
        result["snapshots"] = snapshots
        host_values = snapshots[0].get("values", {})
        client_values = snapshots[1].get("values", {})
        if not (
            isinstance(host_values, dict)
            and isinstance(client_values, dict)
            and grid_geometry_matches(host_values, client_values)
        ):
            raise RuntimeError(
                "host/client native navigation geometry differs: "
                f"host={host_values} client={client_values}"
            )
        result["shared_geometry"] = {
            name: host_values[name]
            for name in (
                "width",
                "height",
                "cell_width",
                "cell_height",
                "subdivisions",
                "cell_count",
                "sample_count",
            )
        }
        result["ok"] = True
        return result
    finally:
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
    parser.add_argument(
        "--confirm-mutation",
        action="store_true",
        help="confirm that the verifier may enter one isolated run",
    )
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.confirm_mutation:
        result["error"] = "refusing run entry without --confirm-mutation"
        return_code = 2
    elif not args.launch_pair:
        result["error"] = "Lua navigation acceptance requires --launch-pair"
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
