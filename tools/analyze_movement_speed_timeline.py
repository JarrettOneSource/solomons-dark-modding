#!/usr/bin/env python3
"""Derive fighter movement-speed proxies from multiplayer timeline evidence."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


LOG_EVENT_PATTERNS = (
    ("skill-choice", re.compile(r"random skill picker choice applied\..*chosen=(?P<skill>\d+)")),
    ("skill-choice", re.compile(r"host-self level-up choice resolved.*option_id=(?P<skill>\d+)")),
    ("skill-choice-native", re.compile(r"native skill choice phases\..*choice_id=(?P<skill>\d+)")),
    ("level-up", re.compile(r"level-up barrier started")),
    ("respawn", re.compile(r"captured Arena player respawn")),
    ("wave-boundary", re.compile(r"wave respawn applied")),
    ("death", re.compile(r"death presentation started")),
)
LOG_LINE = re.compile(r"^\[(?P<timestamp>[^]]+)] (?P<message>.*)$")
PENDING_MOVEMENT_FRAMES = re.compile(
    r"\[lua\]\[bot\.brain] takeover\.pending_movement_frames=(?P<frames>\d+)"
)
BOT_THINK_COUNT = re.compile(r"\[lua\]\[bot\.brain] brain\.think_count=(?P<count>\d+)")
SHARED_SIMULATION_HOLD = re.compile(
    r"Shared simulation control suppressing actor tick\..*local_player=1"
)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - index) + ordered[upper] * (index - lower)


def summarize(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "median": statistics.median(values) if values else None,
        "p90": percentile(values, 0.90),
        "maximum": max(values) if values else None,
        "mean": statistics.fmean(values) if values else None,
    }


def timeline_samples(path: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            row = json.loads(line)
            if row.get("event") is not None or "bot-play-endurance" not in str(row.get("phase", "")):
                continue
            if not all(
                isinstance(row.get(peer, {}).get("player"), dict)
                and row[peer]["player"].get("valid") is True
                for peer in ("host", "clientB")
            ):
                continue
            row["_line"] = line_number
            samples.append(row)
    return samples


def derive_segments(run: str, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for previous, current in zip(samples, samples[1:]):
        dt = (int(current["utcNanoseconds"]) - int(previous["utcNanoseconds"])) / 1e9
        if dt < 0.5 or dt > 3.5:
            continue
        wave = int(current["host"].get("world", {}).get("waveIndex", 0))
        for peer, fighter in (("host", "host"), ("clientB", "client")):
            before = previous[peer]["player"]
            after = current[peer]["player"]
            if int(before.get("address", 0)) != int(after.get("address", 0)):
                continue
            dx = float(after["x"]) - float(before["x"])
            dy = float(after["y"]) - float(before["y"])
            distance = math.hypot(dx, dy)
            # Arena teleports and respawns are not movement samples. The upper
            # bound is intentionally far above the recovered native envelope.
            if not math.isfinite(distance) or distance > 500.0:
                continue
            segments.append(
                {
                    "run": run,
                    "fighter": fighter,
                    "peer": peer,
                    "utcNanoseconds": int(current["utcNanoseconds"]),
                    "elapsedSeconds": float(current["elapsedSeconds"]),
                    "wave": wave,
                    "actorAddress": int(after.get("address", 0)),
                    "dtSeconds": dt,
                    "distance": distance,
                    "speed": distance / dt,
                    "moving": distance > 0.5,
                    "timelineLine": int(current["_line"]),
                }
            )
    return segments


def parse_log_events(peer: str, path: Path, timezone: ZoneInfo) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            match = LOG_LINE.match(line.rstrip())
            if match is None:
                continue
            message = match.group("message")
            for kind, pattern in LOG_EVENT_PATTERNS:
                event_match = pattern.search(message)
                if event_match is None:
                    continue
                timestamp = datetime.strptime(
                    match.group("timestamp"), "%Y-%m-%d %H:%M:%S.%f"
                ).replace(tzinfo=timezone)
                event: dict[str, Any] = {
                    "peer": peer,
                    "kind": kind,
                    "utcNanoseconds": int(timestamp.timestamp() * 1e9),
                    "line": line_number,
                    "message": message,
                }
                if "skill" in event_match.groupdict():
                    event["skillId"] = int(event_match.group("skill"))
                events.append(event)
                break
    return events


def parse_log_movement_backlog(
    run: str, peer: str, path: Path, timezone: ZoneInfo
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    samples: list[dict[str, Any]] = []
    holds: list[dict[str, Any]] = []
    latest_think_count: int | None = None
    with path.open(encoding="utf-8-sig", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            match = LOG_LINE.match(line.rstrip())
            if match is None:
                continue
            message = match.group("message")
            timestamp = datetime.strptime(
                match.group("timestamp"), "%Y-%m-%d %H:%M:%S.%f"
            ).replace(tzinfo=timezone)
            utc_nanoseconds = int(timestamp.timestamp() * 1e9)
            think_match = BOT_THINK_COUNT.search(message)
            if think_match is not None:
                latest_think_count = int(think_match.group("count"))
            pending_match = PENDING_MOVEMENT_FRAMES.search(message)
            if pending_match is not None:
                samples.append(
                    {
                        "run": run,
                        "peer": peer,
                        "utcNanoseconds": utc_nanoseconds,
                        "line": line_number,
                        "pendingMovementFrames": int(pending_match.group("frames")),
                        "latestThinkCount": latest_think_count,
                    }
                )
            if SHARED_SIMULATION_HOLD.search(message) is not None:
                holds.append(
                    {
                        "peer": peer,
                        "utcNanoseconds": utc_nanoseconds,
                        "line": line_number,
                        "message": message,
                    }
                )
    return samples, holds


def summarize_movement_backlog(
    samples: list[dict[str, Any]], holds: list[dict[str, Any]]
) -> dict[str, Any]:
    frames = [sample["pendingMovementFrames"] for sample in samples]
    maximum = max(samples, key=lambda sample: sample["pendingMovementFrames"]) if samples else None
    first_positive = next(
        (sample for sample in samples if sample["pendingMovementFrames"] > 0),
        None,
    )
    return {
        "sampleCount": len(samples),
        "sharedSimulationLocalHoldCount": len(holds),
        "maximumPendingMovementFrames": max(frames) if frames else None,
        "maximumSample": maximum,
        "firstPositiveSample": first_positive,
        "lastSample": samples[-1] if samples else None,
        "samplesAtOrAboveOneSecondAt60Hz": sum(value >= 60 for value in frames),
        "samplesAtOrAboveOneMinuteAt60Hz": sum(value >= 3600 for value in frames),
    }


def event_correlations(
    events: list[dict[str, Any]], segments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    correlations: list[dict[str, Any]] = []
    for event in events:
        item = dict(event)
        item["fighters"] = {}
        for fighter in ("host", "client"):
            before = [
                segment["speed"]
                for segment in segments
                if segment["fighter"] == fighter
                and segment["moving"]
                and event["utcNanoseconds"] - 20_000_000_000
                <= segment["utcNanoseconds"]
                < event["utcNanoseconds"]
            ]
            after = [
                segment["speed"]
                for segment in segments
                if segment["fighter"] == fighter
                and segment["moving"]
                and event["utcNanoseconds"]
                <= segment["utcNanoseconds"]
                <= event["utcNanoseconds"] + 20_000_000_000
            ]
            item["fighters"][fighter] = {
                "before20s": summarize(before),
                "after20s": summarize(after),
            }
        correlations.append(item)
    return correlations


def run_summary(segments: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for fighter in ("host", "client"):
        fighter_segments = [row for row in segments if row["fighter"] == fighter]
        moving = [row for row in fighter_segments if row["moving"]]
        result[fighter] = {
            "all": summarize([row["speed"] for row in fighter_segments]),
            "moving": summarize([row["speed"] for row in moving]),
            "maximumSegment": max(moving, key=lambda row: row["speed"]) if moving else None,
            "quarterMoving": [],
        }
        if fighter_segments:
            start = min(row["utcNanoseconds"] for row in fighter_segments)
            end = max(row["utcNanoseconds"] for row in fighter_segments)
            span = max(end - start, 1)
            for quarter in range(4):
                values = [
                    row["speed"]
                    for row in moving
                    if (
                        quarter
                        <= (row["utcNanoseconds"] - start) * 4 / span
                        < quarter + 1
                    )
                    or (quarter == 3 and row["utcNanoseconds"] == end)
                ]
                result[fighter]["quarterMoving"].append(summarize(values))
    return result


def parse_run(value: str) -> tuple[str, Path]:
    label, separator, raw_path = value.partition("=")
    if not separator or not label or not raw_path:
        raise argparse.ArgumentTypeError("run must be LABEL=TIMELINE_JSONL")
    return label, Path(raw_path)


def parse_log(value: str) -> tuple[str, str, Path]:
    run, first, remainder = value.partition(":")
    peer, second, raw_path = remainder.partition("=")
    if not first or not second or not run or not peer or not raw_path:
        raise argparse.ArgumentTypeError("log must be RUN:PEER=LOG_PATH")
    return run, peer, Path(raw_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", type=parse_run, required=True)
    parser.add_argument("--log", action="append", type=parse_log, default=[])
    parser.add_argument("--timezone", default="America/New_York")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-backlog-csv", type=Path)
    args = parser.parse_args()

    timezone = ZoneInfo(args.timezone)
    logs_by_run: dict[str, list[tuple[str, Path]]] = {}
    for run, peer, path in args.log:
        logs_by_run.setdefault(run, []).append((peer, path))

    report: dict[str, Any] = {"schemaVersion": 2, "runs": {}}
    all_segments: list[dict[str, Any]] = []
    all_backlog_samples: list[dict[str, Any]] = []
    for run, timeline in args.run:
        samples = timeline_samples(timeline)
        segments = derive_segments(run, samples)
        events = [
            event
            for peer, path in logs_by_run.get(run, [])
            for event in parse_log_events(peer, path, timezone)
        ]
        events.sort(key=lambda event: event["utcNanoseconds"])
        backlog_by_peer: dict[str, Any] = {}
        for peer, path in logs_by_run.get(run, []):
            backlog_samples, holds = parse_log_movement_backlog(
                run, peer, path, timezone
            )
            backlog_by_peer[peer] = summarize_movement_backlog(
                backlog_samples, holds
            )
            all_backlog_samples.extend(backlog_samples)
        report["runs"][run] = {
            "timeline": str(timeline),
            "sampleCount": len(samples),
            "segmentCount": len(segments),
            "summary": run_summary(segments),
            "events": event_correlations(events, segments),
            "movementInputBacklog": backlog_by_peer,
        }
        all_segments.extend(segments)

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(all_segments[0]) if all_segments else []
    with args.output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_segments)
    if args.output_backlog_csv is not None:
        args.output_backlog_csv.parent.mkdir(parents=True, exist_ok=True)
        backlog_fieldnames = list(all_backlog_samples[0]) if all_backlog_samples else []
        with args.output_backlog_csv.open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=backlog_fieldnames)
            writer.writeheader()
            writer.writerows(all_backlog_samples)
    print(json.dumps({"runs": list(report["runs"]), "segments": len(all_segments)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
