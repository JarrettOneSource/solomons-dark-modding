#!/usr/bin/env python3
"""Prove benign legacy-verifier paths perform no process operations."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from legacy_verifier_inventory import AUDITED_LEGACY_VERIFIERS


ROOT = Path(__file__).resolve().parents[1]
CHILD = ROOT / "tools" / "legacy_verifier_probe_child.py"
MODES = ("import", "help", "invalid")


class ProbeFailure(RuntimeError):
    pass


def _trace_verdict(trace: str) -> dict[str, Any]:
    lines = [line for line in trace.splitlines() if line.strip()]
    exec_lines = [line for line in lines if "execve(" in line]
    signal_lines = [
        line
        for line in lines
        if any(token in line for token in ("kill(", "killpg(", "tgkill(", "tkill("))
    ]
    return {
        "execve_count": len(exec_lines),
        "signal_operation_count": len(signal_lines),
        "unexpected_execve": exec_lines[1:],
        "signal_operations": signal_lines,
        "ok": len(exec_lines) == 1 and not signal_lines,
    }


def probe_entry(
    entry_point: str,
    mode: str,
    *,
    trace_path: Path | None = None,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"unsupported probe mode: {mode}")
    child_command = [
        sys.executable,
        str(CHILD),
        "--entry",
        entry_point,
        "--mode",
        mode,
    ]
    command = child_command
    if trace_path is not None:
        strace = shutil.which("strace")
        if strace is None:
            raise ProbeFailure("strace is required for traced evidence")
        command = [
            strace,
            "-f",
            "-qq",
            "-e",
            "trace=execve,kill,tgkill,tkill",
            "-o",
            str(trace_path),
            *child_command,
        ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=45.0,
        check=False,
    )
    if completed.returncode != 0:
        raise ProbeFailure(
            f"probe child failed for {entry_point} {mode}: "
            f"rc={completed.returncode} stderr={completed.stderr!r}"
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeFailure(
            f"probe child returned invalid JSON for {entry_point} {mode}: "
            f"{completed.stdout!r}"
        ) from exc
    expected_exit_code = {
        "import": 0,
        "help": 0,
        "invalid": 2,
    }[mode]
    result["expected_exit_code"] = expected_exit_code
    result["audit_hook_ok"] = (
        result.get("target_exit_code") == expected_exit_code
        and not result.get("process_events")
        and not result.get("exception")
    )
    if trace_path is not None:
        trace = trace_path.read_text(encoding="utf-8", errors="replace")
        result["syscall_trace"] = _trace_verdict(trace)
    result["ok"] = bool(
        result["audit_hook_ok"]
        and (
            trace_path is None
            or result.get("syscall_trace", {}).get("ok")
        )
    )
    return result


def run_all(
    *,
    output_directory: Path | None = None,
    trace: bool = False,
) -> dict[str, Any]:
    if trace and output_directory is None:
        raise ValueError("traced probes require an output directory")
    if output_directory is not None:
        output_directory.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for entry_point in AUDITED_LEGACY_VERIFIERS:
        slug = Path(entry_point).stem
        for mode in MODES:
            trace_path = (
                output_directory / "traces" / slug / f"{mode}.strace"
                if trace and output_directory is not None
                else None
            )
            if trace_path is not None:
                trace_path.parent.mkdir(parents=True, exist_ok=True)
            result = probe_entry(
                entry_point,
                mode,
                trace_path=trace_path,
            )
            records.append(result)
            if output_directory is not None:
                record_path = (
                    output_directory / "records" / slug / f"{mode}.json"
                )
                record_path.parent.mkdir(parents=True, exist_ok=True)
                record_path.write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

    failures = [
        {
            "entry_point": record["entry_point"],
            "mode": record["mode"],
        }
        for record in records
        if not record["ok"]
    ]
    summary = {
        "ok": not failures,
        "process_probe": "sys.addaudithook",
        "syscall_trace_enabled": trace,
        "entry_point_count": len(AUDITED_LEGACY_VERIFIERS),
        "mode_count": len(MODES),
        "probe_count": len(records),
        "process_event_count": sum(
            len(record.get("process_events", []))
            for record in records
        ),
        "unexpected_execve_count": (
            sum(
                len(
                    record.get("syscall_trace", {}).get(
                        "unexpected_execve",
                        [],
                    )
                )
                for record in records
            )
            if trace
            else None
        ),
        "signal_operation_count": (
            sum(
                int(
                    record.get("syscall_trace", {}).get(
                        "signal_operation_count",
                        0,
                    )
                )
                for record in records
            )
            if trace
            else None
        ),
        "failures": failures,
        "records": records,
    }
    if output_directory is not None:
        (output_directory / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args()

    summary = run_all(
        output_directory=args.output_dir,
        trace=args.trace,
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in summary.items()
                if key != "records"
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
