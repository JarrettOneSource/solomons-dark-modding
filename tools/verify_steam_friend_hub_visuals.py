#!/usr/bin/env python3
"""Verify participant presentation on an already-running Steam friend pair."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import multiplayer_frame_capture as frame_capture
import verify_local_multiplayer_sync as local_sync
import verify_player_health_death_sync as health
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import VerifyFailure, parse_key_values
from verify_multiplayer_hud_names import (
    verify_ally_hud_name_layout,
    verify_dx9_nameplate_health_bar_geometry,
)
from verify_steam_friend_active_pair_state import configure_modules


DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_hub_visuals.json"
HALF_HP = 250.0
HALF_MAX_HP = 500.0
HUB_WINDOWS_CAPTURE_POSITION = (975.0, 375.0, 90.0)
HUB_PROTON_CAPTURE_POSITION = (1275.0, 375.0, 270.0)
RUN_WINDOWS_CAPTURE_POSITION = (1400.0, 1700.0, 90.0)
RUN_PROTON_CAPTURE_POSITION = (1600.0, 1700.0, 270.0)


@dataclass(frozen=True)
class Participant:
    label: str
    participant_id: int
    name: str
    endpoint: str
    log: Path
    screenshot: Path
    game_path_kind: Literal["windows", "proton"]
    instance: str


def matching_line(log_text: str, required_tokens: tuple[str, ...]) -> str:
    for line in log_text.splitlines():
        if all(token in line for token in required_tokens):
            return line
    raise VerifyFailure(
        "missing loader log record containing: " + ", ".join(required_tokens)
    )


def render_evidence(observer: Participant, owner: Participant) -> dict[str, Any]:
    log_text = observer.log.read_text(encoding="utf-8", errors="replace")
    participant_token = f"participant={owner.participant_id}"
    failed_draws = [
        line
        for line in log_text.splitlines()
        if "source=dx9_nameplate_healthbar" in line
        and participant_token in line
        and " ok=0 " in line
    ]
    if failed_draws:
        raise VerifyFailure(
            f"{observer.label} recorded failed DX9 health draws for {owner.label}: "
            f"{failed_draws[-1]}"
        )

    baseline_world = matching_line(
        log_text,
        (
            "source=playerwizard_render",
            participant_token,
            f"name={owner.name}",
            "ok=1",
            "health_bar=dx9",
            "health_valid=1",
            "health_percent=100",
        ),
    )
    baseline_dx9 = matching_line(
        log_text,
        (
            "source=dx9_nameplate_healthbar",
            participant_token,
            "ok=1",
            "health_percent=100",
        ),
    )
    half_world = matching_line(
        log_text,
        (
            "source=playerwizard_render",
            participant_token,
            f"name={owner.name}",
            "ok=1",
            "health_bar=dx9",
            "health_valid=1",
            "health_percent=50",
        ),
    )
    half_dx9 = matching_line(
        log_text,
        (
            "source=dx9_nameplate_healthbar",
            participant_token,
            "ok=1",
            "health_percent=50",
        ),
    )
    ally_hud = matching_line(
        log_text,
        (
            "source=ally_healthbar",
            participant_token,
            f"name={owner.name}",
            "ok=1",
            "hud_row=1",
            "stock_label=0",
            "layout_ok=1",
        ),
    )

    ally_lines = [
        line
        for line in log_text.splitlines()
        if "source=ally_healthbar" in line and " ok=1 " in line
    ]
    observed_participants: set[int] = set()
    observed_rows: set[int] = set()
    for line in ally_lines:
        participant_match = re.search(r"(?:^| )participant=([0-9]+)", line)
        row_match = re.search(r"(?:^| )hud_row=([0-9]+)", line)
        if participant_match is not None:
            observed_participants.add(int(participant_match.group(1)))
        if row_match is not None:
            observed_rows.add(int(row_match.group(1)))
    if observed_participants != {owner.participant_id} or observed_rows != {1}:
        raise VerifyFailure(
            f"{observer.label} ally HUD ownership/count mismatch: "
            f"participants={observed_participants} rows={observed_rows}"
        )

    return {
        "world_nameplate_baseline": baseline_world,
        "world_nameplate_half_health": half_world,
        "dx9_baseline": {
            "line": baseline_dx9,
            "geometry": verify_dx9_nameplate_health_bar_geometry(
                baseline_dx9,
                100,
            ),
        },
        "dx9_half_health": {
            "line": half_dx9,
            "geometry": verify_dx9_nameplate_health_bar_geometry(
                half_dx9,
                50,
            ),
        },
        "ally_hud": ally_hud,
        "ally_hud_layout": verify_ally_hud_name_layout(ally_hud),
        "ally_hud_unique_participant_count": len(observed_participants),
        "ally_hud_rows": sorted(observed_rows),
    }


def wait_for_render_evidence(
    participants: tuple[Participant, Participant], timeout: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            host, client = participants
            return {
                "windows_observes_proton": render_evidence(host, client),
                "proton_observes_windows": render_evidence(client, host),
            }
        except (OSError, VerifyFailure) as exc:
            last_error = str(exc)
        time.sleep(0.1)
    raise VerifyFailure(
        f"Steam friend visual render evidence did not converge: {last_error}"
    )


def compact_vitals(values: dict[str, str]) -> dict[str, float]:
    return {
        key: float(values[key])
        for key in ("hp", "max_hp", "mp", "max_mp")
    }


def place_for_capture(
    host: Participant,
    client: Participant,
    scene: str,
    timeout: float,
) -> dict[str, Any]:
    if scene == "hub":
        host_target = HUB_WINDOWS_CAPTURE_POSITION
        client_target = HUB_PROTON_CAPTURE_POSITION
    elif scene == "testrun":
        host_target = RUN_WINDOWS_CAPTURE_POSITION
        client_target = RUN_PROTON_CAPTURE_POSITION
    else:
        raise VerifyFailure(f"unsupported participant visual scene: {scene!r}")
    local_sync.hold_player_heading(host.endpoint, None)
    local_sync.hold_player_heading(client.endpoint, None)
    local_sync.place_player(host.endpoint, *host_target)
    local_sync.place_player(client.endpoint, *client_target)
    host_position = local_sync.wait_for_local_transform_settled(
        host.endpoint, stable_seconds=0.5
    )
    client_position = local_sync.wait_for_local_transform_settled(
        client.endpoint, stable_seconds=0.5
    )
    client_view = local_sync.wait_for_remote_convergence(
        client.endpoint,
        host.participant_id,
        *host_position,
        timeout=timeout,
    )
    host_view = local_sync.wait_for_remote_convergence(
        host.endpoint,
        client.participant_id,
        *client_position,
        timeout=timeout,
    )
    return {
        "windows": list(host_position),
        "proton": list(client_position),
        "windows_observer_error": math.hypot(
            float(host_view[f"peer.{client.participant_id}.x"])
            - client_position[0],
            float(host_view[f"peer.{client.participant_id}.y"])
            - client_position[1],
        ),
        "proton_observer_error": math.hypot(
            float(client_view[f"peer.{host.participant_id}.x"])
            - host_position[0],
            float(client_view[f"peer.{host.participant_id}.y"])
            - host_position[1],
        ),
    }


def presentation_relationships(
    host: Participant,
    client: Participant,
    scene: str,
    timeout: float,
) -> dict[str, Any]:
    host_seen = local_sync.wait_for_remote(
        host.endpoint,
        client.participant_id,
        client.name,
        scene,
        timeout,
    )
    client_seen = local_sync.wait_for_remote(
        client.endpoint,
        host.participant_id,
        host.name,
        scene,
        timeout,
    )
    observations = (
        (
            "windows_observes_proton",
            host,
            client,
            host_seen,
            client_seen,
        ),
        (
            "proton_observes_windows",
            client,
            host,
            client_seen,
            host_seen,
        ),
    )
    evidence: dict[str, Any] = {}
    for label, observer, owner, values, owner_source in observations:
        prefix = f"peer.{owner.participant_id}."
        owner_primary_type = local_sync.parse_int_text(
            owner_source.get("player.primary_visual_type"),
            0,
        )
        owner_secondary_type = local_sync.parse_int_text(
            owner_source.get("player.secondary_visual_type"),
            0,
        )
        owner_attachment_type = local_sync.parse_int_text(
            owner_source.get("player.attachment_visual_type"),
            0,
        )
        owner_attachment_address = local_sync.parse_int_text(
            owner_source.get("player.attachment_visual_address"),
            0,
        )
        if (
            {owner_primary_type, owner_secondary_type}
            != {
                local_sync.REMOTE_PRIMARY_VISUAL_TYPE_ID,
                local_sync.REMOTE_SECONDARY_VISUAL_TYPE_ID,
            }
            or owner_attachment_type
            != local_sync.REMOTE_ATTACHMENT_VISUAL_TYPE_ID
            or owner_attachment_address == 0
        ):
            raise VerifyFailure(
                f"{owner.label} local body/staff visual lanes are incomplete: "
                f"primary={owner_primary_type} secondary={owner_secondary_type} "
                f"attachment={owner_attachment_type} "
                f"attachment_present={owner_attachment_address != 0}"
            )
        element_id = local_sync.parse_int_text(values.get(prefix + "element_id"), -1)
        selector = values.get(prefix + "render_selector", "")
        selector_parts = [int(part, 0) for part in selector.split(",")]
        expected_selection = local_sync.REMOTE_RENDER_SELECTION_BY_ELEMENT.get(
            element_id
        )
        primary_type = local_sync.parse_int_text(
            values.get(prefix + "primary_visual_type"), 0
        )
        secondary_type = local_sync.parse_int_text(
            values.get(prefix + "secondary_visual_type"), 0
        )
        attachment_type = local_sync.parse_int_text(
            values.get(prefix + "attachment_visual_type"), 0
        )
        attachment_address = local_sync.parse_int_text(
            values.get(prefix + "attachment_visual_address"), 0
        )
        staff_visual_state = local_sync.parse_int_text(
            values.get(prefix + "staff_visual_state"), 0
        )
        if (
            len(selector_parts) != 5
            or expected_selection is None
            or selector_parts[3] != expected_selection
        ):
            raise VerifyFailure(
                f"{label} render selection mismatch: element={element_id} "
                f"selector={selector!r}"
            )
        if (
            primary_type != local_sync.REMOTE_PRIMARY_VISUAL_TYPE_ID
            or secondary_type != local_sync.REMOTE_SECONDARY_VISUAL_TYPE_ID
        ):
            raise VerifyFailure(
                f"{label} actor visual lanes are incomplete: "
                f"primary={primary_type} secondary={secondary_type}"
            )
        if (
            attachment_type != local_sync.REMOTE_ATTACHMENT_VISUAL_TYPE_ID
            or attachment_address == 0
        ):
            raise VerifyFailure(
                f"{label} remote staff attachment lane is incomplete: "
                f"type={attachment_type} address={attachment_address}"
            )
        source_blocks = local_sync.visual_blocks_by_type(
            owner_source,
            "player",
        )
        remote_blocks = local_sync.visual_blocks_by_type(values, prefix[:-1])
        for type_id, source_block in source_blocks.items():
            if remote_blocks.get(type_id) != source_block:
                raise VerifyFailure(
                    f"{label} remote visual block mismatch for type={type_id}"
                )
        evidence[label] = {
            "observer": observer.label,
            "owner": owner.label,
            "owner_local_primary_visual_type": owner_primary_type,
            "owner_local_secondary_visual_type": owner_secondary_type,
            "owner_local_attachment_visual_type": owner_attachment_type,
            "owner_local_attachment_visual_present": True,
            "name": values[prefix + "name"],
            "nameplate": values[prefix + "nameplate"],
            "materialized": values[prefix + "materialized"] == "true",
            "render_selector": selector,
            "primary_visual_type": primary_type,
            "secondary_visual_type": secondary_type,
            "attachment_visual_type": attachment_type,
            "attachment_visual_present": True,
            "staff_visual_state": f"0x{staff_visual_state:08X}",
            "visual_link_types": sorted(remote_blocks),
        }
    return evidence


def restore_vitals(participant: Participant, values: dict[str, float]) -> None:
    health.set_local_player_vitals(
        participant.endpoint,
        values["hp"],
        values["max_hp"],
        mp=values["mp"],
        max_mp=values["max_mp"],
    )


def suspend_runtime_test_godmode(
    pair: SteamFriendActivePair,
    participant: Participant,
) -> str:
    values = parse_key_values(
        pair.lua(
            participant.endpoint,
            r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
local previous = _G.__sdmod_steam_test_godmode_enabled
if previous == nil then
  emit('previous', 'nil')
else
  emit('previous', previous)
end
_G.__sdmod_steam_test_godmode_enabled = false
emit('enabled', _G.__sdmod_steam_test_godmode_enabled)
""",
            timeout=8.0,
        )
    )
    previous = values.get("previous", "")
    if previous not in {"nil", "false", "true"} or values.get("enabled") != "false":
        raise VerifyFailure(
            f"failed to suspend runtime test godmode on {participant.label}: {values}"
        )
    return previous


