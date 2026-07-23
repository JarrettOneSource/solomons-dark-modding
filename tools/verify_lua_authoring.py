#!/usr/bin/env python3
"""Verify source hot reload against an already-running isolated authoring lab."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import VerifyFailure, lua, parse_key_values


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "mods" / "lua_authoring_lab" / "scripts" / "main.lua"
DEFAULT_OUTPUT = ROOT / "runtime" / "lua_authoring_verification.json"
DEFAULT_PIPE = "SolomonDarkModLoader_LuaExec"
MOD_ID = "sample.lua.authoring_lab"
BASELINE_VERSION = "authoring-baseline-0001"
RELOADED_VERSION = "authoring-reloaded-0002"


SNAPSHOT = r'''
local mod = assert(sd.runtime.get_mod())
local multiplayer = sd.runtime.get_multiplayer_state()
local surface = assert(sd.ui.get_authored_state(authoring_lab_surface))
print("mod_id=" .. mod.id)
print("hot_reload=" .. tostring(mod.hot_reload))
print("version=" .. authoring_lab_version)
print("surface_handle=" .. tostring(authoring_lab_surface))
print("surface_hidden=" .. tostring(surface.visible == false))
print("element_count=" .. tostring(#surface.elements))
print("transport_enabled=" .. tostring(multiplayer.transport_enabled))
print("transport_ready=" .. tostring(multiplayer.transport_ready))
'''


def _atomic_write(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".authoring-verify",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _snapshot(pipe_name: str) -> dict[str, str]:
    values = parse_key_values(lua(pipe_name, SNAPSHOT, timeout=8.0))
    required = {
        "mod_id",
        "hot_reload",
        "version",
        "surface_handle",
        "surface_hidden",
        "element_count",
        "transport_enabled",
        "transport_ready",
    }
    missing = sorted(required.difference(values))
    if missing:
        raise VerifyFailure(f"authoring snapshot omitted {missing}: {values}")
    if values["mod_id"] != MOD_ID:
        raise VerifyFailure(
            f"Lua exec targets {values['mod_id']!r}; enable only {MOD_ID!r}"
        )
    for name in ("hot_reload", "surface_hidden"):
        if values[name] != "true":
            raise VerifyFailure(f"authoring snapshot failed {name}: {values}")
    if values["element_count"] != "2":
        raise VerifyFailure(f"authoring surface was not recreated intact: {values}")
    return values


def _wait_for_version(
    pipe_name: str,
    expected: str,
    timeout: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] | None = None
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = _snapshot(pipe_name)
            if last["version"] == expected:
                return last
        except Exception as error:  # noqa: BLE001 - retain transient reload detail.
            last_error = str(error)
        time.sleep(0.15)
    raise VerifyFailure(
        f"hot reload did not reach {expected!r}; last={last} error={last_error}"
    )


def _assert_version_stays(
    pipe_name: str,
    expected: str,
    expected_handle: str,
    duration: float,
) -> dict[str, str]:
    deadline = time.monotonic() + duration
    last = _snapshot(pipe_name)
    while True:
        if last["version"] != expected or last["surface_handle"] != expected_handle:
            raise VerifyFailure(
                "hot reload changed state while transport deferral was required: "
                f"{last}"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return last
        time.sleep(min(0.2, remaining))
        last = _snapshot(pipe_name)


def _parse_transport_enabled(values: dict[str, str]) -> bool:
    value = values["transport_enabled"]
    if value not in {"true", "false"}:
        raise VerifyFailure(f"invalid transport_enabled value: {values}")
    return value == "true"


def run(
    pipe_name: str,
    source_path: Path,
    mode: str,
    timeout: float,
    settle_seconds: float,
) -> dict[str, Any]:
    source_path = source_path.resolve()
    original = source_path.read_bytes()
    baseline_token = BASELINE_VERSION.encode("utf-8")
    reloaded_token = RELOADED_VERSION.encode("utf-8")
    if original.count(baseline_token) != 1:
        raise VerifyFailure(
            f"{source_path} must contain exactly one {BASELINE_VERSION!r} token"
        )
    candidate = original.replace(baseline_token, reloaded_token, 1)
    invalid_candidate = candidate + b"\nlocal authoring_syntax_error =\n"

    initial = _snapshot(pipe_name)
    if initial["version"] != BASELINE_VERSION:
        raise VerifyFailure(f"authoring lab was not at its baseline source: {initial}")
    transport_enabled = _parse_transport_enabled(initial)
    selected_mode = (
        "deferred" if transport_enabled else "offline"
    ) if mode == "auto" else mode
    if selected_mode == "offline" and transport_enabled:
        raise VerifyFailure("offline reload mode requires transport_enabled=false")
    if selected_mode == "deferred" and not transport_enabled:
        raise VerifyFailure("deferred mode requires transport_enabled=true")

    evidence: dict[str, Any] = {
        "mode": selected_mode,
        "source": str(source_path),
        "initial": initial,
    }
    primary_error: Exception | None = None
    source_changed = False
    try:
        _atomic_write(source_path, candidate)
        source_changed = True
        if selected_mode == "offline":
            reloaded = _wait_for_version(pipe_name, RELOADED_VERSION, timeout)
            if reloaded["surface_handle"] == initial["surface_handle"]:
                raise VerifyFailure(
                    "reload did not recreate the mod-owned UI surface with a new handle"
                )
            evidence["reloaded"] = reloaded

            _atomic_write(source_path, invalid_candidate)
            time.sleep(settle_seconds)
            preserved = _snapshot(pipe_name)
            if (
                preserved["version"] != RELOADED_VERSION
                or preserved["surface_handle"] != reloaded["surface_handle"]
            ):
                raise VerifyFailure(
                    "syntax-invalid source did not preserve the running Lua state: "
                    f"{preserved}"
                )
            evidence["syntax_error_preserved"] = preserved
        else:
            evidence["deferred_candidate"] = _assert_version_stays(
                pipe_name,
                BASELINE_VERSION,
                initial["surface_handle"],
                settle_seconds,
            )
    except Exception as error:  # noqa: BLE001 - cleanup must still restore source.
        primary_error = error
    finally:
        cleanup_error: Exception | None = None
        try:
            if source_path.read_bytes() != original:
                _atomic_write(source_path, original)
            if source_changed:
                if selected_mode == "offline":
                    restored = _wait_for_version(pipe_name, BASELINE_VERSION, timeout)
                    if "reloaded" in evidence and (
                        restored["surface_handle"]
                        == evidence["reloaded"]["surface_handle"]
                    ):
                        raise VerifyFailure(
                            "restored baseline did not recreate the Lua state"
                        )
                    evidence["restored"] = restored
                else:
                    evidence["restored"] = _assert_version_stays(
                        pipe_name,
                        BASELINE_VERSION,
                        initial["surface_handle"],
                        settle_seconds,
                    )
            if source_path.read_bytes() != original:
                raise VerifyFailure("authoring verifier did not restore exact source bytes")
        except Exception as error:  # noqa: BLE001 - report cleanup alongside primary.
            cleanup_error = error

        if primary_error is not None:
            if cleanup_error is not None:
                raise VerifyFailure(
                    f"{primary_error}; source cleanup also failed: {cleanup_error}"
                ) from primary_error
            raise primary_error
        if cleanup_error is not None:
            raise cleanup_error

    evidence["source_restored"] = True
    return {
        "ok": True,
        "pipe": pipe_name,
        "evidence": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", default=DEFAULT_PIPE)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--mode",
        choices=("auto", "offline", "deferred"),
        default="auto",
    )
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--settle-seconds", type=float, default=1.25)
    args = parser.parse_args()

    try:
        result: dict[str, Any] = run(
            args.pipe,
            args.source,
            args.mode,
            max(1.0, args.timeout),
            max(0.75, args.settle_seconds),
        )
        return_code = 0
    except Exception as error:  # noqa: BLE001 - preserve exact live evidence.
        result = {"ok": False, "pipe": args.pipe, "error": str(error)}
        return_code = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
