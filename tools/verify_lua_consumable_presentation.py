#!/usr/bin/env python3
"""Verify registered potion icons and duration-bound native VFX on a hosted pair."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_local_multiplayer_sync as sync  # noqa: E402
import verify_world_render_z_order as zorder  # noqa: E402
from multiplayer_defense_behavior_harness import (  # noqa: E402
    invoke_native_magic_hit_trial,
)
from multiplayer_frame_capture import capture_game_backbuffer  # noqa: E402


FIRST_CUSTOM_POTION_SUBTYPE = 6


def parse_values(pipe: str, code: str) -> dict[str, str]:
    return sync.parse_key_values(sync.lua(pipe, code, timeout=15.0))


def item_definition(pipe: str) -> dict[str, int]:
    values = parse_values(
        pipe,
        """
local item = sd.items.get("invincibility_potion")
print("content_id=" .. tostring(item and item.id or 0))
print("native_subtype=" .. tostring(item and item.native_subtype or -1))
print("duration_ms=" .. tostring(item and item.duration_ms or -1))
""",
    )
    result = {
        "content_id": int(values.get("content_id", "0")),
        "native_subtype": int(values.get("native_subtype", "-1")),
        "duration_ms": int(values.get("duration_ms", "-1")),
    }
    if (
        result["content_id"] <= 0
        or result["native_subtype"] < FIRST_CUSTOM_POTION_SUBTYPE
        or result["duration_ms"] <= 0
    ):
        raise sync.VerifyFailure(
            f"Invincibility Potion definition is incomplete: {values}"
        )
    return result


def wait_inventory_item(
    pipe: str,
    native_subtype: int,
    timeout: float,
) -> dict[str, int]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_values(
            pipe,
            f"""
local inventory = sd.player.get_inventory_state()
print("root=" .. tostring(inventory and inventory.item_list_root_address or 0))
for _, item in ipairs(inventory and inventory.items or {{}}) do
  if item.type_id == {zorder.POTION_TYPE_ID} and item.slot == {native_subtype} then
    print("item_address=" .. tostring(item.item_address or 0))
    print("slot=" .. tostring(item.slot))
    print("stack=" .. tostring(item.stack_count or 0))
    break
  end
end
""",
        )
        if (
            int(last.get("root", "0")) > 0
            and int(last.get("item_address", "0")) > 0
            and int(last.get("slot", "-1")) == native_subtype
            and int(last.get("stack", "0")) > 0
        ):
            return {
                "root": int(last["root"]),
                "item_address": int(last["item_address"]),
                "slot": int(last["slot"]),
                "stack": int(last["stack"]),
            }
        time.sleep(0.2)
    raise sync.VerifyFailure(f"custom inventory item did not arrive: {last}")


def wait_inventory_surface(
    pipe: str,
    expected: bool,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = parse_values(
            pipe,
            """
