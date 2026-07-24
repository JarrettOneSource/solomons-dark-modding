#!/usr/bin/env python3
"""Verify dead-player progression, same-actor loadout, and wave respawn cancellation."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import verify_multiplayer_death_spectator_respawn as death
import verify_multiplayer_inventory_audit as inventory
import verify_multiplayer_level_up_offer_sync as level_up
from multiplayer_frame_capture import capture_game_backbuffer
from multiplayer_progression_probe import query_progression_snapshot
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    HOST_ID,
    HOST_NAME,
    ROOT,
    VerifyFailure,
    game_process_ids,
    launch_pair,
    lua,
    nudge_player,
    place_player,
    path_for_powershell,
    parse_int_text,
    parse_key_values,
    select_available_windows_udp_ports,
    snap_to_nav,
    stop_game_processes,
    wait_for_remote,
    wait_for_scene,
)


OUTPUT = ROOT / "runtime" / "multiplayer_dead_progression_round_respawn.json"
SCREENSHOT_ROOT = (
    ROOT / "runtime" / "multiplayer_dead_progression_round_respawn"
)
ACCEPTANCE_MOD_ID = "sample.lua.ui_sandbox_lab"
WAVE_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "waves"
    / "death_spectator_respawn_test.txt"
)
STAFF_TYPE_ID = 0x1B5C
VITAL_TOLERANCE = 0.05
POSITION_TOLERANCE = 0.25
REMOTE_POSITION_TOLERANCE = 3.0
FAR_FROM_SPAWN_MINIMUM = 220.0
CLICK_WINDOW = ROOT / "scripts" / "click_window.py"
FIRST_PICKER_OPTION_X = 0.375
PICKER_OPTION_Y = 0.5


def _click_owned_window(
    process_id: int,
    x: float,
    y: float,
) -> dict[str, Any]:
    command = subprocess.list2cmdline(
        [
            "py",
            "-3",
            path_for_powershell(CLICK_WINDOW),
            "--pid",
            str(process_id),
            "--relative",
            "--x",
            str(x),
            "--y",
            str(y),
            "--activate",
            "--activation-delay-ms",
            "250",
            "--post-delay-ms",
            "150",
            "--hold-ms",
            "90",
            "--button",
            "left",
            "--global-only",
        ]
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=8.0,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(
            "exact-PID dead picker click failed "
            f"for process {process_id} ({completed.returncode}): "
            f"{completed.stdout.strip()}"
        )
    return {
        "method": "exact_pid_stock_window_click",
        "process_id": process_id,
        "relative_x": x,
        "relative_y": y,
        "output": completed.stdout.strip(),
    }


def _integer(values: Mapping[str, str], key: str) -> int:
    raw = values.get(key, "")
    try:
        return int(raw, 0)
    except (TypeError, ValueError):
        try:
            return int(float(raw))
        except (TypeError, ValueError, OverflowError):
            return -1


def _number(values: Mapping[str, str], key: str) -> float:
    try:
        value = float(values.get(key, "nan"))
    except (TypeError, ValueError):
        return math.nan
    return value if math.isfinite(value) else math.nan


def _distance(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> float:
    return math.hypot(x2 - x1, y2 - y1)


def _spawn_from_state(
    values: Mapping[str, str],
    *,
    label: str,
) -> dict[str, Any]:
    spawn_x = _number(values, "player_spawn_x")
    spawn_y = _number(values, "player_spawn_y")
    spawn_facing = _number(values, "player_spawn_facing")
    arena_address = _integer(values, "arena_address")
    if (
        values.get("player_spawn_valid") != "true"
        or not math.isfinite(spawn_x)
        or not math.isfinite(spawn_y)
        or not math.isfinite(spawn_facing)
        or arena_address == 0
    ):
        raise VerifyFailure(
            f"{label} did not expose the live Arena player spawn: "
            f"{dict(values)}"
        )
    return {
        "arena_address": arena_address,
        "x": spawn_x,
        "y": spawn_y,
        "facing": spawn_facing,
    }


def _assert_spawn_parity(
    client_values: Mapping[str, str],
    host_values: Mapping[str, str],
) -> dict[str, Any]:
    client = _spawn_from_state(client_values, label="client")
    host = _spawn_from_state(host_values, label="host")
    if (
        abs(client["x"] - host["x"]) > POSITION_TOLERANCE
        or abs(client["y"] - host["y"]) > POSITION_TOLERANCE
        or abs(client["facing"] - host["facing"])
        > POSITION_TOLERANCE
    ):
        raise VerifyFailure(
            "host and client Arena player-spawn state diverged: "
            f"host={host} client={client}"
        )
    return {"host": host, "client": client}


def _wait_for_far_client_position(
    *,
    host_pipe: str,
    client_pipe: str,
    expected_x: float,
    expected_y: float,
    spawn_x: float,
    spawn_y: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + 10.0
    stable_since: float | None = None
    last_client: dict[str, str] = {}
    last_host: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_client = death.query_spectator_state(client_pipe)
        last_host = death.query_remote_death_state(
            host_pipe,
            CLIENT_ID,
        )
        client_x = _number(last_client, "x")
        client_y = _number(last_client, "y")
        host_x = _number(last_host, "x")
        host_y = _number(last_host, "y")
        converged = (
            last_host.get("materialized") == "true"
            and _distance(
                client_x,
                client_y,
                expected_x,
                expected_y,
            )
            <= REMOTE_POSITION_TOLERANCE
            and _distance(
                host_x,
                host_y,
                expected_x,
                expected_y,
            )
            <= REMOTE_POSITION_TOLERANCE
            and _distance(
                client_x,
                client_y,
                spawn_x,
                spawn_y,
            )
            >= FAR_FROM_SPAWN_MINIMUM
        )
        if converged:
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= 0.5:
                return {
                    "expected": {
                        "x": expected_x,
                        "y": expected_y,
                    },
                    "client": last_client,
                    "host": last_host,
                    "distance_from_spawn": _distance(
                        client_x,
                        client_y,
                        spawn_x,
                        spawn_y,
                    ),
                }
        else:
            stable_since = None
        time.sleep(0.1)
    raise VerifyFailure(
        "client did not settle far from the Arena spawn on both peers: "
        f"expected=({expected_x},{expected_y}) "
        f"client={last_client} host={last_host}"
    )


def _place_client_far_from_spawn(
    *,
    host_pipe: str,
    client_pipe: str,
) -> dict[str, Any]:
    client_before = death.query_spectator_state(client_pipe)
    host_before = death.query_remote_death_state(
        host_pipe,
        CLIENT_ID,
    )
    spawn = _assert_spawn_parity(client_before, host_before)
    spawn_x = float(spawn["host"]["x"])
    spawn_y = float(spawn["host"]["y"])
    candidates: list[tuple[float, float]] = []
    for dx, dy in (
        (520.0, 360.0),
        (-520.0, 360.0),
        (520.0, -360.0),
        (-520.0, -360.0),
    ):
        try:
            candidates.append(
                snap_to_nav(
                    client_pipe,
                    spawn_x + dx,
                    spawn_y + dy,
                )
            )
        except VerifyFailure:
            continue
    if not candidates:
        raise VerifyFailure(
            "could not resolve a traversable Boneyard position away "
            "from the Arena spawn"
        )
    target_x, target_y = max(
        candidates,
        key=lambda position: _distance(
            position[0],
            position[1],
            spawn_x,
            spawn_y,
        ),
    )
    if (
        _distance(target_x, target_y, spawn_x, spawn_y)
        < FAR_FROM_SPAWN_MINIMUM
    ):
        raise VerifyFailure(
            "the Boneyard nav grid did not provide a sufficiently "
            f"distant death position: spawn={spawn['host']} "
            f"candidates={candidates}"
        )
    placement = place_player(
        client_pipe,
        target_x,
        target_y,
        135.0,
    )
    if placement.get("rebind") != "true":
        raise VerifyFailure(
            "far-from-spawn placement did not rebind the client actor: "
            f"{placement}"
        )
    convergence = _wait_for_far_client_position(
        host_pipe=host_pipe,
        client_pipe=client_pipe,
        expected_x=target_x,
        expected_y=target_y,
        spawn_x=spawn_x,
        spawn_y=spawn_y,
    )
    return {
        "spawn": spawn,
        "placement": placement,
        "convergence": convergence,
    }


def _respawn_actor_matches(
    values: Mapping[str, str],
    *,
    spawn_x: float,
    spawn_y: float,
    remote: bool,
) -> bool:
    position_tolerance = (
        REMOTE_POSITION_TOLERANCE
        if remote
        else POSITION_TOLERANCE
    )
    return (
        values.get("materialized") == "true"
        and _integer(values, "actor_address") != 0
        and _integer(values, "grid_cell_address") != 0
        and _integer(values, "grid_member_flag") == 1
        and abs(_number(values, "render_sort_bias"))
        <= 0.0001
        and _integer(values, "death_drive_state") == 0
        and (
            remote
            or _integer(values, "death_presentation_ticks") == 0
        )
        and (
            not remote
            or _integer(
                values,
                "authoritative_death_presentation_ticks",
            )
            == 0
        )
        and _integer(values, "terminal_pending") == 0
        and values.get("presentation_active") == "false"
        and values.get("red_effect_active") == "false"
        and _distance(
            _number(values, "x"),
            _number(values, "y"),
            spawn_x,
            spawn_y,
        )
        <= position_tolerance
    )


def _wait_for_respawn_peer_views(
    *,
    host_pipe: str,
    client_pipe: str,
    spawn_x: float,
    spawn_y: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + 10.0
    last_client: dict[str, str] = {}
    last_host: dict[str, str] = {}
    while time.monotonic() < deadline:
        observed_ns = time.monotonic_ns()
        last_client = death.query_spectator_state(client_pipe)
        last_host = death.query_remote_death_state(
            host_pipe,
            CLIENT_ID,
        )
        replicated_x = _number(last_host, "participant_x")
        replicated_y = _number(last_host, "participant_y")
        if (
            _respawn_actor_matches(
                last_client,
                spawn_x=spawn_x,
                spawn_y=spawn_y,
                remote=False,
            )
            and _respawn_actor_matches(
                last_host,
                spawn_x=spawn_x,
                spawn_y=spawn_y,
                remote=True,
            )
            and _distance(
                replicated_x,
                replicated_y,
                spawn_x,
                spawn_y,
            )
            <= REMOTE_POSITION_TOLERANCE
        ):
            return {
                "observed_monotonic_ns": observed_ns,
                "client_owner": last_client,
                "host_observer": last_host,
            }
        time.sleep(0.05)
    raise VerifyFailure(
        "respawned client actor did not converge at the Arena spawn "
        f"on owner and host views: client={last_client} "
        f"host={last_host}"
    )


def _assert_respawn_spawn_and_corpse_retired(
    *,
    views: Mapping[str, Any],
    death_location: Mapping[str, float],
    before_corpse_views: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    client = views["client_owner"]
    host = views["host_observer"]
    spawn = _assert_spawn_parity(client, host)
    spawn_x = float(spawn["host"]["x"])
    spawn_y = float(spawn["host"]["y"])
    death_x = float(death_location["x"])
    death_y = float(death_location["y"])
    if (
        _distance(death_x, death_y, spawn_x, spawn_y)
        < FAR_FROM_SPAWN_MINIMUM
    ):
        raise VerifyFailure(
            "death did not occur far enough from the Arena spawn: "
            f"death={death_location} spawn={spawn}"
        )
    if (
        abs(_number(client, "last_respawn_x") - spawn_x)
        > POSITION_TOLERANCE
        or abs(_number(client, "last_respawn_y") - spawn_y)
        > POSITION_TOLERANCE
    ):
        raise VerifyFailure(
            "accepted respawn command did not carry the Arena spawn: "
            f"client={client} spawn={spawn}"
        )
    for label, values, remote in (
        ("client_owner", client, False),
        ("host_observer", host, True),
    ):
        if not _respawn_actor_matches(
            values,
            spawn_x=spawn_x,
            spawn_y=spawn_y,
            remote=remote,
        ):
            raise VerifyFailure(
                f"{label} retained a corpse/death presentation after "
                f"respawn: {dict(values)}"
            )
    client_old_cell = _integer(
        before_corpse_views["client_owner"],
        "grid_cell_address",
    )
    client_new_cell = _integer(client, "grid_cell_address")
    if client_old_cell != 0 and client_old_cell == client_new_cell:
        raise VerifyFailure(
            "the owner actor remained in its death-location world cell "
            f"after respawn: cell={client_old_cell}"
        )
    host_old_cell = _integer(
        before_corpse_views["host_observer"],
        "grid_cell_address",
    )
    host_new_cell = _integer(host, "grid_cell_address")
    if host_old_cell != 0 and host_old_cell == host_new_cell:
        raise VerifyFailure(
            "the host view retained the remote actor in its "
            f"death-location world cell: cell={host_old_cell}"
        )
    return {
        "spawn": spawn,
        "death_location": {
            "x": death_x,
            "y": death_y,
        },
        "client_old_grid_cell": client_old_cell,
        "client_spawn_grid_cell": client_new_cell,
        "host_old_grid_cell": host_old_cell,
        "host_spawn_grid_cell": host_new_cell,
        "client_corpse_present": False,
        "host_corpse_present": False,
        "client_exact_spawn_delta": {
            "x": _number(client, "x") - spawn_x,
            "y": _number(client, "y") - spawn_y,
        },
        "host_exact_spawn_delta": {
            "x": _number(host, "x") - spawn_x,
            "y": _number(host, "y") - spawn_y,
        },
    }


def _capture_focused_location(
    pipe_name: str,
    *,
    world_x: float,
    world_y: float,
    output_path: Path,
) -> dict[str, Any]:
    focus = parse_key_values(
        lua(
            pipe_name,
            (
                "local ok=sd.camera.set_focus("
                f"{world_x:.9f},{world_y:.9f}); "
                "local c=sd.camera.get_state(); "
                "print('ok='..tostring(ok)); "
                "print('focus_active='..tostring(c.focus_active)); "
                "print('owns_focus='..tostring(c.owns_focus)); "
                "print('focus_x='..tostring(c.focus_x or 0)); "
                "print('focus_y='..tostring(c.focus_y or 0)); "
                "print('center_x='..tostring(c.center_x)); "
                "print('center_y='..tostring(c.center_y))"
            ),
            timeout=8.0,
        )
    )
    if (
        focus.get("ok") != "true"
        or focus.get("focus_active") != "true"
        or focus.get("owns_focus") != "true"
    ):
        raise VerifyFailure(
            f"could not focus {pipe_name} for screenshot: {focus}"
        )
    try:
        time.sleep(0.25)
        screenshot = capture_game_backbuffer(
            pipe_name,
            output_path,
            maximum_dominant_fraction=0.95,
        )
    finally:
        cleared = parse_key_values(
            lua(
                pipe_name,
                "print('cleared='..tostring("
                "sd.camera.clear_focus()))",
                timeout=8.0,
            )
        )
    return {
        "focus": focus,
        "screenshot": screenshot,
        "clear": cleared,
    }


def _capture_respawn_locations(
    *,
    host_pipe: str,
    client_pipe: str,
    screenshot_directory: Path,
    scenario_label: str,
    death_location: Mapping[str, float],
    spawn: Mapping[str, Any],
    client_spawn_filename: str,
) -> dict[str, Any]:
    spawn_x = float(spawn["host"]["x"])
    spawn_y = float(spawn["host"]["y"])
    death_x = float(death_location["x"])
    death_y = float(death_location["y"])
    return {
        "death_location": {
            "client": _capture_focused_location(
                client_pipe,
                world_x=death_x,
                world_y=death_y,
                output_path=screenshot_directory
                / f"client-{scenario_label}-death-location-cleared.png",
            ),
            "host": _capture_focused_location(
                host_pipe,
                world_x=death_x,
                world_y=death_y,
                output_path=screenshot_directory
                / f"host-{scenario_label}-death-location-cleared.png",
            ),
        },
        "spawn": {
            "client": _capture_focused_location(
                client_pipe,
                world_x=spawn_x,
                world_y=spawn_y,
                output_path=screenshot_directory
                / client_spawn_filename,
            ),
            "host": _capture_focused_location(
                host_pipe,
                world_x=spawn_x,
                world_y=spawn_y,
                output_path=screenshot_directory
                / f"host-{scenario_label}-spawn.png",
            ),
        },
    }


def _local_owned_participant(
    values: dict[str, str],
) -> dict[str, Any]:
    participant = inventory.find_participant(values, CLIENT_ID)
    if participant is not None:
        return participant
    local_rows = [
        row
        for row in inventory.participant_rows(values)
        if row["kind"].lower() in {"localhuman", "local_human"}
    ]
    if len(local_rows) != 1:
        raise VerifyFailure(
            "could not identify the client-owned participant snapshot: "
            f"{inventory.participant_rows(values)}"
        )
    return local_rows[0]


def _authority_owned_client(
    values: dict[str, str],
) -> dict[str, Any]:
    participant = inventory.find_participant(values, CLIENT_ID)
    if participant is None:
        raise VerifyFailure(
            "host did not expose the client-owned progression snapshot: "
            f"{inventory.participant_rows(values)}"
        )
    return participant


def _owned_projection(participant: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "gold",
        "gold_revision",
        "inventory_revision",
        "equipment_revision",
        "spellbook_revision",
        "statbook_revision",
        "loadout_revision",
        "inventory_host_authoritative",
        "has_inventory_items",
        "inventory_item_count",
        "inventory_item_total_count",
        "inventory_truncated",
        "inventory_items",
        "equipment",
        "progression_book_entry_count",
        "progression_book_entry_total_count",
        "progression_book_truncated",
        "statbook_entry_count",
        "statbook_entries",
        "skillbook_entry_count",
        "skillbook_entry_total_count",
        "skillbook_truncated",
        "spellbook_entry_count",
        "spellbook_entry_total_count",
        "spellbook_truncated",
        "has_skillbook_entries",
        "has_spellbook_entries",
        "has_statbook_entries",
        "has_ability_loadout",
        "ability_loadout",
    )
    return {
        key: copy.deepcopy(participant[key])
        for key in keys
    }


def progression_respawn_projection(
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Remove only current resources, which wave respawn intentionally refills."""

    projected = copy.deepcopy(dict(snapshot))
    runtime = projected.get("runtime")
    if isinstance(runtime, dict):
        runtime.pop("life_current", None)
        runtime.pop("mana_current", None)
    native = projected.get("native")
    if isinstance(native, dict):
        native.pop("hp", None)
        native.pop("mp", None)
    raw = projected.get("raw")
    if isinstance(raw, dict):
        for key in (
            "runtime.life_current",
            "runtime.mana_current",
            "native.hp",
            "native.mp",
        ):
            raw.pop(key, None)
    return projected


