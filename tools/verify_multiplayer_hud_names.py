#!/usr/bin/env python3
"""Verify remote world nameplates, DX9 health bars, and named ally HUD rows."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from multiplayer_frame_capture import capture_game_backbuffer
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
    place_player,
    query,
    start_testrun,
    stop_game_processes,
    wait_for_remote,
    wait_for_remote_convergence,
    wait_for_scene,
)
from verify_player_health_death_sync import (
    set_local_player_vitals,
    wait_for_remote_matches_owner_health,
)


OUTPUT = ROOT / "runtime" / "multiplayer_hud_names.json"
ACCEPTANCE_MOD_ID = "sample.lua.ui_sandbox_lab"
CLIENT_TEST_HP = 250.0
CLIENT_TEST_MAX_HP = 500.0
EXPECTED_HALF_HEALTH_PERCENT = 50
RUN_FORMATION_LEASE_SECONDS = 5.5
MIN_ALLY_HUD_NAME_GAP = 1.0
MIN_DX9_NAMEPLATE_BAR_WIDTH = 64.0
DX9_NAMEPLATE_BAR_HEIGHT = 7.0
DX9_NAMEPLATE_BAR_VERTICAL_GAP = 1.0


@dataclass(frozen=True)
class Participant:
    label: str
    participant_id: int
    name: str
    pipe: str
    log: Path
    screenshot: Path


def _participants_for_prefix(
    instance_prefix: str,
) -> tuple[Participant, Participant, Participant]:
    def participant(
        label: str,
        participant_id: int,
        name: str,
        suffix: str,
    ) -> Participant:
        instance = f"{instance_prefix}-{suffix}"
        return Participant(
            label,
            participant_id,
            name,
            f"SolomonDarkModLoader_LuaExec_{instance}",
            ROOT
            / "runtime"
            / "instances"
            / instance
            / "stage/.sdmod/logs/solomondarkmodloader.log",
            ROOT
            / "runtime"
            / f"multiplayer_hud_names_{instance}.png",
        )

    return (
        participant("host", HOST_ID, HOST_NAME, "host"),
        participant("client", CLIENT_ID, CLIENT_NAME, "client"),
        participant("third", THIRD_ID, THIRD_NAME, "third"),
    )


def _configure_participants(instance_prefix: str) -> None:
    global HOST, CLIENT, THIRD, PARTICIPANTS

    HOST, CLIENT, THIRD = _participants_for_prefix(instance_prefix)
    PARTICIPANTS = (HOST, CLIENT, THIRD)


def _reserve_udp_ports(count: int) -> list[int]:
    sockets: list[socket.socket] = []
    try:
        for _ in range(count):
            handle = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            handle.bind(("127.0.0.1", 0))
            sockets.append(handle)
        return [int(handle.getsockname()[1]) for handle in sockets]
    finally:
        for handle in sockets:
            handle.close()


def _default_instance_prefix() -> str:
    return f"hud-{os.getpid():x}-{time.time_ns() & 0xFFFF:04x}"


HOST, CLIENT, THIRD = _participants_for_prefix("local-mp")
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
    # A physical pair reuses its log across focused regressions. Resolve the
    # newest matching render so geometry reflects the placement exercised by
    # this run instead of an earlier centered frame.
    for line in reversed(log_text.splitlines()):
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


def verify_dx9_nameplate_health_bar_geometry(
    line: str,
    expected_percent: int | None = None,
) -> dict[str, float]:
    ratio_match = re.search(r"(?:^| )health_ratio=([0-9.]+)", line)
    percent_match = re.search(r"(?:^| )health_percent=([0-9]+)", line)
    bounds_match = re.search(
        r"(?:^| )bounds=\((-?[0-9.]+),(-?[0-9.]+),"
        r"(-?[0-9.]+),(-?[0-9.]+)\)",
        line,
    )
    name_bounds_match = re.search(
        r"(?:^| )name_bounds=\((-?[0-9.]+),(-?[0-9.]+),"
        r"(-?[0-9.]+),(-?[0-9.]+)\)",
        line,
    )
    if (
        ratio_match is None
        or percent_match is None
        or bounds_match is None
        or name_bounds_match is None
    ):
        raise VerifyFailure(f"DX9 health draw has incomplete geometry: {line}")

    health_ratio = float(ratio_match.group(1))
    health_percent = int(percent_match.group(1))
    left, top, right, bottom = (
        float(value) for value in bounds_match.groups()
    )
    name_left, name_top, name_right, name_bottom = (
        float(value) for value in name_bounds_match.groups()
    )
    width = right - left
    height = bottom - top
    name_width = name_right - name_left
    name_height = name_bottom - name_top
    if expected_percent is not None:
        expected_ratio = expected_percent / 100.0
        if health_percent != expected_percent or abs(
            health_ratio - expected_ratio
        ) > 0.01:
            raise VerifyFailure(
                "DX9 health draw ratio mismatch: "
                f"expected={expected_ratio} line={line}"
            )
    if (
        width + 0.01 < MIN_DX9_NAMEPLATE_BAR_WIDTH
        or not math.isclose(
            height,
            DX9_NAMEPLATE_BAR_HEIGHT,
            rel_tol=0.0,
            abs_tol=0.01,
        )
        or name_width <= 0.0
        or name_height <= 0.0
        or width + 0.01 < name_width
    ):
        raise VerifyFailure(f"DX9 health draw has invalid dimensions: {line}")
    if not math.isclose(
        (left + right) * 0.5,
        (name_left + name_right) * 0.5,
        rel_tol=0.0,
        abs_tol=0.01,
    ):
        raise VerifyFailure(f"DX9 health bar is not centered under its name: {line}")
    if not math.isclose(
        top,
        name_bottom + DX9_NAMEPLATE_BAR_VERTICAL_GAP,
        rel_tol=0.0,
        abs_tol=0.01,
    ):
        raise VerifyFailure(f"DX9 health bar is not flush under its name: {line}")

    return {
        "health_ratio": health_ratio,
        "health_percent": float(health_percent),
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": width,
        "height": height,
        "name_left": name_left,
        "name_top": name_top,
        "name_right": name_right,
        "name_bottom": name_bottom,
        "name_width": name_width,
        "name_height": name_height,
    }


def verify_health_bar_pixels(
    capture_path: Path,
    geometry: dict[str, float],
) -> dict[str, int]:
    with Image.open(capture_path) as raw:
        image = raw.convert("RGB")

    left = max(0, math.ceil(geometry["left"] + 1.0))
    top = max(0, math.ceil(geometry["top"] + 1.0))
    right = min(image.width, math.floor(geometry["right"] - 1.0))
    bottom = min(image.height, math.floor(geometry["bottom"] - 1.0))
    if right - left < 4 or bottom - top < 2:
        raise VerifyFailure(
            f"healthbar pixels have invalid capture bounds: "
            f"path={capture_path} geometry={geometry}"
        )

    health_ratio = max(0.0, min(1.0, geometry["health_ratio"]))
    fill_right = left + round((right - left) * health_ratio)
    if health_ratio > 0.0:
        fill_right = max(left + 1, min(fill_right, right))

    def is_health_pixel(pixel: tuple[int, int, int]) -> bool:
        red, green, blue = pixel
        return (
            red >= 150
            and red - green >= 70
            and red - blue >= 60
        )

    def count_health_pixels(
        region_left: int,
        region_right: int,
    ) -> tuple[int, int]:
        pixels = [
            image.getpixel((x, y))
            for y in range(top, bottom)
            for x in range(region_left, region_right)
        ]
        return (
            sum(is_health_pixel(pixel) for pixel in pixels),
            len(pixels),
        )

    filled_health_pixels, filled_pixels = count_health_pixels(
        left,
        fill_right,
    )
    if (
        filled_pixels == 0
        or filled_health_pixels / filled_pixels < 0.45
    ):
        raise VerifyFailure(
            "captured frame is missing the expected filled healthbar pixels: "
            f"path={capture_path} geometry={geometry} "
            f"health_pixels={filled_health_pixels}/{filled_pixels}"
        )

    empty_health_pixels = 0
    empty_pixels = 0
    if fill_right < right:
        empty_health_pixels, empty_pixels = count_health_pixels(
            fill_right,
            right,
        )
        if (
            empty_pixels == 0
            or empty_health_pixels / empty_pixels > 0.25
        ):
            raise VerifyFailure(
                "captured frame does not show the expected empty healthbar "
                "segment: "
                f"path={capture_path} geometry={geometry} "
                f"health_pixels={empty_health_pixels}/{empty_pixels}"
            )

    return {
        "filled_health_pixels": filled_health_pixels,
        "filled_pixels": filled_pixels,
        "empty_health_pixels": empty_health_pixels,
        "empty_pixels": empty_pixels,
    }


def verify_render_logs(
    *,
    expected_health_percent_by_participant: dict[int, int] | None = None,
    minimum_log_line_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for observer in PARTICIPANTS:
        log_text = observer.log.read_text(encoding="utf-8", errors="replace")
        log_lines = log_text.splitlines()
        minimum_line_count = (
            minimum_log_line_counts.get(observer.label, 0)
            if minimum_log_line_counts is not None
            else 0
        )
        if minimum_line_count > len(log_lines):
            raise VerifyFailure(
                f"{observer.label} loader log was truncated during HUD verification"
            )
        dynamic_log_text = "\n".join(log_lines[minimum_line_count:])
        observer_evidence: dict[str, Any] = {}
        for owner in PARTICIPANTS:
            if observer == owner:
                continue
            participant_token = f"participant={owner.participant_id}"
            expected_health_percent = (
                expected_health_percent_by_participant.get(owner.participant_id)
                if expected_health_percent_by_participant is not None
                else None
            )
            health_percent_token = (
                f"health_percent={expected_health_percent}"
                if expected_health_percent is not None
                else "health_percent="
            )
            world_line = matching_line(
                dynamic_log_text,
                (
                    "source=playerwizard_render",
                    participant_token,
                    f"name={owner.name}",
                    "ok=1",
                    "health_bar=dx9",
                    "health_valid=1",
                    health_percent_token,
                ),
            )
            dx9_health_line = matching_line(
                dynamic_log_text,
                (
                    "source=dx9_nameplate_healthbar",
                    participant_token,
                    "ok=1",
                    "health_ratio=",
                    health_percent_token,
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
                "dx9_health_bar": dx9_health_line,
                "dx9_health_bar_geometry": (
                    verify_dx9_nameplate_health_bar_geometry(
                        dx9_health_line,
                        expected_health_percent,
                    )
                ),
                "ally_hud": ally_hud_line,
                "ally_hud_layout": verify_ally_hud_name_layout(ally_hud_line),
            }

        client_expected_percent = (
            expected_health_percent_by_participant.get(CLIENT.participant_id)
            if expected_health_percent_by_participant is not None
            else EXPECTED_HALF_HEALTH_PERCENT
        )
        if (
            observer != CLIENT
            and client_expected_percent == EXPECTED_HALF_HEALTH_PERCENT
        ):
            half_health_line = matching_line(
                dynamic_log_text,
                (
                    "source=playerwizard_render",
                    f"participant={CLIENT.participant_id}",
                    "health_bar=dx9",
                    f"health_percent={EXPECTED_HALF_HEALTH_PERCENT}",
                ),
            )
            half_health_dx9_line = matching_line(
                dynamic_log_text,
                (
                    "source=dx9_nameplate_healthbar",
                    f"participant={CLIENT.participant_id}",
                    "ok=1",
                    f"health_percent={EXPECTED_HALF_HEALTH_PERCENT}",
                ),
            )
            half_health_geometry = verify_dx9_nameplate_health_bar_geometry(
                half_health_dx9_line,
                EXPECTED_HALF_HEALTH_PERCENT,
            )
            observer_evidence["client_half_health"] = {
                "health_ratio": half_health_geometry["health_ratio"],
                "world_line": half_health_line,
                "dx9_health_bar_line": half_health_dx9_line,
                "dx9_health_bar_geometry": half_health_geometry,
            }
        evidence[observer.label] = observer_evidence
    return evidence


def wait_for_render_logs(
    timeout: float,
    *,
    expected_health_percent_by_participant: dict[int, int] | None = None,
    minimum_log_line_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            return verify_render_logs(
                expected_health_percent_by_participant=(
                    expected_health_percent_by_participant
                ),
                minimum_log_line_counts=minimum_log_line_counts,
            )
        except (OSError, VerifyFailure) as exc:
            last_error = str(exc)
        time.sleep(0.1)
    raise VerifyFailure(
        "multiplayer name/health render evidence did not converge: "
        f"{last_error}"
    )


def _verify_quick_start_enabled() -> dict[str, str]:
    evidence: dict[str, str] = {}
    for participant in PARTICIPANTS:
        log_text = participant.log.read_text(
            encoding="utf-8",
            errors="replace",
        )
        marker = "Multiplayer join flow enabled."
        if marker not in log_text:
            raise VerifyFailure(
                f"{participant.label} did not enter multiplayer quick-start "
                f"mode: {participant.log}"
            )
        evidence[participant.label] = marker
    return evidence


def verify_loopback_transport_log(log_text: str) -> str:
    return matching_line(
        log_text,
        (
            "Multiplayer local UDP transport initialized.",
            "bind=127.0.0.1",
            "remote=127.0.0.1:",
        ),
    )


def _verify_loopback_transport() -> dict[str, str]:
    return {
        participant.label: verify_loopback_transport_log(
            participant.log.read_text(
                encoding="utf-8",
                errors="replace",
            ),
        )
        for participant in PARTICIPANTS
    }


def _verify_running_trio(
    result: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    result["quick_start"] = _verify_quick_start_enabled()
    result["loopback_transport"] = _verify_loopback_transport()
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
    result["render_logs"] = wait_for_render_logs(timeout)

    result["screenshots"] = {
        participant.label: capture_game_backbuffer(
            participant.pipe,
            participant.screenshot,
        )
        for participant in PARTICIPANTS
    }
    result["healthbar_pixels"] = {
        observer.label: verify_health_bar_pixels(
            observer.screenshot,
            result["render_logs"][observer.label]["client_half_health"][
                "dx9_health_bar_geometry"
            ],
        )
        for observer in (HOST, THIRD)
    }
    result["summary"] = {
        "participant_count": len(PARTICIPANTS),
        "observer_relationship_count": 6,
        "world_nameplate_checks": 6,
        "dx9_health_bar_checks": 6,
        "ally_hud_name_checks": 6,
        "half_health_owner": CLIENT.name,
        "half_health_percent": EXPECTED_HALF_HEALTH_PERCENT,
    }
    result["ok"] = True
    return result


def run_live_verification(
    *,
    timeout: float,
    instance_prefix: str,
    ports: list[int],
    game_directory: Path | None,
) -> dict[str, Any]:
    if len(ports) != 3:
        raise ValueError("healthbar verification requires exactly three UDP ports")

    _configure_participants(instance_prefix)
    clear_previous_evidence()
    launch = launch_pair(
        host_preset="map_create_fire_mind_hub",
        client_preset="map_create_water_body_hub",
        third_preset="map_create_earth_arcane_hub",
        temporary_host_profile=True,
        god_mode=False,
        tile_windows=False,
        third_player=True,
        kill_existing=False,
        instance_prefix=instance_prefix,
        host_port=ports[0],
        client_port=ports[1],
        third_port=ports[2],
        game_directory=game_directory,
        exact_mod_id=ACCEPTANCE_MOD_ID,
        quick_start=True,
    )
    process_ids = game_process_ids(launch)
    if len(process_ids) != 3:
        stop_game_processes(process_ids)
        raise VerifyFailure(
            f"isolated healthbar trio did not report three exact process "
            f"IDs: {launch}"
        )

    result: dict[str, Any] = {
        "ok": False,
        "launch": launch,
        "instance_prefix": instance_prefix,
        "ports": ports,
        "process_ids": process_ids,
    }
    try:
        return _verify_running_trio(result, timeout)
    finally:
        stop_game_processes(process_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--instance-prefix",
        default="",
        help="Unique launcher instance prefix (generated by default).",
    )
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=None,
        help="Retail game directory override for isolated worktrees.",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    instance_prefix = args.instance_prefix or _default_instance_prefix()
    result: dict[str, Any] = {"ok": False}
    try:
        result = run_live_verification(
            timeout=args.timeout,
            instance_prefix=instance_prefix,
            ports=_reserve_udp_ports(3),
            game_directory=args.game_dir,
        )
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        result["instance_prefix"] = instance_prefix
        return_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "ok": result.get("ok", False),
        "error": result.get("error"),
        "summary": result.get("summary"),
        "screenshots": result.get("screenshots"),
        "output": str(args.output),
    }, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
