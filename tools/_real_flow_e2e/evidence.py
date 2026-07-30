from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import shutil
import threading
import time
from typing import Any

from .windows import WindowsPeer, capture_window as capture_local_window


class EvidenceError(RuntimeError):
    """An evidence artifact is missing, malformed, or ambiguous."""


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class JsonlWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=False)
        self._lock = threading.Lock()

    def append(self, value: dict[str, Any]) -> None:
        line = json.dumps(value, sort_keys=True, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
                handle.write("\n")


def paired_windows_capture(
    source_root: Path,
    host: WindowsPeer,
    client: WindowsPeer,
    output_directory: Path,
    *,
    label: str,
) -> dict[str, Any]:
    output_directory.mkdir(parents=True, exist_ok=True)
    barrier_id = (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        + f"-{time.time_ns() % 1_000_000_000:09d}"
    )
    barrier_ns = time.time_ns()

    def capture(peer: WindowsPeer, output: Path) -> dict[str, Any]:
        remote = getattr(peer, "capture_window", None)
        if callable(remote):
            return dict(remote(output))
        return capture_local_window(source_root, peer, output)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            "host": executor.submit(
                capture,
                host,
                output_directory / f"{label}-{barrier_id}-host.png",
            ),
            "clientB": executor.submit(
                capture,
                client,
                output_directory / f"{label}-{barrier_id}-client-b.png",
            ),
        }
        captures = {
            role: future.result()
            for role, future in futures.items()
        }
    skew_ns = abs(
        captures["host"]["captureUtcNanoseconds"]
        - captures["clientB"]["captureUtcNanoseconds"]
    )
    if skew_ns > 1_000_000_000:
        raise EvidenceError(
            f"paired window capture skew was {skew_ns / 1e6:.1f} ms"
        )
    return {
        "barrierId": barrier_id,
        "barrierUtcNanoseconds": barrier_ns,
        "captureSkewNanoseconds": skew_ns,
        "captures": captures,
    }


