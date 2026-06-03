#!/usr/bin/env python3
"""Verify remote player spell-cast presentation sync over local multiplayer."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

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
    lua,
    parse_key_values,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)


ROOT = Path(__file__).resolve().parent.parent
HOST_LOG = ROOT / "runtime/instances/local-mp-host/stage/.sdmod/logs/solomondarkmodloader.log"
CLIENT_LOG = ROOT / "runtime/instances/local-mp-client/stage/.sdmod/logs/solomondarkmodloader.log"


@dataclass(frozen=True)
class CastDirection:
    name: str
    source_id: int
    source_name: str
    source_pipe: str
    source_log: Path
    receiver_pipe: str
    receiver_log: Path


CLIENT_TO_HOST = CastDirection(
    name="client_to_host",
    source_id=CLIENT_ID,
    source_name=CLIENT_NAME,
    source_pipe=CLIENT_PIPE,
    source_log=CLIENT_LOG,
    receiver_pipe=HOST_PIPE,
    receiver_log=HOST_LOG,
)
HOST_TO_CLIENT = CastDirection(
    name="host_to_client",
    source_id=HOST_ID,
    source_name=HOST_NAME,
    source_pipe=HOST_PIPE,
    source_log=HOST_LOG,
    receiver_pipe=CLIENT_PIPE,
    receiver_log=CLIENT_LOG,
)


PROJECTILE_PRESENTATION_LUA = """
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local actors = sd.world.list_actors and sd.world.list_actors() or {}
local first_fire = nil
local fire_count = 0
local projectile_count = 0
for _, actor in ipairs(actors) do
  local type_id = tonumber(actor.object_type_id) or 0
  if type_id == 0x7D4 or type_id == 0x7D3 or type_id == 0x7D5 then
    projectile_count = projectile_count + 1
  end
  if type_id == 0x7D4 then
    fire_count = fire_count + 1
    if first_fire == nil then
      first_fire = actor
    end
  end
end
emit("projectile_count", projectile_count)
emit("fire_count", fire_count)
if first_fire ~= nil then
  emit("fire_address", first_fire.actor_address or 0)
  emit("fire_x", first_fire.x or 0)
  emit("fire_y", first_fire.y or 0)
end
"""


CAST_CLICK_LUA = """
local function emit(key, value) print(key .. "=" .. tostring(value)) end
if sd.input and sd.input.click_normalized then
  emit("click", sd.input.click_normalized(0.5, 0.5))
end
if sd.input and sd.input.hold_mouse_left_frames then
  emit("hold", sd.input.hold_mouse_left_frames(3))
end
"""


QUEUE_PRIMARY_CAST_LUA = """
local function emit(key, value) print(key .. "=" .. tostring(value)) end
if sd.input and sd.input.queue_local_spell_cast then
  emit("queued", sd.input.queue_local_spell_cast(0, 1.0, 0.0, 0))
end
"""


def queue_primary_cast_lua(hold_frames: int) -> str:
    return f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
if sd.input and sd.input.queue_local_spell_cast then
  emit("queued", sd.input.queue_local_spell_cast(0, 1.0, 0.0, {hold_frames}))
end
"""


def remote_cast_state_lua(participant_id: int) -> str:
    return f"""
local function emit(key, value) print(key .. "=" .. tostring(value)) end
local bot = sd.bots and sd.bots.get_participant_state and sd.bots.get_participant_state({participant_id}) or nil
if bot == nil then
  emit("found", false)
  return
end
emit("found", true)
emit("entity_materialized", bot.entity_materialized or false)
emit("actor_address", bot.actor_address or 0)
emit("cast_pending", bot.cast_pending or false)
emit("cast_active", bot.cast_active or false)
emit("cast_saw_activity", bot.cast_saw_activity or false)
emit("cast_skill_id", bot.cast_skill_id or 0)
emit("cast_ticks_waiting", bot.cast_ticks_waiting or 0)
emit("active_spell_object_readable", bot.active_spell_object_readable or false)
emit("active_spell_object_address", bot.active_spell_object_address or 0)
emit("native_action_cooldown_ticks", bot.native_action_cooldown_ticks or 0)
"""


