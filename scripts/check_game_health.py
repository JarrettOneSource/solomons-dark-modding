#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

def powershell_json(command: str) -> dict | list | None:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    if not text:
        return None
    return json.loads(text)


def get_process_snapshot() -> dict | None:
    command = (
        "Get-Process SolomonDark -ErrorAction SilentlyContinue | "
        "Select-Object Id,Responding,CPU,WS | ConvertTo-Json -Compress"
    )
    data = powershell_json(command)
    return data if isinstance(data, dict) else None


def capture_png(script_path: pathlib.Path, title: str, path: pathlib.Path) -> bool:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            (
                "py -3 "
                f"\"{script_path}\" "
                f"--title \"{title}\" --output \"{path}\" --method window"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and path.exists()


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if os.name != "nt":
        print("check_game_health.py must be run with Windows Python (for example: py -3 scripts/check_game_health.py).")
        return 2

    from capture_window import find_window

    parser = argparse.ArgumentParser(description="Check whether Solomon Dark looks healthy.")
    parser.add_argument("--title", default="SolomonDark")
    parser.add_argument("--interval-seconds", type=float, default=3.0)
    parser.add_argument("--expect-visual-change", action="store_true")
    parser.add_argument("--capture-dir", default="runtime/health")
    args = parser.parse_args()

    capture_dir = pathlib.Path(args.capture_dir)
    capture_dir.mkdir(parents=True, exist_ok=True)
    script_path = pathlib.Path(__file__).with_name("capture_window.py")

    window = find_window(args.title, None, None)
    process_before = get_process_snapshot()
    if process_before is None:
        print("unhealthy: SolomonDark process not found")
        return 2

    before_path = capture_dir / "before.png"
    after_path = capture_dir / "after.png"
    capture_png(script_path, window.title, before_path)
    before_hash = sha256_file(before_path) if before_path.exists() else ""

    time.sleep(max(0.1, args.interval_seconds))

    process_after = get_process_snapshot()
    if process_after is None:
        print("unhealthy: SolomonDark process disappeared")
        return 2

    capture_png(script_path, window.title, after_path)
    after_hash = sha256_file(after_path) if after_path.exists() else ""

    problems: list[str] = []
    if process_after.get("Responding") is False:
        problems.append("process not responding")
    if args.expect_visual_change and before_hash and after_hash and before_hash == after_hash:
        problems.append("window image unchanged during expected activity")

    summary = {
        "process_before": process_before,
        "process_after": process_after,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "problems": problems,
    }
    print(json.dumps(summary, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
