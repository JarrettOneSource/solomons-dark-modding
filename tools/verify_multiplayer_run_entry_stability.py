#!/usr/bin/env python3
"""Run repeated shared Boneyard entries and reject every access violation."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import verify_run_static_layout_sync as layout_sync


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "runtime" / "run_entry_stability_verification.json"
DEFAULT_LAYOUT_OUTPUT = (
    ROOT / "runtime" / "run_entry_stability" / "layout_result.json"
)
DEFAULT_EVIDENCE_DIR = (
    ROOT / "runtime" / "run_entry_stability" / "screenshots"
)

ACCESS_VIOLATION_PATTERNS = (
    re.compile(
        r"first-chance exception.*code=0xC0000005",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"testrun region switch raised.*exception_code=0xC0000005",
        flags=re.IGNORECASE,
    ),
    re.compile(r"\bIP_IN_FREE_BLOCK\b", flags=re.IGNORECASE),
)


class StabilityFailure(RuntimeError):
    """Raised when repeated run entry is incomplete or unsafe."""


def local_path(path_text: str) -> Path:
    if re.match(r"^[A-Za-z]:[\\/]", path_text):
        completed = subprocess.run(
            ["wslpath", "-u", path_text],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5.0,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise StabilityFailure(
                f"could not translate Windows log path {path_text!r}: {detail}"
            )
        return Path(completed.stdout.strip())
    return Path(path_text)


def access_violation_lines(log_text: str) -> list[str]:
    matches: list[str] = []
    for line in log_text.splitlines():
        if any(pattern.search(line) for pattern in ACCESS_VIOLATION_PATTERNS):
            matches.append(line)
    return matches


def validate_layout_result(
    result: dict[str, Any],
    expected_runs: int,
) -> dict[str, Any]:
    runs = result.get("runs")
    if not isinstance(runs, list) or len(runs) != expected_runs:
        raise StabilityFailure(
            f"layout verifier completed {len(runs) if isinstance(runs, list) else 0}"
            f"/{expected_runs} runs"
        )

    run_summaries: list[dict[str, Any]] = []
    for expected_index, run in enumerate(runs, start=1):
        if not isinstance(run, dict):
            raise StabilityFailure(
                f"run {expected_index} result is not an object"
            )
        if run.get("run_index") != expected_index:
            raise StabilityFailure(
                f"run index mismatch: expected {expected_index}, "
                f"got {run.get('run_index')!r}"
            )
        if run.get("ok") is not True:
            raise StabilityFailure(f"run {expected_index} did not complete")
        host_entry = run.get("host_run_entry")
        if not isinstance(host_entry, dict) or host_entry.get(
            "host_started"
        ) is not True or host_entry.get("client_followed_host") is not True:
            raise StabilityFailure(
                f"run {expected_index} did not complete host/client entry"
            )
        cleanup = run.get("cleanup")
        if not isinstance(cleanup, dict) or cleanup.get(
            "exact_pid_path_cleanup"
        ) is not True:
            raise StabilityFailure(
                f"run {expected_index} lacks exact-PID cleanup proof"
            )

        launch = run.get("launch")
        if not isinstance(launch, dict):
            raise StabilityFailure(f"run {expected_index} lacks launch data")
        peer_logs: dict[str, str] = {}
        for role, key in (("host", "hostLog"), ("client", "clientLog")):
            raw_path = str(launch.get(key) or "")
            if not raw_path:
                raise StabilityFailure(
                    f"run {expected_index} lacks its {role} log path"
                )
            log_path = local_path(raw_path)
            try:
                log_text = log_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                raise StabilityFailure(
                    f"could not read run {expected_index} {role} log "
                    f"{log_path}: {exc}"
                ) from exc
            violations = access_violation_lines(log_text)
            if violations:
                raise StabilityFailure(
                    f"run {expected_index} {role} logged an access violation: "
                    f"{violations[0]}"
                )
            peer_logs[role] = str(log_path)

        run_summaries.append(
            {
                "run_index": expected_index,
                "host_client_entry": True,
                "access_violation_count": 0,
                "exact_pid_path_cleanup": True,
                "logs": peer_logs,
            }
        )

    if result.get("ok") is not True:
        raise StabilityFailure(
            f"layout verifier failed after completed runs: "
            f"{result.get('error')!r}"
        )
    return {
        "runs_completed": len(run_summaries),
        "peer_entries_completed": len(run_summaries) * 2,
        "access_violation_count": 0,
        "runs": run_summaries,
    }


def cleanup_interrupted_runs(layout_output: Path) -> list[dict[str, Any]]:
    if not layout_output.is_file():
        return []
    try:
        result = json.loads(layout_output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    cleanup_results: list[dict[str, Any]] = []
    runs = result.get("runs") if isinstance(result, dict) else None
    if not isinstance(runs, list):
        return cleanup_results
    for run in runs:
        if not isinstance(run, dict):
            continue
        cleanup = run.get("cleanup")
        if isinstance(cleanup, dict) and cleanup.get(
            "exact_pid_path_cleanup"
        ) is True:
            continue
        identities = run.get("owned_processes")
        if not isinstance(identities, list) or not identities:
            launch = run.get("launch")
            run_index = run.get("run_index")
            base_prefix = result.get("instance_prefix")
            if (
                not isinstance(launch, dict)
                or not isinstance(run_index, int)
                or not isinstance(base_prefix, str)
            ):
                continue
            try:
                identities = layout_sync.expected_owned_process_identities(
                    launch,
                    f"{base_prefix}-run{run_index:02d}",
                )
            except Exception:
                continue
        if not isinstance(identities, list) or not identities:
            continue
        cleanup_results.append(layout_sync.stop_owned_processes(identities))
    return cleanup_results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument(
        "--instance-prefix",
        default="run-entry-stability",
    )
    parser.add_argument("--game-directory", type=Path)
    parser.add_argument("--exact-mod-id", default="sample.lua.camera_lab")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--layout-output",
        type=Path,
        default=DEFAULT_LAYOUT_OUTPUT,
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=DEFAULT_EVIDENCE_DIR,
    )
    parser.add_argument("--layout-timeout", type=float, default=45.0)
    parser.add_argument(
        "--total-timeout",
        type=float,
        help="Hard timeout for the complete child verifier.",
    )
    args = parser.parse_args()
    if args.runs < 5 or args.runs > 10:
        parser.error("--runs must be between 5 and 10")
    if args.layout_timeout <= 0:
        parser.error("--layout-timeout must be positive")
    if args.total_timeout is not None and args.total_timeout <= 0:
        parser.error("--total-timeout must be positive")
    return args


def persist(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    output_path = args.output.resolve()
    layout_output = args.layout_output.resolve()
    evidence_dir = args.evidence_dir.resolve()
    total_timeout = args.total_timeout or (
        args.runs * (args.layout_timeout + 180.0)
    )
    result: dict[str, Any] = {
        "ok": False,
        "runs_requested": args.runs,
        "instance_prefix": args.instance_prefix,
        "transport": "loopback_udp",
        "layout_output": str(layout_output),
        "hard_timeout_seconds": total_timeout,
    }
    persist(output_path, result)

    command = [
        sys.executable,
        str(ROOT / "tools" / "verify_run_static_layout_sync.py"),
        "--runs",
        str(args.runs),
        "--instance-prefix",
        args.instance_prefix,
        "--exact-mod-id",
        args.exact_mod_id,
        "--output",
        str(layout_output),
        "--evidence-dir",
        str(evidence_dir),
        "--layout-timeout",
        str(args.layout_timeout),
    ]
    if args.game_directory is not None:
        command.extend(
            ["--game-directory", str(args.game_directory.resolve())]
        )

    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=total_timeout,
            check=False,
        )
        result["layout_verifier_exit_code"] = completed.returncode
        result["layout_verifier_output"] = completed.stdout[-12000:]
        if not layout_output.is_file():
            raise StabilityFailure(
                "layout verifier did not write its result"
            )
        layout_result = json.loads(
            layout_output.read_text(encoding="utf-8")
        )
        result["stability"] = validate_layout_result(
            layout_result,
            args.runs,
        )
        if completed.returncode != 0:
            raise StabilityFailure(
                f"layout verifier exited {completed.returncode}"
            )
        result["ok"] = True
    except subprocess.TimeoutExpired as exc:
        result["timeout"] = True
        result["cleanup"] = cleanup_interrupted_runs(layout_output)
        result["error"] = (
            f"layout verifier exceeded hard timeout {total_timeout:.1f}s"
        )
        if exc.stdout:
            output = (
                exc.stdout.decode(errors="replace")
                if isinstance(exc.stdout, bytes)
                else exc.stdout
            )
            result["layout_verifier_output"] = output[-12000:]
    except Exception as exc:
        result["error"] = str(exc)

    persist(output_path, result)
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "output": str(output_path),
                "layout_output": str(layout_output),
                "runs": (
                    result.get("stability", {}).get("runs_completed", 0)
                ),
                "error": result.get("error"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
