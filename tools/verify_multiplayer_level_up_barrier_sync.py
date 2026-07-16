#!/usr/bin/env python3
"""Verify all-player level-up pause, waiting UI, resume, and timeout auto-pick."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    VerifyFailure,
    disable_bots,
    launch_pair,
    parse_int_text,
    place_player,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)
from verify_multiplayer_level_up_offer_sync import (
    capture,
    choose_client_option,
    choose_host_option,
    publish_barrier_offer,
    query_progression_entry,
    query_progression_stats,
    wait_for_choice_result,
    wait_for_client_offer,
    wait_for_host_offer,
    wait_for_waiting_ids,
)
from verify_multiplayer_primary_kill_stress import (
    enable_manual_stock_spawner_combat,
    parse_float,
    parse_int,
    query_run_enemy_by_network_id,
    set_manual_spawner_test_mode,
    spawn_one_enemy,
)
from verify_player_health_death_sync import (
    query_local_player_vitals,
    set_local_player_vitals,
)


ROOT = Path(__file__).resolve().parent.parent
RUNTIME_OUTPUT = ROOT / "runtime" / "multiplayer_level_up_barrier_sync.json"
HOST_LOG = ROOT / "runtime/instances/local-mp-host/stage/.sdmod/logs/solomondarkmodloader.log"
CLIENT_LOG = ROOT / "runtime/instances/local-mp-client/stage/.sdmod/logs/solomondarkmodloader.log"

WORLD_ACTIVITY_TEST_HP = 50_000.0
WORLD_ACTIVITY_HOST_POSITION = (900.0, 1750.0)
WORLD_ACTIVITY_CLIENT_POSITION = (2800.0, 1750.0)
WORLD_ACTIVITY_ENEMY_POSITION = (1800.0, 1750.0)
WORLD_ACTIVITY_MOTION_THRESHOLD = 2.0
WORLD_ACTIVITY_PAUSE_TOLERANCE = 0.75
WORLD_ACTIVITY_HP_TOLERANCE = 0.01


def read_log_from(path: Path, offset: int) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read().decode("utf-8", errors="replace")


def next_shared_level() -> tuple[int, int, dict[str, Any]]:
    host = query_progression_stats(HOST_PIPE)
    client = query_progression_stats(CLIENT_PIPE)
    if not host["available"] or not client["available"]:
        raise VerifyFailure(
            f"local progression unavailable: host={host} client={client}"
        )
    level = max(host["level"], client["level"]) + 1
    experience = int(
        max(
            host["next_xp_threshold"],
            client["next_xp_threshold"],
            125.0,
        )
        + 10.0
    )
    return level, experience, {"host": host, "client": client}


def summarize_wait(snapshot: dict[str, str]) -> dict[str, Any]:
    waiting_count = parse_int_text(snapshot.get("wait.waiting_count"), 0)
    return {
        "valid": snapshot.get("wait.valid") == "true",
        "pause_active": snapshot.get("wait.pause_active") == "true",
        "timed_out": snapshot.get("wait.timed_out") == "true",
        "barrier_id": parse_int_text(snapshot.get("wait.barrier_id"), 0),
        "revision": parse_int_text(snapshot.get("wait.revision"), 0),
        "deadline_remaining_ms": parse_int_text(
            snapshot.get("wait.deadline_remaining_ms"),
            0,
        ),
        "waiting_count": waiting_count,
        "waiting_participant_ids": [
            parse_int_text(snapshot.get(f"wait.participant.{index}"), 0)
            for index in range(1, waiting_count + 1)
        ],
        "display_text": snapshot.get("wait.display_text", ""),
    }


def require_enemy_state(network_actor_id: int) -> dict[str, str]:
    state = query_run_enemy_by_network_id(HOST_PIPE, network_actor_id)
    if state.get("found") != "true" or state.get("dead") == "true":
        raise VerifyFailure(
            "world-activity probe enemy disappeared: "
            f"network_actor_id={network_actor_id} state={state}"
        )
    return state


def position_delta(before: dict[str, str], after: dict[str, str]) -> float:
    return math.hypot(
        parse_float(after.get("x")) - parse_float(before.get("x")),
        parse_float(after.get("y")) - parse_float(before.get("y")),
    )


def wait_for_enemy_motion(
    network_actor_id: int,
    start: dict[str, str],
    *,
    timeout: float = 6.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = start
    while time.monotonic() < deadline:
        last = require_enemy_state(network_actor_id)
        drift = position_delta(start, last)
        if drift >= WORLD_ACTIVITY_MOTION_THRESHOLD:
            return {
                "before": start,
                "after": last,
                "position_drift": drift,
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "world-activity probe enemy did not move while gameplay was active: "
        f"network_actor_id={network_actor_id} before={start} after={last}"
    )


def prepare_world_activity_probe() -> dict[str, Any]:
    host_vitals = set_local_player_vitals(
        HOST_PIPE,
        WORLD_ACTIVITY_TEST_HP,
        WORLD_ACTIVITY_TEST_HP,
    )
    client_vitals = set_local_player_vitals(
        CLIENT_PIPE,
        WORLD_ACTIVITY_TEST_HP,
        WORLD_ACTIVITY_TEST_HP,
    )
    host_place = place_player(
        HOST_PIPE,
        WORLD_ACTIVITY_HOST_POSITION[0],
        WORLD_ACTIVITY_HOST_POSITION[1],
        90.0,
    )
    client_place = place_player(
        CLIENT_PIPE,
        WORLD_ACTIVITY_CLIENT_POSITION[0],
        WORLD_ACTIVITY_CLIENT_POSITION[1],
        270.0,
    )
    time.sleep(0.35)
    spawn = spawn_one_enemy(
        WORLD_ACTIVITY_ENEMY_POSITION[0],
        WORLD_ACTIVITY_ENEMY_POSITION[1],
        WORLD_ACTIVITY_TEST_HP,
        freeze_on_spawn=False,
    )
    network_actor_id = parse_int(spawn["result"].get("network_actor_id"))
    if network_actor_id == 0:
        raise VerifyFailure(f"world-activity probe spawn had no network id: {spawn}")

    deadline = time.monotonic() + 6.0
    initial: dict[str, str] = {}
    while time.monotonic() < deadline:
        initial = query_run_enemy_by_network_id(HOST_PIPE, network_actor_id)
        if initial.get("found") == "true":
            break
        time.sleep(0.1)
    if initial.get("found") != "true":
        raise VerifyFailure(
            "world-activity probe enemy never entered the authoritative snapshot: "
            f"network_actor_id={network_actor_id} last={initial}"
        )
    active_motion = wait_for_enemy_motion(network_actor_id, initial)
    return {
        "network_actor_id": network_actor_id,
        "host_vitals": host_vitals,
        "client_vitals": client_vitals,
        "host_place": host_place,
        "client_place": client_place,
        "spawn": spawn,
        "active_motion": active_motion,
    }


def verify_world_activity_paused(world_activity_probe: dict[str, Any]) -> dict[str, Any]:
    network_actor_id = int(world_activity_probe["network_actor_id"])
    # Allow one already-published transform to settle after the barrier revision.
    time.sleep(0.35)
    before = require_enemy_state(network_actor_id)
    health_before = query_local_player_vitals(HOST_PIPE)
    time.sleep(1.5)
    after = require_enemy_state(network_actor_id)
    health_after = query_local_player_vitals(HOST_PIPE)
    pause_position_drift = position_delta(before, after)
    pause_hp_drift = abs(
        parse_float(health_after.get("hp"))
        - parse_float(health_before.get("hp"))
    )
    if pause_position_drift > WORLD_ACTIVITY_PAUSE_TOLERANCE:
        raise VerifyFailure(
            "enemy world activity continued while another participant was still "
            "choosing a skill: "
            f"drift={pause_position_drift:.3f} before={before} after={after}"
        )
    if pause_hp_drift > WORLD_ACTIVITY_HP_TOLERANCE:
        raise VerifyFailure(
            "host remained vulnerable while waiting on another participant's "
            "skill choice: "
            f"hp_drift={pause_hp_drift:.3f} before={health_before} after={health_after}"
        )
    return {
        "before": before,
        "after": after,
        "health_before": health_before,
        "health_after": health_after,
        "pause_position_drift": pause_position_drift,
        "pause_hp_drift": pause_hp_drift,
    }


def verify_world_activity_resumed(
    world_activity_probe: dict[str, Any],
    paused: dict[str, Any],
) -> dict[str, Any]:
    network_actor_id = int(world_activity_probe["network_actor_id"])
    motion = wait_for_enemy_motion(
        network_actor_id,
        paused["after"],
    )
    motion["resumed_position_drift"] = motion.pop("position_drift")
    return motion


def wait_for_observer_choice_result(
    pipe_name: str,
    *,
    offer_id: int,
    target_participant_id: int,
    level: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = capture(pipe_name)
        if (
            parse_int_text(last.get("result.offer_id"), 0) == offer_id
            and parse_int_text(last.get("result.target"), 0)
            == target_participant_id
            and parse_int_text(last.get("result.code"), 0) == 1
            and parse_int_text(last.get("result.level"), 0) == level
        ):
            return {
                "raw": last,
                "option_id": parse_int_text(last.get("result.option_id"), -1),
                "resulting_active": parse_int_text(
                    last.get("result.resulting_active"),
                    0,
                ),
                "auto_picked": last.get("result.auto_picked") == "true",
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "accepted level-up choice result was not visible to its local owner: "
        f"offer_id={offer_id} target_participant_id={target_participant_id} "
        f"last={last}"
    )


def wait_for_native_upgrade_convergence(
    *,
    owner_pipe: str,
    observer_pipe: str,
    owner_participant_id: int,
    option_id: int,
    expected_active: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    owner: dict[str, Any] = {}
    observer: dict[str, Any] = {}
    while time.monotonic() < deadline:
        owner = query_progression_entry(owner_pipe, option_id=option_id)
        observer = query_progression_entry(
            observer_pipe,
            option_id=option_id,
            participant_id=owner_participant_id,
        )
        if (
            owner["available"]
            and observer["available"]
            and owner["active"] == expected_active
            and observer["active"] == expected_active
        ):
            return {"owner": owner, "observer": observer}
        time.sleep(0.1)
    raise VerifyFailure(
        "level-up upgrade did not converge on the owner and remote native clone: "
        f"owner_participant_id={owner_participant_id} option_id={option_id} "
        f"expected_active={expected_active} owner={owner} observer={observer}"
    )


def verify_normal_barrier(
    timeout: float,
    world_activity_probe: dict[str, Any],
) -> dict[str, Any]:
    level, experience, before = next_shared_level()
    publish = publish_barrier_offer(level, experience)
    host_offer = wait_for_host_offer(level, timeout)
    client_offer = wait_for_client_offer(level, timeout)
    host_option_id = host_offer["first_option_id"]
    host_apply_count = parse_int_text(
        host_offer["raw"].get("offer.option.1.apply_count"),
        1,
    )
    client_option_id = client_offer["first_option_id"]
    client_apply_count = parse_int_text(
        client_offer["raw"].get("offer.option.1.apply_count"),
        1,
    )
    host_remote_before = query_progression_entry(
        HOST_PIPE,
        option_id=client_option_id,
        participant_id=CLIENT_ID,
    )
    client_local_before = query_progression_entry(
        CLIENT_PIPE,
        option_id=client_option_id,
    )
    host_local_before = query_progression_entry(
        HOST_PIPE,
        option_id=host_option_id,
    )
    client_remote_host_before = query_progression_entry(
        CLIENT_PIPE,
        option_id=host_option_id,
        participant_id=HOST_ID,
    )
    if not (
        host_remote_before["available"]
        and client_local_before["available"]
        and host_remote_before["active"] == client_local_before["active"]
    ):
        raise VerifyFailure(
            "remote client progression did not share a native pre-choice baseline: "
            f"host_remote={host_remote_before} client_local={client_local_before}"
        )
    if not (
        host_local_before["available"]
        and client_remote_host_before["available"]
        and host_local_before["active"] == client_remote_host_before["active"]
    ):
        raise VerifyFailure(
            "host progression did not share a native pre-choice baseline with "
            "the client's remote clone: "
            f"host_local={host_local_before} "
            f"client_remote_host={client_remote_host_before}"
        )
    expected_client_active = client_local_before["active"] + client_apply_count
    expected_host_active = host_local_before["active"] + host_apply_count
    active = wait_for_waiting_ids(
        {HOST_ID, CLIENT_ID},
        timeout,
        require_timed_out=False,
    )
    active_host = summarize_wait(active["host"])
    active_client = summarize_wait(active["client"])
    if not (
        0 < active_host["deadline_remaining_ms"] <= 60_000
        and 0 < active_client["deadline_remaining_ms"] <= 60_000
    ):
        raise VerifyFailure(
            f"normal barrier did not publish a live 60-second deadline: {active}"
        )

    client_choice = choose_client_option(client_offer["offer_id"], 1)
    client_result = wait_for_choice_result(
        client_offer["offer_id"],
        level,
        timeout,
        target_participant_id=CLIENT_ID,
    )
    if client_result["auto_picked"]:
        raise VerifyFailure(
            f"manual client choice was marked auto-picked: {client_result}"
        )
    if client_result["result_option_id"] != client_option_id:
        raise VerifyFailure(
            "manual remote result selected a different option than requested: "
            f"offered={client_option_id} result={client_result}"
        )
    resulting_active = client_result["resulting_active"]
    host_remote_entry = query_progression_entry(
        HOST_PIPE,
        option_id=client_option_id,
        participant_id=CLIENT_ID,
    )
    client_local_entry = query_progression_entry(
        CLIENT_PIPE,
        option_id=client_option_id,
    )
    if not (
        resulting_active == expected_client_active
        and host_remote_entry["available"]
        and client_local_entry["available"]
        and host_remote_entry["active"] == resulting_active
        and client_local_entry["active"] == resulting_active
    ):
        raise VerifyFailure(
            "manual remote level-up did not converge exactly once on both native "
            f"progressions: option_id={client_option_id} "
            f"apply_count={client_apply_count} expected_active={expected_client_active} "
            f"resulting_active={resulting_active} before_host={host_remote_before} "
            f"before_client={client_local_before} "
            f"host_remote={host_remote_entry} client_local={client_local_entry}"
        )

    waiting = wait_for_waiting_ids(
        {HOST_ID},
        timeout,
        client_display_text="Waiting on 1 player",
        require_timed_out=False,
    )
    waiting_host = summarize_wait(waiting["host"])
    waiting_client = summarize_wait(waiting["client"])
    if waiting_host["display_text"] != "Choose your skill upgrade":
        raise VerifyFailure(
            "unresolved host did not retain its choice prompt while the client "
            f"waited: {waiting_host}"
        )

    paused_world_activity = verify_world_activity_paused(world_activity_probe)

    host_choice = choose_host_option(host_offer["offer_id"], 1)
    host_result = wait_for_observer_choice_result(
        HOST_PIPE,
        offer_id=host_offer["offer_id"],
        target_participant_id=HOST_ID,
        level=level,
        timeout=timeout,
    )
    if host_result["auto_picked"]:
        raise VerifyFailure(f"manual host choice was marked auto-picked: {host_result}")
    if host_result["option_id"] != host_option_id:
        raise VerifyFailure(
            "manual host result selected a different option than requested: "
            f"offered={host_option_id} result={host_result}"
        )
    if host_result["resulting_active"] != expected_host_active:
        raise VerifyFailure(
            "manual host result reported an unexpected native rank: "
            f"expected_active={expected_host_active} result={host_result}"
        )
    host_native_upgrade = wait_for_native_upgrade_convergence(
        owner_pipe=HOST_PIPE,
        observer_pipe=CLIENT_PIPE,
        owner_participant_id=HOST_ID,
        option_id=host_option_id,
        expected_active=expected_host_active,
        timeout=timeout,
    )
    resumed = wait_for_waiting_ids(
        set(),
        timeout,
        require_timed_out=False,
    )
    resumed_host = summarize_wait(resumed["host"])
    resumed_client = summarize_wait(resumed["client"])
    if resumed_host["display_text"] or resumed_client["display_text"]:
        raise VerifyFailure(
            "completed normal barrier retained level-up wait text: "
            f"host={resumed_host} client={resumed_client}"
        )
    if not (
        active_host["barrier_id"]
        == waiting_host["barrier_id"]
        == resumed_host["barrier_id"]
        == active_client["barrier_id"]
        == waiting_client["barrier_id"]
        == resumed_client["barrier_id"]
    ):
        raise VerifyFailure("normal barrier id diverged between stages or peers")
    if not (
        active_host["revision"]
        < waiting_host["revision"]
        < resumed_host["revision"]
    ):
        raise VerifyFailure(
            "normal barrier revision did not advance through pick/resume: "
            f"active={active_host} waiting={waiting_host} resumed={resumed_host}"
        )
    resumed_world_activity = verify_world_activity_resumed(
        world_activity_probe,
        paused_world_activity,
    )

    return {
        "level": level,
        "experience": experience,
        "progression_before": before,
        "publish": publish,
        "host_offer_id": host_offer["offer_id"],
        "client_offer_id": client_offer["offer_id"],
        "active": {"host": active_host, "client": active_client},
        "host_choice": host_choice,
        "host_result_option_id": host_result["option_id"],
        "host_native_upgrade": {
            "apply_count": host_apply_count,
            "expected_active": expected_host_active,
            "resulting_active": host_result["resulting_active"],
            "host_local_before": host_local_before,
            "client_remote_host_before": client_remote_host_before,
            "host_local": host_native_upgrade["owner"],
            "client_remote_host": host_native_upgrade["observer"],
        },
        "client_waiting_for_host": {
            "host": waiting_host,
            "client": waiting_client,
        },
        "world_activity": {
            "probe": world_activity_probe,
            "paused": paused_world_activity,
            "resumed": resumed_world_activity,
        },
        "client_choice": client_choice,
        "client_result_option_id": client_result["result_option_id"],
        "client_native_upgrade": {
            "apply_count": client_apply_count,
            "expected_active": expected_client_active,
            "resulting_active": resulting_active,
            "host_remote_before": host_remote_before,
            "client_local_before": client_local_before,
            "host_remote_client": host_remote_entry,
            "client_local": client_local_entry,
        },
        "resumed": {"host": resumed_host, "client": resumed_client},
    }


def wait_for_timeout_auto_pick(
    *,
    barrier_id: int,
    client_offer_id: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_host: dict[str, str] = {}
    last_client: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_host = capture(HOST_PIPE)
        last_client = capture(CLIENT_PIPE)
        snapshots = (last_host, last_client)
        if all(
            snapshot.get("wait.pause_active") == "false"
            and snapshot.get("wait.timed_out") == "true"
            and parse_int_text(snapshot.get("wait.waiting_count"), 0) == 0
            and parse_int_text(snapshot.get("player.skill_picker_screen"), 0) == 0
            and snapshot.get("offer.valid") == "false"
            and parse_int_text(snapshot.get("wait.barrier_id"), 0) == barrier_id
            and parse_int_text(snapshot.get("result.offer_id"), 0)
            == client_offer_id
            and parse_int_text(snapshot.get("result.target"), 0) == CLIENT_ID
            and parse_int_text(snapshot.get("result.code"), 0) == 1
            and snapshot.get("result.auto_picked") == "true"
            for snapshot in snapshots
        ):
            return {
                "host": last_host,
                "client": last_client,
                "option_id": parse_int_text(
                    last_client.get("result.option_id"),
                    -1,
                ),
                "resulting_active": parse_int_text(
                    last_client.get("result.resulting_active"),
                    0,
                ),
                "picker_screen": {
                    "host": parse_int_text(
                        last_host.get("player.skill_picker_screen"),
                        0,
                    ),
                    "client": parse_int_text(
                        last_client.get("player.skill_picker_screen"),
                        0,
                    ),
                },
                "offer_valid": {
                    "host": last_host.get("offer.valid") == "true",
                    "client": last_client.get("offer.valid") == "true",
                },
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "60-second level-up timeout did not auto-pick and resume both peers: "
        f"barrier_id={barrier_id} client_offer_id={client_offer_id} "
        f"last_host={last_host} last_client={last_client}"
    )


def verify_timeout_barrier(setup_timeout: float, auto_timeout: float) -> dict[str, Any]:
    level, experience, before = next_shared_level()
    started = time.monotonic()
    host_log_offset = HOST_LOG.stat().st_size if HOST_LOG.exists() else 0
    client_log_offset = CLIENT_LOG.stat().st_size if CLIENT_LOG.exists() else 0
    publish = publish_barrier_offer(level, experience)
    host_offer = wait_for_host_offer(level, setup_timeout)
    client_offer = wait_for_client_offer(level, setup_timeout)
    client_option_baselines: dict[int, dict[str, Any]] = {}
    for option_index, option_id in enumerate(client_offer["option_ids"], start=1):
        apply_count = parse_int_text(
            client_offer["raw"].get(
                f"offer.option.{option_index}.apply_count"
            ),
            1,
        )
        host_remote_before = query_progression_entry(
            HOST_PIPE,
            option_id=option_id,
            participant_id=CLIENT_ID,
        )
        client_local_before = query_progression_entry(
            CLIENT_PIPE,
            option_id=option_id,
        )
        if not (
            host_remote_before["available"]
            and client_local_before["available"]
            and host_remote_before["active"] == client_local_before["active"]
        ):
            raise VerifyFailure(
                "timeout offer lacked a shared native pre-choice baseline: "
                f"option_id={option_id} host_remote={host_remote_before} "
                f"client_local={client_local_before}"
            )
        client_option_baselines[option_id] = {
            "apply_count": apply_count,
            "host_remote_before": host_remote_before,
            "client_local_before": client_local_before,
            "expected_active": client_local_before["active"] + apply_count,
        }
    active = wait_for_waiting_ids(
        {HOST_ID, CLIENT_ID},
        setup_timeout,
        require_timed_out=False,
    )
    active_host = summarize_wait(active["host"])

    host_choice = choose_host_option(host_offer["offer_id"], 1)
    host_result = wait_for_choice_result(
        host_offer["offer_id"],
        level,
        setup_timeout,
        target_participant_id=HOST_ID,
    )
    waiting = wait_for_waiting_ids(
        {CLIENT_ID},
        setup_timeout,
        host_display_text="Waiting on 1 player",
        require_timed_out=False,
    )
    waiting_host = summarize_wait(waiting["host"])

    auto_result = wait_for_timeout_auto_pick(
        barrier_id=active_host["barrier_id"],
        client_offer_id=client_offer["offer_id"],
        timeout=auto_timeout,
    )
    elapsed = time.monotonic() - started
    if elapsed < 58.0:
        raise VerifyFailure(
            f"level-up timeout fired too early: elapsed={elapsed:.3f}s"
        )

    final_host = summarize_wait(auto_result["host"])
    final_client = summarize_wait(auto_result["client"])
    if final_host["display_text"] or final_client["display_text"]:
        raise VerifyFailure(
            "timeout resume retained level-up wait text: "
            f"host={final_host} client={final_client}"
        )
    if final_host["revision"] <= waiting_host["revision"]:
        raise VerifyFailure(
            "timeout final barrier revision did not advance: "
            f"waiting={waiting_host} final={final_host}"
        )

    option_id = auto_result["option_id"]
    host_remote_entry = query_progression_entry(
        HOST_PIPE,
        option_id=option_id,
        participant_id=CLIENT_ID,
    )
    client_local_entry = query_progression_entry(
        CLIENT_PIPE,
        option_id=option_id,
    )
    resulting_active = auto_result["resulting_active"]
    selected_baseline = client_option_baselines.get(option_id)
    if not (
        selected_baseline is not None
        and resulting_active == selected_baseline["expected_active"]
        and host_remote_entry["available"]
        and client_local_entry["available"]
        and host_remote_entry["active"] == resulting_active
        and client_local_entry["active"] == resulting_active
    ):
        raise VerifyFailure(
            "timeout auto-pick did not converge the selected upgrade exactly once: "
            f"resulting_active={resulting_active} "
            f"baseline={selected_baseline} "
            f"host_remote={host_remote_entry} client_local={client_local_entry}"
        )

    host_level_up_log = read_log_from(HOST_LOG, host_log_offset)
    client_level_up_log = read_log_from(CLIENT_LOG, client_log_offset)
    confirmation_send_count = client_level_up_log.count(
        "forced level-up choice applied and native picker closed; confirmation sent"
    )
    host_confirmation_accept_count = sum(
        "auto_pick_confirmation=1" in line and "result=Accepted" in line
        for line in host_level_up_log.splitlines()
    )
    if confirmation_send_count != 1 or host_confirmation_accept_count > 2:
        raise VerifyFailure(
            "forced auto-pick produced a confirmation feedback loop: "
            f"client_sends={confirmation_send_count} "
            f"host_accepts={host_confirmation_accept_count}"
        )

    return {
        "level": level,
        "experience": experience,
        "elapsed_seconds": elapsed,
        "progression_before": before,
        "publish": publish,
        "host_offer_id": host_offer["offer_id"],
        "client_offer_id": client_offer["offer_id"],
        "active": active_host,
        "host_choice": host_choice,
        "host_result_option_id": host_result["result_option_id"],
        "waiting_for_client": waiting_host,
        "auto_result": {
            "option_id": option_id,
            "resulting_active": resulting_active,
            "picker_screen": auto_result["picker_screen"],
            "offer_valid": auto_result["offer_valid"],
            "host": final_host,
            "client": final_client,
        },
        "native_upgrade": {
            "baseline": selected_baseline,
            "host_remote_client": host_remote_entry,
            "client_local": client_local_entry,
        },
        "confirmation_counts": {
            "client_send_events": confirmation_send_count,
            "host_accepted_packets": host_confirmation_accept_count,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--auto-timeout", type=float, default=75.0)
    parser.add_argument(
        "--normal-only",
        action="store_true",
        help="run the fast manual-choice barrier regression without the 60-second timeout case",
    )
    args = parser.parse_args()

    output: dict[str, Any] = {"ok": False}
    try:
        stop_games()
        output["launch"] = launch_pair()
        disable_bots()
        output["hub_ready"] = {
            "host_observes_client": wait_for_remote(
                HOST_PIPE,
                CLIENT_ID,
                CLIENT_NAME,
                "hub",
            ),
            "client_observes_host": wait_for_remote(
                CLIENT_PIPE,
                HOST_ID,
                HOST_NAME,
                "hub",
            ),
        }
        output["manual_spawner_mode"] = {
            "host": set_manual_spawner_test_mode(HOST_PIPE, True),
            "client": set_manual_spawner_test_mode(CLIENT_PIPE, True),
        }
        output["run_entry"] = start_host_testrun_and_wait_for_clients(
            timeout=args.timeout
        )
        output["run_ready"] = {
            "host_observes_client": wait_for_remote(
                HOST_PIPE,
                CLIENT_ID,
                CLIENT_NAME,
                "testrun",
            ),
            "client_observes_host": wait_for_remote(
                CLIENT_PIPE,
                HOST_ID,
                HOST_NAME,
                "testrun",
            ),
        }
        output["combat_bootstrap"] = enable_manual_stock_spawner_combat()
        output["world_activity_probe"] = prepare_world_activity_probe()
        output["normal_barrier"] = verify_normal_barrier(
            args.timeout,
            output["world_activity_probe"],
        )
        if not args.normal_only:
            output["timeout_barrier"] = verify_timeout_barrier(
                args.timeout,
                args.auto_timeout,
            )
        output["ok"] = True
    except (VerifyFailure, subprocess.TimeoutExpired) as exc:
        output["error"] = str(exc)
    finally:
        if not args.keep_open:
            stop_games()

    RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_OUTPUT.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    elif output["ok"]:
        if args.normal_only:
            normal_result = output["normal_barrier"]
            print(
                "level-up barrier sync ok: normal all-player resume; "
                f"remote_option={normal_result['client_result_option_id']}"
            )
        else:
            timeout_result = output["timeout_barrier"]
            print(
                "level-up barrier sync ok: normal all-player resume; "
                f"timeout_auto_pick={timeout_result['elapsed_seconds']:.3f}s "
                f"option={timeout_result['auto_result']['option_id']}"
            )
    else:
        print(f"level-up barrier sync verifier failed: {output.get('error', '')}")
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
