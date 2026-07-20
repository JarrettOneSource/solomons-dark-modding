#!/usr/bin/env python3
"""Verify player presentation and multiplayer HUD layout on a live Steam pair."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

import multiplayer_frame_capture as frame_capture
import verify_local_multiplayer_sync as local_sync
import verify_multiplayer_animation_mana_elements as animation
import verify_multiplayer_hud_names as hud
import verify_player_health_death_sync as health
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from steam_friend_behavior_context import (
    configure_behavior_context,
    require_shared_test_run,
)
from verify_local_multiplayer_sync import VerifyFailure, parse_key_values
from verify_steam_friend_active_pair_progression import find_new_crash_artifacts
from verify_steam_friend_active_pair_state import configure_modules, direction


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_active_pair_visuals.json"
HOST_SCREENSHOT = ROOT / "runtime/steam_friend_active_pair_visuals_host.png"
CLIENT_SCREENSHOT = ROOT / "runtime/steam_friend_active_pair_visuals_client.png"
EXPECTED_BODY_TYPES = {7005, 7006}
EXPECTED_STAFF_TYPE = 7004
CAPTURE_HALF_SEPARATION = 330.0
VIEWPORT_GEOMETRY_TOLERANCE = 0.05
VIEWPORT_EDGE_EXERCISE_DISTANCE = 24.0


def participant_visuals(
    owner: dict[str, str],
    observer: dict[str, str],
    participant_id: int,
) -> dict[str, Any]:
    prefix = f"peer.{participant_id}."
    result = {
        "local_body_types": sorted(
            {
                int(owner["player.primary_visual_type"]),
                int(owner["player.secondary_visual_type"]),
            }
        ),
        "local_staff_type": int(owner["player.attachment_visual_type"]),
        "local_staff_address_present": (
            int(owner["player.attachment_visual_address"]) != 0
        ),
        "remote_body_types": sorted(
            {
                int(observer[prefix + "primary_visual_type"]),
                int(observer[prefix + "secondary_visual_type"]),
            }
        ),
        "remote_staff_type": int(observer[prefix + "attachment_visual_type"]),
        "remote_staff_address_present": (
            int(observer[prefix + "attachment_visual_address"]) != 0
        ),
        "remote_nameplate_present": bool(observer[prefix + "nameplate"]),
    }
    if set(result["local_body_types"]) != EXPECTED_BODY_TYPES:
        raise VerifyFailure(f"local wizard body lanes are incomplete: {result}")
    if set(result["remote_body_types"]) != EXPECTED_BODY_TYPES:
        raise VerifyFailure(f"remote wizard body lanes are incomplete: {result}")
    if (
        result["local_staff_type"] != EXPECTED_STAFF_TYPE
        or not result["local_staff_address_present"]
        or result["remote_staff_type"] != EXPECTED_STAFF_TYPE
        or not result["remote_staff_address_present"]
    ):
        raise VerifyFailure(f"wizard staff attachment is incomplete: {result}")
    if not result["remote_nameplate_present"]:
        raise VerifyFailure(f"remote wizard nameplate is missing: {result}")
    return result


def successful_ally_rows(
    log_path: Path,
    *,
    local_participant_id: int,
    remote_participant_id: int,
) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    lines = [
        line
        for line in text.splitlines()
        if "source=ally_healthbar" in line and " ok=1" in line
    ]
    local_token = f"participant={local_participant_id}"
    remote_token = f"participant={remote_participant_id}"
    if any(local_token in line for line in lines):
        raise VerifyFailure("local participant incorrectly received an ally HUD row")
    remote_lines = [line for line in lines if remote_token in line]
    if not remote_lines:
        raise VerifyFailure("remote participant ally HUD row was never rendered")
    latest = remote_lines[-1]
    row_match = re.search(r"(?:^| )hud_row=([0-9]+)", latest)
    if row_match is None or int(row_match.group(1)) != 1:
        raise VerifyFailure(f"remote participant did not occupy ally HUD row 1: {latest}")
    return {
        "remote_row": 1,
        "local_row_present": False,
        "layout": hud.verify_ally_hud_name_layout(latest),
    }


def capture_remote_host_backbuffer(
    pair: SteamFriendActivePair,
    output_path: Path,
) -> dict[str, Any]:
    remote_path = os.environ.get(
        "SDMOD_STEAM_REMOTE_CAPTURE_PATH",
        r"C:\Users\Public\Documents\SolomonDarkBeta5RemoteTest\physical-host-backbuffer.bmp",
    )
    raw_path = output_path.with_suffix(".bmp")
    raw_path.unlink(missing_ok=True)
    output_path.unlink(missing_ok=True)
    command = (
        "local ok,err=sd.debug.capture_backbuffer(" + json.dumps(remote_path) + ");"
        "print('ok='..tostring(ok));print('error='..tostring(err or ''))"
    )
    capture = parse_key_values(pair.lua(HOST_ENDPOINT, command, timeout=20.0))
    if capture.get("ok") != "true":
        raise VerifyFailure(f"remote D3D9 backbuffer capture failed: {capture}")

    ssh_host = os.environ.get("SDMOD_STEAM_REMOTE_SSH_HOST", "").strip()
    ssh_user = os.environ.get(
        "SDMOD_STEAM_REMOTE_SSH_USER", "TailscaleToday"
    ).strip()
    ssh_key = Path(
        os.environ.get(
            "SDMOD_STEAM_REMOTE_SSH_KEY",
            "~/.ssh/id_ed25519_workstation20_tailscale",
        )
    ).expanduser()
    if not ssh_host or not ssh_key.is_file():
        raise VerifyFailure("remote Windows SSH capture configuration is incomplete")
    remote_spec = f"{ssh_user}@{ssh_host}:{remote_path.replace(chr(92), '/')}"
    completed = subprocess.run(
        ["scp", "-q", "-i", str(ssh_key), remote_spec, str(raw_path)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30.0,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise VerifyFailure(f"remote D3D9 backbuffer copy failed: {detail}")

    raw_bytes = raw_path.stat().st_size if raw_path.is_file() else 0
    quality = frame_capture.convert_and_validate_backbuffer(raw_path, output_path)
    raw_path.unlink(missing_ok=True)
    return {
        "path": str(output_path),
        "bytes": output_path.stat().st_size,
        "raw_bmp_bytes": raw_bytes,
        "capture_method": "remote_d3d9_backbuffer",
        "quality": quality,
    }


def verify_capture_resolution_contract(
    screenshots: dict[str, dict[str, Any]],
    render_logs: dict[str, Any],
    *,
    require_distinct: bool,
) -> dict[str, Any]:
    resolutions: dict[str, list[int]] = {}
    checked_health_bars = 0
    edge_contained_health_bars = 0
    for observer in ("host", "client"):
        quality = screenshots[observer]["quality"]
        width = int(quality["width"])
        height = int(quality["height"])
        if width <= 0 or height <= 0:
            raise VerifyFailure(
                f"{observer} captured an invalid D3D9 viewport: {quality}"
            )
        resolutions[observer] = [width, height]

        for evidence in render_logs[observer].values():
            if not isinstance(evidence, dict):
                continue
            geometry = evidence.get("dx9_health_bar_geometry")
            if not isinstance(geometry, dict):
                continue
            checked_health_bars += 1
            left = min(float(geometry["left"]), float(geometry["name_left"]))
            top = min(float(geometry["top"]), float(geometry["name_top"]))
            right = max(float(geometry["right"]), float(geometry["name_right"]))
            bottom = max(float(geometry["bottom"]), float(geometry["name_bottom"]))
            if (
                left < -VIEWPORT_GEOMETRY_TOLERANCE
                or top < -VIEWPORT_GEOMETRY_TOLERANCE
                or right > width + VIEWPORT_GEOMETRY_TOLERANCE
                or bottom > height + VIEWPORT_GEOMETRY_TOLERANCE
            ):
                raise VerifyFailure(
                    f"{observer} participant name/health geometry escaped its "
                    f"{width}x{height} D3D9 viewport: {geometry}"
                )
            if (
                left <= VIEWPORT_EDGE_EXERCISE_DISTANCE
                or top <= VIEWPORT_EDGE_EXERCISE_DISTANCE
                or right >= width - VIEWPORT_EDGE_EXERCISE_DISTANCE
                or bottom >= height - VIEWPORT_EDGE_EXERCISE_DISTANCE
            ):
                edge_contained_health_bars += 1

    distinct = resolutions["host"] != resolutions["client"]
    if require_distinct and not distinct:
        raise VerifyFailure(
            "physical cross-resolution verification requires different D3D9 "
            f"backbuffer dimensions: {resolutions}"
        )
    if checked_health_bars < 2:
        raise VerifyFailure(
            "cross-resolution verification found fewer than two participant "
            f"health-bar witnesses: {checked_health_bars}"
        )
    if require_distinct and edge_contained_health_bars == 0:
        raise VerifyFailure(
            "cross-resolution verification did not exercise a participant "
            "name/health bar at a viewport edge"
        )
    return {
        "resolutions": resolutions,
        "distinct": distinct,
        "distinct_required": require_distinct,
        "viewport_contained_health_bars": checked_health_bars,
        "edge_contained_health_bars": edge_contained_health_bars,
    }


def configure_hud_participants(
    pair: SteamFriendActivePair,
    host_log: Path,
    client_log: Path,
    names: dict[str, str],
) -> tuple[hud.Participant, hud.Participant]:
    host = hud.Participant(
        "host",
        pair.host_participant_id,
        names["host"],
        HOST_ENDPOINT,
        host_log,
        HOST_SCREENSHOT,
    )
    client = hud.Participant(
        "client",
        pair.client_participant_id,
        names["client"],
        CLIENT_ENDPOINT,
        client_log,
        CLIENT_SCREENSHOT,
    )
    hud.HOST = host
    hud.CLIENT = client
    hud.PARTICIPANTS = (host, client)
    hud.lua = pair.lua
    return host, client


def place_pair_for_capture(pair: SteamFriendActivePair) -> dict[str, Any]:
    host_state = local_sync.query(HOST_ENDPOINT)
    center_x = float(host_state["player.x"])
    center_y = float(host_state["player.y"])
    host_requested = (center_x - CAPTURE_HALF_SEPARATION, center_y, 90.0)
    client_requested = (center_x + CAPTURE_HALF_SEPARATION, center_y, 270.0)
    local_sync.hold_player_heading(HOST_ENDPOINT, host_requested[2])
    local_sync.hold_player_heading(CLIENT_ENDPOINT, client_requested[2])
    try:
        writes = {
            "host": local_sync.place_player(HOST_ENDPOINT, *host_requested),
            "client": local_sync.place_player(CLIENT_ENDPOINT, *client_requested),
        }
        # Stock navigation can legally correct a raw test placement near the
        # edge of the current Boneyard. The replicated contract is that each
        # observer reaches the owner's settled native transform, not that the
        # game preserves an out-of-bounds coordinate written by the harness.
        host_target = local_sync.wait_for_local_transform_settled(
            HOST_ENDPOINT,
            stable_seconds=0.75,
        )
        client_target = local_sync.wait_for_local_transform_settled(
            CLIENT_ENDPOINT,
            stable_seconds=0.75,
        )
        # Settling the second process can overlap a late correction on the
        # first, so refresh both native truths immediately before convergence.
        host_target = local_sync.wait_for_local_transform_settled(
            HOST_ENDPOINT,
            stable_seconds=0.75,
        )
        client_view = local_sync.wait_for_remote_convergence(
            CLIENT_ENDPOINT,
            pair.host_participant_id,
            *host_target,
            timeout=15.0,
        )
        client_target = local_sync.wait_for_local_transform_settled(
            CLIENT_ENDPOINT,
            stable_seconds=0.75,
        )
        host_view = local_sync.wait_for_remote_convergence(
            HOST_ENDPOINT,
            pair.client_participant_id,
            *client_target,
            timeout=15.0,
        )
    finally:
        local_sync.hold_player_heading(HOST_ENDPOINT, None)
        local_sync.hold_player_heading(CLIENT_ENDPOINT, None)
    return {
        "host_requested": list(host_requested),
        "client_requested": list(client_requested),
        "host_settled": list(host_target),
        "client_settled": list(client_target),
        "writes": writes,
        "client_observed_host": [
            float(client_view[f"peer.{pair.host_participant_id}.x"]),
            float(client_view[f"peer.{pair.host_participant_id}.y"]),
        ],
        "host_observed_client": [
            float(host_view[f"peer.{pair.client_participant_id}.x"]),
            float(host_view[f"peer.{pair.client_participant_id}.y"]),
        ],
    }


def restore_vitals(endpoint: str, snapshot: dict[str, str]) -> dict[str, str]:
    return health.set_local_player_vitals(
        endpoint,
        float(snapshot["hp"]),
        float(snapshot["max_hp"]),
        mp=float(snapshot["mp"]),
        max_mp=float(snapshot["max_mp"]),
    )


def suspend_runtime_test_godmode(
    pair: SteamFriendActivePair,
    endpoint: str,
    label: str,
) -> str:
    values = parse_key_values(
        pair.lua(
            endpoint,
            r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local previous = _G.__sdmod_steam_test_godmode_enabled
emit('previous', previous == nil and 'nil' or previous)
_G.__sdmod_steam_test_godmode_enabled = false
emit('enabled', _G.__sdmod_steam_test_godmode_enabled)
""",
            timeout=8.0,
        )
    )
    previous = values.get("previous", "")
    if previous not in {"nil", "false", "true"} or values.get("enabled") != "false":
        raise VerifyFailure(
            f"failed to suspend runtime test godmode on {label}: {values}"
        )
    return previous


