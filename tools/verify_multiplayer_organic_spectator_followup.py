#!/usr/bin/env python3
"""Verify organic spectated death and Ether-minion spectator isolation."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable

import multiplayer_secondary_behavior_harness as secondary
import verify_multiplayer_focus_behavior_sync as focus
from multiplayer_frame_capture import capture_game_backbuffer
from multiplayer_log_probe import log_position
from multiplayer_progression_probe import query_progression_snapshot
from normal_gameplay_debug_surface_guard import (
    assert_launch_debug_surfaces_empty,
)
from spectator_product_hud_guard import (
    assert_spectator_product_hud_lifecycle,
    assert_spectator_product_hud_never_visible,
    parse_spectator_product_hud_states,
    wait_for_spectator_product_hud_state,
)
from spectator_product_hud_visual import (
    inspect_spectator_product_hud_pixels,
)
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    HOST_ID,
    HOST_NAME,
    ROOT,
    THIRD_ID,
    THIRD_NAME,
    VerifyFailure,
    game_process_ids,
    launch_pair,
    lua,
    parse_key_values,
    select_available_windows_udp_ports,
    stop_game_processes,
    wait_for_remote,
    wait_for_scene,
)
from verify_multiplayer_death_spectator_respawn import (
    _arm_death_traces,
    _disarm_death_traces,
    query_spectator_state,
)
from verify_multiplayer_organic_player_death import (
    ACCEPTANCE_MOD_ID,
    DEATH_PRESENTATION_SECONDS,
    LIFECYCLE_TIMEOUT_SECONDS,
    SURVIVOR_HP,
    VICTIM_ARMING_HP,
    VICTIM_MAX_HP,
    WAVE_FIXTURES,
    _arm_enemy_arena,
    _assert_lifecycle,
    _disable_companion_bots,
    _finish_wave,
    _materialize_native_wave_schedule,
    _query_live_enemies,
    _sample_lifecycle,
    _set_enemy_attack,
    _set_enemy_idle,
    _small_state,
    _stabilize_enemy,
    _start_testrun_when_ready,
    _start_waves,
    _wait_for_new_wave_enemy,
    _wait_for_respawn,
    _wait_for_victim_damage,
)
from verify_player_health_death_sync import set_local_player_vitals


OUTPUT = (
    ROOT
    / "runtime"
    / "multiplayer_organic_spectator_followup.json"
)
ARTIFACT_ROOT = (
    ROOT
    / "runtime"
    / "multiplayer_organic_spectator_followup"
)
ETHER_MINION_NATIVE_TYPE_ID = 0x07F2
CALL_LEVIATHAN_SKILL_ROW = 11


class OrganicSpectatorFollowupFailure(VerifyFailure):
    """Live verifier failure that retains the evidence captured so far."""

    def __init__(self, message: str, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


QUERY_NATIVE_TYPE_COUNT_LUA = r"""
local native_type_id = __NATIVE_TYPE_ID__
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local count = 0
for _, actor in ipairs(sd.world.list_actors and sd.world.list_actors() or {}) do
  if (tonumber(actor.object_type_id) or 0) == native_type_id then
    count = count + 1
  end
