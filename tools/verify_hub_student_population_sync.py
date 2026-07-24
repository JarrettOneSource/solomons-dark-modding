#!/usr/bin/env python3
"""Verify that a connected client does not retain a second hub Student pool."""

from __future__ import annotations

import argparse
import json
import os
import time
import traceback
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from multiplayer_lua_probe import run_all
from verify_local_multiplayer_sync import (
    ROOT,
    VerifyFailure,
    game_process_ids,
    launch_pair,
    select_available_windows_udp_ports,
    stop_game_processes,
)


DEFAULT_OUTPUT = ROOT / "runtime" / "hub_student_population_sync.json"
ACCEPTANCE_MOD_ID = "sample.lua.ui_sandbox_lab"
DEFAULT_WARMUP_SAMPLES = 3
DEFAULT_CONVERGENCE_TIMEOUT = 30.0
DEFAULT_CONFIRMATION_SAMPLES = 3


LUA_CAPTURE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end

local student_type = 0x138A
local owner_offset = sd.debug.layout_offset("actor_owner")
local pending_offset = sd.debug.layout_offset("actor_pending_remove")
local student_count_offset = sd.debug.layout_offset("hub_student_count")
local actors = sd.world.list_actors() or {}
local registered_students = 0
local pending_students = 0
local owner_address = 0
local active_addresses = {}

for _, actor in ipairs(actors) do
  local address = tonumber(actor.actor_address) or 0
  if tonumber(actor.object_type_id) == student_type and address ~= 0 then
    registered_students = registered_students + 1
    local pending =
      (tonumber(sd.debug.read_u8(address + pending_offset)) or 0) ~= 0
    if pending then
      pending_students = pending_students + 1
    else
      active_addresses[address] = true
    end
    if owner_address == 0 then
      owner_address =
        tonumber(sd.debug.read_u32(address + owner_offset)) or 0
    end
  end
end

local replicated =
  sd.world.get_replicated_actors and
  sd.world.get_replicated_actors() or nil
local authoritative_students = 0
local bound_students = 0
local authoritative_student_ids = {}
local bound_student_ids = {}
local bound_student_id_set = {}
if replicated ~= nil then
  local authority = replicated.apply_actors_available and
    replicated.apply_actors or replicated.actors or {}
  for _, actor in ipairs(authority) do
    if tonumber(actor.object_type_id) == student_type then
      authoritative_students = authoritative_students + 1
      table.insert(
        authoritative_student_ids,
        tonumber(actor.network_actor_id) or 0)
    end
  end
  for _, binding in ipairs(replicated.bindings or {}) do
    local address = tonumber(binding.local_actor_address) or 0
    if tonumber(binding.object_type_id) == student_type and
        binding.matched and not binding.parked and not binding.removed and
        active_addresses[address] then
      bound_students = bound_students + 1
      local network_actor_id = tonumber(binding.network_actor_id) or 0
      table.insert(bound_student_ids, network_actor_id)
      bound_student_id_set[network_actor_id] = true
    end
  end
end

table.sort(authoritative_student_ids)
table.sort(bound_student_ids)
local missing_student_ids = {}
for _, network_actor_id in ipairs(authoritative_student_ids) do
  if not bound_student_id_set[network_actor_id] then
    table.insert(missing_student_ids, network_actor_id)
  end
end

local active_students = registered_students - pending_students
emit("scene", (sd.world.get_scene() or {}).name or "")
emit("registered_students", registered_students)
emit("pending_students", pending_students)
emit("active_students", active_students)
emit(
  "stock_student_count",
  owner_address ~= 0 and
    (tonumber(sd.debug.read_i32(
      owner_address + student_count_offset)) or -1) or -1)
emit("authoritative_students", authoritative_students)
emit("bound_students", bound_students)
emit("unbound_students", math.max(active_students - bound_students, 0))
emit("authoritative_student_ids", table.concat(authoritative_student_ids, ","))
emit("bound_student_ids", table.concat(bound_student_ids, ","))
emit("missing_student_ids", table.concat(missing_student_ids, ","))
emit("sampled_ms", replicated and replicated.sampled_ms or 0)
emit("snapshot_sequence", replicated and replicated.sequence or 0)
emit("apply_sequence", replicated and replicated.apply_sequence or 0)
emit(
  "apply_source_snapshot_age_ms",
  replicated and replicated.apply_source_snapshot_age_ms or 0)
