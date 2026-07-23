#!/usr/bin/env python3
"""Verify profile-local Lua storage across a disposable multiplayer pair."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable, Iterator
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


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "runtime" / "lua_storage_multiplayer_verification.json"
ACCEPTANCE_MOD_ID = "sample.lua.storage_lab"
HOST_TOKEN = "host-profile-token"
CLIENT_TOKEN = "client-profile-token"
STORAGE_KEY = hashlib.sha256(ACCEPTANCE_MOD_ID.encode("utf-8")).hexdigest()
INSTANCE_NAMES = ("local-mp-host", "local-mp-client")
PROFILE_STORAGE_PATHS = tuple(
    ROOT
    / "runtime"
    / "instances"
    / instance
    / "stage"
    / ".sdmod"
    / "runtime"
    / "sandbox"
    / "mods"
    / STORAGE_KEY
    / "data"
    / "profile-storage.bin"
    for instance in INSTANCE_NAMES
)


STATE_PROBE = """
local mod = assert(sd.runtime.get_mod())
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local scene = assert(sd.world.get_scene(), "live scene required")
local owner_count = 0
for _, participant in ipairs(multiplayer.participants or {}) do
  if participant.is_owner then owner_count = owner_count + 1 end
end
local namespace_count = 0
local namespace_exact = true
for name, value in pairs(sd.storage) do
  namespace_count = namespace_count + 1
  if (name ~= "get" and name ~= "set" and name ~= "delete" and
      name ~= "clear" and name ~= "snapshot") or
      type(value) ~= "function" then
    namespace_exact = false
  end
end
namespace_exact = namespace_exact and namespace_count == 5

local snapshot = sd.storage.snapshot()
local entry_count = 0
for _, _ in pairs(snapshot) do entry_count = entry_count + 1 end
local acceptance = snapshot.acceptance
local acceptance_exact = acceptance == nil
if type(acceptance) == "table" then
  local keys = {
    token = true, owner = true, count = true,
    flags = true, nested = true,
  }
  local key_count = 0
  acceptance_exact = true
  for key, _ in pairs(acceptance) do
    if type(key) ~= "string" or not keys[key] then
      acceptance_exact = false
    end
    key_count = key_count + 1
  end
  local nested = acceptance.nested
  local nested_count = 0
  if type(nested) == "table" then
    for key, _ in pairs(nested) do
      if key ~= "enabled" and key ~= "label" then
        acceptance_exact = false
      end
      nested_count = nested_count + 1
    end
  end
  acceptance_exact =
    acceptance_exact and key_count == 5 and
    type(acceptance.token) == "string" and
    type(acceptance.owner) == "string" and
    acceptance.count == 41 and
    type(acceptance.flags) == "table" and
    #acceptance.flags == 2 and
    acceptance.flags[1] == true and acceptance.flags[2] == false and
    type(nested) == "table" and nested_count == 2 and
    nested.enabled == true and nested.label == "profile"
end

print("mod_id=" .. tostring(mod.id))
print("storage_capability=" .. tostring(
  sd.runtime.has_capability("storage.profile.local")))
