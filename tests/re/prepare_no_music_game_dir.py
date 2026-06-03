#!/usr/bin/env python3
"""Prepare a staged Solomon Dark game directory with startup music disabled.

This is a live-RE harness utility for machines where the stock BASS startup
music path crashes before Lua probes can drive the game. It does not patch the
binary or loader; it stages a normal game copy and empties the native
music/music.txt data list so the game skips startup music loading.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"
DEFAULT_INSTANCE = "live_no_music_source"


class PrepareNoMusicFailure(RuntimeError):
    pass


def run_command(args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def to_windows_path(path: Path) -> str:
    result = run_command(["wslpath", "-w", str(path)], timeout=10.0)
    if result.returncode != 0:
        raise PrepareNoMusicFailure(
            f"wslpath failed for {path}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout.strip()


def prepare(instance: str) -> dict[str, object]:
    if not LAUNCHER.exists():
        raise PrepareNoMusicFailure(f"Launcher is missing: {LAUNCHER}")

    stage = run_command([str(LAUNCHER), "stage", "--json", "--instance", instance], timeout=120.0)
    stage_output = stage.stdout.strip() or stage.stderr.strip()
    if stage.returncode != 0:
        raise PrepareNoMusicFailure(
            f"launcher stage failed with exit code {stage.returncode}\n{stage_output}"
        )

    try:
        stage_payload = json.loads(stage_output)
    except json.JSONDecodeError as exc:
        raise PrepareNoMusicFailure(f"launcher stage did not return JSON: {exc}\n{stage_output[:1000]}") from exc

    stage_root = ROOT / "runtime" / "instances" / instance / "stage"
    music_list = stage_root / "music" / "music.txt"
    if not music_list.exists():
        raise PrepareNoMusicFailure(f"music list is missing after staging: {music_list}")

    music_list.write_text("", encoding="utf-8")

    return {
        "success": True,
        "instance": instance,
        "game_dir": str(stage_root),
        "game_dir_windows": to_windows_path(stage_root),
        "music_list": str(music_list),
        "stage_success": bool(stage_payload.get("success")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", default=DEFAULT_INSTANCE)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        result = prepare(args.instance)
    except Exception as exc:
        if args.json:
            print(json.dumps({"success": False, "error": str(exc)}, indent=2))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["game_dir"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
