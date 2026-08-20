"""Static contracts for the G7 native loot selector reconstruction."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import struct
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    assert_recorded_hash_matches_file,
)


DOC = ROOT / "docs/reverse-engineering/native-loot-selector.md"
FIXTURE = ROOT / "tests/fixtures/webgame/loot-goldens.json"
RECORDER = ROOT / "tests/re/record_live_loot_goldens.py"
HUB_FIXTURE = ROOT / "tests/fixtures/webgame/hub-economy-goldens.json"
PICKUP_PACKETS = (
    ROOT
    / "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_packet_handlers.inl"
)
PICKUP_AUTHORITY = (
    ROOT
    / "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_authority.inl"
)
PICKUP_FINALIZATION = (
    ROOT
    / "SolomonDarkModLoader/src/multiplayer_local_transport/loot_pickup_host_finalization.inl"
)
REPLICATED_LOOT = (
    ROOT
    / "SolomonDarkModLoader/src/mod_loader_gameplay/replicated_loot_reconciliation.inl"
)
REPLICATED_ENEMY_DEATH = (
    ROOT
    / "SolomonDarkModLoader/src/mod_loader_gameplay/world_snapshot_reconciliation/run_enemy_health_and_status.inl"
)
GOLD_PICKUP_HOOK = (
    ROOT
    / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/gold_pickup_hook.inl"
)

FIXTURE_SHA256 = "dabdd9cdd87dc78b4b800477d2765a1afd63f86da22cf19427b5eb077cc6be26"
RECORDER_SHA256 = "7aaa50f7a1630cf6e09dd26b64ab6ebebecb61bc49a3479804f8c4458db4fcf7"
HUB_FIXTURE_SHA256 = "770fa976c9faea7eab731ba6d40b3798c548546dfec6a62780862b0b59c3ae3f"
SOURCE_REVISION = "fbfc7502090e8c84ad310f8fa4db5bebc4583bf3"
RETAIL_SHA256 = "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
RELEASE_LOADER_SHA256 = "8ad824fb74783760de11791aaabb6077ea8d5ffc963ea3c8a2f62053de9a29ea"
RELEASE_LAUNCHER_SHA256 = "8da5a34698e1ed59aa64880c4c05ecf210a6ea203d9e9b21d5e2b52e61d61941"

RNG_MASK = 0x3FFFFFFF
RNG_WORD_COUNT = 55
RNG_DIVISOR = 100000
CATEGORY_ORDER = ["key", "orb", "gold", "item", "potion", "powerup"]


def _read(path: Path, consequence: str) -> str:
    if not path.is_file():
        raise StaticReTestFailure(consequence)
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _fixture() -> dict[str, Any]:
    raw = _read(FIXTURE, "the standalone native loot live golden is absent")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise StaticReTestFailure(
            f"the native loot golden is not reviewable JSON: {error}"
        ) from error
    if not isinstance(value, dict):
        raise StaticReTestFailure("native loot consumers lost the fixture's top-level object")
    return value


@lru_cache(maxsize=1)
def _hub_fixture() -> dict[str, Any]:
    raw = _read(HUB_FIXTURE, "the G8 Dig source fixture is absent")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise StaticReTestFailure(
            f"the G8 Dig source fixture is not reviewable JSON: {error}"
        ) from error
    if not isinstance(value, dict):
        raise StaticReTestFailure("the G8 Dig comparison lost its source object")
    return value


def _unique_section(text: str, name: str) -> str:
    begin_marker = f"<!-- {name}_BEGIN -->"
    end_marker = f"<!-- {name}_END -->"
    begin = text.find(begin_marker)
    if begin < 0:
        raise StaticReTestFailure(f"{name} documentation contract has no beginning")
    if text.find(begin_marker, begin + len(begin_marker)) >= 0:
        raise StaticReTestFailure(f"{name} documentation lookup is ambiguous at its beginning")
    end = text.find(end_marker, begin + len(begin_marker))
    if end < 0:
        raise StaticReTestFailure(f"{name} documentation contract has no ending")
    if text.find(end_marker, end + len(end_marker)) >= 0:
        raise StaticReTestFailure(f"{name} documentation lookup is ambiguous at its ending")
    if end <= begin:
        raise StaticReTestFailure(f"{name} documentation markers no longer enclose the claim")
    return text[begin + len(begin_marker) : end]


def _markdown_table(section: str, header: tuple[str, ...], consequence: str) -> list[tuple[str, ...]]:
    raw_lines = section.splitlines()
    parsed_by_line: dict[int, tuple[str, ...]] = {}
    for line_index, raw_line in enumerate(raw_lines):
        line = raw_line.strip()
        if line.startswith("|") and line.endswith("|"):
            parsed_by_line[line_index] = tuple(
                cell.strip() for cell in line[1:-1].split("|")
            )
    if not parsed_by_line:
        raise StaticReTestFailure(f"{consequence}: no Markdown table rows were reached")
    header_indices = [index for index, row in parsed_by_line.items() if row == header]
    if len(header_indices) != 1:
        raise StaticReTestFailure(
            f"{consequence}: table header lookup is absent or ambiguous: {header_indices!r}"
        )
    start = header_indices[0]
    separator = parsed_by_line.get(start + 1)
    if separator is None or not all(
        re.fullmatch(r":?-+:?", cell) for cell in separator
    ):
        raise StaticReTestFailure(f"{consequence}: table separator no longer follows its header")
    rows: list[tuple[str, ...]] = []
    for line_index in range(start + 2, len(raw_lines)):
        row = parsed_by_line.get(line_index)
        if row is None:
            break
        if len(row) != len(header):
            break
        if all(re.fullmatch(r":?-+:?", cell) for cell in row):
            break
        rows.append(row)
    if not rows:
        raise StaticReTestFailure(f"{consequence}: table has no claim rows")
    return rows


def _require_tokens(text: str, tokens: tuple[str, ...], consequence: str) -> None:
    # Whitespace-insensitive anchors are used only for prose facts. Table shape and
    # source sequencing are checked by dedicated parsers/regexes below.
    flattened = " ".join(text.split())
    missing = [token for token in tokens if " ".join(token.split()) not in flattened]
    if missing:
        raise StaticReTestFailure(f"{consequence}: {missing!r}")


def _function(tree: ast.Module, name: str, consequence: str) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(matches) != 1:
        raise StaticReTestFailure(f"{consequence}: found {len(matches)} definitions")
    return matches[0]


def _cpp_function_body(text: str, signature: str, consequence: str) -> str:
    starts = [match.start() for match in re.finditer(re.escape(signature), text)]
    if len(starts) != 1:
        raise StaticReTestFailure(f"{consequence}: found {len(starts)} candidate definitions")
    opening = text.find("{", starts[0] + len(signature))
    if opening < 0:
        raise StaticReTestFailure(f"{consequence}: definition has no body")
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    raise StaticReTestFailure(f"{consequence}: definition has no balanced ending")


def _normalized_state(value: Any, consequence: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "index_a",
        "index_b",
        "divisor",
        "state_words",
    }:
        raise StaticReTestFailure(f"{consequence}: complete native RNG state is absent")
    words = value["state_words"]
    if not isinstance(words, list) or len(words) != RNG_WORD_COUNT:
        raise StaticReTestFailure(f"{consequence}: the full 55-word stream was not recorded")
    if any(type(word) is not int or not 0 <= word <= RNG_MASK for word in words):
        raise StaticReTestFailure(f"{consequence}: a stream word escaped the retail 30-bit state")
    if (
        type(value["index_a"]) is not int
        or type(value["index_b"]) is not int
        or not 0 <= value["index_a"] < RNG_WORD_COUNT
        or not 0 <= value["index_b"] < RNG_WORD_COUNT
        or value["divisor"] != RNG_DIVISOR
    ):
        raise StaticReTestFailure(f"{consequence}: ring indices or object-local divisor drifted")
    return {
        "index_a": value["index_a"],
        "index_b": value["index_b"],
        "divisor": value["divisor"],
        "state_words": list(words),
    }


def _seeded_state(seed: int) -> dict[str, Any]:
    words = [seed & RNG_MASK, 1]
    while len(words) < RNG_WORD_COUNT:
        words.append((words[-1] + words[-2]) & RNG_MASK)
    return {
        "index_a": 0,
        "index_b": 31,
        "divisor": RNG_DIVISOR,
        "state_words": words,
    }


def _stream_word(state: dict[str, Any]) -> int:
    index_a = state["index_a"]
    index_b = state["index_b"]
    words = state["state_words"]
    result = (words[index_a] + words[index_b]) & RNG_MASK
    words[index_a] = result
    state["index_a"] = (index_a + 1) % RNG_WORD_COUNT
    state["index_b"] = (index_b + 1) % RNG_WORD_COUNT
    return result


def _bounded_integer(state: dict[str, Any], requested_bound: int) -> int:
    if requested_bound == 0:
        return 0
    bound = abs(requested_bound)
    power = 2
    while power < bound:
        power <<= 1
    return ((_stream_word(state) >> 6) & (power - 1)) % bound


def _state_sha256(state: dict[str, Any]) -> str:
    payload = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _replay_rolls(
    before_value: Any,
    rolls_value: Any,
    after_value: Any,
    consequence: str,
    *,
    allow_empty: bool,
) -> int:
    state = _normalized_state(before_value, f"{consequence} boundary before")
    expected_after = _normalized_state(after_value, f"{consequence} boundary after")
    if not isinstance(rolls_value, list):
        raise StaticReTestFailure(f"{consequence}: roll trace is not a list")
    if not rolls_value:
        if not allow_empty:
            raise StaticReTestFailure(f"{consequence}: no live rolls were reached")
        if state != expected_after:
            raise StaticReTestFailure(f"{consequence}: an empty trace still advanced the stream")
        return 0

    for roll_index, roll in enumerate(rolls_value, start=1):
        if not isinstance(roll, dict):
            raise StaticReTestFailure(f"{consequence}: roll {roll_index} lost its trace object")
        expected_keys = {
            "ordinal",
            "thread_id",
            "bound",
            "return_address",
            "label",
            "output",
            "state_before_index_a",
            "state_before_index_b",
            "state_before_sha256",
            "state_after_index_a",
            "state_after_index_b",
            "state_after_sha256",
        }
        if not expected_keys.issubset(roll):
            raise StaticReTestFailure(
                f"{consequence}: roll {roll_index} lost address, bound, output, or state hashes"
            )
        if (
            roll["state_before_index_a"] != state["index_a"]
            or roll["state_before_index_b"] != state["index_b"]
            or roll["state_before_sha256"] != _state_sha256(state)
        ):
            raise StaticReTestFailure(
                f"{consequence}: roll {roll_index} no longer begins at its recorded stream state"
            )
        output = _bounded_integer(state, roll["bound"])
        if output != roll["output"]:
            raise StaticReTestFailure(
                f"{consequence}: roll {roll_index} output no longer replays bit-exact"
            )
        if (
            roll["state_after_index_a"] != state["index_a"]
            or roll["state_after_index_b"] != state["index_b"]
            or roll["state_after_sha256"] != _state_sha256(state)
        ):
            raise StaticReTestFailure(
                f"{consequence}: roll {roll_index} no longer ends at its recorded stream state"
            )
    if state != expected_after:
        raise StaticReTestFailure(f"{consequence}: final state no longer follows every recorded roll")
    return len(rolls_value)


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _f32_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _native_weights(bound: int) -> list[int]:
    power = 2
    while power < bound:
        power <<= 1
    result = [0] * bound
    for masked in range(power):
        result[masked % bound] += 1
    return result


def test_native_loot_golden_provenance_and_recorder_contract_are_pinned() -> str:
    assert_recorded_hash_matches_file(
        FIXTURE_SHA256, FIXTURE, "native loot standalone live golden"
    )
    document = _fixture()
    if document.get("schema") != "solomon-dark-native-loot-goldens-v1":
        raise StaticReTestFailure("native loot consumers lost the reviewed golden schema")
    if document.get("recorded_live") is not True:
        raise StaticReTestFailure("native loot outcomes are no longer declared as live retail evidence")
    if document.get("source_revision") != SOURCE_REVISION:
        raise StaticReTestFailure("native loot provenance lost the exact capture revision")

    header = document.get("header")
    expected_header_keys = {
        "allowed_udp_ports",
        "audio_disabled",
        "capture_method",
        "client_retail_executable_sha256",
        "executable_paths",
        "instance_prefix",
        "process_ids",
        "recorder_path",
        "recorder_sha256",
        "release_launcher_sha256",
        "release_loader_sha256",
        "retail_executable_sha256",
        "source_revision",
        "source_revision_derived_by",
        "udp_ports",
        "worktree_status_at_capture",
    }
    if not isinstance(header, dict) or set(header) != expected_header_keys:
        raise StaticReTestFailure("native loot live evidence lost its standard provenance header")
    expected_hashes = {
        "retail_executable_sha256": RETAIL_SHA256,
        "client_retail_executable_sha256": RETAIL_SHA256,
        "release_loader_sha256": RELEASE_LOADER_SHA256,
        "release_launcher_sha256": RELEASE_LAUNCHER_SHA256,
    }
    if any(header.get(key) != value for key, value in expected_hashes.items()):
        raise StaticReTestFailure("native loot provenance no longer identifies the captured binaries")
    if (
        header.get("source_revision") != SOURCE_REVISION
        or header.get("source_revision_derived_by") != "git rev-parse HEAD in recorder"
        or header.get("recorder_path") != "tests/re/record_live_loot_goldens.py"
        or header.get("recorder_sha256") != RECORDER_SHA256
    ):
        raise StaticReTestFailure("native loot recorder provenance no longer derives its own source identity")
    assert_recorded_hash_matches_file(
        header["recorder_sha256"], RECORDER, "loot recorder provenance"
    )
    if (
        header.get("instance_prefix") != "loot-g7-capture"
        or header.get("udp_ports") != {"host": 52391, "client": 52392}
        or header.get("allowed_udp_ports") != list(range(52391, 52399))
        or header.get("audio_disabled") is not True
    ):
        raise StaticReTestFailure("native loot capture escaped its owned instance, ports, or audio-off boundary")
    process_ids = header.get("process_ids")
    executable_paths = header.get("executable_paths")
    if (
        not isinstance(process_ids, dict)
        or set(process_ids) != {"host", "client"}
        or any(type(pid) is not int or pid <= 0 for pid in process_ids.values())
        or process_ids["host"] == process_ids["client"]
        or not isinstance(executable_paths, dict)
        or set(executable_paths) != {"host", "client"}
    ):
        raise StaticReTestFailure("native loot provenance lost two distinct owned process witnesses")
    expected_path_parts = {
        "host": "\\loot-g7-capture-host\\stage\\solomondark.exe",
        "client": "\\loot-g7-capture-client\\stage\\solomondark.exe",
    }
    if any(expected_path_parts[role] not in executable_paths[role].lower() for role in expected_path_parts):
        raise StaticReTestFailure("native loot executable provenance no longer names both staged instances")

    contract = document.get("capture_contract")
    expected_capture_contract = {
        "actor_private_stream_required": True,
        "allowed_instance_prefix": "loot-*",
        "allowed_udp_ports": list(range(52391, 52399)),
        "enemy_families": ["Skeleton", "Zombie", "Wraith"],
        "enemy_kill_count": 100,
        "full_private_state_words_per_kill": 55,
        "magnet_trajectory_count": 3,
        "sd_rng_set_seed_used": False,
        "two_participant_credit_case": True,
    }
    if contract != expected_capture_contract:
        raise StaticReTestFailure("native loot fixture lost its complete live-capture census")

    doc = _read(DOC, "the native loot implementation document is absent")
    hash_matches = re.findall(
        r"committed fixture's reviewed SHA-256 is\s*`([0-9a-f]{64})`", doc
    )
    if hash_matches != [FIXTURE_SHA256]:
        raise StaticReTestFailure("native loot documentation must name one unambiguous reviewed fixture hash")

    recorder_text = _read(RECORDER, "the native loot golden no longer has a reviewable recorder")
    try:
        tree = ast.parse(recorder_text)
    except SyntaxError as error:
        raise StaticReTestFailure(f"native loot recorder is not parseable Python: {error}") from error
    main = _function(tree, "main", "native loot recorder CLI lookup is ambiguous")
    cli_flags: list[str] = []
    for node in ast.walk(main):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            cli_flags.append(node.args[0].value)
    if cli_flags != ["--smoke", "--output", "--raw-output"]:
        raise StaticReTestFailure("native loot recorder CLI accepted a provenance override or lost a capture option")

    run_capture = _function(tree, "run_capture", "native loot run_capture lookup is ambiguous")
    revision_assignments = [
        node
        for node in ast.walk(run_capture)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "source_revision" for target in node.targets)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "git_output"
        and [ast.literal_eval(arg) for arg in node.value.args] == ["rev-parse", "HEAD"]
    ]
    if len(revision_assignments) != 1:
        raise StaticReTestFailure("native loot recorder no longer derives HEAD exactly once inside run_capture")
    provenance = _function(tree, "fixture_provenance", "native loot provenance builder lookup is ambiguous")
    provenance_source = ast.get_source_segment(recorder_text, provenance) or ""
    _require_tokens(
        provenance_source,
        (
            '"recorder_sha256": windows_sha256(Path(__file__))',
            '"retail_executable_sha256": windows_sha256(host_executable)',
            '"client_retail_executable_sha256": windows_sha256(client_executable)',
            '"release_loader_sha256": windows_sha256(LOADER)',
            '"release_launcher_sha256": windows_sha256(LAUNCHER)',
        ),
        "native loot recorder stopped deriving committed and binary provenance itself",
    )
    wait_until = _function(tree, "wait_until", "native loot readiness probe lookup is ambiguous")
    while_nodes = [node for node in ast.walk(wait_until) if isinstance(node, ast.While)]
    if len(while_nodes) != 1 or not while_nodes[0].body:
        raise StaticReTestFailure("native loot readiness wait lost its one bounded probe loop")
    first_wait_statement = while_nodes[0].body[0]
    if not (
        isinstance(first_wait_statement, ast.Expr)
        and isinstance(first_wait_statement.value, ast.Call)
        and isinstance(first_wait_statement.value.func, ast.Name)
        and first_wait_statement.value.func.id == "assert_pair_runnable"
    ):
        raise StaticReTestFailure("native loot readiness wait no longer proves runnability before each probe")
    wait_source = ast.get_source_segment(recorder_text, wait_until) or ""
    if "BROKEN:" not in wait_source or "BUSY_TIMEOUT:" not in wait_source:
        raise StaticReTestFailure("native loot readiness probe no longer distinguishes broken from busy")
    cleanup_pattern = re.compile(
        r"finally:\s*try:\s*if launch is not None:.*?"
        r"stopped_ids == set\(process_ids\).*?"
        r"raw\[\"processes_after\"\] = snapshot_owned_target_processes\(\).*?"
        r"not raw\[\"processes_after\"\]",
        re.DOTALL,
    )
    if cleanup_pattern.search(recorder_text) is None:
        raise StaticReTestFailure("native loot exact-owned-PID cleanup sequencing regex no longer matches")
    return "reviewed fixture, binaries, self-derived recorder provenance, and fail-closed capture lifecycle are pinned"


def test_native_loot_actor_private_seed_lifecycle_replays_bit_exact() -> str:
    document = _fixture()
    recovered = document.get("recovered_contract")
    expected_private_contract = {
        "actor_seed_draw_bound": 10000000,
        "actor_seed_draw_stream": "active process-global stream through [0x00818B08]",
        "constructor": "0x00401110",
        "integer_function": "0x00401170",
        "seed_field": "actor+0x1C0",
        "seed_function": "0x00401120",
        "size_bytes": 232,
    }
    if not isinstance(recovered, dict) or recovered.get("selector", {}).get("private_stream") != expected_private_contract:
        raise StaticReTestFailure("actor-private loot stream no longer pins its seed source and 0xE8 lifecycle")

    doc = _read(DOC, "the native loot implementation document is absent")
    seed_section = _unique_section(doc, "LOOT_ACTOR_SEED_LIFECYCLE")
    seed_rows = _markdown_table(
        seed_section,
        ("Family", "Type", "Seed at death"),
        "per-family loot seed lifecycle",
    )
    expected_seed_rows = [
        ("Badguy", "1000 / `0x3E8`", "Base-constructor shared `Integer(10000000)`; no later writer recovered."),
        ("Skeleton", "1001 / `0x3E9`", "Slot-0 action scheduling at `0x00473980` replaces `+0x1C0` with shared `Integer(10000000)` at `0x004739D1`."),
        ("SkeletonArcher", "1002 / `0x3EA`", "Slot-0 scheduling at `0x00473B40` replaces it with shared `Integer(10000000)` at `0x00473B60`."),
        ("SkeletonMage", "1003 / `0x3EB`", "Slot-0 scheduling at `0x00478290` replaces it at `0x004782B7`; cast scheduling in `0x00490860` replaces it again at `0x004909D0`. Both use shared `Integer(10000000)`."),
        ("Imp", "1004 / `0x3EC`", "Base-constructor seed only."),
        ("Zombie", "1006 / `0x3EE`", "Base-constructor seed only."),
        ("Wraith", "1007 / `0x3EF`", "Base-constructor seed only."),
        ("DemonSkull", "1008 / `0x3F0`", "Base seed, then scheduler `0x00474930` increments `+0x1C0` by exactly one rather than drawing the shared stream."),
        ("Demon", "1009 / `0x3F1`", "Base-constructor seed only."),
        ("DireFaculty", "1010 / `0x3F2`", "Base-constructor seed only."),
        ("Heartmonger", "1011 / `0x3F3`", "Base-constructor seed only."),
        ("Coffin", "1013 / `0x3F5`", "Base-constructor seed only."),
        ("GreenImp", "2044 / `0x7FC`", "Base-constructor seed only."),
        ("Spider", "2057 / `0x809`", "Base-constructor seed only."),
        ("Portal", "5021 / `0x139D`", "Base-constructor seed only."),
    ]
    if seed_rows != expected_seed_rows:
        raise StaticReTestFailure("per-family loot seed lifecycle table changed or became incomplete")
    _require_tokens(
        seed_section,
        (
            "GoodImp `1005/0x3ED` and Crow `1012/0x3F4` never enter the hostile reward path",
            "Maggot `2045/0x7FD` and Cocoon `2058/0x80A` call the death path but return",
            "destroy private_rng // no state copied back",
        ),
        "actor-private loot lifecycle lost its non-participant families or one-shot destruction rule",
    )

    kills = document.get("enemy_kills")
    if not isinstance(kills, list) or len(kills) != 100:
        raise StaticReTestFailure("actor-private replay must reach exactly 100 recorded deaths")
    expected_families = Counter({"Skeleton": 34, "Zombie": 33, "Wraith": 33})
    if Counter(row.get("enemy_family") for row in kills if isinstance(row, dict)) != expected_families:
        raise StaticReTestFailure("actor-private replay lost one of three named enemy-family witnesses")
    if [row.get("kill_index") for row in kills] != list(range(1, 101)):
        raise StaticReTestFailure("actor-private replay lost contiguous per-kill identity")
    if (
        (kills[0].get("enemy_family"), kills[0].get("family_index")) != ("Skeleton", 1)
        or (kills[33].get("enemy_family"), kills[33].get("family_index")) != ("Skeleton", 34)
        or (kills[34].get("enemy_family"), kills[34].get("family_index")) != ("Zombie", 1)
        or (kills[66].get("enemy_family"), kills[66].get("family_index")) != ("Zombie", 33)
        or (kills[67].get("enemy_family"), kills[67].get("family_index")) != ("Wraith", 1)
        or (kills[99].get("enemy_family"), kills[99].get("family_index")) != ("Wraith", 33)
    ):
        raise StaticReTestFailure("actor-private replay lost named first/last witnesses for each family")
    seeds = [row.get("private_stream", {}).get("seed") for row in kills]
    if (
        any(type(seed) is not int or not 0 <= seed < 10000000 for seed in seeds)
        or len(set(seeds)) != 100
        or max(seeds) <= 1000000
    ):
        raise StaticReTestFailure("actor-private seed corpus no longer proves the ten-million draw bound")
    private_roll_counts = Counter(len(row.get("private_stream", {}).get("rolls", [])) for row in kills)
    if private_roll_counts != Counter({0: 7, 4: 77, 5: 6, 8: 10}):
        raise StaticReTestFailure("actor-private replay lost its short-circuit, base, gold, or orb trace census")
    shared_roll_counts = [len(row.get("shared_stream", {}).get("rolls", [])) for row in kills]
    if min(shared_roll_counts) != 78 or max(shared_roll_counts) != 241:
        raise StaticReTestFailure("shared-stream replay no longer reaches live constructor/materializer traffic")

    private_roll_total = 0
    shared_roll_total = 0
    expected_types = {"Skeleton": 1001, "Zombie": 1006, "Wraith": 1007}
    expected_post_updates = {
        "Skeleton": [
            {
                "function": "0x00473980",
                "rule": "slot-0 action scheduling replaces actor+0x1C0 with active-shared Integer(10000000, false)",
                "write_site": "0x004739D1",
            }
        ],
        "Zombie": [],
        "Wraith": [],
    }
    for row in kills:
        kill_index = row["kill_index"]
        family = row["enemy_family"]
        if row.get("enemy_type_id") != expected_types[family]:
            raise StaticReTestFailure(f"kill {kill_index} no longer identifies its enemy family type")
        timestamps = row.get("timestamps")
        if (
            not isinstance(timestamps, dict)
            or type(timestamps.get("app_tick_before")) is not int
            or type(timestamps.get("app_tick_after")) is not int
            or timestamps["app_tick_after"] < timestamps["app_tick_before"]
            or not isinstance(timestamps.get("captured_at_utc"), str)
        ):
            raise StaticReTestFailure(f"kill {kill_index} lost its live tick and UTC stamps")
        lifecycle = row.get("actor_seed_lifecycle")
        expected_constructor = {
            "actor": family,
            "base_constructor": "Badguy 0x00473390",
            "draw": {
                "bound": 10000000,
                "integer_function": "0x00401170",
                "signed": False,
                "stream": "active process-global stream through [0x00818B08]",
            },
            "write_site": "0x0047345E -> actor+0x1C0",
        }
        if (
            not isinstance(lifecycle, dict)
            or lifecycle.get("constructor_seed") != expected_constructor
            or lifecycle.get("captured_actor_field") != "actor+0x1C0"
            or lifecycle.get("death_capture") != "live actor+0x1C0 read immediately before 0x0047C070"
            or lifecycle.get("selector_constructs_stack_state_at") != "0x0047C0CF"
            or lifecycle.get("selector_seeds_stack_state_at") != "0x0047C0DF -> 0x00401120"
            or lifecycle.get("post_constructor_updates") != expected_post_updates[family]
        ):
            raise StaticReTestFailure(f"kill {kill_index} seed lifecycle no longer names its actor writers")
        private = row.get("private_stream")
        if not isinstance(private, dict) or private.get("seed") != lifecycle.get("seed"):
            raise StaticReTestFailure(f"kill {kill_index} private seed no longer equals the death-time actor field")
        seeded = _seeded_state(private["seed"])
        if _normalized_state(private.get("before"), f"kill {kill_index} private before") != seeded:
            raise StaticReTestFailure(f"kill {kill_index} private seed ladder no longer starts from death actor seed")
        private_roll_total += _replay_rolls(
            private.get("before"),
            private.get("rolls"),
            private.get("after"),
            f"kill {kill_index} actor-private stream",
            allow_empty=True,
        )
        shared = row.get("shared_stream")
        if not isinstance(shared, dict):
            raise StaticReTestFailure(f"kill {kill_index} shared materializer stream is absent")
        shared_roll_total += _replay_rolls(
            shared.get("before"),
            shared.get("rolls"),
            shared.get("after"),
            f"kill {kill_index} active-shared stream",
            allow_empty=False,
        )
    if private_roll_total != 418:
        raise StaticReTestFailure(f"actor-private replay did not examine all 418 rolls: {private_roll_total}")
    if shared_roll_total != 13416:
        raise StaticReTestFailure(f"active-shared replay did not examine all 13,416 rolls: {shared_roll_total}")
    return "100 actor seeds independently reconstruct 418 private and 13,416 shared live RNG transitions"


def test_native_loot_selector_tables_and_decision_traces_are_pinned() -> str:
    document = _fixture()
    selector = document.get("recovered_contract", {}).get("selector")
    expected_selector = {
        "base_bounds_by_policy": {
            "gold_after_x2": {"0": 22, "1": 44, "2": 11, "3": 0, "4": None, "5": 22},
            "item_before_arena_modifier": {"0": 360, "1": 720, "2": 180, "3": 0, "4": None},
            "orb": {"0": 8, "1": 16, "2": 4, "3": 0, "4": None},
            "potion": {"0": 400, "1": 800, "2": 200, "3": 0, "4": None},
        },
        "candidate_order": CATEGORY_ORDER,
        "function": "0x0047C070",
        "goodie_crate": {
            "buckets": {
                "0..3": "five health potions",
                "10": "definition-backed item selector 4",
                "11..12": "three Book of Skill items, subtype 2 or 3 independently",
                "13..16": "explicit gold: 500, 800, or 1100",
                "17": "six-potion bundle: 5,0,1,4,2,2",
                "4..7": "six mana potions",
                "8..9": "two or three random equipment items",
            },
            "seed_draw": {"bound": 1000, "stored_field": "+0x148", "stream": "active shared"},
            "selector": "stored_seed % 18",
        },
        "private_stream": {
            "actor_seed_draw_bound": 10000000,
            "actor_seed_draw_stream": "active process-global stream through [0x00818B08]",
            "constructor": "0x00401110",
            "integer_function": "0x00401170",
            "seed_field": "actor+0x1C0",
            "seed_function": "0x00401120",
            "size_bytes": 232,
        },
        "quick_potion_shared_gate": {"combined_probability": "1/16", "draws": [[2, 0], [10, 1]]},
    }
    if selector != expected_selector:
        raise StaticReTestFailure("loot selector recovered tables, private stream, or candidate order changed")

    doc = _read(DOC, "the native loot implementation document is absent")
    section = _unique_section(doc, "LOOT_SELECTOR_TABLES")
    choice_rows = _markdown_table(
        section,
        ("Candidate count", "Index weights"),
        "native-biased candidate-choice weights",
    )
    if choice_rows != [
        ("1", "`1`"),
        ("2", "`1,1` out of 2"),
        ("3", "`2,1,1` out of 4"),
        ("4", "`1,1,1,1` out of 4"),
        ("5", "`2,2,2,1,1` out of 8"),
        ("6", "`2,2,1,1,1,1` out of 8"),
    ]:
        raise StaticReTestFailure("native-biased candidate-choice distribution is no longer pinned for sizes 1 through 6")
    decision_rows = _markdown_table(
        section,
        ("Order", "Candidate", "Gate and exact bound before final truncation", "Stream/target"),
        "enemy drop decision table",
    )
    if [(row[0], row[1], row[3]) for row in decision_rows] != [
        ("1", "key", "private `Integer(bound) == 2`"),
        ("2", "orb", "private target 1"),
        ("3", "gold", "private target 1"),
        ("4", "item", "private target 1"),
        ("5", "potion", "private target 1"),
        ("6", "powerup", "private target 1"),
    ]:
        raise StaticReTestFailure("enemy drop decision sequence no longer pins six ordered private targets")
    decision_text = " ".join(cell for row in decision_rows for cell in row)
    _require_tokens(
        decision_text,
        (
            "* 100)",
            "`8/16/4`",
            "`22/44/11`",
            "`360/720/180`",
            "`400/800/200`",
            "then multiply by 9",
            "Arena vtable `+0x130`",
            "Arena `+0x134`",
            "Arena `+0x13C`",
            "Arena `+0x138`",
        ),
        "enemy drop decision table lost a bound, multiplier, or Arena virtual",
    )

    kills = document.get("enemy_kills")
    if not isinstance(kills, list) or len(kills) != 100:
        raise StaticReTestFailure("selector trace contract must reach exactly 100 live kills")
    standard_context = {
        "active_player_index": "255",
        "actor.participant_slot": "0",
        "arena.current_level": "-1",
        "arena.disable_mask": "0",
        "arena.level": "0",
        "arena.level_ceiling": "100",
        "arena.level_floor": "0",
        "arena.mode": "0",
        "config.special_mode": "0",
        "policy.gold": "0",
        "policy.item": "0",
        "policy.orb": "0",
        "policy.potion": "0",
        "policy.powerup": "0",
        "policy.specific_item": "0",
        "progression.0x804": "1.0",
        "progression.0x808": "1.0",
        "progression.0x80C": "1.0",
        "progression.0x810": "1.0",
        "progression.0x814_u8": "0",
        "progression.0xBC": "1.0",
        "progression.0xC0": "1.0",
        "progression.0xCC": "1.25",
        "progression.level": "1",
    }
    short_indices = [2, 16, 19, 39, 64, 71, 83]
    if [row["kill_index"] for row in kills if not row.get("private_stream", {}).get("rolls")] != short_indices:
        raise StaticReTestFailure("selector short-circuit witnesses no longer name all seven emergency-health hits")

    outcome_counts: Counter[Any] = Counter()
    materialized_counts: Counter[str] = Counter()
    for row in kills:
        kill_index = row["kill_index"]
        context = row.get("table_context")
        if not isinstance(context, dict) or any(context.get(key) != value for key, value in standard_context.items()):
            raise StaticReTestFailure(f"kill {kill_index} no longer records the table inputs used by its rolls")
        selector_trace = row.get("selector")
        if (
            not isinstance(selector_trace, dict)
            or selector_trace.get("roll_order") != CATEGORY_ORDER
            or selector_trace.get("arena_disable_mask") != 0
            or selector_trace.get("policies")
            != {"gold": 0, "item": 0, "orb": 0, "potion": 0, "powerup": 0, "specific_item": 0}
        ):
            raise StaticReTestFailure(f"kill {kill_index} no longer records the consulted selector tables")
        private_rolls = row["private_stream"]["rolls"]
        quick_rolls = row["shared_stream"].get("quick_potion_rolls")
        if not isinstance(quick_rolls, list) or len(quick_rolls) not in {1, 2}:
            raise StaticReTestFailure(f"kill {kill_index} lost the shared emergency-potion gate trace")
        quick_signature = [(roll.get("bound"), roll.get("output")) for roll in quick_rolls]
        if not private_rolls:
            if quick_signature != [(2, 0), (10, 1)]:
                raise StaticReTestFailure(f"kill {kill_index} private short circuit no longer follows the 1/16 shared gate")
            expected_eligible: list[str] = []
        else:
            direct = private_rolls[:4]
            if selector_trace.get("effective_roll_bounds") != {
                "gold": 22,
                "item": 288000,
                "orb": 8,
                "potion": 400,
            }:
                raise StaticReTestFailure(f"kill {kill_index} no longer records its four effective table bounds")
            if [(roll.get("label"), roll.get("bound")) for roll in direct] != [
                ("orb_eligibility", 8),
                ("gold_eligibility", 22),
                ("item_eligibility", 288000),
                ("potion_eligibility", 400),
            ]:
                raise StaticReTestFailure(f"kill {kill_index} private roll order or effective table bounds changed")
            expected_eligible = [
                category
                for category, roll in zip(("orb", "gold", "item", "potion"), direct)
                if roll["output"] == 1
            ]
        if not private_rolls and selector_trace.get("effective_roll_bounds") != {}:
            raise StaticReTestFailure(f"kill {kill_index} short circuit consulted tables after returning")
        if selector_trace.get("eligible_candidates") != expected_eligible:
            raise StaticReTestFailure(f"kill {kill_index} eligibility no longer follows target-1 table results")
        expected_selected: str | None = None
        if expected_eligible:
            choice = private_rolls[4]
            if (
                choice.get("label") != "candidate_choice"
                or choice.get("bound") != len(expected_eligible)
                or selector_trace.get("candidate_choice_index") != choice.get("output")
            ):
                raise StaticReTestFailure(f"kill {kill_index} candidate choice no longer consumes the private stream")
            expected_selected = expected_eligible[choice["output"]]
        elif selector_trace.get("candidate_choice_index") is not None:
            raise StaticReTestFailure(f"kill {kill_index} invented a choice for an empty candidate table")
        if selector_trace.get("selected_category") != expected_selected:
            raise StaticReTestFailure(f"kill {kill_index} selected category no longer follows its private choice")
        rewards = row.get("materialized_rewards")
        if not isinstance(rewards, list) or len(rewards) != (1 if expected_selected else 0):
            raise StaticReTestFailure(f"kill {kill_index} materialization no longer matches its one-category decision")
        reward_families = [reward.get("family") for reward in rewards]
        if reward_families != ([expected_selected] if expected_selected else []):
            raise StaticReTestFailure(f"kill {kill_index} materialized a family other than its selected category")
        outcome_counts[expected_selected] += 1
        materialized_counts.update(reward_families)
    if outcome_counts != Counter({None: 84, "orb": 10, "gold": 6}):
        raise StaticReTestFailure("100-kill outcome census no longer pins 84 none, 10 orb, and 6 gold")
    if materialized_counts != Counter({"orb": 10, "gold": 6}):
        raise StaticReTestFailure("materialized reward census no longer agrees with all 16 selected drops")
    return "six-category order, biased choice weights, effective tables, and all 100 decisions are pinned"


def test_native_loot_amounts_and_non_enemy_sources_are_pinned() -> str:
    document = _fixture()
    amounts = document.get("recovered_contract", {}).get("amounts")
    expected_amounts = {
        "bonus_kind_weights": {"0_bonus_skill": "1/4", "1_random_skill": "1/8", "2_damage_x4": "5/8"},
        "enemy_potion_subtypes": {"health_0": "1/2", "invincibility_6": "not in stock selector", "mana_1": "1/2"},
        "gold": {
            "chunk_maximum": 25,
            "level_addend": "max(1,trunc(level/5))",
            "level_draw_bound": "trunc(level/2)+6",
            "progression_multiplier_field": "+0xC0",
        },
        "orb_raw_value": {
            "health_scale": 25.0,
            "kind_weights": {"health": "1/4", "mana": "3/4"},
            "mana_scale": 40.0,
            "maximum_inclusive": 0.7,
            "minimum": 0.25,
        },
    }
    if amounts != expected_amounts:
        raise StaticReTestFailure("loot amount, orb, potion, or Bonus distributions changed")

    doc = _read(DOC, "the native loot implementation document is absent")
    amount_section = _unique_section(doc, "LOOT_AMOUNT_TABLES")
    gold_rows = _markdown_table(
        amount_section,
        ("Total gold", "Weight"),
        "stock level-zero gold distribution",
    )
    if gold_rows != [
        ("1", "`1/16`"),
        ("2", "`7/16`"),
        ("3", "`1/8`"),
        ("4", "`1/8`"),
        ("5", "`1/8`"),
        ("6", "`1/8`"),
    ]:
        raise StaticReTestFailure("stock level-zero gold amount distribution is no longer exact")
    base_weights = _native_weights(6)
    correction_weights = _native_weights(3)
    derived_sixteenths = [0] * 6
    derived_sixteenths[0] = base_weights[0] * correction_weights[2] // 2
    derived_sixteenths[1] = (
        base_weights[0] * sum(correction_weights[:2]) // 2
        + base_weights[1] * 2
    )
    for output in range(2, 6):
        derived_sixteenths[output] = base_weights[output] * 2
    if derived_sixteenths != [1, 7, 2, 2, 2, 2]:
        raise StaticReTestFailure("stock gold distribution no longer follows native-biased bound-6 correction")
    item_mode_rows = _markdown_table(
        amount_section,
        ("Mode", "Definition rarities entered"),
        "runtime ItemSet/UIDGroup selector modes",
    )
    if item_mode_rows != [
        ("0", "common always; rare when shared `Integer(15) == 1`; epic when shared `Integer(20) == 1`"),
        ("1", "common"),
        ("2", "rare"),
        ("3", "epic"),
        ("4", "rare and epic"),
    ]:
        raise StaticReTestFailure("runtime item/equipment selector rarity lanes are no longer pinned")
    _require_tokens(
        amount_section,
        (
            "`Arena_SelectAndDropItem (0x0046A360)`",
            "appends exactly 110 placeholder entries",
            "random-equipment factory `0x004645B0`",
            "requested level is greater than 18",
            "`Integer(2)==1`",
            "generated item level `+0x5A = 8`",
            "Goodie's definition-backed bucket instead calls `0x0046BDE0` with mode 4",
            "invincibility subtype 6 is an additive `HookEnemyDeath` path",
            "not inserted into this stock 0/1 selector",
            "then float32 addition of `0.25`",
        ),
        "amount contract lost item-store selection, invincibility separation, or float behavior",
    )

    kills = document.get("enemy_kills")
    if not isinstance(kills, list) or len(kills) != 100:
        raise StaticReTestFailure("amount replay must reach all 100 recorded deaths")
    rewards = [reward for row in kills for reward in row.get("materialized_rewards", [])]
    if len(rewards) != 16:
        raise StaticReTestFailure("amount replay no longer reaches all 16 materialized reward witnesses")
    orb_rows = [row for row in kills if row.get("selector", {}).get("selected_category") == "orb"]
    gold_rows_live = [row for row in kills if row.get("selector", {}).get("selected_category") == "gold"]
    if len(orb_rows) != 10 or len(gold_rows_live) != 6:
        raise StaticReTestFailure("amount replay lost its ten orb or six gold live witnesses")
    observed_orb_kinds: Counter[int] = Counter()
    for row in orb_rows:
        kill_index = row["kill_index"]
        rolls = row["private_stream"]["rolls"]
        if len(rolls) != 8 or [roll["bound"] for roll in rolls[-3:]] != [3, 100001, 100001]:
            raise StaticReTestFailure(f"kill {kill_index} orb amount no longer consumes kind, value, and phase rolls")
        reward = row["materialized_rewards"][0]
        expected_kind = 0 if rolls[-3]["output"] == 1 else 1
        sampled = rolls[-2]["output"]
        expected_value = _f32(_f32(_f32(float(sampled)) / 100000.0) * _f32(0.45))
        expected_value = _f32(expected_value + _f32(0.25))
        if (
            reward.get("type_id") != 2011
            or reward.get("field_0x13c_u8") != expected_kind
            or _f32_bits(reward.get("field_0x140_f32")) != _f32_bits(expected_value)
            or reward.get("field_0x144_i32") != 900
        ):
            raise StaticReTestFailure(f"kill {kill_index} orb kind/value no longer follows its private float rolls")
        if not 0.25 <= reward["field_0x140_f32"] <= 0.70:
            raise StaticReTestFailure(f"kill {kill_index} orb value escaped the inclusive stock range")
        observed_orb_kinds[expected_kind] += 1
    if observed_orb_kinds != Counter({1: 8, 0: 2}):
        raise StaticReTestFailure("orb live witness census no longer contains both health and mana families")
    observed_gold = sorted(row["materialized_rewards"][0].get("field_0x140_i32") for row in gold_rows_live)
    if observed_gold != [2, 2, 2, 2, 2, 6]:
        raise StaticReTestFailure("gold amount live witnesses no longer pin five two-gold and one six-gold outcomes")
    if any(row["materialized_rewards"][0].get("type_id") != 2012 for row in gold_rows_live):
        raise StaticReTestFailure("gold amount witnesses no longer materialize the distinct type-2012 family")

    source_section = _unique_section(doc, "LOOT_SOURCE_TABLES")
    goodie_rows = _markdown_table(
        source_section,
        ("Selector", "Weight / 1024", "Contents and further shared rolls"),
        "Goodie/crate contents table",
    )
    if [(row[0], row[1]) for row in goodie_rows] != [
        ("0..3", "232"),
        ("4..7", "230"),
        ("8..9", "114"),
        ("10", "56"),
        ("11..12", "112"),
        ("13..16", "224"),
        ("17", "56"),
    ]:
        raise StaticReTestFailure("Goodie/crate weighted content buckets are no longer exact")
    remainders = Counter((masked % 1000) % 18 for masked in range(1024))
    if [remainders[index] for index in range(18)] != [58] * 6 + [57] * 4 + [56] * 8:
        raise StaticReTestFailure("Goodie/crate remainder distribution no longer follows native Integer(1000)")
    _require_tokens(
        source_section,
        (
            "`shared.Integer(1000)` at construction",
            "`stored_seed % 18`",
            "`5,0,1,4,2,2`",
            "Dig is not a stock reward source in that route",
            "No generic wave-end ground reward exists",
            "Types 2011, 2012, 2013, and 2038 do not reroll a category when ticked",
        ),
        "non-enemy source contract lost Goodie, ground actor, Dig, or wave-end behavior",
    )

    dig = document.get("dig_reward_sequence")
    if not isinstance(dig, dict) or dig.get("source_fixture_sha256") != HUB_FIXTURE_SHA256:
        raise StaticReTestFailure("embedded Dig recording no longer names its committed G8 source")
    assert_recorded_hash_matches_file(
        dig["source_fixture_sha256"], HUB_FIXTURE, "embedded Dig source fixture"
    )
    hub = _hub_fixture()
    dig_trials = hub.get("dig_trials")
    if not isinstance(dig_trials, list) or len(dig_trials) != 8:
        raise StaticReTestFailure("embedded Dig comparison no longer reaches all eight G8 trials")
    if dig.get("sequence") != dig_trials[0]:
        raise StaticReTestFailure("embedded Dig sequence diverged from the standalone G8 fixture")
    if dig.get("cross_trial_summary") != hub.get("observed_dig_distribution"):
        raise StaticReTestFailure("embedded Dig summary diverged from the standalone G8 fixture")
    summary = dig["cross_trial_summary"]
    if (
        summary.get("trial_count") != 8
        or summary.get("gold_deltas") != [0] * 8
        or summary.get("inventory_changed") != [False] * 8
        or summary.get("direct_yield_counts") != [0] * 8
        or summary.get("reward_actor_deltas") != [{"2011": 0, "2012": 0, "2013": 0, "2038": 0}] * 8
    ):
        raise StaticReTestFailure("Dig no-reward result no longer has eight independent zero-delta witnesses")
    return "gold/orb/potion/item/Bonus amounts and Goodie, Dig, ground, and wave-end sources are pinned"


def test_native_loot_physics_lifetimes_and_multiplayer_credit_are_pinned() -> str:
    document = _fixture()
    physics = document.get("recovered_contract", {}).get("physics")
    expected_physics = {
        "bonus": {"capture_radius_units_per_pickup_factor": 20.0, "despawn_ticks": 1200, "magnet": False},
        "gold": {
            "above_threshold_per_tick_gate": {"bound": 15, "probability": "1/16", "target": 1},
            "capture_radius_units_per_pickup_factor": 30.0,
            "despawn_timer": None,
            "enhanced_pickup_factor_threshold": 1.26,
            "magnet": False,
        },
        "orb": {
            "active_value_floor": 0.01,
            "capture_radius_units_per_pickup_factor": 20.0,
            "decay_per_tick": 0.002,
            "decay_start_ticks": 900,
            "movement_units_per_actor_tick": 1.5,
            "pull_radius_units_per_pickup_factor": 60.0,
        },
        "sack": {"capture_radius_units_per_pickup_factor": 30.0, "despawn_timer": None, "magnet": False},
        "world_registration": {"allocation_scan": 2048, "full_behavior": "registration fails; no loot eviction", "ids_per_owner_slot": 2047},
    }
    if physics != expected_physics:
        raise StaticReTestFailure("loot magnet, lifetime, capture, or field-cap constants changed")

    doc = _read(DOC, "the native loot implementation document is absent")
    physics_section = _unique_section(doc, "LOOT_PHYSICS_TABLE")
    physics_rows = _markdown_table(
        physics_section,
        ("Family", "Attraction and capture", "Lifetime"),
        "per-family pickup physics table",
    )
    if [row[0] for row in physics_rows] != ["Orb 2011", "Gold 2012", "Sack 2013", "Bonus 2038"]:
        raise StaticReTestFailure("per-family pickup physics table lost a distinct ground-reward family")
    physics_claims = {
        "Orb 2011": ("`60 * pickup_factor * orb_pull_multiplier`", "`20 * pickup_factor`", "exactly 1.5 units", "starts 900", "float32 0.002", "1024..1250 actor ticks"),
        "Gold 2012": ("No magnet", "`30 * pickup_factor`", "`Integer(15) == 1`", "No despawn timer"),
        "Sack 2013": ("No magnet", "`30 * pickup_factor`", "multiplies velocity by 1.5", "No despawn timer"),
        "Bonus 2038": (
            "No magnet",
            "`20 * pickup_factor`",
            "starts 1200",
            "101 fade updates",
            "update 1300",
        ),
    }
    rows_by_family = {row[0]: row for row in physics_rows}
    if len(rows_by_family) != 4:
        raise StaticReTestFailure("per-family pickup physics lookup is ambiguous because a family is duplicated")
    for family, tokens in physics_claims.items():
        _require_tokens(" ".join(rows_by_family[family]), tokens, f"{family} physics constants changed")
    _require_tokens(
        physics_section,
        (
            "Scans participant slots 0,1,2,3 in ascending order",
            "health/mana write is guarded by `slot_index == 0`",
            "IDs 1..2047 independently per owner slot",
            "scans at most 2048 candidates",
            "never evicts an existing drop",
        ),
        "stock slot credit or field-cap behavior is no longer explicit",
    )

    trajectories = document.get("magnet_trajectories")
    if not isinstance(trajectories, list) or len(trajectories) != 3:
        raise StaticReTestFailure("orb magnet corpus must retain exactly three live trajectories")
    if [(row.get("trajectory_index"), row.get("kind"), len(row.get("samples", []))) for row in trajectories] != [
        (1, "health_orb", 23),
        (2, "mana_orb", 15),
        (3, "health_orb", 6),
    ]:
        raise StaticReTestFailure("orb magnet corpus lost its three named health/mana trajectory witnesses")
    trajectory_samples_checked = 0
    for trajectory in trajectories:
        index = trajectory["trajectory_index"]
        if (
            trajectory.get("base_pull_radius_units_per_pickup_factor") != 60.0
            or trajectory.get("base_capture_radius_units_per_pickup_factor") != 20.0
            or trajectory.get("captured_pickup_factor") != 1.25
            or trajectory.get("captured_orb_pull_multiplier") != 1.0
            or trajectory.get("effective_pull_radius") != 75.0
            or trajectory.get("effective_capture_radius") != 25.0
            or trajectory.get("expected_constant_step_per_actor_tick") != 1.5
            or trajectory.get("capture_observed") is not True
        ):
            raise StaticReTestFailure(f"trajectory {index} no longer pins live pull/capture constants")
        samples = trajectory.get("samples")
        if not isinstance(samples, list) or len(samples) < 6:
            raise StaticReTestFailure(f"trajectory {index} does not reach a runnable per-tick sequence")
        if samples[0].get("decay_timer") != 900 or samples[-1].get("distance", math.inf) >= 25.0:
            raise StaticReTestFailure(f"trajectory {index} no longer crosses the strict capture radius from timer 900")
        for sample_index, sample in enumerate(samples, start=1):
            if (
                sample.get("sample_index") != sample_index
                or type(sample.get("tick")) is not int
                or type(sample.get("monotonic_milliseconds")) is not int
                or not all(math.isfinite(sample.get(key, math.nan)) for key in ("x", "y", "player_x", "player_y", "distance"))
            ):
                raise StaticReTestFailure(f"trajectory {index} sample {sample_index} lost position or tick provenance")
            trajectory_samples_checked += 1
        transitions = list(zip(samples, samples[1:]))
        if not transitions:
            raise StaticReTestFailure(f"trajectory {index} has no per-tick movement transition")
        for transition_index, (before, after) in enumerate(transitions, start=1):
            if (
                after["tick"] != before["tick"] + 1
                or after["monotonic_milliseconds"] < before["monotonic_milliseconds"]
                or after["decay_timer"] != before["decay_timer"] - 1
            ):
                raise StaticReTestFailure(f"trajectory {index} transition {transition_index} lost tick cadence")
            moved = math.hypot(after["x"] - before["x"], after["y"] - before["y"])
            expected_move = 0.0 if transition_index == len(transitions) else 1.5
            if not math.isclose(moved, expected_move, rel_tol=0.0, abs_tol=0.0002):
                raise StaticReTestFailure(f"trajectory {index} transition {transition_index} violates constant-step orb physics")
    if trajectory_samples_checked != 44:
        raise StaticReTestFailure(f"orb trajectory contract did not inspect all 44 tick samples: {trajectory_samples_checked}")

    credit = document.get("two_participant_crediting")
    if not isinstance(credit, dict):
        raise StaticReTestFailure("two-participant loot credit recording is absent")
    placement = credit.get("placement")
    before = credit.get("before")
    after = credit.get("after")
    drop = credit.get("drop")
    if (
        drop != {"amount": 11, "kind": "gold", "x": 1500.0, "y": 1750.0}
        or placement
        != {
            "both_inside_stock_capture_radius": True,
            "client": {"distance": 6.0, "x": 1506.0, "y": 1750.0},
            "host": {"distance": 18.0, "x": 1482.0, "y": 1750.0},
        }
    ):
        raise StaticReTestFailure("multiplayer credit witness no longer puts both participants inside one 11-gold radius")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise StaticReTestFailure("multiplayer credit witness lost its before/after ledgers")
    host_delta = after["host"]["player"]["gold"] - before["host"]["player"]["gold"]
    client_delta = after["client"]["player"]["gold"] - before["client"]["player"]["gold"]
    if host_delta != 11 or client_delta != 0 or placement["host"]["distance"] <= placement["client"]["distance"]:
        raise StaticReTestFailure("multiplayer credit no longer proves farther-host first-retirement beats nearest-player")
    host_result = after["host"]["last_pickup_result"]
    client_result = after["client"]["last_pickup_result"]
    if (
        host_result.get("result") != "AlreadyGone"
        or client_result.get("result") != "AlreadyGone"
        or host_result.get("network_drop_id") == 0
        or host_result.get("network_drop_id") != client_result.get("network_drop_id")
    ):
        raise StaticReTestFailure("multiplayer credit no longer records the losing claim as AlreadyGone")

    multiplayer_section = _unique_section(doc, "LOOT_MULTIPLAYER_RULE")
    _require_tokens(
        multiplayer_section,
        (
            "The host alone runs enemy death selection",
            "Clients suppress local death loot",
            "first path that retires/accepts the drop receives credit",
            "There is no nearest-player comparison",
            "farther host gains all 11",
            "roll once on its server/host",
        ),
        "host authority and first-retirement multiplayer rule is no longer rebuildable",
    )

    packet_text = _read(PICKUP_PACKETS, "loot pickup packet authority implementation is absent")
    packet_body = _cpp_function_body(
        packet_text,
        "void ApplyLootPickupRequestPacket(",
        "loot pickup request handler lookup is ambiguous",
    )
    packet_sequence = re.compile(
        r"pending_host_loot_pickups_by_drop_id\.find\(.*?"
        r"LootPickupResultCode::AlreadyGone.*?"
        r"ValidateLootPickupRequest\(.*?"
        r"QueueHostLootDropDeactivation\(.*?"
        r"pending_host_loot_pickups_by_drop_id\.emplace\(",
        re.DOTALL,
    )
    if packet_sequence.search(packet_body) is None:
        raise StaticReTestFailure("loot claim sequencing regex no longer proves pending rejection before validated retirement")

    authority_text = _read(PICKUP_AUTHORITY, "loot pickup validation implementation is absent")
    validation_body = _cpp_function_body(
        authority_text,
        "bool ValidateLootPickupRequest(",
        "loot pickup validation lookup is ambiguous",
    )
    _require_tokens(
        validation_body,
        (
            "participant_run_nonce_mismatch",
            "accepted_loot_pickup_drop_ids.find(packet.network_drop_id)",
            "drop_already_gone",
            "drop_inactive",
            "StockLootBehaviorDistance(drop_kind, derived_stats.pickup_range)",
            "client_position_in_range",
            "host_observed_position_in_range",
            "kLootPickupDropDriftMaxDistance",
        ),
        "loot claim validation lost run, active-drop, claimant-radius, or drift checks",
    )
    if "nearest" in validation_body.lower() or "best_distance" in validation_body:
        raise StaticReTestFailure("loot claim validation introduced nearest-player ranking")

    finalization_text = _read(PICKUP_FINALIZATION, "loot pickup finalization implementation is absent")
    finalization_body = _cpp_function_body(
        finalization_text,
        "void FinalizeHostLootPickup(",
        "loot pickup finalization lookup is ambiguous",
    )
    finalization_sequence = re.compile(
        r"deactivation\.deactivated.*?"
        r"accepted_loot_pickup_drop_ids\.insert\(.*?"
        r"ApplyAcceptedHostLootPickupState\(&pending\).*?"
        r"LootPickupResultCode::Accepted",
        re.DOTALL,
    )
    if finalization_sequence.search(finalization_body) is None:
        raise StaticReTestFailure("loot finalization sequencing regex no longer couples retirement, credit, and Accepted")

    death_text = _read(REPLICATED_ENEMY_DEATH, "replicated enemy death implementation is absent")
    death_sequence = re.compile(
        r"TryTriggerRunEnemyDeath\(actor_address.*?"
        r"death_called\s*&&\s*multiplayer::IsLocalTransportClient\(\).*?"
        r"SuppressClientLocalLootActors\(\"client_replicated_enemy_death_snapshot\"\)",
        re.DOTALL,
    )
    if death_sequence.search(death_text) is None:
        raise StaticReTestFailure("client death-loot suppression sequencing regex no longer follows replicated death")
    reconciliation_text = _read(REPLICATED_LOOT, "replicated loot materialization implementation is absent")
    _require_tokens(
        reconciliation_text,
        (
            "RemoveUnboundClientLootActors(\"pre_reconcile\")",
            "SpawnReplicatedLootPresentationActor(drop, &actor_address, &spawn_error)",
            "RemoveUnboundClientLootActors(\"post_reconcile\")",
        ),
        "clients no longer suppress local drops around host snapshot materialization",
    )
    gold_hook_text = _read(GOLD_PICKUP_HOOK, "host stock gold pickup hook implementation is absent")
    gold_hook_body = _cpp_function_body(
        gold_hook_text,
        "void __fastcall HookGoldPickupTick(",
        "host stock gold pickup hook lookup is ambiguous",
    )
    gold_host_sequence = re.compile(
        r"if \(multiplayer::IsLocalTransportClient\(\)\).*?return;.*?"
        r"if \(IsReplicatedLootPresentationActorInternal\(gold_address\)\)\s*\{\s*return;\s*\}.*?"
        r"original\(self\);",
        re.DOTALL,
    )
    if gold_host_sequence.search(gold_hook_body) is None:
        raise StaticReTestFailure("host-local gold no longer reaches stock pickup after client/presentation guards")
    return "four family constants, 44 live orb ticks, no-eviction capacity, and first-retirement credit are pinned"
