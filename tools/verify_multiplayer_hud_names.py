#!/usr/bin/env python3
"""Verify remote world nameplates, thin health bars, and named ally HUD rows."""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from multiplayer_frame_capture import capture_game_backbuffer
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    ROOT,
    THIRD_ID,
    THIRD_NAME,
    THIRD_PIPE,
    VerifyFailure,
    launch_trio,
    lua,
    place_player,
    query,
    start_testrun,
    stop_games,
    wait_for_remote,
    wait_for_remote_convergence,
    wait_for_scene,
)
from verify_player_health_death_sync import (
    set_local_player_vitals,
    wait_for_remote_matches_owner_health,
)
from verify_real_input_spell_cast_sync import detect_instance_pids


OUTPUT = ROOT / "runtime" / "multiplayer_hud_names.json"
CLIENT_TEST_HP = 250.0
CLIENT_TEST_MAX_HP = 500.0
EXPECTED_HALF_HEALTH_SEGMENTS = 6
RUN_FORMATION_LEASE_SECONDS = 5.5
MIN_ALLY_HUD_NAME_GAP = 1.0


@dataclass(frozen=True)
class Participant:
    label: str
    participant_id: int
    name: str
    pipe: str
    log: Path
    screenshot: Path


HOST = Participant(
    "host",
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    ROOT / "runtime/instances/local-mp-host/stage/.sdmod/logs/solomondarkmodloader.log",
    ROOT / "runtime/multiplayer_hud_names_host.png",
)
CLIENT = Participant(
    "client",
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    ROOT / "runtime/instances/local-mp-client/stage/.sdmod/logs/solomondarkmodloader.log",
    ROOT / "runtime/multiplayer_hud_names_client.png",
)
THIRD = Participant(
    "third",
    THIRD_ID,
    THIRD_NAME,
    THIRD_PIPE,
    ROOT / "runtime/instances/local-mp-third/stage/.sdmod/logs/solomondarkmodloader.log",
    ROOT / "runtime/multiplayer_hud_names_third.png",
)
PARTICIPANTS = (HOST, CLIENT, THIRD)


def clear_previous_evidence() -> None:
    for participant in PARTICIPANTS:
        participant.log.unlink(missing_ok=True)
        participant.screenshot.unlink(missing_ok=True)


def disable_all_bots() -> dict[str, int]:
    disabled: dict[str, int] = {}
    for participant in PARTICIPANTS:
        count_text = lua(
            participant.pipe,
            "lua_bots_disable_tick = true; sd.bots.clear(); "
            "return tostring(sd.bots.get_count())",
            timeout=10.0,
        ).strip()
        count = int(count_text)
        if count != 0:
            raise VerifyFailure(
                f"failed to disable stock bots on {participant.label}: count={count}"
            )
        disabled[participant.label] = count
    return disabled


def wait_for_all_relationships(scene: str, timeout: float) -> dict[str, Any]:
    relationships: dict[str, Any] = {}
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
            prefix = f"peer.{owner.participant_id}."
            relationships[key] = {
                "actor": state.get(prefix + "actor"),
                "name": state.get(prefix + "name"),
                "nameplate": state.get(prefix + "nameplate"),
                "materialized": state.get(prefix + "materialized"),
            }
    return relationships


def place_trio_for_capture(timeout: float) -> dict[str, Any]:
    host_state = query(HOST.pipe)
    center_x = float(host_state["player.x"])
    center_y = float(host_state["player.y"])
    placements = {
        HOST.label: (center_x - 170.0, center_y + 35.0, 90.0),
        CLIENT.label: (center_x, center_y - 35.0, 180.0),
        THIRD.label: (center_x + 170.0, center_y + 35.0, 270.0),
    }

    writes: dict[str, Any] = {}
    for owner in PARTICIPANTS:
        x, y, heading = placements[owner.label]
        writes[owner.label] = place_player(owner.pipe, x, y, heading)

    convergence: dict[str, Any] = {}
    for observer in PARTICIPANTS:
        for owner in PARTICIPANTS:
            if observer == owner:
                continue
            x, y, heading = placements[owner.label]
            key = f"{observer.label}_observes_{owner.label}"
            state = wait_for_remote_convergence(
                observer.pipe,
                owner.participant_id,
                x,
                y,
                heading,
                timeout=timeout,
            )
            prefix = f"peer.{owner.participant_id}."
            convergence[key] = {
                "x": state.get(prefix + "x"),
                "y": state.get(prefix + "y"),
                "heading": state.get(prefix + "heading"),
            }

    return {
        "targets": {
            label: [x, y, heading]
            for label, (x, y, heading) in placements.items()
        },
        "writes": writes,
        "convergence": convergence,
    }


def matching_line(log_text: str, required_tokens: tuple[str, ...]) -> str:
    for line in log_text.splitlines():
        if all(token in line for token in required_tokens):
            return line
    raise VerifyFailure(
        "missing loader log record containing: " + ", ".join(required_tokens)
    )


