#!/usr/bin/env python3
"""Verify whether stock hub Students stay deterministic across two local clients."""

from __future__ import annotations

import argparse
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_OUTPUT = ROOT / "runtime" / "hub_student_seed_viability.json"
HOST_PIPE = "SolomonDarkModLoader_LuaExec_local-mp-host"
CLIENT_PIPE = "SolomonDarkModLoader_LuaExec_local-mp-client"


class VerifyFailure(RuntimeError):
    pass


def stop_games() -> None:
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-Process SolomonDark* -ErrorAction SilentlyContinue | Stop-Process -Force",
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def run_command(args: list[str], timeout: float) -> str:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(
            f"command failed ({completed.returncode}): {' '.join(args)}\n{completed.stdout}"
        )
    return completed.stdout


def extract_json_object(text: str) -> dict[str, object]:
    start = text.find("{")
    if start < 0:
        raise VerifyFailure(f"command did not emit JSON:\n{text}")
    decoder = json.JSONDecoder()
    value, _ = decoder.raw_decode(text[start:])
    if not isinstance(value, dict):
        raise VerifyFailure(f"expected JSON object, got {type(value).__name__}")
    return value


def launch_isolated_pair(preset: str, timeout: float) -> dict[str, object]:
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "scripts/Launch-LocalMultiplayerPair.ps1",
        "-Preset",
        preset,
        "-DisableMultiplayerTransport",
        "-HostName",
        "Seed Host",
        "-ClientName",
        "Seed Client",
    ]
    process = subprocess.Popen(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    assert process.stdout is not None

    def terminate_launcher() -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()

    def run_pipe(pipe_name: str, code: str, command_timeout: float = 2.0) -> str:
        env = os.environ.copy()
        env["SDMOD_LUA_EXEC_PIPE_NAME"] = pipe_name
        try:
            completed = subprocess.run(
                ["python3", "tools/lua-exec.py", code],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=command_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ""
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip()

    def query_scene(pipe_name: str) -> str:
        return run_pipe(
            pipe_name,
            "local s=sd.world.get_scene(); return tostring(s and (s.name or s.kind) or '')",
        )

    def request_hub(pipe_name: str) -> None:
        run_pipe(
            pipe_name,
            "local s=sd.world.get_scene(); "
            "if s and (s.name or s.kind) ~= 'hub' then print('ok='..tostring(sd.debug.switch_region(0))) end",
            command_timeout=4.0,
        )

    deadline = time.monotonic() + timeout
    buffer = ""
    last_probe = 0.0
    last_switch: dict[str, float] = {}
    last_scenes: dict[str, str] = {}
    while time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], 0.1)
        if ready:
            line = process.stdout.readline()
            if line:
                buffer += line
                parsed = None
                try:
                    parsed = extract_json_object(buffer)
                except VerifyFailure:
                    parsed = None
                if parsed is not None:
                    terminate_launcher()
                    return parsed
            elif process.poll() is not None:
                break

        now = time.monotonic()
        if now - last_probe >= 1.0:
            last_probe = now
            last_scenes = {
                "host": query_scene(HOST_PIPE),
                "client": query_scene(CLIENT_PIPE),
            }
            if last_scenes.get("host") == "hub" and last_scenes.get("client") == "hub":
                terminate_launcher()
                return {
                    "fallbackReady": True,
                    "preset": preset,
                    "hostLuaPipe": HOST_PIPE,
                    "clientLuaPipe": CLIENT_PIPE,
                    "scenes": last_scenes,
                }
            for name, pipe_name in (("host", HOST_PIPE), ("client", CLIENT_PIPE)):
                scene = last_scenes.get(name, "")
                if scene and scene not in {"hub", "transition"} and now - last_switch.get(name, 0.0) >= 5.0:
                    last_switch[name] = now
                    request_hub(pipe_name)

        if process.poll() is not None:
            remainder = process.stdout.read()
            if remainder:
                buffer += remainder
            if last_scenes.get("host") == "hub" and last_scenes.get("client") == "hub":
                return {
                    "fallbackReady": True,
                    "preset": preset,
                    "hostLuaPipe": HOST_PIPE,
                    "clientLuaPipe": CLIENT_PIPE,
                    "scenes": last_scenes,
                }
            raise VerifyFailure(
                f"pair launcher exited ({process.returncode}) before both clients reached hub. "
                f"last_scenes={last_scenes}\n{buffer}"
            )

    terminate_launcher()
    raise VerifyFailure(f"timed out waiting for isolated pair hub scenes. last_scenes={last_scenes}\n{buffer}")