emit(
  "removed_actor_total_count",
  replicated and replicated.removed_actor_total_count or 0)
emit(
  "failed_remove_actor_total_count",
  replicated and replicated.failed_remove_actor_total_count or 0)
"""


def _reserve_udp_port() -> int:
    return select_available_windows_udp_ports(1)[0]


def _default_instance_prefix() -> str:
    return f"hs-{os.getpid():x}-{uuid.uuid4().hex[:4]}"


def _int(values: Mapping[str, str], key: str) -> int:
    raw = values.get(key, "")
    try:
        return int(raw, 0)
    except (TypeError, ValueError):
        try:
            return int(float(raw))
        except (TypeError, ValueError, OverflowError) as exc:
            raise VerifyFailure(
                f"hub Student probe returned invalid {key}: {raw!r}"
            ) from exc


def _int_list(values: Mapping[str, str], key: str) -> list[int]:
    raw = values.get(key, "")
    if not raw:
        return []
    try:
        return [int(value, 0) for value in raw.split(",")]
    except ValueError as exc:
        raise VerifyFailure(
            f"hub Student probe returned invalid {key}: {raw!r}"
        ) from exc


def _parse_endpoint(row: Mapping[str, object]) -> dict[str, object]:
    name = str(row.get("name", "unknown"))
    if row.get("returncode") != 0:
        raise VerifyFailure(
            f"{name} hub Student probe failed: "
            f"{row.get('stderr') or row.get('stdout')}"
        )
    raw_values = row.get("values")
    if not isinstance(raw_values, Mapping):
        raise VerifyFailure(f"{name} hub Student probe returned no values")
    values = {str(key): str(value) for key, value in raw_values.items()}
    return {
        "scene": values.get("scene", ""),
        "registered_students": _int(values, "registered_students"),
        "pending_students": _int(values, "pending_students"),
        "active_students": _int(values, "active_students"),
        "stock_student_count": _int(values, "stock_student_count"),
        "authoritative_students": _int(
            values,
            "authoritative_students",
        ),
        "bound_students": _int(values, "bound_students"),
        "unbound_students": _int(values, "unbound_students"),
        "authoritative_student_ids": _int_list(
            values,
            "authoritative_student_ids",
        ),
        "bound_student_ids": _int_list(values, "bound_student_ids"),
        "missing_student_ids": _int_list(values, "missing_student_ids"),
        "sampled_ms": _int(values, "sampled_ms"),
        "snapshot_sequence": _int(values, "snapshot_sequence"),
        "apply_sequence": _int(values, "apply_sequence"),
        "apply_source_snapshot_age_ms": _int(
            values,
            "apply_source_snapshot_age_ms",
        ),
        "removed_actor_total_count": _int(
            values,
            "removed_actor_total_count",
        ),
        "failed_remove_actor_total_count": _int(
            values,
            "failed_remove_actor_total_count",
        ),
    }


def capture_sample(
    clients: list[tuple[str, str]],
    *,
    index: int,
    timeout: float,
) -> dict[str, object]:
    rows = run_all(clients, LUA_CAPTURE, timeout)
    endpoints = {
        str(row.get("name", "unknown")): _parse_endpoint(row)
        for row in rows
    }
    if set(endpoints) != {"host", "client"}:
        raise VerifyFailure(
            f"hub Student probe did not return host and client: {endpoints}"
        )
    return {
        "index": index,
        "host": endpoints["host"],
        "client": endpoints["client"],
    }


def evaluate_samples(
    samples: Sequence[Mapping[str, object]],
    *,
    warmup_samples: int = DEFAULT_WARMUP_SAMPLES,
    confirmation_samples: int = DEFAULT_CONFIRMATION_SAMPLES,
    require_retirement: bool = True,
    require_convergence: bool = True,
) -> dict[str, object]:
    if warmup_samples < 0:
        raise ValueError("warmup_samples must not be negative")
    if confirmation_samples <= 0:
        raise ValueError("confirmation_samples must be positive")
    if len(samples) <= warmup_samples:
        raise VerifyFailure(
            "hub Student verifier has no post-warmup samples"
        )

    stable_samples = samples[warmup_samples:]
    client_surpluses: list[int] = []
    population_gaps: list[int] = []
    unbound_counts: list[int] = []
    missing_counts: list[int] = []
    removal_totals: list[int] = []
    converged_count = 0
    binding_converged_count = 0
    consecutive_converged = 0
    maximum_consecutive_converged = 0

    for sample in stable_samples:
        index = int(sample.get("index", -1))
        host = sample.get("host")
        client = sample.get("client")
        if not isinstance(host, Mapping) or not isinstance(client, Mapping):
            raise VerifyFailure(
                f"sample {index} does not contain host and client state"
            )

        for label, endpoint in (("host", host), ("client", client)):
            if endpoint.get("scene") != "hub":
                raise VerifyFailure(
                    f"sample {index} {label} left the shared hub"
                )
            registered = int(endpoint["registered_students"])
            pending = int(endpoint["pending_students"])
            active = int(endpoint["active_students"])
            stock_count = int(endpoint["stock_student_count"])
            if registered <= 0 or pending < 0 or pending > registered:
                raise VerifyFailure(
                    f"sample {index} {label} has an invalid Student pool"
                )
            if active != registered - pending:
                raise VerifyFailure(
                    f"sample {index} {label} active Student count is incoherent"
                )
            if stock_count != active:
                raise VerifyFailure(
                    f"sample {index} {label} stock Student counter "
                    f"{stock_count} does not match active population {active}"
                )
            if int(endpoint["failed_remove_actor_total_count"]) != 0:
                raise VerifyFailure(
                    f"sample {index} {label} recorded a failed retirement"
                )

        client_active = int(client["active_students"])
        authoritative = int(client["authoritative_students"])
        bound = int(client["bound_students"])
        unbound = int(client["unbound_students"])
        if authoritative <= 0 or bound < 0:
            raise VerifyFailure(
                f"sample {index} lacks an authoritative Student population"
            )
        if bound > client_active or unbound != client_active - bound:
            raise VerifyFailure(
                f"sample {index} client Student binding counts are incoherent"
            )

        authoritative_ids = client.get("authoritative_student_ids")
        bound_ids = client.get("bound_student_ids")
        missing_ids = client.get("missing_student_ids")
        for label, identifiers in (
            ("authoritative", authoritative_ids),
            ("bound", bound_ids),
            ("missing", missing_ids),
        ):
            if (
                not isinstance(identifiers, Sequence)
                or isinstance(identifiers, (str, bytes))
                or any(
                    not isinstance(identifier, int) or identifier <= 0
                    for identifier in identifiers
                )
                or len(set(identifiers)) != len(identifiers)
            ):
                raise VerifyFailure(
                    f"sample {index} has invalid {label} Student identities"
                )
        assert isinstance(authoritative_ids, Sequence)
        assert isinstance(bound_ids, Sequence)
        assert isinstance(missing_ids, Sequence)
        authoritative_id_set = set(authoritative_ids)
        bound_id_set = set(bound_ids)
        missing_id_set = set(missing_ids)
        if len(authoritative_ids) != authoritative:
            raise VerifyFailure(
                f"sample {index} authoritative Student identities "
                "do not match the population count"
            )
        if len(bound_ids) != bound:
            raise VerifyFailure(
                f"sample {index} bound Student identities "
                "do not match the binding count"
            )
        if missing_id_set != authoritative_id_set - bound_id_set:
            raise VerifyFailure(
                f"sample {index} missing Student identities are incoherent"
            )

        surplus = client_active - authoritative
        gap = abs(client_active - authoritative)
        client_surpluses.append(surplus)
        population_gaps.append(gap)
        unbound_counts.append(unbound)
        missing_counts.append(len(missing_ids))
        removal_totals.append(
            int(client["removed_actor_total_count"])
        )
        population_converged = client_active == authoritative
        binding_converged = (
            bound == client_active
            and unbound == 0
            and authoritative_id_set == bound_id_set
            and not missing_ids
        )
        exactly_converged = (
            population_converged
            and binding_converged
            and int(client["pending_students"]) == 0
        )
        if population_converged:
            converged_count += 1
        if binding_converged:
            binding_converged_count += 1
        if exactly_converged:
            consecutive_converged += 1
            maximum_consecutive_converged = max(
                maximum_consecutive_converged,
                consecutive_converged,
            )
        else:
            consecutive_converged = 0

    if any(
        later < earlier
        for earlier, later in zip(removal_totals, removal_totals[1:])
    ):
        raise VerifyFailure(
            "hub Student retirement total regressed within one scene"
        )
    if require_retirement and max(removal_totals) <= 0:
        raise VerifyFailure(
            "the connected run did not exercise deferred Student retirement"
        )
    if (
        require_convergence
        and consecutive_converged < confirmation_samples
    ):
        raise VerifyFailure(
            "client Student population did not reach "
            f"{confirmation_samples} consecutive exact identity matches; "
            f"final gap {population_gaps[-1]}, "
            f"missing IDs {list(missing_ids)}, "
            f"unbound Students {unbound_counts[-1]}"
        )

    return {
        "sample_count": len(samples),
        "stable_sample_count": len(stable_samples),
        "converged_sample_count": converged_count,
        "binding_converged_sample_count": binding_converged_count,
        "maximum_client_surplus": max(
            max(surplus, 0)
            for surplus in client_surpluses
        ),
        "maximum_client_deficit": max(
            max(-surplus, 0)
            for surplus in client_surpluses
        ),
        "maximum_population_gap": max(population_gaps),
        "maximum_unbound_client_students": max(unbound_counts),
        "maximum_missing_student_ids": max(missing_counts),
        "final_population_gap": population_gaps[-1],
        "final_missing_student_ids": list(missing_ids),
        "consecutive_converged_sample_count": consecutive_converged,
        "maximum_consecutive_converged_sample_count": (
            maximum_consecutive_converged
        ),
        "required_confirmation_samples": confirmation_samples,
        "convergence_confirmed": (
            consecutive_converged >= confirmation_samples
        ),
        "student_retirement_total": max(removal_totals),
    }


def run_live_verification(
    *,
    convergence_timeout: float,
    confirmation_samples: int,
    warmup_samples: int,
    interval: float,
    timeout: float,
    instance_prefix: str,
    host_port: int,
    client_port: int,
    game_directory: Path | None,
) -> dict[str, object]:
    launch: dict[str, object] = {}
    process_ids: list[int] = []
    try:
        launch = launch_pair(
            tile_windows=False,
            allow_focus_steal=False,
            kill_existing=False,
            instance_prefix=instance_prefix,
            host_port=host_port,
            client_port=client_port,
            game_directory=game_directory,
            exact_mod_id=ACCEPTANCE_MOD_ID,
        )
        process_ids = game_process_ids(launch)
        if len(process_ids) != 2:
            raise VerifyFailure(
                "isolated hub Student pair did not report "
                f"two exact process IDs: {launch}"
            )

        clients = [
            ("host", str(launch["hostLuaPipe"])),
            ("client", str(launch["clientLuaPipe"])),
        ]
        samples: list[dict[str, object]] = []
        started_at = time.monotonic()
        deadline = started_at + convergence_timeout
        index = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sample = capture_sample(
                clients,
                index=index,
                timeout=min(timeout, remaining),
            )
            observed_at = time.monotonic()
            sample["elapsed_seconds"] = round(
                observed_at - started_at,
                3,
            )
            samples.append(sample)
            print(json.dumps(sample, sort_keys=True), flush=True)

            if len(samples) > warmup_samples:
                aggregate = evaluate_samples(
                    samples,
                    warmup_samples=warmup_samples,
                    confirmation_samples=confirmation_samples,
                    require_retirement=False,
                    require_convergence=False,
                )
                if (
                    observed_at <= deadline
                    and aggregate["convergence_confirmed"]
                    and aggregate["student_retirement_total"] > 0
                ):
                    aggregate = evaluate_samples(
                        samples,
                        warmup_samples=warmup_samples,
                        confirmation_samples=confirmation_samples,
                    )
                    return {
                        "ok": True,
                        "instance_prefix": instance_prefix,
                        "ports": [host_port, client_port],
                        "process_ids": process_ids,
                        "convergence_timeout_seconds": (
                            convergence_timeout
                        ),
                        "elapsed_seconds": sample["elapsed_seconds"],
                        "aggregate": aggregate,
                        "samples": samples,
                    }

            remaining = deadline - observed_at
            if remaining <= 0:
                break
            if interval > 0:
                time.sleep(min(interval, remaining))
            index += 1

        if len(samples) <= warmup_samples:
            error = (
                "hub Student verifier reached its convergence deadline "
                "without post-warmup samples"
            )
            aggregate = None
        else:
            aggregate = evaluate_samples(
                samples,
                warmup_samples=warmup_samples,
                confirmation_samples=confirmation_samples,
                require_retirement=False,
                require_convergence=False,
            )
            final_client = samples[-1]["client"]
            assert isinstance(final_client, Mapping)
            error = (
                "client Student population did not reach "
                f"{confirmation_samples} consecutive exact identity "
                f"matches within {convergence_timeout:g}s; "
                f"final gap {aggregate['final_population_gap']}, "
                f"missing IDs {aggregate['final_missing_student_ids']}, "
                f"unbound Students {final_client['unbound_students']}, "
                "retirement total "
                f"{aggregate['student_retirement_total']}"
            )
        return {
            "ok": False,
            "error": error,
            "instance_prefix": instance_prefix,
            "ports": [host_port, client_port],
            "process_ids": process_ids,
            "convergence_timeout_seconds": convergence_timeout,
            "elapsed_seconds": round(time.monotonic() - started_at, 3),
            "aggregate": aggregate,
            "samples": samples,
        }
    finally:
        stop_game_processes(process_ids or game_process_ids(launch))


def _optional_game_directory(raw: str | None) -> Path | None:
    if raw is None or not raw.strip():
        return None
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (ROOT / path).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--convergence-timeout",
        type=float,
        default=DEFAULT_CONVERGENCE_TIMEOUT,
    )
    parser.add_argument(
        "--confirmation-samples",
        type=int,
        default=DEFAULT_CONFIRMATION_SAMPLES,
    )
    parser.add_argument(
        "--warmup-samples",
        type=int,
        default=DEFAULT_WARMUP_SAMPLES,
    )
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--instance-prefix")
    parser.add_argument("--host-port", type=int)
    parser.add_argument("--client-port", type=int)
    parser.add_argument(
        "--game-dir",
        default=os.environ.get("SD_PROBE_GAME_DIR"),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if args.warmup_samples < 0:
        parser.error("--warmup-samples must not be negative")
    if args.confirmation_samples <= 0:
        parser.error("--confirmation-samples must be positive")
    if args.convergence_timeout <= 0:
        parser.error("--convergence-timeout must be positive")
    if args.interval < 0 or args.timeout <= 0:
        parser.error("--interval must be non-negative and --timeout positive")

    host_port = args.host_port or _reserve_udp_port()
    client_port = args.client_port or _reserve_udp_port()
    while client_port == host_port:
        client_port = _reserve_udp_port()

    result: dict[str, Any] = {"ok": False}
    return_code = 1
    try:
        result = run_live_verification(
            convergence_timeout=args.convergence_timeout,
            confirmation_samples=args.confirmation_samples,
            warmup_samples=args.warmup_samples,
            interval=args.interval,
            timeout=args.timeout,
            instance_prefix=args.instance_prefix or _default_instance_prefix(),
            host_port=host_port,
            client_port=client_port,
            game_directory=_optional_game_directory(args.game_dir),
        )
        return_code = 0 if result.get("ok") else 1
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "ok": result.get("ok", False),
                    "error": result.get("error"),
                    "aggregate": result.get("aggregate"),
                    "output": str(args.output),
                },
                sort_keys=True,
            )
        )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
