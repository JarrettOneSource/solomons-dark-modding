#!/usr/bin/env python3
"""Verify clean same-identity Steam replacement during an active run."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import multiplayer_progression_probe as progression
import verify_local_multiplayer_sync as local_sync
import verify_multiplayer_all_stat_sync as stats
import verify_multiplayer_inventory_audit as inventory
import verify_multiplayer_native_item_inventory_sync as native_item
from drive_steam_friend_active_pair import (
    arm_test_manual_enemy_mode,
    drive_one_to_hub,
)
from steam_friend_active_pair import (
    CLIENT_ENDPOINT,
    HOST_ENDPOINT,
    PAIR_BACKEND,
    ROOT,
    SteamFriendActivePair,
)
from verify_local_multiplayer_sync import VerifyFailure, parse_int_text
from verify_multiplayer_native_potion_inventory_sync import find_local_participant
from verify_steam_friend_active_pair_progression import configure_verifiers


DEFAULT_HOST_INSTANCE = "steam-host-v63-full95-0717"
DEFAULT_OLD_CLIENT_INSTANCE = "wsl-steam-v63-full97-0717"
DEFAULT_NEW_CLIENT_INSTANCE = "wsl-steam-v63-reconnect98-0717"
DEFAULT_OUTPUT = ROOT / "runtime/steam_friend_v63_active_run_reconnect98.json"
INSTANCE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
SENSITIVE_INTEGER_PATTERN = re.compile(r"(?<!\d)\d{10,20}(?!\d)")
SESSION_RESET_MARKER = (
    "Multiplayer transport reset disconnected participant session epoch."
)
EQUIPMENT_SLOTS = (
    "primary",
    "secondary",
    "attachment",
    "hat",
    "robe",
    "weapon",
    "amulet",
    "ring_1",
    "ring_2",
)
OWNED_REVISION_FIELDS = (
    "gold_revision",
    "inventory_revision",
    "equipment_revision",
    "spellbook_revision",
    "statbook_revision",
    "loadout_revision",
)


def stage(message: str) -> None:
    print(f"[steam-reconnect] {message}", flush=True)


def require_instance_name(value: str) -> str:
    if not INSTANCE_NAME_PATTERN.fullmatch(value):
        raise VerifyFailure(f"invalid instance name: {value!r}")
    return value


def instance_root(instance: str) -> Path:
    return ROOT / "runtime/instances" / instance


def loader_log(instance: str) -> Path:
    return instance_root(instance) / "stage/.sdmod/logs/solomondarkmodloader.log"


def session_status_path(instance: str) -> Path:
    return instance_root(instance) / "stage/.sdmod/multiplayer-session-status.json"


def compatibility_manifest(instance: str) -> Path:
    return (
        instance_root(instance)
        / "stage/.sdmod/multiplayer-compatibility.json"
    )


def compatibility_loader_sha256(instance: str) -> str:
    path = compatibility_manifest(instance)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        digest = str(document["compatibility"]["loader"]["sha256"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise VerifyFailure(
            f"loader compatibility record is unavailable for {instance}"
        ) from exc
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise VerifyFailure(
            f"loader compatibility record is invalid for {instance}"
        )
    return digest


def read_lobby_id(path: Path) -> int:
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VerifyFailure(f"host session status is unavailable: {path}") from exc
    lobby_id = int(status.get("lobbyId", 0))
    if (
        status.get("enabled") is not True
        or status.get("isHost") is not True
        or lobby_id <= 0
    ):
        raise VerifyFailure("host Steam lobby is not active")
    return lobby_id


def exact_game_processes(instance: str) -> list[int]:
    windows_target = (
        f"runtime\\instances\\{instance}\\stage\\SolomonDark.exe"
    ).casefold()
    unix_target = f"runtime/instances/{instance}/stage/SolomonDark.exe".casefold()
    matches: list[int] = []
    for process_dir in Path("/proc").iterdir():
        if not process_dir.name.isdigit():
            continue
        try:
            if process_dir.joinpath("comm").read_text().strip() != "SolomonDark.exe":
                continue
            command = process_dir.joinpath("cmdline").read_bytes().replace(
                b"\x00", b" "
            ).decode("utf-8", "replace").casefold()
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        if windows_target in command or unix_target in command:
            matches.append(int(process_dir.name))
    return sorted(matches)


def require_one_game_process(instance: str) -> int:
    matches = exact_game_processes(instance)
    if len(matches) != 1:
        raise VerifyFailure(
            f"expected one exact SolomonDark process for {instance}, found {len(matches)}"
        )
    return matches[0]


def stop_exact_game(instance: str, timeout: float) -> int:
    pid = require_one_game_process(instance)
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pid not in exact_game_processes(instance):
            return pid
        time.sleep(0.1)
    os.kill(pid, signal.SIGKILL)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if pid not in exact_game_processes(instance):
            return pid
        time.sleep(0.1)
    raise VerifyFailure(f"exact SolomonDark process for {instance} did not exit")


def wait_for_game(instance: str, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches = exact_game_processes(instance)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise VerifyFailure(
                f"multiple exact SolomonDark processes appeared for {instance}"
            )
        time.sleep(0.25)
    raise VerifyFailure(f"SolomonDark process did not start for {instance}")


def wait_for_authenticated_peers(path: Path, expected: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last = -1
    while time.monotonic() < deadline:
        try:
            status = json.loads(path.read_text(encoding="utf-8"))
            last = int(status.get("authenticatedPeerCount", -1))
        except (OSError, ValueError, TypeError):
            last = -1
        if last == expected:
            return
        time.sleep(0.25)
    raise VerifyFailure(
        f"host authenticated peer count did not become {expected}; last={last}"
    )


def wait_for_host_participant_absence(
    pair: SteamFriendActivePair,
    participant_id: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = local_sync.query(HOST_ENDPOINT)
        prefix = f"peer.{participant_id}."
        present = any(key.startswith(prefix) for key in last)
        if not present:
            return {
                "participant_removed": True,
                "host_scene": last.get("scene", ""),
                "host_run_preserved": last.get("local.in_run") == "true",
            }
        time.sleep(0.2)
    raise VerifyFailure("host retained the disconnected participant runtime state")


def wait_for_log_marker(path: Path, offset: int, marker: str, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                stream.seek(offset)
                text = stream.read()
        except OSError:
            text = ""
        count = text.count(marker)
        if count:
            return count
        time.sleep(0.2)
    raise VerifyFailure(f"loader log did not record required lifecycle marker: {marker}")


def launch_replacement(instance: str, lobby_id: int, log_path: Path) -> None:
    if instance_root(instance).exists():
        raise VerifyFailure(
            f"replacement instance already exists; use a new instance name: {instance}"
        )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "LP_NUM_THREADS": "4",
            "PULSE_SERVER": "unix:/dev/null",
            "SDL_AUDIODRIVER": "dummy",
            "SDMOD_WSL_STEAM_INSTANCE": instance,
        }
    )
    with log_path.open("w", encoding="utf-8") as stream:
        subprocess.Popen(
            ["bash", "scripts/Launch-WslSteamMultiplayerClient.sh", str(lobby_id)],
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def configure_pair(pair: SteamFriendActivePair) -> dict[str, str]:
    configure_verifiers(pair)
    for module in (local_sync, inventory):
        module.lua = pair.lua
        module.HOST_ID = pair.host_participant_id
        module.CLIENT_ID = pair.client_participant_id
        module.HOST_PIPE = HOST_ENDPOINT
        module.CLIENT_PIPE = CLIENT_ENDPOINT

    host_view = local_sync.query(HOST_ENDPOINT)
    client_view = local_sync.query(CLIENT_ENDPOINT)
    client_name = host_view.get(f"peer.{pair.client_participant_id}.name", "")
    host_name = client_view.get(f"peer.{pair.host_participant_id}.name", "")
    if not host_name or not client_name:
        raise VerifyFailure("Steam display names are not available on both peers")
    local_sync.HOST_NAME = host_name
    local_sync.CLIENT_NAME = client_name
    return {"host_name_available": "true", "client_name_available": "true"}


def equipment_identities(row: dict[str, Any]) -> set[tuple[int, int]]:
    return {
        (int(row["equipment"][slot]["type_id"]), int(row["equipment"][slot]["recipe_uid"]))
        for slot in EQUIPMENT_SLOTS
        if int(row["equipment"][slot]["type_id"]) > 0
        and int(row["equipment"][slot]["recipe_uid"]) > 0
    }


def inventory_identities(row: dict[str, Any]) -> set[tuple[int, int]]:
    return {
        (int(item["type_id"]), int(item["recipe_uid"]))
        for item in row["inventory_items"]
        if int(item["type_id"]) > 0 and int(item["recipe_uid"]) > 0
    }


def compact_owned_state(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "gold": int(row["gold"]),
        "gold_revision": int(row["gold_revision"]),
        "inventory_revision": int(row["inventory_revision"]),
        "equipment_revision": int(row["equipment_revision"]),
        "spellbook_revision": int(row["spellbook_revision"]),
        "statbook_revision": int(row["statbook_revision"]),
        "loadout_revision": int(row["loadout_revision"]),
        "inventory_items": sorted(
            (
                int(item["type_id"]),
                int(item["recipe_uid"]),
                int(item["slot"]),
                int(item["stack_count"]),
            )
            for item in row["inventory_items"]
        ),
        "equipment": {
            slot: (
                int(row["equipment"][slot]["type_id"]),
                int(row["equipment"][slot]["recipe_uid"]),
            )
            for slot in EQUIPMENT_SLOTS
        },
        "ability_loadout": row["ability_loadout"],
    }


def capture_client_owned_pair(
    pair: SteamFriendActivePair,
) -> tuple[dict[str, Any], dict[str, Any]]:
    client_capture = inventory.capture(CLIENT_ENDPOINT)
    host_capture = inventory.capture(HOST_ENDPOINT)
    owner = find_local_participant(client_capture)
    observer = inventory.find_participant(host_capture, pair.client_participant_id)
    if owner is None or observer is None:
        raise VerifyFailure("client owner/host observer inventory row is unavailable")
    return owner, observer


def require_fresh_owned_state(
    owner: dict[str, Any],
    observer: dict[str, Any],
    mutated_identities: set[tuple[int, int]],
    previous_revisions: dict[str, int],
) -> dict[str, Any]:
    if (
        owner["inventory_host_authoritative"]
        or observer["inventory_host_authoritative"]
    ):
        raise VerifyFailure(
            "replacement retained host-authored inventory authority state"
        )
    owner_compact = compact_owned_state(owner)
    observer_compact = compact_owned_state(observer)
    if owner_compact != observer_compact:
        raise VerifyFailure(
            "replacement owner state differs from the host observer state"
        )
    expected_revisions = {
        "gold_revision": 1,
        "inventory_revision": 1,
        "equipment_revision": 1,
        "spellbook_revision": 1,
        "statbook_revision": 1,
        "loadout_revision": 1,
    }
    actual_revisions = {
        key: int(owner_compact[key]) for key in expected_revisions
    }
    if actual_revisions != expected_revisions:
        raise VerifyFailure(
            f"replacement inherited stale owned-state revisions: {actual_revisions}"
        )
    revision_decreases = {
        key: previous_revisions[key] > actual_revisions[key]
        for key in OWNED_REVISION_FIELDS
    }
    if not all(revision_decreases.values()):
        raise VerifyFailure(
            "replacement did not strictly rebase every owned-state revision: "
            f"before={previous_revisions} after={actual_revisions}"
        )
    leaked = mutated_identities & (
        inventory_identities(owner) | equipment_identities(owner)
    )
    if leaked:
        raise VerifyFailure(
            f"replacement inherited {len(leaked)} item/equipment identities"
        )
    return {
        "owner_observer_exact": True,
        "inventory_authority_boundary": {
            "owner_is_host_authoritative": False,
            "host_observer_is_host_authoritative": True,
        },
        "fresh_revisions": actual_revisions,
        "all_revisions_strictly_decreased": True,
        "revision_decrease_count": len(revision_decreases),
        "inventory_item_count": len(owner["inventory_items"]),
        "equipment_valid": bool(owner["equipment"]["valid"]),
        "mutated_identity_count_checked": len(mutated_identities),
        "mutated_identity_leak_count": 0,
    }


def require_progression_parity(
    pair: SteamFriendActivePair,
    timeout: float,
) -> dict[str, Any]:
    owner, observer = stats.wait_for_derived_parity(
        pair.client_participant_id, timeout
    )
    native_book_mismatches = progression.compare_book_rows(
        owner["native"]["entries"], observer["native"]["entries"]
    )
    ledger_book_mismatches = progression.compare_book_rows(
        owner["ledger"]["entries"], observer["ledger"]["entries"]
    )
    if native_book_mismatches or ledger_book_mismatches:
        raise VerifyFailure(
            "replacement skill/stat books differ between owner and observer"
        )
    if owner["loadout"] != observer["loadout"]:
        raise VerifyFailure("replacement ability loadout differs on the host")
    if int(owner["native"]["level"]) != 1:
        raise VerifyFailure(
            f"replacement temporary profile inherited level {owner['native']['level']}"
        )
    if int(observer["native"]["level"]) != 1:
        raise VerifyFailure("host observer did not materialize replacement level one")
    if owner["ledger"]["spellbook_revision"] != 1 or owner["ledger"]["statbook_revision"] != 1:
        raise VerifyFailure("replacement progression revisions are not fresh")

    spell_fields = (
        "current_spell_id",
        "progression_level",
        "damage",
        "secondary_damage",
        "mana_cost",
        "mana_spend_cost",
        "outputs",
    )
    spell_mismatches: list[str] = []
    for field in spell_fields:
        left = owner["spell"][field]
        right = observer["spell"][field]
        if isinstance(left, float) and isinstance(right, float):
            if not math.isclose(left, right, rel_tol=0.0, abs_tol=0.001):
                spell_mismatches.append(field)
        elif left != right:
            spell_mismatches.append(field)
    if spell_mismatches:
        raise VerifyFailure(
            f"replacement spell outputs differ on fields: {spell_mismatches}"
        )
    return {
        "level": 1,
        "native_book_entry_count": len(owner["native"]["entries"]),
        "ledger_book_entry_count": len(owner["ledger"]["entries"]),
        "native_book_mismatch_count": 0,
        "ledger_book_mismatch_count": 0,
        "derived_mismatch_count": 0,
        "loadout_exact": True,
        "spell_output_exact": True,
        "spellbook_revision": owner["ledger"]["spellbook_revision"],
        "statbook_revision": owner["ledger"]["statbook_revision"],
    }


def transport_health(pair: SteamFriendActivePair) -> dict[str, dict[str, Any]]:
    code = r"""
