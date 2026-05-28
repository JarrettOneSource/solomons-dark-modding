#!/usr/bin/env python3
"""Run one Lua probe against multiple Solomon Dark clients and compare output."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLIENTS = (
    ("host", "SolomonDarkModLoader_LuaExec_local-mp-host"),
    ("client", "SolomonDarkModLoader_LuaExec_local-mp-client"),
)


def parse_client(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("client must be NAME=PIPE")
    name, pipe = value.split("=", 1)
    name = name.strip()
    pipe = pipe.strip()
    if not name or not pipe:
        raise argparse.ArgumentTypeError("client must be NAME=PIPE")
    return name, pipe


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_code(args: argparse.Namespace) -> str:
    code_parts: list[str] = []
    if args.file is not None:
        code_parts.append(args.file.read_text(encoding="utf-8"))
    if args.code:
        code_parts.append(args.code)
    if not code_parts:
        if sys.stdin.isatty():
            raise SystemExit("provide --code, --file, or Lua code on stdin")
        code_parts.append(sys.stdin.read())
    code = "\n".join(part for part in code_parts if part.strip())
    if not code.strip():
        raise SystemExit("Lua probe code is empty")
    return code


def run_lua_client(name: str, pipe: str, code: str, timeout: float) -> dict[str, object]:
    env = os.environ.copy()
    env["SDMOD_LUA_EXEC_PIPE_NAME"] = pipe
    started = time.monotonic()
    completed = subprocess.run(
        ["python3", "tools/lua-exec.py", code],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    stdout = completed.stdout
    stderr = completed.stderr
    return {
        "name": name,
        "pipe": pipe,
        "returncode": completed.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stdout": stdout,
        "stderr": stderr,
        "values": parse_key_values(stdout),
    }


def run_all(clients: list[tuple[str, str]], code: str, timeout: float) -> list[dict[str, object]]:
    processes: list[tuple[str, str, subprocess.Popen[str], float]] = []
    for name, pipe in clients:
        env = os.environ.copy()
        env["SDMOD_LUA_EXEC_PIPE_NAME"] = pipe
        process = subprocess.Popen(
            ["python3", "tools/lua-exec.py", code],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        processes.append((name, pipe, process, time.monotonic()))

    results: list[dict[str, object]] = []
    for name, pipe, process, started in processes:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            results.append(
                {
                    "name": name,
                    "pipe": pipe,
                    "returncode": -1,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "stdout": stdout,
                    "stderr": (stderr or "") + f"\nTimed out after {timeout:.1f}s",
                    "values": parse_key_values(stdout),
                }
            )
            continue

        results.append(
            {
                "name": name,
                "pipe": pipe,
                "returncode": process.returncode,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "stdout": stdout,
                "stderr": stderr,
                "values": parse_key_values(stdout),
            }
        )
    return results


def build_value_diff(results: list[dict[str, object]]) -> dict[str, dict[str, str]]:
    all_keys: set[str] = set()
    values_by_client: dict[str, dict[str, str]] = {}
    for result in results:
        client = str(result["name"])
        values = result.get("values")
        if not isinstance(values, dict):
            values = {}
        typed_values = {str(key): str(value) for key, value in values.items()}
        values_by_client[client] = typed_values
        all_keys.update(typed_values.keys())

    diff: dict[str, dict[str, str]] = {}
    for key in sorted(all_keys):
        row = {client: values.get(key, "") for client, values in values_by_client.items()}
        if len(set(row.values())) > 1:
            diff[key] = row
    return diff


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        action="append",
        type=parse_client,
        help="Lua exec endpoint as NAME=PIPE. Defaults to local multiplayer host/client.",
    )
    parser.add_argument("--code", help="Lua code to execute.")
    parser.add_argument("--file", type=Path, help="Lua file to execute.")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--json", action="store_true", help="Emit full structured JSON.")
    parser.add_argument("--no-parallel", action="store_true", help="Run clients serially.")
    args = parser.parse_args()

    clients = args.client or list(DEFAULT_CLIENTS)
    code = load_code(args)

    if args.no_parallel:
        results = [run_lua_client(name, pipe, code, args.timeout) for name, pipe in clients]
    else:
        results = run_all(clients, code, args.timeout)

    output = {
        "ok": all(result["returncode"] == 0 for result in results),
        "clients": results,
        "value_diff": build_value_diff(results),
    }
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        for result in results:
            print(f"== {result['name']} ({result['pipe']}) rc={result['returncode']} ==")
            stdout = str(result["stdout"]).rstrip()
            stderr = str(result["stderr"]).rstrip()
            if stdout:
                print(stdout)
            if stderr:
                print(stderr, file=sys.stderr)
        if output["value_diff"]:
            print("== value diff ==")
            for key, row in output["value_diff"].items():
                print(key + " " + " ".join(f"{client}={value}" for client, value in row.items()))

    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