def disable_bots() -> dict[str, str]:
    code = "lua_bots_disable_tick = true; sd.bots.clear(); return tostring(sd.bots.get_count())"
    env_host = os.environ.copy()
    env_host["SDMOD_LUA_EXEC_PIPE_NAME"] = HOST_PIPE
    host = subprocess.run(
        ["python3", "tools/lua-exec.py", code],
        cwd=ROOT,
        env=env_host,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10.0,
        check=False,
    )
    env_client = os.environ.copy()
    env_client["SDMOD_LUA_EXEC_PIPE_NAME"] = CLIENT_PIPE
    client = subprocess.run(
        ["python3", "tools/lua-exec.py", code],
        cwd=ROOT,
        env=env_client,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10.0,
        check=False,
    )
    if host.returncode != 0 or client.returncode != 0:
        raise VerifyFailure(
            "failed to disable Lua bots\n"
            f"host rc={host.returncode} output={host.stdout}\n"
            f"client rc={client.returncode} output={client.stdout}"
        )
    return {"host": host.stdout.strip(), "client": client.stdout.strip()}


def run_probe(samples: int, interval: float, timeout: float) -> dict[str, object]:
    output = run_command(
        [
            "python3",
            "tools/probe_hub_world_sync.py",
            "--samples",
            str(samples),
            "--interval",
            str(interval),
            "--timeout",
            str(timeout),
            "--json",
        ],
        timeout=max(timeout * max(samples, 1) + interval * max(samples - 1, 0) + 5.0, 30.0),
    )
    return extract_json_object(output)


def first_sample_values(probe: dict[str, object]) -> dict[str, dict[str, str]]:
    samples = probe.get("samples")
    if not isinstance(samples, list) or not samples:
        return {}
    first = samples[0]
    if not isinstance(first, dict):
        return {}
    clients = first.get("clients")
    if not isinstance(clients, list):
        return {}
    values_by_name: dict[str, dict[str, str]] = {}
    for client in clients:
        if not isinstance(client, dict):
            continue
        name = str(client.get("name", ""))
        values = client.get("values")
        if not name or not isinstance(values, dict):
            continue
        values_by_name[name] = {str(k): str(v) for k, v in values.items()}
    return values_by_name


def evaluate(probe: dict[str, object]) -> dict[str, object]:
    summary = probe.get("summary")
    if not isinstance(summary, dict):
        raise VerifyFailure("probe did not include a summary")

    values = first_sample_values(probe)
    host = values.get("host", {})
    client = values.get("client", {})
    rng_host = host.get("rng.global_818b08", "")
    rng_client = client.get("rng.global_818b08", "")
    rng_diverged = bool(rng_host and rng_client and rng_host != rng_client)

    student_count_diverged = bool(summary.get("student_count_diverged"))
    actor_total_diverged = bool(summary.get("actor_total_diverged"))
    student_state_diverged = bool(summary.get("student_state_diverged"))
    divergent = (
        student_count_diverged or
        actor_total_diverged or
        student_state_diverged or
        rng_diverged
    )

    return {
        "stock_hub_student_lockstep_viable": not divergent,
        "global_seed_as_primary_sync_recommended": False,
        "divergent": divergent,
        "reasons": {
            "actor_total_diverged": actor_total_diverged,
            "student_count_diverged": student_count_diverged,
            "student_state_diverged": student_state_diverged,
            "rng_global_818b08_diverged": rng_diverged,
        },
        "first_sample": {
            "host_rng_global_818b08": rng_host,
            "client_rng_global_818b08": rng_client,
            "host_students": host.get("students.total", ""),
            "client_students": client.get("students.total", ""),
            "host_actors": host.get("actors.total", ""),
            "client_actors": client.get("actors.total", ""),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=6)
    parser.add_argument("--interval", type=float, default=0.35)
    parser.add_argument("--lua-timeout", type=float, default=10.0)
    parser.add_argument("--launch-timeout", type=float, default=240.0)
    parser.add_argument("--preset", default="map_create_fire_mind_hub")
    parser.add_argument("--skip-launch", action="store_true")
    parser.add_argument("--keep-running", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    output: dict[str, object] = {"ok": False}
    try:
        if not args.skip_launch:
            output["launch"] = launch_isolated_pair(args.preset, args.launch_timeout)
        output["bots_disabled"] = disable_bots()
        time.sleep(0.75)
        probe = run_probe(args.samples, args.interval, args.lua_timeout)
        decision = evaluate(probe)
        output = {
            "ok": True,
            "decision": decision,
            "probe_summary": probe.get("summary", {}),
            "probe": probe,
        }
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
        if args.json:
            print(json.dumps(output, indent=2, sort_keys=True))
        else:
            print(json.dumps({"ok": output["ok"], "decision": decision}, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        output = {"ok": False, "error": str(exc)}
        RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_OUTPUT.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(output, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        if not args.keep_running:
            stop_games()


if __name__ == "__main__":
    raise SystemExit(main())
