#!/usr/bin/env python3
"""Verify presentation-local Lua camera control across a disposable pair."""

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
OUTPUT = ROOT / "runtime" / "lua_camera_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.camera_lab"
HOST_FOCUS = (256.25, 384.5)
CLIENT_FOCUS = (768.75, 512.5)
SHAKE_INTENSITY = 0.75
CAMERA_EPSILON = 0.05
QUIET_SHAKE_EPSILON = 0.0001


STATE_PROBE = f"""
local mod = assert(sd.runtime.get_mod())
local camera = assert(sd.camera.get_state())
local scene = assert(sd.world.get_scene(), "live scene required")
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local owner_count = 0
for _, participant in ipairs(multiplayer.participants or {{}}) do
  if participant.is_owner then owner_count = owner_count + 1 end
end
local namespace_count = 0
local namespace_exact = true
for name, value in pairs(sd.camera) do
  namespace_count = namespace_count + 1
  if (name ~= "get_state" and name ~= "set_focus" and
      name ~= "clear_focus" and name ~= "shake") or
      type(value) ~= "function" then
    namespace_exact = false
  end
end
namespace_exact = namespace_exact and namespace_count == 4

local function finite(value)
  return type(value) == "number" and
    value == value and value ~= math.huge and value ~= -math.huge
end

local allowed = {{
  available = true,
  scene_available = true,
  focus_active = true,
  owns_focus = true,
  origin_x = true,
  origin_y = true,
  width = true,
  height = true,
  center_x = true,
  center_y = true,
  scale = true,
  shake_magnitude = true,
  shake_accumulator = true,
  focus_x = true,
  focus_y = true,
}}
local schema_count = 0
local schema_exact = true
for key, _ in pairs(camera) do
  if type(key) ~= "string" or not allowed[key] then
    schema_exact = false
  end
  schema_count = schema_count + 1
end
local expected_schema_count = camera.focus_active and 15 or 13
schema_exact = schema_exact and schema_count == expected_schema_count
local numbers_finite = true
for _, field in ipairs({{
  "origin_x", "origin_y", "width", "height", "center_x", "center_y",
  "scale", "shake_magnitude", "shake_accumulator",
}}) do
  numbers_finite = numbers_finite and finite(camera[field])
end
local focus_fields_valid = false
if camera.focus_active then
  focus_fields_valid =
    camera.owns_focus == true and
    finite(camera.focus_x) and finite(camera.focus_y)
else
  focus_fields_valid =
    camera.owns_focus == false and
    camera.focus_x == nil and camera.focus_y == nil
end
local raw_addresses_absent = true
for _, key in ipairs({{
  "region_address",
  "world_address",
  "camera_address",
  "actor_address",
  "function_address",
  "pointer",
}}) do
  if camera[key] ~= nil then raw_addresses_absent = false end
end
local target_x = tonumber(_G.__lua_camera_acceptance_target_x)
local target_y = tonumber(_G.__lua_camera_acceptance_target_y)
local target_set = finite(target_x) and finite(target_y)
local focus_matches_target =
  target_set and camera.focus_active and
  math.abs(camera.focus_x - target_x) <= {CAMERA_EPSILON} and
  math.abs(camera.focus_y - target_y) <= {CAMERA_EPSILON}
local native_focus_applied =
  focus_matches_target and
  math.abs(camera.center_x - target_x) <= {CAMERA_EPSILON} and
  math.abs(camera.center_y - target_y) <= {CAMERA_EPSILON}
local shake_quiet =
  math.abs(camera.shake_magnitude) <= {QUIET_SHAKE_EPSILON} and
  math.abs(camera.shake_accumulator) <= {QUIET_SHAKE_EPSILON}

print("mod_id=" .. tostring(mod.id))
print("read_capability=" .. tostring(
  sd.runtime.has_capability("camera.local.read")))
print("focus_capability=" .. tostring(
  sd.runtime.has_capability("camera.local.focus")))
print("shake_capability=" .. tostring(
  sd.runtime.has_capability("camera.local.shake")))
print("authority=" .. tostring(sd.state.is_authority()))
print("world_scene=" .. tostring(scene.name or scene.kind))
print("participant_count=" .. tostring(multiplayer.participant_count))
print("participant_rows=" .. tostring(#(multiplayer.participants or {{}})))
print("owner_count=" .. tostring(owner_count))
print("namespace_exact=" .. tostring(namespace_exact))
print("available=" .. tostring(camera.available))
print("scene_available=" .. tostring(camera.scene_available))
print("focus_active=" .. tostring(camera.focus_active))
print("owns_focus=" .. tostring(camera.owns_focus))
print("width=" .. tostring(camera.width))
print("height=" .. tostring(camera.height))
print("scale=" .. tostring(camera.scale))
print("center_x=" .. tostring(camera.center_x))
print("center_y=" .. tostring(camera.center_y))
print("shake_magnitude=" .. tostring(camera.shake_magnitude))
print("shake_accumulator=" .. tostring(camera.shake_accumulator))
print("schema_exact=" .. tostring(schema_exact))
print("numbers_finite=" .. tostring(numbers_finite))
print("focus_fields_valid=" .. tostring(focus_fields_valid))
print("raw_addresses_absent=" .. tostring(raw_addresses_absent))
print("target_set=" .. tostring(target_set))
print("target_x=" .. tostring(target_x or 0))
print("target_y=" .. tostring(target_y or 0))
print("focus_matches_target=" .. tostring(focus_matches_target))
print("native_focus_applied=" .. tostring(native_focus_applied))
print("shake_quiet=" .. tostring(shake_quiet))
"""