print("authority=" .. tostring(sd.state.is_authority()))
print("world_scene=" .. tostring(scene.name or scene.kind))
print("participant_count=" .. tostring(multiplayer.participant_count))
print("participant_rows=" .. tostring(#(multiplayer.participants or {})))
print("owner_count=" .. tostring(owner_count))
print("namespace_exact=" .. tostring(namespace_exact))
print("entry_count=" .. tostring(entry_count))
print("has_launches=" .. tostring(snapshot.launches ~= nil))
print("launches=" .. tostring(snapshot.launches or 0))
print("has_acceptance=" .. tostring(acceptance ~= nil))
print("acceptance_exact=" .. tostring(acceptance_exact))
print("token=" .. tostring(acceptance and acceptance.token or ""))
print("owner=" .. tostring(acceptance and acceptance.owner or ""))
"""


CLEAR_PROBE = """
local first = sd.storage.clear()
local second = sd.storage.clear()
print("first=" .. tostring(first))
print("second=" .. tostring(second))
print("empty=" .. tostring(next(sd.storage.snapshot()) == nil))
"""


DELETE_PROBE = """
local first = sd.storage.delete("acceptance")
local second = sd.storage.delete("acceptance")
local snapshot = sd.storage.snapshot()
local count = 0
for _, _ in pairs(snapshot) do count = count + 1 end
print("first=" .. tostring(first))
print("second=" .. tostring(second))
print("entry_count=" .. tostring(count))
print("launches_retained=" .. tostring(snapshot.launches == 1))
"""


def _write_probe(token: str, owner: str) -> str:
    return f"""
local default_ok = sd.storage.get("missing", "fallback") == "fallback"
local stored = sd.storage.set("acceptance", {{
  token = {json.dumps(token)},
  owner = {json.dumps(owner)},
  count = 41,
  flags = {{true, false}},
  nested = {{enabled = true, label = "profile"}},
}})
local ephemeral_set = sd.storage.set("ephemeral", "delete-me")
local ephemeral_deleted = sd.storage.delete("ephemeral")
local delete_missing = not sd.storage.delete("ephemeral")

local cycle = {{}}
cycle.self = cycle
local empty_key_ok = pcall(sd.storage.set, "", true)
local long_key_ok = pcall(sd.storage.set, string.rep("k", 129), true)
local cycle_ok = pcall(sd.storage.set, "cycle", cycle)
local sparse_ok = pcall(
  sd.storage.set, "sparse", {{[1] = true, [3] = false}})
local mixed_ok = pcall(
  sd.storage.set, "mixed", {{[1] = true, name = "mixed"}})
local nan_ok = pcall(sd.storage.set, "nan", 0 / 0)
local infinity_ok = pcall(sd.storage.set, "infinity", math.huge)
local nil_ok = pcall(sd.storage.set, "nil", nil)

local snapshot = sd.storage.snapshot()
local count = 0
for _, _ in pairs(snapshot) do count = count + 1 end
local acceptance = snapshot.acceptance or {{}}
local transactional_unchanged =
  count == 1 and snapshot.ephemeral == nil and
  snapshot.cycle == nil and snapshot.sparse == nil and
  snapshot.mixed == nil and snapshot.nan == nil and
  snapshot.infinity == nil and snapshot[""] == nil and
  acceptance.token == {json.dumps(token)} and
  acceptance.owner == {json.dumps(owner)}

print("stored=" .. tostring(stored))
print("default_ok=" .. tostring(default_ok))
print("ephemeral_set=" .. tostring(ephemeral_set))
print("ephemeral_deleted=" .. tostring(ephemeral_deleted))
print("delete_missing=" .. tostring(delete_missing))
print("empty_key_rejected=" .. tostring(not empty_key_ok))
print("long_key_rejected=" .. tostring(not long_key_ok))
print("cycle_rejected=" .. tostring(not cycle_ok))
print("sparse_rejected=" .. tostring(not sparse_ok))
print("mixed_rejected=" .. tostring(not mixed_ok))
print("nan_rejected=" .. tostring(not nan_ok))
print("infinity_rejected=" .. tostring(not infinity_ok))
print("nil_rejected=" .. tostring(not nil_ok))
print("transactional_unchanged=" .. tostring(transactional_unchanged))
"""


def _temporary_path(path: Path) -> Path:
    return path.with_name(path.name + ".tmp")


def _atomic_restore(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.acceptance-restore-{uuid.uuid4().hex}"
    )
    try:
        with temporary.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def _preserve_profile_storage() -> Iterator[dict[str, str]]:
    managed = tuple(
        candidate
        for path in PROFILE_STORAGE_PATHS
        for candidate in (path, _temporary_path(path))
    )
    saved: dict[Path, bytes | None] = {}
    for path in managed:
        if path.is_symlink():
            raise RuntimeError(
                f"refusing symlinked Lua profile storage path: {path}"
            )
        if path.exists() and not path.is_file():
            raise RuntimeError(
                f"refusing non-file Lua profile storage path: {path}"
            )
        saved[path] = path.read_bytes() if path.exists() else None

    try:
        for path in managed:
            path.unlink(missing_ok=True)
        yield {
            instance: str(path.relative_to(ROOT)).replace("\\", "/")
            for instance, path in zip(
                INSTANCE_NAMES,
                PROFILE_STORAGE_PATHS,
                strict=True,
            )
        }
    finally:
        restore_errors: list[str] = []
        for path in managed:
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                restore_errors.append(f"remove {path}: {error}")
        for path, payload in saved.items():
            if payload is None:
                continue
            try:
                _atomic_restore(path, payload)
            except OSError as error:
                restore_errors.append(f"restore {path}: {error}")
        if restore_errors:
            raise RuntimeError(
                "Lua profile storage restoration failed: "
                + "; ".join(restore_errors)
            )


def _failed_exec(result: dict[str, Any]) -> str | None:
    if result.get("returncode") == 0:
        return None
    return str(
        result.get("stderr") or result.get("stdout") or "Lua exec failed"
    ).strip()


def _values(result: dict[str, Any]) -> dict[str, str]:
    values = result.get("values", {})
    if not isinstance(values, dict):
        raise RuntimeError(f"Lua probe returned invalid values: {result}")
    return values


def _int_value(values: dict[str, str], name: str) -> int:
    try:
        return int(values.get(name, ""))
    except ValueError as error:
        raise RuntimeError(f"invalid {name}: {values}") from error


def storage_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
    token: str | None,
    owner: str | None,
    launches: int | None,
) -> bool:
    try:
        expected_entries = int(token is not None) + int(launches is not None)
        return (
            values.get("mod_id") == ACCEPTANCE_MOD_ID
            and values.get("storage_capability") == "true"
            and values.get("authority") == ("true" if authority else "false")
            and values.get("world_scene") == "hub"
            and _int_value(values, "participant_count") == 2
            and _int_value(values, "participant_rows") == 2
            and _int_value(values, "owner_count") == 1
            and values.get("namespace_exact") == "true"
            and _int_value(values, "entry_count") == expected_entries
            and values.get("has_launches")
            == ("true" if launches is not None else "false")
            and _int_value(values, "launches") == (launches or 0)
            and values.get("has_acceptance")
            == ("true" if token is not None else "false")
            and values.get("acceptance_exact") == "true"
            and values.get("token") == (token or "")
            and values.get("owner") == (owner or "")
        )
    except RuntimeError:
        return False


def write_matches(values: dict[str, str]) -> bool:
    return all(
        values.get(name) == "true"
        for name in (
            "stored",
            "default_ok",
            "ephemeral_set",
            "ephemeral_deleted",
            "delete_missing",
            "empty_key_rejected",
            "long_key_rejected",
            "cycle_rejected",
            "sparse_rejected",
            "mixed_rejected",
            "nan_rejected",
            "infinity_rejected",
            "nil_rejected",
            "transactional_unchanged",
        )
    )


def clear_matches(values: dict[str, str]) -> bool:
    return (
        values.get("first") == "true"
        and values.get("second") == "false"
        and values.get("empty") == "true"
    )


def delete_matches(values: dict[str, str]) -> bool:
    return (
        values.get("first") == "true"
        and values.get("second") == "false"
        and values.get("entry_count") == "1"
        and values.get("launches_retained") == "true"
    )


def _run_probe(
    client: tuple[str, str],
    code: str,
) -> dict[str, Any]:
    result = run_lua_client(client[0], client[1], code, timeout=12.0)
    failure = _failed_exec(result)
    if failure:
        raise RuntimeError(failure)
    return result


def _require_action(
    client: tuple[str, str],
    code: str,
    predicate: Callable[[dict[str, str]], bool],
    description: str,
) -> dict[str, Any]:
    result = _run_probe(client, code)
    if not predicate(_values(result)):
        raise RuntimeError(f"{description} failed: {result}")
    return result


def _poll_state(
    client: tuple[str, str],
    *,
    authority: bool,
    token: str | None,
    owner: str | None,
    launches: int | None,
    timeout: float,
    description: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = run_lua_client(
            client[0],
            client[1],
            STATE_PROBE,
            timeout=12.0,
        )
        values = last.get("values", {})
        if (
            _failed_exec(last) is None
            and isinstance(values, dict)
            and storage_state_matches(
                values,
                authority=authority,
                token=token,
                owner=owner,
                launches=launches,
            )
        ):
            return last
        time.sleep(0.1)
    raise RuntimeError(
        f"{description} did not converge for {client[0]}: {last}"
    )


def _storage_file_evidence() -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for instance, path in zip(
        INSTANCE_NAMES,
        PROFILE_STORAGE_PATHS,
        strict=True,
    ):
        if not path.is_file():
            raise RuntimeError(
                f"{instance} profile storage was not published: {path}"
            )
        temporary = _temporary_path(path)
        if temporary.exists():
            raise RuntimeError(
                f"{instance} profile storage left a temporary file: "
                f"{temporary}"
            )
        payload = path.read_bytes()
        if not payload or len(payload) > 64 * 1024:
            raise RuntimeError(
                f"{instance} profile storage size is invalid: {len(payload)}"
            )
        evidence[instance] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "temporary_absent": True,
        }
    hashes = {item["sha256"] for item in evidence.values()}
    if len(hashes) != len(PROFILE_STORAGE_PATHS):
        raise RuntimeError(
            f"host/client profile storage files are not distinct: {evidence}"
        )
    return evidence


def _launch_owned_pair(
    process_ids: list[int],
) -> dict[str, object]:
    pair = launch_pair(
        temporary_host_profile=True,
        tile_windows=False,
        kill_existing=False,
        exact_mod_id=ACCEPTANCE_MOD_ID,
    )
    process_ids.extend(game_process_ids(pair))
    if len(set(process_ids)) != 2:
        raise RuntimeError(
            "local pair did not report two exact process IDs: "
            f"{process_ids}"
        )
    return pair


def _wait_for_pair() -> None:
    disable_bots()
    wait_for_remote(HOST_PIPE, CLIENT_ID, CLIENT_NAME, "hub")
    wait_for_remote(CLIENT_PIPE, HOST_ID, HOST_NAME, "hub")


def run(
    clients: list[tuple[str, str]],
    *,
    launch: bool,
    timeout: float,
) -> dict[str, Any]:
    if not launch:
        raise RuntimeError("Lua storage acceptance requires --launch-pair")
    if len(clients) != 2:
        raise RuntimeError("exactly one host and one client endpoint are required")
    host, client = clients
    result: dict[str, Any] = {
        "ok": False,
        "launched_pair": True,
        "host": host[0],
        "client": client[0],
        "sessions": [],
    }
    launched_process_ids: list[int] = []

    with _preserve_profile_storage() as profile_paths:
        result["profile_paths"] = profile_paths
        try:
            pair = _launch_owned_pair(launched_process_ids)
            result["sessions"].append(pair)
            _wait_for_pair()

            result["fresh_profiles"] = [
                _poll_state(
                    peer,
                    authority=index == 0,
                    token=None,
                    owner=None,
                    launches=1,
                    timeout=timeout,
                    description="fresh profile launch count",
                )
                for index, peer in enumerate((host, client))
            ]
            result["initial_clear"] = [
                _require_action(
                    peer,
                    CLEAR_PROBE,
                    clear_matches,
                    "initial profile clear",
                )
                for peer in (host, client)
            ]
            result["empty_profiles"] = [
                _poll_state(
                    peer,
                    authority=index == 0,
                    token=None,
                    owner=None,
                    launches=None,
                    timeout=timeout,
                    description="empty profile storage",
                )
                for index, peer in enumerate((host, client))
            ]

            result["host_write"] = _require_action(
                host,
                _write_probe(HOST_TOKEN, "host"),
                write_matches,
                "host profile write",
            )
            result["host_write_isolation"] = [
                _poll_state(
                    host,
                    authority=True,
                    token=HOST_TOKEN,
                    owner="host",
                    launches=None,
                    timeout=timeout,
                    description="host local profile value",
                ),
                _poll_state(
                    client,
                    authority=False,
                    token=None,
                    owner=None,
                    launches=None,
                    timeout=timeout,
                    description="client isolation from host profile write",
                ),
            ]
            result["client_write"] = _require_action(
                client,
                _write_probe(CLIENT_TOKEN, "client"),
                write_matches,
                "client profile write",
            )
            result["independent_profiles"] = [
                _poll_state(
                    host,
                    authority=True,
                    token=HOST_TOKEN,
                    owner="host",
                    launches=None,
                    timeout=timeout,
                    description="host retained profile value",
                ),
                _poll_state(
                    client,
                    authority=False,
                    token=CLIENT_TOKEN,
                    owner="client",
                    launches=None,
                    timeout=timeout,
                    description="client local profile value",
                ),
            ]

            stop_game_processes(launched_process_ids)
            launched_process_ids = []
            result["durable_files"] = _storage_file_evidence()

            pair = _launch_owned_pair(launched_process_ids)
            result["sessions"].append(pair)
            _wait_for_pair()
            result["persisted_profiles"] = [
                _poll_state(
                    host,
                    authority=True,
                    token=HOST_TOKEN,
                    owner="host",
                    launches=1,
                    timeout=timeout,
                    description="host persisted profile value",
                ),
                _poll_state(
                    client,
                    authority=False,
                    token=CLIENT_TOKEN,
                    owner="client",
                    launches=1,
                    timeout=timeout,
                    description="client persisted profile value",
                ),
            ]

            result["host_delete"] = _require_action(
                host,
                DELETE_PROBE,
                delete_matches,
                "host profile delete",
            )
            result["host_delete_isolation"] = [
                _poll_state(
                    host,
                    authority=True,
                    token=None,
                    owner=None,
                    launches=1,
                    timeout=timeout,
                    description="host deleted profile value",
                ),
                _poll_state(
                    client,
                    authority=False,
                    token=CLIENT_TOKEN,
                    owner="client",
                    launches=1,
                    timeout=timeout,
                    description="client retained profile after host delete",
                ),
            ]
            result["host_clear"] = _require_action(
                host,
                CLEAR_PROBE,
                clear_matches,
                "host profile clear",
            )
            result["host_clear_isolation"] = [
                _poll_state(
                    host,
                    authority=True,
                    token=None,
                    owner=None,
                    launches=None,
                    timeout=timeout,
                    description="host empty profile",
                ),
                _poll_state(
                    client,
                    authority=False,
                    token=CLIENT_TOKEN,
                    owner="client",
                    launches=1,
                    timeout=timeout,
                    description="client retained profile after host clear",
                ),
            ]
            result["client_clear"] = _require_action(
                client,
                CLEAR_PROBE,
                clear_matches,
                "client profile clear",
            )
            result["released"] = [
                _poll_state(
                    peer,
                    authority=index == 0,
                    token=None,
                    owner=None,
                    launches=None,
                    timeout=timeout,
                    description="released profile storage",
                )
                for index, peer in enumerate((host, client))
            ]
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
    parser.add_argument(
        "--confirm-profile-mutation",
        action="store_true",
        help="confirm temporary writes to isolated host/client mod profiles",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.confirm_profile_mutation:
        result["error"] = (
            "refusing profile writes without --confirm-profile-mutation"
        )
        return_code = 2
    elif not args.launch_pair:
        result["error"] = "Lua storage acceptance requires --launch-pair"
        return_code = 2
    else:
        try:
            result = run(
                args.client or list(DEFAULT_CLIENTS),
                launch=True,
                timeout=max(1.0, args.timeout),
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
