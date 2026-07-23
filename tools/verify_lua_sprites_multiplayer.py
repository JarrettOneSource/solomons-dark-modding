#!/usr/bin/env python3
"""Verify presentation-local Lua sprite atlases across a disposable pair."""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from build_lua_sprite_bundle import build_bundle
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
OUTPUT = ROOT / "runtime" / "lua_sprites_multiplayer_verification.json"
MOD_ROOT = ROOT / "mods" / "lua_sprites_lab"
FIXTURE_IMAGE_SOURCE = MOD_ROOT / "sprites" / "lab.png.base64"
FIXTURE_DESCRIPTOR = MOD_ROOT / "sprites" / "atlas.example.json"
FIXTURE_IMAGE = MOD_ROOT / "sprites" / "lab.png"
FIXTURE_BUNDLE = MOD_ROOT / "sprites" / "lab.bundle"
FIXTURE_IMAGE_SHA256 = (
    "9e59013304f476f3943dd6270d2503012c5a631e54d75b571b3da7b6227507db"
)
ACCEPTANCE_MOD_ID = "sample.lua.sprites_lab"
ATLAS_KEY = "acceptance"
ATLAS_ID = f"{ACCEPTANCE_MOD_ID}:{ATLAS_KEY}"
IMAGE_PATH = "sprites/lab.png"
BUNDLE_PATH = "sprites/lab.bundle"


BASE_PROBE = f"""
local mod = assert(sd.runtime.get_mod())
local multiplayer = assert(sd.runtime.get_multiplayer_state())
local scene = assert(sd.world.get_scene(), "live scene required")
local owner_count = 0
for _, participant in ipairs(multiplayer.participants or {{}}) do
  if participant.is_owner then owner_count = owner_count + 1 end
end
local namespace_count = 0
local namespace_exact = true
for name, value in pairs(sd.sprites) do
  namespace_count = namespace_count + 1
  if (name ~= "register" and name ~= "unregister" and
      name ~= "get" and name ~= "list" and name ~= "get_limits") or
      type(value) ~= "function" then
    namespace_exact = false
  end
end
namespace_exact = namespace_exact and namespace_count == 5
local atlas = sd.sprites.get({json.dumps(ATLAS_KEY)})
local listed = sd.sprites.list()
print("mod_id=" .. tostring(mod.id))
print("register_capability=" .. tostring(
  sd.runtime.has_capability("sprites.local.register")))
print("read_capability=" .. tostring(
  sd.runtime.has_capability("sprites.local.read")))
print("draw_capability=" .. tostring(
  sd.runtime.has_capability("draw.local.immediate")))
print("authority=" .. tostring(sd.state.is_authority()))
print("world_scene=" .. tostring(scene.name or scene.kind))
print("participant_count=" .. tostring(multiplayer.participant_count))
print("participant_rows=" .. tostring(#(multiplayer.participants or {{}})))
print("owner_count=" .. tostring(owner_count))
print("namespace_exact=" .. tostring(namespace_exact))
print("registered=" .. tostring(atlas ~= nil))
print("list_count=" .. tostring(#listed))
"""


REGISTER_PROBE = f"""
local image = {json.dumps(IMAGE_PATH)}
local bundle = {json.dumps(BUNDLE_PATH)}
local traversal_ok = pcall(
  sd.sprites.register, "bad_traversal", "../escape.png", bundle)
local absolute_ok = pcall(
  sd.sprites.register, "bad_absolute", "/escape.png", bundle)
local image_extension_ok = pcall(
  sd.sprites.register, "bad_image_extension", "sprites/nope.txt", bundle)
local bundle_extension_ok = pcall(
  sd.sprites.register, "bad_bundle_extension", image, "sprites/nope.txt")
local bad_key_ok = pcall(sd.sprites.register, "BadKey", image, bundle)
local extra_register_ok = pcall(
  sd.sprites.register, "extra", image, bundle, true)
local first = sd.sprites.register(
  {json.dumps(ATLAS_KEY)}, image, bundle)
_G.__lua_sprites_acceptance_initial_revision = first.revision
_G.__lua_sprites_acceptance_current_revision = first.revision
local frame_zero = assert(sd.draw.get_sprite_info(first.id, 0))
local frame_one = assert(sd.draw.get_sprite_info(first.id, 1))
print("accepted=true")
print("id=" .. tostring(first.id))
print("key=" .. tostring(first.key))
print("image=" .. tostring(first.image))
print("bundle=" .. tostring(first.bundle))
print("frame_count=" .. tostring(first.frame_count))
print("image_width=" .. tostring(first.image_width))
print("image_height=" .. tostring(first.image_height))
print("revision=" .. tostring(first.revision))
print("local_only=" .. tostring(first.local_only))
print("frame_zero_x=" .. string.format("%.0f", frame_zero.atlas_x))
print("frame_zero_y=" .. string.format("%.0f", frame_zero.atlas_y))
print("frame_zero_width=" .. string.format("%.0f", frame_zero.packed_width))
print("frame_zero_height=" .. string.format("%.0f", frame_zero.packed_height))
print("frame_one_x=" .. string.format("%.0f", frame_one.atlas_x))
print("frame_one_y=" .. string.format("%.0f", frame_one.atlas_y))
print("frame_one_width=" .. string.format("%.0f", frame_one.packed_width))
print("frame_one_height=" .. string.format("%.0f", frame_one.packed_height))
print("traversal_rejected=" .. tostring(not traversal_ok))
print("absolute_rejected=" .. tostring(not absolute_ok))
print("image_extension_rejected=" .. tostring(not image_extension_ok))
print("bundle_extension_rejected=" .. tostring(not bundle_extension_ok))
print("bad_key_rejected=" .. tostring(not bad_key_ok))
print("extra_register_rejected=" .. tostring(not extra_register_ok))
"""


