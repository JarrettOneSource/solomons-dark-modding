#!/usr/bin/env python3
"""Record stock loot-selector, magnet, and multiplayer-credit goldens.

The recorder owns one isolated ``loot-*`` local pair on UDP 52391/52392.  It
traces retail ``NativeRng::Integer`` at every enemy death, replays both the
actor-seeded private selector stream and the active shared stream, and refuses
to publish a fixture unless the captured entry-state words and final states
match bit for bit.  Provenance is derived from this checkout and the binaries
actually staged by the launcher; no provenance value is accepted from CLI.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from owned_process_ledger import OWNED_GAME_PROCESSES  # noqa: E402
import verify_local_multiplayer_sync as local_sync  # noqa: E402
import verify_multiplayer_primary_kill_stress as primary  # noqa: E402


POWERSHELL = Path(
    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
)
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
LAUNCHER = ROOT / "dist/launcher/SolomonDarkModLauncher.exe"
LOADER = ROOT / "dist/launcher/SolomonDarkModLoader.dll"
RUNTIME_ROOT = ROOT / "runtime/lootre"
DEFAULT_OUTPUT = ROOT / "tests/fixtures/webgame/loot-goldens.json"
RAW_OUTPUT = RUNTIME_ROOT / "loot-live-raw.json"
HUB_GOLDEN = ROOT / "tests/fixtures/webgame/hub-economy-goldens.json"

INSTANCE_PREFIX = "loot-g7-capture"
SMOKE_INSTANCE_PREFIX = "loot-g7-smoke"
HOST_PORT = 52391
CLIENT_PORT = 52392
ALLOWED_PORTS = tuple(range(52391, 52399))
HOST_PIPE = f"SolomonDarkModLoader_LuaExec_{INSTANCE_PREFIX}-host"
CLIENT_PIPE = f"SolomonDarkModLoader_LuaExec_{INSTANCE_PREFIX}-client"
TRACE_NAME = "lootre_native_integer"

RNG_INTEGER = 0x00401170
ACTIVE_RNG_POINTER = 0x00818B08
APP_GLOBAL = 0x00B401A8
GAMEPLAY_GLOBAL = 0x0081C264
ACTIVE_PLAYER_GLOBAL = 0x0081C6E0
RNG_MASK = 0x3FFFFFFF
RNG_WORD_COUNT = 55
RNG_DIVISOR = 100000
ACTOR_SEED_BOUND = 10_000_000

REWARD_TYPES = {2011: "orb", 2012: "gold", 2013: "sack", 2038: "bonus"}
ENEMY_FAMILIES = (
    {"family": "Skeleton", "type_id": 1001, "kills": 34},
    {"family": "Zombie", "type_id": 1006, "kills": 33},
    {"family": "Wraith", "type_id": 1007, "kills": 33},
)

ACTOR_SEED_UPDATES = {
    "Skeleton": [
        {
            "function": "0x00473980",
            "write_site": "0x004739D1",
            "rule": "slot-0 action scheduling replaces actor+0x1C0 with active-shared Integer(10000000, false)",
        },
    ],
    "Zombie": [],
    "Wraith": [],
}

DIRECT_ROLL_LABELS = {
    0x0047C1F0: "quick_health_gate_1_of_2",
    0x0047C206: "quick_health_gate_1_of_10",
    0x0047C364: "key_eligibility",
    0x0047C442: "orb_eligibility",
    0x0047C536: "gold_eligibility",
    0x0047C629: "item_eligibility",
    0x0047C6CD: "potion_eligibility",
    0x0047C880: "powerup_eligibility",
    0x0047C8B9: "candidate_choice",
    0x0047CA4C: "potion_subtype",
}
PRIVATE_DIRECT_RETURNS = {
    address
    for address, label in DIRECT_ROLL_LABELS.items()
    if label not in {
        "quick_health_gate_1_of_2",
        "quick_health_gate_1_of_10",
        "potion_subtype",
    }
}
CATEGORY_ORDER = ("key", "orb", "gold", "item", "potion", "powerup")

KILL_X = 2950.0
KILL_Y = 1750.0
HOST_PARK = (650.0, 1750.0)
CLIENT_PARK = (1800.0, 1750.0)
MAGNET_ANCHOR = (1500.0, 1750.0)


class CaptureFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CaptureFailure(message)


def as_int(value: object, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(str(value), 0)
    except ValueError:
        return int(float(str(value)))


def as_float(value: object, default: float = math.nan) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def signed_u32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def git_output(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30.0,
        check=False,
    )
    require(
        completed.returncode == 0,
        f"BROKEN: git {' '.join(arguments)} failed: {completed.stdout}",
    )
    return completed.stdout.strip()


def windows_path(path: Path) -> str:
    return local_sync.path_for_powershell(path)


def windows_sha256(path: Path) -> str:
    require(path.is_file(), f"BROKEN: file to hash is absent: {path}")
    literal = windows_path(path).replace("'", "''")
    completed = subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"(Get-FileHash -LiteralPath '{literal}' -Algorithm SHA256).Hash.ToLowerInvariant()",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30.0,
        check=False,
    )
    digest = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
    require(
        completed.returncode == 0 and len(digest) == 64,
        f"BROKEN: Windows SHA-256 failed for {path}: {completed.stdout}",
    )
    return digest


def snapshot_owned_target_processes() -> list[dict[str, Any]]:
    root = windows_path(RUNTIME_ROOT / "instances").replace("'", "''")
    script = f"""
$root = [System.IO.Path]::GetFullPath('{root}\\')
$rows = @(
  Get-CimInstance Win32_Process -Filter "Name = 'SolomonDark.exe'" |
    Where-Object {{
      $_.ExecutablePath -and
      [System.IO.Path]::GetFullPath($_.ExecutablePath).StartsWith(
        $root, [System.StringComparison]::OrdinalIgnoreCase)
    }} |
    Select-Object @{{n='process_id';e={{[int]$_.ProcessId}}}},
                  @{{n='executable_path';e={{[string]$_.ExecutablePath}}}}
)
if ($rows.Count -eq 0) {{ '[]' }} else {{ $rows | ConvertTo-Json -Compress }}
"""
    completed = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30.0,
        check=False,
    )
    require(completed.returncode == 0, f"BROKEN: process snapshot failed: {completed.stdout}")
    value = json.loads(completed.stdout.strip().lstrip("\ufeff") or "[]")
    if isinstance(value, dict):
        return [value]
    require(isinstance(value, list), f"BROKEN: process snapshot is not a list: {value!r}")
    return value


def assert_reserved_ports_free() -> None:
    ports = ",".join(str(port) for port in ALLOWED_PORTS)
    script = f"""
$ports = @({ports})
$rows = @(Get-NetUDPEndpoint -ErrorAction SilentlyContinue |
  Where-Object {{ $ports -contains $_.LocalPort }} |
  Select-Object LocalAddress,LocalPort,OwningProcess)
