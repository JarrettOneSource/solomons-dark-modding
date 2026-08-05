#!/usr/bin/env python3
"""Run every tests/test_*.py module that does not need a real machine.

CI used to name test modules one workflow step at a time, so a module was
covered only if somebody remembered to write its step.  Fifty-four of the
eighty-four modules never had one.  This runner discovers the suite instead:
every tests/test_*.py file runs unless it is declared in
MACHINE_DEPENDENT_TESTS together with the reason it cannot run on a hosted
runner.  Adding a test file is now enough to put it in CI.
"""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"

# Modules that cannot run on a hosted Linux runner, with the measured reason.
# Each reason was established by running the module with process spawning
# blocked and reading what it tried to reach for.  Anything not listed here
# runs in CI; this dict is the only way to opt out, and the contract
# test_ci_runs_every_test_module_it_can guards it against quiet growth.
MACHINE_DEPENDENT_TESTS: dict[str, str] = {
    "test_bot_mana_reserve": "spawns the Lua interpreter at /usr/bin/lua",
    "test_bot_match_runner": "needs a staged Windows launcher under dist/launcher",
    "test_bot_play_for_me": "spawns the Lua interpreter at /usr/bin/lua",
    "test_bot_primary_damage_matrix": "needs a staged Windows launcher under dist/launcher",
    "test_ml_bot_policy": "spawns the Lua interpreter at /usr/bin/lua",
    "test_remote_latency_wave5_verifier": "shells out to wslpath; needs a WSL host",
    "test_staged_loader_build_flavor": "shells out to wslpath; needs a WSL host",
    "test_world_render_z_order_verifier": "shells out to wslpath; needs a WSL host",
}

# A broken glob must not read as "nothing to run"; a deleted suite must not
# pass silently.  Raise this when modules are added, the same way the static
# contract floors move.
DISCOVERY_FLOOR = 84

# Exclusions are a cost, not a knob.  Growing past this is a deliberate edit
# that has to be argued for in review.
MAX_MACHINE_DEPENDENT = 8


def discover() -> list[str]:
    """Every test module in tests/, checked for being a plausible suite."""
    discovered = sorted(path.stem for path in TESTS_DIR.glob("test_*.py"))
    if len(discovered) < DISCOVERY_FLOOR:
        raise SystemExit(
            f"discovered only {len(discovered)} test modules under {TESTS_DIR}; "
            f"floor is {DISCOVERY_FLOOR}"
        )
    stale = sorted(set(MACHINE_DEPENDENT_TESTS) - set(discovered))
    if stale:
        raise SystemExit(
            "MACHINE_DEPENDENT_TESTS names modules that do not exist: "
            + ", ".join(stale)
        )
    if len(MACHINE_DEPENDENT_TESTS) > MAX_MACHINE_DEPENDENT:
        raise SystemExit(
            f"{len(MACHINE_DEPENDENT_TESTS)} modules are excluded from CI; "
            f"the ceiling is {MAX_MACHINE_DEPENDENT}"
        )
    return discovered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the modules that would run, one per line, and exit.",
    )
    args = parser.parse_args()

    discovered = discover()
    selected = [name for name in discovered if name not in MACHINE_DEPENDENT_TESTS]

    if args.list:
        for name in selected:
            print(name)
        return 0

    sys.path.insert(0, str(ROOT))
    loader = unittest.TestLoader()
    runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=0)

    failed: list[str] = []
    total = 0
    for name in selected:
        try:
            suite = loader.loadTestsFromName(f"tests.{name}")
        except Exception as exc:  # noqa: BLE001 - a module that will not import is a failure.
            print(f"FAIL: {name}: could not load: {exc}", flush=True)
            failed.append(name)
            continue
        count = suite.countTestCases()
        result = runner.run(suite)
        total += count
        if result.wasSuccessful():
            print(f"PASS: {name}: {count} tests", flush=True)
        else:
            print(f"FAIL: {name}: {count} tests", flush=True)
            failed.append(name)

    excluded = len(MACHINE_DEPENDENT_TESTS)
    print(
        f"{len(selected) - len(failed)}/{len(selected)} modules passed "
        f"({total} tests); {excluded} excluded as machine-dependent"
    )
    for name in failed:
        print(f"  failed: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