ATLAS_STATE_PROBE = f"""
{BASE_PROBE}
local atlas = sd.sprites.get({json.dumps(ATLAS_KEY)})
if atlas == nil then
  print("ready=true")
  return
end

local function exact_object(value, allowed, expected)
  if type(value) ~= "table" then return false end
  local count = 0
  for key, _ in pairs(value) do
    if type(key) ~= "string" or not allowed[key] then return false end
    count = count + 1
  end
  return count == expected
end

local atlas_keys = {{
  id = true, key = true, image = true, bundle = true,
  frame_count = true, image_width = true, image_height = true,
  revision = true, local_only = true,
}}
local limits_keys = {{
  atlases_per_mod = true, global_atlases = true,
  frames_per_atlas = true, global_frames = true,
  relative_path_bytes = true, atlas_id_bytes = true,
  image_bytes = true, bundle_bytes = true,
  image_dimension = true, frame_geometry = true,
}}
local frame_keys = {{
  atlas = true, record = true, atlas_x = true, atlas_y = true,
  packed_width = true, packed_height = true,
  logical_width = true, logical_height = true,
  content_width = true, content_height = true,
  center_offset_x = true, center_offset_y = true, rotated = true,
}}
local limits = sd.sprites.get_limits()
local frame_zero = assert(sd.draw.get_sprite_info(atlas.id, 0))
local frame_one = assert(sd.draw.get_sprite_info(atlas.id, 1))
local schema_exact =
  exact_object(atlas, atlas_keys, 9) and
  exact_object(limits, limits_keys, 10) and
  exact_object(frame_zero, frame_keys, 13) and
  exact_object(frame_one, frame_keys, 13)
local limits_exact =
  limits.atlases_per_mod == 32 and
  limits.global_atlases == 128 and
  limits.frames_per_atlas == 4096 and
  limits.global_frames == 32768 and
  limits.relative_path_bytes == 512 and
  limits.atlas_id_bytes == 257 and
  limits.image_bytes == 67108864 and
  limits.bundle_bytes == 16777216 and
  limits.image_dimension == 4096 and
  limits.frame_geometry == 16384
local frames_exact =
  frame_zero.atlas == atlas.id and frame_zero.record == 0 and
  frame_zero.atlas_x == 0 and frame_zero.atlas_y == 0 and
  frame_zero.packed_width == 16 and frame_zero.packed_height == 16 and
  frame_zero.logical_width == 16 and frame_zero.logical_height == 16 and
  frame_zero.content_width == 16 and frame_zero.content_height == 16 and
  frame_zero.center_offset_x == 0 and frame_zero.center_offset_y == 0 and
  frame_zero.rotated == false and
  frame_one.atlas == atlas.id and frame_one.record == 1 and
  frame_one.atlas_x == 16 and frame_one.atlas_y == 0 and
  frame_one.packed_width == 16 and frame_one.packed_height == 16 and
  frame_one.logical_width == 16 and frame_one.logical_height == 16 and
  frame_one.content_width == 16 and frame_one.content_height == 16 and
  frame_one.center_offset_x == 0 and frame_one.center_offset_y == 0 and
  frame_one.rotated == false
local raw_internals_absent =
  atlas.canonical_path == nil and atlas.native_pointer == nil and
  atlas.image_address == nil and atlas.bundle_address == nil and
  frame_zero.native_pointer == nil and frame_one.native_pointer == nil
print("ready=true")
print("id=" .. tostring(atlas.id))
print("key=" .. tostring(atlas.key))
print("image=" .. tostring(atlas.image))
print("bundle=" .. tostring(atlas.bundle))
print("frame_count=" .. tostring(atlas.frame_count))
print("image_width=" .. tostring(atlas.image_width))
print("image_height=" .. tostring(atlas.image_height))
print("revision=" .. tostring(atlas.revision))
print("initial_revision=" .. tostring(
  _G.__lua_sprites_acceptance_initial_revision or 0))
print("current_revision=" .. tostring(
  _G.__lua_sprites_acceptance_current_revision or 0))
print("local_only=" .. tostring(atlas.local_only))
print("schema_exact=" .. tostring(schema_exact))
print("limits_exact=" .. tostring(limits_exact))
print("frames_exact=" .. tostring(frames_exact))
print("raw_internals_absent=" .. tostring(raw_internals_absent))
"""


