#!/usr/bin/env python3
"""Trace stock Earth Boulder damage in an isolated two-peer loopback matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import time
from pathlib import Path
from typing import Any

import verify_local_multiplayer_sync as local_sync
import verify_multiplayer_primary_kill_stress as kill
import verify_multiplayer_replicated_audio_events as audio
from verify_player_health_death_sync import set_local_player_vitals
from verify_real_input_spell_cast_sync import Direction


ROOT = Path(__file__).resolve().parents[1]
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
FLAT_BONEYARD = (
    ROOT / "tests/fixtures/boneyards/flat_multiplayer_test.boneyard"
)
BOULDER_CONFIG = GAME_DIRECTORY / "data/wizardskills/boulder.cfg"
REQUIRED_RUNTIME_PARENT = Path("/mnt/c/sd-earth-damage-20260727")
REQUIRED_INSTANCE_PREFIX = "edmg"
REQUIRED_HOST_PORT = 48911
REQUIRED_CLIENT_PORT = 48912
TARGET_X = 1800.0
TARGET_Y = 1750.0
CASTER_X = TARGET_X - 176.0
OBSERVER_X = TARGET_X + 640.0
OBSERVER_Y = TARGET_Y + 480.0
TARGET_HP = 50_000.0
PLAYER_HP = 50_000.0
SKELETON_TYPE_ID = 1001
CONDITIONS = (
    ("instant_release", 2),
    ("audit_hold_170", 170),
    ("fully_held", 900),
)

INTEGER_TRACE_FIELDS = (
    "sequence",
    "source_participant_id",
    "source_actor_address",
    "owner_actor_address",
    "progression_address",
    "target_actor_address",
    "source_native_type_id",
    "source_gameplay_slot",
    "progression_level",
    "effective_rank",
)
FLOAT_TRACE_FIELDS = (
    "progression_base_additive",
    "configured_rank_damage",
    "progression_global_flat",
    "progression_spell_flat",
    "progression_class_flat",
    "progression_global_multiplier",
    "progression_spell_multiplier",
    "progression_class_multiplier",
    "progression_siege_multiplier",
    "actor_stat_damage",
    "charge",
    "growth_rate",
    "release_charge",
    "release_damage_pool",
    "release_base_damage",
    "maximum_charge",
    "toughness",
    "damage_lane_primary",
    "damage_lane_secondary",
    "target_hp_before",
    "target_hp_after",
    "target_max_hp",
    "hp_delta",
)


def stage(message: str) -> None:
    print(f"[earth-damage] {message}", flush=True)


def values(
    pipe_name: str,
    code: str,
    *,
    timeout: float = 8.0,
) -> dict[str, str]:
    return local_sync.parse_key_values(
        local_sync.lua(pipe_name, code, timeout=timeout)
    )


def parse_int(value: str | None, default: int = 0) -> int:
    if not value:
        return default
    try:
        return int(value, 16) if value.startswith(("0x", "0X")) else int(float(value))
    except (TypeError, ValueError):
        return default


def parse_float(value: str | None, default: float = 0.0) -> float:
    try:
        parsed = float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def float_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_boulder_damage_ranks() -> list[float]:
    text = BOULDER_CONFIG.read_text(encoding="utf-8")
    match = re.search(r"mDamage\s*=\s*\{([^}]*)\}", text)
    if match is None:
        raise local_sync.VerifyFailure(
            f"mDamage row missing from {BOULDER_CONFIG}"
        )
    return [
        float(value.strip())
        for value in match.group(1).split(",")
        if value.strip()
    ]


def configure_modules(
    host_pipe: str,
    client_pipe: str,
    host_log: Path,
    client_log: Path,
) -> None:
    local_sync.HOST_PIPE = host_pipe
    local_sync.CLIENT_PIPE = client_pipe
    kill.HOST_PIPE = host_pipe
    kill.CLIENT_PIPE = client_pipe
    kill.HOST_LOG = host_log
    kill.CLIENT_LOG = client_log


def arm_observations(pipe_name: str) -> dict[str, str]:
    result = values(
        pipe_name,
        "print('ok=' .. tostring("
        "sd.debug.reset_earth_boulder_damage_observations()))",
    )
    if result.get("ok") != "true":
        raise local_sync.VerifyFailure(
            f"failed to arm Earth damage telemetry on {pipe_name}: {result}"
        )
    return result


def take_observations(pipe_name: str) -> list[dict[str, Any]]:
    integer_keys = "{" + ",".join(
        json.dumps(field) for field in INTEGER_TRACE_FIELDS
    ) + "}"
    float_keys = "{" + ",".join(
        json.dumps(field) for field in FLOAT_TRACE_FIELDS
    ) + "}"
    code = f"""
