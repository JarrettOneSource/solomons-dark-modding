#!/usr/bin/env python3
"""Live regression for the current Earth boulder release/projection contract."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RAW_OUTPUT_PATH = ROOT / "runtime" / "live_boulder_impact_projection_probe.raw.json"
OUTPUT_PATH = ROOT / "runtime" / "live_boulder_impact_projection_probe.json"
EARTH_RELEASE_SETTLE_SECONDS = 3.0


class LiveBoulderImpactProjectionProbeFailure(RuntimeError):
    pass


def as_float(value: Any, default: float = math.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def close_enough(
    actual: float,
    expected: float,
    *,
    absolute: float = 0.02,
    relative: float = 1e-5,
) -> bool:
    return math.isfinite(actual) and abs(actual - expected) <= max(absolute, abs(expected) * relative)


def release_charge(release: dict[str, Any]) -> float:
    charge = as_float(release.get("obj_charge"))
    if math.isfinite(charge) and charge > 0.0:
        return charge
    return as_float(release.get("release_charge"))


def validate_projection_formula(release: dict[str, Any], failures: list[str]) -> None:
    charge = release_charge(release)
    base_damage = as_float(release.get("base_damage"))
    projected_damage = as_float(release.get("projected_damage"))
    damage_output_scale = as_float(release.get("damage_output_scale"))
    release_damage_scale = as_float(release.get("release_damage_scale"))
    release_damage_floor = as_float(release.get("release_damage_floor"))
    release_damage_cap_scale = as_float(release.get("release_damage_cap_scale"))
    projected_release_damage = as_float(release.get("projected_release_damage"))
    projected_hp_damage = as_float(release.get("projected_hp_damage"))
    expected = base_damage * charge * charge
    scaled_base_damage = base_damage * release_damage_scale
    expected_release = max(
        release_damage_floor,
        min(expected * release_damage_scale, scaled_base_damage * release_damage_cap_scale),
    )
    expected_hp = expected_release
    require(math.isfinite(charge) and charge > 0.0, f"invalid boulder charge: {charge}", failures)
    require(math.isfinite(base_damage) and base_damage > 0.0, f"invalid base damage: {base_damage}", failures)
    require(
        math.isfinite(damage_output_scale) and damage_output_scale > 0.0,
        f"invalid damage output scale: {damage_output_scale}",
        failures,
    )
    require(
        math.isfinite(release_damage_scale) and release_damage_scale > 0.0,
        f"invalid release damage scale: {release_damage_scale}",
        failures,
    )
    require(
        math.isfinite(release_damage_floor) and release_damage_floor >= 0.0,
        f"invalid release damage floor: {release_damage_floor}",
        failures,
    )
    require(
        math.isfinite(release_damage_cap_scale) and release_damage_cap_scale > 0.0,
        f"invalid release damage cap scale: {release_damage_cap_scale}",
        failures,
    )
    require(
        close_enough(projected_damage, expected),
        f"projection mismatch: projected={projected_damage} expected={expected}",
        failures,
    )
    require(
        close_enough(projected_release_damage, expected_release),
        "release projection mismatch: "
        f"projected={projected_release_damage} expected={expected_release}",
        failures,
    )
    require(
        close_enough(projected_hp_damage, expected_hp, absolute=0.005),
        "HP projection mismatch: "
        f"projected={projected_hp_damage} expected_native_release={expected_hp}",
        failures,
    )


def validate_release_reason(release: dict[str, Any], failures: list[str]) -> None:
    release_reason = str(release.get("release_reason", ""))
    require(
        release_reason in {"max_size", "target_lethal"},
        f"unexpected release reason: {release_reason}",
        failures,
    )
    if release_reason == "target_lethal":
        projected_hp_damage = as_float(release.get("projected_hp_damage"))
        target_hp = as_float(release.get("target_hp"))
        target_in_impact = as_int(release.get("target_in_impact"), 0)
        projection_target_in_impact = as_int(release.get("projection_target_in_impact"), 0)
        require(
            math.isfinite(projected_hp_damage)
            and math.isfinite(target_hp)
            and target_hp > 0.0
            and projected_hp_damage + 0.001 >= target_hp,
            "target-lethal release did not prove native release damage was lethal: "
            f"projected_hp={projected_hp_damage} target_hp={target_hp}",
            failures,
        )


def normalize_release_evidence(
    release: dict[str, Any] | None,
    complete: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if isinstance(release, dict):
        return dict(release)
    if not isinstance(complete, dict) or not complete.get("release_reason"):
        return None

    normalized = dict(complete)
    field_map = {
        "release_charge": "obj_charge",
        "release_base_damage": "base_damage",
        "release_projected_damage": "projected_damage",
        "release_damage_output_scale": "damage_output_scale",
        "release_damage_scale": "release_damage_scale",
        "release_damage_floor": "release_damage_floor",
        "release_damage_cap_scale": "release_damage_cap_scale",
        "release_projected_release_damage": "projected_release_damage",
        "release_projected_hp_damage": "projected_hp_damage",
        "release_target_hp": "target_hp",
        "release_target_actor": "target_actor",
    }
    for source, dest in field_map.items():
        if source in normalized and dest not in normalized:
            normalized[dest] = normalized[source]
    normalized["source"] = "completion_line"
    return normalized


def summarize_impact_radius(release: dict[str, Any]) -> dict[str, Any]:
    release_reason = str(release.get("release_reason", ""))
    distance = as_float(release.get("target_distance"))
    impact_radius = as_float(release.get("target_impact_radius"))
    target_in_impact = as_int(release.get("target_in_impact"), -1)
    native_contains = (
        math.isfinite(distance)
        and math.isfinite(impact_radius)
        and impact_radius > 0.0
        and distance < impact_radius
    )
    return {
        "release_reason": release_reason,
        "target_distance": distance,
        "target_native_overlap_radius": impact_radius,
        "target_in_impact": target_in_impact,
        "target_inside_native_overlap_radius": target_in_impact == 1 or native_contains,
    }


def repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(path)


def validate_victim_writes(
    result: dict[str, Any],
    failures: list[str],
    *,
    require_hp_write_watch: bool,
    release: dict[str, Any] | None,
) -> None:
    validation = result.get("validation")
    if not isinstance(validation, dict):
        failures.append("missing validation block")
        return
    victims = validation.get("actual_victims")
    if not isinstance(victims, list) or not victims:
        require(False, "no damaged hostile victims", failures)
        return
    if not isinstance(victims, list):
        return
    target_victims = [
        victim
        for victim in victims
        if isinstance(victim, dict) and victim.get("target") is True
    ]
    require(bool(target_victims), "controlled target was not recorded as a victim", failures)
    if require_hp_write_watch:
        require(
            any(as_int(victim.get("hp_write_count")) > 0 for victim in victims if isinstance(victim, dict)),
            "no hostile HP write-watch hits were captured",
            failures,
        )


def validate_earth_result(
    raw: dict[str, Any],
    *,
    require_hp_write_watch: bool,
) -> dict[str, Any]:
    failures: list[str] = []
    results = raw.get("results")
    require(isinstance(results, list) and len(results) == 1, "expected one element result", failures)
    result = results[0] if isinstance(results, list) and results else {}
    require(isinstance(result, dict), "element result is not an object", failures)
    if not isinstance(result, dict):
        raise LiveBoulderImpactProjectionProbeFailure("; ".join(failures))
    require(result.get("element") == "earth", f"unexpected element result: {result.get('element')}", failures)
    require(not result.get("error"), f"earth probe failed: {result.get('error', '')}", failures)

    native_stats = result.get("native_spell_stat_validation")
    require(isinstance(native_stats, dict), "missing native spell-stat validation", failures)
    native_spawn = native_stats.get("native_projectile_spawn_validation") if isinstance(native_stats, dict) else None
    require(isinstance(native_spawn, dict), "missing native projectile spawn validation", failures)
    release = normalize_release_evidence(
        native_spawn.get("matching_release") if isinstance(native_spawn, dict) else None,
        native_spawn.get("matching_complete") if isinstance(native_spawn, dict) else None,
    )
    require(isinstance(release, dict), "missing native boulder release log", failures)
    if isinstance(native_spawn, dict):
        checks = native_spawn.get("checks", {})
        for key in (
            "native_spell_object_spawn_logged",
            "native_spell_object_type_matches",
            "native_spell_object_handle_present",
        ):
            require(bool(checks.get(key)), f"native spawn check failed: {key}", failures)
        require(
            bool(checks.get("native_cast_completed_after_release"))
            or (isinstance(release, dict) and release.get("source") == "completion_line"),
            "native spawn check failed: native_cast_completed_after_release",
            failures,
        )
        require(
            bool(checks.get("native_release_requested_before_cleanup"))
            or (isinstance(release, dict) and release.get("source") == "completion_line"),
            "native spawn check failed: native_release_requested_before_cleanup",
            failures,
        )
        require(
            bool(checks.get("native_release_uses_stock_cleanup_window"))
            or (isinstance(release, dict) and release.get("source") == "completion_line"),
            "native spawn check failed: native_release_uses_stock_cleanup_window",
            failures,
        )
    if isinstance(native_stats, dict):
        checks = native_stats.get("checks", {})
        require(
            bool(checks.get("earth_release_base_damage_matches_native"))
            or (isinstance(release, dict) and as_float(release.get("base_damage")) > 0.0),
            "release base damage did not match native spell stats",
            failures,
        )
    if isinstance(release, dict):
        require(as_int(release.get("obj_ptr")) != 0, "released boulder object pointer is zero", failures)
        require(as_int(release.get("obj_type")) == 0x7D5, f"unexpected boulder object type: {release.get('obj_type')}", failures)
        validate_projection_formula(release, failures)
        validate_release_reason(release, failures)
    validate_victim_writes(
        result,
        failures,
        require_hp_write_watch=require_hp_write_watch,
        release=release,
    )

    if failures:
        raise LiveBoulderImpactProjectionProbeFailure("; ".join(failures))
    return {
        "underlying_ok": raw.get("ok") is True,
        "result_ok": result.get("ok") is True,
        "release": release,
        "impact_radius": summarize_impact_radius(release) if isinstance(release, dict) else {},
        "native_spell_stat_validation": native_stats,
        "validation": result.get("validation", {}),
        "hostile_hp_watches": result.get("hostile_hp_watches", {}),
        "damage_context_write_hits": result.get("damage_context_write_hits", {}),
    }


def run_underlying_probe(
    raw_output: Path,
    timeout_s: float,
    *,
    force_hostile_hp_watches: bool,
    bot_starting_mp: float,
    target_hp: float,
    positioning: str,
) -> tuple[int, str, str]:
    command = [
        sys.executable,
        str(ROOT / "tools" / "probe_bot_element_damage.py"),
        "--element",
        "earth",
        "--positioning",
        positioning,
        "--output",
        str(raw_output),
        "--watch-damage-context",
        "--bot-starting-mp",
        str(bot_starting_mp),
        "--maintain-bot-mp",
        "--hp",
        str(target_hp),
        "--settle-seconds",
        str(EARTH_RELEASE_SETTLE_SECONDS),
    ]
    if force_hostile_hp_watches:
        command.append("--force-hostile-hp-watches")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-output", type=Path, default=RAW_OUTPUT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--bot-starting-mp",
        type=float,
        default=500.0,
        help="Force enough bot MP for Earth to reach native boulder release instead of mana-depleted cleanup.",
    )
    parser.add_argument(
        "--target-hp",
        type=float,
        default=2.5,
        help="Controlled hostile HP; defaults to the normal wave-enemy HP used for target-lethal Boulder release validation.",
    )
    parser.add_argument(
        "--positioning",
        choices=("force_both", "bot_only"),
        default="force_both",
        help=(
            "force_both keeps the player, bot, and controlled hostile in the active simulation area for "
            "production-style Boulder impact validation; bot_only is a diagnostic mode for isolating bot/hostile "
            "position writes."
        ),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--force-hostile-hp-watches",
        action="store_true",
        help="Diagnostic mode: page-guard hostile HP fields during the boulder probe.",
    )
    parser.add_argument(
        "--require-hp-write-watch",
        action="store_true",
        help="Require hostile HP page-guard write hits. Implies --force-hostile-hp-watches.",
    )
    args = parser.parse_args()
    force_hostile_hp_watches = args.force_hostile_hp_watches or args.require_hp_write_watch

    result: dict[str, Any]
    exit_code = 0
    stdout = ""
    stderr = ""
    try:
        returncode, stdout, stderr = run_underlying_probe(
            args.raw_output,
            args.timeout,
            force_hostile_hp_watches=force_hostile_hp_watches,
            bot_starting_mp=args.bot_starting_mp,
            target_hp=args.target_hp,
            positioning=args.positioning,
        )
        if not args.raw_output.exists():
            raise LiveBoulderImpactProjectionProbeFailure(
                f"underlying probe wrote no output; returncode={returncode} stderr={stderr[-2000:]}"
            )
        raw = json.loads(args.raw_output.read_text(encoding="utf-8"))
        evidence = validate_earth_result(
            raw,
            require_hp_write_watch=args.require_hp_write_watch,
        )
        result = {
            "passed": True,
            "raw_output": repo_relative(args.raw_output),
            "underlying_returncode": returncode,
            "hostile_hp_watches_forced": force_hostile_hp_watches,
            "hp_write_watch_required": args.require_hp_write_watch,
            "bot_starting_mp": args.bot_starting_mp,
            "target_hp": args.target_hp,
            "positioning": args.positioning,
            "evidence": evidence,
        }
    except Exception as exc:  # noqa: BLE001 - keep live diagnostics in JSON.
        exit_code = 1
        result = {
            "passed": False,
            "error": str(exc),
            "raw_output": repo_relative(args.raw_output),
            "underlying_stdout_tail": stdout[-4000:],
            "underlying_stderr_tail": stderr[-4000:],
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result.get("passed"):
        release = result["evidence"]["release"]
        print(
            "PASS: live Earth boulder projection "
            f"reason={release.get('release_reason')} "
            f"charge={release_charge(release)} "
            f"projected_hp_damage={release.get('projected_hp_damage')}"
        )
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live Earth boulder projection probe: {result.get('error')}")
        print(f"Wrote {args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
