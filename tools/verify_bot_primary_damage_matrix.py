#!/usr/bin/env python3
"""Prove each stock elemental primary through authoritative HP edges."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cast_state_probe as csp
import run_bot_match as bot_match


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "tools/bot_match.example.json"
ELEMENTS = ("fire", "air", "water", "earth")


class PrimaryMatrixFailure(RuntimeError):
    """Raised when an elemental primary lacks an applied-damage edge."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def element_config_document(
    source: dict[str, Any],
    element: str,
) -> dict[str, Any]:
    if element not in ELEMENTS:
        raise PrimaryMatrixFailure(f"Unsupported matrix element: {element}")
    document = copy.deepcopy(source)
    document["player"]["element"] = element
    for row in document["bots"]:
        row["element"] = element
    document["match"]["fullTimeoutSeconds"] = 240
    document["match"]["stallTimeoutSeconds"] = 90
    document["match"]["monitorIntervalSeconds"] = 0.25
    return document


def validate_element_result(
    element: str,
    config: bot_match.BotMatchConfig,
    result: dict[str, Any],
) -> dict[str, Any]:
    expected_names = {
        config.player_name,
        *(fighter.name for fighter in config.bots),
    }
    fighters = result.get("damage", {}).get("fighters", {})
    if set(fighters) != expected_names:
        raise PrimaryMatrixFailure(
            f"{element} did not register the four expected fighters: "
            f"expected={sorted(expected_names)} actual={sorted(fighters)}"
        )
    missing = sorted(
        name
        for name, row in fighters.items()
        if int(row.get("damageDealtEdges", 0)) < 1
        or float(row.get("damageDealt", 0.0)) <= 0.0
    )
    if missing:
        raise PrimaryMatrixFailure(
            f"{element} lacked authoritative enemy-HP damage from "
            f"{missing}: {fighters}"
        )
    if (
        result.get("end", {}).get("reason")
        != "four_fighter_damage_matrix_satisfied"
    ):
        raise PrimaryMatrixFailure(
            f"{element} stopped before the matrix contract: "
            f"{result.get('end')}"
        )
    if (
        result.get("gateTransit", {}).get("stuckTeleports") != 0
        or result.get("solomonDig", {}).get("triggered") is not True
    ):
        raise PrimaryMatrixFailure(
            f"{element} did not preserve the physical gate and real "
            f"Solomon trigger contract: gate={result.get('gateTransit')} "
            f"trigger={result.get('solomonDig')}"
        )
    return {
        "element": element,
        "slot0": fighters[config.player_name],
        "synthetic": {
            fighter.name: fighters[fighter.name]
            for fighter in config.bots
        },
        "furthestWave": int(result.get("furthestWave", 0)),
        "enemyDamageEdges": int(
            result.get("damage", {}).get("enemyDamageEdges", 0)
        ),
        "gateStuckTeleports": 0,
        "realSolomonTrigger": True,
    }


def accepted_element_run(
    element: str,
    config: bot_match.BotMatchConfig,
    element_directory: Path,
) -> dict[str, Any] | None:
    for result_path in sorted(
        element_directory.glob("run-*/result.json"),
        reverse=True,
    ):
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if result.get("ok") is not True:
            continue
        row = validate_element_result(element, config, result)
        row["result"] = str(result_path)
        row["runIndex"] = int(result.get("runIndex", 0))
        row["reused"] = True
        return row
    return None