def values(pipe_name: str, code: str) -> dict[str, str]:
    return parse_key_values(lua(pipe_name, code))


def read_log(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def log_after(path: Path, offset: int) -> str:
    text = read_log(path)
    return text[offset:]


def parse_int(value: str | None, default: int = 0) -> int:
    if value in (None, ""):
        return default
    return int(value, 0)


def wait_for_local_cast_send(direction: CastDirection, log_offset: int, timeout: float = 8.0) -> str:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        last = log_after(direction.source_log, log_offset)
        if "Multiplayer local cast sent" in last:
            return last
        time.sleep(0.15)
    raise VerifyFailure(f"{direction.name}: source did not emit a local spell cast packet")


def parse_local_cast_packets(log_text: str) -> list[dict[str, object]]:
    packet_pattern = re.compile(
        r"Multiplayer local cast sent\..*?"
        r"cast_sequence=(?P<sequence>[0-9]+).*?"
        r"phase=(?P<phase>[a-z_]+).*?"
        r"skill_id=(?P<skill_id>-?[0-9]+)"
    )
    packets: list[dict[str, object]] = []
    for line in log_text.splitlines():
        match = packet_pattern.search(line)
        if not match:
            continue
        packets.append(
            {
                "sequence": int(match.group("sequence")),
                "phase": match.group("phase"),
                "skill_id": int(match.group("skill_id")),
            }
        )
    return packets


def wait_for_local_cast_phase_counts(
    direction: CastDirection,
    log_offset: int,
    required_counts: dict[str, int],
    timeout: float = 4.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_packets: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        last_packets = parse_local_cast_packets(log_after(direction.source_log, log_offset))
        sequences = sorted({int(packet["sequence"]) for packet in last_packets})
        for sequence in sequences:
            phase_counts: dict[str, int] = {}
            sequence_packets = [
                packet
                for packet in last_packets
                if int(packet["sequence"]) == sequence and int(packet["skill_id"]) == 0
            ]
            for packet in sequence_packets:
                phase = str(packet["phase"])
                phase_counts[phase] = phase_counts.get(phase, 0) + 1
            if all(phase_counts.get(phase, 0) >= count for phase, count in required_counts.items()):
                return {
                    "sequence": sequence,
                    "phase_counts": phase_counts,
                    "packets": sequence_packets,
                }
        time.sleep(0.05)
    raise VerifyFailure(
        f"{direction.name}: source cast phases did not reach {required_counts}; packets={last_packets}"
    )


def trigger_local_cast(direction: CastDirection, log_offset: int) -> dict[str, object]:
    attempts: list[dict[str, str]] = []
    for _ in range(5):
        attempts.append(values(direction.source_pipe, CAST_CLICK_LUA))
        try:
            log_text = wait_for_local_cast_send(direction, log_offset, timeout=1.0)
            native_hook = "Multiplayer local primary cast queued from native pure-primary" in log_text
            if not native_hook:
                raise VerifyFailure(f"{direction.name}: cast packet was sent without the native pure-primary hook marker")
            if "skill_id=0" not in log_text:
                raise VerifyFailure(f"{direction.name}: primary cast packet did not preserve skill_id=0")
            phases = wait_for_local_cast_phase_counts(
                direction,
                log_offset,
                {"pressed": 1, "released": 1},
                timeout=2.0,
            )
            return {
                "mode": "native_click",
                "native_hook": native_hook,
                "primary_skill_id_zero": "skill_id=0" in log_text,
                "source_cast_phases": phases,
                "attempts": attempts,
            }
        except VerifyFailure:
            time.sleep(0.2)
    queued_attempt = values(direction.source_pipe, QUEUE_PRIMARY_CAST_LUA)
    log_text = wait_for_local_cast_send(direction, log_offset, timeout=3.0)
    if "skill_id=0" not in log_text:
        raise VerifyFailure(f"{direction.name}: queued primary cast packet did not preserve skill_id=0")
    phases = wait_for_local_cast_phase_counts(
        direction,
        log_offset,
        {"pressed": 1, "released": 1},
        timeout=2.0,
    )
    return {
        "mode": "queued_transport",
        "native_attempts": attempts,
        "queued_attempt": queued_attempt,
        "primary_skill_id_zero": "skill_id=0" in log_text,
        "source_cast_phases": phases,
    }


def parse_remote_completions(log_text: str, source_id: int) -> list[dict[str, object]]:
    completions: list[dict[str, object]] = []
    label_pattern = re.compile(r"\[bots\] cast complete \((?P<label>[^)]+)\)\.")
    ticks_pattern = re.compile(r" ticks=(?P<ticks>[0-9]+) ")
    rearm_pattern = re.compile(r" native_action_rearm=(?P<rearm>[01])")
    obj_pattern = re.compile(r" obj_ptr=(?P<obj>0x[0-9A-Fa-f]+)")
    marker = f"bot_id={source_id}"
    for line in log_text.splitlines():
        if marker not in line or "[bots] cast complete" not in line:
            continue
        label = label_pattern.search(line)
        ticks = ticks_pattern.search(line)
        rearm = rearm_pattern.search(line)
        obj = obj_pattern.search(line)
        completions.append(
            {
                "label": label.group("label") if label else "",
                "ticks": int(ticks.group("ticks")) if ticks else -1,
                "native_action_rearm": int(rearm.group("rearm")) if rearm else -1,
                "obj_ptr": obj.group("obj") if obj else "",
            }
        )
    return completions


def wait_for_remote_cast_presentation(
    direction: CastDirection,
    receiver_log_offset: int,
    timeout: float = 10.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_state: dict[str, str] = {}
    last_projectile_state: dict[str, str] = {}
    last_log = ""
    queued_marker = f"Multiplayer remote cast queued. participant_id={direction.source_id}"
    prepped_marker = f"[bots] wizard cast prepped. bot_id={direction.source_id}"
    while time.monotonic() < deadline:
        last_log = log_after(direction.receiver_log, receiver_log_offset)
        last_projectile_state = values(direction.receiver_pipe, PROJECTILE_PRESENTATION_LUA)
        last_state = values(direction.receiver_pipe, remote_cast_state_lua(direction.source_id))
        queued = queued_marker in last_log
        prepped = prepped_marker in last_log
        visible_state = (
            last_state.get("active_spell_object_readable") == "true"
            and last_state.get("active_spell_object_address") not in (None, "", "0")
        )
        visible_projectile = parse_int(last_projectile_state.get("fire_count")) > 0
        completions = parse_remote_completions(last_log, direction.source_id)
        if queued and prepped and (visible_state or visible_projectile):
            return {
                "queued_log": queued,
                "prepped_log": prepped,
                "visible_state": visible_state,
                "visible_projectile": visible_projectile,
                "projectile_state": last_projectile_state,
                "completion": completions[-1] if completions else None,
                "state": last_state,
            }
        time.sleep(0.15)
    raise VerifyFailure(
        f"{direction.name}: receiver did not queue and visibly present the remote cast; "
        f"state={last_state} projectile_state={last_projectile_state} "
        f"completions={parse_remote_completions(last_log, direction.source_id)} "
        f"log_tail={last_log[-1200:]}"
    )


def wait_for_remote_completion(
    direction: CastDirection,
    receiver_log_offset: int,
    timeout: float = 8.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_log = ""
    while time.monotonic() < deadline:
        last_log = log_after(direction.receiver_log, receiver_log_offset)
        completions = parse_remote_completions(last_log, direction.source_id)
        if completions:
            return completions[-1]
        time.sleep(0.1)
    raise VerifyFailure(
        f"{direction.name}: remote cast did not complete; log_tail={last_log[-1200:]}"
    )


def observe_no_duplicate_remote_fire(
    direction: CastDirection,
    receiver_log_offset: int,
    initial_projectile_state: dict[str, str],
    duration: float = 2.3,
) -> dict[str, object]:
    deadline = time.monotonic() + duration
    fire_addresses: set[str] = set()
    initial_fire_count = parse_int(initial_projectile_state.get("fire_count"))
    max_fire_count = initial_fire_count
    initial_fire_address = initial_projectile_state.get("fire_address", "")
    if initial_fire_count > 0 and initial_fire_address not in ("", "0"):
        fire_addresses.add(initial_fire_address)
    samples = 0
    last_projectile_state: dict[str, str] = {}
    while time.monotonic() < deadline:
        samples += 1
        last_projectile_state = values(direction.receiver_pipe, PROJECTILE_PRESENTATION_LUA)
        fire_count = parse_int(last_projectile_state.get("fire_count"))
        max_fire_count = max(max_fire_count, fire_count)
        fire_address = last_projectile_state.get("fire_address", "")
        if fire_count > 0 and fire_address not in ("", "0"):
            fire_addresses.add(fire_address)
        time.sleep(0.05)

    log_text = log_after(direction.receiver_log, receiver_log_offset)
    mana_spends = sum(
        1
        for line in log_text.splitlines()
        if f"[bots] native mana delta owner context. bot_id={direction.source_id}" in line
        and " delta=-" in line
    )
    completions = parse_remote_completions(log_text, direction.source_id)
    final_state = values(direction.receiver_pipe, remote_cast_state_lua(direction.source_id))
    cooldown_rejections = sum(
        1
        for line in log_text.splitlines()
        if f"[bots] cast rejected for native action cooldown. bot_id={direction.source_id}" in line
    )

    if mana_spends > 1:
        raise VerifyFailure(f"{direction.name}: one remote cast spent mana {mana_spends} times")
    if not fire_addresses:
        raise VerifyFailure(f"{direction.name}: receiver never observed the remote fire projectile")
    if len(fire_addresses) > 1:
        raise VerifyFailure(f"{direction.name}: one remote cast produced multiple fire projectile actors: {sorted(fire_addresses)}")
    if not completions:
        raise VerifyFailure(f"{direction.name}: remote cast never completed")
    completion = completions[-1]
    if int(completion["ticks"]) > 60:
        raise VerifyFailure(f"{direction.name}: remote pure-primary cast stayed active too long: {completion}")
    if int(completion["native_action_rearm"]) != 0:
        raise VerifyFailure(f"{direction.name}: remote player mirror cast wrote AI native-action rearm: {completion}")
    if cooldown_rejections:
        raise VerifyFailure(f"{direction.name}: remote player cast was rejected by AI native-action cooldown")
    if final_state.get("cast_active") == "true":
        raise VerifyFailure(f"{direction.name}: remote cast still active after settle window: {final_state}")

    return {
        "samples": samples,
        "max_fire_count": max_fire_count,
        "fire_addresses": sorted(fire_addresses),
        "mana_spend_log_count": mana_spends,
        "completion": completion,
        "final_state": final_state,
        "last_projectile_state": last_projectile_state,
    }


def verify_held_cast_direction(direction: CastDirection) -> dict[str, object]:
    source_log_offset = len(read_log(direction.source_log))
    receiver_log_offset = len(read_log(direction.receiver_log))
    queued_attempt = values(direction.source_pipe, queue_primary_cast_lua(120))
    held_phases = wait_for_local_cast_phase_counts(
        direction,
        source_log_offset,
        {"pressed": 1, "held": 3},
        timeout=3.0,
    )
    presentation = wait_for_remote_cast_presentation(
        direction,
        receiver_log_offset,
        timeout=6.0,
    )
    early_completions = parse_remote_completions(
        log_after(direction.receiver_log, receiver_log_offset),
        direction.source_id,
    )
    if early_completions:
        raise VerifyFailure(
            f"{direction.name}: held cast completed before source release: {early_completions[-1]}"
        )
    held_state = values(direction.receiver_pipe, remote_cast_state_lua(direction.source_id))
    if held_state.get("cast_active") != "true":
        raise VerifyFailure(f"{direction.name}: held remote cast was not active: {held_state}")

    released_phases = wait_for_local_cast_phase_counts(
        direction,
        source_log_offset,
        {"pressed": 1, "held": 3, "released": 1},
        timeout=5.0,
    )
    completion = wait_for_remote_completion(direction, receiver_log_offset)
    if int(completion["native_action_rearm"]) != 0:
        raise VerifyFailure(f"{direction.name}: held remote cast wrote AI native-action rearm: {completion}")
    if completion["label"] == "remote_input_timeout":
        raise VerifyFailure(f"{direction.name}: held remote cast completed by timeout instead of release: {completion}")
    receiver_log = log_after(direction.receiver_log, receiver_log_offset)
    if f"Multiplayer remote cast input release. participant_id={direction.source_id}" not in receiver_log:
        raise VerifyFailure(f"{direction.name}: receiver did not process remote cast release")
    final_state = values(direction.receiver_pipe, remote_cast_state_lua(direction.source_id))
    if final_state.get("cast_active") == "true":
        raise VerifyFailure(f"{direction.name}: held remote cast still active after release: {final_state}")

    return {
        "queued_attempt": queued_attempt,
        "held_phases": held_phases,
        "released_phases": released_phases,
        "receiver_cast": presentation,
        "completion": completion,
        "final_state": final_state,
    }


def verify_direction(direction: CastDirection) -> dict[str, object]:
    source_log_offset = len(read_log(direction.source_log))
    receiver_log_offset = len(read_log(direction.receiver_log))
    trigger = trigger_local_cast(direction, source_log_offset)
    presentation = wait_for_remote_cast_presentation(direction, receiver_log_offset)
    duplicate_check = observe_no_duplicate_remote_fire(
        direction,
        receiver_log_offset,
        presentation["projectile_state"],
    )
    return {
        "trigger": trigger,
        "receiver_cast": presentation,
        "duplicate_check": duplicate_check,
    }


def wait_for_remote_entity_materialized(
    pipe_name: str,
    participant_id: int,
    timeout: float = 12.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last_state: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_state = values(pipe_name, remote_cast_state_lua(participant_id))
        if (
            last_state.get("found") == "true"
            and last_state.get("entity_materialized") == "true"
            and last_state.get("actor_address") not in (None, "", "0")
        ):
            return last_state
        time.sleep(0.2)
    raise VerifyFailure(f"remote participant {participant_id} did not materialize on {pipe_name}: {last_state}")


def main() -> int:
    result: dict[str, object] = {"ok": False}
    try:
        stop_games()
        result["launch"] = launch_pair()
        disable_bots()
        result["run_entry"] = start_host_testrun_and_wait_for_clients()
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "testrun")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "testrun")
        result["remote_entities"] = {
            "client_on_host": wait_for_remote_entity_materialized(HOST_PIPE, CLIENT_ID),
            "host_on_client": wait_for_remote_entity_materialized(CLIENT_PIPE, HOST_ID),
        }

        result[CLIENT_TO_HOST.name] = verify_direction(CLIENT_TO_HOST)
        time.sleep(0.5)
        result[HOST_TO_CLIENT.name] = verify_direction(HOST_TO_CLIENT)
        time.sleep(0.5)
        result["held_client_to_host"] = verify_held_cast_direction(CLIENT_TO_HOST)
        result["ok"] = True
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    finally:
        stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
