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
    path_for_powershell,
    parse_int_text,
    parse_key_values,
    select_available_windows_udp_ports,
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
        or values.get("presentation_active") != "false"
        or values.get("red_effect_active") != "false"
        or _integer(values, "death_transition_hits") != 1
        or _integer(values, "staff_drop_hits") != 1
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
        spectating = _wait_for_client_spectator(client_pipe)
        result["spectating"] = spectating

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
        time.sleep(0.75)
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
        result["respawn_screenshot"] = capture_game_backbuffer(
            client_pipe,
            screenshot_directory
            / "client-respawn-with-dead-time-skill.png",
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

        samples: list[dict[str, str]] = []
        stable_until = time.monotonic() + 3.4
        while time.monotonic() < stable_until:
            sample = death.query_spectator_state(client_pipe)
            assert_immediate_respawn_sample(
                sample,
                epoch=epoch,
                wave=wave,
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
        result["normal_control"] = _assert_normal_control(
            client_pipe
        )
        screenshot_directory = SCREENSHOT_ROOT / instance_prefix
        result["respawn_screenshot"] = capture_game_backbuffer(
            client_pipe,
            screenshot_directory
            / "client-immediate-round-respawn-clean.png",
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