REPLACE_PROBE = f"""
local before = assert(sd.sprites.get({json.dumps(ATLAS_KEY)}))
local after = sd.sprites.register(
  {json.dumps(ATLAS_KEY)},
  {json.dumps(IMAGE_PATH)},
  {json.dumps(BUNDLE_PATH)})
_G.__lua_sprites_acceptance_current_revision = after.revision
print("accepted=true")
print("id_stable=" .. tostring(after.id == before.id))
print("revision_advanced=" .. tostring(after.revision > before.revision))
print("before_revision=" .. tostring(before.revision))
print("after_revision=" .. tostring(after.revision))
"""


UNREGISTER_PROBE = f"""
local first = sd.sprites.unregister({json.dumps(ATLAS_KEY)})
local second = sd.sprites.unregister({json.dumps(ATLAS_KEY)})
_G.__lua_sprites_acceptance_initial_revision = nil
_G.__lua_sprites_acceptance_current_revision = nil
print("first=" .. tostring(first))
print("second=" .. tostring(second))
print("missing=" .. tostring(
  sd.sprites.get({json.dumps(ATLAS_KEY)}) == nil))
print("list_count=" .. tostring(#sd.sprites.list()))
"""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@contextlib.contextmanager
def _materialize_fixture_assets() -> Iterator[dict[str, Any]]:
    if FIXTURE_IMAGE.exists() or FIXTURE_BUNDLE.exists():
        raise RuntimeError(
            "refusing to overwrite existing sprite fixture assets: "
            f"{FIXTURE_IMAGE}, {FIXTURE_BUNDLE}"
        )
    image_payload = base64.b64decode(
        FIXTURE_IMAGE_SOURCE.read_text(encoding="ascii").strip(),
        validate=True,
    )
    image_sha256 = _sha256(image_payload)
    if image_sha256 != FIXTURE_IMAGE_SHA256:
        raise RuntimeError(
            "encoded sprite fixture hash mismatch: "
            f"{image_sha256} != {FIXTURE_IMAGE_SHA256}"
        )
    descriptor = json.loads(
        FIXTURE_DESCRIPTOR.read_text(encoding="utf-8")
    )
    bundle_payload = build_bundle(descriptor)
    created: list[Path] = []
    try:
        for path, payload in (
            (FIXTURE_IMAGE, image_payload),
            (FIXTURE_BUNDLE, bundle_payload),
        ):
            with path.open("xb") as output:
                created.append(path)
                output.write(payload)
        yield {
            "image": IMAGE_PATH,
            "image_bytes": len(image_payload),
            "image_sha256": image_sha256,
            "bundle": BUNDLE_PATH,
            "bundle_bytes": len(bundle_payload),
            "bundle_sha256": _sha256(bundle_payload),
            "frame_count": len(descriptor["frames"]),
        }
    finally:
        for path in reversed(created):
            path.unlink(missing_ok=True)


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


def _base_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    try:
        return (
            values.get("mod_id") == ACCEPTANCE_MOD_ID
            and values.get("register_capability") == "true"
            and values.get("read_capability") == "true"
            and values.get("draw_capability") == "true"
            and values.get("authority") == ("true" if authority else "false")
            and values.get("world_scene") == "hub"
            and _int_value(values, "participant_count") == 2
            and _int_value(values, "participant_rows") == 2
            and _int_value(values, "owner_count") == 1
            and values.get("namespace_exact") == "true"
        )
    except RuntimeError:
        return False