def _focus_probe(target_x: float, target_y: float) -> str:
    return f"""
local initial = assert(sd.camera.get_state())
local extra_get_ok = pcall(sd.camera.get_state, true)
local nan_focus_ok = pcall(
  sd.camera.set_focus, 0 / 0, initial.center_y)
local huge_focus_ok = pcall(
  sd.camera.set_focus, 1000001, initial.center_y)
local missing_focus_ok = pcall(sd.camera.set_focus, {target_x})
local accepted = sd.camera.set_focus({target_x}, {target_y})
_G.__lua_camera_acceptance_target_x = {target_x}
_G.__lua_camera_acceptance_target_y = {target_y}
local focused = assert(sd.camera.get_state())
print("accepted=" .. tostring(accepted))
print("target_x=" .. tostring({target_x}))
print("target_y=" .. tostring({target_y}))
print("focus_active=" .. tostring(focused.focus_active))
print("owns_focus=" .. tostring(focused.owns_focus))
print("focus_x=" .. tostring(focused.focus_x))
print("focus_y=" .. tostring(focused.focus_y))
print("extra_get_rejected=" .. tostring(not extra_get_ok))
print("nan_focus_rejected=" .. tostring(not nan_focus_ok))
print("huge_focus_rejected=" .. tostring(not huge_focus_ok))
print("missing_focus_rejected=" .. tostring(not missing_focus_ok))
"""


HOST_FOCUS_PROBE = _focus_probe(*HOST_FOCUS)
CLIENT_FOCUS_PROBE = _focus_probe(*CLIENT_FOCUS)


SHAKE_PROBE = f"""
local before = assert(sd.camera.get_state())
local zero_ok = pcall(sd.camera.shake, 0)
local high_ok = pcall(sd.camera.shake, 1.01)
local nan_ok = pcall(sd.camera.shake, 0 / 0)
local extra_ok = pcall(sd.camera.shake, {SHAKE_INTENSITY}, true)
local accepted = sd.camera.shake({SHAKE_INTENSITY})
local after = assert(sd.camera.get_state())
local native_feedback_changed =
  after.shake_magnitude > before.shake_magnitude or
  after.shake_accumulator > before.shake_accumulator
print("accepted=" .. tostring(accepted))
print("before_magnitude=" .. tostring(before.shake_magnitude))
print("before_accumulator=" .. tostring(before.shake_accumulator))
print("after_magnitude=" .. tostring(after.shake_magnitude))
print("after_accumulator=" .. tostring(after.shake_accumulator))
print("native_feedback_changed=" .. tostring(native_feedback_changed))
print("zero_rejected=" .. tostring(not zero_ok))
print("high_rejected=" .. tostring(not high_ok))
print("nan_rejected=" .. tostring(not nan_ok))
print("extra_rejected=" .. tostring(not extra_ok))
"""


