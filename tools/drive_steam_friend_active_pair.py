#!/usr/bin/env python3
"""Drive an authenticated two-account Steam pair through native onboarding."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import verify_local_multiplayer_sync as local_sync
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import VerifyFailure, parse_key_values


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_active_pair_onboarding.json"
READY_SCENE_STABILITY_SECONDS = 1.0
BLOCKING_ONBOARDING_SURFACES = frozenset(
    ("dialog", "main_menu", "create", "simple_menu")
)


TEST_GODMODE_LUA = r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local function sustain()
  if _G.__sdmod_steam_test_godmode_enabled ~= true then
    return false, 'disabled'
  end
  local player = sd.player.get_state()
  if type(player) ~= 'table' then return false, 'player_unavailable' end
  local progression = tonumber(player.progression_address) or 0
  if progression == 0 then return false, 'progression_unavailable' end
  local hp_offset = sd.debug.layout_offset('progression_hp')
  local max_hp_offset = sd.debug.layout_offset('progression_max_hp')
  local mp_offset = sd.debug.layout_offset('progression_mp')
  local max_mp_offset = sd.debug.layout_offset('progression_max_mp')
  local max_hp = tonumber(sd.debug.read_float(progression + max_hp_offset)) or 0
  local max_mp = tonumber(sd.debug.read_float(progression + max_mp_offset)) or 0
  if max_hp > 0 then sd.debug.write_float(progression + hp_offset, max_hp) end
  if max_mp > 0 then sd.debug.write_float(progression + mp_offset, max_mp) end
  return true, 'ok'
end
if not _G.__sdmod_steam_test_godmode_enabled then
  _G.__sdmod_steam_test_godmode_enabled = true
  sd.events.on('runtime.tick', sustain)
end
local applied, status = sustain()
emit('registered', true)
emit('initial_apply', applied)
emit('status', status)
"""


DISABLE_TEST_GODMODE_LUA = r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
_G.__sdmod_steam_test_godmode_enabled = false
emit('enabled', _G.__sdmod_steam_test_godmode_enabled)
"""


TEST_MANUAL_ENEMY_MODE_LUA = r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local function local_participant_in_run()
  local state = sd.runtime.get_multiplayer_state()
  for _, participant in ipairs(state and state.participants or {}) do
    if participant.is_owner then
      return participant.in_run == true
    end
  end
  return false
end
local function sustain()
  if _G.__sdmod_steam_test_manual_enemy_mode_enabled ~= true then
    return false, 'disabled'
  end
  if not local_participant_in_run() then
    return false, 'not_in_run'
  end
  local state = sd.gameplay.get_manual_enemy_spawner_state()
  if state and state.manual_mode then
    return true, 'ok'
  end
  local ok, active = sd.gameplay.set_manual_enemy_spawner_test_mode(true)
  return ok == true and active == true, active and 'ok' or 'activation_failed'
end
if not _G.__sdmod_steam_test_manual_enemy_mode_registered then
  sd.events.on('runtime.tick', sustain)
  _G.__sdmod_steam_test_manual_enemy_mode_registered = true
end
_G.__sdmod_steam_test_manual_enemy_mode_enabled = true
local applied, status = sustain()
emit('registered', _G.__sdmod_steam_test_manual_enemy_mode_registered)
emit('initial_apply', applied)
emit('status', status)
"""


