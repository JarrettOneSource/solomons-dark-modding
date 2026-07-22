#!/usr/bin/env python3
"""Verify that a connected WSL Steam client remains healthy for a timed interval."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTON_ROOT = (
    Path.home() / ".local/share/Steam/compatibilitytools.d/GE-Proton10-34"
)
PULSE_ABORT_SIGNATURE = "pa_stream_get_time()"


class VerifyFailure(RuntimeError):
    """Raised when the connected Steam pair stops satisfying the stability gate."""


def instance_root(instance: str) -> Path:
    return ROOT / "runtime/instances" / instance


def session_status_path(instance: str) -> Path:
    return instance_root(instance) / "stage/.sdmod/multiplayer-session-status.json"


def exact_game_processes(instance: str) -> list[int]:
    windows_target = f"runtime\\instances\\{instance}\\stage\\SolomonDark.exe".casefold()
    unix_target = f"runtime/instances/{instance}/stage/SolomonDark.exe".casefold()
    matches: list[int] = []
    for process_dir in Path("/proc").iterdir():
        if not process_dir.name.isdigit():
            continue
        try:
            if process_dir.joinpath("comm").read_text().strip() != "SolomonDark.exe":
                continue
            command = process_dir.joinpath("cmdline").read_bytes().replace(
                b"\x00", b" "
            ).decode("utf-8", "replace").casefold()
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        if windows_target in command or unix_target in command:
            matches.append(int(process_dir.name))
    return sorted(matches)


def process_start_ticks(pid: int) -> int:
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError as exc:
        raise VerifyFailure(f"client process {pid} disappeared") from exc
    end_of_name = stat_text.rfind(")")
    fields_after_name = stat_text[end_of_name + 2 :].split()
    if end_of_name < 0 or len(fields_after_name) <= 19:
        raise VerifyFailure(f"cannot read process identity for client pid {pid}")
    return int(fields_after_name[19])


def read_status(path: Path) -> tuple[dict[str, Any], int]:
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
        modified_ns = path.stat().st_mtime_ns
    except (OSError, ValueError) as exc:
        raise VerifyFailure(f"Steam session status is unavailable: {path}") from exc
    if not isinstance(status, dict):
        raise VerifyFailure(f"Steam session status is not an object: {path}")
    return status, modified_ns


def validate_pair_status(
    host: dict[str, Any],
    client: dict[str, Any],
    expected_peers: int,
) -> None:
    checks = (
        (host.get("enabled") is True, "host Steam transport is disabled"),
        (host.get("isHost") is True, "host status no longer identifies the host"),
        (host.get("phase") == "Connected", "host is not connected"),
        (client.get("enabled") is True, "client Steam transport is disabled"),
        (client.get("isHost") is False, "client status identifies itself as host"),
        (client.get("phase") == "Connected", "client is not connected"),
        (
            int(host.get("authenticatedPeerCount", -1)) == expected_peers,
            "host authenticated peer count changed",
        ),
        (
            int(client.get("authenticatedPeerCount", -1)) == expected_peers,
            "client authenticated peer count changed",
        ),
        (not host.get("errorText"), "host session reported an error"),
        (not client.get("errorText"), "client session reported an error"),
        (
            int(host.get("lobbyId", 0)) > 0
            and host.get("lobbyId") == client.get("lobbyId"),
            "host and client lobby IDs differ",
        ),
        (
            host.get("protocolVersion") == client.get("protocolVersion"),
            "host and client protocol versions differ",
        ),
        (
            host.get("manifestSha256") == client.get("manifestSha256"),
            "host and client build fingerprints differ",
        ),
    )
    for passed, message in checks:
        if not passed:
            raise VerifyFailure(message)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def proton_provenance(proton_root: Path) -> dict[str, Any]:
    version_path = proton_root / "version"
    winepulse_path = proton_root / "files/lib/wine/i386-unix/winepulse.so"
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise VerifyFailure(f"Proton version record is unavailable: {version_path}") from exc
    if not winepulse_path.is_file():
        raise VerifyFailure(f"Proton Wine PulseAudio driver is unavailable: {winepulse_path}")
    return {
        "root": str(proton_root),
        "version": version,
        "winepulse_path": str(winepulse_path),
        "winepulse_sha256": file_sha256(winepulse_path),
    }


def crash_artifact_state(instances: tuple[str, ...]) -> dict[str, tuple[int, int]]:
    artifacts: dict[str, tuple[int, int]] = {}
    for instance in instances:
        stage = instance_root(instance) / "stage"
        candidates: set[Path] = set()
        for pattern in ("**/*crash*", "**/SolomonDark.exe*.dmp"):
            candidates.update(stage.glob(pattern))
        for path in candidates:
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            artifacts[str(path.relative_to(ROOT))] = (stat.st_mtime_ns, stat.st_size)
    return artifacts


def console_tail(path: Path, offset: int) -> str:
    if not path.is_file():
        return ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            stream.seek(offset)
            return stream.read()
    except OSError as exc:
        raise VerifyFailure(f"cannot read WSL client console log: {path}") from exc


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-instance", required=True)
    parser.add_argument("--client-instance", required=True)
    parser.add_argument("--duration", type=float, default=180.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--max-status-age", type=float, default=5.0)
    parser.add_argument("--expected-peers", type=int, default=1)
    parser.add_argument("--proton-root", type=Path, default=DEFAULT_PROTON_ROOT)
    parser.add_argument("--console-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.duration <= 0 or args.poll_interval <= 0 or args.max_status_age <= 0:
        parser.error("duration, poll interval, and maximum status age must be positive")
    if args.expected_peers < 1:
        parser.error("expected peers must be positive")

    started_wall = time.time()
    started_monotonic = time.monotonic()
    console_offset = args.console_log.stat().st_size if args.console_log.is_file() else 0
    initial_crash_artifacts = crash_artifact_state(
        (args.host_instance, args.client_instance)
    )
    result: dict[str, Any] = {
        "schema_version": 1,
        "passed": False,
        "started_at_utc": utc_now(),
        "host_instance": args.host_instance,
        "client_instance": args.client_instance,
        "requested_duration_seconds": args.duration,
        "poll_interval_seconds": args.poll_interval,
        "console_log": str(args.console_log),
        "console_start_offset": console_offset,
        "platform": {
            "kernel": platform.release(),
            "pulse_server": os.environ.get("PULSE_SERVER", ""),
            "sdl_audio_driver": os.environ.get("SDL_AUDIODRIVER", ""),
        },
        "timeline": [],
        "new_crash_artifacts": [],
    }

    try:
        result["proton"] = proton_provenance(args.proton_root.resolve())
        pids = exact_game_processes(args.client_instance)
        if len(pids) != 1:
            raise VerifyFailure(
                f"expected one exact WSL client game process, found {len(pids)}"
            )
        client_pid = pids[0]
        start_ticks = process_start_ticks(client_pid)
        result["client_pid"] = client_pid
        result["process_start_ticks"] = start_ticks

        host_path = session_status_path(args.host_instance)
        client_path = session_status_path(args.client_instance)
        initial_host_mtime = host_path.stat().st_mtime_ns
        initial_client_mtime = client_path.stat().st_mtime_ns
        deadline = started_monotonic + args.duration

        while True:
            elapsed = time.monotonic() - started_monotonic
            current_pids = exact_game_processes(args.client_instance)
            if current_pids != [client_pid]:
                raise VerifyFailure(
                    f"WSL client process identity changed: expected {client_pid}, "
                    f"found {current_pids}"
                )
            if process_start_ticks(client_pid) != start_ticks:
                raise VerifyFailure("WSL client process was replaced during the gate")

            host_status, host_mtime = read_status(host_path)
            client_status, client_mtime = read_status(client_path)
            validate_pair_status(host_status, client_status, args.expected_peers)

            now_ns = time.time_ns()
            max_age_ns = int(args.max_status_age * 1_000_000_000)
            if now_ns - host_mtime > max_age_ns:
                raise VerifyFailure("host session status stopped advancing")
            if now_ns - client_mtime > max_age_ns:
                raise VerifyFailure("client session status stopped advancing")

            if PULSE_ABORT_SIGNATURE in console_tail(args.console_log, console_offset):
                raise VerifyFailure("GE-Proton PulseAudio pa_stream_get_time() abort recurred")

            current_crash_artifacts = crash_artifact_state(
                (args.host_instance, args.client_instance)
            )
            new_crash_artifacts = sorted(
                path
                for path, state in current_crash_artifacts.items()
                if initial_crash_artifacts.get(path) != state
            )
            result["new_crash_artifacts"] = new_crash_artifacts
            if new_crash_artifacts:
                raise VerifyFailure(
                    "new crash artifacts appeared: " + ", ".join(new_crash_artifacts)
                )

            result["timeline"].append(
                {
                    "elapsed_seconds": round(elapsed, 3),
                    "client_pid": client_pid,
                    "host_phase": host_status.get("phase"),
                    "client_phase": client_status.get("phase"),
                    "host_peers": host_status.get("authenticatedPeerCount"),
                    "client_peers": client_status.get("authenticatedPeerCount"),
                    "host_status_mtime_ns": host_mtime,
                    "client_status_mtime_ns": client_mtime,
                }
            )

            if time.monotonic() >= deadline:
                if host_mtime <= initial_host_mtime:
                    raise VerifyFailure("host session status did not advance during the gate")
                if client_mtime <= initial_client_mtime:
                    raise VerifyFailure("client session status did not advance during the gate")
                break
            time.sleep(min(args.poll_interval, max(0.0, deadline - time.monotonic())))

        result["passed"] = True
    except (OSError, ValueError, VerifyFailure) as exc:
        result["failure"] = str(exc)
    finally:
        result["finished_at_utc"] = utc_now()
        result["elapsed_seconds"] = round(time.time() - started_wall, 3)
        write_result(args.output, result)

    if not result["passed"]:
        print(f"FAIL: {result.get('failure', 'unknown failure')}", file=sys.stderr)
        print(f"Evidence: {args.output}", file=sys.stderr)
        return 1
    print(
        f"PASS: WSL Steam session remained stable for {result['elapsed_seconds']} seconds"
    )
    print(f"Evidence: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