def capture_local_actor_state(pipe_name: str) -> dict[str, Any]:
    spectator = death.query_spectator_state(pipe_name)
    raw_inventory = inventory.capture(pipe_name)
    participant = _local_owned_participant(raw_inventory)
    return {
        "actor_address": _integer(spectator, "actor_address"),
        "progression": query_progression_snapshot(pipe_name),
        "items": inventory.item_rows(raw_inventory),
        "book": inventory.book_rows(raw_inventory),
        "owned": _owned_projection(participant),
        "visuals": {
            lane: {
                field: parse_int_text(
                    raw_inventory.get(f"visual.{lane}.{field}"),
                    0,
                )
                for field in ("type_id", "recipe_uid", "object")
            }
            for lane in ("primary", "secondary", "attachment")
        },
        "death": spectator,
    }


def capture_host_authority_client_state(
    host_pipe: str,
) -> dict[str, Any]:
    raw_inventory = inventory.capture(host_pipe)
    remote = death.query_remote_death_state(host_pipe, CLIENT_ID)
    return {
        "actor_address": _integer(remote, "actor_address"),
        "progression": query_progression_snapshot(
            host_pipe,
            participant_id=CLIENT_ID,
        ),
        "owned": _owned_projection(
            _authority_owned_client(raw_inventory)
        ),
        "death": remote,
    }


