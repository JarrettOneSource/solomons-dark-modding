#!/usr/bin/env python3
"""Run all static reverse-engineering and multiplayer contracts."""

from __future__ import annotations

import argparse
import json
import sys

from static_re_contract_support import TestResult
from static_re_test_registry import TESTS

def run_tests() -> list[TestResult]:
    results: list[TestResult] = []
    for name, test in TESTS:
        try:
            detail = test()
            results.append(TestResult(name=name, passed=True, detail=detail))
        except Exception as exc:  # noqa: BLE001 - test runner reports all failures uniformly.
            results.append(TestResult(name=name, passed=False, detail=str(exc)))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit structured JSON instead of text.")
    args = parser.parse_args()

    results = run_tests()
    failed = [result for result in results if not result.passed]
    if args.json:
        print(json.dumps([result.__dict__ for result in results], indent=2))
    else:
        for result in results:
            marker = "PASS" if result.passed else "FAIL"
            print(f"{marker}: {result.name}: {result.detail}")
        print(f"{len(results) - len(failed)}/{len(results)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