def restore_runtime_test_godmode(
    pair: SteamFriendActivePair,
    endpoint: str,
    label: str,
    previous: str,
) -> None:
    value_expression = {
        "nil": "nil",
        "false": "false",
        "true": "true",
    }.get(previous)
    if value_expression is None:
        raise VerifyFailure(
            f"invalid runtime test godmode state for {label}: {previous!r}"
        )
    values = parse_key_values(
        pair.lua(
            endpoint,
            "_G.__sdmod_steam_test_godmode_enabled = "
            + value_expression
            + "\nprint('restored=' .. tostring(_G.__sdmod_steam_test_godmode_enabled))",
            timeout=8.0,
        )
    )
    expected = "nil" if previous == "nil" else previous
    if values.get("restored") != expected:
        raise VerifyFailure(
            f"failed to restore runtime test godmode on {label}: {values}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--require-distinct-resolutions", action="store_true")
    args = parser.parse_args()

    started_at = time.time()
    pair = SteamFriendActivePair()
    output: dict[str, Any] = {"ok": False}
    client_vitals_before: dict[str, str] | None = None
    client_godmode_before: str | None = None
    return_code = 1
    try:
        output["active_step"] = "discover_pair"
        output["pair"] = pair.discover()
        require_shared_test_run(output["pair"])
        context = configure_behavior_context(pair)
        names = configure_modules(pair)
        host, client = configure_hud_participants(
            pair,
            context.host_log,
            context.client_log,
            names,
        )

        output["active_step"] = "visual_state"
        host_state = local_sync.query(HOST_ENDPOINT)
        client_state = local_sync.query(CLIENT_ENDPOINT)
        if int(host_state["peer.count"]) != 1 or int(client_state["peer.count"]) != 1:
            raise VerifyFailure("each two-player peer must expose exactly one remote participant")
        output["visual_state"] = {
            "host_owned": participant_visuals(
                host_state,
                client_state,
                pair.host_participant_id,
            ),
            "client_owned": participant_visuals(
                client_state,
                host_state,
                pair.client_participant_id,
            ),
        }

        output["active_step"] = "transform_and_heading"
        output["presentation_transform"] = local_sync.verify_scene("testrun")
        output["animation"] = {
            owner: animation.verify_animation_field_replication(
                direction(pair, names, owner=owner)
            )
            for owner in ("host", "client")
        }
        output["capture_placement"] = place_pair_for_capture(pair)

        output["active_step"] = "half_health_hud"
        client_godmode_before = suspend_runtime_test_godmode(
            pair,
            CLIENT_ENDPOINT,
            "client",
        )
        client_vitals_before = health.query_local_player_vitals(CLIENT_ENDPOINT)
        client_max_hp = float(client_vitals_before["max_hp"])
        client_half_hp = client_max_hp * 0.5
        output["client_half_health_write"] = health.set_local_player_vitals(
            CLIENT_ENDPOINT,
            client_half_hp,
            client_max_hp,
            mp=float(client_vitals_before["mp"]),
            max_mp=float(client_vitals_before["max_mp"]),
        )
        output["client_half_health_observer"] = (
            health.wait_for_remote_matches_owner_health(
                CLIENT_ENDPOINT,
                HOST_ENDPOINT,
                pair.client_participant_id,
                client_max_hp,
                expect_dead=False,
                timeout=args.timeout,
            )
        )
        output["render_logs"] = hud.wait_for_render_logs(args.timeout)
        output["ally_row_contract"] = {
            "host": successful_ally_rows(
                host.log,
                local_participant_id=pair.host_participant_id,
                remote_participant_id=pair.client_participant_id,
            ),
            "client": successful_ally_rows(
                client.log,
                local_participant_id=pair.client_participant_id,
                remote_participant_id=pair.host_participant_id,
            ),
        }

        output["active_step"] = "screenshots"
        frame_capture.lua = pair.lua
        output["screenshots"] = {
            "host": capture_remote_host_backbuffer(pair, HOST_SCREENSHOT),
            "client": frame_capture.capture_game_backbuffer(
                CLIENT_ENDPOINT,
                CLIENT_SCREENSHOT,
            ),
        }
        output["resolution_contract"] = verify_capture_resolution_contract(
            output["screenshots"],
            output["render_logs"],
            require_distinct=args.require_distinct_resolutions,
        )
        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
        if output["new_crash_artifacts"]:
            raise VerifyFailure("new crash artifacts appeared during visual verification")
        output.pop("active_step", None)
        output["ok"] = True
        return_code = 0
    except (VerifyFailure, subprocess.SubprocessError, ValueError, OSError) as exc:
        output["error"] = str(exc)
        output["error_type"] = type(exc).__name__
        output["traceback"] = traceback.format_exc()
        output["new_crash_artifacts"] = find_new_crash_artifacts(started_at)
    finally:
        if client_vitals_before is not None:
            try:
                output["client_vitals_restore"] = restore_vitals(
                    CLIENT_ENDPOINT,
                    client_vitals_before,
                )
            except (VerifyFailure, subprocess.SubprocessError, ValueError, OSError) as exc:
                output["client_vitals_restore_error"] = str(exc)
                output["ok"] = False
                return_code = 1
        if client_godmode_before is not None:
            try:
                restore_runtime_test_godmode(
                    pair,
                    CLIENT_ENDPOINT,
                    "client",
                    client_godmode_before,
                )
            except (VerifyFailure, subprocess.SubprocessError, ValueError, OSError) as exc:
                output["client_godmode_restore_error"] = str(exc)
                output["ok"] = False
                return_code = 1
        pair.close()
        output = pair.redact(output)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "active_step": output.get("active_step"),
                "error": output.get("error"),
                "visual_state": output.get("visual_state"),
                "ally_row_contract": output.get("ally_row_contract"),
                "screenshots": output.get("screenshots"),
                "new_crash_artifacts": output.get("new_crash_artifacts", []),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