def rendered_enemy_assertion(
    state: dict[str, Any],
    capture_path: Path,
) -> dict[str, Any]:
    try:
        from PIL import Image, ImageStat
    except ImportError as exc:
        raise EvidenceError(
            "Pillow is required for the screenshot render assertion"
        ) from exc
    if not capture_path.is_file():
        raise EvidenceError(f"client screenshot is missing: {capture_path}")
    viewport = state["viewport"]
    width = int(viewport["width"])
    height = int(viewport["height"])
    bindings = {
        int(binding["network_id"]): binding
        for binding in state["enemyBindings"]
        if binding["matched"]
        and not binding["parked"]
        and not binding["removed"]
        and int(binding["address"]) != 0
    }
    native = {
        int(enemy["network_id"]): enemy
        for enemy in state["nativeEnemies"]
        if int(enemy["network_id"]) != 0 and not enemy["dead"]
    }
    candidates = [
        enemy
        for enemy in state["replicatedEnemies"]
        if int(enemy["network_id"]) in bindings
        and int(enemy["network_id"]) in native
        and not enemy["dead"]
    ]
    if not candidates:
        raise EvidenceError(
            "client screenshot has no replicated enemy with a matched "
            "native render actor"
        )
    camera = state.get("camera", {})
    projected_candidates: list[
        tuple[dict[str, Any], float, float, str]
    ] = []
    for enemy in candidates:
        network_id = int(enemy["network_id"])
        actor = native[network_id]
        if (
            camera.get("sceneAvailable") is True
            and all(
                key in camera
                for key in ("originX", "originY", "scale")
            )
            and all(key in actor for key in ("x", "y"))
        ):
            camera_scale = float(camera["scale"])
            screen_x = (
                float(actor["x"]) - float(camera["originX"])
            ) * camera_scale
            screen_y = (
                float(actor["y"]) - float(camera["originY"])
            ) * camera_scale
            if (
                camera_scale > 0
                and math.isfinite(screen_x)
                and math.isfinite(screen_y)
                and 0 <= screen_x < width
                and 0 <= screen_y < height
            ):
                projected_candidates.append(
                    (enemy, screen_x, screen_y, "native-camera")
                )
                continue
        if (
            enemy["screen_valid"]
            and 0 <= float(enemy["screen_x"]) < width
            and 0 <= float(enemy["screen_y"]) < height
        ):
            projected_candidates.append(
                (
                    enemy,
                    float(enemy["screen_x"]),
                    float(enemy["screen_y"]),
                    "replicated-state",
                )
            )
    with Image.open(capture_path) as image:
        rgb = image.convert("RGB")
        image_size = [rgb.width, rgb.height]
        scale_x = rgb.width / max(1, width)
        scale_y = rgb.height / max(1, height)
        rows: list[dict[str, Any]] = []
        for (
            enemy,
            screen_x,
            screen_y,
            projection_source,
        ) in projected_candidates:
            center_x = round(screen_x * scale_x)
            center_y = round(screen_y * scale_y)
            radius = max(
                8,
                min(48, round(24 * max(scale_x, scale_y))),
            )
            bounds = (
                max(0, center_x - radius),
                max(0, center_y - radius),
                min(rgb.width, center_x + radius + 1),
                min(rgb.height, center_y + radius + 1),
            )
            crop = rgb.crop(bounds)
            extrema = crop.getextrema()
            channel_ranges = [
                maximum - minimum
                for minimum, maximum in extrema
            ]
            standard_deviation = ImageStat.Stat(crop).stddev
            rows.append(
                {
                    "networkActorId": int(enemy["network_id"]),
                    "localActorAddress": int(
                        bindings[int(enemy["network_id"])]["address"]
                    ),
                    "projection": [
                        screen_x,
                        screen_y,
                    ],
                    "projectionSource": projection_source,
                    "cropBounds": list(bounds),
                    "channelRanges": channel_ranges,
                    "channelStandardDeviation": standard_deviation,
                    "visuallyNonUniform": (
                        max(channel_ranges) >= 12
                        and max(standard_deviation) >= 3.0
                    ),
                }
            )
        if not rows:
            world_bounds = (
                0,
                max(0, round(rgb.height * 0.03)),
                rgb.width,
                max(1, round(rgb.height * 0.85)),
            )
            crop = rgb.crop(world_bounds)
            extrema = crop.getextrema()
            channel_ranges = [
                maximum - minimum
                for minimum, maximum in extrema
            ]
            standard_deviation = ImageStat.Stat(crop).stddev
            rows.append(
                {
                    "networkActorIds": sorted(
                        int(enemy["network_id"])
                        for enemy in candidates
                    ),
                    "localActorAddresses": sorted(
                        int(bindings[int(enemy["network_id"])]["address"])
                        for enemy in candidates
                    ),
                    "cropBounds": list(world_bounds),
                    "channelRanges": channel_ranges,
                    "channelStandardDeviation": standard_deviation,
                    "worldVisuallyNonUniform": (
                        max(channel_ranges) >= 12
                        and max(standard_deviation) >= 3.0
                    ),
                    "visuallyNonUniform": False,
                    "projectionUnavailable": True,
                }
            )
    accepted = [row for row in rows if row["visuallyNonUniform"]]
    bar_candidates: list[dict[str, Any]] = []
    if not accepted:
        pixels = rgb.load()
        runs_by_row: list[list[tuple[int, int]]] = []
        for y in range(0, round(rgb.height * 0.85)):
            runs: list[tuple[int, int]] = []
            start: int | None = None
            for x in range(rgb.width):
                red, green, blue = pixels[x, y]
                selected = (
                    red >= 150
                    and red >= green + 60
                    and red >= blue + 40
                )
                if selected and start is None:
                    start = x
                if not selected and start is not None:
                    width = x - start
                    if 20 <= width <= 80:
                        runs.append((start, x - 1))
                    start = None
            if start is not None:
                width = rgb.width - start
                if 20 <= width <= 80:
                    runs.append((start, rgb.width - 1))
            runs_by_row.append(runs)
        for y, runs in enumerate(runs_by_row):
            for start, end in runs:
                height = 1
                for following_y in range(
                    y + 1,
                    min(y + 10, len(runs_by_row)),
                ):
                    matched = any(
                        abs(candidate_start - start) <= 2
                        and abs(candidate_end - end) <= 2
                        for candidate_start, candidate_end
                        in runs_by_row[following_y]
                    )
                    if not matched:
                        break
                    height += 1
                if height >= 3:
                    candidate = {
                        "bounds": [
                            start,
                            y,
                            end + 1,
                            y + height,
                        ],
                        "width": end - start + 1,
                        "height": height,
                        "signature": "enemy-health-bar",
                    }
                    if candidate not in bar_candidates:
                        bar_candidates.append(candidate)
        if bar_candidates:
            accepted.append(
                {
                    "networkActorIds": sorted(
                        int(enemy["network_id"])
                        for enemy in candidates
                    ),
                    "localActorAddresses": sorted(
                        int(bindings[int(enemy["network_id"])]["address"])
                        for enemy in candidates
                    ),
                    "visuallyNonUniform": True,
                    "projectionMismatch": True,
                    "enemyHealthBarCandidates": bar_candidates,
                }
            )
    if not accepted:
        raise EvidenceError(
            "matched on-screen client enemy crops were visually uniform: "
            + json.dumps(rows, sort_keys=True)
        )
    return {
        "capture": str(capture_path),
        "viewport": viewport,
        "imageSize": image_size,
        "candidates": rows,
        "accepted": accepted,
        "enemyHealthBarCandidates": bar_candidates,
    }