def empty_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    return (
        _base_state_matches(values, authority=authority)
        and values.get("registered") == "false"
        and values.get("ready") == "true"
        and values.get("list_count") == "0"
    )


def registered_state_matches(
    values: dict[str, str],
    *,
    authority: bool,
) -> bool:
    try:
        revision = _int_value(values, "revision")
        return (
            _base_state_matches(values, authority=authority)
            and values.get("registered") == "true"
            and values.get("ready") == "true"
            and values.get("list_count") == "1"
            and values.get("id") == ATLAS_ID
            and values.get("key") == ATLAS_KEY
            and values.get("image") == IMAGE_PATH
            and values.get("bundle") == BUNDLE_PATH
            and _int_value(values, "frame_count") == 2
            and _int_value(values, "image_width") == 32
            and _int_value(values, "image_height") == 16
            and revision > 0
            and _int_value(values, "initial_revision") > 0
            and _int_value(values, "current_revision") == revision
            and values.get("local_only") == "true"
            and values.get("schema_exact") == "true"
            and values.get("limits_exact") == "true"
            and values.get("frames_exact") == "true"
            and values.get("raw_internals_absent") == "true"
        )
    except RuntimeError:
        return False


def registration_matches(values: dict[str, str]) -> bool:
    try:
        return (
            values.get("accepted") == "true"
            and values.get("id") == ATLAS_ID
            and values.get("key") == ATLAS_KEY
            and values.get("image") == IMAGE_PATH
            and values.get("bundle") == BUNDLE_PATH
            and _int_value(values, "frame_count") == 2
            and _int_value(values, "image_width") == 32
            and _int_value(values, "image_height") == 16
            and _int_value(values, "revision") > 0
            and values.get("local_only") == "true"
            and _int_value(values, "frame_zero_x") == 0
            and _int_value(values, "frame_zero_y") == 0
            and _int_value(values, "frame_zero_width") == 16
            and _int_value(values, "frame_zero_height") == 16
            and _int_value(values, "frame_one_x") == 16
            and _int_value(values, "frame_one_y") == 0
            and _int_value(values, "frame_one_width") == 16
            and _int_value(values, "frame_one_height") == 16
            and all(
                values.get(name) == "true"
                for name in (
                    "traversal_rejected",
                    "absolute_rejected",
                    "image_extension_rejected",
                    "bundle_extension_rejected",
                    "bad_key_rejected",
                    "extra_register_rejected",
                )
            )
        )
    except RuntimeError:
        return False


def replacement_matches(values: dict[str, str]) -> bool:
    try:
        return (
            values.get("accepted") == "true"
            and values.get("id_stable") == "true"
            and values.get("revision_advanced") == "true"
            and _int_value(values, "after_revision")
            > _int_value(values, "before_revision")
        )
    except RuntimeError:
        return False


def unregister_matches(values: dict[str, str]) -> bool:
    return (
        values.get("first") == "true"
        and values.get("second") == "false"
        and values.get("missing") == "true"
        and values.get("list_count") == "0"
    )