end
emit("native_type_id", native_type_id)
emit("count", count)
"""


def _default_instance_prefix() -> str:
    return f"orgsf-{uuid.uuid4().hex[:10]}"


def _assert_spectated_target_hold(
    lifecycle: list[dict[str, Any]],
    *,
    expected_participant_id: int,
) -> dict[str, Any]:
    presentation_samples = [
        sample
        for sample in lifecycle
        if sample.get("spectator_hold", {}).get(
            "expected_target_presentation_active"
        ) == "true"
    ]
    if not presentation_samples:
        raise VerifyFailure(
            "spectated target lifecycle contained no death-presentation "
            "samples"
        )

    target_names: set[str] = set()
    for sample in presentation_samples:
        spectator = sample.get("spectator_hold")
        if not isinstance(spectator, dict):
            raise VerifyFailure(
                "spectated target lifecycle omitted spectator target state"
            )
        target_id = int(spectator.get("target_participant_id", "0"))
        if target_id != expected_participant_id:
            raise VerifyFailure(
                "spectator target migrated during the death presentation: "
                f"expected={expected_participant_id} observed={target_id} "
                f"sample={sample}"
            )
        target_name = spectator.get("target_name", "")
        if target_name:
            target_names.add(str(target_name))

    span_seconds = (
        float(presentation_samples[-1]["elapsed_seconds"])
        - float(presentation_samples[0]["elapsed_seconds"])
    )
    if span_seconds < DEATH_PRESENTATION_SECONDS - 0.5:
        raise VerifyFailure(
            "spectator target was not held through the full five-second "
            f"presentation: span={span_seconds:.3f}s"
        )
    return {
        "expected_participant_id": expected_participant_id,
        "sample_count": len(presentation_samples),
        "span_seconds": span_seconds,
        "target_names": sorted(target_names),
        "target_stayed_attached": True,
    }


def _assert_ether_minion_counts(
    peer_counts: dict[str, dict[str, str]],
) -> dict[str, Any]:
    missing = {
        role: values
        for role, values in peer_counts.items()
        if (
            int(values.get("native_type_id", "0"))
                != ETHER_MINION_NATIVE_TYPE_ID
            or int(values.get("count", "0")) < 1
        )
    }
    if missing:
        raise VerifyFailure(
            "Call Leviathan did not materialize on every peer: "
            f"{missing}"
        )
    return {
        "native_type_id": ETHER_MINION_NATIVE_TYPE_ID,
        "minimum_peer_count": min(
            int(values["count"])
            for values in peer_counts.values()
        ),
        "all_peers_materialized": True,
    }


def _capture_rendered_backbuffer(
    pipe_name: str,
    output_path: Path,
    *,
    capture: Callable[[str, Path], dict[str, Any]] =
        capture_game_backbuffer,
    attempts: int = 5,
    retry_delay: float = 0.05,
) -> dict[str, Any]:
    blank_frame_errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            evidence = capture(pipe_name, output_path)
            evidence["capture_attempt"] = attempt
            evidence["blank_frame_retries"] = len(blank_frame_errors)
            return evidence
        except VerifyFailure as exc:
            message = str(exc)
            if "blank or low-information" not in message:
                raise
            blank_frame_errors.append(message)
            if attempt < attempts:
                time.sleep(retry_delay)
    raise VerifyFailure(
        "D3D9 backbuffer stayed blank through bounded terminal-frame "
        f"retries: pipe={pipe_name} attempts={attempts} "
        f"errors={blank_frame_errors}"
    )


def _wait_for_native_type_counts(
    pipes: dict[str, str],
    *,
    native_type_id: int,
    timeout: float,
) -> dict[str, dict[str, str]]:
    code = QUERY_NATIVE_TYPE_COUNT_LUA.replace(
        "__NATIVE_TYPE_ID__",
        str(native_type_id),
    )
    deadline = time.monotonic() + timeout
    last: dict[str, dict[str, str]] = {}
    while time.monotonic() < deadline:
        last = {
            role: parse_key_values(lua(pipe_name, code))
            for role, pipe_name in pipes.items()
        }
        if all(
            int(values.get("count", "0")) >= 1
            for values in last.values()
        ):
            return last
        time.sleep(0.05)
    raise VerifyFailure(
        f"native actor type 0x{native_type_id:X} did not materialize on "
        f"every peer: {last}"
    )


def _wait_for_spectator_target(
    pipe_name: str,
    *,
    expected_participant_id: int,
    timeout: float,
    allow_cycle: bool,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    next_cycle_at = 0.0
    while time.monotonic() < deadline:
        last = query_spectator_state(pipe_name)
        if (
            last.get("active") == "true"
            and last.get("phase") == "Spectating"
            and int(last.get("target_participant_id", "0"))
                == expected_participant_id
        ):
            return last
        now = time.monotonic()
        if (
            allow_cycle
            and last.get("phase") == "Spectating"
            and now >= next_cycle_at
        ):
            lua(
                pipe_name,
                "return tostring("
                "sd.input.click_normalized(0.5, 0.5))",
            )
            next_cycle_at = now + 0.35
        time.sleep(0.05)
    raise VerifyFailure(
        "spectator did not select the expected target "
        f"{expected_participant_id}: {last}"
    )


def _participant_log(instance_prefix: str, role: str) -> Path:
    return (
        ROOT
        / "runtime"
        / "instances"
        / f"{instance_prefix}-{role}"
        / "stage"
        / ".sdmod"
        / "logs"
        / "solomondarkmodloader.log"
    )


def _arm_organic_target_death(
    *,
    host_pipe: str,
    victim_pipe: str,
    victim_participant_id: int,
    enemy_actor_address: int,
) -> dict[str, Any]:
    victim = query_spectator_state(victim_pipe)
    target_x = float(victim["x"])
    target_y = float(victim["y"])
    baseline_hp = float(victim["hp"])
    attack = _set_enemy_attack(
        host_pipe,
        target_x=target_x,
        target_y=target_y,
        target_participant_id=victim_participant_id,
        enemy_actor_address=enemy_actor_address,
        attack_distance=64.0,
    )
    damage = _wait_for_victim_damage(
        victim_pipe,
        baseline_hp=baseline_hp,
        timeout=18.0,
    )
    armed = set_local_player_vitals(
        victim_pipe,
        VICTIM_ARMING_HP,
        VICTIM_MAX_HP,
    )
    return {
        "victim_before": victim,
        "enemy_attack": attack,
        "enemy_damage_observed": damage,
        "victim_armed": armed,
    }


def run_live_verification(
    *,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path,
    launcher_path: Path | None,
    enable_audio: bool,
) -> dict[str, Any]:
    artifact_directory = ARTIFACT_ROOT / instance_prefix
    retail_wave_path = game_directory.resolve() / "data" / "wave.txt"
    effective_wave_path = artifact_directory / "effective-melee-wave.txt"
    wave_schedule = _materialize_native_wave_schedule(
        retail_wave_path=retail_wave_path,
        fixture_path=WAVE_FIXTURES["melee"],
        output_path=effective_wave_path,
    )
    if wave_schedule["record_count"] != 42:
        raise VerifyFailure(
            "organic spectator follow-up expected the 42-record retail "
            f"wave graph: {wave_schedule}"
        )

    launch = launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset="map_create_air_mind_hub",
        third_preset="map_create_ether_mind_hub",
        temporary_host_profile=True,
        tile_windows=False,
        test_blank_boneyard=True,
        test_wave_override=effective_wave_path,
        third_player=True,
        use_sandbox_preset_flow=True,
        kill_existing=False,
        instance_prefix=instance_prefix,
        host_port=ports[0],
        client_port=ports[1],
        third_port=ports[2],
        game_directory=game_directory,
        launcher_path=launcher_path,
        exact_mod_id=ACCEPTANCE_MOD_ID,
        enable_audio=enable_audio,
    )
    process_ids = game_process_ids(launch)
    if len(process_ids) != 3:
        stop_game_processes(process_ids)
        raise VerifyFailure(
            f"isolated spectator follow-up did not report three PIDs: "
            f"{launch}"
        )

    host_pipe = str(launch["hostLuaPipe"])
    client_pipe = str(launch["clientLuaPipe"])
    third_pipe = str(launch["thirdLuaPipe"])
    pipes = {
        "host": host_pipe,
        "client": client_pipe,
        "third": third_pipe,
    }
    host_log = _participant_log(instance_prefix, "host")
    client_log = _participant_log(instance_prefix, "client")
    third_log = _participant_log(instance_prefix, "third")
    result: dict[str, Any] = {
        "launch": launch,
        "process_ids": process_ids,
        "instance_prefix": instance_prefix,
        "ports": ports,
        "wave_schedule": wave_schedule,
        "screenshots": {},
    }
    try:
        _disable_companion_bots(list(pipes.values()))
        _start_testrun_when_ready(host_pipe)
        for pipe_name in pipes.values():
            wait_for_scene(pipe_name, "testrun", 45.0)

        for pipe_name in pipes.values():
            set_local_player_vitals(
                pipe_name,
                SURVIVOR_HP,
                SURVIVOR_HP,
            )
        participants = (
            (host_pipe, HOST_ID, HOST_NAME),
            (client_pipe, CLIENT_ID, CLIENT_NAME),
            (third_pipe, THIRD_ID, THIRD_NAME),
        )
        relationships: dict[str, dict[str, str]] = {}
        for observer_pipe, observer_id, _ in participants:
            for _, owner_id, owner_name in participants:
                if owner_id == observer_id:
                    continue
                relationships[
                    f"{observer_id:x}_observes_{owner_id:x}"
                ] = wait_for_remote(
                    observer_pipe,
                    owner_id,
                    owner_name,
                    "testrun",
                    45.0,
                )
        result["relationships"] = relationships
        result["product_hud_alive"] = (
            wait_for_spectator_product_hud_state(
                [host_log, client_log, third_log],
                context="alive",
                expected_active=False,
                expected_phase="Inactive",
                expected_registered=False,
                expected_rendered=False,
                expected_target_participant_id=0,
                timeout=5.0,
            )
        )
        result["death_traces_armed"] = _arm_death_traces(
            list(pipes.values())
        )

        pre_wave_enemies = _query_live_enemies(host_pipe)
        pre_wave_actor_addresses = {
            int(actor["actor_address"])
            for actor in pre_wave_enemies
        }
        result["pre_wave_actor_addresses"] = sorted(
            pre_wave_actor_addresses
        )
        result["wave_start"] = _start_waves(host_pipe)
        enemy = _wait_for_new_wave_enemy(
            host_pipe,
            pre_wave_actor_addresses=pre_wave_actor_addresses,
        )
        result["enemy"] = enemy

        client_before = query_spectator_state(client_pipe)
        result["enemy_arena"] = _arm_enemy_arena(
            host_pipe,
            float(client_before["x"]),
            float(client_before["y"]),
        )
        result["enemy_stabilized"] = _stabilize_enemy(
            host_pipe,
            enemy_actor_address=int(enemy["actor_address"]),
        )
        result["first_organic_death_armed"] = (
            _arm_organic_target_death(
                host_pipe=host_pipe,
                victim_pipe=client_pipe,
                victim_participant_id=CLIENT_ID,
                enemy_actor_address=int(enemy["actor_address"]),
            )
        )
        first_lifecycle, first_milestones = _sample_lifecycle(
            victim_pipe=client_pipe,
            observer_pipe=host_pipe,
            victim_id=CLIENT_ID,
            timeout=LIFECYCLE_TIMEOUT_SECONDS["melee"],
        )
        result["first_lifecycle_samples"] = first_lifecycle
        result["first_milestones"] = first_milestones
        result["first_grace_seconds"] = _assert_lifecycle(
            first_lifecycle,
            first_milestones,
        )
        result["enemy_idle_between_deaths"] = _set_enemy_idle(host_pipe)

        result["spectating_ether_target"] = _wait_for_spectator_target(
            client_pipe,
            expected_participant_id=THIRD_ID,
            timeout=8.0,
            allow_cycle=True,
        )
        result["product_hud_spectating_ether_target"] = (
            wait_for_spectator_product_hud_state(
                [client_log],
                context="spectating",
                expected_active=True,
                expected_phase="Spectating",
                expected_registered=True,
                expected_rendered=True,
                expected_target_participant_id=THIRD_ID,
                timeout=5.0,
            )
        )
        result["product_hud_alive_target_peers"] = (
            wait_for_spectator_product_hud_state(
                [host_log, third_log],
                context="alive",
                expected_active=False,
                expected_phase="Inactive",
                expected_registered=False,
                expected_rendered=False,
                expected_target_participant_id=0,
                timeout=5.0,
            )
        )
        result["screenshots"]["before_ether_minion"] = (
            capture_game_backbuffer(
                client_pipe,
                artifact_directory / "before-ether-minion.png",
            )
        )
        result["product_hud_pixels_before_minion"] = (
            inspect_spectator_product_hud_pixels(
                artifact_directory / "before-ether-minion.png",
                expected_visible=True,
            )
        )

        third_progression = query_progression_snapshot(third_pipe)
        third_belt = third_progression["loadout"][
            "secondary_entry_indices"
        ]
        if not third_belt or third_belt[0] != CALL_LEVIATHAN_SKILL_ROW:
            raise VerifyFailure(
                "Ether participant did not have Call Leviathan on default "
                f"right-click belt slot: {third_belt}"
            )
        result["third_default_belt"] = third_belt
        direction = focus.Direction(
            name="ether_target_while_spectated",
            process_role="third",
            source_id=THIRD_ID,
            source_pipe=third_pipe,
            source_log=third_log,
            observer_log=client_log,
        )
        source_offset = log_position(third_log)
        observer_offset = log_position(client_log)
        result["call_leviathan_input"] = (
            focus.cast_secondary_belt_slot(
                direction,
                0,
                8.0,
            )
        )
        result["call_leviathan_delivery"] = (
            secondary.wait_for_secondary_delivery(
                direction,
                CALL_LEVIATHAN_SKILL_ROW,
                0,
                source_offset,
                observer_offset,
                10.0,
            )
        )
        minion_counts = _wait_for_native_type_counts(
            pipes,
            native_type_id=ETHER_MINION_NATIVE_TYPE_ID,
            timeout=10.0,
        )
        result["ether_minion_counts"] = minion_counts
        result["ether_minion_materialization"] = (
            _assert_ether_minion_counts(minion_counts)
        )
        result["spectating_ether_target_after_minion"] = (
            _wait_for_spectator_target(
                client_pipe,
                expected_participant_id=THIRD_ID,
                timeout=3.0,
                allow_cycle=False,
            )
        )
        result["product_hud_after_ether_minion"] = (
            wait_for_spectator_product_hud_state(
                [client_log],
                context="spectating",
                expected_active=True,
                expected_phase="Spectating",
                expected_registered=True,
                expected_rendered=True,
                expected_target_participant_id=THIRD_ID,
                timeout=5.0,
            )
        )
        result["screenshots"]["after_ether_minion"] = (
            capture_game_backbuffer(
                client_pipe,
                artifact_directory / "after-ether-minion.png",
            )
        )
        result["screenshots"]["ether_minion_owner"] = (
            capture_game_backbuffer(
                third_pipe,
                artifact_directory / "ether-minion-owner.png",
            )
        )
        result["product_hud_pixels_after_minion"] = {
            "spectator_visible":
                inspect_spectator_product_hud_pixels(
                    artifact_directory / "after-ether-minion.png",
                    expected_visible=True,
                ),
            "alive_owner_hidden":
                inspect_spectator_product_hud_pixels(
                    artifact_directory / "ether-minion-owner.png",
                    expected_visible=False,
                ),
        }
        result["normal_surface_guard_after_minion"] = (
            assert_launch_debug_surfaces_empty(
                launch,
                roles=("host", "client", "third"),
                context="spectating_after_ether_minion",
            )
        )

        third_before = query_spectator_state(third_pipe)
        result["enemy_arena_for_spectated_death"] = _arm_enemy_arena(
            host_pipe,
            float(third_before["x"]),
            float(third_before["y"]),
        )
        result["enemy_restabilized"] = _stabilize_enemy(
            host_pipe,
            enemy_actor_address=int(enemy["actor_address"]),
        )
        result["spectated_organic_death_armed"] = (
            _arm_organic_target_death(
                host_pipe=host_pipe,
                victim_pipe=third_pipe,
                victim_participant_id=THIRD_ID,
                enemy_actor_address=int(enemy["actor_address"]),
            )
        )

        terminal_screenshots: dict[str, Any] = {}

        def capture_terminal_corpse_frames() -> None:
            terminal_screenshots["spectator"] = (
                _capture_rendered_backbuffer(
                    client_pipe,
                    artifact_directory
                    / "spectated-target-terminal-corpse.png",
                )
            )
            terminal_screenshots["owner"] = _capture_rendered_backbuffer(
                third_pipe,
                artifact_directory
                / "spectated-target-owner-terminal-corpse.png",
            )

        target_lifecycle, target_milestones = _sample_lifecycle(
            victim_pipe=third_pipe,
            observer_pipe=client_pipe,
            victim_id=THIRD_ID,
            timeout=LIFECYCLE_TIMEOUT_SECONDS["melee"],
            spectator_hold_pipe=client_pipe,
            terminal_frame_callback=capture_terminal_corpse_frames,
        )
        result["spectated_target_lifecycle_samples"] = target_lifecycle
        result["spectated_target_milestones"] = target_milestones
        result["spectated_target_grace_seconds"] = _assert_lifecycle(
            target_lifecycle,
            target_milestones,
        )
        result["spectated_target_hold"] = (
            _assert_spectated_target_hold(
                target_lifecycle,
                expected_participant_id=THIRD_ID,
            )
        )
        if set(terminal_screenshots) != {"spectator", "owner"}:
            raise VerifyFailure(
                "terminal corpse screenshots were not captured on both "
                f"peers: {terminal_screenshots}"
            )
        result["screenshots"].update(
            {
                "spectated_target_terminal_corpse":
                    terminal_screenshots["spectator"],
                "spectated_target_owner_terminal_corpse":
                    terminal_screenshots["owner"],
            }
        )
        result["product_hud_pixels_terminal_corpse"] = {
            "spectator_visible":
                inspect_spectator_product_hud_pixels(
                    artifact_directory
                    / "spectated-target-terminal-corpse.png",
                    expected_visible=True,
                ),
            "death_presentation_owner_hidden":
                inspect_spectator_product_hud_pixels(
                    artifact_directory
                    / "spectated-target-owner-terminal-corpse.png",
                    expected_visible=False,
                ),
        }
        result["automatic_retarget_after_grace"] = (
            _wait_for_spectator_target(
                client_pipe,
                expected_participant_id=HOST_ID,
                timeout=4.0,
                allow_cycle=False,
            )
        )
        result["product_hud_after_target_grace"] = {
            "client": wait_for_spectator_product_hud_state(
                [client_log],
                context="spectating",
                expected_active=True,
                expected_phase="Spectating",
                expected_registered=True,
                expected_rendered=True,
                expected_target_participant_id=HOST_ID,
                timeout=5.0,
            ),
            "third": wait_for_spectator_product_hud_state(
                [third_log],
                context="spectating",
                expected_active=True,
                expected_phase="Spectating",
                expected_registered=True,
                expected_rendered=True,
                expected_target_participant_id=HOST_ID,
                timeout=5.0,
            ),
            "host": wait_for_spectator_product_hud_state(
                [host_log],
                context="alive",
                expected_active=False,
                expected_phase="Inactive",
                expected_registered=False,
                expected_rendered=False,
                expected_target_participant_id=0,
                timeout=5.0,
            ),
        }
        result["screenshots"]["after_target_grace"] = (
            capture_game_backbuffer(
                client_pipe,
                artifact_directory / "after-target-grace.png",
            )
        )
        result["product_hud_pixels_after_target_grace"] = (
            inspect_spectator_product_hud_pixels(
                artifact_directory / "after-target-grace.png",
                expected_visible=True,
            )
        )
        result["normal_surface_guard_after_target_death"] = (
            assert_launch_debug_surfaces_empty(
                launch,
                roles=("host", "client", "third"),
                context="spectating_after_target_death",
            )
        )

        result["enemy_idle_before_wave_finish"] = _set_enemy_idle(
            host_pipe
        )
        result["wave_finish"] = _finish_wave(host_pipe)
        result["respawned"] = {
            "client": _wait_for_respawn(client_pipe),
            "third": _wait_for_respawn(third_pipe),
        }
        result["product_hud_respawned"] = (
            wait_for_spectator_product_hud_state(
                [host_log, client_log, third_log],
                context="respawned",
                expected_active=False,
                expected_phase="Inactive",
                expected_registered=False,
                expected_rendered=False,
                expected_target_participant_id=0,
                timeout=5.0,
            )
        )
        result["product_hud_lifecycles"] = {
            "client": assert_spectator_product_hud_lifecycle(
                client_log,
                expected_target_participant_id=THIRD_ID,
                require_retired=True,
            ),
            "third": assert_spectator_product_hud_lifecycle(
                third_log,
                expected_target_participant_id=HOST_ID,
                require_retired=True,
            ),
            "host_never_visible":
                assert_spectator_product_hud_never_visible(host_log),
        }
        result["product_hud_surface_states"] = {
            role: parse_spectator_product_hud_states(
                log_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            )
            for role, log_path in (
                ("host", host_log),
                ("client", client_log),
                ("third", third_log),
            )
        }
        retail_sha256_after = hashlib.sha256(
            retail_wave_path.read_bytes()
        ).hexdigest()
        result["wave_schedule"]["retail_sha256_after"] = (
            retail_sha256_after
        )
        result["wave_schedule"]["retail_unchanged"] = (
            retail_sha256_after
            == result["wave_schedule"]["retail_sha256"]
        )
        if not result["wave_schedule"]["retail_unchanged"]:
            raise VerifyFailure(
                f"retail wave source changed: {retail_wave_path}"
            )
        result["ok"] = True
        return result
    except Exception as exc:
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        raise OrganicSpectatorFollowupFailure(
            str(exc),
            result,
        ) from exc
    finally:
        _disarm_death_traces(list(pipes.values()))
        stop_game_processes(process_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-prefix", default="")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--launcher-path", type=Path, default=None)
    parser.add_argument(
        "--enable-audio",
        action="store_true",
        help="Keep stock audio enabled when silent D3D startup stalls.",
    )
    parser.add_argument("--host-port", type=int, default=None)
    parser.add_argument("--client-port", type=int, default=None)
    parser.add_argument("--third-port", type=int, default=None)
    args = parser.parse_args()

    supplied_ports = (
        args.host_port,
        args.client_port,
        args.third_port,
    )
    if any(port is not None for port in supplied_ports) and not all(
        port is not None for port in supplied_ports
    ):
        parser.error(
            "--host-port, --client-port, and --third-port must be supplied "
            "together"
        )
    ports = (
        [int(port) for port in supplied_ports if port is not None]
        if all(port is not None for port in supplied_ports)
        else select_available_windows_udp_ports(3)
    )
    instance_prefix = (
        args.instance_prefix or _default_instance_prefix()
    )
    result: dict[str, Any] = {"ok": False}
    exit_code = 1
    try:
        result = run_live_verification(
            instance_prefix=instance_prefix,
            ports=ports,
            game_directory=args.game_dir,
            launcher_path=args.launcher_path,
            enable_audio=args.enable_audio,
        )
        exit_code = 0
    except Exception as exc:  # noqa: BLE001 - persist exact live evidence.
        if isinstance(exc, OrganicSpectatorFollowupFailure):
            result = exc.evidence
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
        result["instance_prefix"] = instance_prefix
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "instance_prefix": instance_prefix,
                "first_grace_seconds":
                    result.get("first_grace_seconds"),
                "spectated_target_grace_seconds":
                    result.get("spectated_target_grace_seconds"),
                "spectated_target_hold":
                    result.get("spectated_target_hold"),
                "ether_minion_materialization":
                    result.get("ether_minion_materialization"),
                "error": result.get("error"),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