DISABLE_TEST_MANUAL_ENEMY_MODE_LUA = r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
_G.__sdmod_steam_test_manual_enemy_mode_enabled = false
local ok, active = sd.gameplay.set_manual_enemy_spawner_test_mode(false)
emit('ok', ok)
emit('active', active)
emit('enabled', _G.__sdmod_steam_test_manual_enemy_mode_enabled)
"""


def arm_test_godmode(
    pair: SteamFriendActivePair, endpoint: str
) -> dict[str, str]:
    values = parse_key_values(pair.lua(endpoint, TEST_GODMODE_LUA, timeout=8.0))
    if values.get("registered") != "true":
        raise VerifyFailure(f"failed to register test godmode on {endpoint}: {values}")
    return values


def disable_test_godmode(
    pair: SteamFriendActivePair, endpoint: str
) -> dict[str, str]:
    values = parse_key_values(
        pair.lua(endpoint, DISABLE_TEST_GODMODE_LUA, timeout=8.0)
    )
    if values.get("enabled") != "false":
        raise VerifyFailure(
            f"failed to disable test godmode on {endpoint}: {values}"
        )
    return values


def arm_test_manual_enemy_mode(
    pair: SteamFriendActivePair, endpoint: str
) -> dict[str, str]:
    values = parse_key_values(
        pair.lua(endpoint, TEST_MANUAL_ENEMY_MODE_LUA, timeout=8.0)
    )
    if values.get("registered") != "true":
        raise VerifyFailure(
            f"failed to register test manual enemy mode on {endpoint}: {values}"
        )
    return values


def disable_test_manual_enemy_mode(
    pair: SteamFriendActivePair,
    endpoint: str,
) -> dict[str, str]:
    values = parse_key_values(
        pair.lua(endpoint, DISABLE_TEST_MANUAL_ENEMY_MODE_LUA, timeout=8.0)
    )
    if (
        values.get("ok") != "true"
        or values.get("active") != "false"
        or values.get("enabled") != "false"
    ):
        raise VerifyFailure(
            f"failed to disable test manual enemy mode on {endpoint}: {values}"
        )
    return values


def parse_run_generation_seed(value: str) -> int:
    seed = int(value, 0)
    if not 0 <= seed <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("run generation seed must fit in uint32")
    return seed


def set_run_generation_seed(
    pair: SteamFriendActivePair,
    seed: int,
) -> dict[str, str]:
    values = parse_key_values(
        pair.lua(
            HOST_ENDPOINT,
            "print('ok=' .. tostring(sd.debug.set_run_generation_seed(" +
            str(seed) + ")))"
        )
    )
    if values.get("ok") != "true":
        raise VerifyFailure(f"failed to set run generation seed: {values}")
    values["seed"] = f"0x{seed:08X}"
    return values


def query_navigation_state(
    pair: SteamFriendActivePair, endpoint: str
) -> dict[str, Any]:
    values = parse_key_values(
        pair.lua(
            endpoint,
            r"""
local scene = sd.world.get_scene()
local snapshot = sd.ui.get_snapshot()
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
emit('scene', scene and (scene.name or scene.kind) or '')
emit('surface', snapshot and snapshot.surface_id or '')
local count = 0
for _, element in ipairs(snapshot and snapshot.elements or {}) do
  local action_id = tostring(element.action_id or '')
  if action_id ~= '' then
    count = count + 1
    emit('action.' .. count, action_id)
  end