def atlas_descriptors_match(
    host_values: dict[str, str],
    client_values: dict[str, str],
) -> bool:
    return all(
        host_values.get(name) == client_values.get(name)
        for name in (
            "id",
            "key",
            "image",
            "bundle",
            "frame_count",
            "image_width",
            "image_height",
            "local_only",
            "frames_exact",
        )
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


def _poll_probe(
    client: tuple[str, str],
    predicate: Callable[[dict[str, str]], bool],
    *,
    timeout: float,
    description: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = run_lua_client(
            client[0],
            client[1],
            ATLAS_STATE_PROBE,
            timeout=12.0,
        )
        values = last.get("values", {})
        if (
            _failed_exec(last) is None
            and isinstance(values, dict)
            and predicate(values)
        ):
            return last
        time.sleep(0.1)
    raise RuntimeError(
        f"{description} did not converge for {client[0]}: {last}"
    )


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
    registered: bool,
    timeout: float,
    description: str,
) -> dict[str, Any]:
    predicate = registered_state_matches if registered else empty_state_matches
    return _poll_probe(
        client,
        lambda values: predicate(values, authority=authority),
        timeout=timeout,
        description=description,
    )


def run(
    clients: list[tuple[str, str]],
    *,
    launch: bool,
    timeout: float,
) -> dict[str, Any]:
    if not launch:
        raise RuntimeError("Lua sprite acceptance requires --launch-pair")
    if len(clients) != 2:
        raise RuntimeError("exactly one host and one client endpoint are required")
    host = clients[0]
    client = clients[1]
    result: dict[str, Any] = {
        "ok": False,
        "launched_pair": True,
        "host": host[0],
        "client": client[0],
    }
    launched_process_ids: list[int] = []
    with _materialize_fixture_assets() as fixture:
        result["fixture"] = fixture
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

            result["initial"] = [
                _poll_state(
                    peer,
                    authority=index == 0,
                    registered=False,
                    timeout=timeout,
                    description="empty local sprite registry",
                )
                for index, peer in enumerate((host, client))
            ]
            result["host_register"] = _require_action(
                host,
                REGISTER_PROBE,
                registration_matches,
                "host sprite registration",
            )
            result["host_registration_isolation"] = [
                _poll_state(
                    host,
                    authority=True,
                    registered=True,
                    timeout=timeout,
                    description="host local sprite atlas",
                ),
                _poll_state(
                    client,
                    authority=False,
                    registered=False,
                    timeout=timeout,
                    description="client registration isolation",
                ),
            ]
            result["client_register"] = _require_action(
                client,
                REGISTER_PROBE,
                registration_matches,
                "client sprite registration",
            )
            result["registered"] = [
                _poll_state(
                    peer,
                    authority=index == 0,
                    registered=True,
                    timeout=timeout,
                    description="local sprite atlas",
                )
                for index, peer in enumerate((host, client))
            ]
            host_values = _values(result["registered"][0])
            client_values = _values(result["registered"][1])
            if not atlas_descriptors_match(host_values, client_values):
                raise RuntimeError(
                    "host/client sprite descriptors differ: "
                    f"host={host_values} client={client_values}"
                )
            if _int_value(host_values, "revision") != _int_value(
                client_values,
                "revision",
            ):
                raise RuntimeError(
                    "fresh host/client sprite revisions differ: "
                    f"host={host_values} client={client_values}"
                )

            result["host_replace"] = _require_action(
                host,
                REPLACE_PROBE,
                replacement_matches,
                "host sprite replacement",
            )
            result["host_replacement_isolation"] = [
                _poll_state(
                    host,
                    authority=True,
                    registered=True,
                    timeout=timeout,
                    description="host replacement revision",
                ),
                _poll_state(
                    client,
                    authority=False,
                    registered=True,
                    timeout=timeout,
                    description="client retained revision",
                ),
            ]
            replacement_values = [
                _values(peer)
                for peer in result["host_replacement_isolation"]
            ]
            if _int_value(
                replacement_values[0], "revision"
            ) <= _int_value(replacement_values[1], "revision"):
                raise RuntimeError(
                    "host replacement failed local revision isolation: "
                    f"{replacement_values}"
                )

            result["client_replace"] = _require_action(
                client,
                REPLACE_PROBE,
                replacement_matches,
                "client sprite replacement",
            )
            result["replaced"] = [
                _poll_state(
                    peer,
                    authority=index == 0,
                    registered=True,
                    timeout=timeout,
                    description="independent replacement revision",
                )
                for index, peer in enumerate((host, client))
            ]
            replaced_values = [_values(peer) for peer in result["replaced"]]
            if not atlas_descriptors_match(*replaced_values):
                raise RuntimeError(
                    "host/client replacement descriptors differ: "
                    f"{replaced_values}"
                )
            if _int_value(
                replaced_values[0], "revision"
            ) != _int_value(replaced_values[1], "revision"):
                raise RuntimeError(
                    "independent replacement revisions did not converge: "
                    f"{replaced_values}"
                )

            result["host_unregister"] = _require_action(
                host,
                UNREGISTER_PROBE,
                unregister_matches,
                "host sprite unregister",
            )
            result["host_unregister_isolation"] = [
                _poll_state(
                    host,
                    authority=True,
                    registered=False,
                    timeout=timeout,
                    description="host empty sprite registry",
                ),
                _poll_state(
                    client,
                    authority=False,
                    registered=True,
                    timeout=timeout,
                    description="client retained sprite atlas",
                ),
            ]
            result["client_unregister"] = _require_action(
                client,
                UNREGISTER_PROBE,
                unregister_matches,
                "client sprite unregister",
            )
            result["released"] = [
                _poll_state(
                    peer,
                    authority=index == 0,
                    registered=False,
                    timeout=timeout,
                    description="released local sprite registry",
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
        "--confirm-mutation",
        action="store_true",
        help="confirm local temporary sprite registration on the isolated pair",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    if not args.confirm_mutation:
        result["error"] = "refusing sprite mutations without --confirm-mutation"
        return_code = 2
    elif not args.launch_pair:
        result["error"] = "Lua sprite acceptance requires --launch-pair"
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