local surface = sd.hub.get_surface_state()
print("valid=" .. tostring(surface and surface.valid or false))
print("active=" .. tostring(surface and surface.inventory_screen_active or false))
print("surface_address=" .. tostring(surface and surface.surface_address or 0))
print("surface_vtable=" .. tostring(surface and surface.surface_vtable or 0))
""",
        )
        if last.get("active") == str(expected).lower():
            return last
        time.sleep(0.1)
    raise sync.VerifyFailure(
        f"inventory surface did not become {expected}: {last}"
    )


def strong_green_stats(path: Path) -> dict[str, int]:
    with Image.open(path) as opened:
        image = opened.convert("RGB")
        pixels = list(image.get_flattened_data())
    matches = [
        pixel
        for pixel in pixels
        if pixel[1] >= 150
        and pixel[1] >= pixel[0] * 1.65
        and pixel[1] >= pixel[2] * 1.25
    ]
    return {
        "width": image.width,
        "height": image.height,
        "strong_green_pixels": len(matches),
        "maximum_green": max((pixel[1] for pixel in matches), default=0),
    }


def inventory_icon_visible(
    closed: dict[str, int],
    opened: dict[str, int],
) -> bool:
    closed_count = closed["strong_green_pixels"]
    opened_count = opened["strong_green_pixels"]
    return opened_count >= 64 and opened_count >= closed_count + 48


def analyze_vfx_visibility(
    evidence: Path,
    baseline: dict[str, Any],
    phase: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for role in ("host", "client"):
        baseline_path = evidence / f"vfx-baseline-{role}.png"
        phase_path = evidence / f"{label}-{role}.png"
        point = phase[role]["projection"]["effect"]
        with (
            Image.open(baseline_path) as before_open,
            Image.open(phase_path) as after_open,
        ):
            before = before_open.convert("RGB")
            after = after_open.convert("RGB")
            box = zorder._crop_box(after, point, half_width=75, half_height=85)
            difference = ImageChops.difference(
                before.crop(box),
                after.crop(box),
            )
            changed = sum(
                1
                for pixel in difference.get_flattened_data()
                if max(pixel) >= 18
            )
        green_before = zorder.color_stats(
            baseline_path,
            baseline[role]["projection"]["effect"],
            color="green",
        )
        green_after = zorder.color_stats(
            phase_path,
            point,
            color="green",
        )
        result[role] = {
            "visible": changed >= 40
            and green_after["matching_pixels"]
            > green_before["matching_pixels"],
            "box": list(box),
            "changed_pixels": changed,
            "green_before": green_before,
            "green_after": green_after,
        }
    return result


def require_vfx_visibility(
    analysis: dict[str, Any],
    expected: bool,
    label: str,
) -> None:
    mismatches = {
        role: row
        for role, row in analysis.items()
        if row["visible"] is not expected
    }
    if mismatches:
        raise sync.VerifyFailure(
            f"native SpellGlow visibility mismatch at {label}: {mismatches}"
        )


def wait_until_elapsed(started: float, elapsed_seconds: float) -> float:
    while True:
        remaining = started + elapsed_seconds - time.monotonic()
        if remaining <= 0.0:
            return time.monotonic() - started
        time.sleep(min(remaining, 0.5))


def wait_for_log_token(path: Path, token: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and token in path.read_text(
            encoding="utf-8",
            errors="replace",
        ):
            return
        time.sleep(0.2)
    raise sync.VerifyFailure(f"loader log never contained {token!r}: {path}")


def run(
    *,
    evidence: Path,
    game_directory: Path,
    runtime_root: Path,
    launcher_path: Path,
    instance_prefix: str,
    ports: tuple[int, int],
    timeout: float,
    expected_source_sha: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    evidence.mkdir(parents=True, exist_ok=True)
    pipes = {
        role: f"SolomonDarkModLoader_LuaExec_{instance_prefix}-{role}"
        for role in ("host", "client")
    }
    process_ids: list[int] = []
    result.update(
        {
            "ok": False,
            "audio_disabled": True,
            "source_and_artifacts": zorder.verify_exact_source_and_artifacts(
                expected_source_sha
            ),
        }
    )
    try:
        occupied = zorder.bound_campaign_ports(ports)
        if occupied:
            raise sync.VerifyFailure(
                f"campaign ports were occupied before launch: {occupied}"
            )
        launch = sync.launch_pair(
            host_preset="map_create_fire_mind_hub",
            client_preset="map_create_water_body_hub",
            temporary_host_profile=True,
            god_mode=False,
            tile_windows=False,
            allow_focus_steal=False,
            kill_existing=False,
            instance_prefix=instance_prefix,
            host_port=ports[0],
            client_port=ports[1],
            third_port=ports[1] + 1,
            game_directory=game_directory,
            launcher_path=launcher_path,
            runtime_root=runtime_root,
            exact_mod_id=zorder.MOD_ID,
            quick_start=True,
            enable_audio=False,
        )
        process_ids = sync.game_process_ids(launch)
        if len(process_ids) != 2:
            raise sync.VerifyFailure(f"pair did not report two PIDs: {launch}")
        result["launch"] = launch
        result["process_ids"] = process_ids
        result["launched_processes"] = zorder.verify_launched_processes_and_modules(
            launch,
            runtime_root=runtime_root,
            launcher_path=launcher_path,
            instance_prefix=instance_prefix,
            loader_sha256=result["source_and_artifacts"]["loader_sha256"],
        )
        result["udp_port_owners"] = zorder.verify_campaign_port_owners(
            ports,
            launch,
        )

        sync.wait_for_remote(
            pipes["host"], sync.CLIENT_ID, sync.CLIENT_NAME, "hub", timeout
        )
        sync.wait_for_remote(
            pipes["client"], sync.HOST_ID, sync.HOST_NAME, "hub", timeout
        )
        for pipe in pipes.values():
            sync.lua(pipe, "lua_bots_disable_tick=true; sd.bots.clear(); return true")
        sync.start_testrun(pipes["host"])
        for pipe in pipes.values():
            sync.wait_for_scene(pipe, "testrun", timeout)
        sync.wait_for_remote(
            pipes["host"], sync.CLIENT_ID, sync.CLIENT_NAME, "testrun", timeout
        )
        sync.wait_for_remote(
            pipes["client"], sync.HOST_ID, sync.HOST_NAME, "testrun", timeout
        )

        definition = item_definition(pipes["host"])
        result["item_definition"] = definition
        host_state = sync.query(pipes["host"])
        drop_x = float(host_state["player.x"]) + 260.0
        drop_y = float(host_state["player.y"]) + 220.0
        pickup_hold = zorder.set_local_pickup_range(
            pipes["host"],
            pickup_range=0.01,
        )
        result["pickup_hold"] = pickup_hold
        spawn = parse_values(
            pipes["host"],
            f"""
