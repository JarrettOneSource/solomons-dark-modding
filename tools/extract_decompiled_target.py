#!/usr/bin/env python3
"""Print one or more target blocks from headless-Ghidra decompile logs."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


TARGET_RE = re.compile(r"^=== TARGET: 0x(?P<address>[0-9A-Fa-f]{8}) ===$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, action="append", required=True)
    parser.add_argument("address", nargs="+", help="virtual address, with or without 0x")
    return parser.parse_args()


def normalize_address(value: str) -> str:
    return "%08X" % int(value, 0)


def main() -> int:
    args = parse_args()
    wanted = {normalize_address(value) for value in args.address}
    found: set[str] = set()

    for path in args.log:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        starts = [index for index, line in enumerate(lines) if TARGET_RE.match(line)]
        for position, start in enumerate(starts):
            match = TARGET_RE.match(lines[start])
            assert match is not None
            address = match.group("address").upper()
            if address not in wanted:
                continue
            end = starts[position + 1] if position + 1 < len(starts) else len(lines)
            block = lines[start:end]
            done_index = next(
                (
                    index
                    for index, line in enumerate(block)
                    if line.strip() == "=== DONE ==="
                ),
                None,
            )
            if done_index is not None:
                block = block[:done_index]
            print("\n".join(block).rstrip())
            print()
            found.add(address)

    missing = wanted - found
    if missing:
        raise SystemExit("targets not found: " + ", ".join("0x" + value for value in sorted(missing)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