end
emit('action_count', count)
""",
            timeout=local_sync.NATIVE_UI_LUA_TIMEOUT_SECONDS,
        )
    )
    count = local_sync.parse_int_text(values.get("action_count"), 0)
    return {
        "scene": values.get("scene", ""),
        "surface": values.get("surface", ""),
        "actions": [
            values[f"action.{index}"]
            for index in range(1, count + 1)
            if values.get(f"action.{index}")
        ],
    }


def state_signature(state: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    return (
        str(state["scene"]),
        str(state["surface"]),
        tuple(str(action) for action in state["actions"]),
    )


def wait_for_navigation_change(
    pair: SteamFriendActivePair,
    endpoint: str,
    previous: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    previous_signature = state_signature(previous)
    deadline = time.monotonic() + timeout
    last = previous
    while time.monotonic() < deadline:
        last = query_navigation_state(pair, endpoint)
        if state_signature(last) != previous_signature:
            return last
        time.sleep(0.1)
    raise VerifyFailure(
        "native onboarding action dispatched but the UI did not transition: "
        f"endpoint={endpoint} state={last}"
    )


def drive_one_to_hub(
    pair: SteamFriendActivePair,
    endpoint: str,
    *,
    element: str,
    discipline: str,
    timeout: float,
    exercise_last_game_redirect: bool = False,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    actions: list[dict[str, str]] = []
    last: dict[str, Any] = {}
    main_menu_first_seen_at: float | None = None
    ready_scene = ""
    ready_since: float | None = None
    run_entry_dispatched = False
    while time.monotonic() < deadline:
        last = query_navigation_state(pair, endpoint)
        available = set(last["actions"])
        action: tuple[str, str] | None = None
        if last["surface"] == "dialog" and "dialog.primary" in available:
            action = ("dialog.primary", "dialog")
        elif (
            last["scene"] in ("hub", "testrun")
            and last["surface"] not in BLOCKING_ONBOARDING_SURFACES
        ):
            now = time.monotonic()
            if ready_scene != last["scene"]:
                ready_scene = last["scene"]
                ready_since = now
            elif (
                ready_since is not None
                and now - ready_since >= READY_SCENE_STABILITY_SECONDS
            ):
                return {"scene": last["scene"], "actions": actions}
            time.sleep(0.1)
            continue
        elif last["surface"] == "main_menu":
            if main_menu_first_seen_at is None:
                main_menu_first_seen_at = time.monotonic()
            # The one-time beta dialog is created shortly after the first menu
            # frame. Let it become dominant before navigating so it cannot
            # interrupt a committed NEW GAME transition.
            if not actions and time.monotonic() - main_menu_first_seen_at < 1.0:
                time.sleep(0.1)
                continue
            if "main_menu.play" in available:
                action = ("main_menu.play", "main_menu")
            elif not run_entry_dispatched:
                if exercise_last_game_redirect:
                    if "main_menu.resume_last_game" in available:
                        action = ("main_menu.resume_last_game", "main_menu")
                    elif "main_menu.new_game" in available:
                        raise VerifyFailure(
                            "LAST GAME redirect regression requested, but the saved-run action is unavailable"
                        )
                # Normal connected multiplayer always starts from the native
                # New Game preparation path; saved-run geometry is not shared.
                elif "main_menu.new_game" in available:
                    action = ("main_menu.new_game", "main_menu")
        elif last["surface"] == "create":
            created = local_sync.complete_native_create(
                endpoint,
                element=element,
                discipline=discipline,
                timeout=min(45.0, max(5.0, deadline - time.monotonic())),
            )
            actions.extend(created["actions"])
            ready_scene = ""
            ready_since = None
            continue

        if last["scene"] not in ("hub", "testrun"):
            ready_scene = ""
            ready_since = None

        if action is None:
            time.sleep(0.1)
            continue

        ready_scene = ""
        ready_since = None
        action_id, surface_id = action
        if action_id in ("main_menu.new_game", "main_menu.resume_last_game"):
            run_entry_dispatched = True
        actions.append(
            local_sync.activate_native_ui_action(endpoint, action_id, surface_id)
        )
        # Dispatch success only means the game's handler ran. Wait for the
        # surface or action set to change before considering another action;
        # reissuing NEW GAME against the old frame can corrupt the transition.
        wait_for_navigation_change(pair, endpoint, last, min(15.0, timeout))

    raise VerifyFailure(
        f"timed out driving native onboarding on {endpoint}: last={last}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-element", default="fire")
    parser.add_argument("--client-element", default="air")
    parser.add_argument("--discipline", default="arcane")
    parser.add_argument("--start-run", action="store_true")
    parser.add_argument(
        "--run-generation-seed",
        type=parse_run_generation_seed,
        help="Set an exact host run seed before --start-run.",
    )
    parser.add_argument("--test-godmode", action="store_true")
    parser.add_argument("--test-manual-enemy-mode", action="store_true")
    parser.add_argument("--exercise-last-game-redirect", action="store_true")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.run_generation_seed is not None and not args.start_run:
        parser.error("--run-generation-seed requires --start-run")

    pair = SteamFriendActivePair()
    output: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        output["pair"] = pair.discover()
        local_sync.lua = pair.lua
        local_sync.HOST_ID = pair.host_participant_id
        local_sync.CLIENT_ID = pair.client_participant_id
        local_sync.HOST_PIPE = HOST_ENDPOINT
        local_sync.CLIENT_PIPE = CLIENT_ENDPOINT
        output["host"] = drive_one_to_hub(
            pair,
            HOST_ENDPOINT,
            element=args.host_element,
            discipline=args.discipline,
            timeout=args.timeout,
            exercise_last_game_redirect=args.exercise_last_game_redirect,
        )
        host_view_before_client = local_sync.query(HOST_ENDPOINT)
        if (
            host_view_before_client.get("scene") == "testrun"
            and host_view_before_client.get("local.in_run") != "true"
        ):
            raise VerifyFailure(
                "host is still presenting an ended run; refusing to start a competing client scene load"
            )
        output["client"] = drive_one_to_hub(
            pair,
            CLIENT_ENDPOINT,
            element=args.client_element,
            discipline=args.discipline,
            timeout=args.timeout,
            exercise_last_game_redirect=args.exercise_last_game_redirect,
        )
        if args.test_godmode:
            output["test_godmode"] = {
                "host": arm_test_godmode(pair, HOST_ENDPOINT),
                "client": arm_test_godmode(pair, CLIENT_ENDPOINT),
            }
        if args.test_manual_enemy_mode:
            output["test_manual_enemy_mode"] = {
                "host": arm_test_manual_enemy_mode(pair, HOST_ENDPOINT),
                "client": arm_test_manual_enemy_mode(pair, CLIENT_ENDPOINT),
            }
        if args.start_run:
            host_view = local_sync.query(HOST_ENDPOINT)
            client_view = local_sync.query(CLIENT_ENDPOINT)
            local_sync.CLIENT_NAME = host_view.get(
                f"peer.{pair.client_participant_id}.name", ""
            )
            local_sync.HOST_NAME = client_view.get(
                f"peer.{pair.host_participant_id}.name", ""
            )
            if (
                host_view.get("scene") == "testrun"
                and host_view.get("local.in_run") == "true"
            ):
                if args.run_generation_seed is not None:
                    raise VerifyFailure(
                        "cannot set a run generation seed after the host entered a run"
                    )
                # A reconnecting client can reach its hub after the host is
                # already in a run. The replicated host-run state immediately
                # advances that client into the same run, so there is no hub
                # window in which a fresh host start can or should be tested.
                local_sync.wait_for_scene(CLIENT_ENDPOINT, "testrun", timeout=45.0)
                output["run_entry"] = {
                    "host_started": False,
                    "client_followed_host": True,
                    "rejoined_active_run": True,
                    "scene": "testrun",
                }
            else:
                if args.run_generation_seed is not None:
                    output["run_generation_seed"] = set_run_generation_seed(
                        pair,
                        args.run_generation_seed,
                    )
                output["client_start_blocked"] = (
                    local_sync.assert_client_start_testrun_blocked()
                )
                output["run_entry"] = (
                    local_sync.start_host_testrun_and_wait_for_clients(
                        timeout=45.0
                    )
                )
            output["run_bootstrap"] = local_sync.verify_run_entry_bootstrap(
                timeout=20.0
            )
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, OSError, ValueError) as exc:
        output["error"] = str(exc)
    finally:
        pair.close()
        output = pair.redact(output)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "error": output.get("error"),
                "host_scene": output.get("host", {}).get("scene"),
                "client_scene": output.get("client", {}).get("scene"),
                "run_started": "run_entry" in output,
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
