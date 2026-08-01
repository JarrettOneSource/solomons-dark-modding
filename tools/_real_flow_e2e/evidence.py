from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import ntpath
from pathlib import Path
import shutil
import threading
import time
from typing import Any

from .windows import (
    WindowsPeer,
    windows_path,
)


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
    host_pipe: Any | None = None,
    client_pipe: Any | None = None,
    event_writer: JsonlWriter | None = None,
) -> dict[str, Any]:
    output_directory.mkdir(parents=True, exist_ok=True)
    if host_pipe is None or client_pipe is None:
        raise EvidenceError(
            "coordinated in-game capture requires both Lua peers"
        )

    del source_root, host
    barrier_id = (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        + f"-{time.time_ns() % 1_000_000_000:09d}"
    )
    barrier_path = output_directory / f"{label}-{barrier_id}-barrier.json"
    host_output = output_directory / f"{label}-{barrier_id}-host.png"
    client_output = (
        output_directory / f"{label}-{barrier_id}-client-b.png"
    )
    host_raw = host_output.with_suffix(".bmp")
    client_raw = client_output.with_suffix(".bmp")
    for path in (barrier_path, host_output, client_output, host_raw, client_raw):
        if path.exists():
            raise EvidenceError(f"capture output must be new: {path}")

    remote_connection = getattr(client, "connection", None)
    remote_run_root = getattr(client, "run_root", None)
    remote_bridge = getattr(client_pipe, "bridge", None)
    remote_client = (
        remote_connection is not None
        and isinstance(remote_run_root, str)
        and remote_bridge is not None
    )
    if remote_client:
        client_capture_path = ntpath.join(
            remote_run_root,
            "captures",
            client_raw.name,
        )
    else:
        client_capture_path = windows_path(client_raw)
    host_capture_path = windows_path(host_raw)

    record: dict[str, Any] = {
        "schemaVersion": 1,
        "barrierId": barrier_id,
        "label": label,
        "pairingDefinition": (
            "conservative UTC skew between capture-file completion times "
            "produced by one replicated in-game event; remote UTC is "
            "aligned before the trigger and controller request/acknowledgement "
            "time is excluded"
        ),
        "maximumPairingIntervalNanoseconds": 1_000_000_000,
        "status": "preparing",
    }
    record_written = False

    def emit(event: str, **values: Any) -> None:
        if event_writer is not None:
            event_writer.append(
                {
                    "schemaVersion": 1,
                    "kind": "capture-barrier",
                    "event": event,
                    "barrierId": barrier_id,
                    "label": label,
                    "utcNanoseconds": time.time_ns(),
                    **values,
                }
            )

    def execute_observer(pipe: Any, code: str) -> dict[str, str]:
        response = pipe.execute(
            "-- sdmod-exec-target: tool.real_flow_e2e_observer\n" + code
        )
        return {
            key: value
            for line in response.splitlines()
            if "=" in line
            for key, value in (line.split("=", 1),)
        }

    def arm(pipe: Any, path: str) -> dict[str, str]:
        values = execute_observer(
            pipe,
            "local armed=__real_flow_e2e_capture_arm("
            + json.dumps(barrier_id)
            + ","
            + json.dumps(path)
            + ");print('armed='..tostring(armed));print('barrier_id='.."
            + json.dumps(barrier_id)
            + ")",
        )
        if values != {"armed": "true", "barrier_id": barrier_id}:
            raise EvidenceError(
                f"capture barrier arm returned invalid state: {values}"
            )
        return values

    status_code = r"""
local result = __real_flow_e2e_capture_result()
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
if type(result) ~= "table" then
  emit("status", "missing")
  return
end
for _, key in ipairs({
  "status",
  "barrier_id",
  "authority_participant_id",
  "stream_sequence",
  "trigger_tick_count",
  "trigger_monotonic_ms",
  "capture_monotonic_ms",
  "capture_frame_count",
  "capture_completed_monotonic_ms",
  "capture_completed_frame_count",
  "ok",
  "error",
}) do
  emit(key, result[key])
end
"""

    def wait_for_capture(pipe: Any) -> dict[str, Any]:
        deadline = time.monotonic() + 20.0
        last: dict[str, str] = {}
        while time.monotonic() < deadline:
            last = execute_observer(pipe, status_code)
            if (
                last.get("barrier_id") == barrier_id
                and last.get("status") in {"captured", "failed"}
            ):
                integer_keys = {
                    "authority_participant_id",
                    "stream_sequence",
                    "trigger_tick_count",
                    "trigger_monotonic_ms",
                    "capture_monotonic_ms",
                    "capture_frame_count",
                    "capture_completed_monotonic_ms",
                    "capture_completed_frame_count",
                }
                parsed: dict[str, Any] = dict(last)
                try:
                    parsed.update(
                        {key: int(last.get(key, "0")) for key in integer_keys}
                    )
                except ValueError as exc:
                    raise EvidenceError(
                        f"capture barrier returned malformed timing: {last}"
                    ) from exc
                parsed["ok"] = last.get("ok") == "true"
                return parsed
            time.sleep(0.05)
        raise EvidenceError(
            "coordinated in-game capture barrier failed to synchronize: "
            f"barrier={barrier_id} last={last}"
        )

    def convert_capture(raw: Path, output: Path) -> dict[str, Any]:
        if not raw.is_file() or raw.stat().st_size <= 0:
            raise EvidenceError(f"capture file is missing or empty: {raw}")
        from PIL import Image

        with Image.open(raw) as source:
            image = source.convert("RGB")
            colors = image.getcolors(maxcolors=image.width * image.height)
            unique_colors = (
                len(colors) if colors is not None else image.width * image.height
            )
            dominant_fraction = (
                max(count for count, _ in colors)
                / float(image.width * image.height)
                if colors
                else 0.0
            )
            if unique_colors < 1000 or dominant_fraction >= 0.85:
                raise EvidenceError(
                    f"backbuffer capture was blank or low-information: {raw}"
                )
            image.save(output)
            quality = {
                "width": image.width,
                "height": image.height,
                "uniqueColors": unique_colors,
                "dominantFraction": dominant_fraction,
            }
        raw_bytes = raw.stat().st_size
        raw.unlink()
        return {"rawBmpBytes": raw_bytes, "quality": quality}

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            armed = {
                "host": executor.submit(
                    arm,
                    host_pipe,
                    host_capture_path,
                ),
                "clientB": executor.submit(
                    arm,
                    client_pipe,
                    client_capture_path,
                ),
            }
            record["armed"] = {
                role: future.result() for role, future in armed.items()
            }

        if remote_client:
            clock_alignment = remote_bridge.clock_alignment(samples=5)
        else:
            clock_alignment = {
                "method": "shared-host-windows-utc",
                "selected": {
                    "remoteToControllerOffsetNanoseconds": 0,
                    "uncertaintyNanoseconds": 0,
                    "roundTripNanoseconds": 0,
                },
                "samples": [],
            }
        record["clockAlignment"] = clock_alignment
        record["status"] = "armed"
        emit("armed", clockAlignmentMethod=clock_alignment["method"])

        published_ns = time.time_ns()
        published = execute_observer(
            host_pipe,
            "local sequence=__real_flow_e2e_capture_publish("
            + json.dumps(barrier_id)
            + ");print('barrier_id='.."
            + json.dumps(barrier_id)
            + ");print('stream_sequence='..tostring(sequence))",
        )
        try:
            stream_sequence = int(published.get("stream_sequence", "0"))
        except ValueError as exc:
            raise EvidenceError(
                f"capture barrier publish returned invalid state: {published}"
            ) from exc
        if published.get("barrier_id") != barrier_id or stream_sequence <= 0:
            raise EvidenceError(
                f"capture barrier publish returned invalid state: {published}"
            )
        record["publishedUtcNanoseconds"] = published_ns
        record["streamSequence"] = stream_sequence
        record["status"] = "published"
        emit("published", streamSequence=stream_sequence)

        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = {
                "host": executor.submit(wait_for_capture, host_pipe),
                "clientB": executor.submit(wait_for_capture, client_pipe),
            }
            peers = {
                role: future.result() for role, future in pending.items()
            }
        record["peers"] = peers
        for role, peer in peers.items():
            if (
                peer["status"] != "captured"
                or peer["ok"] is not True
                or peer["stream_sequence"] != stream_sequence
                or peer["trigger_monotonic_ms"] <= 0
                or peer["capture_monotonic_ms"] <= 0
            ):
                raise EvidenceError(
                    "coordinated in-game capture barrier failed to "
                    f"synchronize: role={role} state={peer}"
                )
            local_lag_ms = abs(
                peer["capture_monotonic_ms"]
                - peer["trigger_monotonic_ms"]
            )
            peer["localTriggerToCaptureMilliseconds"] = local_lag_ms
            if local_lag_ms > 1000:
                raise EvidenceError(
                    "coordinated in-game capture barrier exceeded the local "
                    f"trigger bound: role={role} lag={local_lag_ms} ms"
                )

        host_stat = host_raw.stat()
        host_capture_utc_ns = host_stat.st_mtime_ns
        host_quality = convert_capture(host_raw, host_output)

        if remote_client:
            remote_info = remote_connection.file_info(client_capture_path)
            remote_capture_utc_ns = int(
                remote_info.get("lastWriteUtcNanoseconds", 0)
            )
            if (
                remote_info.get("exists") is not True
                or int(remote_info.get("size", 0)) <= 0
                or remote_capture_utc_ns <= 0
            ):
                raise EvidenceError(
                    "workstation20 barrier capture file is missing or invalid"
                )
            remote_connection.copy_file_from(client_capture_path, client_raw)
        else:
            if not client_raw.is_file():
                raise EvidenceError("client barrier capture file is missing")
            remote_capture_utc_ns = client_raw.stat().st_mtime_ns
        client_quality = convert_capture(client_raw, client_output)

        selected_clock = clock_alignment["selected"]
        adjusted_client_utc_ns = (
            remote_capture_utc_ns
            + int(selected_clock["remoteToControllerOffsetNanoseconds"])
        )
        estimated_skew_ns = abs(
            host_capture_utc_ns - adjusted_client_utc_ns
        )
        uncertainty_ns = int(selected_clock["uncertaintyNanoseconds"])
        pairing_interval_ns = estimated_skew_ns + uncertainty_ns
        captures = {
            "host": {
                "path": str(host_output),
                "captureUtcNanoseconds": host_capture_utc_ns,
                "captureFileUtcNanoseconds": host_capture_utc_ns,
                "captureMethod": "replicated-event-d3d9-backbuffer",
                "clockDomain": "host-windows-utc",
                "barrier": peers["host"],
                **host_quality,
            },
            "clientB": {
                "path": str(client_output),
                "captureUtcNanoseconds": adjusted_client_utc_ns,
                "captureFileUtcNanoseconds": remote_capture_utc_ns,
                "captureMethod": "replicated-event-d3d9-backbuffer",
                "clockDomain": (
                    "remote-windows-utc-aligned-to-controller"
                    if remote_client
                    else "host-windows-utc"
                ),
                "barrier": peers["clientB"],
                **client_quality,
            },
        }
        result = {
            "barrierId": barrier_id,
            "barrierUtcNanoseconds": published_ns,
            "barrierStreamSequence": stream_sequence,
            "pairingDefinition": record["pairingDefinition"],
            "captureSkewNanoseconds": estimated_skew_ns,
            "clockAlignmentUncertaintyNanoseconds": uncertainty_ns,
            "gameAnchoredPairingIntervalNanoseconds": pairing_interval_ns,
            "captureBoundSpanNanoseconds": pairing_interval_ns,
            "maximumPairingIntervalNanoseconds": 1_000_000_000,
            "clockAlignment": clock_alignment,
            "attempt": 1,
            "rejectedAttempts": [],
            "captures": captures,
        }
        record.update(result)
        record["status"] = (
            "accepted"
            if pairing_interval_ns <= 1_000_000_000
            else "rejected"
        )
        write_json(barrier_path, record)
        record_written = True
        emit(
            record["status"],
            streamSequence=stream_sequence,
            estimatedSkewNanoseconds=estimated_skew_ns,
            clockAlignmentUncertaintyNanoseconds=uncertainty_ns,
            gameAnchoredPairingIntervalNanoseconds=pairing_interval_ns,
            evidencePath=str(barrier_path),
            peers=peers,
        )
        if pairing_interval_ns > 1_000_000_000:
            raise EvidenceError(
                "coordinated in-game paired capture exceeded the 1000 ms "
                f"bound: interval={pairing_interval_ns / 1e6:.1f} ms "
                f"estimatedSkew={estimated_skew_ns / 1e6:.1f} ms "
                f"uncertainty={uncertainty_ns / 1e6:.1f} ms "
                f"barrier={barrier_id}"
            )
        return result
    except BaseException as exc:
        if not record_written:
            record["status"] = "failed"
            record["error"] = f"{type(exc).__name__}: {exc}"
            write_json(barrier_path, record)
        emit(
            "failed",
            error=f"{type(exc).__name__}: {exc}",
            evidencePath=str(barrier_path),
        )
        raise


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
        "launcherLog": peer.settings_root / "logs" / "launcher.log",
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
