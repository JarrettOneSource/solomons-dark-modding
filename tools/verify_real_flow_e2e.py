#!/usr/bin/env python3
"""Drive and verify the owner-reported multiplayer flow without test seams."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools._real_flow_e2e.config import (  # noqa: E402
    ConfigError,
    HarnessConfig,
    LOCAL_WINDOWS,
)
from tools._real_flow_e2e.evidence import (  # noqa: E402
    EvidenceError,
    JsonlWriter,
    copy_runtime_artifacts,
    packet_accounting,
    paired_windows_capture,
    rendered_enemy_assertion,
    steam_transport_assertion,
    write_json,
    write_manifest,
)
from tools._real_flow_e2e.endurance import (  # noqa: E402
    EnduranceAnomalyMonitor,
    FighterStatsTracker,
    effective_wave as endurance_wave,
    is_capture_milestone,
    terminal_game_over,
)
from tools._real_flow_e2e.runtime import (  # noqa: E402
    LuaPipe,
    RuntimeProbeError,
    approach_solomon_and_complete_dialogue,
    cover_participant_with_real_input_once,
    damage_enemy_with_real_input,
    drive_combat_to_wave_with_real_input,
    effective_wave_index,
    enemy_attack_assertion,
    enemy_motion_assertion,
    execute_actions,
    observe_water_cast_with_real_input,
    parse_key_values,
    wait_for_state,
    wait_shared_hub,
)
from tools._real_flow_e2e.windows import (  # noqa: E402
    BOT_PLAY_TEAM_ROSTER,
    PowerShell,
    WindowsHarnessError,
    WindowsPeer,
    assert_ports_free,
    client_through_launcher,
    close_exact_owned_processes,
    exact_owned_processes,
    host_through_launcher,
    port_inventory,
    prepare_windows_peer,
    send_key,
    windows_processes,
)
from tools._real_flow_e2e.remote import RemoteHarnessError  # noqa: E402
from tools._real_flow_e2e.wan import (  # noqa: E402
    WanFlowFailure,
    run_wan_nfo,
)
from tools._real_flow_e2e.ws20 import (  # noqa: E402
    RemoteWindowsConnection,
    Ws20HarnessError,
    Ws20Peer,
)


class RealFlowFailure(RuntimeError):
    """The real-flow contract did not complete or an assertion failed."""


BOT_MOD_ID = "bot.brain"
OBSERVER_MOD_ID = "tool.real_flow_e2e_observer"
BOT_EXEC_DIRECTIVE = f"-- sdmod-exec-target: {BOT_MOD_ID}\n"
OBSERVER_EXEC_DIRECTIVE = (
    f"-- sdmod-exec-target: {OBSERVER_MOD_ID}\n"
)
BOT_PROBE_LUA = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local root = rawget(_G, "bot_brain_debug") or {}
local local_player = root.local_player or {}
local brain = local_player.brain or {}
local takeover = sd.input.get_local_player_takeover_state()
emit("loaded", rawget(_G, "bot_brain_debug") ~= nil)
emit("desired", local_player.desired or false)
emit("active", local_player.active or false)
emit("behavior", local_player.behavior or "")
emit("participant_id", local_player.participant_id or 0)
emit("activation_count", local_player.activation_count or 0)
emit("release_count", local_player.release_count or 0)
emit("release_clean", local_player.release_clean or false)
emit("last_release_reason", local_player.last_release_reason or "")
emit("last_error", local_player.last_error or "")
emit("focus_active", root.focus_active or false)
emit("brain.mode", brain.mode or "")
emit("brain.wave", brain.wave or 0)
emit("brain.think_count", brain.think_count or 0)
emit("brain.move_accepted", brain.move_accepted or 0)
emit("brain.cast_issued", brain.cast_issued or 0)
emit("brain.cast_accepted", brain.cast_accepted or 0)
emit("brain.target_network_actor_id",
  brain.target_network_actor_id or 0)
emit("brain.live_enemy_count", brain.live_enemy_count or 0)
emit("brain.attack_window_max", brain.attack_window_max or 0)
emit("brain.nearest_enemy_distance",
  brain.nearest_enemy_distance or 0)
emit("brain.target_distance", brain.target_distance or 0)
emit("brain.hp_ratio", brain.hp_ratio or 0)
for _, key in ipairs({
  "active",
  "clean",
  "owner_mod_id",
  "actor_address",
  "target_actor_address",
  "target_valid",
  "movement_input_x",
  "movement_input_y",
  "pending_movement_x",
  "pending_movement_y",
  "pending_movement_frames",
  "pending_mouse_left_frames",
  "pending_mouse_right_frames",
  "pending_scancode_count",
  "pending_native_control_frames",
  "cast_intent",
  "primary_skill_id",
  "previous_skill_id",
  "current_target_actor_address",
  "control_brain_move_x",
  "control_brain_move_y",
}) do
  emit("takeover." .. key, takeover[key])
end
"""
RESET_DAMAGE_LUA = r"""
print("enemy=" ..
  tostring(sd.debug.reset_enemy_damage_observations()))
print("player=" ..
  tostring(sd.debug.reset_player_damage_observations()))
"""
DRAIN_DAMAGE_LUA = r"""
local output = {}
for _, row in ipairs(
    sd.debug.take_enemy_damage_observations() or {}) do
  output[#output + 1] = table.concat({
    "enemy",
    tostring(row.sequence or 0),
    tostring(row.monotonic_ms or 0),
    tostring(row.source_participant_id or 0),
    tostring(row.target_network_actor_id or 0),
    tostring(row.target_hp_before or 0),
    tostring(row.target_hp_after or 0),
    tostring(row.hp_delta or 0),
  }, "|")
end
for _, row in ipairs(
    sd.debug.take_player_damage_observations() or {}) do
  output[#output + 1] = table.concat({
    "player",
    tostring(row.sequence or 0),
    tostring(row.monotonic_ms or 0),
    tostring(row.target_participant_id or 0),
    tostring(row.target_hp_before or 0),
    tostring(row.target_hp_after or 0),
    tostring(row.hp_delta or 0),
  }, "|")
end
if #output == 0 then return "none" end
return table.concat(output, "\n")
"""
AUTHORITY_DAMAGE_RE = re.compile(
    r"Multiplayer enemy damage claim accepted\. "
    r"participant_id=(\d+) "
    r"target_network_actor_id=(\d+) "
    r"damage=([-+0-9.eE]+) "
    r"before_hp=([-+0-9.eE]+) "
    r"after_hp=([-+0-9.eE]+)"
)


def validate_stock_water_cast(
    cast: dict[str, Any],
    *,
    expected_contact_damage: float,
) -> dict[str, Any]:
    observation = cast["observation"]
    contact_count = int(observation["nativeContactCount"])
    contact_samples = [
        float(value)
        for value in observation["nativeContactSamples"]
    ]
    if not observation["damageClaimValid"] or contact_count <= 0:
        raise RealFlowFailure(
            f"Water cast produced no native damage observation: {observation}"
        )
    if (
        int(observation["nativeContactSkillId"]) != 32
        or not observation["nativeContactSkillConsistent"]
    ):
        raise RealFlowFailure(
            "Water cast contacts did not retain stock skill 32: "
            f"{observation}"
        )
    if not contact_samples:
        raise RealFlowFailure(
            f"Water cast retained no exact native samples: {observation}"
        )
    tolerance = 0.00001
    non_stock = [
        value
        for value in contact_samples
        if not math.isclose(
            value,
            expected_contact_damage,
            rel_tol=0.0,
            abs_tol=tolerance,
        )
    ]
    if non_stock:
        raise RealFlowFailure(
            "Water cast contained non-stock native contacts: "
            f"expected={expected_contact_damage} actual={non_stock}"
        )
    expected_total = expected_contact_damage * contact_count
    native_total = float(observation["nativeContactTotal"])
    claimed_total = float(observation["claimedTotal"])
    host_damage = float(cast["hostDamage"])
    for label, actual in (
        ("native contact total", native_total),
        ("replicated claim total", claimed_total),
        ("host authoritative HP delta", host_damage),
    ):
        if not math.isclose(
            actual,
            expected_total,
            rel_tol=0.0,
            abs_tol=0.0002,
        ):
            raise RealFlowFailure(
                f"Water {label} diverged from stock per-cast total: "
                f"contacts={contact_count} expected={expected_total:.6f} "
                f"actual={actual:.6f}"
            )
    if (
        int(observation["associatedSkillId"]) != 32
        or not observation["associatedSkillConsistent"]
        or int(observation["unassociatedClaimCount"]) != 0
    ):
        raise RealFlowFailure(
            "Water claim association was ambiguous or used a non-Water "
            f"skill: {observation}"
        )
    network_actor_id = int(cast["networkActorId"])
    client_enemy = next(
        (
            enemy
            for enemy in cast["clientAfter"]["replicatedEnemies"]
            if int(enemy["network_id"]) == network_actor_id
        ),
        None,
    )
    client_hp = (
        0.0
        if client_enemy is None or client_enemy["dead"]
        else float(client_enemy["hp"])
    )
    host_hp = float(cast["hostHpAfter"])
    if not math.isclose(
        client_hp,
        host_hp,
        rel_tol=0.0,
        abs_tol=0.0005,
    ):
        raise RealFlowFailure(
            "Water cast HP did not converge on both peers: "
            f"host={host_hp:.6f} clientB={client_hp:.6f}"
        )
    return {
        "networkActorId": network_actor_id,
        "skillId": 32,
        "contactCount": contact_count,
        "perContactDamage": expected_contact_damage,
        "nativeContactTotal": native_total,
        "replicatedClaimTotal": claimed_total,
        "hostAuthoritativeDamage": host_damage,
        "hostHpAfter": host_hp,
        "clientBHpAfter": client_hp,
    }