local rows = sd.debug.take_earth_boulder_damage_observations()
local integer_keys = {integer_keys}
local float_keys = {float_keys}
local function emit(key, value) print(key .. "=" .. tostring(value)) end
emit("count", #rows)
for index, row in ipairs(rows) do
  local prefix = tostring(index) .. "."
  emit(prefix .. "valid", row.valid == true)
  for _, key in ipairs(integer_keys) do
    emit(prefix .. key, row[key] or 0)
  end
  for _, key in ipairs(float_keys) do
    emit(prefix .. key, row[key] or 0)
    emit(prefix .. key .. "_bits", row[key .. "_bits"] or 0)
  end
end
"""
    raw = values(pipe_name, code, timeout=10.0)
    count = parse_int(raw.get("count"))
    rows: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        prefix = f"{index}."
        row: dict[str, Any] = {
            "valid": raw.get(prefix + "valid") == "true",
        }
        for field in INTEGER_TRACE_FIELDS:
            row[field] = parse_int(raw.get(prefix + field))
        for field in FLOAT_TRACE_FIELDS:
            row[field] = parse_float(raw.get(prefix + field))
            row[field + "_bits"] = parse_int(
                raw.get(prefix + field + "_bits")
            )
        rows.append(row)
    return rows


def exact_target_state(
    pipe_name: str,
    actor_address: int,
) -> dict[str, Any]:
    result = values(
        pipe_name,
        f"""
local actor = {actor_address}
local hp_offset = sd.debug.layout_offset("enemy_current_hp")
local max_hp_offset = sd.debug.layout_offset("enemy_max_hp")
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local hp = sd.debug.read_float(actor + hp_offset)
local max_hp = sd.debug.read_float(actor + max_hp_offset)
emit("hp", hp)
emit("hp_bits", sd.debug.read_u32(actor + hp_offset))
emit("max_hp", max_hp)
emit("max_hp_bits", sd.debug.read_u32(actor + max_hp_offset))
""",
    )
    return {
        "actor_address": actor_address,
        "hp": parse_float(result.get("hp")),
        "hp_bits": parse_int(result.get("hp_bits")),
        "max_hp": parse_float(result.get("max_hp")),
        "max_hp_bits": parse_int(result.get("max_hp_bits")),
    }


def wait_for_exact_convergence(
    host_pipe: str,
    client_pipe: str,
    host_actor: int,
    client_actor: int,
    initial_hp_bits: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    stable_bits: int | None = None
    samples: list[dict[str, Any]] = []
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        host = exact_target_state(host_pipe, host_actor)
        client = exact_target_state(client_pipe, client_actor)
        last = {"host": host, "client": client}
        samples.append(last)
        if len(samples) > 12:
            samples.pop(0)
        now = time.monotonic()
        converged_bits = host["hp_bits"]
        if (
            converged_bits != initial_hp_bits
            and converged_bits == client["hp_bits"]
        ):
            if stable_bits != converged_bits:
                stable_bits = converged_bits
                stable_since = now
            elif stable_since is not None and now - stable_since >= 1.0:
                return {
                    "host": host,
                    "client": client,
                    "stable_seconds": now - stable_since,
                    "tail_samples": samples,
                }
        else:
            stable_bits = None
            stable_since = None
        time.sleep(0.15)
    raise local_sync.VerifyFailure(
        "target HP did not reach exact peer convergence after native Earth "
        f"contact: last={last} tail={samples}"
    )


def decompose_observation(
    observation: dict[str, Any],
    damage_ranks: list[float],
) -> dict[str, Any]:
    rank = int(observation["effective_rank"])
    if rank < 0 or rank >= len(damage_ranks):
        configured_damage = math.nan
    else:
        configured_damage = damage_ranks[rank]

    additive = (
        observation["progression_base_additive"]
        + configured_damage
        + observation["progression_global_flat"]
        + observation["progression_spell_flat"]
        + observation["progression_class_flat"]
    )
    computed_actor_damage = float32(
        additive
        * observation["progression_global_multiplier"]
        * observation["progression_spell_multiplier"]
        * observation["progression_class_multiplier"]
        * observation["progression_siege_multiplier"]
    )
    actor_damage = observation["actor_stat_damage"]
    release_base = observation["release_base_damage"]
    early_base = float32(actor_damage * 0.5)
    full_base = actor_damage
    loader_scaled_base = float32(actor_damage * 1956.0)
    if observation["release_base_damage_bits"] == float_bits(early_base):
        release_path = "stock_early_half"
    elif observation["release_base_damage_bits"] == float_bits(full_base):
        release_path = "stock_full_unhalved"
    elif observation["release_base_damage_bits"] == float_bits(
        loader_scaled_base
    ):
        release_path = "loader_1956_overwrite"
    else:
        release_path = "unresolved"

    expected_pool = float32(
        max(
            0.25,
            min(
                release_base
                * observation["charge"]
                * observation["charge"],
                release_base * 1.25,
            ),
        )
    )
    payload = min(
        observation["target_hp_before"],
        observation["release_damage_pool"],
    )
    expected_lane = float32(payload * 0.5)
    expected_hp_single_store = float32(
        observation["target_hp_before"]
        - observation["damage_lane_primary"]
        - observation["damage_lane_secondary"]
    )
    expected_hp_lane_stores = float32(
        float32(
            observation["target_hp_before"]
            - observation["damage_lane_primary"]
        )
        - observation["damage_lane_secondary"]
    )
    hp_after_bits = observation["target_hp_after_bits"]
    if hp_after_bits == float_bits(expected_hp_single_store):
        hp_store_path = "single_final_store"
    elif hp_after_bits == float_bits(expected_hp_lane_stores):
        hp_store_path = "lane_store_rounding"
    elif observation["hp_delta_bits"] == 0:
        hp_store_path = "contact_suppressed"
    else:
        hp_store_path = "unresolved"

    value_bits_exact = all(
        observation[field + "_bits"] == float_bits(observation[field])
        for field in FLOAT_TRACE_FIELDS
    )
    configured_rank_exact = (
        math.isfinite(configured_damage)
        and observation["configured_rank_damage_bits"]
        == float_bits(configured_damage)
    )
    actor_formula_exact = (
        observation["actor_stat_damage_bits"]
        == float_bits(computed_actor_damage)
    )
    release_pool_exact = (
        observation["release_damage_pool_bits"]
        == float_bits(expected_pool)
    )
    lanes_exact = (
        observation["damage_lane_primary_bits"]
        == float_bits(expected_lane)
        and observation["damage_lane_secondary_bits"]
        == float_bits(expected_lane)
    )
    applied = observation["hp_delta_bits"] != 0
    endpoint_exact = not applied or hp_store_path in {
        "single_final_store",
        "lane_store_rounding",
    }
    return {
        "configured_rank_damage_from_boulder_cfg": configured_damage,
        "configured_rank_exact": configured_rank_exact,
        "additive_sum": additive,
        "computed_actor_stat_damage": computed_actor_damage,
        "computed_actor_stat_damage_bits": float_bits(computed_actor_damage),
        "actor_formula_exact": actor_formula_exact,
        "release_multiplier": (
            release_base / actor_damage if actor_damage != 0 else math.nan
        ),
        "release_path": release_path,
        "expected_release_damage_pool": expected_pool,
        "expected_release_damage_pool_bits": float_bits(expected_pool),
        "release_pool_exact": release_pool_exact,
        "expected_contact_lane": expected_lane,
        "expected_contact_lane_bits": float_bits(expected_lane),
        "contact_lanes_exact": lanes_exact,
        "expected_hp_after_single_store": expected_hp_single_store,
        "expected_hp_after_single_store_bits": float_bits(
            expected_hp_single_store
        ),
        "expected_hp_after_lane_stores": expected_hp_lane_stores,
        "expected_hp_after_lane_stores_bits": float_bits(
            expected_hp_lane_stores
        ),
        "hp_store_path": hp_store_path,
        "contact_applied": applied,
        "endpoint_exact": endpoint_exact,
        "value_bits_exact": value_bits_exact,
        "exact": (
            observation["valid"]
            and value_bits_exact
            and configured_rank_exact
            and actor_formula_exact
            and release_pool_exact
            and lanes_exact
            and endpoint_exact
            and release_path != "unresolved"
        ),
    }


def trace_log_lines(path: Path, offset: int) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        return [
            line.rstrip()
            for line in handle
            if "[earth-damage-trace]" in line
        ]


def run_cell(
    *,
    condition: str,
    frames: int,
    caster_peer: str,
    host_pipe: str,
    client_pipe: str,
    host_log: Path,
    client_log: Path,
    host_pid: int,
    client_pid: int,
    damage_ranks: list[float],
) -> dict[str, Any]:
    stage(f"{condition} {caster_peer}: quiescing and spawning fixture")
    quiesce = kill.quiesce_gameplay_primary_input(
        f"{condition}.{caster_peer}"
    )
    cleanup = kill.cleanup_live_enemies()
    enemy = kill.spawn_one_enemy(
        TARGET_X,
        TARGET_Y,
        setup_hp=TARGET_HP,
        freeze_on_spawn=True,
        native_type_id=SKELETON_TYPE_ID,
    )
    network_actor_id = int(enemy["network_actor_id"])
    bindings = {
        "host": kill.find_target(
            host_pipe,
            TARGET_X,
            TARGET_Y,
            network_actor_id,
        ),
        "client": kill.find_target(
            client_pipe,
            TARGET_X,
            TARGET_Y,
            network_actor_id,
        ),
    }
    actor_addresses = {
        peer: parse_int(binding.get("local.actor_address"))
        for peer, binding in bindings.items()
    }
    if any(address == 0 for address in actor_addresses.values()):
        raise local_sync.VerifyFailure(
            f"exact target binding missing: {bindings}"
        )

    source_pipe = host_pipe if caster_peer == "host" else client_pipe
    receiver_pipe = client_pipe if caster_peer == "host" else host_pipe
    source_log = host_log if caster_peer == "host" else client_log
    receiver_log = client_log if caster_peer == "host" else host_log
    source_pid = host_pid if caster_peer == "host" else client_pid
    source_id = (
        local_sync.HOST_ID
        if caster_peer == "host"
        else local_sync.CLIENT_ID
    )
    source_name = (
        local_sync.HOST_NAME
        if caster_peer == "host"
        else local_sync.CLIENT_NAME
    )
    direction = Direction(
        f"{caster_peer}_casts",
        source_id,
        source_name,
        source_pipe,
        source_log,
        source_pid,
        receiver_pipe,
        receiver_log,
    )

    source_place = local_sync.place_player(
        source_pipe,
        CASTER_X,
        TARGET_Y,
        90.0,
    )
    observer_place = local_sync.place_player(
        receiver_pipe,
        OBSERVER_X,
        OBSERVER_Y,
        270.0,
    )
    time.sleep(1.0)
    bindings = {
        "host": kill.find_target(
            host_pipe,
            TARGET_X,
            TARGET_Y,
            network_actor_id,
        ),
        "client": kill.find_target(
            client_pipe,
            TARGET_X,
            TARGET_Y,
            network_actor_id,
        ),
    }
    actor_addresses = {
        peer: parse_int(binding.get("local.actor_address"))
        for peer, binding in bindings.items()
    }
    before = {
        "host": exact_target_state(
            host_pipe,
            actor_addresses["host"],
        ),
        "client": exact_target_state(
            client_pipe,
            actor_addresses["client"],
        ),
    }
    if (
        before["host"]["hp_bits"] != float_bits(TARGET_HP)
        or before["client"]["hp_bits"] != float_bits(TARGET_HP)
    ):
        raise local_sync.VerifyFailure(
            f"fixture HP was not pinned to {TARGET_HP}: {before}"
        )

    host_log_offset = host_log.stat().st_size if host_log.exists() else 0
    client_log_offset = client_log.stat().st_size if client_log.exists() else 0
    armed = {
        "host": arm_observations(host_pipe),
        "client": arm_observations(client_pipe),
    }
    source_target_actor = actor_addresses[caster_peer]
    queued = kill.prepare_and_queue_caster(
        direction,
        source_target_actor,
        TARGET_X,
        TARGET_Y,
        frames,
    )
    timeout = 24.0 if frames >= 900 else 14.0
    convergence = wait_for_exact_convergence(
        host_pipe,
        client_pipe,
        actor_addresses["host"],
        actor_addresses["client"],
        float_bits(TARGET_HP),
        timeout,
    )
    observations = {
        "host": take_observations(host_pipe),
        "client": take_observations(client_pipe),
    }
    for peer_rows in observations.values():
        for observation in peer_rows:
            observation["formula"] = decompose_observation(
                observation,
                damage_ranks,
            )
    clear = {
        "host": kill.clear_gameplay_mouse_left(host_pipe),
        "client": kill.clear_gameplay_mouse_left(client_pipe),
    }
    endpoint_delta = float32(
        TARGET_HP - convergence["host"]["hp"]
    )
    result = {
        "condition": condition,
        "hold_frames": frames,
        "caster_peer": caster_peer,
        "fixture": {
            "native_type_id": SKELETON_TYPE_ID,
            "network_actor_id": network_actor_id,
            "x": TARGET_X,
            "y": TARGET_Y,
            "initial_hp": TARGET_HP,
            "initial_hp_bits": float_bits(TARGET_HP),
            "frozen": True,
        },
        "quiesce": quiesce,
        "cleanup": cleanup,
        "spawn": enemy,
        "bindings": bindings,
        "placement": {
            "source": source_place,
            "observer": observer_place,
        },
        "before": before,
        "armed": armed,
        "queued": queued,
        "convergence": convergence,
        "endpoint": {
            "host_hp": convergence["host"]["hp"],
            "host_hp_bits": convergence["host"]["hp_bits"],
            "client_hp": convergence["client"]["hp"],
            "client_hp_bits": convergence["client"]["hp_bits"],
            "damage": endpoint_delta,
            "damage_bits": float_bits(endpoint_delta),
            "exact_peer_convergence": (
                convergence["host"]["hp_bits"]
                == convergence["client"]["hp_bits"]
            ),
        },
        "observations": observations,
        "trace_log_lines": {
            "host": trace_log_lines(host_log, host_log_offset),
            "client": trace_log_lines(
                client_log,
                client_log_offset,
            ),
        },
        "clear": clear,
    }
    formula_rows = [
        row["formula"]
        for rows in observations.values()
        for row in rows
    ]
    result["formula_exact"] = bool(formula_rows) and all(
        row["exact"] for row in formula_rows
    )
    result["loader_1956_overwrite_observed"] = any(
        row["release_path"] == "loader_1956_overwrite"
        for row in formula_rows
    )
    stage(
        f"{condition} {caster_peer}: damage={endpoint_delta} "
        f"bits=0x{float_bits(endpoint_delta):08X} "
        f"traces={sum(len(rows) for rows in observations.values())}"
    )
    return result


def compare_matrix(
    cells: list[dict[str, Any]],
    phase: str,
    baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    by_key = {
        (cell["condition"], cell["caster_peer"]): cell
        for cell in cells
    }
    conditions: dict[str, Any] = {}
    for condition, _ in CONDITIONS:
        host = by_key[(condition, "host")]
        client = by_key[(condition, "client")]
        conditions[condition] = {
            "host_damage": host["endpoint"]["damage"],
            "host_damage_bits": host["endpoint"]["damage_bits"],
            "client_damage": client["endpoint"]["damage"],
            "client_damage_bits": client["endpoint"]["damage_bits"],
            "exact_equal": (
                host["endpoint"]["damage_bits"]
                == client["endpoint"]["damage_bits"]
            ),
            "ratio": (
                client["endpoint"]["damage"]
                / host["endpoint"]["damage"]
                if host["endpoint"]["damage"] != 0
                else math.inf
            ),
        }

    host_scaled = any(
        cell["loader_1956_overwrite_observed"]
        for cell in cells
        if cell["caster_peer"] == "host"
    )
    client_scaled = any(
        cell["loader_1956_overwrite_observed"]
        for cell in cells
        if cell["caster_peer"] == "client"
    )
    formula_exact = all(cell["formula_exact"] for cell in cells)
    exact_peer_convergence = all(
        cell["endpoint"]["exact_peer_convergence"]
        for cell in cells
    )
    client_only_inflation = (
        client_scaled
        and not host_scaled
        and any(
            row["ratio"] > 100.0
            for row in conditions.values()
        )
    )
    no_scaled_release = not host_scaled and not client_scaled
    control_equality = all(
        conditions[name]["exact_equal"]
        for name in ("instant_release", "fully_held")
    )

    host_baseline_unchanged: dict[str, bool] = {}
    if baseline is not None:
        baseline_by_key = {
            (cell["condition"], cell["caster_peer"]): cell
            for cell in baseline.get("cells", [])
        }
        for condition in ("instant_release", "fully_held"):
            previous = baseline_by_key.get((condition, "host"))
            host_baseline_unchanged[condition] = (
                previous is not None
                and previous["endpoint"]["damage_bits"]
                == by_key[(condition, "host")]["endpoint"]["damage_bits"]
            )

    if phase == "pre-fix":
        phase_ok = (
            formula_exact
            and exact_peer_convergence
            and client_only_inflation
        )
        verdict = "CLIENT-ONLY INFLATION"
    else:
        phase_ok = (
            formula_exact
            and exact_peer_convergence
            and no_scaled_release
            and control_equality
            and bool(host_baseline_unchanged)
            and all(host_baseline_unchanged.values())
        )
        verdict = "CLIENT-ONLY INFLATION FIXED"

    return {
        "phase": phase,
        "verdict": verdict,
        "conditions": conditions,
        "formula_exact": formula_exact,
        "exact_peer_convergence": exact_peer_convergence,
        "host_scaled_release_observed": host_scaled,
        "client_scaled_release_observed": client_scaled,
        "client_only_inflation": client_only_inflation,
        "no_scaled_release": no_scaled_release,
        "instant_and_full_exact_equality": control_equality,
        "host_baseline_unchanged": host_baseline_unchanged,
        "ok": phase_ok,
    }


def write_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=("pre-fix", "post-fix"),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument(
        "--instance-prefix",
        default=REQUIRED_INSTANCE_PREFIX,
    )
    parser.add_argument("--host-port", type=int, default=REQUIRED_HOST_PORT)
    parser.add_argument(
        "--client-port",
        type=int,
        default=REQUIRED_CLIENT_PORT,
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if (
        args.instance_prefix != REQUIRED_INSTANCE_PREFIX
        or args.host_port != REQUIRED_HOST_PORT
        or args.client_port != REQUIRED_CLIENT_PORT
    ):
        raise ValueError(
            "this verifier is locked to instance prefix edmg and ports "
            "48911/48912"
        )
    runtime_root = args.runtime_root.resolve()
    if not runtime_root.is_relative_to(REQUIRED_RUNTIME_PARENT.resolve()):
        raise ValueError(
            "runtime root must stay under "
            f"{REQUIRED_RUNTIME_PARENT}"
        )
    if args.phase == "post-fix" and args.baseline is None:
        raise ValueError("post-fix verification requires --baseline")


def main() -> int:
    args = parse_args()
    result: dict[str, Any] = {
        "ok": False,
        "phase": args.phase,
        "instance_prefix": args.instance_prefix,
        "ports": [args.host_port, args.client_port],
        "audio_required": False,
        "audio_enabled": False,
        "cells": [],
    }
    expected: dict[int, Path] = {}
    try:
        validate_args(args)
        damage_ranks = read_boulder_damage_ranks()
        result["stock_config"] = {
            "path": str(BOULDER_CONFIG),
            "sha256": sha256(BOULDER_CONFIG),
            "mDamage": damage_ranks,
        }
        result["build"] = {
            "loader": str(ROOT / "bin/Release/Win32/SolomonDarkModLoader.dll"),
            "loader_sha256": sha256(
                ROOT / "bin/Release/Win32/SolomonDarkModLoader.dll"
            ),
            "binary_layout": str(ROOT / "config/binary-layout.ini"),
            "binary_layout_sha256": sha256(
                ROOT / "config/binary-layout.ini"
            ),
            "retail_exe_sha256": sha256(
                GAME_DIRECTORY / "SolomonDark.exe"
            ),
        }
        stage("launching isolated edmg pair with audio disabled")
        pair = local_sync.launch_pair(
            host_preset="map_create_earth_mind_hub",
            client_preset="map_create_earth_mind_hub",
            tile_windows=False,
            kill_existing=False,
            instance_prefix=args.instance_prefix,
            host_port=args.host_port,
            client_port=args.client_port,
            game_directory=GAME_DIRECTORY,
            runtime_root=args.runtime_root.resolve(),
            exact_mod_id="sample.lua.ui_sandbox_lab",
            enable_audio=False,
            god_mode=True,
            test_blank_boneyard=True,
            test_survival_boneyard_override=FLAT_BONEYARD,
            use_sandbox_preset_flow=True,
        )
        if pair.get("audioDisabled") is not True:
            raise local_sync.VerifyFailure(
                f"launcher did not confirm disabled audio: {pair}"
            )
        if (
            pair.get("instancePrefix") != REQUIRED_INSTANCE_PREFIX
            or int(pair.get("hostPort", 0)) != REQUIRED_HOST_PORT
            or int(pair.get("clientPort", 0)) != REQUIRED_CLIENT_PORT
        ):
            raise local_sync.VerifyFailure(
                f"launcher violated the locked instance contract: {pair}"
            )
        process_ids = local_sync.game_process_ids(pair)
        if len(process_ids) != 2:
            raise local_sync.VerifyFailure(
                f"launcher did not return exactly two game PIDs: {pair}"
            )
        expected = {
            int(pair["hostProcessId"]): audio.expected_executable(
                args.runtime_root,
                f"{args.instance_prefix}-host",
            ),
            int(pair["clientProcessId"]): audio.expected_executable(
                args.runtime_root,
                f"{args.instance_prefix}-client",
            ),
        }
        audio.validate_owned_processes(expected)
        host_pipe = str(pair["hostLuaPipe"])
        client_pipe = str(pair["clientLuaPipe"])
        host_log = (
            args.runtime_root
            / "instances"
            / f"{args.instance_prefix}-host"
            / "stage/.sdmod/logs/solomondarkmodloader.log"
        )
        client_log = (
            args.runtime_root
            / "instances"
            / f"{args.instance_prefix}-client"
            / "stage/.sdmod/logs/solomondarkmodloader.log"
        )
        configure_modules(
            host_pipe,
            client_pipe,
            host_log,
            client_log,
        )
        result["launch"] = pair
        result["owned_processes"] = {
            str(process_id): str(path)
            for process_id, path in expected.items()
        }
        local_sync.wait_for_remote(
            host_pipe,
            local_sync.CLIENT_ID,
            local_sync.CLIENT_NAME,
            "hub",
        )
        local_sync.wait_for_remote(
            client_pipe,
            local_sync.HOST_ID,
            local_sync.HOST_NAME,
            "hub",
        )
        local_sync.disable_bots()
        result["manual_spawner_prearm"] = {
            "host": kill.set_manual_spawner_test_mode(host_pipe, True),
            "client": kill.set_manual_spawner_test_mode(client_pipe, True),
        }
        result["run_entry"] = (
            local_sync.start_host_testrun_and_wait_for_clients(
                timeout=45.0
            )
        )
        local_sync.wait_for_remote(
            host_pipe,
            local_sync.CLIENT_ID,
            local_sync.CLIENT_NAME,
            "testrun",
        )
        local_sync.wait_for_remote(
            client_pipe,
            local_sync.HOST_ID,
            local_sync.HOST_NAME,
            "testrun",
        )
        result["vitals"] = {
            "host": set_local_player_vitals(
                host_pipe,
                PLAYER_HP,
                PLAYER_HP,
            ),
            "client": set_local_player_vitals(
                client_pipe,
                PLAYER_HP,
                PLAYER_HP,
            ),
        }
        result["combat"] = kill.enable_manual_stock_spawner_combat()
        write_result(args.output, result)

        host_pid = int(pair["hostProcessId"])
        client_pid = int(pair["clientProcessId"])
        for condition, frames in CONDITIONS:
            for caster_peer in ("host", "client"):
                cell = run_cell(
                    condition=condition,
                    frames=frames,
                    caster_peer=caster_peer,
                    host_pipe=host_pipe,
                    client_pipe=client_pipe,
                    host_log=host_log,
                    client_log=client_log,
                    host_pid=host_pid,
                    client_pid=client_pid,
                    damage_ranks=damage_ranks,
                )
                result["cells"].append(cell)
                write_result(args.output, result)

        baseline = None
        if args.baseline is not None:
            baseline = json.loads(
                args.baseline.read_text(encoding="utf-8")
            )
        result["matrix"] = compare_matrix(
            result["cells"],
            args.phase,
            baseline,
        )
        result["ok"] = result["matrix"]["ok"]
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if expected:
            try:
                result["cleanup"] = audio.stop_owned_processes(expected)
            except Exception as exc:
                result["cleanup_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                result["ok"] = False
        write_result(args.output, result)
        print(
            json.dumps(
                {
                    "ok": result.get("ok"),
                    "phase": result.get("phase"),
                    "cell_count": len(result.get("cells", [])),
                    "verdict": result.get("matrix", {}).get("verdict"),
                    "error": result.get("error"),
                    "output": str(args.output),
                },
                indent=2,
                sort_keys=True,
            ),
            flush=True,
        )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
