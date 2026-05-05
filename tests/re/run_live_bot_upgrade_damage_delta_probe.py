#!/usr/bin/env python3
"""Live regression proving a native primary upgrade changes Boulder combat stats."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cast_state_probe as csp  # noqa: E402

ELEMENT_DAMAGE_PROBE = ROOT / "tools/probe_bot_element_damage.py"
OUTPUT_PATH = ROOT / "runtime/live_bot_upgrade_damage_delta_probe.json"
BASELINE_OUTPUT_PATH = ROOT / "runtime/probe_earth_baseline_25000_bot_only_goal_confirm.json"
UPGRADED_OUTPUT_PATH = ROOT / "runtime/probe_earth_upgraded_25000_bot_only_goal_confirm.json"
DEFAULT_TARGET_HP = 25000.0
DEFAULT_BOT_MP = 500.0


class BotUpgradeDamageDeltaProbeFailure(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise BotUpgradeDamageDeltaProbeFailure(f"expected probe artifact was not written: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def first_result(payload: dict[str, Any], label: str) -> dict[str, Any]:
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise BotUpgradeDamageDeltaProbeFailure(f"{label} probe has no result records")
    result = results[0]
    if not isinstance(result, dict):
        raise BotUpgradeDamageDeltaProbeFailure(f"{label} result is malformed: {result!r}")
    return result


def nested(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def bool_value(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def command_tail(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def run_element_damage_probe(
    *,
    output: Path,
    apply_primary_upgrade: bool,
    hp: float,
    bot_starting_mp: float,
    timeout_s: float,
    reuse_existing: bool,
) -> dict[str, Any]:
    if reuse_existing and output.exists():
        return {
            "skipped": True,
            "reason": "reuse_existing",
            "output": str(output),
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(ELEMENT_DAMAGE_PROBE),
        "--element",
        "earth",
        "--positioning",
        "bot_only",
        "--bot-starting-mp",
        str(bot_starting_mp),
        "--maintain-bot-mp",
        "--hp",
        str(hp),
        "--casts",
        "1",
        "--output",
        str(output),
    ]
    if apply_primary_upgrade:
        command.append("--apply-primary-upgrade")

    with csp.temporary_required_lua_mods(csp.LUA_BOT_MOD_ID):
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    return {
        "skipped": False,
        "command": command,
        "returncode": completed.returncode,
        "stdout_tail": command_tail(completed.stdout),
        "stderr_tail": command_tail(completed.stderr),
        "output": str(output),
    }


def validate_probe_pair(baseline: dict[str, Any], upgraded: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    baseline_result = first_result(baseline, "baseline")
    upgraded_result = first_result(upgraded, "upgraded")

    baseline_validation = baseline_result.get("validation", {})
    upgraded_validation = upgraded_result.get("validation", {})
    baseline_native = baseline_result.get("native_spell_stat_validation", {})
    upgraded_native = upgraded_result.get("native_spell_stat_validation", {})
    baseline_release = nested(
        baseline_native,
        ("native_projectile_spawn_validation", "matching_release"),
    ) or {}
    baseline_complete = nested(
        baseline_native,
        ("native_projectile_spawn_validation", "matching_complete"),
    ) or {}
    upgraded_release = nested(
        upgraded_native,
        ("native_projectile_spawn_validation", "matching_release"),
    ) or {}
    upgraded_complete = nested(
        upgraded_native,
        ("native_projectile_spawn_validation", "matching_complete"),
    ) or {}
    baseline_mana = baseline_native.get("matching_mana_prepared", {}) or {}
    upgraded_mana = upgraded_native.get("matching_mana_prepared", {}) or {}
    baseline_stats = baseline_native.get("native_spell_stats", {}) or {}
    upgraded_stats = upgraded_native.get("native_spell_stats", {}) or {}
    primary_upgrade = upgraded_result.get("primary_upgrade", {}) or {}
    upgrade_application = primary_upgrade.get("application", {}) or {}

    baseline_fresh = baseline.get("launcher_freshness", {}) or {}
    upgraded_fresh = upgraded.get("launcher_freshness", {}) or {}
    if not bool_value(baseline_fresh.get("matches")):
        failures.append(f"baseline launcher bundle is stale: {baseline_fresh}")
    if not bool_value(upgraded_fresh.get("matches")):
        failures.append(f"upgraded launcher bundle is stale: {upgraded_fresh}")
    if baseline_fresh.get("dist_hash") != upgraded_fresh.get("dist_hash"):
        failures.append(
            "baseline/upgraded probes did not run against the same staged loader hash: "
            f"baseline={baseline_fresh.get('dist_hash')} upgraded={upgraded_fresh.get('dist_hash')}"
        )

    if baseline_native.get("ok") is not True:
        failures.append(f"baseline native spell validation failed: {baseline_native.get('checks')}")
    if upgraded_native.get("ok") is not True:
        failures.append(f"upgraded native spell validation failed: {upgraded_native.get('checks')}")
    if baseline_stats.get("source") != "live_progression_primary_stat_output":
        failures.append(f"baseline native stat source was not live progression output: {baseline_stats}")
    if upgraded_stats.get("source") != "live_progression_primary_stat_output":
        failures.append(f"upgraded native stat source was not live progression output: {upgraded_stats}")

    baseline_level = number(baseline_mana.get("progression_level"))
    upgraded_level = number(upgraded_mana.get("progression_level"))
    baseline_cost = number(baseline_mana.get("cost"))
    upgraded_cost = number(upgraded_mana.get("cost"))
    baseline_base_damage = number(baseline_release.get("base_damage"))
    upgraded_base_damage = number(upgraded_release.get("base_damage"))
    baseline_projected_damage = number(baseline_release.get("projected_damage"))
    upgraded_projected_damage = number(upgraded_release.get("projected_damage"))

    if baseline_level <= 0.0:
        failures.append(f"baseline progression level was not positive: {baseline_mana}")
    if upgraded_level <= baseline_level:
        failures.append(f"upgraded progression level did not increase: baseline={baseline_level} upgraded={upgraded_level}")
    if baseline_cost <= 0.0:
        failures.append(f"baseline native mana cost was not positive: {baseline_mana}")
    if upgraded_cost <= baseline_cost:
        failures.append(f"upgraded native mana cost did not increase: baseline={baseline_cost} upgraded={upgraded_cost}")
    if baseline_base_damage <= 0.0 or baseline_projected_damage <= 0.0:
        failures.append(f"baseline native boulder damage was not positive: {baseline_release}")
    if upgraded_base_damage <= baseline_base_damage:
        failures.append(
            "upgraded native boulder base damage did not increase: "
            f"baseline={baseline_base_damage} upgraded={upgraded_base_damage}"
        )
    if upgraded_projected_damage <= baseline_projected_damage:
        failures.append(
            "upgraded native boulder projected damage did not increase: "
            f"baseline={baseline_projected_damage} upgraded={upgraded_projected_damage}"
        )
    if int(number(baseline_release.get("target_in_impact"))) != 1:
        failures.append(f"baseline target was not in native impact radius: {baseline_release}")
    if int(number(upgraded_release.get("target_in_impact"))) != 1:
        failures.append(f"upgraded target was not in native impact radius: {upgraded_release}")
    if baseline_release.get("release_reason") != "max_size":
        failures.append(f"baseline did not use native max-size release: {baseline_release}")
    if baseline_complete.get("exit_label") not in {"max_size_reached", "max_size_released"}:
        failures.append(f"baseline did not complete via native max-size release: {baseline_complete}")
    if int(number(baseline_complete.get("post_release_ticks"))) < 60:
        failures.append(f"baseline did not preserve the native post-release launch window: {baseline_complete}")
    if "native_cleanup_release" in baseline_release or "threshold_charge_write" in baseline_release:
        failures.append(f"baseline still exposes removed threshold-release fields: {baseline_release}")

    if not bool_value(baseline_validation.get("any_cast_queued")):
        failures.append(f"baseline cast was not queued: {baseline_validation}")

    if primary_upgrade.get("matched") is not True:
        failures.append(f"upgraded run did not match the primary upgrade: {primary_upgrade}")
    if upgrade_application.get("matched_primary_upgrade") is not True:
        failures.append(f"upgraded application was not the primary upgrade: {upgrade_application}")
    if not bool_value(upgraded_validation.get("any_cast_queued")):
        failures.append(f"upgraded cast was not queued: {upgraded_validation}")
    if upgraded_release.get("release_reason") != "max_size":
        failures.append(f"upgraded native release was not max-size: {upgraded_release}")
    if int(number(upgraded_release.get("release_charge_write"))) != 1:
        failures.append(f"upgraded max-size release did not write release charge: {upgraded_release}")
    if "native_cleanup_release" in upgraded_release or "threshold_charge_write" in upgraded_release:
        failures.append(f"upgraded still exposes removed threshold-release fields: {upgraded_release}")
    if upgraded_complete.get("exit_label") not in {"max_size_reached", "max_size_released"}:
        failures.append(f"upgraded cast did not complete via max-size release: {upgraded_complete}")
    if int(number(upgraded_complete.get("post_release_ticks"))) < 60:
        failures.append(f"upgraded did not preserve the native post-release launch window: {upgraded_complete}")
    if int(number(upgraded_complete.get("release_target_actor"))) == 0:
        failures.append(f"upgraded cast-complete log did not preserve the target actor: {upgraded_complete}")

    baseline_hp_before = number(baseline_validation.get("hp_before"))
    upgraded_hp_before = number(upgraded_validation.get("hp_before"))
    upgraded_hp_after = number(upgraded_validation.get("hp_after"))
    if abs(baseline_hp_before - upgraded_hp_before) > 0.001:
        failures.append(
            "baseline and upgraded runs did not use the same target HP threshold: "
            f"baseline={baseline_hp_before} upgraded={upgraded_hp_before}"
        )
    summary = {
        "loader_hash": upgraded_fresh.get("dist_hash"),
        "baseline_level": baseline_level,
        "upgraded_level": upgraded_level,
        "baseline_mana_cost": baseline_cost,
        "upgraded_mana_cost": upgraded_cost,
        "baseline_base_damage": baseline_base_damage,
        "upgraded_base_damage": upgraded_base_damage,
        "baseline_projected_damage": baseline_projected_damage,
        "upgraded_projected_damage": upgraded_projected_damage,
        "baseline_release_reason": baseline_release.get("release_reason"),
        "upgraded_release_reason": upgraded_release.get("release_reason"),
        "upgraded_release_projected_damage": number(upgraded_complete.get("release_projected_damage")),
        "upgraded_release_target_actor": upgraded_complete.get("release_target_actor"),
        "baseline_hp_before": baseline_hp_before,
        "baseline_hp_after": number(baseline_validation.get("hp_after")),
        "baseline_any_hostile_damaged": bool_value(baseline_validation.get("any_hostile_damaged")),
        "upgraded_hp_before": upgraded_hp_before,
        "upgraded_hp_after": upgraded_hp_after,
        "upgraded_any_hostile_damaged": bool_value(upgraded_validation.get("any_hostile_damaged")),
        "upgrade_option_id": primary_upgrade.get("target_option_id"),
        "upgrade_matched_step": primary_upgrade.get("matched_step"),
        "upgrade_selected_option": nested(upgrade_application, ("selected_option", "name")),
    }
    if failures:
        raise BotUpgradeDamageDeltaProbeFailure(json.dumps({"summary": summary, "failures": failures}, indent=2))
    return summary


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    command_results = {
        "baseline": run_element_damage_probe(
            output=args.baseline_output,
            apply_primary_upgrade=False,
            hp=args.hp,
            bot_starting_mp=args.bot_starting_mp,
            timeout_s=args.timeout,
            reuse_existing=args.reuse_existing,
        ),
        "upgraded": run_element_damage_probe(
            output=args.upgraded_output,
            apply_primary_upgrade=True,
            hp=args.hp,
            bot_starting_mp=args.bot_starting_mp,
            timeout_s=args.timeout,
            reuse_existing=args.reuse_existing,
        ),
    }
    baseline = read_json(args.baseline_output)
    upgraded = read_json(args.upgraded_output)
    summary = validate_probe_pair(baseline, upgraded)
    baseline_returncode = command_results["baseline"].get("returncode")
    upgraded_returncode = command_results["upgraded"].get("returncode")
    if upgraded_returncode != 0 and not command_results["upgraded"].get("skipped"):
        raise BotUpgradeDamageDeltaProbeFailure(
            f"upgraded child damage probe failed with return code {upgraded_returncode}: "
            f"{command_results['upgraded']}"
        )
    if baseline_returncode not in {0, 1, None} and not command_results["baseline"].get("skipped"):
        raise BotUpgradeDamageDeltaProbeFailure(
            f"baseline child damage probe exited with unexpected return code {baseline_returncode}: "
            f"{command_results['baseline']}"
        )
    return {
        "passed": True,
        "command_results": command_results,
        "command_returncode_policy": {
            "baseline": (
                "0 or 1 accepted: the wrapper validates native baseline projection, "
                "while the child tool returns 1 when its standalone actual-damage criterion is not met"
            ),
            "upgraded": "0 required unless --reuse-existing skipped execution",
        },
        "artifacts": {
            "baseline": str(args.baseline_output),
            "upgraded": str(args.upgraded_output),
        },
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--baseline-output", type=Path, default=BASELINE_OUTPUT_PATH)
    parser.add_argument("--upgraded-output", type=Path, default=UPGRADED_OUTPUT_PATH)
    parser.add_argument("--hp", type=float, default=DEFAULT_TARGET_HP)
    parser.add_argument("--bot-starting-mp", type=float, default=DEFAULT_BOT_MP)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--reuse-existing", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    exit_code = 0
    try:
        result = run_probe(args)
    except Exception as exc:  # noqa: BLE001 - preserve live diagnostics.
        result = {
            "passed": False,
            "error": str(exc),
            "artifacts": {
                "baseline": str(args.baseline_output),
                "upgraded": str(args.upgraded_output),
            },
        }
        exit_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result.get("passed"):
        summary = result["summary"]
        print(
            "PASS: Earth primary upgrade changes live native Boulder projection "
            f"level={summary['baseline_level']:.0f}->{summary['upgraded_level']:.0f} "
            f"mana={summary['baseline_mana_cost']:.3f}->{summary['upgraded_mana_cost']:.3f} "
            f"projected={summary['baseline_projected_damage']:.3f}->{summary['upgraded_projected_damage']:.3f} "
            f"target_hp={summary['upgraded_hp_before']:.3f}->{summary['upgraded_hp_after']:.3f}"
        )
        print(f"Wrote {args.output}")
    else:
        print(f"FAIL: live bot upgrade damage delta probe: {result.get('error')}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