def _staff_state(state: Mapping[str, Any]) -> dict[str, Any]:
    items = state["items"]
    owned = state["owned"]
    equipment = owned["equipment"]
    return {
        "inventory_rows": [
            copy.deepcopy(row)
            for row in items
            if row["type_id"] == STAFF_TYPE_ID
        ],
        "owned_weapon": copy.deepcopy(
            equipment.get("weapon", {})
        ),
        "equipment_attachment_view": copy.deepcopy(
            equipment.get("attachment", {})
        ),
        "attachment_visual": copy.deepcopy(
            state["visuals"]["attachment"]
        ),
    }


def assert_same_actor_loadout_after_respawn(
    dead_after_choice: Mapping[str, Any],
    after_respawn: Mapping[str, Any],
) -> dict[str, Any]:
    actor_address = int(dead_after_choice["actor_address"])
    progression_address = int(
        dead_after_choice["progression"]["progression"]
    )
    if (
        actor_address == 0
        or actor_address != int(after_respawn["actor_address"])
        or progression_address == 0
        or progression_address
        != int(after_respawn["progression"]["progression"])
    ):
        raise VerifyFailure(
            "wave respawn replaced the client actor/progression: "
            f"dead_actor={actor_address} "
            f"respawn_actor={after_respawn['actor_address']} "
            f"dead_progression={progression_address} "
            f"respawn_progression="
            f"{after_respawn['progression']['progression']}"
        )

    comparisons = {
        "progression": (
            progression_respawn_projection(
                dead_after_choice["progression"]
            ),
            progression_respawn_projection(
                after_respawn["progression"]
            ),
        ),
        "items": (
            dead_after_choice["items"],
            after_respawn["items"],
        ),
        "book": (
            dead_after_choice["book"],
            after_respawn["book"],
        ),
        "owned": (
            dead_after_choice["owned"],
            after_respawn["owned"],
        ),
    }
    mismatches = {
        key: {"dead_after_choice": before, "after_respawn": after}
        for key, (before, after) in comparisons.items()
        if before != after
    }
    if mismatches:
        raise VerifyFailure(
            "same-actor progression/loadout changed across respawn: "
            + json.dumps(mismatches, sort_keys=True)
        )

    return {
        "actor_address": actor_address,
        "progression_address": progression_address,
        "items_exact": True,
        "book_exact": True,
        "owned_progression_exact": True,
    }