if ($rows.Count -eq 0) {{ '[]' }} else {{ $rows | ConvertTo-Json -Compress }}
"""
    completed = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30.0,
        check=False,
    )
    require(completed.returncode == 0, f"BROKEN: UDP port probe failed: {completed.stdout}")
    rows = json.loads(completed.stdout.strip().lstrip("\ufeff") or "[]")
    require(rows == [], f"BROKEN: reserved loot UDP ports are already occupied: {rows}")


def configure_helper_pipes(instance_prefix: str) -> tuple[str, str]:
    host_pipe = f"SolomonDarkModLoader_LuaExec_{instance_prefix}-host"
    client_pipe = f"SolomonDarkModLoader_LuaExec_{instance_prefix}-client"
    local_sync.HOST_PIPE = host_pipe
    local_sync.CLIENT_PIPE = client_pipe
    primary.HOST_PIPE = host_pipe
    primary.CLIENT_PIPE = client_pipe
    return host_pipe, client_pipe


def assert_pair_runnable(process_ids: tuple[int, int]) -> None:
    inspections = OWNED_GAME_PROCESSES.inspect()
    ours = [row for row in inspections if as_int(row.get("processId")) in process_ids]
    require(
        len(ours) == 2,
        f"BROKEN: an owned loot process disappeared: expected={process_ids} observed={inspections}",
    )
    bad = [row for row in ours if row.get("alreadyExited") or not row.get("pathMatched")]
    require(not bad, f"BROKEN: an owned loot process is not runnable at its staged path: {bad}")


def wait_until(
    description: str,
    producer: Callable[[], Any],
    predicate: Callable[[Any], bool],
    *,
    process_ids: tuple[int, int],
    timeout: float,
    interval: float = 0.1,
) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    last_busy = ""
    while time.monotonic() < deadline:
        assert_pair_runnable(process_ids)
        try:
            last = producer()
            if predicate(last):
                return last
            last_busy = repr(last)
        except (local_sync.VerifyFailure, subprocess.TimeoutExpired) as exc:
            message = str(exc)
            if "pipe" not in message.lower() and "busy" not in message.lower():
                raise CaptureFailure(f"BROKEN: {description} probe failed: {message}") from exc
            last_busy = message
        time.sleep(interval)
    raise CaptureFailure(f"BUSY_TIMEOUT: {description}; last={last_busy}")


def values(pipe_name: str, code: str, timeout: float = 15.0) -> dict[str, str]:
    return local_sync.parse_key_values(local_sync.lua(pipe_name, code, timeout=timeout))


class NativeRng:
    def __init__(
        self,
        *,
        index_a: int,
        index_b: int,
        state_words: list[int],
        divisor: int = RNG_DIVISOR,
    ) -> None:
        require(len(state_words) == RNG_WORD_COUNT, "RNG replay did not receive all 55 state words")
        self.index_a = index_a
        self.index_b = index_b
        self.state_words = [int(word) & RNG_MASK for word in state_words]
        self.divisor = divisor

    @classmethod
    def seeded(cls, seed: int) -> "NativeRng":
        words = [seed & RNG_MASK, 1]
        while len(words) < RNG_WORD_COUNT:
            words.append((words[-1] + words[-2]) & RNG_MASK)
        return cls(index_a=0, index_b=31, state_words=words)

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "NativeRng":
        return cls(
            index_a=int(snapshot["index_a"]),
            index_b=int(snapshot["index_b"]),
            state_words=list(snapshot["state_words"]),
            divisor=int(snapshot["divisor"]),
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "index_a": self.index_a,
            "index_b": self.index_b,
            "divisor": self.divisor,
            "state_words": list(self.state_words),
        }

    def entry_prefix(self) -> list[int]:
        return [self.index_a, self.index_b, *self.state_words[:22]]

    def stream_word(self) -> int:
        value = (self.state_words[self.index_a] + self.state_words[self.index_b]) & RNG_MASK
        self.state_words[self.index_a] = value
        self.index_a = (self.index_a + 1) % RNG_WORD_COUNT
        self.index_b = (self.index_b + 1) % RNG_WORD_COUNT
        return value

    def bounded_entry(self, requested_bound: int) -> int:
        """Replay the one recurrence advance made at this traced entry.

        A signed ``Integer`` request recursively re-enters 0x00401170 for its
        sign bit, so that second advance appears as its own trace hit.  Signed
        ``Float`` instead inlines the sign advance in 0x00401310; replay_hits
        inserts that unhooked but structurally proven advance separately.
        """
        if requested_bound == 0:
            return 0
        bound = abs(requested_bound)
        power = 2
        while power < bound:
            power <<= 1
        return ((self.stream_word() >> 6) & (power - 1)) % bound


def state_sha256(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parse_state(parts: list[str], label: str) -> dict[str, Any]:
    require(len(parts) == 5, f"{label} RNG state row has the wrong field count: {parts}")
    words = [as_int(word) for word in parts[4].split(",") if word != ""]
    require(len(words) == RNG_WORD_COUNT, f"{label} did not expose all 55 RNG words")
    state = {
        "stream_address": as_int(parts[0]),
        "index_a": as_int(parts[1]),
        "index_b": as_int(parts[2]),
        "divisor": as_int(parts[3]),
        "state_words": words,
    }
    require(state["stream_address"] != 0, f"{label} stream address is null")
    require(state["divisor"] == RNG_DIVISOR, f"{label} divisor is not 100000")
    return state


def compact_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "index_a": snapshot["index_a"],
        "index_b": snapshot["index_b"],
        "divisor": snapshot["divisor"],
        "state_words": snapshot["state_words"],
    }


def parse_kill_capture(output: str) -> dict[str, Any]:
    metadata: dict[str, str] = {}
    states: dict[str, dict[str, Any]] = {}
    hits: list[dict[str, Any]] = []
    rewards: list[dict[str, Any]] = []
    for line in output.splitlines():
        if line.startswith("M|"):
            parts = line.split("|", 2)
            if len(parts) == 3:
                metadata[parts[1]] = parts[2]
        elif line.startswith("Q|"):
            parts = line.split("|", 6)
            require(len(parts) == 7, f"RNG state line is malformed: {line}")
            states[parts[1]] = parse_state(parts[2:], parts[1])
        elif line.startswith("H|"):
            parts = line.split("|", 9)
            require(len(parts) == 10, f"native Integer trace line is malformed: {line}")
            words = [as_int(word) for word in parts[9].split(",") if word != ""]
            valid = parts[8] == "true"
            require(not valid or len(words) == 24, f"trace hit lost its 24-word ECX snapshot: {line}")
            hits.append(
                {
                    "ordinal": as_int(parts[1]),
                    "thread_id": as_int(parts[2]),
                    "ecx": as_int(parts[3]),
                    "bound_u32": as_int(parts[4]),
                    "bound": signed_u32(as_int(parts[4])),
                    "arg1": as_int(parts[5]),
                    "return_address": f"0x{as_int(parts[6]):08X}",
                    "return_address_int": as_int(parts[6]),
                    "entry_words_valid": valid,
                    "entry_words": words,
                }
            )
        elif line.startswith("R|"):
            parts = line.split("|")
            require(len(parts) == 18, f"reward actor line is malformed: {line}")
            type_id = as_int(parts[1])
            rewards.append(
                {
                    "type_id": type_id,
                    "family": REWARD_TYPES.get(type_id, "unknown"),
                    "actor_address": as_int(parts[2]),
                    "x": as_float(parts[3]),
                    "y": as_float(parts[4]),
                    "field_0x13c_u8": as_int(parts[5]),
                    "field_0x13c_i32": as_int(parts[6]),
                    "field_0x140_f32": as_float(parts[7]),
                    "field_0x140_i32": as_int(parts[8]),
                    "field_0x144_f32": as_float(parts[9]),
                    "field_0x144_i32": as_int(parts[10]),
                    "field_0x148_u32": as_int(parts[11]),
                    "field_0x14c_f32": as_float(parts[12]),
                    "field_0x14c_i32": as_int(parts[13]),
                    "field_0x154_f32": as_float(parts[14]),
                    "field_0x154_i32": as_int(parts[15]),
                    "held_item_type_id": as_int(parts[16]),
                    "held_item_subtype": as_int(parts[17], -1),
                }
            )
    require(metadata.get("triggered") == "true", f"native enemy death did not run: {metadata}")
    require("shared_before" in states and "shared_after" in states, "kill trace lost shared stream boundary states")
    require(hits, "kill trace captured no NativeRng::Integer calls")
    require(len(hits) < 256, "kill trace saturated the 256-hit trace buffer")
    return {"metadata": metadata, "states": states, "hits": hits, "rewards": rewards}


def replay_hits(
    rng: NativeRng,
    hits: list[dict[str, Any]],
    *,
    stream_name: str,
    allow_inline_float_sign_advances: bool = False,
    expected_after: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    require(hits, f"{stream_name} replay reached no captured rolls")
    replayed: list[dict[str, Any]] = []
    for hit in hits:
        inserted_sign_advances = 0
        while hit["entry_words"] != rng.entry_prefix():
            prior_is_float_inner = bool(
                replayed
                and replayed[-1]["return_address"] == "0x00401323"
            )
            require(
                allow_inline_float_sign_advances
                and prior_is_float_inner
                and inserted_sign_advances == 0,
                f"{stream_name} roll {hit['ordinal']} entry state does not match native recurrence: "
                f"bound={hit['bound']} return={hit['return_address']} "
                f"expected_indices={rng.entry_prefix()[:2]} actual_indices={hit['entry_words'][:2]}",
            )
            before_sign = rng.snapshot()
            sign_bit = (rng.stream_word() >> 6) & 1
            after_sign = rng.snapshot()
            replayed.append(
                {
                    "ordinal": f"inline-before-{hit['ordinal']}",
                    "thread_id": hit["thread_id"],
                    "bound": 2,
                    "return_address": "0x00401310:inline-sign",
                    "label": "signed_float_sign_bit",
                    "output": sign_bit,
                    "state_before_index_a": before_sign["index_a"],
                    "state_before_index_b": before_sign["index_b"],
                    "state_before_sha256": state_sha256(before_sign),
                    "state_after_index_a": after_sign["index_a"],
                    "state_after_index_b": after_sign["index_b"],
                    "state_after_sha256": state_sha256(after_sign),
                }
            )
            inserted_sign_advances += 1
        require(hit["entry_words_valid"], f"{stream_name} roll lost readable entry state")
        expected_prefix = rng.entry_prefix()
        require(
            hit["entry_words"] == expected_prefix,
            f"{stream_name} roll {hit['ordinal']} entry state does not match native recurrence: "
            f"bound={hit['bound']} return={hit['return_address']} "
            f"expected_indices={expected_prefix[:2]} actual_indices={hit['entry_words'][:2]} "
            f"first_mismatch={next((index for index, pair in enumerate(zip(expected_prefix, hit['entry_words'])) if pair[0] != pair[1]), None)}",
        )
        before = rng.snapshot()
        output = rng.bounded_entry(hit["bound"])
        after = rng.snapshot()
        replayed.append(
            {
                "ordinal": hit["ordinal"],
                "thread_id": hit["thread_id"],
                "bound": hit["bound"],
                "return_address": hit["return_address"],
                "label": DIRECT_ROLL_LABELS.get(hit["return_address_int"], "nested_or_materializer_integer"),
                "output": output,
                "signed_result_pending_nested_roll": bool(
                    hit["bound"] < 0 or hit["arg1"] == 1
                ),
                "state_before_index_a": before["index_a"],
                "state_before_index_b": before["index_b"],
                "state_before_sha256": state_sha256(before),
                "state_after_index_a": after["index_a"],
                "state_after_index_b": after["index_b"],
                "state_after_sha256": state_sha256(after),
            }
        )
        if (
            len(replayed) >= 2
            and replayed[-2].get("signed_result_pending_nested_roll") is True
            and hit["bound"] == 2
            and 0x00401170 <= hit["return_address_int"] < 0x00401310
        ):
            signed_parent = replayed[-2]
            signed_parent["magnitude_output"] = signed_parent["output"]
            signed_parent["sign_roll_output"] = output
            if output == 1:
                signed_parent["output"] = -signed_parent["output"]
            signed_parent["signed_result_pending_nested_roll"] = False
    if expected_after is not None:
        trailing_sign_advances = 0
        while compact_state(rng.snapshot()) != compact_state(expected_after):
            prior_is_float_inner = bool(
                replayed
                and replayed[-1]["return_address"] == "0x00401323"
            )
            require(
                allow_inline_float_sign_advances
                and prior_is_float_inner
                and trailing_sign_advances == 0,
                f"{stream_name} final state does not match the traced recurrence",
            )
            before_sign = rng.snapshot()
            sign_bit = (rng.stream_word() >> 6) & 1
            after_sign = rng.snapshot()
            replayed.append(
                {
                    "ordinal": "inline-after-final-trace",
                    "thread_id": hits[-1]["thread_id"],
                    "bound": 2,
                    "return_address": "0x00401310:inline-sign",
                    "label": "signed_float_sign_bit",
                    "output": sign_bit,
                    "state_before_index_a": before_sign["index_a"],
                    "state_before_index_b": before_sign["index_b"],
                    "state_before_sha256": state_sha256(before_sign),
                    "state_after_index_a": after_sign["index_a"],
                    "state_after_index_b": after_sign["index_b"],
                    "state_after_sha256": state_sha256(after_sign),
                }
            )
            trailing_sign_advances += 1
    return replayed, rng.snapshot()


def find_private_stream(hits: list[dict[str, Any]], shared_address: int) -> int | None:
    candidates = {
        hit["ecx"]
        for hit in hits
        if hit["return_address_int"] in PRIVATE_DIRECT_RETURNS
        and hit["ecx"] != shared_address
    }
    require(len(candidates) <= 1, f"selector trace contains ambiguous private streams: {sorted(candidates)}")
    return next(iter(candidates)) if candidates else None


def classify_selector(
    private_rolls: list[dict[str, Any]],
    metadata: dict[str, str],
    rewards: list[dict[str, Any]],
) -> dict[str, Any]:
    by_label = {
        roll["label"]: roll
        for roll in private_rolls
        if roll["label"] != "nested_or_materializer_integer"
    }
    policies = {
        name: as_int(metadata.get(f"policy.{name}"))
        for name in ("orb", "powerup", "item", "gold", "specific_item", "potion")
    }
    candidates: list[str] = []
    if by_label.get("key_eligibility", {}).get("output") == 2:
        candidates.append("key")
    for category in ("orb", "gold", "item", "potion", "powerup"):
        policy = policies[category]
        roll = by_label.get(f"{category}_eligibility")
        if policy == 3 or (roll is not None and roll["output"] == 1):
            candidates.append(category)
    choice = by_label.get("candidate_choice")
    selected = None
    if choice is not None:
        require(candidates, "candidate-choice roll ran with an empty reconstructed table")
        require(0 <= choice["output"] < len(candidates), "candidate-choice output escaped its table")
        selected = candidates[choice["output"]]
    quick_first = next(
        (
            roll
            for roll in private_rolls
            if roll["label"] == "quick_health_gate_1_of_2"
        ),
        None,
    )
    del quick_first  # quick-gate rolls live on the shared stream, never private.
    return {
        "roll_order": list(CATEGORY_ORDER),
        "policies": policies,
        "arena_disable_mask": as_int(metadata.get("arena.disable_mask")),
        "effective_roll_bounds": {
            label.removesuffix("_eligibility"): roll["bound"]
            for label, roll in by_label.items()
            if label.endswith("_eligibility")
        },
        "eligible_candidates": candidates,
        "candidate_choice_index": choice["output"] if choice is not None else None,
        "selected_category": selected,
        "materialized_reward_families": [reward["family"] for reward in rewards],
    }


def state_rows_lua(tag: str, stream_expression: str) -> str:
    return f"""
