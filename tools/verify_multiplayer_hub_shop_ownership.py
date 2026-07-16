#!/usr/bin/env python3
"""Verify stock hub purchases mutate and replicate only the purchasing player."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any, Callable

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_ID,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    lua,
    parse_key_values,
    place_player,
    stop_games,
    wait_for_both_hub_settled,
)
from verify_multiplayer_hub_inventory_shop_sync import (
    click_relative,
    hold_real_key,
    local_inventory,
    participant_inventory,
    settle_mouse_release,
)
from verify_multiplayer_inventory_audit import capture


OUTPUT = ROOT / "runtime/multiplayer_hub_shop_ownership.json"
POTION_TYPE_ID = 0x1B59


PLAYER_RUNTIME_LUA = r"""
local function emit(key, value) print(key .. "=" .. tostring(value or "")) end
local player = sd.player.get_state()
emit("local.gold", player and player.gold or 0)
emit("local.hp", player and player.hp or 0)
emit("local.max_hp", player and player.max_hp or 0)
emit("local.mp", player and player.mp or 0)
emit("local.max_mp", player and player.max_mp or 0)
local multiplayer = sd.runtime.get_multiplayer_state()
local target = __TARGET_PARTICIPANT__
local remote = nil
for _, participant in ipairs(multiplayer and multiplayer.participants or {}) do
  if (participant.participant_id or 0) == target then remote = participant break end