def assert_staff_preserved_without_duplication(
    before_death: Mapping[str, Any],
    after_respawn: Mapping[str, Any],
) -> dict[str, Any]:
    before = _staff_state(before_death)
    after = _staff_state(after_respawn)
    before_semantic = copy.deepcopy(before)
    after_semantic = copy.deepcopy(after)
    before_semantic["attachment_visual"].pop("object", None)
    after_semantic["attachment_visual"].pop("object", None)
    if before_semantic != after_semantic:
        raise VerifyFailure(
            "equipped staff changed or duplicated across death/respawn: "
            f"before={before_semantic} after={after_semantic}"
        )
    if (
        after["attachment_visual"]["type_id"] != STAFF_TYPE_ID
        or after["owned_weapon"].get("type_id") != STAFF_TYPE_ID
    ):
        raise VerifyFailure(
            "respawn did not restore the retained equipped staff: "
            f"{after}"
        )
    attachment_view = after["equipment_attachment_view"]
    if (
        attachment_view
        and (
            attachment_view.get("type_id")
            != after["owned_weapon"].get("type_id")
            or attachment_view.get("recipe_uid")
            != after["owned_weapon"].get("recipe_uid")
        )
    ):
        raise VerifyFailure(
            "staff attachment view diverged from the owned weapon: "
            f"{after}"
        )
    return {
        "before": before,
        "after": after,
        "inventory_staff_row_count": len(
            after["inventory_rows"]
        ),
        "inventory_staff_row_delta": (
            len(after["inventory_rows"])
            - len(before["inventory_rows"])
        ),
        "owned_weapon_type_id": after["owned_weapon"]["type_id"],
        "attachment_view_matches_owned_weapon": True,
    }