def validate_living_wave_boundary(
    rows: list[dict[str, Any]],
    *,
    target_wave: int,
    maximum_displacement: float,
) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: int(row["utcNanoseconds"]))
    after_index = next(
        (
            index
            for index, row in enumerate(ordered)
            if (
                effective_wave_index(row["host"]) >= target_wave
                and effective_wave_index(row["clientB"]) >= target_wave
                and float(row["host"]["player"]["hp"]) > 0
                and float(row["clientB"]["player"]["hp"]) > 0
            )
        ),
        None,
    )
    if after_index is None:
        raise RealFlowFailure(
            f"no living paired sample reached wave {target_wave}"
        )
    before_index = next(
        (
            index
            for index in range(after_index - 1, -1, -1)
            if (
                effective_wave_index(ordered[index]["host"])
                == target_wave - 1
                and effective_wave_index(ordered[index]["clientB"])
                == target_wave - 1
                and float(ordered[index]["host"]["player"]["hp"]) > 0
                and float(ordered[index]["clientB"]["player"]["hp"]) > 0
            )
        ),
        None,
    )
    if before_index is None:
        raise RealFlowFailure(
            f"no living paired sample preceded wave {target_wave}"
        )
    before = ordered[before_index]
    after = ordered[after_index]
    window = ordered[max(0, before_index - 4):min(
        len(ordered),
        after_index + 5,
    )]
    participants: dict[str, Any] = {}
    for role, key in (("host", "host"), ("clientB", "clientB")):
        before_position = (
            float(before[key]["player"]["x"]),
            float(before[key]["player"]["y"]),
        )
        after_position = (
            float(after[key]["player"]["x"]),
            float(after[key]["player"]["y"]),
        )
        boundary_displacement = math.dist(
            before_position,
            after_position,
        )
        living_positions = [
            (
                float(row[key]["player"]["x"]),
                float(row[key]["player"]["y"]),
            )
            for row in window
            if (
                row[key]["scene"]["name"] == "testrun"
                and float(row[key]["player"]["hp"]) > 0
            )
        ]
        jumps = [
            math.dist(first, second)
            for first, second in zip(
                living_positions,
                living_positions[1:],
            )
        ]
        maximum_jump = max(jumps, default=0.0)
        if (
            boundary_displacement > maximum_displacement
            or maximum_jump > maximum_displacement
        ):
            raise RealFlowFailure(
                f"living {role} position was moved by the wave respawn seam: "
                f"boundary={boundary_displacement:.3f} "
                f"maximumJump={maximum_jump:.3f} "
                f"limit={maximum_displacement:.3f}"
            )
        participants[role] = {
            "hpBefore": float(before[key]["player"]["hp"]),
            "hpAfter": float(after[key]["player"]["hp"]),
            "positionBefore": list(before_position),
            "positionAfter": list(after_position),
            "boundaryDisplacement": boundary_displacement,
            "maximumLivingSampleJump": maximum_jump,
        }
    return {
        "fromWave": target_wave - 1,
        "toWave": target_wave,
        "maximumAllowedDisplacement": maximum_displacement,
        "beforeUtcNanoseconds": int(before["utcNanoseconds"]),
        "afterUtcNanoseconds": int(after["utcNanoseconds"]),
        "participants": participants,
    }


def validate_wave_convergence(
    host: dict[str, Any],
    client: dict[str, Any],
    *,
    target_wave: int,
) -> dict[str, Any]:
    host_wave = effective_wave_index(host)
    client_wave = effective_wave_index(client)
    if host_wave < target_wave or client_wave < target_wave:
        raise RealFlowFailure(
            f"wave state did not converge through {target_wave}: "
            f"host={host_wave} clientB={client_wave}"
        )
    if (
        host["scene"]["name"] != "testrun"
        or client["scene"]["name"] != "testrun"
        or float(host["player"]["hp"]) <= 0
        or float(client["player"]["hp"]) <= 0
    ):
        raise RealFlowFailure(
            "wave convergence did not retain two living testrun participants"
        )
    for role, state in (("host", host), ("clientB", client)):
        active = [
            participant
            for participant in state["multiplayer"]["participants"]
            if participant["connected"] and participant["in_run"]
        ]
        if len(active) < 2 or any(
            int(participant["wave"]) < target_wave
            for participant in active
        ):
            raise RealFlowFailure(
                f"{role} participant projection did not converge through "
                f"wave {target_wave}: {active}"
            )
    return {
        "targetWave": target_wave,
        "hostWave": host_wave,
        "clientBWave": client_wave,
        "hostParticipantCount": (
            host["multiplayer"]["participantCount"]
        ),
        "clientBParticipantCount": (
            client["multiplayer"]["participantCount"]
        ),
    }