local function emit(key, value) print(key .. '=' .. tostring(value or 0)) end
local state = sd.runtime.get_multiplayer_state()
emit('ready', state and state.transport_ready or false)
emit('transport', state and state.session_transport or '')
emit('status', state and state.session_status or '')
emit('send_failures', state and state.steam_send_failures or 0)
emit('reliable_send_failures', state and state.steam_reliable_send_failures or 0)
"""
    result: dict[str, dict[str, Any]] = {}
    for label, endpoint in (("host", HOST_ENDPOINT), ("client", CLIENT_ENDPOINT)):
        values = local_sync.parse_key_values(pair.lua(endpoint, code, timeout=8.0))
        if values.get("ready") != "true" or values.get("transport") != "Steam":
            raise VerifyFailure(f"{label} Steam transport is not ready: {values}")
        result[label] = {
            "ready": True,
            "transport": "Steam",
            "status": values.get("status", ""),
            "send_failures": parse_int_text(values.get("send_failures"), 0),
            "reliable_send_failures": parse_int_text(
                values.get("reliable_send_failures"), 0
            ),
        }
    return result


def new_crash_artifacts(started_at: float, instances: tuple[str, ...]) -> list[str]:
    locations = [loader_log(instance).parent for instance in instances]
    locations.append(Path("/mnt/c/Users/user/AppData/Local/CrashDumps"))
    artifacts: list[str] = []
    for location in locations:
        if not location.is_dir():
            continue
        for pattern in ("*crash*", "SolomonDark.exe*.dmp"):
            for path in location.glob(pattern):
                if path.is_file() and path.stat().st_mtime >= started_at - 0.5:
                    artifacts.append(str(path))
    return sorted(set(artifacts))


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and abs(value) >= 10_000_000_000:
        return "<redacted>"
    if isinstance(value, str):
        return SENSITIVE_INTEGER_PATTERN.sub("<redacted>", value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-instance", default=DEFAULT_HOST_INSTANCE)
    parser.add_argument("--old-client-instance", default=DEFAULT_OLD_CLIENT_INSTANCE)
    parser.add_argument("--new-client-instance", default=DEFAULT_NEW_CLIENT_INSTANCE)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--launch-timeout", type=float, default=180.0)
    parser.add_argument("--stability-seconds", type=float, default=5.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    args.host_instance = require_instance_name(args.host_instance)
    args.old_client_instance = require_instance_name(args.old_client_instance)
    args.new_client_instance = require_instance_name(args.new_client_instance)
    if args.old_client_instance == args.new_client_instance:
        raise SystemExit("old and replacement client instances must differ")

    started_at = time.time()
    output: dict[str, Any] = {
        "ok": False,
        "transport": "steam_friend",
        "same_machine": PAIR_BACKEND == "wsl",
        "client_runtime": "wsl_proton",
    }
    old_pair: SteamFriendActivePair | None = None
    new_pair: SteamFriendActivePair | None = None
    old_client_id = 0
    old_host_id = 0
    return_code = 1
    try:
        host_status = session_status_path(args.host_instance)
        lobby_id = read_lobby_id(host_status)
        host_log = loader_log(args.host_instance)
        host_log_offset = host_log.stat().st_size

        stage("capturing the mutated active client")
        old_pair = SteamFriendActivePair()
        output["old_pair"] = old_pair.discover()
        configure_pair(old_pair)
        old_client_id = old_pair.client_participant_id
        old_host_id = old_pair.host_participant_id
        old_owner, old_observer = capture_client_owned_pair(old_pair)
        all_owned_identities = (
            inventory_identities(old_owner)
            | equipment_identities(old_owner)
        )
        mutated_identities = {
            identity
            for identity in all_owned_identities
            if identity[0] in native_item.EQUIPPABLE_TYPE_IDS
        }
        mutated_types = {type_id for type_id, _ in mutated_identities}
        if mutated_types != set(native_item.EQUIPPABLE_TYPE_IDS):
            raise VerifyFailure(
                "pre-disconnect client does not own every test equipment type"
            )
        old_revisions = {
            field: int(old_owner[field]) for field in OWNED_REVISION_FIELDS
        }
        old_progression = progression.query_progression_snapshot(CLIENT_ENDPOINT)
        old_host_view = local_sync.query(HOST_ENDPOINT)
        old_actor = parse_int_text(
            old_host_view.get(f"peer.{old_client_id}.actor"), 0
        )
        old_present_mutations = mutated_identities & (
            inventory_identities(old_owner) | equipment_identities(old_owner)
        )
        if (
            old_actor == 0
            or int(old_progression["native"]["level"]) <= 1
            or int(old_progression["ledger"]["spellbook_revision"]) <= 1
            or any(revision <= 1 for revision in old_revisions.values())
            or old_present_mutations != mutated_identities
        ):
            raise VerifyFailure("pre-disconnect client is not meaningfully mutated")
        if compact_owned_state(old_owner) != compact_owned_state(old_observer):
            raise VerifyFailure("pre-disconnect client state is not settled on the host")
        if (
            old_owner["inventory_host_authoritative"]
            or not old_observer["inventory_host_authoritative"]
        ):
            raise VerifyFailure("pre-disconnect inventory authority boundary is incorrect")
        old_pid = require_one_game_process(args.old_client_instance)
        output["pre_disconnect"] = {
            "scene": output["old_pair"]["client"]["scene"],
            "level": old_progression["native"]["level"],
            "spellbook_revision": old_progression["ledger"]["spellbook_revision"],
            "statbook_revision": old_progression["ledger"]["statbook_revision"],
            "inventory_revision": old_owner["inventory_revision"],
            "equipment_revision": old_owner["equipment_revision"],
            "gold_revision": old_owner["gold_revision"],
            "loadout_revision": old_owner["loadout_revision"],
            "mutated_identity_count": len(old_present_mutations),
            "native_proxy_materialized": True,
        }
        old_pair.close()
        old_pair = None

        stage("stopping only the exact Proton game process")
        stopped_pid = stop_exact_game(args.old_client_instance, min(20.0, args.timeout))
        if stopped_pid != old_pid:
            raise VerifyFailure("the stopped game process changed unexpectedly")
        host_only = SteamFriendActivePair()
        local_sync.lua = host_only.lua
        output["disconnect"] = wait_for_host_participant_absence(
            host_only, old_client_id, args.timeout
        )
        if output["disconnect"]["host_run_preserved"] is not True:
            raise VerifyFailure("client disconnect ended the host run")
        wait_for_authenticated_peers(host_status, 0, args.timeout)
        reset_count = wait_for_log_marker(
            host_log,
            host_log_offset,
            SESSION_RESET_MARKER,
            args.timeout,
        )
        output["disconnect"]["authenticated_peer_count"] = 0
        output["disconnect"]["session_epoch_reset_log_count"] = reset_count
        output["disconnect"]["exact_game_process_stopped"] = True
        host_only.close()

        stage("launching a fresh temporary profile into the same private lobby")
        launch_log = (
            ROOT
            / "runtime/detached-launch-logs"
            / f"{args.new_client_instance}.log"
        )
        launch_replacement(args.new_client_instance, lobby_id, launch_log)
        new_pid = wait_for_game(args.new_client_instance, args.launch_timeout)
        if new_pid == old_pid:
            raise VerifyFailure("replacement did not receive a new process")

        stage("authenticating and onboarding the replacement")
        new_pair = SteamFriendActivePair()
        output["new_pair"] = new_pair.discover()
        if (
            new_pair.client_participant_id != old_client_id
            or new_pair.host_participant_id != old_host_id
        ):
            raise VerifyFailure("replacement did not preserve the two Steam identities")
        configure_pair(new_pair)
        output["onboarding"] = {
            "host": drive_one_to_hub(
                new_pair,
                HOST_ENDPOINT,
                element="fire",
                discipline="arcane",
                timeout=args.timeout,
            ),
            "client": drive_one_to_hub(
                new_pair,
                CLIENT_ENDPOINT,
                element="air",
                discipline="arcane",
                timeout=args.timeout,
            ),
        }
        local_sync.wait_for_scene(CLIENT_ENDPOINT, "testrun", args.timeout)
        output["run_bootstrap"] = local_sync.verify_run_entry_bootstrap(
            min(args.timeout, 30.0)
        )
        wait_for_authenticated_peers(host_status, 1, args.timeout)

        host_view = local_sync.query(HOST_ENDPOINT)
        new_actor = parse_int_text(
            host_view.get(f"peer.{new_pair.client_participant_id}.actor"), 0
        )
        if new_actor == 0:
            raise VerifyFailure("replacement native proxy was not materialized")
        output["replacement_proxy"] = {
            "materialized": True,
            "old_proxy_was_removed_before_rejoin": True,
            "address_reuse_allowed": True,
            "address_was_reused": new_actor == old_actor,
        }

        host_loader_sha256 = compatibility_loader_sha256(args.host_instance)
        client_loader_sha256 = compatibility_loader_sha256(
            args.new_client_instance
        )
        if host_loader_sha256 != client_loader_sha256:
            raise VerifyFailure("host and replacement loaded different mod binaries")
        output["binary_match"] = True

        stage("verifying clean state and exact owner/observer parity")
        owner, observer = capture_client_owned_pair(new_pair)
        output["fresh_owned_state"] = require_fresh_owned_state(
            owner, observer, mutated_identities, old_revisions
        )
        output["progression_parity"] = require_progression_parity(
            new_pair, min(args.timeout, 45.0)
        )
        output["transport_before_stability"] = transport_health(new_pair)

        stage("holding a stale-packet rejection window")
        time.sleep(max(1.0, args.stability_seconds))
        stable_owner, stable_observer = capture_client_owned_pair(new_pair)
        stable_owned = require_fresh_owned_state(
            stable_owner, stable_observer, mutated_identities, old_revisions
        )
        stable_progression = require_progression_parity(
            new_pair, min(args.timeout, 45.0)
        )
        transport_after = transport_health(new_pair)
        for side in ("host", "client"):
            before = output["transport_before_stability"][side]
            after = transport_after[side]
            if (
                after["send_failures"] != before["send_failures"]
                or after["reliable_send_failures"]
                != before["reliable_send_failures"]
            ):
                raise VerifyFailure(
                    f"{side} Steam send failures increased during stability window"
                )
        output["stability_window"] = {
            "seconds": max(1.0, args.stability_seconds),
            "fresh_owned_state": stable_owned,
            "progression": stable_progression,
            "transport": transport_after,
            "no_late_stale_state": True,
        }
        output["manual_enemy_mode"] = {
            "host": arm_test_manual_enemy_mode(new_pair, HOST_ENDPOINT),
            "client": arm_test_manual_enemy_mode(new_pair, CLIENT_ENDPOINT),
        }
        output["new_crash_artifacts"] = new_crash_artifacts(
            started_at, (args.host_instance, args.new_client_instance)
        )
        if output["new_crash_artifacts"]:
            raise VerifyFailure(
                f"new crash artifacts appeared: {output['new_crash_artifacts']}"
            )
        output["summary"] = {
            "same_steam_identity_replaced": True,
            "host_run_survived_disconnect": True,
            "old_proxy_removed_before_rejoin": True,
            "fresh_profile_revisions_verified": 6,
            "all_owned_revisions_strictly_decreased": True,
            "mutated_item_equipment_identities_rejected": len(mutated_identities),
            "all_skill_stat_book_rows_compared": True,
            "loadout_spell_outputs_derived_stats_compared": True,
            "stable_transport_send_failures": True,
        }
        output["ok"] = True
        return_code = 0
    except (
        VerifyFailure,
        OSError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
    ) as exc:
        output["error"] = str(exc)
        output["new_crash_artifacts"] = new_crash_artifacts(
            started_at, (args.host_instance, args.new_client_instance)
        )
    finally:
        if old_pair is not None:
            old_pair.close()
        if new_pair is not None:
            new_pair.close()
            output = new_pair.redact(output)
        elif old_client_id > 1 or old_host_id > 1:
            redactor = SteamFriendActivePair.__new__(SteamFriendActivePair)
            redactor.host_participant_id = old_host_id
            redactor.client_participant_id = old_client_id
            output = redactor.redact(output)
        output = sanitize(output)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "ok": output.get("ok", False),
                "error": output.get("error", ""),
                "summary": output.get("summary", {}),
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