def assert_immediate_respawn_sample(
    values: Mapping[str, str],
    *,
    epoch: int,
    wave: int,
    spawn_x: float,
    spawn_y: float,
) -> None:
    if (
        values.get("active") != "false"
        or values.get("phase") != "Inactive"
        or _integer(values, "death_started_ms") != 0
        or _integer(values, "presentation_remaining_ms") != 0
        or _integer(values, "last_applied_respawn_epoch") != epoch
        or _integer(values, "last_applied_respawn_wave") != wave
        or _integer(values, "anim_drive_state") != 0
        or _integer(values, "death_drive_state") != 0
        or _integer(values, "death_presentation_ticks") != 0
        or _integer(values, "terminal_pending") != 0
        or _integer(values, "grid_cell_address") == 0
        or _integer(values, "grid_member_flag") != 1
        or abs(_number(values, "render_sort_bias")) > 0.0001
        or values.get("presentation_active") != "false"
        or values.get("red_effect_active") != "false"
        or _integer(values, "death_transition_hits") != 1
        or _integer(values, "staff_drop_hits") != 1
        or _distance(
            _number(values, "x"),
            _number(values, "y"),
            spawn_x,
            spawn_y,
        )
        > POSITION_TOLERANCE
    ):
        raise VerifyFailure(
            "wave respawn did not atomically retire the death epoch: "
            f"{dict(values)}"
        )
    hp = _number(values, "hp")
    max_hp = _number(values, "max_hp")
    mp = _number(values, "mp")
    max_mp = _number(values, "max_mp")
    if (
        not math.isfinite(hp)
        or not math.isfinite(max_hp)
        or abs(hp - max_hp) > VITAL_TOLERANCE
        or not math.isfinite(mp)
        or not math.isfinite(max_mp)
        or abs(mp - max_mp) > VITAL_TOLERANCE
    ):
        raise VerifyFailure(
            "wave respawn resources did not remain restored: "
            f"{dict(values)}"
        )


def _configure_level_up_pipes(
    host_pipe: str,
    client_pipe: str,
) -> None:
    level_up.HOST_PIPE = host_pipe
    level_up.CLIENT_PIPE = client_pipe


def _launch_scenario(
    *,
    instance_prefix: str,
    ports: tuple[int, int],
    game_directory: Path | None,
) -> tuple[dict[str, object], str, str, list[int]]:
    launch = launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset="map_create_water_body_hub",
        temporary_host_profile=True,
        god_mode=False,
        tile_windows=False,
        test_wave_override=WAVE_FIXTURE,
        kill_existing=False,
        instance_prefix=instance_prefix,
        host_port=ports[0],
        client_port=ports[1],
        game_directory=game_directory,
        exact_mod_id=ACCEPTANCE_MOD_ID,
    )
    process_ids = game_process_ids(launch)
    if len(process_ids) != 2:
        stop_game_processes(process_ids)
        raise VerifyFailure(
            "isolated pair did not report exactly two process IDs: "
            f"{launch}"
        )
    host_pipe = str(launch["hostLuaPipe"])
    client_pipe = str(launch["clientLuaPipe"])
    _configure_level_up_pipes(host_pipe, client_pipe)
    return launch, host_pipe, client_pipe, process_ids


def _prepare_run(
    host_pipe: str,
    client_pipe: str,
) -> dict[str, Any]:
    pipes = [host_pipe, client_pipe]
    bots_disabled = death._disable_bots(pipes)
    death._start_testrun_when_ready(host_pipe)
    for pipe_name in pipes:
        wait_for_scene(pipe_name, "testrun", 45.0)
    relationships = {
        "host_observes_client": wait_for_remote(
            host_pipe,
            CLIENT_ID,
            CLIENT_NAME,
            "testrun",
            45.0,
        ),
        "client_observes_host": wait_for_remote(
            client_pipe,
            HOST_ID,
            HOST_NAME,
            "testrun",
            45.0,
        ),
    }
    return {
        "bots_disabled": bots_disabled,
        "relationships": relationships,
        "death_traces_armed": death._arm_death_traces(pipes),
    }


def _wait_for_client_staff(client_pipe: str) -> dict[str, str]:
    return death._wait_for_values(
        client_pipe,
        lambda values: _integer(
            values,
            "attachment_type_id",
        )
        == STAFF_TYPE_ID,
        timeout=8.0,
        description="client equipped staff",
    )


def _wait_for_client_spectator(
    client_pipe: str,
) -> dict[str, str]:
    return death._wait_for_values(
        client_pipe,
        death.spectator_state_matches,
        timeout=6.0,
        description="client spectator phase",
    )


def _wait_for_respawn(
    client_pipe: str,
    *,
    previous_epoch: int,
    wave: int,
) -> dict[str, str]:
    return death._wait_for_values(
        client_pipe,
        lambda values: death.respawn_state_matches(
            values,
            previous_epoch=previous_epoch,
            expected_wave=wave,
        ),
        timeout=8.0,
        description=f"client wave-{wave} respawn",
    )


def _start_and_complete_wave(
    host_pipe: str,
) -> tuple[dict[str, str], list[dict[str, str]], dict[str, str]]:
    started = parse_key_values(
        lua(
            host_pipe,
            "print('ok=' .. tostring(sd.gameplay.start_waves()))",
        )
    )
    if started.get("ok") != "true":
        raise VerifyFailure(f"host could not start waves: {started}")
    active = death._wait_for_wave(
        host_pipe,
        lambda values: int(values.get("alive", "0")) > 0,
        timeout=15.0,
        description="live host-authored wave",
    )
    triggers = death._trigger_all_live_wave_enemy_deaths(
        host_pipe
    )
    completed = death._wait_for_wave(
        host_pipe,
        lambda values: values.get("phase") == "completed"
        and int(values.get("wave", "0")) > 0,
        timeout=8.0,
        description="host-authored wave completion",
    )
    return active, triggers, completed