class PairSampler:
    def __init__(
        self,
        host: LuaPipe,
        client: LuaPipe,
        writer: JsonlWriter,
        interval_seconds: float,
    ) -> None:
        self.host = host
        self.client = client
        self.writer = writer
        self.interval_seconds = interval_seconds
        self.started = time.monotonic()
        self.phase = "not-started"
        self.rows: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def set_phase(self, phase: str) -> None:
        with self._lock:
            self.phase = phase

    def start(self) -> None:
        if self._thread is not None:
            raise RealFlowFailure("pair sampler was started twice")
        self._thread = threading.Thread(
            target=self._run,
            name="real-flow-pair-sampler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=20)
            if self._thread.is_alive():
                raise RealFlowFailure("pair sampler did not stop")

    def sample_now(self, label: str) -> dict[str, Any]:
        row = self._sample(label)
        self.rows.append(row)
        self.writer.append(row)
        return row

    def _sample(self, label: str) -> dict[str, Any]:
        with self._lock:
            phase = self.phase
        started_ns = time.time_ns()
        host = self.host.state()
        between_ns = time.time_ns()
        client = self.client.state()
        return {
            "schemaVersion": 1,
            "label": label,
            "phase": phase,
            "utcNanoseconds": started_ns,
            "betweenPeerUtcNanoseconds": between_ns,
            "completedUtcNanoseconds": time.time_ns(),
            "elapsedSeconds": time.monotonic() - self.started,
            "host": host,
            "clientB": client,
        }

    def _run(self) -> None:
        next_sample = time.monotonic()
        while not self._stop.is_set():
            try:
                row = self._sample("periodic")
                self.rows.append(row)
                self.writer.append(row)
            except BaseException as exc:
                error = {
                    "timeUtcNanoseconds": time.time_ns(),
                    "elapsedSeconds": time.monotonic() - self.started,
                    "phase": self.phase,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                self.errors.append(error)
            next_sample += self.interval_seconds
            delay = max(0.01, next_sample - time.monotonic())
            self._stop.wait(delay)


def _git_sha(source_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=15,
        check=False,
    )
    sha = completed.stdout.strip().lower()
    if completed.returncode != 0 or len(sha) != 40:
        raise RealFlowFailure(
            f"could not resolve source SHA: {completed.stdout.strip()}"
        )
    return sha


def _process_rows(ps: PowerShell) -> list[dict[str, Any]]:
    return [asdict(record) for record in windows_processes(ps)]


def _owned_process_rows(
    ps: PowerShell,
    peers: tuple[WindowsPeer, ...],
) -> list[dict[str, Any]]:
    return [asdict(record) for record in exact_owned_processes(ps, peers)]


def _udp_exclusion_inventory(
    ps: PowerShell,
    ports: set[int],
) -> dict[str, Any]:
    raw = ps.run(
        "netsh interface ipv4 show excludedportrange protocol=udp",
        timeout=20,
    )
    ranges: list[dict[str, int]] = []
    for line in raw.splitlines():
        match = re.fullmatch(
            r"\s*([0-9]+)\s+([0-9]+)(?:\s+\*)?\s*",
            line,
        )
        if match is None:
            continue
        ranges.append(
            {
                "start": int(match.group(1)),
                "end": int(match.group(2)),
            }
        )
    excluded = {
        port
        for port in ports
        if any(row["start"] <= port <= row["end"] for row in ranges)
    }
    if excluded:
        raise RealFlowFailure(
            f"requested UDP ports are Windows-excluded: {sorted(excluded)}"
        )
    return {
        "command": (
            "netsh interface ipv4 show excludedportrange protocol=udp"
        ),
        "raw": raw,
        "ranges": ranges,
        "requestedPorts": sorted(ports),
        "requestedPortsExcluded": [],
    }


def _assert_client_enemy_materialization(
    state: dict[str, Any],
) -> dict[str, Any]:
    client = state["clientB"]
    replicas = [
        enemy
        for enemy in client["replicatedEnemies"]
        if not enemy["dead"] and enemy["hp"] > 0
    ]
    bindings = {
        int(binding["network_id"]): binding
        for binding in client["enemyBindings"]
        if binding["matched"]
        and not binding["parked"]
        and not binding["removed"]
        and int(binding["address"]) != 0
    }
    native_network_ids = {
        int(enemy["network_id"])
        for enemy in client["nativeEnemies"]
        if not enemy["dead"]
        and enemy["hp"] > 0
        and int(enemy["network_id"]) != 0
    }
    replica_ids = {
        int(enemy["network_id"])
        for enemy in replicas
        if int(enemy["network_id"]) != 0
    }
    bound_ids = replica_ids.intersection(bindings)
    native_ids = replica_ids.intersection(native_network_ids)
    if not replicas or not bound_ids or not native_ids:
        raise RealFlowFailure(
            "client B did not materialize host-authored enemies as native "
            f"replicas: replicas={sorted(replica_ids)} "
            f"bound={sorted(bound_ids)} native={sorted(native_ids)}"
        )
    return {
        "replicaIds": sorted(replica_ids),
        "boundReplicaIds": sorted(bound_ids),
        "nativeReplicaIds": sorted(native_ids),
        "replicaCount": len(replicas),
    }


def _copy_and_account(
    peer: Any,
    output_directory: Path,
    *,
    require_steam_transport: bool = False,
) -> dict[str, Any]:
    remote_copy = getattr(peer, "copy_runtime_artifacts", None)
    if callable(remote_copy):
        copied = dict(remote_copy(output_directory))
    else:
        copied = copy_runtime_artifacts(peer, output_directory)
    telemetry = copied["networkTelemetry"]
    if not telemetry["copied"]:
        raise RealFlowFailure(
            f"{peer.config.role} did not produce mandatory network telemetry: "
            f"{telemetry}"
        )
    accounting = packet_accounting(Path(telemetry["path"]))
    if accounting["events"].get("telemetry_start", 0) != 1:
        raise RealFlowFailure(
            f"{peer.config.role} telemetry did not start exactly once: "
            f"{accounting['events']}"
        )
    result = {
        "copied": copied,
        "packetAccounting": accounting,
    }
    if require_steam_transport:
        result["steamTransport"] = steam_transport_assertion(
            accounting,
            role=peer.config.role,
        )
    return result


def _bot_settings_path(peer: WindowsPeer) -> Path:
    return (
        peer.runtime_root
        / "instances"
        / peer.config.instance
        / "stage"
        / ".sdmod"
        / "mod-settings"
        / f"{BOT_MOD_ID}.json"
    )


def _write_bot_settings(
    peer: Any,
    *,
    enabled: bool,
    behavior: str = "skirmisher",
    roster: list[dict[str, str]] | None = None,
) -> str:
    values = {
        "play_for_me": enabled,
        "play_for_me_behavior": behavior,
        "roster": roster or [],
    }
    remote_write = getattr(peer, "write_bot_settings", None)
    if callable(remote_write):
        return str(remote_write(mod_id=BOT_MOD_ID, values=values))
    path = _bot_settings_path(peer)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.bply-tmp")
    if temporary.exists():
        raise RealFlowFailure(
            f"bot-play settings temporary path already exists: {temporary}"
        )
    temporary.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "values": values,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return str(path)


def _targeted_execute(
    pipe: LuaPipe,
    mod_id: str,
    code: str,
) -> str:
    return pipe.execute(f"-- sdmod-exec-target: {mod_id}\n{code}")


def _bot_probe(pipe: LuaPipe) -> dict[str, Any]:
    raw = parse_key_values(
        _targeted_execute(pipe, BOT_MOD_ID, BOT_PROBE_LUA)
    )
    boolean_keys = {
        "loaded",
        "desired",
        "active",
        "release_clean",
        "focus_active",
        "takeover.active",
        "takeover.clean",
        "takeover.target_valid",
    }
    integer_keys = {
        "participant_id",
        "activation_count",
        "release_count",
        "brain.wave",
        "brain.think_count",
        "brain.move_accepted",
        "brain.cast_issued",
        "brain.cast_accepted",
        "brain.target_network_actor_id",
        "brain.live_enemy_count",
        "takeover.actor_address",
        "takeover.target_actor_address",
        "takeover.pending_movement_frames",
        "takeover.pending_mouse_left_frames",
        "takeover.pending_mouse_right_frames",
        "takeover.pending_scancode_count",
        "takeover.pending_native_control_frames",
        "takeover.cast_intent",
        "takeover.primary_skill_id",
        "takeover.previous_skill_id",
        "takeover.current_target_actor_address",
    }
    float_keys = {
        "brain.attack_window_max",
        "brain.nearest_enemy_distance",
        "brain.target_distance",
        "brain.hp_ratio",
        "takeover.movement_input_x",
        "takeover.movement_input_y",
        "takeover.pending_movement_x",
        "takeover.pending_movement_y",
        "takeover.control_brain_move_x",
        "takeover.control_brain_move_y",
    }
    normalized: dict[str, Any] = dict(raw)
    for key in boolean_keys:
        normalized[key] = raw.get(key, "").casefold() == "true"
    for key in integer_keys:
        try:
            normalized[key] = int(float(raw.get(key, "0")))
        except ValueError:
            normalized[key] = 0
    for key in float_keys:
        try:
            normalized[key] = float(raw.get(key, "0"))
        except ValueError:
            normalized[key] = math.nan
    return normalized


def _reload_bot_settings(pipe: LuaPipe) -> dict[str, str]:
    output = _targeted_execute(
        pipe,
        BOT_MOD_ID,
        f"""
local result = sd.__settings_reload("{BOT_MOD_ID}")
print("ok=" .. tostring(result.ok))
print("changed=" .. table.concat(result.changed or {{}}, ","))
print("error=" .. tostring(result.error or ""))
""",
    )
    result = parse_key_values(output)
    if result.get("ok") != "true":
        raise RealFlowFailure(
            f"Bot Play For Me settings reload failed: {result}"
        )
    return result


def _set_bot_play(
    peer: Any,
    pipe: LuaPipe,
    *,
    enabled: bool,
    behavior: str = "skirmisher",
    roster: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    path = _write_bot_settings(
        peer,
        enabled=enabled,
        behavior=behavior,
        roster=roster,
    )
    return {
        "enabled": enabled,
        "behavior": behavior,
        "roster": roster or [],
        "settingsPath": str(path),
        "reload": _reload_bot_settings(pipe),
    }


def _wait_for_bot_state(
    pipe: LuaPipe,
    predicate: Any,
    *,
    timeout: float,
    label: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = _bot_probe(pipe)
            last_error = ""
            if predicate(last):
                return last
        except (RuntimeProbeError, ValueError) as exc:
            last_error = str(exc)
        time.sleep(0.1)
    raise RealFlowFailure(
        f"{label} timed out; last={last} error={last_error!r}"
    )


def _assert_clean_release(
    state: dict[str, Any],
    *,
    after_human_input: bool = False,
) -> dict[str, Any]:
    takeover_exact_zero = (
        "takeover.actor_address",
        "takeover.target_actor_address",
        "takeover.pending_movement_frames",
        "takeover.pending_mouse_left_frames",
        "takeover.pending_mouse_right_frames",
        "takeover.pending_scancode_count",
        "takeover.pending_native_control_frames",
    )
    stock_exact_zero = (
        "takeover.cast_intent",
        "takeover.primary_skill_id",
        "takeover.previous_skill_id",
        "takeover.current_target_actor_address",
    )
    takeover_float_zero = (
        "takeover.pending_movement_x",
        "takeover.pending_movement_y",
    )
    stock_float_zero = (
        "takeover.movement_input_x",
        "takeover.movement_input_y",
        "takeover.control_brain_move_x",
        "takeover.control_brain_move_y",
    )
    exact_zero = takeover_exact_zero
    float_zero = takeover_float_zero
    if not after_human_input:
        exact_zero += stock_exact_zero
        float_zero += stock_float_zero
    failures = {
        key: state.get(key)
        for key in exact_zero
        if int(state.get(key, -1)) != 0
    }
    failures.update(
        {
            key: state.get(key)
            for key in float_zero
            if not math.isclose(
                float(state.get(key, math.nan)),
                0.0,
                rel_tol=0.0,
                abs_tol=0.000001,
            )
        }
    )
    if (
        state.get("active") is True
        or state.get("desired") is True
        or state.get("takeover.active") is True
        or state.get("takeover.clean") is not True
        or state.get("takeover.target_valid") is True
        or state.get("focus_active") is True
        or failures
    ):
        raise RealFlowFailure(
            "Bot Play For Me release retained control state: "
            f"failures={failures} state={state}"
        )
    return {
        "clean": True,
        "afterHumanInput": after_human_input,
        "explicitZeroFields": list(exact_zero + float_zero),
        "state": state,
    }


def _reset_damage_observations(
    pipe: LuaPipe,
    *,
    target_mod_id: str = OBSERVER_MOD_ID,
) -> dict[str, str]:
    result = parse_key_values(
        _targeted_execute(
            pipe,
            target_mod_id,
            RESET_DAMAGE_LUA,
        )
    )
    if result != {"enemy": "true", "player": "true"}:
        raise RealFlowFailure(
            f"could not reset damage observations: {result}"
        )
    return result


def _drain_damage_observations(
    pipe: LuaPipe,
    enemy_rows: list[dict[str, Any]],
    player_rows: list[dict[str, Any]],
    *,
    target_mod_id: str = OBSERVER_MOD_ID,
) -> None:
    output = _targeted_execute(
        pipe,
        target_mod_id,
        DRAIN_DAMAGE_LUA,
    ).strip()
    if output in {"", "none"}:
        return
    for line in output.splitlines():
        parts = line.strip().split("|")
        try:
            if len(parts) == 8 and parts[0] == "enemy":
                enemy_rows.append(
                    {
                        "sequence": int(parts[1]),
                        "monotonicMs": int(parts[2]),
                        "sourceParticipantId": int(parts[3]),
                        "targetNetworkActorId": int(parts[4]),
                        "targetHpBefore": float(parts[5]),
                        "targetHpAfter": float(parts[6]),
                        "damage": float(parts[7]),
                    }
                )
            elif len(parts) == 7 and parts[0] == "player":
                player_rows.append(
                    {
                        "sequence": int(parts[1]),
                        "monotonicMs": int(parts[2]),
                        "targetParticipantId": int(parts[3]),
                        "targetHpBefore": float(parts[4]),
                        "targetHpAfter": float(parts[5]),
                        "damage": float(parts[6]),
                    }
                )
            else:
                raise ValueError("unexpected row shape")
        except ValueError as exc:
            raise RealFlowFailure(
                f"malformed applied-damage observation: {line!r}"
            ) from exc


def _drain_authority_damage_log(
    log_path: Path,
    offset: int,
    partial_line: str,
    enemy_rows: list[dict[str, Any]],
) -> tuple[int, str]:
    if not log_path.is_file():
        return offset, partial_line
    with log_path.open("rb") as stream:
        stream.seek(offset)
        chunk = stream.read()
        new_offset = stream.tell()
    if not chunk:
        return new_offset, partial_line
    text = partial_line + chunk.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    next_partial = ""
    if lines and not lines[-1].endswith(("\n", "\r")):
        next_partial = lines.pop()
    for line in lines:
        match = AUTHORITY_DAMAGE_RE.search(line)
        if match is None:
            continue
        before_hp = float(match.group(4))
        after_hp = float(match.group(5))
        accepted_damage = before_hp - after_hp
        if accepted_damage <= 0.0:
            continue
        enemy_rows.append(
            {
                "sequence": 0,
                "monotonicMs": 0,
                "sourceParticipantId": int(match.group(1)),
                "targetNetworkActorId": int(match.group(2)),
                "targetHpBefore": before_hp,
                "targetHpAfter": after_hp,
                "damage": accepted_damage,
                "claimedDamage": float(match.group(3)),
                "evidenceSource": "host-authority-log",
            }
        )
    return new_offset, next_partial


def _damage_metrics(
    config: HarnessConfig,
    enemy_rows: list[dict[str, Any]],
    player_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    fighters: dict[str, Any] = {}
    for role, peer in (("host", config.host), ("clientB", config.client)):
        dealt = [
            row
            for row in enemy_rows
            if row["sourceParticipantId"] == peer.participant_id
            and row["damage"] > 0.0
        ]
        taken = [
            row
            for row in player_rows
            if row["targetParticipantId"] == peer.participant_id
            and row["damage"] > 0.0
        ]
        fighters[role] = {
            "participantId": peer.participant_id,
            "damageDealt": sum(row["damage"] for row in dealt),
            "damageDealtEdges": len(dealt),
            "damageTaken": sum(row["damage"] for row in taken),
            "damageTakenEdges": len(taken),
        }
    missing = [
        role
        for role, row in fighters.items()
        if row["damageDealt"] <= 0.0
        or row["damageDealtEdges"] <= 0
    ]
    if missing:
        raise RealFlowFailure(
            "bot-driven fighters lacked authoritative enemy damage: "
            f"{missing} metrics={fighters}"
        )
    return {
        "fighters": fighters,
        "enemyDamageEdges": len(enemy_rows),
        "playerDamageEdges": len(player_rows),
        "totalEnemyDamage": sum(row["damage"] for row in enemy_rows),
        "enemyRows": enemy_rows,
        "playerRows": player_rows,
    }


def _indicator_region_assertion(capture_path: Path) -> dict[str, Any]:
    from PIL import Image

    with Image.open(capture_path) as image:
        rgb = image.convert("RGB")
        left = max(0, rgb.width - 220)
        top = 0
        right = rgb.width
        bottom = min(rgb.height, 75)
        crop = rgb.crop((left, top, right, bottom))
        green_pixels = sum(
            1
            for red, green, blue in crop.getdata()
            if green >= 145
            and green - red >= 35
            and green - blue >= 20
        )
        if green_pixels < 40:
            raise RealFlowFailure(
                "bot indicator was not visible in its top-right capture "
                f"region: path={capture_path} greenPixels={green_pixels}"
            )
        return {
            "capturePath": str(capture_path),
            "imageSize": [rgb.width, rgb.height],
            "region": [left, top, right, bottom],
            "greenPixels": green_pixels,
        }


def _native_enemy_render_assertion(
    state: dict[str, Any],
    capture_path: Path,
) -> dict[str, Any]:
    from PIL import Image, ImageStat

    visible_enemies = [
        enemy
        for enemy in state["nativeEnemies"]
        if enemy["screen_valid"]
        and not enemy["dead"]
        and float(enemy["hp"]) > 0.0
    ]
    if not visible_enemies:
        raise RealFlowFailure(
            "fighting screenshot has no visible living native enemy"
        )
    viewport = state["viewport"]
    with Image.open(capture_path) as image:
        rgb = image.convert("RGB")
        scale_x = rgb.width / max(1, int(viewport["width"]))
        scale_y = rgb.height / max(1, int(viewport["height"]))
        candidates: list[dict[str, Any]] = []
        for enemy in visible_enemies:
            center_x = round(float(enemy["screen_x"]) * scale_x)
            center_y = round(float(enemy["screen_y"]) * scale_y)
            radius = max(
                8,
                min(48, round(24 * max(scale_x, scale_y))),
            )
            bounds = (
                max(0, center_x - radius),
                max(0, center_y - radius),
                min(rgb.width, center_x + radius + 1),
                min(rgb.height, center_y + radius + 1),
            )
            crop = rgb.crop(bounds)
            channel_ranges = [
                maximum - minimum
                for minimum, maximum in crop.getextrema()
            ]
            standard_deviation = ImageStat.Stat(crop).stddev
            candidates.append(
                {
                    "localActorAddress": int(enemy["address"]),
                    "projection": [
                        float(enemy["screen_x"]),
                        float(enemy["screen_y"]),
                    ],
                    "cropBounds": list(bounds),
                    "channelRanges": channel_ranges,
                    "channelStandardDeviation": standard_deviation,
                    "visuallyNonUniform": (
                        max(channel_ranges) >= 12
                        and max(standard_deviation) >= 3.0
                    ),
                }
            )
    accepted = [
        row for row in candidates if row["visuallyNonUniform"]
    ]
    if not accepted:
        raise RealFlowFailure(
            "on-screen native enemy crops were visually uniform: "
            + json.dumps(candidates, sort_keys=True)
        )
    return {
        "capture": str(capture_path),
        "viewport": viewport,
        "imageSize": [rgb.width, rgb.height],
        "candidates": candidates,
        "accepted": accepted,
    }


def _bot_is_driving(
    state: dict[str, Any],
    participant_id: int | None = None,
) -> bool:
    runtime_participant_id = int(state.get("participant_id", 0))
    return (
        state.get("loaded") is True
        and state.get("desired") is True
        and state.get("active") is True
        and state.get("takeover.active") is True
        and state.get("takeover.clean") is False
        and state.get("takeover.owner_mod_id") == BOT_MOD_ID
        and runtime_participant_id > 0
        and (
            participant_id is None
            or runtime_participant_id == participant_id
        )
        and int(state.get("takeover.actor_address", 0)) > 0
        and state.get("focus_active") is False
    )


def _visible_living_enemy(state: dict[str, Any]) -> bool:
    return any(
        enemy["screen_valid"]
        and not enemy["dead"]
        and float(enemy["hp"]) > 0.0
        for enemy in state["nativeEnemies"]
    )


def _fighter_damage_present(
    rows: list[dict[str, Any]],
    participant_id: int,
) -> bool:
    return any(
        row["sourceParticipantId"] == participant_id
        and row["damage"] > 0.0
        for row in rows
    )


def _verify_mixed_bot_and_idle_human(
    sampler: PairSampler,
    host_pipe: LuaPipe,
    client_pipe: LuaPipe,
    host_participant_id: int,
) -> dict[str, Any]:
    sampler.set_phase("mixed-host-bot-client-idle-human")
    started = sampler.sample_now("mixed-mode-start")
    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        sample = sampler.sample_now("mixed-mode-idle-human")
        host_bot = _bot_probe(host_pipe)
        client_clean = _bot_probe(client_pipe)
        if not _bot_is_driving(host_bot, host_participant_id):
            raise RealFlowFailure(
                f"host bot stopped during mixed mode: {host_bot}"
            )
        _assert_clean_release(client_clean)
        if (
            sample["host"]["scene"]["name"] != "testrun"
            or sample["clientB"]["scene"]["name"] != "testrun"
            or float(sample["host"]["player"]["hp"]) <= 0.0
            or float(sample["clientB"]["player"]["hp"]) <= 0.0
        ):
            raise RealFlowFailure(
                "mixed bot/idle-human pair became unhealthy: "
                f"{sample}"
            )
        samples.append(
            {
                "utcNanoseconds": sample["utcNanoseconds"],
                "hostWave": effective_wave_index(sample["host"]),
                "clientBWave": effective_wave_index(sample["clientB"]),
                "hostHp": sample["host"]["player"]["hp"],
                "clientBHp": sample["clientB"]["player"]["hp"],
                "hostPacketsSent": (
                    sample["host"]["multiplayer"]["packetsSent"]
                ),
                "clientBPacketsReceived": (
                    sample["clientB"]["multiplayer"]["packetsReceived"]
                ),
            }
        )
        time.sleep(0.25)
    final = sampler.sample_now("mixed-mode-complete")
    final_host_bot = _bot_probe(host_pipe)
    final_client_clean = _bot_probe(client_pipe)
    if not _bot_is_driving(final_host_bot, host_participant_id):
        raise RealFlowFailure(
            f"host bot stopped at mixed-mode completion: {final_host_bot}"
        )
    _assert_clean_release(final_client_clean)
    if (
        final["host"]["scene"]["name"] != "testrun"
        or final["clientB"]["scene"]["name"] != "testrun"
        or float(final["host"]["player"]["hp"]) <= 0.0
        or float(final["clientB"]["player"]["hp"]) <= 0.0
    ):
        raise RealFlowFailure(
            "mixed bot/idle-human pair was unhealthy at completion: "
            f"{final}"
        )
    host_packet_delta = (
        final["host"]["multiplayer"]["packetsSent"]
        - started["host"]["multiplayer"]["packetsSent"]
    )
    client_packet_delta = (
        final["clientB"]["multiplayer"]["packetsReceived"]
        - started["clientB"]["multiplayer"]["packetsReceived"]
    )
    if host_packet_delta <= 0 or client_packet_delta <= 0:
        raise RealFlowFailure(
            "mixed mode starved the idle human peer of session traffic: "
            f"hostDelta={host_packet_delta} clientDelta={client_packet_delta}"
        )
    return {
        "durationSeconds": 5.0,
        "hostBotDriven": True,
        "clientBIdleHuman": True,
        "clientBCleanThroughout": True,
        "hostPacketsSentDelta": host_packet_delta,
        "clientBPacketsReceivedDelta": client_packet_delta,
        "finalHostHp": final["host"]["player"]["hp"],
        "finalClientBHp": final["clientB"]["player"]["hp"],
        "samples": samples,
    }


def _run_bot_play_mixed_mode_preflight(
    host: WindowsPeer,
    host_pipe: LuaPipe,
    client_pipe: LuaPipe,
    sampler: PairSampler,
) -> dict[str, Any]:
    activation_request = _set_bot_play(
        host,
        host_pipe,
        enabled=True,
        roster=[],
    )
    host_takeover = _wait_for_bot_state(
        host_pipe,
        _bot_is_driving,
        timeout=15.0,
        label="mixed-mode host local-player bot takeover",
    )
    idle_human = _wait_for_bot_state(
        client_pipe,
        lambda state: (
            state.get("loaded") is True
            and state.get("desired") is False
            and state.get("active") is False
            and state.get("takeover.active") is False
            and state.get("takeover.clean") is True
        ),
        timeout=15.0,
        label="mixed-mode idle-human client state",
    )
    proof = _verify_mixed_bot_and_idle_human(
        sampler,
        host_pipe,
        client_pipe,
        int(host_takeover["participant_id"]),
    )
    release_request = _set_bot_play(
        host,
        host_pipe,
        enabled=False,
        roster=[],
    )
    released = _wait_for_bot_state(
        host_pipe,
        lambda state: (
            state.get("desired") is False
            and state.get("active") is False
            and state.get("takeover.active") is False
            and state.get("takeover.clean") is True
        ),
        timeout=5.0,
        label="mixed-mode host clean release",
    )
    return {
        **proof,
        "activationRequest": activation_request,
        "hostTakeover": host_takeover,
        "idleHumanState": _assert_clean_release(idle_human),
        "releaseRequest": release_request,
        "hostCleanRelease": _assert_clean_release(released),
        "combatStarted": any(
            int(sample["hostWave"]) > 0
            or int(sample["clientBWave"]) > 0
            for sample in proof["samples"]
        ),
    }


def _living_enemy_count(state: dict[str, Any]) -> int:
    return sum(
        1
        for enemy in state["nativeEnemies"]
        if not enemy["dead"] and float(enemy["hp"]) > 0.0
    )


def _wait_for_client_enemy_materialization(
    config: HarnessConfig,
    sampler: PairSampler,
) -> dict[str, Any]:
    sampler.set_phase("first-enemy-spawn")
    enemy_state = sampler.sample_now("first-enemy-wait-start")
    deadline = time.monotonic() + config.timeout_seconds
    materialization_error = ""
    while time.monotonic() < deadline:
        enemy_state = sampler.sample_now("first-enemy-wait")
        if (
            len(enemy_state["host"]["nativeEnemies"]) > 0
            and len(enemy_state["clientB"]["replicatedEnemies"]) > 0
        ):
            try:
                return _assert_client_enemy_materialization(enemy_state)
            except RealFlowFailure as exc:
                materialization_error = str(exc)
        time.sleep(0.2)
    raise RealFlowFailure(
        "the real flow produced no aligned host/native and "
        "client/materialized replicated enemies; "
        f"last={materialization_error!r}"
    )


def _run_bot_play_endurance(
    config: HarnessConfig,
    host: WindowsPeer,
    client: Any,
    host_pipe: LuaPipe,
    client_pipe: LuaPipe,
    sampler: PairSampler,
    client_prearm_request: dict[str, Any],
) -> dict[str, Any]:
    event_writer = JsonlWriter(
        config.evidence_root / "endurance-events.jsonl"
    )
    damage_writer = JsonlWriter(
        config.evidence_root / "endurance-damage.jsonl"
    )
    enemy_rows: list[dict[str, Any]] = []
    player_rows: list[dict[str, Any]] = []
    enemy_rows_written = 0
    player_rows_written = 0

    initial = sampler.sample_now("endurance-pre-activation")
    participant_ids = {
        role: (
            int(initial[role]["multiplayer"]["localSteamId"])
            or peer.participant_id
        )
        for role, peer in (
            ("host", config.host),
            ("clientB", config.client),
        )
    }
    if (
        min(participant_ids.values()) <= 0
        or participant_ids["host"] == participant_ids["clientB"]
    ):
        raise RealFlowFailure(
            "endurance could not resolve two distinct transport identities: "
            f"{participant_ids}"
        )

    result: dict[str, Any] = {
        "mode": "natural-game-over-or-wall-clock-limit",
        "maxWallClockSeconds": config.endurance_max_seconds,
        "syntheticTeamRoster": [],
        "participantIdentity": {
            role: {
                "transportId": participant_ids[role],
                "configuredId": peer.participant_id,
            }
            for role, peer in (
                ("host", config.host),
                ("clientB", config.client),
            )
        },
    }
    result["damageObserversReset"] = _reset_damage_observations(
        host_pipe
    )
    authority_log_path = (
        host.game_executable.parent
        / ".sdmod"
        / "logs"
        / "solomondarkmodloader.log"
    )
    authority_log_offset = (
        authority_log_path.stat().st_size
        if authority_log_path.is_file()
        else 0
    )
    authority_log_partial = ""

    result["activationRequests"] = {
        "host": _set_bot_play(
            host,
            host_pipe,
            enabled=True,
            roster=[],
        ),
        "clientB": client_prearm_request,
    }
    result["activeTakeovers"] = {
        "host": _wait_for_bot_state(
            host_pipe,
            _bot_is_driving,
            timeout=15.0,
            label="endurance host local-player bot takeover",
        ),
        "clientB": _wait_for_bot_state(
            client_pipe,
            _bot_is_driving,
            timeout=15.0,
            label="endurance client local-player bot takeover",
        ),
    }
    runtime_participant_ids = {
        role: int(state["participant_id"])
        for role, state in result["activeTakeovers"].items()
    }
    for role in ("host", "clientB"):
        result["participantIdentity"][role]["runtimeSlotId"] = (
            runtime_participant_ids[role]
        )

    result["clientEnemyMaterialization"] = (
        _wait_for_client_enemy_materialization(config, sampler)
    )

    sampler.set_phase("bot-play-endurance")
    tracker = FighterStatsTracker(participant_ids)
    monitor = EnduranceAnomalyMonitor()
    started_monotonic = time.monotonic()
    started_utc_ns = time.time_ns()
    deadline = started_monotonic + config.endurance_max_seconds
    captures: list[dict[str, Any]] = []
    capture_errors: list[dict[str, Any]] = []
    captured_milestones: set[int] = set()
    missed_milestones: set[int] = set()
    capture_attempts: dict[int, int] = {}
    terminal_started: float | None = None
    final_sample = initial
    final_bots = result["activeTakeovers"]
    termination_reason = ""
    game_over_capture: dict[str, Any] | None = None

    while True:
        sample = sampler.sample_now("endurance-monitor")
        final_sample = sample
        for event in tracker.observe(sample):
            event_writer.append(event)
        _drain_damage_observations(
            host_pipe,
            enemy_rows,
            player_rows,
        )
        (
            authority_log_offset,
            authority_log_partial,
        ) = _drain_authority_damage_log(
            authority_log_path,
            authority_log_offset,
            authority_log_partial,
            enemy_rows,
        )
        while enemy_rows_written < len(enemy_rows):
            damage_writer.append(
                {"kind": "enemy", **enemy_rows[enemy_rows_written]}
            )
            enemy_rows_written += 1
        while player_rows_written < len(player_rows):
            damage_writer.append(
                {"kind": "player", **player_rows[player_rows_written]}
            )
            player_rows_written += 1

        bots = {
            "host": _bot_probe(host_pipe),
            "clientB": _bot_probe(client_pipe),
        }
        final_bots = bots
        driving = {
            role: _bot_is_driving(
                bots[role],
                runtime_participant_ids[role],
            )
            for role in ("host", "clientB")
        }
        for finding in monitor.observe(sample, bots, driving):
            event_writer.append({"event": "finding", **finding})

        converged_wave = min(
            endurance_wave(sample["host"]),
            endurance_wave(sample["clientB"]),
        )
        pending_milestones = [
            wave
            for wave in range(1, converged_wave + 1)
            if is_capture_milestone(wave)
            and wave not in captured_milestones
            and wave not in missed_milestones
        ]
        for missed in (
            wave for wave in pending_milestones if wave < converged_wave
        ):
            missed_milestones.add(missed)
            capture_error = {
                "kind": "milestone-capture-missed",
                "milestoneWave": missed,
                "observedWave": converged_wave,
                "elapsedSeconds": sample["elapsedSeconds"],
                "message": "wave advanced before a paired capture succeeded",
            }
            capture_errors.append(capture_error)
            event_writer.append({"event": "capture-error", **capture_error})
        pending_milestones = [
            wave for wave in pending_milestones if wave == converged_wave
        ]
        if (
            pending_milestones
            and _living_enemy_count(sample["host"]) > 0
            and _living_enemy_count(sample["clientB"]) > 0
        ):
            milestone = max(pending_milestones)
            attempts = capture_attempts.get(milestone, 0) + 1
            capture_attempts[milestone] = attempts
            try:
                capture = paired_windows_capture(
                    config.source_root,
                    host,
                    client,
                    config.evidence_root / "captures" / "endurance",
                    label=f"wave-{milestone}",
                )
                assertions: dict[str, Any] = {}
                for role in ("host", "clientB"):
                    capture_path = Path(
                        capture["captures"][role]["path"]
                    )
                    role_assertions: dict[str, Any] = {
                        "bot": bots[role],
                        "driving": driving[role],
                    }
                    if driving[role]:
                        role_assertions["indicator"] = (
                            _indicator_region_assertion(capture_path)
                        )
                    role_assertions["enemyRendered"] = (
                        _native_enemy_render_assertion(
                            sample[role],
                            capture_path,
                        )
                        if role == "host"
                        else rendered_enemy_assertion(
                            sample[role],
                            capture_path,
                        )
                    )
                    assertions[role] = role_assertions
                capture_row = {
                    "milestoneWave": milestone,
                    "observedHostWave": endurance_wave(sample["host"]),
                    "observedClientBWave": endurance_wave(
                        sample["clientB"]
                    ),
                    "sampleUtcNanoseconds": sample["utcNanoseconds"],
                    "capture": capture,
                    "assertions": assertions,
                }
                captures.append(capture_row)
                captured_milestones.add(milestone)
                event_writer.append(
                    {
                        "event": "milestone-capture",
                        **capture_row,
                    }
                )
            except (
                EvidenceError,
                RealFlowFailure,
                WindowsHarnessError,
                Ws20HarnessError,
            ) as exc:
                capture_error = {
                    "kind": "milestone-capture-failure",
                    "milestoneWave": milestone,
                    "attempt": attempts,
                    "elapsedSeconds": sample["elapsedSeconds"],
                    "message": str(exc),
                }
                capture_errors.append(capture_error)
                event_writer.append(
                    {"event": "capture-error", **capture_error}
                )

        host_terminal = terminal_game_over(sample["host"])
        client_terminal = terminal_game_over(sample["clientB"])
        if host_terminal and client_terminal:
            if terminal_started is None:
                terminal_started = time.monotonic()
                event_writer.append(
                    {
                        "event": "terminal-game-over-converged",
                        "elapsedSeconds": sample["elapsedSeconds"],
                        "hostWave": endurance_wave(sample["host"]),
                        "clientBWave": endurance_wave(sample["clientB"]),
                    }
                )
            surfaces_ready = all(
                sample[role]["ui"]["surfaceId"] == "game_over"
                for role in ("host", "clientB")
            )
            if surfaces_ready or time.monotonic() - terminal_started >= 4.0:
                try:
                    game_over_capture = paired_windows_capture(
                        config.source_root,
                        host,
                        client,
                        config.evidence_root / "captures" / "endurance",
                        label=(
                            "natural-game-over-wave-"
                            f"{max(endurance_wave(sample['host']), endurance_wave(sample['clientB']))}"
                        ),
                    )
                except (
                    EvidenceError,
                    WindowsHarnessError,
                    Ws20HarnessError,
                ) as exc:
                    capture_error = {
                        "kind": "game-over-capture-failure",
                        "elapsedSeconds": sample["elapsedSeconds"],
                        "message": str(exc),
                    }
                    capture_errors.append(capture_error)
                    event_writer.append(
                        {"event": "capture-error", **capture_error}
                    )
                termination_reason = "natural-game-over"
                break
        else:
            terminal_started = None

        if time.monotonic() >= deadline:
            try:
                game_over_capture = paired_windows_capture(
                    config.source_root,
                    host,
                    client,
                    config.evidence_root / "captures" / "endurance",
                    label=f"wall-clock-limit-wave-{converged_wave}",
                )
            except (
                EvidenceError,
                WindowsHarnessError,
                Ws20HarnessError,
            ) as exc:
                capture_error = {
                    "kind": "wall-clock-capture-failure",
                    "elapsedSeconds": sample["elapsedSeconds"],
                    "message": str(exc),
                }
                capture_errors.append(capture_error)
                event_writer.append(
                    {"event": "capture-error", **capture_error}
                )
            termination_reason = "wall-clock-limit"
            break
        time.sleep(max(0.1, config.sampling_seconds))

    _drain_damage_observations(
        host_pipe,
        enemy_rows,
        player_rows,
    )
    (
        authority_log_offset,
        authority_log_partial,
    ) = _drain_authority_damage_log(
        authority_log_path,
        authority_log_offset,
        authority_log_partial,
        enemy_rows,
    )
    while enemy_rows_written < len(enemy_rows):
        damage_writer.append(
            {"kind": "enemy", **enemy_rows[enemy_rows_written]}
        )
        enemy_rows_written += 1
    while player_rows_written < len(player_rows):
        damage_writer.append(
            {"kind": "player", **player_rows[player_rows_written]}
        )
        player_rows_written += 1

    elapsed_seconds = time.monotonic() - started_monotonic
    findings = monitor.finish(float(final_sample["elapsedSeconds"]))
    fighter_stats = tracker.result(enemy_rows, player_rows)
    for role, stats in fighter_stats.items():
        if stats["damageDealtEdges"] == 0:
            findings.append(
                {
                    "id": f"F{len(findings) + 1:03d}",
                    "kind": "fighter-no-authoritative-damage",
                    "role": role,
                    "evidence": stats,
                    "ongoingAtEnd": True,
                }
            )
    for capture_error in capture_errors:
        findings.append(
            {
                "id": f"F{len(findings) + 1:03d}",
                **capture_error,
            }
        )
    if not captures:
        raise RealFlowFailure(
            "endurance produced no paired wave-milestone capture"
        )

    result.update(
        {
            "startedUtcNanoseconds": started_utc_ns,
            "endedUtcNanoseconds": time.time_ns(),
            "durationSeconds": elapsed_seconds,
            "terminationReason": termination_reason,
            "naturalGameOver": termination_reason == "natural-game-over",
            "furthestWave": max(
                stats["furthestWave"] for stats in fighter_stats.values()
            ),
            "fighterStats": fighter_stats,
            "damageEventCounts": {
                "enemy": len(enemy_rows),
                "player": len(player_rows),
            },
            "damageEvidencePath": str(
                config.evidence_root / "endurance-damage.jsonl"
            ),
            "milestoneCaptures": captures,
            "captureErrors": capture_errors,
            "gameOverOrLimitCapture": game_over_capture,
            "findings": findings,
            "finalBots": final_bots,
            "finalState": final_sample,
            "completedPhase": (
                "bot-play-natural-game-over"
                if termination_reason == "natural-game-over"
                else "bot-play-90-minute-limit"
            ),
        }
    )
    return result


def _run_bot_play_for_me(
    config: HarnessConfig,
    host: WindowsPeer,
    client: WindowsPeer,
    host_pipe: LuaPipe,
    client_pipe: LuaPipe,
    sampler: PairSampler,
    mixed_mode: dict[str, Any],
) -> dict[str, Any]:
    if config.verify_through_wave < 4:
        raise RealFlowFailure(
            "Bot Play For Me acceptance must verify through wave 4 so three "
            "full stock waves have completed"
        )
    enemy_rows: list[dict[str, Any]] = []
    player_rows: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "targetCompletedWaves": config.verify_through_wave - 1,
        "settingsStartedDisabledForPhysicalMatchEntry": True,
        "syntheticTeamRoster": BOT_PLAY_TEAM_ROSTER[:2],
        "mixedMode": mixed_mode,
    }
    result["damageObserversReset"] = _reset_damage_observations(
        host_pipe
    )
    authority_log_path = (
        host.game_executable.parent
        / ".sdmod"
        / "logs"
        / "solomondarkmodloader.log"
    )
    authority_log_offset = (
        authority_log_path.stat().st_size
        if authority_log_path.is_file()
        else 0
    )
    authority_log_partial = ""
    result["activationRequests"] = {
        "host": _set_bot_play(
            host,
            host_pipe,
            enabled=True,
            roster=BOT_PLAY_TEAM_ROSTER[:2],
        ),
        "clientB": _set_bot_play(
            client,
            client_pipe,
            enabled=True,
            roster=BOT_PLAY_TEAM_ROSTER[:2],
        ),
    }
    result["activeTakeovers"] = {
        "host": _wait_for_bot_state(
            host_pipe,
            _bot_is_driving,
            timeout=15.0,
            label="host local-player bot takeover",
        ),
        "clientB": _wait_for_bot_state(
            client_pipe,
            _bot_is_driving,
            timeout=15.0,
            label="client local-player bot takeover",
        ),
    }
    runtime_participant_ids = {
        role: int(state["participant_id"])
        for role, state in result["activeTakeovers"].items()
    }
    result["participantIdentity"] = {
        "host": {
            "runtimeSlotId": runtime_participant_ids["host"],
            "transportId": config.host.participant_id,
        },
        "clientB": {
            "runtimeSlotId": runtime_participant_ids["clientB"],
            "transportId": config.client.participant_id,
        },
    }

    sampler.set_phase("both-local-players-bot-driven")
    deadline = time.monotonic() + config.timeout_seconds
    screenshots: dict[str, dict[str, Any]] = {}
    screenshot_assertions: dict[str, dict[str, Any]] = {}
    screenshot_errors: dict[str, list[str]] = {
        "host": [],
        "clientB": [],
    }
    next_capture_at = {
        "host": time.monotonic(),
        "clientB": time.monotonic(),
    }
    capture_readiness: dict[str, dict[str, bool]] = {}
    final_sample: dict[str, Any] | None = None
    last_summary: dict[str, Any] = {}
    wave_samples: list[dict[str, Any]] = []
    last_wave_signature: tuple[int, int] | None = None
    while time.monotonic() < deadline:
        sample = sampler.sample_now("bot-play-combat")
        _drain_damage_observations(
            host_pipe,
            enemy_rows,
            player_rows,
        )
        (
            authority_log_offset,
            authority_log_partial,
        ) = _drain_authority_damage_log(
            authority_log_path,
            authority_log_offset,
            authority_log_partial,
            enemy_rows,
        )
        host_bot = _bot_probe(host_pipe)
        client_bot = _bot_probe(client_pipe)
        host_wave = effective_wave_index(sample["host"])
        client_wave = effective_wave_index(sample["clientB"])
        wave_signature = (host_wave, client_wave)
        if wave_signature != last_wave_signature:
            wave_samples.append(
                {
                    "hostWave": host_wave,
                    "clientBWave": client_wave,
                    "hostHp": sample["host"]["player"]["hp"],
                    "clientBHp": sample["clientB"]["player"]["hp"],
                    "utcNanoseconds": sample["utcNanoseconds"],
                }
            )
            last_wave_signature = wave_signature
        last_summary = {
            "hostWave": host_wave,
            "clientBWave": client_wave,
            "hostHp": sample["host"]["player"]["hp"],
            "clientBHp": sample["clientB"]["player"]["hp"],
            "hostBot": host_bot,
            "clientBBot": client_bot,
            "enemyDamageEdges": len(enemy_rows),
        }
        for (
            role,
            peer,
            peer_state,
            peer_bot,
            peer_wave,
        ) in (
            (
                "host",
                config.host,
                sample["host"],
                host_bot,
                host_wave,
            ),
            (
                "clientB",
                config.client,
                sample["clientB"],
                client_bot,
                client_wave,
            ),
        ):
            readiness = {
                "castAccepted": (
                    int(peer_bot.get("brain.cast_accepted", 0)) > 0
                ),
                "authoritativeDamage": _fighter_damage_present(
                    enemy_rows,
                    peer.participant_id,
                ),
                "visibleLivingEnemy": _visible_living_enemy(
                    peer_state
                ),
            }
            capture_readiness[role] = readiness
            if (
                role in screenshots
                or time.monotonic() < next_capture_at[role]
                or not all(readiness.values())
            ):
                continue
            try:
                candidate = paired_windows_capture(
                    config.source_root,
                    host,
                    client,
                    config.evidence_root / "screenshots",
                    label=f"bot-fighting-{role}-wave-{peer_wave}",
                )
                capture_path = Path(
                    candidate["captures"][role]["path"]
                )
                assertions = {
                    "indicator": _indicator_region_assertion(
                        capture_path
                    ),
                    "enemyRendered": (
                        _native_enemy_render_assertion(
                            peer_state,
                            capture_path,
                        )
                        if role == "host"
                        else rendered_enemy_assertion(
                            peer_state,
                            capture_path,
                        )
                    ),
                    "visibleLivingEnemy": True,
                    "bot": peer_bot,
                }
                screenshots[role] = candidate
                screenshot_assertions[role] = assertions
            except (EvidenceError, RealFlowFailure) as exc:
                screenshot_errors[role].append(str(exc))
                next_capture_at[role] = time.monotonic() + 2.0
        if (
            host_wave >= config.verify_through_wave
            and client_wave >= config.verify_through_wave
            and float(sample["host"]["player"]["hp"]) > 0.0
            and float(sample["clientB"]["player"]["hp"]) > 0.0
            and _bot_is_driving(
                host_bot,
                runtime_participant_ids["host"],
            )
            and _bot_is_driving(
                client_bot,
                runtime_participant_ids["clientB"],
            )
            and screenshots.keys() >= {"host", "clientB"}
        ):
            final_sample = sample
            break
        if (
            sample["host"]["scene"]["name"] != "testrun"
            or sample["clientB"]["scene"]["name"] != "testrun"
        ):
            raise RealFlowFailure(
                "bot-driven pair left the stock run before three waves "
                f"completed: {last_summary}"
            )
        time.sleep(max(0.1, config.sampling_seconds))
    if final_sample is None:
        raise RealFlowFailure(
            "bot-driven peers did not complete three stock waves alive and "
            f"converged: {last_summary}"
        )
    _drain_damage_observations(
        host_pipe,
        enemy_rows,
        player_rows,
    )
    (
        authority_log_offset,
        authority_log_partial,
    ) = _drain_authority_damage_log(
        authority_log_path,
        authority_log_offset,
        authority_log_partial,
        enemy_rows,
    )
    missing_screenshots = sorted(
        {"host", "clientB"} - screenshots.keys()
    )
    if missing_screenshots:
        raise RealFlowFailure(
            "bot-driven peers lacked independently asserted fighting "
            f"captures: missing={missing_screenshots} "
            f"readiness={capture_readiness} errors={screenshot_errors}"
        )
    final_bots = {
        "host": _bot_probe(host_pipe),
        "clientB": _bot_probe(client_pipe),
    }
    for role, bot in final_bots.items():
        if int(bot.get("brain.cast_accepted", 0)) <= 0:
            raise RealFlowFailure(
                f"{role} bot brain never accepted a cast: {bot}"
            )
        if int(bot.get("brain.move_accepted", 0)) <= 0:
            raise RealFlowFailure(
                f"{role} bot brain never accepted movement: {bot}"
            )
    result["waveSamples"] = wave_samples
    result["finalBots"] = final_bots
    result["waveConvergence"] = validate_wave_convergence(
        final_sample["host"],
        final_sample["clientB"],
        target_wave=config.verify_through_wave,
    )
    result["damageMetrics"] = _damage_metrics(
        config,
        enemy_rows,
        player_rows,
    )
    result["pairedFightingCapture"] = screenshots
    result["captureAssertions"] = screenshot_assertions
    result["captureAttemptErrors"] = screenshot_errors

    sampler.set_phase("client-human-control-restored")
    result["clientToggleOffRequest"] = _set_bot_play(
        client,
        client_pipe,
        enabled=False,
        roster=BOT_PLAY_TEAM_ROSTER[:2],
    )
    client_released = _wait_for_bot_state(
        client_pipe,
        lambda state: (
            state.get("desired") is False
            and state.get("active") is False
            and state.get("takeover.active") is False
            and state.get("takeover.clean") is True
        ),
        timeout=5.0,
        label="client clean takeover release",
    )
    result["clientCleanRelease"] = _assert_clean_release(
        client_released
    )

    before_input = client_pipe.state()
    movement_attempts: list[dict[str, Any]] = []
    moved = False
    for key in ("d", "w", "a", "s"):
        before = client_pipe.state()
        helper = send_key(
            config.source_root,
            client,
            key,
            600,
        )
        try:
            after = wait_for_state(
                client_pipe,
                lambda state: math.dist(
                    (
                        float(before["player"]["x"]),
                        float(before["player"]["y"]),
                    ),
                    (
                        float(state["player"]["x"]),
                        float(state["player"]["y"]),
                    ),
                )
                >= 4.0,
                timeout=3.0,
                label=f"client physical {key} movement after release",
            )
        except RuntimeProbeError as exc:
            movement_attempts.append(
                {
                    "key": key,
                    "helper": helper,
                    "before": before["player"],
                    "error": str(exc),
                    "displacement": 0.0,
                }
            )
            continue
        displacement = math.dist(
            (
                float(before["player"]["x"]),
                float(before["player"]["y"]),
            ),
            (
                float(after["player"]["x"]),
                float(after["player"]["y"]),
            ),
        )
        movement_attempts.append(
            {
                "key": key,
                "helper": helper,
                "before": before["player"],
                "after": after["player"],
                "displacement": displacement,
            }
        )
        if displacement >= 4.0:
            moved = True
            break
    if not moved:
        raise RealFlowFailure(
            "physical human input did not move the released client: "
            f"{movement_attempts}"
        )
    result["humanControlProof"] = {
        "method": "physical-window-key-after-clean-release",
        "before": before_input["player"],
        "attempts": movement_attempts,
    }
    result["clientStillCleanAfterHumanInput"] = _assert_clean_release(
        _bot_probe(client_pipe),
        after_human_input=True,
    )

    result["hostToggleOffRequest"] = _set_bot_play(
        host,
        host_pipe,
        enabled=False,
        roster=BOT_PLAY_TEAM_ROSTER[:2],
    )
    host_released = _wait_for_bot_state(
        host_pipe,
        lambda state: (
            state.get("desired") is False
            and state.get("active") is False
            and state.get("takeover.active") is False
            and state.get("takeover.clean") is True
        ),
        timeout=5.0,
        label="host clean takeover release",
    )
    result["hostCleanRelease"] = _assert_clean_release(host_released)
    result["completedPhase"] = (
        f"bot-play-completed-{config.verify_through_wave - 1}-waves"
    )
    return result


def run(config: HarnessConfig, *, phase: str) -> dict[str, Any]:
    actual_sha = _git_sha(config.source_root)
    if actual_sha != config.expected_source_sha:
        raise RealFlowFailure(
            f"source SHA changed: expected {config.expected_source_sha}, "
            f"actual {actual_sha}"
        )
    if config.topology == "wan_udp_nfo":
        return run_wan_nfo(
            config,
            phase=phase,
            sampler_type=PairSampler,
        )
    is_ws20 = config.topology == "steam_windows_ws20"
    if config.host.platform != LOCAL_WINDOWS or (
        not is_ws20 and config.client.platform != LOCAL_WINDOWS
    ):
        raise RealFlowFailure(
            "this controller currently requires local Windows launcher peers; "
            "remote peer controllers are selected by their topology adapter"
        )
    staging_root = config.windows_staging_root
    if staging_root.exists():
        raise RealFlowFailure(
            f"local staging root must be new: {staging_root}"
        )
    config.evidence_root.mkdir(parents=True, exist_ok=False)
    write_json(config.evidence_root / "config.redacted.json", config.redacted())
    write_json(
        config.evidence_root / "source.json",
        {
            "expectedSha": config.expected_source_sha,
            "actualSha": actual_sha,
            "sourceRoot": str(config.source_root),
        },
    )

    ps = PowerShell(config.source_root)
    ports = {
        peer.local_port
        for peer in (config.host, config.client)
        if peer.local_port
    }
    ports.update(
        peer.remote_port
        for peer in (config.host, config.client)
        if peer.remote_port
    )
    udp_exclusions = _udp_exclusion_inventory(ps, ports)
    assert_ports_free(ps, ports)
    connection: RemoteWindowsConnection | None = None
    remote_before: dict[str, int | bool] | None = None
    remote_stage_claimed = False
    if is_ws20:
        connection = RemoteWindowsConnection(config.client)
        remote_before = connection.inventory()
        if remote_before != {
            "stageRootExists": False,
            "ownedProcessCount": 0,
            "taskCount": 0,
            "interactiveSteamCount": 1,
        }:
            connection.close()
            raise RealFlowFailure(
                "workstation20 did not satisfy the isolated preflight "
                f"boundary: {remote_before}"
            )
    before = {
        "utcNanoseconds": time.time_ns(),
        "processes": _process_rows(ps),
        "udpExclusions": udp_exclusions,
        "reservedPorts": port_inventory(ps, ports),
    }
    if remote_before is not None:
        before["clientBRemote"] = remote_before
    write_json(config.evidence_root / "safety" / "before.json", before)

    try:
        if connection is not None:
            connection.create_stage_root()
            remote_stage_claimed = True
        host = prepare_windows_peer(config, config.host)
        if is_ws20:
            assert connection is not None
            client: Any = Ws20Peer.prepare(config, connection)
            peers = (host,)
        else:
            client = prepare_windows_peer(config, config.client)
            peers = (host, client)
    except BaseException:
        if connection is not None:
            try:
                if remote_stage_claimed:
                    connection.remove_stage_root()
            finally:
                connection.close()
        if staging_root.is_dir():
            shutil.rmtree(staging_root)
        raise
    host_pipe = LuaPipe(config.source_root, config.host.pipe_name)
    if is_ws20:
        client_pipe = client.open_lua_pipe()
    else:
        client_pipe = LuaPipe(
            config.source_root,
            config.client.pipe_name,
        )
    timeline = JsonlWriter(config.evidence_root / "timeline.jsonl")
    sampler = PairSampler(
        host_pipe,
        client_pipe,
        timeline,
        config.sampling_seconds,
    )
    sampler_started = False
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "ok": False,
        "runName": config.run_name,
        "topology": config.topology,
        "phaseRequested": phase,
        "sourceSha": actual_sha,
        "forbiddenSeamsUsed": False,
        "networkTelemetryRequired": True,
        "audioDisabledRequired": True,
    }
    cleanup: dict[str, Any] = {}
    primary_error: BaseException | None = None
    try:
        result["hostLauncher"] = host_through_launcher(ps, config, host)
        if is_ws20:
            result["clientBLauncher"] = client.launch(host.lobby_id)
        else:
            result["clientBLauncher"] = client_through_launcher(
                ps,
                config,
                client,
                host.lobby_id,
            )
        remote_ledger = (
            connection.inventory()
            if connection is not None
            else None
        )
        write_json(
            config.evidence_root / "process-ledger.json",
            {
                "host": result["hostLauncher"],
                "clientB": result["clientBLauncher"],
                "ownedProcesses": _owned_process_rows(ps, peers),
                **(
                    {
                        "clientBStaging": {
                            "validated": True,
                            "sha256": client.staged_hashes,
                        }
                    }
                    if is_ws20
                    else {}
                ),
                **(
                    {"clientBRemote": remote_ledger}
                    if remote_ledger is not None
                    else {}
                ),
            },
        )
        result["sharedHub"] = wait_shared_hub(
            host_pipe,
            client_pipe,
            timeout=config.timeout_seconds,
        )
        sampler.set_phase("shared-hub")
        sampler.start()
        sampler_started = True
        sampler.sample_now("shared-hub-ready")
        result["sharedHubCapture"] = paired_windows_capture(
            config.source_root,
            host,
            client,
            config.evidence_root / "captures",
            label="shared-hub",
        )

        if phase == "shared-hub":
            result["ok"] = True
            result["completedPhase"] = "shared-hub"
            return result
        if not config.host.match_start_actions:
            raise RealFlowFailure(
                "full run requires host.matchStartActions with real key/click "
                "input for the native Start Match flow"
            )

        endurance_client_prearm: dict[str, Any] | None = None
        if config.bot_play_for_me and config.endurance_mode:
            sampler.set_phase("bot-play-client-prearm")
            prearm_request = _set_bot_play(
                client,
                client_pipe,
                enabled=True,
                roster=[],
            )
            prearm_state = _wait_for_bot_state(
                client_pipe,
                lambda state: (
                    state.get("loaded") is True
                    and state.get("desired") is True
                    and state.get("active") is False
                    and state.get("takeover.active") is False
                ),
                timeout=15.0,
                label="endurance client takeover prearm in shared hub",
            )
            endurance_client_prearm = {
                "request": prearm_request,
                "state": prearm_state,
            }
            result["enduranceClientPrearm"] = endurance_client_prearm

        sampler.set_phase("match-start")
        result["hostMatchStartActions"] = execute_actions(
            config.source_root,
            host,
            host_pipe,
            config.host.match_start_actions,
        )
        host_run = wait_for_state(
            host_pipe,
            lambda state: (
                state["solomon"]["valid"]
                and state["scene"]["name"] == "testrun"
            ),
            timeout=config.timeout_seconds,
            label="host native testrun after Start Match",
        )
        host_cover_actions: list[dict[str, Any]] = []

        def cover_client_dig() -> dict[str, Any]:
            action = cover_participant_with_real_input_once(
                config.source_root,
                host,
                host_pipe,
                movement_index=len(host_cover_actions),
            )
            host_cover_actions.append(action)
            return action

        result["sharedRun"] = {
            "host": host_run,
            "clientB": wait_for_state(
                client_pipe,
                lambda state: state["scene"]["name"] == "testrun",
                timeout=config.timeout_seconds,
                label="client B native testrun after host Start Match",
            ),
        }
        sampler.sample_now("native-run-materialized")

        bot_play_mixed_mode: dict[str, Any] | None = None
        if config.bot_play_for_me and not config.endurance_mode:
            bot_play_mixed_mode = _run_bot_play_mixed_mode_preflight(
                host,
                host_pipe,
                client_pipe,
                sampler,
            )

        solomon_peer = (
            host if config.solomon_interactor == "host" else client
        )
        solomon_pipe = (
            host_pipe
            if config.solomon_interactor == "host"
            else client_pipe
        )
        sampler.set_phase(
            f"{config.solomon_interactor}-solomon-dig"
        )
        result["solomonDig"] = {
            "interactor": config.solomon_interactor,
            "flow": approach_solomon_and_complete_dialogue(
                config.source_root,
                solomon_peer,
                solomon_pipe,
                authority_pipe=host_pipe,
                cover_action=(
                    cover_client_dig
                    if config.solomon_interactor == "client"
                    else None
                ),
                timeout=config.timeout_seconds,
            ),
            "hostAirCover": host_cover_actions,
        }
        solomon_completion = sampler.sample_now(
            f"{config.solomon_interactor}-solomon-native-completion"
        )
        dead_at_completion = [
            role
            for role, state in (
                ("host", solomon_completion["host"]),
                ("client B", solomon_completion["clientB"]),
            )
            if float(state["player"]["hp"]) <= 0.0
        ]
        if dead_at_completion:
            raise RealFlowFailure(
                "a participant died before the client completed Solomon Dig: "
                + ", ".join(dead_at_completion)
            )

        if config.bot_play_for_me and config.endurance_mode:
            assert endurance_client_prearm is not None
            result["botPlayForMe"] = _run_bot_play_endurance(
                config,
                host,
                client,
                host_pipe,
                client_pipe,
                sampler,
                endurance_client_prearm["request"],
            )
            result["clientEnemyMaterialization"] = result[
                "botPlayForMe"
            ]["clientEnemyMaterialization"]
            result["completedPhase"] = result["botPlayForMe"][
                "completedPhase"
            ]
            result["ok"] = True
            return result

        result["clientEnemyMaterialization"] = (
            _wait_for_client_enemy_materialization(config, sampler)
        )

        if config.bot_play_for_me:
            assert bot_play_mixed_mode is not None
            result["botPlayForMe"] = _run_bot_play_for_me(
                config,
                host,
                client,
                host_pipe,
                client_pipe,
                sampler,
                bot_play_mixed_mode,
            )
            result["completedPhase"] = result["botPlayForMe"][
                "completedPhase"
            ]
            result["ok"] = True
            return result

        sampler.set_phase("client-real-water-damage")
        if config.require_water_contact_observation:
            water_cast = observe_water_cast_with_real_input(
                config.source_root,
                client,
                client_pipe,
                host_pipe,
                timeout=config.timeout_seconds,
            )
            result["stockWaterCast"] = validate_stock_water_cast(
                water_cast,
                expected_contact_damage=(
                    config.expected_water_contact_damage
                ),
            )
            result["clientEnemyDamage"] = water_cast
        else:
            result["clientEnemyDamage"] = (
                damage_enemy_with_real_input(
                    config.source_root,
                    client,
                    client_pipe,
                    timeout=config.timeout_seconds,
                )
            )
        sampler.sample_now("client-damage-observed")

        sampler.set_phase("paired-render-capture")
        capture_state = sampler.sample_now("paired-capture-state")
        result["pairedCapture"] = paired_windows_capture(
            config.source_root,
            host,
            client,
            config.evidence_root / "screenshots",
            label="first-wave",
        )
        client_capture_path = Path(
            result["pairedCapture"]["captures"]["clientB"]["path"]
        )
        result["clientEnemyRendered"] = rendered_enemy_assertion(
            capture_state["clientB"],
            client_capture_path,
        )

        sampler.set_phase("enemy-motion")
        motion_deadline = time.monotonic() + min(
            5.0,
            config.timeout_seconds,
        )
        while time.monotonic() < motion_deadline:
            sampler.sample_now("enemy-motion")
            time.sleep(max(0.1, config.sampling_seconds))
        result["clientEnemyMotion"] = enemy_motion_assertion(sampler.rows)
        result["clientEnemyAttack"] = enemy_attack_assertion(sampler.rows)

        result["postDamageCapture"] = paired_windows_capture(
            config.source_root,
            host,
            client,
            config.evidence_root / "screenshots",
            label="post-client-damage",
        )
        if config.verify_through_wave >= 2:
            sampler.set_phase(
                f"client-wave-clear-through-{config.verify_through_wave}"
            )
            result["waveAdvance"] = (
                drive_combat_to_wave_with_real_input(
                    config.source_root,
                    client,
                    client_pipe,
                    host_pipe,
                    target_wave=config.verify_through_wave,
                    timeout=config.timeout_seconds,
                    sample=sampler.sample_now,
                )
            )
            final_wave = sampler.sample_now(
                f"wave-{config.verify_through_wave}-converged"
            )
            result["waveBoundaryPositions"] = [
                validate_living_wave_boundary(
                    sampler.rows,
                    target_wave=target_wave,
                    maximum_displacement=(
                        config.wave_boundary_max_displacement
                    ),
                )
                for target_wave in range(
                    2,
                    config.verify_through_wave + 1,
                )
            ]
            result["waveConvergence"] = validate_wave_convergence(
                final_wave["host"],
                final_wave["clientB"],
                target_wave=config.verify_through_wave,
            )
            result["wave2Capture"] = paired_windows_capture(
                config.source_root,
                host,
                client,
                config.evidence_root / "screenshots",
                label=f"wave-{config.verify_through_wave}",
            )
            result["completedPhase"] = (
                f"wave-{config.verify_through_wave}"
            )
        else:
            result["completedPhase"] = "full"
        result["ok"] = True
        return result
    except BaseException as exc:
        primary_error = exc
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        return result
    finally:
        if sampler_started:
            try:
                sampler.stop()
                result["sampler"] = {
                    "rowCount": len(sampler.rows),
                    "errors": sampler.errors,
                }
            except BaseException as exc:
                cleanup["samplerStopError"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                result["ok"] = False
        cleanup["localLuaPipeClose"] = {}
        local_pipes = {"host": host_pipe}
        if not is_ws20:
            local_pipes["clientB"] = client_pipe
        for role, pipe in local_pipes.items():
            try:
                pipe.close()
                cleanup["localLuaPipeClose"][role] = "closed"
            except BaseException as exc:
                cleanup["localLuaPipeClose"][role] = (
                    f"{type(exc).__name__}: {exc}"
                )
                result["ok"] = False
        try:
            cleanup["processClose"] = close_exact_owned_processes(ps, peers)
        except BaseException as exc:
            cleanup["processCloseError"] = f"{type(exc).__name__}: {exc}"
            result["ok"] = False
        if is_ws20:
            try:
                cleanup["clientBProcessClose"] = client.close_processes()
            except BaseException as exc:
                cleanup["clientBProcessCloseError"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                result["ok"] = False
        try:
            time.sleep(0.5)
            result["artifacts"] = {
                "host": _copy_and_account(
                    host,
                    config.evidence_root / "runtime",
                    require_steam_transport=is_ws20,
                ),
                "clientB": _copy_and_account(
                    client,
                    config.evidence_root / "runtime",
                    require_steam_transport=is_ws20,
                ),
            }
        except BaseException as exc:
            cleanup["artifactError"] = f"{type(exc).__name__}: {exc}"
            result["ok"] = False
        if is_ws20:
            try:
                client.delete_run()
                cleanup["clientBRunDeleted"] = True
            except BaseException as exc:
                cleanup["clientBRunDeleteError"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                result["ok"] = False
            try:
                assert connection is not None
                assert remote_stage_claimed
                connection.remove_stage_root()
                cleanup["clientBStageDeleted"] = True
            except BaseException as exc:
                cleanup["clientBStageDeleteError"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                result["ok"] = False
        try:
            if staging_root.is_dir():
                shutil.rmtree(staging_root)
                cleanup["stagingDeleted"] = str(staging_root)
        except BaseException as exc:
            cleanup["stagingDeleteError"] = (
                f"{type(exc).__name__}: {exc}"
            )
            result["ok"] = False
        try:
            after_ports = port_inventory(ps, ports)
            after_owned = _owned_process_rows(ps, peers)
            remote_after = (
                connection.inventory()
                if connection is not None
                else None
            )
            write_json(
                config.evidence_root / "safety" / "after.json",
                {
                    "utcNanoseconds": time.time_ns(),
                    "reservedPorts": after_ports,
                    "ownedProcesses": after_owned,
                    **(
                        {"clientBRemote": remote_after}
                        if remote_after is not None
                        else {}
                    ),
                },
            )
            expected_remote_after = {
                "stageRootExists": False,
                "ownedProcessCount": 0,
                "taskCount": 0,
                "interactiveSteamCount": 1,
            }
            if (
                after_ports
                or after_owned
                or (
                    remote_after is not None
                    and remote_after != expected_remote_after
                )
            ):
                cleanup["residualSafetyFailure"] = {
                    "reservedPorts": after_ports,
                    "ownedProcesses": after_owned,
                    "clientBRemote": remote_after,
                }
                result["ok"] = False
        except BaseException as exc:
            cleanup["afterInventoryError"] = (
                f"{type(exc).__name__}: {exc}"
            )
            result["ok"] = False
        result["cleanup"] = cleanup
        if connection is not None:
            connection.close()
        if primary_error is None and not result["ok"]:
            result.setdefault(
                "error",
                {
                    "type": "CleanupFailure",
                    "message": "the real flow passed but cleanup/evidence failed",
                },
            )
        write_json(config.evidence_root / "result.json", result)
        write_manifest(config.evidence_root)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Drive the real desktop-launcher multiplayer flow, host-native "
            "Start Match, host physical Solomon Dig conversation, and client "
            "enemy render/combat assertions."
        )
    )
    parser.add_argument("config", type=Path)
    parser.add_argument(
        "--phase",
        choices=("shared-hub", "full"),
        default="full",
        help="shared-hub is a bounded calibration run; full is acceptance",
    )
    args = parser.parse_args()
    try:
        config = HarnessConfig.load(args.config)
        result = run(config, phase=args.phase)
    except (
        ConfigError,
        EvidenceError,
        RealFlowFailure,
        RuntimeProbeError,
        RemoteHarnessError,
        WanFlowFailure,
        WindowsHarnessError,
        Ws20HarnessError,
    ) as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if not result["ok"]:
        print(
            "FAIL: " + json.dumps(result.get("error", {}), sort_keys=True),
            file=sys.stderr,
        )
        return 1
    print(
        "PASS: "
        + json.dumps(
            {
                "evidenceRoot": str(config.evidence_root),
                "runName": config.run_name,
                "topology": config.topology,
                "completedPhase": result["completedPhase"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
