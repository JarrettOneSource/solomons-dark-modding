#!/usr/bin/env python3
"""Activate one visible Windows process-owned window."""

from __future__ import annotations

import argparse
import os
import sys

from capture_window import activate_window, find_window


def main() -> int:
    if os.name != "nt":
        print("activate_window.py must be run with Windows Python.", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--delay-ms", type=int, default=250)
    args = parser.parse_args()

    window = find_window(pid=args.pid)
    activate_window(window.hwnd, args.delay_ms)
    print(f"activated {window.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
