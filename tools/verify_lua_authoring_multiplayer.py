#!/usr/bin/env python3
"""Verify that exact-pair transport defers Lua hot reload on both peers."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from multiplayer_lua_probe import DEFAULT_CLIENTS, parse_client, run_lua_client
from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    disable_bots,
    game_process_ids,
    launch_pair,
    stop_game_processes,
    wait_for_remote,
)
from verify_lua_authoring import (
    BASELINE_VERSION,
    MOD_ID,
    RELOADED_VERSION,
    _atomic_write,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_authoring_multiplayer_verification.json"
SOURCE = ROOT / "mods" / "lua_authoring_lab" / "scripts" / "main.lua"
ACCEPTANCE_MOD_ID = MOD_ID


SNAPSHOT_PROBE = """
local mod = assert(sd.runtime.get_mod())
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local scene = assert(sd.world.get_scene(), "live scene required")
local surface = assert(sd.ui.get_authored_state(authoring_lab_surface))
local owner_count = 0
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.is_owner then owner_count = owner_count + 1 end
end
print("mod_id=" .. tostring(mod.id))
print("hot_reload=" .. tostring(mod.hot_reload))
print("version=" .. tostring(authoring_lab_version))
print("surface_handle=" .. tostring(authoring_lab_surface))
print("surface_hidden=" .. tostring(surface.visible == false))
print("element_count=" .. tostring(#surface.elements))
print("transport_enabled=" .. tostring(multiplayer.transport_enabled))
print("transport_ready=" .. tostring(multiplayer.transport_ready))
print("authority=" .. tostring(sd.state.is_authority()))
print("world_scene=" .. tostring(scene.name or scene.kind))
print("participant_count=" .. tostring(multiplayer.participant_count))
print("participant_rows=" .. tostring(#(multiplayer.participants or {})))
print("owner_count=" .. tostring(owner_count))
"""


def _failed_exec(result: dict[str, Any]) -> str | None:
    if result.get("returncode") == 0:
        return None
    return str(
        result.get("stderr") or result.get("stdout") or "Lua exec failed"
    ).strip()


def _snapshot(client: tuple[str, str]) -> dict[str, str]:
    result = run_lua_client(
        client[0],
        client[1],
        SNAPSHOT_PROBE,
        timeout=12.0,
    )
    failure = _failed_exec(result)
    if failure:
        raise RuntimeError(failure)
    values = result.get("values", {})
    if not isinstance(values, dict):
        raise RuntimeError(f"Lua snapshot returned invalid values: {result}")
    return values


def snapshot_matches(
    values: dict[str, str],
    *,
    authority: bool,
    version: str,
    surface_handle: str | None = None,
) -> bool:
    try:
        return (
            values.get("mod_id") == ACCEPTANCE_MOD_ID
            and values.get("hot_reload") == "true"
            and values.get("version") == version
            and int(values.get("surface_handle", "0")) > 0
            and (
                surface_handle is None
                or values.get("surface_handle") == surface_handle
            )
            and values.get("surface_hidden") == "true"
            and values.get("element_count") == "2"
            and values.get("transport_enabled") == "true"
            and values.get("transport_ready") == "true"
            and values.get("authority") == ("true" if authority else "false")
            and values.get("world_scene") == "hub"
            and values.get("participant_count") == "2"
            and values.get("participant_rows") == "2"
            and values.get("owner_count") == "1"
        )
    except ValueError:
        return False


def _require_snapshot(
    client: tuple[str, str],
    *,
    authority: bool,
    version: str,
    surface_handle: str | None,
    description: str,
) -> dict[str, str]:
    values = _snapshot(client)
    if not snapshot_matches(
        values,
        authority=authority,
        version=version,
        surface_handle=surface_handle,
    ):
        raise RuntimeError(
            f"{description} failed for {client[0]}: {values}"
        )
    return values


def _assert_pair_stays(
    clients: list[tuple[str, str]],
    initial: list[dict[str, str]],
    *,
    duration: float,
    description: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + duration
    samples = [0, 0]
    latest = list(initial)
    while True:
        for index, client in enumerate(clients):
            latest[index] = _require_snapshot(
                client,
                authority=index == 0,
                version=BASELINE_VERSION,
                surface_handle=initial[index]["surface_handle"],
                description=description,
            )
            samples[index] += 1
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.15, remaining))
    return {
        "samples": {
            clients[0][0]: samples[0],
            clients[1][0]: samples[1],
        },
        "latest": latest,
    }


def _source_versions(source_path: Path) -> tuple[bytes, bytes]:
    original = source_path.read_bytes()
    baseline_token = BASELINE_VERSION.encode("utf-8")
    reloaded_token = RELOADED_VERSION.encode("utf-8")
    if original.count(baseline_token) != 1:
        raise RuntimeError(
            f"{source_path} must contain exactly one "
            f"{BASELINE_VERSION!r} token"
        )
    return original, original.replace(
        baseline_token,
        reloaded_token,
        1,
    )


def run(
    clients: list[tuple[str, str]],
    *,
    launch: bool,
    source_path: Path,
    settle_seconds: float,
) -> dict[str, Any]:
    if not launch:
        raise RuntimeError("Lua authoring acceptance requires --launch-pair")
    if len(clients) != 2:
        raise RuntimeError("exactly one host and one client endpoint are required")
    host, client = clients
    source_path = source_path.resolve()
    original, candidate = _source_versions(source_path)
    result: dict[str, Any] = {
        "ok": False,
        "launched_pair": True,
        "host": host[0],
        "client": client[0],
        "source": str(source_path),
        "original_sha256": hashlib.sha256(original).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
    }
    launched_process_ids: list[int] = []
    try:
        result["pair"] = launch_pair(
            tile_windows=False,
            kill_existing=False,
            exact_mod_id=ACCEPTANCE_MOD_ID,
        )
        launched_process_ids.extend(game_process_ids(result["pair"]))
        if len(set(launched_process_ids)) != 2:
            raise RuntimeError(
                "local pair did not report two exact process IDs: "
                f"{launched_process_ids}"
            )
        disable_bots()
        wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub")
        wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub")

        initial = [
            _require_snapshot(
                peer,
                authority=index == 0,
                version=BASELINE_VERSION,
                surface_handle=None,
                description="initial authoring pair snapshot",
            )
            for index, peer in enumerate((host, client))
        ]
        result["initial"] = initial

        primary_error: Exception | None = None
        cleanup_error: Exception | None = None
        source_changed = False
        try:
            if source_path.read_bytes() != original:
                raise RuntimeError(
                    "authoring source changed before candidate write; "
                    "refusing to overwrite it"
                )
            _atomic_write(source_path, candidate)
            source_changed = True
            result["deferred_candidate"] = _assert_pair_stays(
                clients,
                initial,
                duration=settle_seconds,
                description="transport-deferred candidate",
            )
        except Exception as error:  # noqa: BLE001 - restore exact source first.
            primary_error = error
        finally:
            try:
                current = source_path.read_bytes()
                if source_changed and current == candidate:
                    _atomic_write(source_path, original)
                elif current != original:
                    raise RuntimeError(
                        "authoring source changed concurrently; "
                        "refusing to overwrite it"
                    )
                if source_path.read_bytes() != original:
                    raise RuntimeError(
                        "authoring pair verifier did not restore exact "
                        "source bytes"
                    )
                result["restored"] = _assert_pair_stays(
                    clients,
                    initial,
                    duration=settle_seconds,
                    description="transport-deferred restored source",
                )
                result["source_restored"] = True
            except Exception as error:  # noqa: BLE001 - preserve both failures.
                cleanup_error = error

        if primary_error is not None:
            if cleanup_error is not None:
                raise RuntimeError(
                    f"{primary_error}; source cleanup also failed: "
                    f"{cleanup_error}"
                ) from primary_error
            raise primary_error
        if cleanup_error is not None:
            raise cleanup_error

        result["ok"] = True
        return result
    finally:
        stop_game_processes(launched_process_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        action="append",
        type=parse_client,
        help="Lua endpoint as NAME=PIPE; provide exactly host then client.",
    )
    parser.add_argument(
        "--launch-pair",
        action="store_true",
        help="stage and launch the disposable local pair required by this verifier",
    )
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--settle-seconds", type=float, default=1.25)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.launch_pair:
        result["error"] = "Lua authoring acceptance requires --launch-pair"
        return_code = 2
    else:
        try:
            result = run(
                args.client or list(DEFAULT_CLIENTS),
                launch=True,
                source_path=args.source,
                settle_seconds=max(0.75, args.settle_seconds),
            )
            return_code = 0 if result.get("ok") else 1
        except Exception as error:  # noqa: BLE001 - preserve exact live evidence.
            result["error"] = str(error)
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