def _assert_normal_control(
    client_pipe: str,
) -> dict[str, Any]:
    before = death.query_spectator_state(client_pipe)
    moved = nudge_player(client_pipe, 31.0, -17.0, 135.0)
    after = death.query_spectator_state(client_pipe)
    dx = _number(after, "x") - _number(before, "x")
    dy = _number(after, "y") - _number(before, "y")
    if (
        not math.isfinite(dx)
        or not math.isfinite(dy)
        or abs(dx - 31.0) > POSITION_TOLERANCE
        or abs(dy + 17.0) > POSITION_TOLERANCE
        or _integer(after, "anim_drive_state") != 0
    ):
        raise VerifyFailure(
            "client control did not resume after wave respawn: "
            f"before={before} moved={moved} after={after}"
        )
    return {
        "before": before,
        "nudge": moved,
        "after": after,
        "delta_x": dx,
        "delta_y": dy,
    }


def _wait_for_authoritative_choice(
    *,
    host_pipe: str,
    client_pipe: str,
    offer_id: int,
    level: int,
    option_id: int,
    expected_active: int,
) -> dict[str, Any]:
    result = level_up.wait_for_choice_result(
        offer_id,
        level,
        12.0,
        target_participant_id=CLIENT_ID,
    )
    client_entry = level_up.wait_for_progression_entry_active(
        client_pipe,
        option_id=option_id,
        expected_active=expected_active,
        timeout=8.0,
    )
    host_entry = level_up.wait_for_progression_entry_active(
        host_pipe,
        option_id=option_id,
        expected_active=expected_active,
        timeout=8.0,
        participant_id=CLIENT_ID,
    )
    return {
        "result": result,
        "client_native_entry": client_entry,
        "host_authority_native_entry": host_entry,
    }


def run_dead_progression_scenario(
    *,
    instance_prefix: str,
    ports: tuple[int, int],
    game_directory: Path | None,
) -> dict[str, Any]:
    launch, host_pipe, client_pipe, process_ids = _launch_scenario(
        instance_prefix=instance_prefix,
        ports=ports,
        game_directory=game_directory,
    )
    pipes = [host_pipe, client_pipe]
    result: dict[str, Any] = {
        "launch": launch,
        "process_ids": process_ids,
        "ports": list(ports),
    }
    try:
        result["setup"] = _prepare_run(host_pipe, client_pipe)
        result["staff_ready"] = _wait_for_client_staff(
            client_pipe
        )
        result["far_from_spawn"] = _place_client_far_from_spawn(
            host_pipe=host_pipe,
            client_pipe=client_pipe,
        )
        before_death = capture_local_actor_state(client_pipe)
        result["before_death"] = before_death
        result["host_authority_before_death"] = (
            capture_host_authority_client_state(host_pipe)
        )

        result["lethal_precondition"] = (
            death._establish_local_lethal_precondition(
                client_pipe,
                "client",
            )
        )
        result["lethal_hit"] = (
            death._apply_authoritative_client_lethal_hit(
                host_pipe
            )
        )
        result["death_presentation"] = death._wait_for_values(
            client_pipe,
            death.death_presentation_state_matches,
            timeout=5.0,
            description="client death presentation",
        )
        death_location = {
            "x": _number(result["death_presentation"], "x"),
            "y": _number(result["death_presentation"], "y"),
        }
        spectating = _wait_for_client_spectator(client_pipe)
        result["spectating"] = spectating
        corpse_views = {
            "client_owner": spectating,
            "host_observer": death.query_remote_death_state(
                host_pipe,
                CLIENT_ID,
            ),
        }
        if (
            _integer(spectating, "grid_member_flag") != 0
            or abs(_number(spectating, "render_sort_bias") + 1000.0)
            > 0.001
            or _integer(spectating, "grid_cell_address") == 0
        ):
            raise VerifyFailure(
                "grace death did not reach the native tick-159 corpse "
                f"state before respawn: {spectating}"
            )
        result["corpse_before_respawn"] = corpse_views

        dead_progression_before = query_progression_snapshot(
            client_pipe
        )
        native_before = dead_progression_before["native"]
        target_level = int(native_before["level"]) + 1
        target_experience = max(
            int(math.ceil(native_before["next_xp_threshold"])),
            int(math.ceil(native_before["xp"])) + 1,
        )
        result["threshold"] = {
            "before_level": native_before["level"],
            "before_xp": native_before["xp"],
            "next_xp_threshold": native_before[
                "next_xp_threshold"
            ],
            "target_level": target_level,
            "target_experience": target_experience,
        }
        result["offer_published"] = level_up.publish_offer(
            target_level,
            target_experience,
        )
        offer = level_up.wait_for_client_offer(
            target_level,
            15.0,
        )
        result["dead_spectator_offer"] = offer
        during_offer = death.query_spectator_state(client_pipe)
        if (
            not death.spectator_state_matches(during_offer)
            or _integer(during_offer, "target_participant_id")
            != _integer(spectating, "target_participant_id")
        ):
            raise VerifyFailure(
                "native picker displaced or cycled the spectator view: "
                f"before={spectating} during={during_offer}"
            )
        result["spectator_during_offer"] = during_offer
        screenshot_directory = SCREENSHOT_ROOT / instance_prefix
        result["picker_screenshot"] = capture_game_backbuffer(
            client_pipe,
            screenshot_directory
            / "client-dead-spectator-level-up-picker.png",
        )

        selected_option_id = int(offer["first_option_id"])
        selected_entry_before = level_up.query_progression_entry(
            client_pipe,
            option_id=selected_option_id,
        )
        expected_active = (
            int(selected_entry_before["active"])
            + int(
                offer["raw"].get(
                    "offer.option.1.apply_count",
                    "1",
                )
            )
        )
        result["selection_submitted"] = _click_owned_window(
            int(launch["clientProcessId"]),
            FIRST_PICKER_OPTION_X,
            PICKER_OPTION_Y,
        )
        result["authoritative_choice"] = (
            _wait_for_authoritative_choice(
                host_pipe=host_pipe,
                client_pipe=client_pipe,
                offer_id=int(offer["offer_id"]),
                level=target_level,
                option_id=selected_option_id,
                expected_active=expected_active,
            )
        )

        after_choice_dead = capture_local_actor_state(
            client_pipe
        )
        host_after_choice = capture_host_authority_client_state(
            host_pipe
        )
        if (
            after_choice_dead["death"].get("phase")
            != "Spectating"
            or _number(
                after_choice_dead["death"],
                "hp",
            )
            > VITAL_TOLERANCE
            or int(
                after_choice_dead["progression"]["native"][
                    "entries"
                ][selected_option_id]["active"]
            )
            != expected_active
            or int(
                host_after_choice["progression"]["native"][
                    "entries"
                ][selected_option_id]["active"]
            )
            != expected_active
        ):
            raise VerifyFailure(
                "dead-time choice did not remain actor-specific and "
                "authoritative: "
                f"client={after_choice_dead} "
                f"host={host_after_choice}"
            )
        result["after_choice_while_dead"] = after_choice_dead
        result["host_authority_after_choice"] = host_after_choice

        previous_epoch = _integer(
            after_choice_dead["death"],
            "last_applied_respawn_epoch",
        )
        active_wave, triggers, completed = (
            _start_and_complete_wave(host_pipe)
        )
        wave = int(completed["wave"])
        result["wave"] = {
            "active": active_wave,
            "death_triggers": triggers,
            "completed": completed,
        }
        result["respawn"] = _wait_for_respawn(
            client_pipe,
            previous_epoch=previous_epoch,
            wave=wave,
        )
        spawn = result["far_from_spawn"]["spawn"]
        peer_views = _wait_for_respawn_peer_views(
            host_pipe=host_pipe,
            client_pipe=client_pipe,
            spawn_x=float(spawn["host"]["x"]),
            spawn_y=float(spawn["host"]["y"]),
        )
        result["respawn_tick_peer_views"] = peer_views
        result["spawn_and_corpse_retirement"] = (
            _assert_respawn_spawn_and_corpse_retired(
                views=peer_views,
                death_location=death_location,
                before_corpse_views=corpse_views,
            )
        )
        result["location_screenshots"] = (
            _capture_respawn_locations(
                host_pipe=host_pipe,
                client_pipe=client_pipe,
                screenshot_directory=screenshot_directory,
                scenario_label="grace-respawn",
                death_location=death_location,
                spawn=spawn,
                client_spawn_filename=(
                    "client-respawn-with-dead-time-skill.png"
                ),
            )
        )
        result["respawn_screenshot"] = result[
            "location_screenshots"
        ]["spawn"]["client"]["screenshot"]
        after_respawn = capture_local_actor_state(client_pipe)
        result["after_respawn"] = after_respawn
        result["host_authority_after_respawn"] = (
            capture_host_authority_client_state(host_pipe)
        )
        result["same_actor_loadout_parity"] = (
            assert_same_actor_loadout_after_respawn(
                after_choice_dead,
                after_respawn,
            )
        )
        result["staff_preservation"] = (
            assert_staff_preserved_without_duplication(
                before_death,
                after_respawn,
            )
        )
        trace_states = {
            "client": death.query_spectator_state(client_pipe),
            "host": death.query_remote_death_state(
                host_pipe,
                CLIENT_ID,
            ),
        }
        if not death.staff_drop_once_matches(
            trace_states,
            owner_label="client",
        ):
            raise VerifyFailure(
                "client staff drop did not remain one allocation for "
                f"the death epoch: {trace_states}"
            )
        result["staff_drop_once"] = trace_states
        result["normal_control"] = _assert_normal_control(
            client_pipe
        )
        result["selected_option"] = {
            "option_id": selected_option_id,
            "before_active": selected_entry_before["active"],
            "expected_active": expected_active,
            "persisted_active": after_respawn["progression"][
                "native"
            ]["entries"][selected_option_id]["active"],
        }
        result["ok"] = True
        return result
    finally:
        death._disarm_death_traces(pipes)
        stop_game_processes(process_ids)


