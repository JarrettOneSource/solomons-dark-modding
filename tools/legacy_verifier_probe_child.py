#!/usr/bin/env python3
"""Isolated audit-hook runner for one legacy verifier invocation."""

from __future__ import annotations

import argparse
import atexit
import contextlib
import hashlib
import io
import json
import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
BLOCKED_PROCESS_EVENTS = {
    "os.kill",
    "os.killpg",
    "os.posix_spawn",
    "os.posix_spawnp",
    "os.spawn",
    "os.system",
    "subprocess.Popen",
}


class ProcessSideEffectBlocked(RuntimeError):
    pass


def _exit_code(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry", required=True)
    parser.add_argument(
        "--mode",
        required=True,
        choices=("import", "help", "invalid"),
    )
    args = parser.parse_args()

    entry = (ROOT / args.entry).resolve()
    if not entry.is_relative_to(ROOT) or not entry.is_file():
        raise SystemExit(f"invalid verifier entry point: {args.entry}")

    events: list[dict[str, str]] = []

    def audit_hook(event: str, event_args: tuple[object, ...]) -> None:
        if event in BLOCKED_PROCESS_EVENTS or event.startswith("os.spawn"):
            events.append(
                {
                    "event": event,
                    "arguments": repr(event_args),
                }
            )
            raise ProcessSideEffectBlocked(
                f"blocked process operation during {args.mode}: {event}"
            )

    sys.addaudithook(audit_hook)
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))

    invocation = {
        "import": [str(entry)],
        "help": [str(entry), "--help"],
        "invalid": [
            str(entry),
            "--__legacy_process_safety_invalid_argument__",
        ],
    }[args.mode]
    sys.argv = invocation
    stdout = io.StringIO()
    stderr = io.StringIO()
    target_exit_code = 0
    exception = ""
    try:
        with (
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            runpy.run_path(
                str(entry),
                run_name=(
                    f"_legacy_probe_{entry.stem}"
                    if args.mode == "import"
                    else "__main__"
                ),
            )
    except SystemExit as exc:
        target_exit_code = _exit_code(exc.code)
    except BaseException as exc:  # noqa: BLE001 - probe records target faults.
        target_exit_code = 125
        exception = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            with (
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                atexit._run_exitfuncs()
        except BaseException as exc:  # noqa: BLE001 - record exit-hook faults.
            target_exit_code = 125
            exception = f"{type(exc).__name__}: {exc}"

    captured_stdout = stdout.getvalue()
    captured_stderr = stderr.getvalue()
    print(
        json.dumps(
            {
                "entry_point": args.entry,
                "mode": args.mode,
                "target_exit_code": target_exit_code,
                "process_events": events,
                "exception": exception,
                "stdout": captured_stdout,
                "stderr": captured_stderr,
                "stdout_sha256": hashlib.sha256(
                    captured_stdout.encode("utf-8")
                ).hexdigest(),
                "stderr_sha256": hashlib.sha256(
                    captured_stderr.encode("utf-8")
                ).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