end
emit("remote.present", remote ~= nil)
emit("remote.life_current", remote and remote.life_current or 0)
emit("remote.life_max", remote and remote.life_max or 0)
emit("remote.mana_current", remote and remote.mana_current or 0)
emit("remote.mana_max", remote and remote.mana_max or 0)
emit("remote.move_speed", remote and remote.move_speed or 0)
emit("remote.persistent_status_flags", remote and remote.persistent_status_flags or 0)
"""


def number(value: str | None) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0.0


def runtime_capture(pipe_name: str, remote_participant_id: int) -> dict[str, Any]:
    values = parse_key_values(
        lua(
            pipe_name,
            PLAYER_RUNTIME_LUA.replace(
                "__TARGET_PARTICIPANT__", f"0x{remote_participant_id:X}"
            ),
            timeout=5.0,
        )
    )
    return {
        "local": {
            "gold": int(number(values.get("local.gold"))),
            "hp": number(values.get("local.hp")),
            "max_hp": number(values.get("local.max_hp")),
            "mp": number(values.get("local.mp")),
            "max_mp": number(values.get("local.max_mp")),
        },
        "remote": {
            "present": values.get("remote.present") == "true",
            "life_current": number(values.get("remote.life_current")),
            "life_max": number(values.get("remote.life_max")),
            "mana_current": number(values.get("remote.mana_current")),
            "mana_max": number(values.get("remote.mana_max")),
            "move_speed": number(values.get("remote.move_speed")),
            "persistent_status_flags": int(
                number(values.get("remote.persistent_status_flags"))
            ),
        },
    }


def snapshot() -> dict[str, Any]:
    host_values = capture(HOST_PIPE)
    client_values = capture(CLIENT_PIPE)
    return {
        "host_runtime": runtime_capture(HOST_PIPE, CLIENT_ID),
        "client_runtime": runtime_capture(CLIENT_PIPE, HOST_ID),
        "host_local_inventory": local_inventory(host_values),
        "client_local_inventory": local_inventory(client_values),
        "host_view_client": participant_inventory(host_values, CLIENT_ID),
        "client_view_host": participant_inventory(client_values, HOST_ID),
        "host_view_client_gold": {
            "value": next(
                row["gold"]
                for row in _participant_rows(host_values)
                if row["id"] == CLIENT_ID
            ),
            "revision": next(
                row["gold_revision"]
                for row in _participant_rows(host_values)
                if row["id"] == CLIENT_ID
            ),
        },
        "client_view_host_gold": {
            "value": next(
                row["gold"]
                for row in _participant_rows(client_values)
                if row["id"] == HOST_ID
            ),
            "revision": next(
                row["gold_revision"]
                for row in _participant_rows(client_values)
                if row["id"] == HOST_ID
            ),
        },
    }


def _participant_rows(values: dict[str, str]) -> list[dict[str, Any]]:
    from verify_multiplayer_inventory_audit import participant_rows

    return participant_rows(values)


def wait_for(
    description: str,
    assertion: Callable[[dict[str, Any]], None],
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = snapshot()
            assertion(last)
            return last
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.2)
    raise VerifyFailure(
        f"{description} did not converge: last_error={last_error} last={last}"
    )


def launch_ready() -> tuple[dict[str, object], int, dict[str, Any]]:
    stop_games()
    launch = launch_pair(allow_focus_steal=True)
    disable_bots()
    wait_for_both_hub_settled()
    baseline = wait_for(
        "hub shop baseline",
        lambda state: assert_baseline(state),
        15.0,
    )
    return launch, int(launch["hostProcessId"]), baseline


def assert_baseline(state: dict[str, Any]) -> None:
    if not state["client_runtime"]["remote"]["present"]:
        raise VerifyFailure("client does not observe host runtime")
    if not state["host_runtime"]["remote"]["present"]:
        raise VerifyFailure("host does not observe client runtime")
    if state["client_view_host_gold"]["value"] != state["host_runtime"]["local"]["gold"]:
        raise VerifyFailure("client host-gold ledger is not converged")
    if state["host_view_client_gold"]["value"] != state["client_runtime"]["local"]["gold"]:
        raise VerifyFailure("host client-gold ledger is not converged")


def click_twice_after_selection(
    pid: int,
    x: float,
    y: float,
    selection_settle_seconds: float = 1.0,
) -> dict[str, str]:
    selected = click_relative(pid, x, y)
    time.sleep(selection_settle_seconds)
    purchased = click_relative(pid, x, y)
    release = settle_mouse_release()
    return {"selected": selected, "purchased": purchased, "release": release}


def open_fomentius(pid: int) -> dict[str, Any]:
    placement = place_player(HOST_PIPE, 1332.0, 664.0, 90.0)
    movement = hold_real_key(pid, "D", 900)
    time.sleep(0.8)
    skip = click_relative(pid, 0.50, 0.44)
    time.sleep(0.8)
    buy = click_relative(pid, 0.50, 0.26)
    time.sleep(1.2)
    return {"placement": placement, "movement": movement, "skip": skip, "buy": buy}


def open_hagatha(pid: int) -> dict[str, Any]:
    intro_placement = place_player(HOST_PIPE, 1340.0, 350.0, 0.0)
    intro_movement = hold_real_key(pid, "W", 1500)
    time.sleep(1.2)
    dismiss_intro = click_relative(pid, 0.50, 0.44)
    time.sleep(1.0)
    menu_placement = place_player(HOST_PIPE, 1340.0, 350.0, 0.0)
    menu_movement = hold_real_key(pid, "W", 1500)
    time.sleep(1.2)
    buy = click_relative(pid, 0.50, 0.24)
    time.sleep(2.0)
    return {
        "intro_placement": intro_placement,
        "intro_movement": intro_movement,
        "dismiss_intro": dismiss_intro,
        "menu_placement": menu_placement,
        "menu_movement": menu_movement,
        "buy_charms_and_curses": buy,
    }


def total_potion_stack(inventory: dict[str, Any], slot: int) -> int:
    return sum(
        int(row["stack_count"])
        for row in inventory["items"]
        if row["type_id"] == POTION_TYPE_ID and row["slot"] == slot
    )


def verify_fomentius(timeout: float, result: dict[str, Any]) -> dict[str, Any]:
    launch, pid, baseline = launch_ready()
    result["launch"] = launch
    result["baseline"] = baseline
    baseline_host_gold = baseline["host_runtime"]["local"]["gold"]
    baseline_client_gold = baseline["client_runtime"]["local"]["gold"]
    baseline_host_stack = total_potion_stack(baseline["host_local_inventory"], 0)
    baseline_client_inventory = baseline["client_local_inventory"]["semantic_items"]
    baseline_gold_revision = baseline["client_view_host_gold"]["revision"]
    baseline_inventory_revision = baseline["client_view_host"]["revision"]

    result["open_shop"] = open_fomentius(pid)
    result["purchase"] = click_twice_after_selection(pid, 0.36, 0.10)

    def purchased(state: dict[str, Any]) -> None:
        host_gold = state["host_runtime"]["local"]["gold"]
        if not 0 < baseline_host_gold - host_gold <= baseline_host_gold:
            raise VerifyFailure(f"Fomentius did not spend host gold: {state}")
        if state["client_runtime"]["local"]["gold"] != baseline_client_gold:
            raise VerifyFailure("host purchase changed the client's native gold")
        if state["client_local_inventory"]["semantic_items"] != baseline_client_inventory:
            raise VerifyFailure("host purchase changed the client's native backpack")
        if total_potion_stack(state["host_local_inventory"], 0) != baseline_host_stack + 1:
            raise VerifyFailure("purchased health potion did not stack in host backpack")
        if state["client_view_host_gold"]["value"] != host_gold:
            raise VerifyFailure("client did not observe exact purchased host gold")
        if state["client_view_host_gold"]["revision"] <= baseline_gold_revision:
            raise VerifyFailure("host gold revision did not advance")
        if state["client_view_host"]["revision"] <= baseline_inventory_revision:
            raise VerifyFailure("host inventory revision did not advance")
        if (
            state["client_view_host"]["semantic_items"]
            != state["host_local_inventory"]["semantic_items"]
        ):
            raise VerifyFailure("client did not observe exact purchased host backpack")

    result["purchased"] = wait_for("Fomentius purchase", purchased, timeout)
    result["price_paid"] = (
        baseline_host_gold - result["purchased"]["host_runtime"]["local"]["gold"]
    )
    result["ok"] = True
    return result


def verify_hagatha(timeout: float, result: dict[str, Any]) -> dict[str, Any]:
    launch, pid, baseline = launch_ready()
    result["launch"] = launch
    result["baseline"] = baseline
    baseline_host = baseline["host_runtime"]["local"]
    baseline_client = baseline["client_runtime"]["local"]
    baseline_host_inventory = baseline["host_local_inventory"]["semantic_items"]
    baseline_client_inventory = baseline["client_local_inventory"]["semantic_items"]
    baseline_gold_revision = baseline["client_view_host_gold"]["revision"]
    if baseline_host["gold"] < 600:
        raise VerifyFailure(f"fresh host lacks the 600 gold needed for Life Charm: {baseline_host}")

    result["open_shop"] = open_hagatha(pid)
    result["purchase"] = click_twice_after_selection(
        pid, 0.36, 0.10, selection_settle_seconds=2.0
    )

    def purchased(state: dict[str, Any]) -> None:
        host = state["host_runtime"]["local"]
        client = state["client_runtime"]["local"]
        remote_host = state["client_runtime"]["remote"]
        if baseline_host["gold"] - host["gold"] != 600:
            raise VerifyFailure(f"Life Charm did not spend exactly 600 gold: {state}")
        expected_max_hp = baseline_host["max_hp"] * 1.25
        if abs(host["max_hp"] - expected_max_hp) > 0.01:
            raise VerifyFailure(f"Life Charm did not raise owner max HP by 25%: {state}")
        if abs(host["hp"] - host["max_hp"]) > 0.01:
            raise VerifyFailure(f"Life Charm did not preserve full owner life ratio: {state}")
        if client != baseline_client:
            raise VerifyFailure(f"host Life Charm changed client native stats/gold: {state}")
        if state["host_local_inventory"]["semantic_items"] != baseline_host_inventory:
            raise VerifyFailure("Life Charm unexpectedly entered the host backpack")
        if state["client_local_inventory"]["semantic_items"] != baseline_client_inventory:
            raise VerifyFailure("Life Charm changed the client backpack")
        if abs(remote_host["life_max"] - host["max_hp"]) > 0.01:
            raise VerifyFailure("client did not observe exact Life Charm max HP")
        if abs(remote_host["life_current"] - host["hp"]) > 0.01:
            raise VerifyFailure("client did not observe exact Life Charm current HP")
        if state["client_view_host_gold"]["value"] != host["gold"]:
            raise VerifyFailure("client did not observe exact Life Charm gold spend")
        if state["client_view_host_gold"]["revision"] <= baseline_gold_revision:
            raise VerifyFailure("Life Charm gold revision did not advance")

    result["purchased"] = wait_for("Hagatha Life Charm purchase", purchased, timeout)
    result["ok"] = True
    return result


def run(args: argparse.Namespace, result: dict[str, Any]) -> dict[str, Any]:
    if args.scenario in ("all", "fomentius"):
        result["fomentius"] = {"ok": False}
        try:
            verify_fomentius(args.timeout, result["fomentius"])
        finally:
            if not args.keep_open:
                stop_games()
    if args.scenario in ("all", "hagatha"):
        result["hagatha"] = {"ok": False}
        try:
            verify_hagatha(args.timeout, result["hagatha"])
        finally:
            if not args.keep_open:
                stop_games()
    result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario", choices=("all", "fomentius", "hagatha"), default="all"
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        run(args, result)
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        return_code = 1
    finally:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": result.get("ok", False),
            "error": result.get("error", ""),
            "output": str(OUTPUT),
        }, indent=2, sort_keys=True))
        if not args.keep_open:
            stop_games()
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