class PrimaryMatrixRun(bot_match.BotMatchRun):
    """Keep bot policy idle until the real Solomon route starts combat."""

    def start_testrun(self) -> dict[str, str]:
        result = super().start_testrun()
        quiesced = self.values(
            """
lua_bots_disable_tick = true
print("quiesced=" .. tostring(lua_bots_disable_tick))
"""
        )
        if quiesced.get("quiesced") != "true":
            raise bot_match.BotMatchFailure(
                f"Could not quiesce bot policy for physical routing: "
                f"{quiesced}"
            )
        return result

    def wait_for_real_trigger(self) -> dict[str, Any]:
        result = super().wait_for_real_trigger()
        resumed = self.values(
            """
lua_bots_disable_tick = false
print("resumed=" .. tostring(
  lua_bots_disable_tick == false))
"""
        )
        if resumed.get("resumed") != "true":
            raise bot_match.BotMatchFailure(
                f"Could not resume bot policy for retail combat: "
                f"{resumed}"
            )
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run four isolated retail-schedule matches and require an "
            "authoritative enemy-HP edge from slot 0 and every synthetic "
            "fighter for Fire, Air, Water, and Earth."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--batch-id",
        default="",
        help="Filename-safe evidence id; defaults to a UTC timestamp.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Reuse accepted element rows in an existing batch and run "
            "only missing or rejected rows."
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        batch_id = bot_match.safe_batch_id(
            args.batch_id
            or datetime.now(timezone.utc).strftime(
                "primary-matrix-%Y%m%dT%H%M%SZ"
            )
        )
        source_path = args.config.resolve()
        source = json.loads(source_path.read_text(encoding="utf-8"))
        base = bot_match.BotMatchConfig.load(source_path)
        batch_directory = base.evidence_root / "runs" / batch_id
        if batch_directory.exists() and not args.resume:
            raise PrimaryMatrixFailure(
                f"Matrix batch already exists: {batch_directory}"
            )
        batch_directory.mkdir(parents=True, exist_ok=args.resume)
        config_directory = batch_directory / "configs"
        config_directory.mkdir(exist_ok=args.resume)
        matrix_config_path = batch_directory / "matrix-config.json"
        if not matrix_config_path.exists():
            bot_match.atomic_write_json(
                matrix_config_path,
                {
                    "schemaVersion": 1,
                    "startedAt": utc_now(),
                    "elements": list(ELEMENTS),
                    "sourceConfig": str(source_path),
                    "sourceConfigSha256": bot_match.sha256_file(
                        source_path
                    ),
                    "gitHead": bot_match.run_checked(
                        ["git", "rev-parse", "HEAD"],
                        timeout=15,
                        cwd=ROOT,
                    ).strip(),
                },
            )

        rows: list[dict[str, Any]] = []
        for index, element in enumerate(ELEMENTS, start=1):
            document = element_config_document(source, element)
            config_path = config_directory / f"{element}.json"
            bot_match.atomic_write_json(config_path, document)
            config = bot_match.BotMatchConfig.load(config_path)
            element_directory = batch_directory / element
            if args.resume:
                accepted = accepted_element_run(
                    element,
                    config,
                    element_directory,
                )
                if accepted is not None:
                    rows.append(accepted)
                    print(json.dumps(accepted, sort_keys=True), flush=True)
                    continue
            existing_indices = [
                int(path.name.removeprefix("run-"))
                for path in element_directory.glob("run-*")
                if path.is_dir()
                and path.name.removeprefix("run-").isdigit()
            ]
            run_index = max(existing_indices, default=0) + 1
            instance = bot_match.instance_name(
                "matrix",
                run_index,
                f"{batch_id}-{element}",
            )
            runner = PrimaryMatrixRun(
                config,
                mode="matrix",
                run_index=run_index,
                batch_directory=element_directory,
                instance=instance,
            )
            result = runner.run()
            row = validate_element_result(element, config, result)
            row["result"] = str(runner.run_directory / "result.json")
            row["runIndex"] = run_index
            row["reused"] = False
            rows.append(row)
            print(json.dumps(row, sort_keys=True), flush=True)

        summary = {
            "schemaVersion": 1,
            "ok": len(rows) == len(ELEMENTS),
            "completedAt": utc_now(),
            "elements": rows,
        }
        summary_path = batch_directory / "summary.json"
        bot_match.atomic_write_json(summary_path, summary)
        print(
            json.dumps(
                {"ok": summary["ok"], "summary": str(summary_path)},
                sort_keys=True,
            )
        )
        return 0
    except (
        PrimaryMatrixFailure,
        bot_match.BotMatchFailure,
        OSError,
        ValueError,
        subprocess.SubprocessError,
        csp.ProbeFailure,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