def copy_runtime_artifacts(
    peer: WindowsPeer,
    output_directory: Path,
) -> dict[str, Any]:
    destination = output_directory / peer.config.role
    destination.mkdir(parents=True, exist_ok=True)
    stage_root = peer.game_executable.parent
    candidates = {
        "networkTelemetry": peer.telemetry_path,
        "loaderLog": (
            stage_root
            / ".sdmod"
            / "logs"
            / "solomondarkmodloader.log"
        ),
        "crashLog": (
            stage_root
            / ".sdmod"
            / "logs"
            / "solomondarkmodloader.crash.log"
        ),
    }
    copied: dict[str, Any] = {}
    for label, source in candidates.items():
        if not source.is_file() or source.stat().st_size == 0:
            copied[label] = {
                "source": str(source),
                "copied": False,
                "size": source.stat().st_size if source.exists() else 0,
            }
            continue
        target = destination / source.name
        shutil.copy2(source, target)
        copied[label] = {
            "source": str(source),
            "path": str(target),
            "copied": True,
            "size": target.stat().st_size,
        }
    return copied


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvidenceError(
                    f"invalid JSONL at {path}:{line_number}: {exc}"
                ) from exc
            if isinstance(row, dict):
                rows.append(row)
    return rows


def packet_accounting(path: Path) -> dict[str, Any]:
    rows = read_jsonl(path)
    events = Counter(str(row.get("event", "")) for row in rows)
    by_event_kind: dict[str, Counter[int]] = defaultdict(Counter)
    bytes_by_event_kind: dict[str, Counter[int]] = defaultdict(Counter)
    rejected_by_kind: Counter[int] = Counter()
    steam_send_result_codes: Counter[int] = Counter()
    steam_send_attempts = 0
    steam_send_accepted = 0
    steam_route_samples = 0
    steam_route_connected_samples = 0
    steam_route_relay_samples = 0
    steam_route_queue_times: list[int] = []
    steam_route_max_pending_unreliable = 0
    steam_route_max_pending_reliable = 0
    steam_route_max_unacked_reliable = 0
    fragment_by_kind: dict[int, dict[str, int]] = defaultdict(
        lambda: {
            "fragments": 0,
            "accepted": 0,
            "rejected": 0,
            "assembliesComplete": 0,
            "logicalBytes": 0,
            "datagramBytes": 0,
        }
    )
    sequences: dict[str, dict[int, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        event = str(row.get("event", ""))
        if event == "steam_send_result":
            steam_send_attempts += 1
            steam_send_accepted += int(row.get("accepted") is True)
            steam_send_result_codes[int(row.get("result_code", 0))] += 1
        if event == "steam_route_status":
            steam_route_samples += 1
            steam_route_connected_samples += int(
                int(row.get("connection_state", 0)) == 3
            )
            steam_route_relay_samples += int(
                row.get("using_relay") is True
            )
            steam_route_queue_times.append(
                max(0, int(row.get("queue_time_microseconds", 0)))
            )
            steam_route_max_pending_unreliable = max(
                steam_route_max_pending_unreliable,
                int(row.get("pending_unreliable_bytes", 0)),
            )
            steam_route_max_pending_reliable = max(
                steam_route_max_pending_reliable,
                int(row.get("pending_reliable_bytes", 0)),
            )
            steam_route_max_unacked_reliable = max(
                steam_route_max_unacked_reliable,
                int(row.get("unacked_reliable_bytes", 0)),
            )
        if "kind" in row:
            kind = int(row["kind"])
            by_event_kind[event][kind] += 1
            bytes_by_event_kind[event][kind] += int(
                row.get("bytes", row.get("logical_bytes", 0))
            )
            if "sequence" in row:
                sequences[event][kind].append(int(row["sequence"]))
            if row.get("accepted") is False:
                rejected_by_kind[kind] += 1
            if event == "fragment_receive":
                entry = fragment_by_kind[kind]
                entry["fragments"] += 1
                entry[
                    "accepted" if row.get("accepted") else "rejected"
                ] += 1
                entry["assembliesComplete"] += int(
                    row.get("assembly_complete") is True
                )
                entry["logicalBytes"] += int(
                    row.get("logical_bytes", 0)
                )
                entry["datagramBytes"] += int(
                    row.get("datagram_bytes", 0)
                )

    def integer_map(counter: Counter[int]) -> dict[str, int]:
        return {
            str(key): value
            for key, value in sorted(counter.items())
        }

    sorted_route_queue_times = sorted(steam_route_queue_times)
    route_p95_index = (
        (len(sorted_route_queue_times) * 95 + 99) // 100 - 1
        if sorted_route_queue_times
        else 0
    )
    sequence_summary: dict[str, dict[str, Any]] = {}
    for event, kinds in sorted(sequences.items()):
        sequence_summary[event] = {}
        for kind, values in sorted(kinds.items()):
            unique = sorted(set(values))
            missing = sum(
                max(0, second - first - 1)
                for first, second in zip(unique, unique[1:])
                if second > first
            )
            sequence_summary[event][str(kind)] = {
                "count": len(values),
                "uniqueCount": len(unique),
                "first": unique[0] if unique else 0,
                "last": unique[-1] if unique else 0,
                "inferredMissingWithinKind": missing,
            }
    return {
        "path": str(path),
        "rowCount": len(rows),
        "events": dict(sorted(events.items())),
        "countByEventAndKind": {
            event: integer_map(counter)
            for event, counter in sorted(by_event_kind.items())
        },
        "bytesByEventAndKind": {
            event: integer_map(counter)
            for event, counter in sorted(bytes_by_event_kind.items())
        },
        "rejectedByKind": integer_map(rejected_by_kind),
        "steamSendResults": {
            "attempts": steam_send_attempts,
            "accepted": steam_send_accepted,
            "rejected": steam_send_attempts - steam_send_accepted,
            "resultCodes": integer_map(steam_send_result_codes),
        },
        "steamRouteStatus": {
            "samples": steam_route_samples,
            "connectedSamples": steam_route_connected_samples,
            "relaySamples": steam_route_relay_samples,
            "maximumQueueTimeMicroseconds": (
                max(sorted_route_queue_times)
                if sorted_route_queue_times
                else 0
            ),
            "p95QueueTimeMicroseconds": (
                sorted_route_queue_times[route_p95_index]
                if sorted_route_queue_times
                else 0
            ),
            "maximumPendingUnreliableBytes":
                steam_route_max_pending_unreliable,
            "maximumPendingReliableBytes":
                steam_route_max_pending_reliable,
            "maximumUnackedReliableBytes":
                steam_route_max_unacked_reliable,
        },
        "fragmentByKind": {
            str(kind): values
            for kind, values in sorted(fragment_by_kind.items())
        },
        "sequences": sequence_summary,
    }


def steam_transport_assertion(
    accounting: dict[str, Any],
    *,
    role: str,
) -> dict[str, Any]:
    send_results = accounting["steamSendResults"]
    route_status = accounting["steamRouteStatus"]
    if int(send_results["attempts"]) == 0:
        raise EvidenceError(
            f"{role} did not record any actual Steam API send attempts"
        )
    result_25_count = int(
        send_results["resultCodes"].get("25", 0)
    )
    if result_25_count != 0:
        raise EvidenceError(
            f"{role} hit Steam result-25 backpressure "
            f"{result_25_count} time(s)"
        )
    if int(route_status["samples"]) == 0 or int(
        route_status["connectedSamples"]
    ) == 0:
        raise EvidenceError(
            f"{role} did not record a connected Steam route sample"
        )
    return {
        "result25Count": result_25_count,
        "routeSamples": int(route_status["samples"]),
        "connectedRouteSamples": int(
            route_status["connectedSamples"]
        ),
        "relaySamples": int(route_status["relaySamples"]),
        "maximumQueueTimeMicroseconds": int(
            route_status["maximumQueueTimeMicroseconds"]
        ),
        "p95QueueTimeMicroseconds": int(
            route_status["p95QueueTimeMicroseconds"]
        ),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(
    evidence_root: Path,
    *,
    manifest_name: str = "evidence-sha256.txt",
) -> Path:
    manifest = evidence_root / manifest_name
    lines: list[str] = []
    for path in sorted(evidence_root.rglob("*")):
        if not path.is_file() or path == manifest:
            continue
        relative = path.relative_to(evidence_root).as_posix()
        lines.append(f"{sha256_file(path)}  {relative}")
    manifest.write_text(
        "\n".join(lines) + ("\n" if lines else ""),
        encoding="utf-8",
    )
    return manifest
