#!/usr/bin/env python3
"""Live regression check for bot-native skill choices.

This wraps probe_bot_skill_choice_stress.py with explicit assertions so future
bot/progression changes can prove the level-up skill path still rolls, names,
applies, and reports native state changes correctly.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cast_state_probe as csp
import probe_bot_skill_choice_stress as stress


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "runtime" / "test_bot_skill_choice_regression.json"


class BotSkillChoiceRegressionFailure(RuntimeError):
    pass


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def option_name_is_resolved(option: dict[str, Any]) -> bool:
    name = str(option.get("name") or "")
    skill_file = str(option.get("skill_file") or "")
    native_text = str(option.get("native_text") or "")
    return bool(name) and not name.startswith("skill_") and bool(skill_file) and bool(native_text)


def is_expected_native_noop(bot_record: dict[str, Any]) -> bool:
    before = bot_record.get("progression_entry_before")
    if not isinstance(before, dict):
        return False

    max_level = as_int(before.get("statbook_max_level"), -1)
    active = as_int(before.get("active"), 0)
    visible = as_int(before.get("visible"), 0)
    return max_level > 0 and active >= max_level and visible >= max_level


def selected_option(bot_record: dict[str, Any]) -> dict[str, Any] | None:
    selected_index = as_int(bot_record.get("selected_index"), 0)
    options = bot_record.get("options_enriched")
    if not isinstance(options, list) or selected_index <= 0 or selected_index > len(options):
        return None
    selected = options[selected_index - 1]
    return selected if isinstance(selected, dict) else None


def validate_result(result: dict[str, Any], *, min_bots: int, min_iterations: int) -> dict[str, Any]:
    failures: list[str] = []
    iterations = result.get("iterations")
    if not isinstance(iterations, list) or len(iterations) < min_iterations:
        failures.append(f"expected at least {min_iterations} iterations, got {len(iterations) if isinstance(iterations, list) else 0}")
        iterations = []

    bonus_probe = result.get("bonus_choice_count_probe")
    bonus_count = 0
    if isinstance(bonus_probe, dict):
        choices = bonus_probe.get("choices")
        if isinstance(choices, dict):
            bonus_count = as_int(choices.get("count"), 0)
    if bonus_count < 4:
        failures.append(f"expected bonus choice-count probe to expose >=4 choices, got {bonus_count}")

    bot_ids: set[int] = set()
    application_count = 0
    changed_application_count = 0
    expected_noop_count = 0
    stat_diff_count = 0
    loadout_diff_count = 0
    selected_health_or_mana_count = 0
    verified_health_or_mana_count = 0

    for iteration_index, iteration in enumerate(iterations, start=1):
        if not isinstance(iteration, dict):
            failures.append(f"iteration {iteration_index} is not an object")
            continue
        bots = iteration.get("bots")
        if not isinstance(bots, list) or len(bots) < min_bots:
            failures.append(
                f"iteration {iteration_index} expected at least {min_bots} bot records, got {len(bots) if isinstance(bots, list) else 0}"
            )
            continue

        for bot_record_index, bot_record in enumerate(bots, start=1):
            if not isinstance(bot_record, dict):
                failures.append(f"iteration {iteration_index} bot record {bot_record_index} is not an object")
                continue

            application_count += 1
            bot_ids.add(as_int(bot_record.get("bot_id"), -1))
            option_count = as_int(bot_record.get("option_count"), 0)
            options = bot_record.get("options_enriched")
            selected = selected_option(bot_record)
            if not isinstance(options, list) or len(options) != option_count:
                failures.append(
                    f"iteration {iteration_index} bot {bot_record.get('bot_id')} option count mismatch"
                )
                continue

            for option in options:
                if not isinstance(option, dict) or not option_name_is_resolved(option):
                    failures.append(
                        f"iteration {iteration_index} bot {bot_record.get('bot_id')} has unresolved option metadata: {option}"
                    )

            if selected is None:
                failures.append(f"iteration {iteration_index} bot {bot_record.get('bot_id')} has invalid selected_index")
            else:
                selected_id = as_int(bot_record.get("selected_option_id"), -1)
                selected_name = str(bot_record.get("selected_option_name") or "")
                if as_int(selected.get("id"), -2) != selected_id or str(selected.get("name") or "") != selected_name:
                    failures.append(
                        f"iteration {iteration_index} bot {bot_record.get('bot_id')} selected option does not match enriched option"
                    )

            entry_changed = bool(bot_record.get("progression_entry_byte_diff"))
            stat_changed = bool(bot_record.get("progression_stat_diff"))
            if entry_changed or stat_changed:
                changed_application_count += 1
            elif is_expected_native_noop(bot_record):
                expected_noop_count += 1
            else:
                failures.append(
                    f"iteration {iteration_index} bot {bot_record.get('bot_id')} picked {bot_record.get('selected_option_name')} "
                    "but no progression entry/stat diff was observed"
                )

            if stat_changed:
                stat_diff_count += 1
            if bot_record.get("loadout_diff"):
                loadout_diff_count += 1

            for key in ("loadout_before", "loadout_after", "loadout_diff"):
                if key not in bot_record:
                    failures.append(f"iteration {iteration_index} bot {bot_record.get('bot_id')} missing {key}")

            selected_name = str(bot_record.get("selected_option_name") or "")
            if selected_name in {"HEALTH UP", "MANA UP"}:
                selected_health_or_mana_count += 1
                stat_diff = bot_record.get("progression_stat_diff")
                if isinstance(stat_diff, dict):
                    hp_keys = {"hp", "max_hp"}
                    mp_keys = {"mp", "max_mp"}
                    if selected_name == "HEALTH UP" and hp_keys.issubset(stat_diff):
                        verified_health_or_mana_count += 1
                    if selected_name == "MANA UP" and mp_keys.issubset(stat_diff):
                        verified_health_or_mana_count += 1

    unique_pool_counts = result.get("unique_pool_counts")
    if min_iterations > 1:
        if not isinstance(unique_pool_counts, dict) or not unique_pool_counts:
            failures.append("missing unique_pool_counts")
        else:
            for bot_id, unique_count in unique_pool_counts.items():
                if as_int(unique_count) < 2:
                    failures.append(f"bot {bot_id} did not show evolving skill pools")

    if len(bot_ids - {-1}) < min_bots:
        failures.append(f"expected at least {min_bots} unique bots, got {len(bot_ids - {-1})}")
    if application_count == 0:
        failures.append("no bot skill applications were recorded")
    if changed_application_count == 0:
        failures.append("no progression entry/stat changes were recorded")
    if selected_health_or_mana_count != verified_health_or_mana_count:
        failures.append(
            "HEALTH UP/MANA UP was selected without the expected HP/MP stat diff "
            f"({verified_health_or_mana_count}/{selected_health_or_mana_count} verified)"
        )

    summary = {
        "iterations": len(iterations),
        "bot_count": len(bot_ids - {-1}),
        "application_count": application_count,
        "changed_application_count": changed_application_count,
        "expected_native_noop_count": expected_noop_count,
        "stat_diff_count": stat_diff_count,
        "loadout_diff_count": loadout_diff_count,
        "health_or_mana_stat_diffs": verified_health_or_mana_count,
        "bonus_option_count": bonus_count,
        "unique_pool_counts": unique_pool_counts or {},
    }
    if failures:
        raise BotSkillChoiceRegressionFailure(json.dumps({"summary": summary, "failures": failures}, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--min-bots", type=int, default=1)
    parser.add_argument("--from-report", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()

    if args.iterations <= 0:
        raise BotSkillChoiceRegressionFailure("--iterations must be positive")
    if args.min_bots <= 0:
        raise BotSkillChoiceRegressionFailure("--min-bots must be positive")

    result: dict[str, Any] | None = None
    try:
        if args.from_report is not None:
            result = json.loads(args.from_report.read_text(encoding="utf-8"))
            if "stress_result" in result and isinstance(result["stress_result"], dict):
                result = result["stress_result"]
        else:
            result = stress.run_stress(args.iterations, args.seed)
            result["ok"] = True

        summary = validate_result(result, min_bots=args.min_bots, min_iterations=args.iterations)
        payload = {
            "ok": True,
            "summary": summary,
            "stress_result": result,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({"ok": True, "output": str(args.output), "summary": summary}, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        payload = {
            "ok": False,
            "error": str(exc),
            "stress_result": result,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1
    finally:
        if args.from_report is None and not args.keep_running:
            csp.stop_game()


if __name__ == "__main__":
    raise SystemExit(main())