def run_immediate_round_scenario(
    *,
    instance_prefix: str,
    ports: tuple[int, int],
    game_directory: Path | None,
) -> dict[str, Any]:
    launch, host_pipe, client_pipe, process_ids = _launch_scenario(
        instance_prefix=instance_prefix,
        ports=ports,
        game_directory=game_directory,
    )
    pipes = [host_pipe, client_pipe]
    result: dict[str, Any] = {
        "launch": launch,
        "process_ids": process_ids,
        "ports": list(ports),
    }
    try:
        result["setup"] = _prepare_run(host_pipe, client_pipe)
        result["staff_ready"] = _wait_for_client_staff(
            client_pipe
        )
        result["far_from_spawn"] = _place_client_far_from_spawn(
            host_pipe=host_pipe,
            client_pipe=client_pipe,
        )
        before_death = capture_local_actor_state(client_pipe)
        result["before_death"] = before_death

        started = parse_key_values(
            lua(
                host_pipe,
                "print('ok=' .. tostring(sd.gameplay.start_waves()))",
            )
        )
        if started.get("ok") != "true":
            raise VerifyFailure(
                f"host could not start immediate-round wave: {started}"
            )
        active = death._wait_for_wave(
            host_pipe,
            lambda values: int(values.get("alive", "0")) > 0,
            timeout=15.0,
            description="immediate-round live wave",
        )
        result["wave_active"] = active

        result["lethal_precondition"] = (
            death._establish_local_lethal_precondition(
                client_pipe,
                "client",
            )
        )
        death_started_at = time.monotonic()
        result["lethal_hit"] = (
            death._apply_authoritative_client_lethal_hit(
                host_pipe
            )
        )
        result["death_presentation"] = death._wait_for_values(
            client_pipe,
            death.death_presentation_state_matches,
            timeout=5.0,
            description="immediate-round death presentation",
        )
        death_location = {
            "x": _number(result["death_presentation"], "x"),
            "y": _number(result["death_presentation"], "y"),
        }
        corpse_views = {
            "client_owner": result["death_presentation"],
            "host_observer": death.query_remote_death_state(
                host_pipe,
                CLIENT_ID,
            ),
        }
        result["death_presentation_peer_views"] = corpse_views
        previous_epoch = _integer(
            result["death_presentation"],
            "last_applied_respawn_epoch",
        )
        result["death_triggers"] = (
            death._trigger_all_live_wave_enemy_deaths(host_pipe)
        )
        completed = death._wait_for_wave(
            host_pipe,
            lambda values: values.get("phase") == "completed"
            and int(values.get("wave", "0")) > 0,
            timeout=8.0,
            description="immediate post-death wave completion",
        )
        completed_after_death_seconds = (
            time.monotonic() - death_started_at
        )
        if completed_after_death_seconds >= 3.0:
            raise VerifyFailure(
                "wave did not complete inside the native death grace "
                f"window: {completed_after_death_seconds:.3f}s"
            )
        wave = int(completed["wave"])
        result["wave_completed"] = completed
        result["wave_completed_after_death_seconds"] = (
            completed_after_death_seconds
        )
        respawn = _wait_for_respawn(
            client_pipe,
            previous_epoch=previous_epoch,
            wave=wave,
        )
        epoch = _integer(
            respawn,
            "last_applied_respawn_epoch",
        )
        result["respawn"] = respawn
        spawn = result["far_from_spawn"]["spawn"]
        peer_views = _wait_for_respawn_peer_views(
            host_pipe=host_pipe,
            client_pipe=client_pipe,
            spawn_x=float(spawn["host"]["x"]),
            spawn_y=float(spawn["host"]["y"]),
        )
        result["respawn_tick_peer_views"] = peer_views
        result["spawn_and_corpse_retirement"] = (
            _assert_respawn_spawn_and_corpse_retired(
                views=peer_views,
                death_location=death_location,
                before_corpse_views=corpse_views,
            )
        )

        samples: list[dict[str, str]] = []
        stable_until = time.monotonic() + 3.4
        while time.monotonic() < stable_until:
            sample = death.query_spectator_state(client_pipe)
            assert_immediate_respawn_sample(
                sample,
                epoch=epoch,
                wave=wave,
                spawn_x=float(spawn["host"]["x"]),
                spawn_y=float(spawn["host"]["y"]),
            )
            samples.append(sample)
            time.sleep(0.12)
        result["stable_post_respawn_samples"] = samples
        result["stable_post_respawn_sample_count"] = len(samples)

        after_respawn = capture_local_actor_state(client_pipe)
        result["after_respawn"] = after_respawn
        result["same_actor_loadout_parity"] = (
            assert_same_actor_loadout_after_respawn(
                before_death,
                after_respawn,
            )
        )
        result["staff_preservation"] = (
            assert_staff_preserved_without_duplication(
                before_death,
                after_respawn,
            )
        )
        screenshot_directory = SCREENSHOT_ROOT / instance_prefix
        result["location_screenshots"] = (
            _capture_respawn_locations(
                host_pipe=host_pipe,
                client_pipe=client_pipe,
                screenshot_directory=screenshot_directory,
                scenario_label="immediate-round-respawn",
                death_location=death_location,
                spawn=spawn,
                client_spawn_filename=(
                    "client-immediate-round-respawn-clean.png"
                ),
            )
        )
        result["respawn_screenshot"] = result[
            "location_screenshots"
        ]["spawn"]["client"]["screenshot"]
        trace_states = {
            "client": death.query_spectator_state(client_pipe),
            "host": death.query_remote_death_state(
                host_pipe,
                CLIENT_ID,
            ),
        }
        if not death.staff_drop_once_matches(
            trace_states,
            owner_label="client",
        ):
            raise VerifyFailure(
                "immediate-round client staff drop did not remain one "
                f"allocation: {trace_states}"
            )
        result["staff_drop_once"] = trace_states
        result["normal_control"] = _assert_normal_control(
            client_pipe
        )
        result["ok"] = True
        return result
    finally:
        death._disarm_death_traces(pipes)
        stop_game_processes(process_ids)