def verify_ally_hud_name_layout(line: str) -> dict[str, float]:
    field_names = (
        "bar_right_x",
        "label_width",
        "label_right_x",
        "name_left_x",
        "name_width",
        "name_right_x",
    )
    values: dict[str, float] = {}
    for field_name in field_names:
        match = re.search(rf"(?:^| ){field_name}=(-?[0-9]+(?:\.[0-9]+)?)", line)
        if match is None:
            raise VerifyFailure(
                f"ally HUD draw record has no numeric {field_name}: {line}"
            )
        values[field_name] = float(match.group(1))

    if values["label_width"] <= 0.0 or values["name_width"] <= 0.0:
        raise VerifyFailure(f"ally HUD draw record has invalid widths: {line}")
    if values["name_left_x"] < values["bar_right_x"] + MIN_ALLY_HUD_NAME_GAP:
        raise VerifyFailure(f"ally HUD name overlaps its health bar: {line}")
    if values["name_right_x"] > values["label_right_x"] + 0.01:
        raise VerifyFailure(f"ally HUD name extends outside its reserved label slot: {line}")
    if abs(
        values["name_left_x"] + values["name_width"] - values["name_right_x"]
    ) > 0.01:
        raise VerifyFailure(f"ally HUD name bounds are internally inconsistent: {line}")
    return values


def verify_render_logs() -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for observer in PARTICIPANTS:
        log_text = observer.log.read_text(encoding="utf-8", errors="replace")
        observer_evidence: dict[str, Any] = {}
        for owner in PARTICIPANTS:
            if observer == owner:
                continue
            participant_token = f"participant={owner.participant_id}"
            world_line = matching_line(
                log_text,
                (
                    "source=playerwizard_render",
                    participant_token,
                    f"name={owner.name}",
                    "ok=1",
                    "health_bar=1",
                    "health_segments=",
                ),
            )
            ally_hud_line = matching_line(
                log_text,
                (
                    "source=ally_healthbar",
                    participant_token,
                    f"name={owner.name}",
                    "ok=1",
                    "stock_label=0",
                    "layout_ok=1",
                ),
            )
            observer_evidence[owner.label] = {
                "world": world_line,
                "ally_hud": ally_hud_line,
                "ally_hud_layout": verify_ally_hud_name_layout(ally_hud_line),
            }

        if observer != CLIENT:
            half_health_line = matching_line(
                log_text,
                (
                    "source=playerwizard_render",
                    f"participant={CLIENT.participant_id}",
                    "health_bar=1",
                    f"health_segments={EXPECTED_HALF_HEALTH_SEGMENTS}/12",
                ),
            )
            ratio_match = re.search(r"health_ratio=([0-9.]+)", half_health_line)
            if ratio_match is None:
                raise VerifyFailure(
                    f"half-health draw record has no numeric ratio: {half_health_line}"
                )
            health_ratio = float(ratio_match.group(1))
            if abs(health_ratio - 0.5) > 0.01:
                raise VerifyFailure(
                    f"half-health draw ratio is outside tolerance: {half_health_line}"
                )
            observer_evidence["client_half_health"] = {
                "health_ratio": health_ratio,
                "line": half_health_line,
            }
        evidence[observer.label] = observer_evidence
    return evidence


def run(timeout: float) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False}
    result["launch"] = launch_trio(god_mode=False, tile_windows=True)
    result["bots_disabled"] = disable_all_bots()
    result["hub_relationships"] = wait_for_all_relationships("hub", timeout)

    start_testrun(HOST.pipe)
    for participant in PARTICIPANTS:
        wait_for_scene(participant.pipe, "testrun", timeout)
    result["run_relationships"] = wait_for_all_relationships("testrun", timeout)
    time.sleep(RUN_FORMATION_LEASE_SECONDS)
    result["capture_placement"] = place_trio_for_capture(timeout)

    result["client_vitals_write"] = set_local_player_vitals(
        CLIENT.pipe,
        CLIENT_TEST_HP,
        CLIENT_TEST_MAX_HP,
    )
    result["half_health_observers"] = {
        observer.label: wait_for_remote_matches_owner_health(
            CLIENT.pipe,
            observer.pipe,
            CLIENT.participant_id,
            CLIENT_TEST_MAX_HP,
            expect_dead=False,
            timeout=timeout,
        )
        for observer in (HOST, THIRD)
    }
    time.sleep(0.5)

    pids = detect_instance_pids()
    if "third" not in pids:
        raise VerifyFailure(f"could not resolve third SolomonDark PID: {pids}")
    result["screenshots"] = {
        participant.label: capture_game_backbuffer(
            participant.pipe,
            pids[participant.label],
            participant.screenshot,
        )
        for participant in PARTICIPANTS
    }
    result["render_logs"] = verify_render_logs()
    result["summary"] = {
        "participant_count": len(PARTICIPANTS),
        "observer_relationship_count": 6,
        "world_nameplate_checks": 6,
        "ally_hud_name_checks": 6,
        "half_health_owner": CLIENT.name,
        "half_health_segments": EXPECTED_HALF_HEALTH_SEGMENTS,
    }
    result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        stop_games()
        clear_previous_evidence()
        result = run(args.timeout)
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        return_code = 1
    finally:
        stop_games()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "ok": result.get("ok", False),
        "error": result.get("error"),
        "summary": result.get("summary"),
        "screenshots": result.get("screenshots"),
        "output": str(OUTPUT),
    }, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
