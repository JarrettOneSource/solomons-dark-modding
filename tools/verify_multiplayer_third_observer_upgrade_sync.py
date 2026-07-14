#!/usr/bin/env python3
"""Verify three-player native progression and Air Chaining behavior parity."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from multiplayer_progression_probe import (
    compare_book_rows,
    compare_float_fields,
    query_progression_snapshot,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    THIRD_ID,
    THIRD_NAME,
    THIRD_PIPE,
    VerifyFailure,
    launch_trio,
    lua,
    parse_int_text,
    parse_key_values,
    place_player,
    start_testrun,
    stop_games,
    wait_for_remote,
    wait_for_scene,
)
from verify_multiplayer_all_upgrade_sync import (
    choose_offer,
    progression_snapshot_mismatches,
    publish_deterministic_offer,
    query_level_state,
    spell_mismatches,
    wait_for_offer,
    waiting_ids,
)
from verify_multiplayer_lightning_chaining_effect_sync import (
    AIR_LIGHTNING_CHAIN_COUNT_OFFSET,
    CHAINING_OPTION_ID,
    CLUSTER_PATTERNS,
    PARK_LOCAL_OBSERVER_LUA,
    TARGET_HP,
    build_air_chain_sync_evidence,
    build_manual_cluster,
    cast_lightning_cluster,
    dispatcher_chain_count,
    enable_flat_manual_cluster_combat,
    query_air_chain_audit,
    query_air_chain_state,
)
from verify_multiplayer_primary_kill_stress import (
    CLIENT_TARGET,
    PLAYER_HEADING_EAST,
    TARGET_FORWARD_DISTANCE,
    cleanup_live_enemies,
    clear_gameplay_mouse_left,
    find_target,
    set_manual_spawner_test_mode,
    spawn_one_enemy,
    values,
    wait_for_remote_position_convergence,
)
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import (
    CLIENT_LOG,
    Direction,
    HOST_LOG,
    detect_instance_pids,
    read_log,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "runtime" / "multiplayer_third_observer_air_chaining_current.json"
FLAT_BONEYARD = ROOT / "tests" / "fixtures" / "boneyards" / "flat_multiplayer_test.boneyard"
AIR_PRESET = "map_create_air_mind_hub"
THIRD_LOG = ROOT / "runtime/instances/local-mp-third/stage/.sdmod/logs/solomondarkmodloader.log"
PARITY_POLL_SECONDS = 0.05
TRANSIENT_LUA_BRIDGE_ERRORS = (
    "Cannot connect to pipe",
    "Lua engine is busy",
    "lua bridge daemon timed out",
    "lua bridge daemon closed unexpectedly",
    "lua bridge daemon write failed",
)


@dataclass(frozen=True)
class Participant:
    label: str
    participant_id: int
    name: str
    pipe: str
    log: Path
    pid_key: str


HOST = Participant("host", HOST_ID, HOST_NAME, HOST_PIPE, HOST_LOG, "host")
CLIENT = Participant("client", CLIENT_ID, CLIENT_NAME, CLIENT_PIPE, CLIENT_LOG, "client")
THIRD = Participant("third", THIRD_ID, THIRD_NAME, THIRD_PIPE, THIRD_LOG, "third")
PARTICIPANTS = (HOST, CLIENT, THIRD)


def other_participants(owner: Participant) -> tuple[Participant, Participant]:
    others = tuple(participant for participant in PARTICIPANTS if participant != owner)
    assert len(others) == 2
    return others


def lua_when_ready(
    participant: Participant,
    code: str,
    *,
    timeout: float,
    attempt_timeout: float = 8.0,
) -> str:
    """Run an idempotent startup command after transient pipe stalls clear.

    Three-player hub startup can briefly occupy the gameplay thread while two
    remote native progression objects are materialized and reconciled. During
    that bounded interval the Lua named-pipe server may not accept a connection
    even though the game and mod loader are healthy. Only known bridge-readiness
    failures are retried here; Lua/runtime errors still fail immediately.
    """
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            return lua(
                participant.pipe,
                code,
                timeout=min(attempt_timeout, max(0.1, deadline - time.monotonic())),
            )
        except VerifyFailure as exc:
            last_error = str(exc)
            if not any(marker in last_error for marker in TRANSIENT_LUA_BRIDGE_ERRORS):
                raise
            time.sleep(0.25)
    raise VerifyFailure(
        f"Lua bridge did not become ready for {participant.label}: {last_error}"
    )


def disable_all_bots(timeout: float) -> dict[str, str]:
    code = "lua_bots_disable_tick = true; sd.bots.clear(); return tostring(sd.bots.get_count())"
    result: dict[str, str] = {}
    for participant in PARTICIPANTS:
        count = lua_when_ready(
            participant,
            code,
            timeout=timeout,
        ).strip()
        if count != "0":
            raise VerifyFailure(
                f"failed to disable stock bots on {participant.label}: count={count!r}"
            )
        result[participant.label] = count
    return result


def wait_for_all_relationships(scene: str, timeout: float) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for observer in PARTICIPANTS:
        for owner in PARTICIPANTS:
            if observer == owner:
                continue
            key = f"{observer.label}_observes_{owner.label}"
            state = wait_for_remote(
                observer.pipe,
                owner.participant_id,
                owner.name,
                scene,
                timeout,
            )
            result[key] = {
                "actor": state.get(f"peer.{owner.participant_id}.actor"),
                "name": state.get(f"peer.{owner.participant_id}.name"),
                "nameplate": state.get(f"peer.{owner.participant_id}.nameplate"),
                "materialized": state.get(f"peer.{owner.participant_id}.materialized"),
                "transform": state.get(f"peer.{owner.participant_id}.transform"),
            }
    return result


def wait_for_trio_hub_settled(timeout: float, settle_seconds: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    settled_since: float | None = None
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        try:
            last = {
                participant.label: lua_when_ready(
                    participant,
                    "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
                    timeout=min(10.0, max(0.1, deadline - time.monotonic())),
                    attempt_timeout=5.0,
                ).strip()
                for participant in PARTICIPANTS
            }
        except VerifyFailure:
            settled_since = None
            time.sleep(0.25)
            continue
        if all(scene == "hub" for scene in last.values()):
            if settled_since is None:
                settled_since = time.monotonic()
            elif time.monotonic() - settled_since >= settle_seconds:
                return
        else:
            settled_since = None
        time.sleep(0.1)
    raise VerifyFailure(f"three instances did not remain hub-settled: {last}")


def start_trio_run(timeout: float) -> dict[str, Any]:
    wait_for_trio_hub_settled(timeout)
    start_testrun(HOST_PIPE)
    for participant in PARTICIPANTS:
        wait_for_scene(participant.pipe, "testrun", timeout)
    return {
        "host_started": True,
        "clients_followed": [CLIENT.participant_id, THIRD.participant_id],
        "scene": "testrun",
    }


def enable_quiet_progression_mode() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for participant in PARTICIPANTS:
        state = set_manual_spawner_test_mode(participant.pipe, True)
        if state.get("ok") != "true" or state.get("active") != "true":
            raise VerifyFailure(
                f"failed to enable quiet progression mode on {participant.label}: {state}"
            )
        result[participant.label] = state
    return result


def wait_for_three_pause(
    target_participant_id: int,
    active: bool,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        states = {
            participant.label: query_level_state(participant.pipe)
            for participant in PARTICIPANTS
        }
        ids = {label: waiting_ids(state) for label, state in states.items()}
        if active:
            ready = all(
                state.get("wait.pause_active") == "true"
                and target_participant_id in ids[label]
                for label, state in states.items()
            )
        else:
            ready = all(
                target_participant_id not in ids[label]
                for label in states
            )
        last = {"states": states, "waiting_ids": ids}
        if ready:
            return {"active": active, "waiting_ids": ids}
        time.sleep(PARITY_POLL_SECONDS)
    raise VerifyFailure(
        f"three-player pause did not become active={active} for "
        f"target={target_participant_id}: {last}"
    )


def wait_for_three_results(
    offer_id: int,
    target_participant_id: int,
    level: int,
    option_id: int,
    expected_active: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        states = {
            participant.label: query_level_state(participant.pipe)
            for participant in PARTICIPANTS
        }
        ready = all(
            state.get("result.valid") == "true"
            and parse_int_text(state.get("result.offer_id"), 0) == offer_id
            and parse_int_text(state.get("result.target"), 0) == target_participant_id
            and parse_int_text(state.get("result.level"), 0) == level
            and parse_int_text(state.get("result.option_id"), -1) == option_id
            and parse_int_text(state.get("result.apply_count"), 0) == 1
            and parse_int_text(state.get("result.resulting_active"), -1) == expected_active
            and parse_int_text(state.get("result.code"), 0) == 1
            for state in states.values()
        )
        last = states
        if ready:
            return {
                "offer_id": offer_id,
                "target_participant_id": target_participant_id,
                "level": level,
                "option_id": option_id,
                "resulting_active": expected_active,
                "received_by": sorted(states),
            }
        time.sleep(PARITY_POLL_SECONDS)
    raise VerifyFailure(f"accepted result did not reach all three peers: {last}")


def view_mismatches(owner: dict[str, Any], observer: dict[str, Any]) -> dict[str, Any]:
    scalar_mismatches = compare_float_fields(
        owner["native"],
        observer["native"],
        (
            "level",
            "previous_xp_threshold",
            "next_xp_threshold",
            "hp",
            "max_hp",
            "mp",
            "max_mp",
            "move_speed",
        ),
        tolerance=0.05,
    )
    scalar_mismatches.extend(
        compare_float_fields(owner["native"], observer["native"], ("xp",), tolerance=0.51)
    )
    return {
        "owner_native_vs_observer_native": compare_book_rows(
            owner["native"]["entries"], observer["native"]["entries"]
        ),
        "owner_native_vs_owner_ledger": compare_book_rows(
            owner["native"]["entries"], owner["ledger"]["entries"]
        ),
        "owner_native_vs_observer_ledger": compare_book_rows(
            owner["native"]["entries"], observer["ledger"]["entries"]
        ),
        "native_scalars": scalar_mismatches,
        "loadout": [] if owner["loadout"] == observer["loadout"] else [
            {"owner": owner["loadout"], "observer": observer["loadout"]}
        ],
        "spell": spell_mismatches(owner, observer),
    }


def compact_snapshot(snapshot: dict[str, Any], row: int) -> dict[str, Any]:
    entry = snapshot["native"]["entries"].get(row, {})
    return {
        "progression": f"0x{snapshot['progression']:08X}",
        "level": snapshot["native"]["level"],
        "xp": snapshot["native"]["xp"],
        "active": entry.get("active"),
        "visible": entry.get("visible"),
        "spellbook_revision": snapshot["ledger"]["spellbook_revision"],
        "statbook_revision": snapshot["ledger"]["statbook_revision"],
        "primary_entry": snapshot["loadout"]["primary_entry"],
        "current_spell_id": snapshot["spell"]["current_spell_id"],
        "spell_outputs": snapshot["spell"]["outputs"],
    }


def wait_for_owner_parity(
    owner: Participant,
    entry_index: int,
    expected_active: int,
    expected_level: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        owner_view = query_progression_snapshot(owner.pipe)
        observer_views = {
            observer.label: query_progression_snapshot(
                observer.pipe,
                participant_id=owner.participant_id,
            )
            for observer in other_participants(owner)
        }
        mismatch_sets = {
            label: view_mismatches(owner_view, observer_view)
            for label, observer_view in observer_views.items()
        }
        owner_row = owner_view["native"]["entries"].get(entry_index, {})
        observer_rows = {
            label: view["native"]["entries"].get(entry_index, {})
            for label, view in observer_views.items()
        }
        ready = (
            owner_view["available"]
            and owner_view["native"]["level"] == expected_level
            and owner_row.get("active") == expected_active
            and all(view["available"] for view in observer_views.values())
            and all(
                view["native"]["level"] == expected_level
                and observer_rows[label].get("active") == expected_active
                for label, view in observer_views.items()
            )
            and all(
                not any(mismatches.values())
                for mismatches in mismatch_sets.values()
            )
        )
        last = {
            "owner": compact_snapshot(owner_view, entry_index),
            "observers": {
                label: compact_snapshot(view, entry_index)
                for label, view in observer_views.items()
            },
            "mismatches": mismatch_sets,
        }
        if ready:
            return last
        time.sleep(PARITY_POLL_SECONDS)
    raise VerifyFailure(
        f"three-player progression parity timed out owner={owner.label} "
        f"entry={entry_index} active={expected_active} level={expected_level}: {last}"
    )


def verify_unchanged(
    participant: Participant,
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    mismatches = progression_snapshot_mismatches(before, after)
    if any(mismatches.values()):
        raise VerifyFailure(
            f"upgrade contaminated untargeted owner {participant.label}: {mismatches}"
        )
    return {
        "participant_id": participant.participant_id,
        "level": after["native"]["level"],
        "xp": after["native"]["xp"],
        "spellbook_revision": after["ledger"]["spellbook_revision"],
        "statbook_revision": after["ledger"]["statbook_revision"],
        "mismatches": mismatches,
    }


def apply_chaining(owner: Participant, timeout: float) -> dict[str, Any]:
    owner_before = query_progression_snapshot(owner.pipe)
    row_before = owner_before["native"]["entries"].get(CHAINING_OPTION_ID)
    if row_before is None:
        raise VerifyFailure(f"{owner.label} is missing Chaining row {CHAINING_OPTION_ID}")
    expected_active = int(row_before["active"]) + 1
    max_level = int(row_before["statbook_max_level"])
    if expected_active > max_level:
        raise VerifyFailure(
            f"{owner.label} Chaining is already maxed: active={row_before['active']} max={max_level}"
        )
    untargeted_before = {
        participant.label: query_progression_snapshot(participant.pipe)
        for participant in other_participants(owner)
    }
    target_level = int(owner_before["native"]["level"]) + 1
    target_experience = int(math.ceil(owner_before["native"]["next_xp_threshold"]))
    publish = publish_deterministic_offer(
        owner.participant_id,
        target_level,
        target_experience,
        CHAINING_OPTION_ID,
    )
    offer = wait_for_offer(
        owner.pipe,
        owner.participant_id,
        target_level,
        CHAINING_OPTION_ID,
        timeout,
    )
    pause_active = wait_for_three_pause(owner.participant_id, True, timeout)
    choice = choose_offer(owner.pipe, offer["offer_id"], CHAINING_OPTION_ID)
    result = wait_for_three_results(
        offer["offer_id"],
        owner.participant_id,
        target_level,
        CHAINING_OPTION_ID,
        expected_active,
        timeout,
    )
    parity = wait_for_owner_parity(
        owner,
        CHAINING_OPTION_ID,
        expected_active,
        target_level,
        timeout,
    )
    pause_cleared = wait_for_three_pause(owner.participant_id, False, timeout)
    isolation = {
        participant.label: verify_unchanged(
            participant,
            untargeted_before[participant.label],
            query_progression_snapshot(participant.pipe),
        )
        for participant in other_participants(owner)
    }
    return {
        "owner": owner.label,
        "target_participant_id": owner.participant_id,
        "before_active": row_before["active"],
        "expected_active": expected_active,
        "target_level": target_level,
        "target_experience": target_experience,
        "publish": publish,
        "offer": offer,
        "pause_active": pause_active,
        "choice": choice,
        "result": result,
        "parity": parity,
        "pause_cleared": pause_cleared,
        "untargeted_isolation": isolation,
    }


def verify_native_object_isolation(timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        process_views: dict[str, Any] = {}
        ready = True
        for process_owner in PARTICIPANTS:
            addresses: dict[str, int] = {}
            for represented in PARTICIPANTS:
                snapshot = query_progression_snapshot(
                    process_owner.pipe,
                    participant_id=(
                        None
                        if represented == process_owner
                        else represented.participant_id
                    ),
                )
                addresses[represented.label] = snapshot["progression"]
            nonzero = all(address != 0 for address in addresses.values())
            distinct = len(set(addresses.values())) == len(PARTICIPANTS)
            process_views[process_owner.label] = {
                "addresses": {
                    label: f"0x{address:08X}" for label, address in addresses.items()
                },
                "nonzero": nonzero,
                "distinct": distinct,
            }
            ready = ready and nonzero and distinct
        last = process_views
        if ready:
            return process_views
        time.sleep(PARITY_POLL_SECONDS)
    raise VerifyFailure(f"participant progression objects were not distinct: {last}")


def wait_for_target_binding(
    pipe_name: str,
    target: dict[str, Any],
    timeout: float = 10.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            return find_target(
                pipe_name,
                float(target["x"]),
                float(target["y"]),
                network_id=int(target["network_id"]),
                timeout=1.5,
                require_local_binding=True,
            )
        except VerifyFailure as exc:
            last_error = str(exc)
            time.sleep(0.1)
    raise VerifyFailure(
        f"target {target['network_id']} did not bind on {pipe_name}: {last_error}"
    )


def wait_for_cluster_bindings(pipe_name: str, cluster: dict[str, Any]) -> list[dict[str, str]]:
    return [wait_for_target_binding(pipe_name, target) for target in cluster["targets"]]


def park_local_observer(participant: Participant, cluster: dict[str, Any]) -> dict[str, str]:
    return values(
        participant.pipe,
        PARK_LOCAL_OBSERVER_LUA
        .replace("__X__", f"{float(cluster['primary_x']) - 1200.0:.3f}")
        .replace("__Y__", f"{float(cluster['primary_y']) + 1200.0:.3f}"),
    )


def build_third_source_cluster(
    direction: Direction,
    offsets: tuple[tuple[float, float], ...],
) -> dict[str, Any]:
    target_x, target_y = CLIENT_TARGET
    source_x = target_x - TARGET_FORWARD_DISTANCE
    placements = {
        "host": place_player(HOST_PIPE, target_x - 1200.0, target_y + 1200.0, PLAYER_HEADING_EAST),
        "client": place_player(CLIENT_PIPE, target_x - 1000.0, target_y + 1000.0, PLAYER_HEADING_EAST),
        "third": place_player(THIRD_PIPE, source_x, target_y, PLAYER_HEADING_EAST),
    }
    clears = {
        participant.label: clear_gameplay_mouse_left(participant.pipe)
        for participant in PARTICIPANTS
    }
    convergence = {
        "host_observes_third": wait_for_remote_position_convergence(
            HOST_PIPE, THIRD_ID, source_x, target_y
        ),
        "client_observes_third": wait_for_remote_position_convergence(
            CLIENT_PIPE, THIRD_ID, source_x, target_y
        ),
    }
    targets: list[dict[str, Any]] = []
    spawns: list[dict[str, Any]] = []
    for index, (offset_x, offset_y) in enumerate(((0.0, 0.0),) + offsets):
        x = target_x + offset_x
        y = target_y + offset_y
        spawn = spawn_one_enemy(x, y, TARGET_HP)
        network_id = parse_int_text(spawn["result"].get("network_actor_id"), 0)
        if network_id == 0:
            raise VerifyFailure(f"third-owner target {index} has no network id: {spawn}")
        target = {
            "label": "primary" if index == 0 else f"secondary_{index}",
            "network_id": network_id,
            "x": x,
            "y": y,
        }
        target["source"] = wait_for_target_binding(THIRD_PIPE, target)
        target["client"] = wait_for_target_binding(CLIENT_PIPE, target)
        targets.append(target)
        spawns.append(spawn)
    primary_source_actor = parse_int_text(
        targets[0]["source"].get("local.actor_address"), 0
    )
    if primary_source_actor == 0:
        raise VerifyFailure(f"third-owner primary target has no local actor: {targets[0]}")
    return {
        "lane": {
            "source_x": source_x,
            "source_y": target_y,
            "target_x": target_x,
            "target_y": target_y,
            "placements": placements,
            "clears": clears,
            "convergence": convergence,
        },
        "spawns": spawns,
        "secondary_offsets": [
            {"x": offset_x, "y": offset_y} for offset_x, offset_y in offsets
        ],
        "targets": targets,
        "primary_network_id": targets[0]["network_id"],
        "primary_actor_address": primary_source_actor,
        "primary_x": target_x,
        "primary_y": target_y,
    }


def make_direction(
    owner: Participant,
    receiver: Participant,
    pids: dict[str, int],
) -> Direction:
    return Direction(
        f"{owner.label}_to_{receiver.label}_three_player_chaining",
        owner.participant_id,
        owner.name,
        owner.pipe,
        owner.log,
        pids[owner.pid_key],
        receiver.pipe,
        receiver.log,
    )


def evidence_ok(evidence: dict[str, Any]) -> bool:
    return (
        evidence["max_owner_target_count"] > 0
        and evidence["max_observer_target_count"] > 0
        and evidence["matching_frame_count"] > 0
        and evidence["applied_target_parity"]
        and evidence["override_success_delta"] > 0
        and evidence["unmapped_target_delta"] == 0
        and evidence["source_override_success_delta"] > 0
        and evidence["source_override_failure_delta"] == 0
        and evidence["applied_source_endpoint_parity"]
        and evidence["endpoint_error_ok"]
        and evidence["owner_terminal_seen"]
        and evidence["observer_terminal_seen"]
    )


def run_owner_behavior_attempt(
    owner: Participant,
    receiver: Participant,
    extra_observer: Participant,
    pids: dict[str, int],
    offsets: tuple[tuple[float, float], ...],
) -> dict[str, Any]:
    cleanup = cleanup_live_enemies()
    direction = make_direction(owner, receiver, pids)
    if owner == THIRD:
        cluster = build_third_source_cluster(direction, offsets)
    else:
        place_player(
            THIRD_PIPE,
            CLIENT_TARGET[0] - 1200.0,
            CLIENT_TARGET[1] + 1200.0,
            PLAYER_HEADING_EAST,
        )
        cluster = build_manual_cluster(direction, offsets)
    extra_bindings = wait_for_cluster_bindings(extra_observer.pipe, cluster)
    extra_park = park_local_observer(extra_observer, cluster)
    set_local_player_vitals(THIRD_PIPE, 5000.0, 5000.0)
    clear_gameplay_mouse_left(THIRD_PIPE)
    extra_before = query_air_chain_audit(
        extra_observer.pipe, owner.participant_id
    )
    extra_chain_before = query_air_chain_state(
        extra_observer.pipe, participant_id=owner.participant_id
    )
    extra_log_offset = len(read_log(extra_observer.log))
    cast = cast_lightning_cluster(
        direction,
        cluster,
        f"three_player_chaining.{owner.label}",
        scripted_manual_control=True,
        additional_geometry_pipes=(extra_observer.pipe,),
    )
    extra_after = query_air_chain_audit(
        extra_observer.pipe, owner.participant_id
    )
    extra_chain_after = query_air_chain_state(
        extra_observer.pipe, participant_id=owner.participant_id
    )
    primary_attempt = {"cast": cast}
    primary_evidence = build_air_chain_sync_evidence(primary_attempt)
    extra_attempt = {
        "cast": {
            "air_chain_sync": {
                "before": {"observer": extra_before},
                "terminal": {
                    "owner": cast["air_chain_sync"]["terminal"]["owner"],
                    "observer": extra_after,
                },
            }
        }
    }
    extra_evidence = build_air_chain_sync_evidence(extra_attempt)
    extra_log = read_log(extra_observer.log)[extra_log_offset:]
    extra_delivery = {
        "remote_cast_queued": (
            f"Multiplayer remote cast queued. participant_id={owner.participant_id}"
            in extra_log
        ),
        "native_cast_prepped": (
            f"[bots] wizard cast prepped. bot_id={owner.participant_id}"
            in extra_log
        ),
    }
    primary_owner_chain = dispatcher_chain_count(primary_attempt, "owner")
    primary_observer_chain = dispatcher_chain_count(primary_attempt, "observer")
    extra_observer_chain = parse_int_text(extra_chain_after.get("chain_count"), -1)
    behavior_ok = (
        cast["replicated_cast_delivery"]["ok"]
        and primary_owner_chain > 0
        and primary_observer_chain > 0
        and extra_observer_chain > 0
        and evidence_ok(primary_evidence)
        and evidence_ok(extra_evidence)
        and extra_delivery["remote_cast_queued"]
        and extra_delivery["native_cast_prepped"]
    )
    return {
        "owner": owner.label,
        "owner_participant_id": owner.participant_id,
        "receiver": receiver.label,
        "extra_observer": extra_observer.label,
        "cleanup": cleanup,
        "cluster": cluster,
        "extra_bindings": extra_bindings,
        "extra_park": extra_park,
        "cast": cast,
        "primary_observer_evidence": primary_evidence,
        "extra_observer_evidence": extra_evidence,
        "dispatcher_chain_counts": {
            "owner": primary_owner_chain,
            receiver.label: primary_observer_chain,
            extra_observer.label: extra_observer_chain,
        },
        "extra_chain_before": extra_chain_before,
        "extra_chain_after": extra_chain_after,
        "extra_delivery": extra_delivery,
        "ok": behavior_ok,
    }


def compact_behavior_attempt(record: dict[str, Any]) -> dict[str, Any]:
    """Keep failed native-targeting attempts useful without duplicating huge audits."""
    return {
        "offsets": record.get("cluster", {}).get("secondary_offsets", []),
        "network_actor_ids": [
            target.get("network_id", 0)
            for target in record.get("cluster", {}).get("targets", [])
        ],
        "dispatcher_chain_counts": record.get("dispatcher_chain_counts", {}),
        "primary_observer_evidence": record.get("primary_observer_evidence", {}),
        "extra_observer_evidence": record.get("extra_observer_evidence", {}),
        "extra_delivery": record.get("extra_delivery", {}),
        "damage": record.get("cast", {}).get("damage", {}),
        "ok": record.get("ok", False),
    }


def verify_owner_behavior(
    owner: Participant,
    receiver: Participant,
    extra_observer: Participant,
    pids: dict[str, int],
) -> dict[str, Any]:
    # Native Lightning chooses its next victim from a live spatial query. A
    # valid cast can therefore have no candidate for one arrangement even
    # though every enemy exists and the ranked chain count is correct. Exercise
    # progressively tighter deterministic clusters, retaining each miss, and
    # require one real non-null authoritative target on both observers.
    prior_attempts: list[dict[str, Any]] = []
    for pattern_index, offsets in enumerate(CLUSTER_PATTERNS, start=1):
        try:
            record = run_owner_behavior_attempt(
                owner,
                receiver,
                extra_observer,
                pids,
                offsets,
            )
        except VerifyFailure as exc:
            prior_attempts.append(
                {
                    "pattern_index": pattern_index,
                    "offsets": [
                        {"x": offset_x, "y": offset_y}
                        for offset_x, offset_y in offsets
                    ],
                    "setup_or_cast_error": str(exc),
                    "ok": False,
                }
            )
            continue
        if record["ok"]:
            record["pattern_index"] = pattern_index
            record["prior_attempts"] = prior_attempts
            return record
        attempt = compact_behavior_attempt(record)
        attempt["pattern_index"] = pattern_index
        prior_attempts.append(attempt)

    raise VerifyFailure(
        f"three-player Chaining exhausted native target geometries "
        f"owner={owner.label}: {prior_attempts}"
    )


def new_crash_artifacts(started_at: float) -> list[str]:
    artifacts: list[str] = []
    for participant in PARTICIPANTS:
        log_dir = (
            ROOT
            / "runtime"
            / "instances"
            / f"local-mp-{participant.label}"
            / "stage"
            / ".sdmod"
            / "logs"
        )
        if not log_dir.exists():
            continue
        for path in log_dir.glob("*crash*"):
            if path.is_file() and path.stat().st_mtime >= started_at - 0.5:
                artifacts.append(str(path.relative_to(ROOT)))
    return sorted(artifacts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    started_at = time.time()
    output: dict[str, Any] = {"ok": False}
    try:
        stop_games()
        output["launch"] = launch_trio(
            preset=AIR_PRESET,
            god_mode=True,
            tile_windows=False,
            test_survival_boneyard_override=FLAT_BONEYARD,
            test_blank_boneyard=True,
        )
        output["hub_ready"] = wait_for_all_relationships("hub", args.timeout)
        output["bots_disabled"] = disable_all_bots(args.timeout)
        output["run_entry"] = start_trio_run(args.timeout)
        output["run_ready"] = wait_for_all_relationships("testrun", args.timeout)
        output["manual_combat"] = enable_flat_manual_cluster_combat()
        output["quiet_progression_mode"] = enable_quiet_progression_mode()
        output["initial_native_objects"] = verify_native_object_isolation(args.timeout)
        output["upgrades"] = []
        for owner in PARTICIPANTS:
            print(f"applying Chaining for {owner.label}", flush=True)
            output["upgrades"].append(apply_chaining(owner, args.timeout))
        output["post_upgrade_native_objects"] = verify_native_object_isolation(args.timeout)
        output["post_upgrade_parity"] = {
            owner.label: wait_for_owner_parity(
                owner,
                CHAINING_OPTION_ID,
                int(
                    query_progression_snapshot(owner.pipe)["native"]["entries"]
                    [CHAINING_OPTION_ID]["active"]
                ),
                int(query_progression_snapshot(owner.pipe)["native"]["level"]),
                args.timeout,
            )
            for owner in PARTICIPANTS
        }
        pids = detect_instance_pids()
        if "third" not in pids:
            raise VerifyFailure(f"third SolomonDark process was not detected: {pids}")
        output["process_ids"] = pids
        output["behavior"] = []
        behavior_specs = (
            (HOST, CLIENT, THIRD),
            (CLIENT, HOST, THIRD),
            (THIRD, HOST, CLIENT),
        )
        for owner, receiver, extra_observer in behavior_specs:
            print(f"casting upgraded Air for {owner.label}", flush=True)
            output["behavior"].append(
                verify_owner_behavior(owner, receiver, extra_observer, pids)
            )
        crashes = new_crash_artifacts(started_at)
        output["new_crash_artifacts"] = crashes
        if crashes:
            raise VerifyFailure(f"new crash artifacts appeared: {crashes}")
        output["summary"] = {
            "participant_count": 3,
            "observer_relationship_count": 6,
            "upgrade_owner_count": len(output["upgrades"]),
            "behavior_owner_count": len(output["behavior"]),
            "native_skillbook_observer_checks": 6,
            "exact_air_chain_observer_checks": 6,
            "chain_count_offset": f"0x{AIR_LIGHTNING_CHAIN_COUNT_OFFSET:X}",
        }
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.TimeoutExpired, ValueError, KeyError) as exc:
        output["error"] = str(exc)
        output["new_crash_artifacts"] = new_crash_artifacts(started_at)
        return_code = 1
    finally:
        if not args.keep_open:
            stop_games()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "error": output.get("error", ""),
                "summary": output.get("summary", {}),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