def _default_instance_prefix() -> str:
    return (
        f"dp-{os.getpid():x}-"
        f"{time.time_ns() & 0xFFFF:04x}"
    )


def _resolve_ports(explicit: list[int] | None) -> list[int]:
    if explicit is None:
        return select_available_windows_udp_ports(4)
    if len(explicit) != 4:
        raise ValueError("exactly four UDP ports are required")
    if (
        len(set(explicit)) != 4
        or any(port < 1 or port > 0xFFFF for port in explicit)
    ):
        raise ValueError(
            "UDP ports must be distinct values between 1 and 65535"
        )
    return explicit


def run_live_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path | None,
) -> dict[str, Any]:
    return {
        "instance_prefix": instance_prefix,
        "ports": ports,
        "dead_progression": run_dead_progression_scenario(
            instance_prefix=instance_prefix + "-p",
            ports=(ports[0], ports[1]),
            game_directory=game_directory,
        ),
        "immediate_round": run_immediate_round_scenario(
            instance_prefix=instance_prefix + "-r",
            ports=(ports[2], ports[3]),
            game_directory=game_directory,
        ),
        "ok": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instance-prefix",
        default="",
        help="Unique isolated launcher prefix (generated by default).",
    )
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=None,
        help="Retail game directory override for isolated worktrees.",
    )
    parser.add_argument(
        "--ports",
        nargs=4,
        type=int,
        default=None,
        metavar=("P1_HOST", "P1_CLIENT", "P2_HOST", "P2_CLIENT"),
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    instance_prefix = (
        args.instance_prefix or _default_instance_prefix()
    )
    result: dict[str, Any] = {
        "ok": False,
        "instance_prefix": instance_prefix,
    }
    try:
        result = run_live_verification(
            instance_prefix=instance_prefix,
            ports=_resolve_ports(args.ports),
            game_directory=args.game_dir,
        )
        exit_code = 0
    except Exception as exc:  # noqa: BLE001 - preserve live evidence.
        result["error"] = str(exc)
        exit_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
