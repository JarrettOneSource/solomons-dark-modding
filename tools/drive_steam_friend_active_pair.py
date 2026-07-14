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
            timeout=5.0,
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
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    actions: list[dict[str, str]] = []
    last: dict[str, Any] = {}
    main_menu_first_seen_at: float | None = None
    run_entry_dispatched = False
    while time.monotonic() < deadline:
        last = query_navigation_state(pair, endpoint)
        if last["scene"] in ("hub", "testrun"):
            return {"scene": last["scene"], "actions": actions}

        available = set(last["actions"])
        action: tuple[str, str] | None = None
        if last["surface"] == "dialog" and "dialog.primary" in available:
            action = ("dialog.primary", "dialog")
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
            # A reconnecting profile can expose both LAST GAME and NEW GAME.
            # Prefer the stock resume route: the multiplayer transition hook
            # redirects it to canonical character setup without invalidating
            # the menu's live task list. NEW GAME remains the fresh-profile
            # fallback when no saved run exists.
            elif (
                "main_menu.resume_last_game" in available
                and not run_entry_dispatched
            ):
                action = ("main_menu.resume_last_game", "main_menu")
            elif "main_menu.new_game" in available and not run_entry_dispatched:
                action = ("main_menu.new_game", "main_menu")
        elif last["surface"] == "create":
            created = local_sync.complete_native_create(
                endpoint,
                element=element,
                discipline=discipline,
                timeout=min(45.0, max(5.0, deadline - time.monotonic())),
            )
            actions.extend(created["actions"])
            return {"scene": created["scene"], "actions": actions}

        if action is None:
            time.sleep(0.1)
            continue

        action_id, surface_id = action
        if action_id in ("main_menu.resume_last_game", "main_menu.new_game"):
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
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

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
        )
        output["client"] = drive_one_to_hub(
            pair,
            CLIENT_ENDPOINT,
            element=args.client_element,
            discipline=args.discipline,
            timeout=args.timeout,
        )
        if args.start_run:
            host_view = local_sync.query(HOST_ENDPOINT)
            client_view = local_sync.query(CLIENT_ENDPOINT)
            local_sync.CLIENT_NAME = host_view.get(
                f"peer.{pair.client_participant_id}.name", ""
            )
            local_sync.HOST_NAME = client_view.get(
                f"peer.{pair.host_participant_id}.name", ""
            )
            if host_view.get("scene") == "testrun":
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