CLEAR_PROBE = """
local first = sd.camera.clear_focus()
local second = sd.camera.clear_focus()
_G.__lua_camera_acceptance_target_x = nil
_G.__lua_camera_acceptance_target_y = nil
local camera = assert(sd.camera.get_state())
print("first=" .. tostring(first))
print("second=" .. tostring(second))
print("focus_active=" .. tostring(camera.focus_active))
print("owns_focus=" .. tostring(camera.owns_focus))
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


def _float_value(values: dict[str, str], name: str) -> float:
    try:
        value = float(values.get(name, ""))
    except ValueError as error:
        raise RuntimeError(f"invalid {name}: {values}") from error
    if not math.isfinite(value):
        raise RuntimeError(f"non-finite {name}: {values}")
    return value


def _int_value(values: dict[str, str], name: str) -> int:
    try:
        return int(values.get(name, ""))
    except ValueError as error:
        raise RuntimeError(f"invalid {name}: {values}") from error


def _base_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    try:
        return (
            values.get("mod_id") == ACCEPTANCE_MOD_ID
            and values.get("read_capability") == "true"
            and values.get("focus_capability") == "true"
            and values.get("shake_capability") == "true"
            and values.get("authority") == ("true" if authority else "false")
            and values.get("world_scene") == "testrun"
            and _int_value(values, "participant_count") == 2
            and _int_value(values, "participant_rows") == 2
            and _int_value(values, "owner_count") == 1
            and values.get("namespace_exact") == "true"
            and values.get("available") == "true"
            and values.get("scene_available") == "true"
            and _float_value(values, "width") > 0.0
            and _float_value(values, "height") > 0.0
            and _float_value(values, "scale") > 0.0
            and math.isfinite(_float_value(values, "center_x"))
            and math.isfinite(_float_value(values, "center_y"))
            and _float_value(values, "shake_magnitude") >= 0.0
            and _float_value(values, "shake_accumulator") >= 0.0
            and values.get("schema_exact") == "true"
            and values.get("numbers_finite") == "true"
            and values.get("focus_fields_valid") == "true"
            and values.get("raw_addresses_absent") == "true"
        )
    except RuntimeError:
        return False


def idle_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
    require_quiet: bool = False,
) -> bool:
    return (
        _base_state_matches(values, authority=authority)
        and values.get("focus_active") == "false"
        and values.get("owns_focus") == "false"
        and values.get("target_set") == "false"
        and values.get("focus_matches_target") == "false"
        and values.get("native_focus_applied") == "false"
        and (not require_quiet or values.get("shake_quiet") == "true")
    )


def focused_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
    target: tuple[float, float],
    require_quiet: bool = False,
) -> bool:
    try:
        return (
            _base_state_matches(values, authority=authority)
            and values.get("focus_active") == "true"
            and values.get("owns_focus") == "true"
            and values.get("target_set") == "true"
            and math.isclose(
                _float_value(values, "target_x"),
                target[0],
                rel_tol=0.0,
                abs_tol=CAMERA_EPSILON,
            )
            and math.isclose(
                _float_value(values, "target_y"),
                target[1],
                rel_tol=0.0,
                abs_tol=CAMERA_EPSILON,
            )
            and values.get("focus_matches_target") == "true"
            and values.get("native_focus_applied") == "true"
            and (not require_quiet or values.get("shake_quiet") == "true")
        )
    except RuntimeError:
        return False


def focus_request_matches(
    values: dict[str, str],
    target: tuple[float, float],
) -> bool:
    try:
        return (
            values.get("accepted") == "true"
            and values.get("focus_active") == "true"
            and values.get("owns_focus") == "true"
            and math.isclose(
                _float_value(values, "target_x"),
                target[0],
                rel_tol=0.0,
                abs_tol=CAMERA_EPSILON,
            )
            and math.isclose(
                _float_value(values, "target_y"),
                target[1],
                rel_tol=0.0,
                abs_tol=CAMERA_EPSILON,
            )
            and math.isclose(
                _float_value(values, "focus_x"),
                target[0],
                rel_tol=0.0,
                abs_tol=CAMERA_EPSILON,
            )
            and math.isclose(
                _float_value(values, "focus_y"),
                target[1],
                rel_tol=0.0,
                abs_tol=CAMERA_EPSILON,
            )
            and all(
                values.get(name) == "true"
                for name in (
                    "extra_get_rejected",
                    "nan_focus_rejected",
                    "huge_focus_rejected",
                    "missing_focus_rejected",
                )
            )
        )
    except RuntimeError:
        return False


def shake_request_matches(values: dict[str, str]) -> bool:
    try:
        return (
            values.get("accepted") == "true"
            and values.get("native_feedback_changed") == "true"
            and _float_value(values, "after_magnitude")
            >= _float_value(values, "before_magnitude")
            and _float_value(values, "after_accumulator")
            >= _float_value(values, "before_accumulator")
            and all(
                values.get(name) == "true"
                for name in (
                    "zero_rejected",
                    "high_rejected",
                    "nan_rejected",
                    "extra_rejected",
                )
            )
        )
    except RuntimeError:
        return False


def clear_request_matches(values: dict[str, str]) -> bool:
    return (
        values.get("first") == "true"
        and values.get("second") == "false"
        and values.get("focus_active") == "false"
        and values.get("owns_focus") == "false"
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


def _poll_probe(
    client: tuple[str, str],
    predicate: Callable[[dict[str, str]], bool],
    *,
    timeout: float,
    description: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = run_lua_client(
            client[0],
            client[1],
            STATE_PROBE,
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
        f"{description} did not converge for {client[0]}: {last}"
    )


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


def run(
    clients: list[tuple[str, str]],
    *,
    launch: bool,
    timeout: float,
) -> dict[str, Any]:
    if not launch:
        raise RuntimeError("Lua camera acceptance requires --launch-pair")
    if len(clients) != 2:
        raise RuntimeError("exactly one host and one client endpoint are required")
    host = clients[0]
    client = clients[1]
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

        result["initial"] = [
            _poll_probe(
                peer,
                lambda values, authority=index == 0: idle_state_matches(
                    values,
                    authority=authority,
                    require_quiet=True,
                ),
                timeout=timeout,
                description="quiescent local camera",
            )
            for index, peer in enumerate((host, client))
        ]

        result["host_focus_request"] = _require_action(
            host,
            HOST_FOCUS_PROBE,
            lambda values: focus_request_matches(values, HOST_FOCUS),
            "host local focus request",
        )
        result["host_focus_isolation"] = [
            _poll_probe(
                host,
                lambda values: focused_state_matches(
                    values,
                    authority=True,
                    target=HOST_FOCUS,
                    require_quiet=True,
                ),
                timeout=timeout,
                description="host native focus",
            ),
            _poll_probe(
                client,
                lambda values: idle_state_matches(
                    values,
                    authority=False,
                    require_quiet=True,
                ),
                timeout=timeout,
                description="client focus isolation",
            ),
        ]

        result["client_focus_request"] = _require_action(
            client,
            CLIENT_FOCUS_PROBE,
            lambda values: focus_request_matches(values, CLIENT_FOCUS),
            "client local focus request",
        )
        result["independent_focus"] = [
            _poll_probe(
                host,
                lambda values: focused_state_matches(
                    values,
                    authority=True,
                    target=HOST_FOCUS,
                    require_quiet=True,
                ),
                timeout=timeout,
                description="retained host focus",
            ),
            _poll_probe(
                client,
                lambda values: focused_state_matches(
                    values,
                    authority=False,
                    target=CLIENT_FOCUS,
                    require_quiet=True,
                ),
                timeout=timeout,
                description="client native focus",
            ),
        ]

        result["host_shake"] = _require_action(
            host,
            SHAKE_PROBE,
            shake_request_matches,
            "host native camera shake",
        )
        result["shake_isolation"] = [
            _poll_probe(
                host,
                lambda values: focused_state_matches(
                    values,
                    authority=True,
                    target=HOST_FOCUS,
                ),
                timeout=timeout,
                description="host focus after shake",
            ),
            _poll_probe(
                client,
                lambda values: focused_state_matches(
                    values,
                    authority=False,
                    target=CLIENT_FOCUS,
                    require_quiet=True,
                ),
                timeout=timeout,
                description="client shake isolation",
            ),
        ]

        result["clear"] = [
            _require_action(
                peer,
                CLEAR_PROBE,
                clear_request_matches,
                f"{peer[0]} focus clear",
            )
            for peer in (host, client)
        ]
        result["released"] = [
            _poll_probe(
                peer,
                lambda values, authority=index == 0: idle_state_matches(
                    values,
                    authority=authority,
                ),
                timeout=timeout,
                description="released local camera",
            )
            for index, peer in enumerate((host, client))
        ]
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
        help="confirm local camera mutation and one isolated run entry",
    )
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.confirm_mutation:
        result["error"] = "refusing camera mutation without --confirm-mutation"
        return_code = 2
    elif not args.launch_pair:
        result["error"] = "Lua camera acceptance requires --launch-pair"
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