do
  local stream = tonumber({stream_expression}) or 0
  local words = {{}}
  if stream ~= 0 then
    for index = 0, 54 do words[#words + 1] = tostring(sd.debug.read_u32(stream + 8 + index * 4) or 0) end
  end
  print('Q|{tag}|' .. tostring(stream) .. '|' ..
    tostring(stream ~= 0 and (sd.debug.read_u32(stream) or 0) or 0) .. '|' ..
    tostring(stream ~= 0 and (sd.debug.read_u32(stream + 4) or 0) or 0) .. '|' ..
    tostring(stream ~= 0 and (sd.debug.read_u32(stream + 0xE4) or 0) or 0) .. '|' ..
    table.concat(words, ','))
end
"""


def kill_trace_lua(actor_address: int) -> str:
    shared_before = state_rows_lua("shared_before", "shared")
    shared_after = state_rows_lua("shared_after", "shared")
    return f"""
local actor = {actor_address}
local trace_name = {json.dumps(TRACE_NAME)}
local function emit(key, value) print('M|' .. key .. '|' .. tostring(value)) end
local base = sd.debug.resolve_game_address(0x00400000) or 0x00400000
local delta = base - 0x00400000
local active_slot = sd.debug.resolve_game_address({ACTIVE_RNG_POINTER}) or 0
local shared = active_slot ~= 0 and (sd.debug.read_ptr(active_slot) or 0) or 0
local app_slot = sd.debug.resolve_game_address({APP_GLOBAL}) or 0
local app = app_slot ~= 0 and (sd.debug.read_ptr(app_slot) or 0) or 0
local cfg = sd.debug.read_ptr(actor + 0x1D0) or 0
local arena = sd.debug.read_ptr(actor + 0x58) or 0
local game_slot = sd.debug.resolve_game_address({GAMEPLAY_GLOBAL}) or 0
local game = game_slot ~= 0 and (sd.debug.read_ptr(game_slot) or 0) or 0
local active_player_slot = sd.debug.resolve_game_address({ACTIVE_PLAYER_GLOBAL}) or 0
local active_player = active_player_slot ~= 0 and (sd.debug.read_ptr(active_player_slot) or 0) or 0
local active_index = active_player ~= 0 and (sd.debug.read_u8(active_player + 0x60) or 255) or 255
local participant_slot = sd.debug.read_u8(actor + 0x5C) or 255
local progression_handle = game ~= 0 and participant_slot < 4 and
  (sd.debug.read_ptr(game + 0x1654 + participant_slot * 4) or 0) or 0
local progression = progression_handle ~= 0 and (sd.debug.read_ptr(progression_handle) or 0) or 0
local prior_rewards = {{}}
for _, row in ipairs(sd.world.list_actors() or {{}}) do
  local t = tonumber(row.object_type_id or row.type_id) or 0
  if t == 2011 or t == 2012 or t == 2013 or t == 2038 then
    prior_rewards[tonumber(row.actor_address) or 0] = true
  end
end
emit('actor.address', actor)
emit('actor.type_id', sd.debug.read_u32(actor + 8) or 0)
emit('actor.seed', sd.debug.read_u32(actor + 0x1C0) or 0)
emit('actor.participant_slot', participant_slot)
emit('actor.config', cfg)
emit('actor.x', sd.debug.read_float(actor + 0x18) or 0)
emit('actor.y', sd.debug.read_float(actor + 0x1C) or 0)
emit('policy.orb', cfg ~= 0 and (sd.debug.read_u8(cfg + 0xCC) or 0) or 0)
emit('policy.powerup', cfg ~= 0 and (sd.debug.read_u8(cfg + 0xCD) or 0) or 0)
emit('policy.item', cfg ~= 0 and (sd.debug.read_u8(cfg + 0xCE) or 0) or 0)
emit('policy.gold', cfg ~= 0 and (sd.debug.read_u8(cfg + 0xCF) or 0) or 0)
emit('policy.specific_item', cfg ~= 0 and (sd.debug.read_u8(cfg + 0xD0) or 0) or 0)
emit('policy.potion', cfg ~= 0 and (sd.debug.read_u8(cfg + 0xD1) or 0) or 0)
emit('config.special_mode', cfg ~= 0 and (sd.debug.read_u8(cfg + 0x54) or 0) or 0)
emit('arena.address', arena)
emit('arena.disable_mask', arena ~= 0 and (sd.debug.read_u32(arena + 0x8F04) or 0) or 0)
emit('arena.level', arena ~= 0 and (sd.debug.read_i32(arena + 0x8FF0) or 0) or 0)
emit('arena.level_floor', arena ~= 0 and (sd.debug.read_i32(arena + 0x8F0C) or 0) or 0)
emit('arena.level_ceiling', arena ~= 0 and (sd.debug.read_i32(arena + 0x8F10) or 0) or 0)
emit('arena.mode', arena ~= 0 and (sd.debug.read_i32(arena + 0x8F08) or 0) or 0)
emit('arena.current_level', arena ~= 0 and (sd.debug.read_i32(arena + 0x9064) or 0) or 0)
emit('active_player_index', active_index)
emit('progression.address', progression)
emit('progression.level', progression ~= 0 and (sd.debug.read_i32(progression + 0x30) or 0) or 0)
for _, offset in ipairs({{0xBC,0xC0,0xCC,0x804,0x808,0x80C,0x810}}) do
  emit(string.format('progression.0x%X', offset), progression ~= 0 and (sd.debug.read_float(progression + offset) or 0) or 0)
end
emit('progression.0x814_u8', progression ~= 0 and (sd.debug.read_u8(progression + 0x814) or 0) or 0)
emit('app_tick_before', app ~= 0 and (sd.debug.read_u32(app + 0x28) or 0) or 0)
{shared_before}
sd.debug.clear_trace_hits(trace_name)
emit('write_health', sd.gameplay.set_run_enemy_health(actor, 0.0, 50.0))
local triggered, exception = sd.world.trigger_enemy_death(actor)
emit('triggered', triggered)
emit('trigger_exception', exception or 0)
emit('app_tick_after', app ~= 0 and (sd.debug.read_u32(app + 0x28) or 0) or 0)
{shared_after}
local hits = sd.debug.get_trace_hits(trace_name) or {{}}
emit('trace_count', #hits)
for index, hit in ipairs(hits) do
  local words = {{}}
  if hit.ecx_words_valid and hit.ecx_words then
    for word_index = 1, 24 do words[#words + 1] = tostring(hit.ecx_words[word_index] or 0) end
  end
  print('H|' .. tostring(index) .. '|' .. tostring(hit.thread_id or 0) .. '|' ..
    tostring(hit.ecx or 0) .. '|' .. tostring(hit.arg0 or 0) .. '|' ..
    tostring(hit.arg1 or 0) .. '|' .. tostring((hit.ret or 0) - delta) .. '|' ..
    tostring(hit.requested_address or 0) .. '|' .. tostring(hit.ecx_words_valid or false) .. '|' ..
    table.concat(words, ','))
end
for _, row in ipairs(sd.world.list_actors() or {{}}) do
  local address = tonumber(row.actor_address) or 0
  local type_id = tonumber(row.object_type_id or row.type_id) or 0
  if not prior_rewards[address] and (type_id == 2011 or type_id == 2012 or type_id == 2013 or type_id == 2038) then
    local held = type_id == 2013 and (sd.debug.read_ptr(address + 0x148) or 0) or 0
    print('R|' .. tostring(type_id) .. '|' .. tostring(address) .. '|' ..
      tostring(tonumber(row.x) or 0) .. '|' .. tostring(tonumber(row.y) or 0) .. '|' ..
      tostring(sd.debug.read_u8(address + 0x13C) or 0) .. '|' ..
      tostring(sd.debug.read_i32(address + 0x13C) or 0) .. '|' ..
      tostring(sd.debug.read_float(address + 0x140) or 0) .. '|' ..
      tostring(sd.debug.read_i32(address + 0x140) or 0) .. '|' ..
      tostring(sd.debug.read_float(address + 0x144) or 0) .. '|' ..
      tostring(sd.debug.read_i32(address + 0x144) or 0) .. '|' ..
      tostring(sd.debug.read_u32(address + 0x148) or 0) .. '|' ..
      tostring(sd.debug.read_float(address + 0x14C) or 0) .. '|' ..
      tostring(sd.debug.read_i32(address + 0x14C) or 0) .. '|' ..
      tostring(sd.debug.read_float(address + 0x154) or 0) .. '|' ..
      tostring(sd.debug.read_i32(address + 0x154) or 0) .. '|' ..
      tostring(held ~= 0 and (sd.debug.read_u32(held + 8) or 0) or 0) .. '|' ..
      tostring(held ~= 0 and (sd.debug.read_i32(held + 0x1C) or -1) or -1))
  end
end
"""


def arm_integer_trace(host_pipe: str) -> dict[str, str]:
    result = values(
        host_pipe,
        f"""
pcall(sd.debug.untrace_function, {RNG_INTEGER})
sd.debug.clear_trace_hits({json.dumps(TRACE_NAME)})
local ok = sd.debug.trace_function({RNG_INTEGER}, {json.dumps(TRACE_NAME)})
print('ok=' .. tostring(ok))
print('error=' .. tostring(sd.debug.get_last_error() or ''))
""",
    )
    require(result.get("ok") == "true", f"BROKEN: native Integer trace could not be armed: {result}")
    return result


def record_one_kill(
    host_pipe: str,
    process_ids: tuple[int, int],
    family: dict[str, Any],
    family_index: int,
    global_index: int,
) -> dict[str, Any]:
    assert_pair_runnable(process_ids)
    spawned = primary.spawn_one_enemy(
        KILL_X,
        KILL_Y,
        setup_hp=50.0,
        freeze_on_spawn=True,
        native_type_id=int(family["type_id"]),
    )
    actor = int(spawned["actor_address"])
    raw = local_sync.lua(host_pipe, kill_trace_lua(actor), timeout=25.0)
    parsed = parse_kill_capture(raw)
    metadata = parsed["metadata"]
    require("actor.seed" in metadata, f"kill {global_index} actor seed field was not captured")
    seed = as_int(metadata["actor.seed"])

    shared_before_raw = parsed["states"]["shared_before"]
    shared_after_raw = parsed["states"]["shared_after"]
    shared_address = int(shared_before_raw["stream_address"])
    require(
        shared_after_raw["stream_address"] == shared_address,
        f"kill {global_index} changed active shared stream identity during death",
    )
    shared_hits = [hit for hit in parsed["hits"] if hit["ecx"] == shared_address]
    shared_rolls, shared_replayed_after = replay_hits(
        NativeRng.from_snapshot(shared_before_raw),
        shared_hits,
        stream_name=f"kill {global_index} shared stream",
        allow_inline_float_sign_advances=True,
        expected_after=shared_after_raw,
    )
    require(
        compact_state(shared_replayed_after) == compact_state(shared_after_raw),
        f"kill {global_index} shared stream has an untraced advance or wrong replay",
    )

    private_address = find_private_stream(parsed["hits"], shared_address)
    private_hits = (
        [hit for hit in parsed["hits"] if hit["ecx"] == private_address]
        if private_address is not None
        else []
    )
    private_before_rng = NativeRng.seeded(seed)
    private_before = private_before_rng.snapshot()
    if private_hits:
        private_rolls, private_after = replay_hits(
            private_before_rng,
            private_hits,
            stream_name=f"kill {global_index} actor-private stream",
        )
    else:
        private_rolls = []
        private_after = private_before_rng.snapshot()

    selector = classify_selector(private_rolls, metadata, parsed["rewards"])
    quick_shared = [
        roll
        for roll in shared_rolls
        if roll["label"] in {"quick_health_gate_1_of_2", "quick_health_gate_1_of_10"}
    ]
    require(
        quick_shared and quick_shared[0]["label"] == "quick_health_gate_1_of_2",
        f"kill {global_index} did not preserve the first quick-potion shared roll",
    )
    timestamp = {
        "app_tick_before": as_int(metadata.get("app_tick_before")),
        "app_tick_after": as_int(metadata.get("app_tick_after")),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "kill_index": global_index,
        "family_index": family_index,
        "enemy_family": str(family["family"]),
        "enemy_type_id": int(family["type_id"]),
        "spawn": {
            "network_actor_id": int(spawned["network_actor_id"]),
            "actor_address": actor,
            "x": float(spawned["x"]),
            "y": float(spawned["y"]),
            "freeze_on_spawn": bool(spawned["freeze_on_spawn"]),
        },
        "timestamps": timestamp,
        "actor_seed_lifecycle": {
            "captured_actor_field": "actor+0x1C0",
            "seed": seed,
            "constructor_seed": {
                "actor": str(family["family"]),
                "base_constructor": "Badguy 0x00473390",
                "draw": {
                    "stream": "active process-global stream through [0x00818B08]",
                    "integer_function": "0x00401170",
                    "bound": ACTOR_SEED_BOUND,
                    "signed": False,
                },
                "write_site": "0x0047345E -> actor+0x1C0",
            },
            "post_constructor_updates": copy.deepcopy(
                ACTOR_SEED_UPDATES[str(family["family"])]
            ),
            "death_capture": "live actor+0x1C0 read immediately before 0x0047C070",
            "selector_constructs_stack_state_at": "0x0047C0CF",
            "selector_seeds_stack_state_at": "0x0047C0DF -> 0x00401120",
            "private_stream_address": private_address,
        },
        "selector": selector,
        "private_stream": {
            "identity": "actor-seeded stack-local 0xE8-byte NativeRng",
            "seed": seed,
            "before": private_before,
            "rolls": private_rolls,
            "after": private_after,
        },
        "shared_stream": {
            "identity": "active process-global stream through [0x00818B08]",
            "stream_address": shared_address,
            "before": compact_state(shared_before_raw),
            "rolls": shared_rolls,
            "after": compact_state(shared_after_raw),
            "quick_potion_rolls": quick_shared,
        },
        "table_context": {
            key: value
            for key, value in metadata.items()
            if key.startswith(("policy.", "arena.", "progression.", "config."))
            or key in {"actor.participant_slot", "active_player_index"}
        },
        "materialized_rewards": parsed["rewards"],
        "all_native_integer_hit_count": len(parsed["hits"]),
    }


MAGNET_ARM_LUA = r"""
local function emit(key, value) print(key .. '=' .. tostring(value)) end
if not rawget(_G, '__lootre_magnet_handler') then
  _G.__lootre_magnet_handler = sd.events.on('runtime.tick', function(event)
    local capture = rawget(_G, '__lootre_magnet_capture')
    if type(capture) ~= 'table' or capture.active ~= true then return end
    local found = nil
    for _, actor in ipairs(sd.world.list_actors() or {}) do
      local address = tonumber(actor.actor_address) or 0
      local type_id = tonumber(actor.object_type_id or actor.type_id) or 0
      if type_id == 2011 and not capture.excluded[address] then
        if capture.actor == 0 then
          local dx = (tonumber(actor.x) or 0) - capture.spawn_x
          local dy = (tonumber(actor.y) or 0) - capture.spawn_y
          if dx * dx + dy * dy < 16 then capture.actor = address end
        end
        if address == capture.actor then found = actor end
      end
    end
    if found ~= nil then
      local player = sd.player.get_state()
      local x = tonumber(found.x) or 0
      local y = tonumber(found.y) or 0
      local px = tonumber(player and player.x) or 0
      local py = tonumber(player and player.y) or 0
      capture.samples[#capture.samples + 1] = {
        tick = type(event) == 'table' and (tonumber(event.tick_count) or 0) or 0,
        monotonic_milliseconds = type(event) == 'table' and (tonumber(event.monotonic_milliseconds) or 0) or 0,
        actor_address = capture.actor,
        x = x,
        y = y,
        player_x = px,
        player_y = py,
        distance = math.sqrt((px - x) * (px - x) + (py - y) * (py - y)),
        remaining_value = sd.debug.read_float(capture.actor + 0x140) or 0,
        decay_timer = sd.debug.read_i32(capture.actor + 0x144) or 0,
      }
    elseif capture.actor ~= 0 and #capture.samples > 0 then
      capture.active = false
      capture.done = true
    end
    if #capture.samples > 160 then
      capture.error = 'orb did not finish within 160 runtime ticks'
      capture.active = false
      capture.done = true
    end
  end)
end
emit('registered', _G.__lootre_magnet_handler ~= nil)
"""


def begin_magnet_capture(host_pipe: str, x: float, y: float, kind: str) -> dict[str, str]:
    return values(
        host_pipe,
        f"""
local excluded = {{}}
for _, actor in ipairs(sd.world.list_actors() or {{}}) do
  if tonumber(actor.object_type_id or actor.type_id) == 2011 then
    excluded[tonumber(actor.actor_address) or 0] = true
  end
end
_G.__lootre_magnet_capture = {{
  active=true, done=false, error='', actor=0, excluded=excluded,
  spawn_x={x:.6f}, spawn_y={y:.6f}, samples={{}}, kind={json.dumps(kind)}
}}
local ok, err = sd.world.spawn_reward({{kind={json.dumps(kind)}, amount=1, x={x:.6f}, y={y:.6f}}})
print('ok=' .. tostring(ok)); print('error=' .. tostring(err or ''))
""",
    )


def magnet_capture_status(host_pipe: str) -> dict[str, str]:
    return values(
        host_pipe,
        """
local c=rawget(_G,'__lootre_magnet_capture') or {}
print('done='..tostring(c.done or false));print('active='..tostring(c.active or false));print('error='..tostring(c.error or ''));print('actor='..tostring(c.actor or 0));print('count='..tostring(#(c.samples or {})))
""",
    )


def read_magnet_capture(host_pipe: str) -> dict[str, Any]:
    output = local_sync.lua(
        host_pipe,
        """
local c=assert(rawget(_G,'__lootre_magnet_capture'))
print('M|kind|'..tostring(c.kind));print('M|actor|'..tostring(c.actor));print('M|error|'..tostring(c.error or ''));print('M|count|'..tostring(#c.samples))
for index,row in ipairs(c.samples) do
 print(table.concat({'T',index,row.tick,row.monotonic_milliseconds,row.actor_address,row.x,row.y,row.player_x,row.player_y,row.distance,row.remaining_value,row.decay_timer},'|'))
end
""",
        timeout=20.0,
    )
    metadata: dict[str, str] = {}
    samples: list[dict[str, Any]] = []
    for line in output.splitlines():
        if line.startswith("M|"):
            _, key, value = line.split("|", 2)
            metadata[key] = value
        elif line.startswith("T|"):
            parts = line.split("|")
            require(len(parts) == 12, f"magnet sample is malformed: {line}")
            samples.append(
                {
                    "sample_index": as_int(parts[1]),
                    "tick": as_int(parts[2]),
                    "monotonic_milliseconds": as_int(parts[3]),
                    "actor_address": as_int(parts[4]),
                    "x": as_float(parts[5]),
                    "y": as_float(parts[6]),
                    "player_x": as_float(parts[7]),
                    "player_y": as_float(parts[8]),
                    "distance": as_float(parts[9]),
                    "remaining_value": as_float(parts[10]),
                    "decay_timer": as_int(parts[11]),
                }
            )
    require(metadata.get("error", "") == "", f"magnet capture failed: {metadata}")
    require(len(samples) >= 3, f"magnet capture produced too few per-tick positions: {metadata}")
    require([row["sample_index"] for row in samples] == list(range(1, len(samples) + 1)), "magnet samples contain an index gap")
    return {
        "kind": metadata["kind"],
        "actor_address": as_int(metadata["actor"]),
        "samples": samples,
        "capture_observed": True,
    }


def capture_magnet_trajectories(
    host_pipe: str,
    client_pipe: str,
    process_ids: tuple[int, int],
    *,
    count: int,
) -> list[dict[str, Any]]:
    local_sync.place_player(host_pipe, MAGNET_ANCHOR[0], MAGNET_ANCHOR[1], 90.0)
    local_sync.place_player(client_pipe, 2800.0, 1750.0, 90.0)
    factor_values = values(
        host_pipe,
        f"""
local game_slot=sd.debug.resolve_game_address({GAMEPLAY_GLOBAL}) or 0
local game=game_slot~=0 and (sd.debug.read_ptr(game_slot) or 0) or 0
local handle=game~=0 and (sd.debug.read_ptr(game+0x1654) or 0) or 0
local progression=handle~=0 and (sd.debug.read_ptr(handle) or 0) or 0
print('progression='..tostring(progression))
print('pickup_factor='..tostring(progression~=0 and (sd.debug.read_float(progression+0xCC) or 0) or 0))
print('orb_pull_multiplier='..tostring(progression~=0 and (sd.debug.read_float(progression+0xBC) or 0) or 0))
""",
    )
    pickup_factor = as_float(factor_values.get("pickup_factor"))
    pull_multiplier = as_float(factor_values.get("orb_pull_multiplier"))
    require(
        math.isfinite(pickup_factor) and pickup_factor > 0.0,
        f"BROKEN: magnet capture has no live pickup factor: {factor_values}",
    )
    require(
        math.isfinite(pull_multiplier) and pull_multiplier > 0.0,
        f"BROKEN: magnet capture has no live orb-pull multiplier: {factor_values}",
    )
    effective_pull_radius = pickup_factor * 60.0 * pull_multiplier
    effective_capture_radius = pickup_factor * 20.0
    armed = values(host_pipe, MAGNET_ARM_LUA)
    require(armed.get("registered") == "true", "BROKEN: runtime.tick magnet sampler did not register")
    specifications = (
        ("health_orb", 55.0, 0.0),
        ("mana_orb", 0.0, 43.0),
        ("health_orb", 31.0 / math.sqrt(2.0), 31.0 / math.sqrt(2.0)),
    )[:count]
    captures: list[dict[str, Any]] = []
    for index, (kind, dx, dy) in enumerate(specifications, 1):
        spawn_x = MAGNET_ANCHOR[0] + dx
        spawn_y = MAGNET_ANCHOR[1] + dy
        spawned = begin_magnet_capture(host_pipe, spawn_x, spawn_y, kind)
        require(spawned.get("ok") == "true", f"BROKEN: magnet orb {index} did not spawn: {spawned}")
        wait_until(
            f"magnet trajectory {index}",
            lambda: magnet_capture_status(host_pipe),
            lambda row: row.get("done") == "true",
            process_ids=process_ids,
            timeout=8.0,
            interval=0.05,
        )
        capture = read_magnet_capture(host_pipe)
        capture.update(
            {
                "trajectory_index": index,
                "spawn": {"x": spawn_x, "y": spawn_y},
                "initial_center_distance": math.hypot(dx, dy),
                "expected_constant_step_per_actor_tick": 1.5,
                "base_pull_radius_units_per_pickup_factor": 60.0,
                "base_capture_radius_units_per_pickup_factor": 20.0,
                "captured_pickup_factor": pickup_factor,
                "captured_orb_pull_multiplier": pull_multiplier,
                "effective_pull_radius": effective_pull_radius,
                "effective_capture_radius": effective_capture_radius,
            }
        )
        captures.append(capture)
    return captures


CREDIT_CAPTURE_LUA = r"""
local function emit(k,v) print(k..'='..tostring(v)) end
local player=sd.player.get_state() or {}
emit('player.gold',player.gold or 0);emit('player.x',player.x or 0);emit('player.y',player.y or 0)
local mp=sd.runtime.get_multiplayer_state() or {}
emit('participant.count',mp.participant_count or 0)
for index,row in ipairs(mp.participants or {}) do
 local p='participant.'..index..'.';local owned=row.owned_progression or {}
 emit(p..'id',row.participant_id or 0);emit(p..'x',row.x or 0);emit(p..'y',row.y or 0);emit(p..'gold',owned.gold or 0);emit(p..'gold_revision',owned.gold_revision or 0)
end
local loot=sd.world.get_replicated_loot and sd.world.get_replicated_loot() or {}
emit('loot.drop_count',loot.drop_count or 0)
local result=loot.last_pickup_result or {}
emit('pickup.valid',loot.last_pickup_result~=nil);emit('pickup.authority_participant_id',result.authority_participant_id or 0);emit('pickup.participant_id',result.participant_id or 0);emit('pickup.network_drop_id',result.network_drop_id or 0);emit('pickup.result',result.result or '');emit('pickup.amount',result.amount or 0);emit('pickup.resulting_gold',result.resulting_gold or 0)
"""


def credit_snapshot(pipe_name: str) -> dict[str, Any]:
    raw = values(pipe_name, CREDIT_CAPTURE_LUA)
    count = as_int(raw.get("participant.count"))
    require(count >= 2, f"two-participant credit capture lost participant membership: {raw}")
    participants = []
    for index in range(1, count + 1):
        prefix = f"participant.{index}."
        participants.append(
            {
                "participant_id": as_int(raw.get(prefix + "id")),
                "x": as_float(raw.get(prefix + "x")),
                "y": as_float(raw.get(prefix + "y")),
                "gold": as_int(raw.get(prefix + "gold")),
                "gold_revision": as_int(raw.get(prefix + "gold_revision")),
            }
        )
    return {
        "player": {
            "gold": as_int(raw.get("player.gold")),
            "x": as_float(raw.get("player.x")),
            "y": as_float(raw.get("player.y")),
        },
        "participants": participants,
        "loot_drop_count": as_int(raw.get("loot.drop_count")),
        "last_pickup_result": {
            "valid": raw.get("pickup.valid") == "true",
            "authority_participant_id": as_int(raw.get("pickup.authority_participant_id")),
            "participant_id": as_int(raw.get("pickup.participant_id")),
            "network_drop_id": as_int(raw.get("pickup.network_drop_id")),
            "result": raw.get("pickup.result", ""),
            "amount": as_int(raw.get("pickup.amount")),
            "resulting_gold": as_int(raw.get("pickup.resulting_gold")),
        },
    }


def capture_two_participant_credit(
    host_pipe: str,
    client_pipe: str,
    process_ids: tuple[int, int],
) -> dict[str, Any]:
    drop = (1500.0, 1750.0)
    host_position = (drop[0] - 18.0, drop[1])
    client_position = (drop[0] + 6.0, drop[1])
    local_sync.place_player(host_pipe, *host_position, 90.0)
    local_sync.place_player(client_pipe, *client_position, 270.0)
    time.sleep(0.5)
    before = {"host": credit_snapshot(host_pipe), "client": credit_snapshot(client_pipe)}
    spawned = values(
        host_pipe,
        f"local ok,err=sd.world.spawn_reward({{kind='gold',amount=11,x={drop[0]},y={drop[1]}}});print('ok='..tostring(ok));print('error='..tostring(err or ''))",
    )
    require(spawned.get("ok") == "true", f"BROKEN: crediting gold did not spawn: {spawned}")

    def completed() -> dict[str, Any]:
        return {"host": credit_snapshot(host_pipe), "client": credit_snapshot(client_pipe)}

    after = wait_until(
        "two-participant gold pickup result",
        completed,
        lambda row: (
            row["host"]["last_pickup_result"]["valid"]
            or row["client"]["last_pickup_result"]["valid"]
            or row["host"]["player"]["gold"] != before["host"]["player"]["gold"]
        ),
        process_ids=process_ids,
        timeout=8.0,
        interval=0.05,
    )
    return {
        "drop": {"kind": "gold", "amount": 11, "x": drop[0], "y": drop[1]},
        "placement": {
            "host": {"x": host_position[0], "y": host_position[1], "distance": 18.0},
            "client": {"x": client_position[0], "y": client_position[1], "distance": 6.0},
            "both_inside_stock_capture_radius": True,
        },
        "before": before,
        "after": after,
        "capture_method": "two real local-UDP participants placed inside the same stock gold radius before host-authoritative spawn",
    }


def copy_dig_sequence() -> dict[str, Any]:
    require(HUB_GOLDEN.is_file(), "BROKEN: landed G8 hub/dig golden is unavailable")
    document = json.loads(HUB_GOLDEN.read_text(encoding="utf-8"))
    trials = document.get("dig_trials")
    require(isinstance(trials, list) and len(trials) >= 8, "landed G8 fixture has fewer than eight Dig trials")
    first = copy.deepcopy(trials[0])
    require(first.get("direct_yield") == [], "landed G8 Dig sequence unexpectedly contains a direct reward")
    return {
        "source_fixture": "tests/fixtures/webgame/hub-economy-goldens.json",
        "source_fixture_sha256": windows_sha256(HUB_GOLDEN),
        "reuse_reason": "G8 already captured eight independent live Solomon Dig completions; G7 builds on that settled finding instead of re-deriving it",
        "sequence": first,
        "cross_trial_summary": copy.deepcopy(document.get("observed_dig_distribution")),
    }


def recovered_contract() -> dict[str, Any]:
    return {
        "selector": {
            "function": "0x0047C070",
            "candidate_order": list(CATEGORY_ORDER),
            "private_stream": {
                "size_bytes": 0xE8,
                "seed_field": "actor+0x1C0",
                "actor_seed_draw_bound": ACTOR_SEED_BOUND,
                "actor_seed_draw_stream": "active process-global stream through [0x00818B08]",
                "constructor": "0x00401110",
                "seed_function": "0x00401120",
                "integer_function": "0x00401170",
            },
            "base_bounds_by_policy": {
                "orb": {"0": 8, "1": 16, "2": 4, "3": 0, "4": None},
                "gold_after_x2": {"0": 22, "1": 44, "2": 11, "3": 0, "4": None, "5": 22},
                "item_before_arena_modifier": {"0": 360, "1": 720, "2": 180, "3": 0, "4": None},
                "potion": {"0": 400, "1": 800, "2": 200, "3": 0, "4": None},
            },
            "quick_potion_shared_gate": {"draws": [[2, 0], [10, 1]], "combined_probability": "1/16"},
            "goodie_crate": {
                "seed_draw": {"stream": "active shared", "bound": 1000, "stored_field": "+0x148"},
                "selector": "stored_seed % 18",
                "buckets": {
                    "0..3": "five health potions",
                    "4..7": "six mana potions",
                    "8..9": "two or three random equipment items",
                    "10": "definition-backed item selector 4",
                    "11..12": "three Book of Skill items, subtype 2 or 3 independently",
                    "13..16": "explicit gold: 500, 800, or 1100",
                    "17": "six-potion bundle: 5,0,1,4,2,2",
                },
            },
        },
        "amounts": {
            "orb_raw_value": {"kind_weights": {"health": "1/4", "mana": "3/4"}, "minimum": 0.25, "maximum_inclusive": 0.70, "health_scale": 25.0, "mana_scale": 40.0},
            "gold": {"level_draw_bound": "trunc(level/2)+6", "level_addend": "max(1,trunc(level/5))", "chunk_maximum": 25, "progression_multiplier_field": "+0xC0"},
            "enemy_potion_subtypes": {"health_0": "1/2", "mana_1": "1/2", "invincibility_6": "not in stock selector"},
            "bonus_kind_weights": {"0_bonus_skill": "1/4", "1_random_skill": "1/8", "2_damage_x4": "5/8"},
        },
        "physics": {
            "orb": {"pull_radius_units_per_pickup_factor": 60.0, "capture_radius_units_per_pickup_factor": 20.0, "movement_units_per_actor_tick": 1.5, "decay_start_ticks": 900, "decay_per_tick": 0.002, "active_value_floor": 0.01},
            "gold": {
                "capture_radius_units_per_pickup_factor": 30.0,
                "magnet": False,
                "despawn_timer": None,
                "enhanced_pickup_factor_threshold": 1.26,
                "above_threshold_per_tick_gate": {"bound": 15, "target": 1, "probability": "1/16"},
            },
            "sack": {"capture_radius_units_per_pickup_factor": 30.0, "magnet": False, "despawn_timer": None},
            "bonus": {"capture_radius_units_per_pickup_factor": 20.0, "magnet": False, "despawn_ticks": 1200},
            "world_registration": {"ids_per_owner_slot": 2047, "allocation_scan": 2048, "full_behavior": "registration fails; no loot eviction"},
        },
    }


def fixture_provenance(
    launch: dict[str, object],
    process_ids: tuple[int, int],
    source_revision: str,
) -> dict[str, Any]:
    host_executable = RUNTIME_ROOT / "instances" / f"{str(launch['instancePrefix']).lower()}-host" / "stage/SolomonDark.exe"
    client_executable = RUNTIME_ROOT / "instances" / f"{str(launch['instancePrefix']).lower()}-client" / "stage/SolomonDark.exe"
    for witness in (host_executable, client_executable, LAUNCHER, LOADER, Path(__file__)):
        require(witness.is_file(), f"BROKEN: provenance witness is absent: {witness}")
    return {
        "source_revision": source_revision,
        "source_revision_derived_by": "git rev-parse HEAD in recorder",
        "worktree_status_at_capture": git_output("status", "--short"),
        "recorder_path": "tests/re/record_live_loot_goldens.py",
        "recorder_sha256": windows_sha256(Path(__file__)),
        "retail_executable_sha256": windows_sha256(host_executable),
        "client_retail_executable_sha256": windows_sha256(client_executable),
        "release_loader_sha256": windows_sha256(LOADER),
        "release_launcher_sha256": windows_sha256(LAUNCHER),
        "instance_prefix": str(launch["instancePrefix"]),
        "process_ids": {"host": process_ids[0], "client": process_ids[1]},
        "executable_paths": {
            "host": str(launch["hostExecutablePath"]),
            "client": str(launch["clientExecutablePath"]),
        },
        "udp_ports": {"host": HOST_PORT, "client": CLIENT_PORT},
        "allowed_udp_ports": list(ALLOWED_PORTS),
        "audio_disabled": bool(launch.get("audioDisabled")),
        "capture_method": "live retail pair; Lua exec; native entry tracing; complete 55-word RNG boundary snapshots; bit-exact Python recurrence replay",
    }


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_capture(*, smoke: bool, output: Path, raw_output: Path) -> dict[str, Any]:
    source_revision = git_output("rev-parse", "HEAD")
    require(len(source_revision) == 40, "BROKEN: recorder could not derive a 40-hex source revision")
    require(POWERSHELL.is_file(), f"BROKEN: PowerShell is not runnable: {POWERSHELL}")
    require(GAME_DIRECTORY.is_dir(), f"BROKEN: read-only retail game directory is absent: {GAME_DIRECTORY}")
    require(LAUNCHER.is_file() and LOADER.is_file(), "BROKEN: this clone has no Release launcher/loader")
    before_processes = snapshot_owned_target_processes()
    require(not before_processes, f"BROKEN: pre-existing loot target processes make ownership ambiguous: {before_processes}")
    assert_reserved_ports_free()

    instance_prefix = SMOKE_INSTANCE_PREFIX if smoke else INSTANCE_PREFIX
    host_pipe, client_pipe = configure_helper_pipes(instance_prefix)
    os.environ["SDMOD_DISABLE_AUDIO"] = "1"
    os.environ.pop("SDMOD_ENABLE_AUDIO", None)
    raw: dict[str, Any] = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_revision": source_revision,
        "processes_before": before_processes,
        "instance_prefix": instance_prefix,
    }
    document: dict[str, Any] | None = None
    launch: dict[str, object] | None = None
    process_ids: tuple[int, int] | None = None
    failure: BaseException | None = None
    cleanup: list[dict[str, Any]] = []
    try:
        print(f"[lootre] launching {instance_prefix} on UDP {HOST_PORT}/{CLIENT_PORT}", flush=True)
        launch = local_sync.launch_pair(
            preset="map_create_fire_mind_hub",
            instance_prefix=instance_prefix,
            host_port=HOST_PORT,
            client_port=CLIENT_PORT,
            game_directory=GAME_DIRECTORY,
            launcher_path=LAUNCHER,
            runtime_root=RUNTIME_ROOT,
            exact_mod_ids=("sample.lua.ui_sandbox_lab",),
            quick_start=True,
            tile_windows=False,
            enable_audio=False,
        )
        process_ids = (as_int(launch["hostProcessId"]), as_int(launch["clientProcessId"]))
        raw["launch"] = launch
        raw["process_ids"] = list(process_ids)
        require(
            launch.get("audioDisabled") is True,
            f"BROKEN: live loot launch did not disable audio: {launch}",
        )
        require(
            as_int(launch.get("hostPort")) == HOST_PORT and as_int(launch.get("clientPort")) == CLIENT_PORT,
            f"BROKEN: live loot launch escaped its reserved ports: {launch}",
        )
        assert_pair_runnable(process_ids)
        raw["run_entry"] = local_sync.start_host_testrun_and_wait_for_clients(timeout=60.0)
        local_sync.wait_for_remote(host_pipe, local_sync.CLIENT_ID, local_sync.CLIENT_NAME, "testrun")
        local_sync.wait_for_remote(client_pipe, local_sync.HOST_ID, local_sync.HOST_NAME, "testrun")
        raw["manual_combat"] = primary.enable_manual_stock_spawner_combat()
        raw["integer_trace"] = arm_integer_trace(host_pipe)
        local_sync.place_player(host_pipe, *HOST_PARK, 90.0)
        local_sync.place_player(client_pipe, *CLIENT_PARK, 270.0)

        families = []
        for family in ENEMY_FAMILIES:
            row = dict(family)
            if smoke:
                row["kills"] = 1
            families.append(row)
        kills: list[dict[str, Any]] = []
        global_index = 0
        for family in families:
            for family_index in range(1, int(family["kills"]) + 1):
                global_index += 1
                print(
                    f"[lootre] kill {global_index}/{sum(int(row['kills']) for row in families)} "
                    f"{family['family']} {family_index}/{family['kills']}",
                    flush=True,
                )
                kills.append(
                    record_one_kill(
                        host_pipe,
                        process_ids,
                        family,
                        family_index,
                        global_index,
                    )
                )
                if global_index % 10 == 0:
                    write_json(raw_output, {**raw, "completed_kills": kills})
                time.sleep(0.025)

        if not smoke:
            require(len(kills) >= 100, "fewer than 100 native kills reached the loot fixture")
            require(
                {row["enemy_family"] for row in kills} == {"Skeleton", "Zombie", "Wraith"},
                "the live kill corpus no longer covers three named enemy families",
            )
        print("[lootre] recording orb magnet trajectories", flush=True)
        trajectories = capture_magnet_trajectories(
            host_pipe,
            client_pipe,
            process_ids,
            count=1 if smoke else 3,
        )
        print("[lootre] recording two-participant gold credit", flush=True)
        crediting = capture_two_participant_credit(host_pipe, client_pipe, process_ids)
        provenance = fixture_provenance(launch, process_ids, source_revision)
        document = {
            "schema": "solomon-dark-native-loot-goldens-v1",
            "recorded_live": True,
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_revision": source_revision,
            "header": provenance,
            "capture_contract": {
                "enemy_kill_count": len(kills),
                "enemy_families": [row["family"] for row in families],
                "actor_private_stream_required": True,
                "full_private_state_words_per_kill": RNG_WORD_COUNT,
                "magnet_trajectory_count": len(trajectories),
                "two_participant_credit_case": True,
                "allowed_instance_prefix": "loot-*",
                "allowed_udp_ports": list(ALLOWED_PORTS),
                "sd_rng_set_seed_used": False,
            },
            "recovered_contract": recovered_contract(),
            "enemy_kills": kills,
            "dig_reward_sequence": copy_dig_sequence(),
            "magnet_trajectories": trajectories,
            "two_participant_crediting": crediting,
        }
        write_json(output, document)
        return document
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            if launch is not None:
                cleanup = local_sync.stop_owned_game_processes()
                local_sync._kill_lua_daemon(host_pipe)
                local_sync._kill_lua_daemon(client_pipe)
                if process_ids is not None:
                    stopped_ids = {
                        as_int(row.get("processId"))
                        for row in cleanup
                        if row.get("stopped") or row.get("alreadyExited")
                    }
                    require(
                        stopped_ids == set(process_ids),
                        f"BROKEN: cleanup did not account for exactly the owned loot PIDs: {cleanup}",
                    )
        finally:
            raw["cleanup"] = cleanup
            raw["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            raw["failure"] = f"{type(failure).__name__}: {failure}" if failure else None
            raw["processes_after"] = snapshot_owned_target_processes()
            write_json(raw_output, raw)
            require(
                not raw["processes_after"],
                f"BROKEN: owned loot processes survived cleanup: {raw['processes_after']}",
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="record three kills and one trajectory into runtime only")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-output", type=Path, default=RAW_OUTPUT)
    arguments = parser.parse_args()
    output = arguments.output
    if arguments.smoke and output == DEFAULT_OUTPUT:
        output = RUNTIME_ROOT / "loot-smoke.json"
    document = run_capture(smoke=arguments.smoke, output=output, raw_output=arguments.raw_output)
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(output),
                "enemy_kills": len(document["enemy_kills"]),
                "magnet_trajectories": len(document["magnet_trajectories"]),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