local ok, err = sd.world.spawn_reward({{
  kind = "lua_consumable", amount = {definition['native_subtype']},
  x = {drop_x:.6f}, y = {drop_y:.6f}
}})
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
""",
        )
        if spawn.get("ok") != "true":
            raise sync.VerifyFailure(f"custom drop spawn failed: {spawn}")
        result["spawn"] = spawn
        deadline = time.monotonic() + timeout
        replicated_drop: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            for row in zorder.loot_rows(pipes["client"]):
                if (
                    row["item_slot"] == definition["native_subtype"]
                    and row["materialized"]
                ):
                    replicated_drop = row
                    break
            if replicated_drop is not None:
                break
            time.sleep(0.2)
        if replicated_drop is None:
            raise sync.VerifyFailure("custom drop did not materialize on the client")
        result["replicated_drop"] = replicated_drop

        result["pickup_restore"] = zorder.set_local_pickup_range(
            pipes["host"],
            pickup_range=float(pickup_hold["previous"]),
        )
        sync.place_player(pipes["host"], drop_x, drop_y, 0.0)
        sync.wait_for_local_transform_settled(pipes["host"], timeout=timeout)
        result["inventory_item"] = wait_inventory_item(
            pipes["host"],
            definition["native_subtype"],
            timeout,
        )

        closed_path = evidence / "inventory-closed-host.png"
        result["inventory_closed_capture"] = capture_game_backbuffer(
            pipes["host"],
            closed_path,
        )
        closed_green = strong_green_stats(closed_path)
        result["inventory_closed_green"] = closed_green
        result["inventory_open_press"] = sync.lua(
            pipes["host"],
            "return tostring(sd.input.press_binding('inventory'))",
        ).strip()
        result["inventory_open_surface"] = wait_inventory_surface(
            pipes["host"],
            True,
            10.0,
        )
        time.sleep(0.75)
        opened_path = evidence / "inventory-open-host.png"
        result["inventory_open_capture"] = capture_game_backbuffer(
            pipes["host"],
            opened_path,
        )
        opened_green = strong_green_stats(opened_path)
        result["inventory_open_green"] = opened_green
        result["inventory_icon_visible"] = inventory_icon_visible(
            closed_green,
            opened_green,
        )
        if not result["inventory_icon_visible"]:
            raise sync.VerifyFailure(
                "registered green inventory icon was not visible: "
                f"closed={closed_green} open={opened_green}"
            )
        result["inventory_close_press"] = sync.lua(
            pipes["host"],
            "return tostring(sd.input.press_binding('inventory'))",
        ).strip()
        result["inventory_closed_surface"] = wait_inventory_surface(
            pipes["host"],
            False,
            10.0,
        )

        log_paths = {
            role: runtime_root
            / "instances"
            / f"{instance_prefix}-{role}"
            / "stage/.sdmod/logs/solomondarkmodloader.log"
            for role in pipes
        }
        wait_for_log_token(
            log_paths["host"],
            "custom inventory glyph reached stock scaled draw",
            timeout,
        )

        effect_x = drop_x + 180.0
        effect_y = drop_y + 120.0
        result["effect_placement"] = zorder.place_pair(
            pipes["host"],
            pipes["client"],
            host_target=(effect_x, effect_y, 0.0),
            client_target=(effect_x + 120.0, effect_y, 180.0),
            timeout=timeout,
        )
        host_view = sync.query(pipes["host"])
        client_view = sync.query(pipes["client"])
        effect_points = {
            "host": {
                "effect": (
                    float(host_view["player.x"]),
                    float(host_view["player.y"]),
                )
            },
            "client": {
                "effect": (
                    float(client_view[f"peer.{sync.HOST_ID}.x"]),
                    float(client_view[f"peer.{sync.HOST_ID}.y"]),
                )
            },
        }
        baseline = zorder.capture_phase(
            evidence,
            "vfx-baseline",
            pipes,
            points_by_role=effect_points,
        )
        result["vfx_baseline"] = baseline
        result["consume"] = zorder.wait_for_and_consume_custom_inventory_item(
            pipes["host"],
            native_subtype=definition["native_subtype"],
            timeout=timeout,
        )
        consumed_at = time.monotonic()
        initial, initial_analysis = zorder.wait_for_vfx_capture(
            evidence,
            baseline,
            pipes,
            effect_points,
            timeout=min(timeout, 10.0),
        )
        result["vfx_initial"] = initial
        result["vfx_initial_analysis"] = initial_analysis
        for path in log_paths.values():
            wait_for_log_token(
                path,
                "consumable VFX native carrier drawn",
                timeout,
            )

        duration_seconds = definition["duration_ms"] / 1000.0
        before_damage_target = max(0.0, duration_seconds - 8.0)
        result["before_damage_wait_elapsed"] = wait_until_elapsed(
            consumed_at,
            before_damage_target,
        )
        before_damage = invoke_native_magic_hit_trial(
            pipes["host"],
            projectile_damage=12.0,
            magic_damage=0.0,
            attempts=1,
            label="registered consumable before duration expiry",
            timeout=15.0,
            require_life_loss=False,
        )
        if not math.isclose(before_damage["hp_delta"], 0.0, abs_tol=0.001):
            raise sync.VerifyFailure(
                f"consumable effect ended before duration: {before_damage}"
            )
        result["damage_before_expiry"] = before_damage
        result["damage_before_expiry_elapsed"] = time.monotonic() - consumed_at

        near_target = max(0.0, duration_seconds - 2.5)
        result["near_expiry_wait_elapsed"] = wait_until_elapsed(
            consumed_at,
            near_target,
        )
        near_started = time.monotonic()
        near_phase = zorder.capture_phase(
            evidence,
            "vfx-near-expiry",
            pipes,
            points_by_role=effect_points,
        )
        near_finished_elapsed = time.monotonic() - consumed_at
        result["vfx_near_expiry"] = near_phase
        result["vfx_near_expiry_timing"] = {
            "started_elapsed_seconds": near_started - consumed_at,
            "finished_elapsed_seconds": near_finished_elapsed,
            "duration_seconds": duration_seconds,
        }
        if near_finished_elapsed >= duration_seconds:
            raise sync.VerifyFailure(
                "near-expiry captures did not finish inside the registered duration: "
                f"{result['vfx_near_expiry_timing']}"
            )
        near_analysis = analyze_vfx_visibility(
            evidence,
            baseline,
            near_phase,
            "vfx-near-expiry",
        )
        require_vfx_visibility(near_analysis, True, "near registered expiry")
        result["vfx_near_expiry_analysis"] = near_analysis

        result["post_expiry_wait_elapsed"] = wait_until_elapsed(
            consumed_at,
            duration_seconds + 2.0,
        )
        post_phase = zorder.capture_phase(
            evidence,
            "vfx-after-expiry",
            pipes,
            points_by_role=effect_points,
        )
        result["vfx_after_expiry"] = post_phase
        result["vfx_after_expiry_elapsed"] = time.monotonic() - consumed_at
        post_analysis = analyze_vfx_visibility(
            evidence,
            baseline,
            post_phase,
            "vfx-after-expiry",
        )
        require_vfx_visibility(post_analysis, False, "after registered expiry")
        result["vfx_after_expiry_analysis"] = post_analysis
        result["damage_after_expiry"] = invoke_native_magic_hit_trial(
            pipes["host"],
            projectile_damage=12.0,
            magic_damage=0.0,
            attempts=1,
            label="registered consumable after duration expiry",
            timeout=15.0,
            require_life_loss=True,
        )
        result["damage_after_expiry_elapsed"] = time.monotonic() - consumed_at

        for role, source in log_paths.items():
            destination = evidence / f"{role}-solomondarkmodloader.log"
            destination.write_bytes(source.read_bytes())
            log_text = destination.read_text(encoding="utf-8", errors="replace")
            if (
                "Lua registered item world sprite draw failed" in log_text
                or "Lua registered item inventory sprite draw failed" in log_text
                or "consumable VFX native carrier could not be queued" in log_text
                or "consumable VFX presentation skipped" in log_text
            ):
                raise sync.VerifyFailure(
                    f"registered item presentation logged a failure on {role}"
                )
            result.setdefault("logs", {})[role] = str(destination)
        result["summary"] = {
            "drop_materialized_both_peers": True,
            "native_inventory_icon_visible": True,
            "native_spell_glow_initial_both_peers": True,
            "native_spell_glow_near_expiry_both_peers": True,
            "native_spell_glow_absent_after_expiry_both_peers": True,
            "damage_blocked_before_expiry": True,
            "damage_resumed_after_expiry": True,
        }
        result["ok"] = True
        return result
    finally:
        result["cleanup"] = sync.stop_game_processes(process_ids)
        result["ports_after_cleanup"] = zorder.wait_for_campaign_ports_unbound(
            ports
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=Path("/mnt/c/SolomonDarkAbandonware"),
    )
    parser.add_argument("--runtime-root", type=Path, default=ROOT / "runtime")
    parser.add_argument(
        "--launcher-path",
        type=Path,
        default=ROOT / "dist/launcher/SolomonDarkModLauncher.exe",
    )
    parser.add_argument("--instance-prefix", required=True)
    parser.add_argument("--host-port", type=int, required=True)
    parser.add_argument("--client-port", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=75.0)
    parser.add_argument("--expected-source-sha", required=True)
    args = parser.parse_args()

    result: dict[str, Any] = {
        "ok": False,
        "instance_prefix": args.instance_prefix,
        "ports": [args.host_port, args.client_port],
    }
    exit_code = 0
    try:
        result = run(
            evidence=args.evidence,
            game_directory=args.game_dir,
            runtime_root=args.runtime_root,
            launcher_path=args.launcher_path,
            instance_prefix=args.instance_prefix,
            ports=(args.host_port, args.client_port),
            timeout=args.timeout,
            expected_source_sha=args.expected_source_sha,
            result=result,
        )
    except Exception as error:  # noqa: BLE001 - persist exact acceptance failure.
        result["error"] = str(error)
        result["error_type"] = type(error).__name__
        exit_code = 1

    args.evidence.mkdir(parents=True, exist_ok=True)
    output = args.evidence / "result.json"
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": result.get("ok", False),
                "error": result.get("error"),
                "summary": result.get("summary"),
                "output": str(output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