def restore_runtime_test_godmode(
    pair: SteamFriendActivePair,
    participant: Participant,
    previous: str,
) -> None:
    value_expression = {
        "nil": "nil",
        "false": "false",
        "true": "true",
    }.get(previous)
    if value_expression is None:
        raise VerifyFailure(
            f"invalid runtime test godmode state for {participant.label}: {previous!r}"
        )
    values = parse_key_values(
        pair.lua(
            participant.endpoint,
            "_G.__sdmod_steam_test_godmode_enabled = "
            + value_expression
            + "\nprint('restored=' .. tostring(_G.__sdmod_steam_test_godmode_enabled))",
            timeout=8.0,
        )
    )
    expected = "nil" if previous == "nil" else previous
    if values.get("restored") != expected:
        raise VerifyFailure(
            f"failed to restore runtime test godmode on {participant.label}: {values}"
        )


def run(timeout: float, output: Path) -> dict[str, Any]:
    host_instance = os.environ.get(
        "SDMOD_STEAM_HOST_INSTANCE", "steam-host-gameplay12"
    )
    client_instance = os.environ.get(
        "SDMOD_STEAM_CLIENT_INSTANCE", "wsl-steam-gameplay12"
    )
    pair = SteamFriendActivePair()
    originals: dict[str, dict[str, float]] = {}
    godmode_states: dict[str, str] = {}
    participants: tuple[Participant, Participant] | None = None
    try:
        pair_state = pair.discover()
        names = configure_modules(pair)
        frame_capture.lua = pair.lua
        host = Participant(
            "windows",
            pair.host_participant_id,
            names["host"],
            HOST_ENDPOINT,
            ROOT
            / "runtime/instances"
            / host_instance
            / "stage/.sdmod/logs/solomondarkmodloader.log",
            output.with_name(f"{output.stem}_windows.png"),
            "windows",
            host_instance,
        )
        client = Participant(
            "proton",
            pair.client_participant_id,
            names["client"],
            CLIENT_ENDPOINT,
            ROOT
            / "runtime/instances"
            / client_instance
            / "stage/.sdmod/logs/solomondarkmodloader.log",
            output.with_name(f"{output.stem}_proton.png"),
            "proton",
            client_instance,
        )
        participants = (host, client)
        for participant in participants:
            if not participant.log.is_file():
                raise VerifyFailure(
                    f"loader log is missing for {participant.label}: {participant.log}"
                )

        host_scene = str(pair_state["host"]["scene"])
        client_scene = str(pair_state["client"]["scene"])
        if host_scene != client_scene or host_scene not in {"hub", "testrun"}:
            raise VerifyFailure(
                "Steam friend participants are not in one settled shared scene: "
                f"windows={host_scene!r} proton={client_scene!r}"
            )
        relationships = presentation_relationships(
            host,
            client,
            host_scene,
            timeout,
        )
        capture_placement = place_for_capture(
            host,
            client,
            host_scene,
            timeout,
        )
        for participant in participants:
            godmode_states[participant.label] = suspend_runtime_test_godmode(
                pair,
                participant,
            )
            originals[participant.label] = compact_vitals(
                health.query_local_player_vitals(participant.endpoint)
            )
            health.set_local_player_vitals(
                participant.endpoint,
                HALF_HP,
                HALF_MAX_HP,
            )

        health_convergence = {
            "windows_observes_proton": health.wait_for_remote_matches_owner_health(
                client.endpoint,
                host.endpoint,
                client.participant_id,
                HALF_MAX_HP,
                expect_dead=False,
                timeout=timeout,
            ),
            "proton_observes_windows": health.wait_for_remote_matches_owner_health(
                host.endpoint,
                client.endpoint,
                host.participant_id,
                HALF_MAX_HP,
                expect_dead=False,
                timeout=timeout,
            ),
        }
        renders = wait_for_render_evidence(participants, timeout)
        screenshots = {
            participant.label: frame_capture.capture_game_backbuffer(
                participant.endpoint,
                participant.screenshot,
                game_path_kind=participant.game_path_kind,
            )
            for participant in participants
        }
        result: dict[str, Any] = {
            "ok": True,
            "pair": pair_state,
            "scene": host_scene,
            "relationships": relationships,
            "capture_placement": capture_placement,
            "half_health": {
                "owner_vitals": {
                    participant.label: {
                        "hp": HALF_HP,
                        "max_hp": HALF_MAX_HP,
                    }
                    for participant in participants
                },
                "convergence": health_convergence,
            },
            "renders": renders,
            "screenshots": screenshots,
            "summary": {
                "genuine_steam_accounts": 2,
                "observers": 2,
                "remote_world_nameplates": 2,
                "successful_dx9_health_bars": 2,
                "half_health_dx9_bars": 2,
                "ally_hud_rows_per_observer": 1,
                "generic_ally_labels": 0,
                "windows_capture": True,
                "proton_capture": True,
            },
        }
        return pair.redact(result)
    finally:
        if participants is not None:
            for participant in participants:
                original = originals.get(participant.label)
                if original is not None:
                    try:
                        restore_vitals(participant, original)
                    except Exception:
                        pass
                previous_godmode_state = godmode_states.get(participant.label)
                if previous_godmode_state is not None:
                    try:
                        restore_runtime_test_godmode(
                            pair,
                            participant,
                            previous_godmode_state,
                        )
                    except Exception:
                        pass
        pair.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        result = run(args.timeout, args.output)
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        return_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "error": result.get("error"),
                "summary": result.get("summary"),
                "screenshots": result.get("screenshots"),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
