"""Static contracts for the G13 native session-flow reconstruction."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from static_re_contract_support import ROOT, StaticReTestFailure


DOC_PATH = ROOT / "docs/reverse-engineering/native-session-flow.md"
GOLDEN_PATH = ROOT / "tests/fixtures/webgame/session-flow-goldens.json"
CAPTURE_SOURCE_PATH = ROOT / "SolomonDarkModLoader/src/native_session_flow_capture.cpp"
SWITCH_HOOK_PATH = (
    ROOT
    / "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_actor_lifecycle_hooks.inl"
)
LOADING_SCREEN_PATH = ROOT / "SolomonDarkModLoader/src/loading_screen.cpp"
BINARY_LAYOUT_PATH = ROOT / "config/binary-layout.ini"


EXPECTED_STATES = {
    ("boot.loader", "MyLoader", -1, "0x005BAB60", "0x00799BDC"),
    (
        "frontend.shell",
        "MainMenu/front-end installer",
        -1,
        "0x005A7F60",
        "0x007980CC",
    ),
    ("gameplay.courtyard", "Courtyard", 0, "0x00506490", "0x00792644"),
    (
        "gameplay.mortuary",
        "Mortuary/Memoratorium",
        1,
        "0x005090A0",
        "0x007927DC",
    ),
    ("gameplay.library", "Library", 2, "0x0050A360", "0x00792C04"),
    ("gameplay.storeroom", "StoreRoom", 3, "0x00509B10", "0x0079294C"),
    ("gameplay.office", "Office", 4, "0x00509C70", "0x00792AB4"),
    ("gameplay.arena", "Arena", 5, "0x00464EE0", "0x00785934"),
    ("overlay.game_over", "GameOver", -1, "0x005CF4F0", "0x0079B0CC"),
    (
        "post_run.mortuary_frontend",
        "Mortuary plus stock front end",
        1,
        "0x005A7F60",
        "0x007980CC",
    ),
    (
        "frontend.hall_of_fame",
        "HallOfFame",
        -1,
        "0x00589CD0",
        "0x00799334",
    ),
    (
        "loading.boneyard",
        "loader readiness barrier",
        -1,
        "0x00000000",
        "0x00000000",
    ),
}

EXPECTED_EDGES = {
    ("boot.loader", "boot_complete", "loader completion", "frontend.shell"),
    (
        "frontend.shell",
        "startup_hub",
        "new/saved/onboarded gameplay selects region 0",
        "gameplay.courtyard",
    ),
    (
        "frontend.shell",
        "startup_office",
        "startup pending kind selects region 4",
        "gameplay.office",
    ),
    (
        "frontend.shell",
        "startup_boneyard",
        "direct Boneyard startup selects region 5",
        "loading.boneyard",
    ),
    (
        "loading.boneyard",
        "arena_materialized",
        "native region 5 switch plus readiness release",
        "gameplay.arena",
    ),
    (
        "gameplay.courtyard",
        "enter_mortuary",
        "Mortuary portal collision",
        "gameplay.mortuary",
    ),
    (
        "gameplay.mortuary",
        "return_courtyard",
        "Mortuary return portal",
        "gameplay.courtyard",
    ),
    (
        "gameplay.mortuary",
        "completed_story_continue",
        "completed story continuation",
        "frontend.hall_of_fame",
    ),
    (
        "gameplay.courtyard",
        "enter_library",
        "Library portal collision",
        "gameplay.library",
    ),
    (
        "gameplay.library",
        "return_courtyard",
        "Library return portal",
        "gameplay.courtyard",
    ),
    (
        "gameplay.courtyard",
        "enter_storeroom",
        "StoreRoom portal collision",
        "gameplay.storeroom",
    ),
    (
        "gameplay.storeroom",
        "return_courtyard",
        "StoreRoom return portal",
        "gameplay.courtyard",
    ),
    (
        "gameplay.courtyard",
        "enter_office",
        "Office portal collision",
        "gameplay.office",
    ),
    (
        "gameplay.office",
        "return_courtyard",
        "Office return portal",
        "gameplay.courtyard",
    ),
    (
        "gameplay.courtyard",
        "start_run",
        "accepted MapPicker/start-match action",
        "loading.boneyard",
    ),
    (
        "gameplay.courtyard",
        "leave_game",
        "stock Pause then Leave Game",
        "frontend.shell",
    ),
    (
        "gameplay.arena",
        "terminal_death",
        "solo lethal callback or authority all-dead command",
        "overlay.game_over",
    ),
    (
        "gameplay.arena",
        "authority_leave_run",
        "host stock Leave Game plus authenticated client follow",
        "frontend.shell",
    ),
    (
        "overlay.game_over",
        "story_completion",
        "normal GameOver close",
        "gameplay.mortuary",
    ),
    (
        "overlay.game_over",
        "boneyard_completion",
        "tick-1000 input acceptance and stock cleanup",
        "post_run.mortuary_frontend",
    ),
    (
        "gameplay.arena",
        "scripted_terminal_reset",
        "WIN LEVEL or LOSE LEVEL finish fade",
        "gameplay.courtyard",
    ),
    (
        "post_run.mortuary_frontend",
        "open_hall_of_fame",
        "stock Menu action",
        "frontend.hall_of_fame",
    ),
    (
        "frontend.hall_of_fame",
        "continue_to_frontend",
        "accepted continue and HallOfFame fade completion",
        "frontend.shell",
    ),
}

EXPECTED_ILLEGAL_EDGE_CLASSES = (
    "private region to different private region",
    "private region directly to Arena",
    "ordinary Arena switch to a fixed region",
    "same-region request is a no-op, not an edge",
    "target -1 is a detach transient, not a stable state",
    "target outside 0..5 is unchecked native memory access",
    "post-run Mortuary directly to Courtyard bypasses stock front end",
    "multiplayer client to Arena without authenticated host intent",
)

EXPECTED_TIMELINE = (
    (
        "startup_office_then_return_courtyard",
        "frontend.shell",
        "gameplay.courtyard",
        "launcher QuickStart accepted the landed Create flow and native onboarding completed",
        0,
        24,
    ),
    (
        "enter_library",
        "gameplay.courtyard",
        "gameplay.library",
        "accepted authority sd.scene.switch_region(2) probe",
        24,
        5,
    ),
    (
        "return_courtyard",
        "gameplay.library",
        "gameplay.courtyard",
        "accepted authority sd.scene.switch_region(0) probe",
        5,
        24,
    ),
    (
        "start_run_pipeline",
        "gameplay.courtyard",
        "gameplay.arena",
        "accepted host start_testrun action",
        23,
        1,
    ),
    (
        "terminal_death",
        "gameplay.arena",
        "overlay.game_over",
        "native magic-hit trial reduced the sole participant to zero life",
        1,
        1,
    ),
    (
        "stock_boneyard_return_pipeline",
        "overlay.game_over",
        "gameplay.courtyard",
        "exact-PID stock window input followed by retained Create confirmation",
        1,
        21,
    ),
)

EXPECTED_EXTERNAL_HASHES = {
    "executable_sha256": (
        "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
    ),
    "loader_sha256": (
        "23c12dc955ae7cbf31906107e4b5a9f4596100578d5bf9095ed68205cb05a08c"
    ),
    "raw_events_sha256": (
        "e0314b2b982b342f9d0b55b98e88a01728c49b03b10f5a4b5c90fa25b7fbec6a"
    ),
    "raw_graph_sha256": (
        "e4b50653cd68f7240d1a53c0b84fb63403032ed8590fda3f638bb27a693ab360"
    ),
    "raw_status_sha256": (
        "741a60dba138cf3d21db94d60415198ed4d676deb7bff72c5e7a01fb3a230126"
    ),
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StaticReTestFailure(message)


def _read(path: Path) -> str:
    _require(
        path.is_file(),
        f"session-flow claim source is absent, so its behavior is unchecked: {path.relative_to(ROOT)}",
    )
    return path.read_text(encoding="utf-8")


def _load_fixture() -> tuple[str, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    doc = _read(DOC_PATH)
    try:
        fixture = json.loads(_read(GOLDEN_PATH))
    except json.JSONDecodeError as exc:
        raise StaticReTestFailure(
            f"session-flow live recording is not reviewable JSON: {exc}"
        ) from exc

    _require(
        fixture.get("schema_version") == 1,
        "session-flow consumers would parse an unrecognized golden schema",
    )
    graph = fixture.get("transition_graph")
    timeline = fixture.get("session_timeline")
    _require(
        isinstance(graph, dict) and isinstance(timeline, dict),
        "session-flow graph or full-session timeline disappeared from the live fixture",
    )
    states = graph.get("states")
    edges = graph.get("edges")
    transitions = timeline.get("transitions")
    _require(
        isinstance(states, list) and len(states) > 0,
        "session-flow state sweeps would inspect nothing because the live state list is empty",
    )
    _require(
        isinstance(edges, list) and len(edges) > 0,
        "session-flow edge sweeps would inspect nothing because the live graph is empty",
    )
    _require(
        isinstance(transitions, list) and len(transitions) > 0,
        "session-flow lifecycle sweeps would inspect nothing because the live timeline is empty",
    )
    _validate_headers(graph.get("header"), timeline.get("header"))
    return doc, fixture, states, transitions


def _validate_headers(graph_header: Any, timeline_header: Any) -> None:
    _require(
        isinstance(graph_header, dict) and isinstance(timeline_header, dict),
        "session-flow fixture no longer identifies both live capture boundaries",
    )
    graph_method = "live injected native graph emitter; no edge was hand-entered into the fixture"
    timeline_method = (
        "live solo Windows instance; injected read-only recorder plus existing lua-exec "
        "and exact-PID stock input"
    )
    _require(
        graph_header.get("capture_method") == graph_method,
        "session-flow graph could be mistaken for a hand-authored edge list",
    )
    _require(
        timeline_header.get("capture_method") == timeline_method,
        "session-flow timeline no longer proves live native and exact-PID capture",
    )
    graph_common = {key: value for key, value in graph_header.items() if key != "capture_method"}
    timeline_common = {
        key: value for key, value in timeline_header.items() if key != "capture_method"
    }
    _require(
        graph_common == timeline_common,
        "the graph and timeline headers would identify two different recordings",
    )
    _require(
        graph_header.get("instance") == "flw-g13-final",
        "session-flow provenance no longer names the isolated flw-g13-final instance",
    )
    _require(
        graph_header.get("source_branch") == "flowre/flowre-20260805"
        and graph_header.get("source_dirty") is False,
        "session-flow provenance no longer proves a clean campaign source tree",
    )
    _require(
        graph_header.get("audio_disabled") is True
        and graph_header.get("udp_ports") == [52321, 52322],
        "session-flow capture escaped its audio-disabled 52321/52322 isolation boundary",
    )
    _require(
        isinstance(graph_header.get("process_id"), int)
        and graph_header["process_id"] > 0,
        "session-flow live recording no longer identifies the exact native process",
    )
    _require(
        re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z",
            str(graph_header.get("captured_at_utc", "")),
        )
        is not None,
        "session-flow recording no longer carries an unambiguous UTC capture time",
    )
    for key, expected in EXPECTED_EXTERNAL_HASHES.items():
        # These hash evidence files or binaries outside the committed fixture.
        # They intentionally remain immutable provenance constants rather than
        # using assert_recorded_hash_matches_file(), which is for committed files.
        _require(
            graph_header.get(key) == expected,
            f"session-flow provenance no longer identifies the exact external {key}",
        )

    source_sha = graph_header.get("source_sha")
    _require(
        isinstance(source_sha, str)
        and re.fullmatch(r"[0-9a-f]{40}", source_sha) is not None,
        "session-flow provenance no longer names a full source commit",
    )
    object_probe = subprocess.run(
        ["git", "cat-file", "-t", source_sha],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    _require(
        object_probe.returncode == 0 and object_probe.stdout.strip() == "commit",
        "session-flow source SHA does not resolve to a commit, so the live capture cannot be audited",
    )
    ancestor_probe = subprocess.run(
        ["git", "merge-base", "--is-ancestor", source_sha, "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    _require(
        ancestor_probe.returncode == 0,
        "session-flow source SHA is not an ancestor of HEAD, so the live capture cannot be re-derived",
    )


def _section(text: str, start_heading: str, end_heading: str) -> str:
    starts = [match.start() for match in re.finditer(re.escape(start_heading), text)]
    _require(
        len(starts) == 1,
        f"session-flow document lookup is ambiguous for {start_heading!r}",
    )
    ends = [
        match.start()
        for match in re.finditer(re.escape(end_heading), text)
        if match.start() > starts[0]
    ]
    _require(
        len(ends) == 1,
        f"session-flow document lookup is ambiguous for {end_heading!r}",
    )
    return text[starts[0] : ends[0]]


def _initializer_body(text: str, declaration_pattern: str, consequence: str) -> str:
    matches = list(
        re.finditer(
            declaration_pattern + r"\s*=\s*\{\{(?P<body>.*?)\}\};",
            text,
            flags=re.DOTALL,
        )
    )
    _require(len(matches) == 1, consequence)
    return matches[0].group("body")


def _function_body(text: str, signature_pattern: str, consequence: str) -> str:
    matches = list(re.finditer(signature_pattern, text, flags=re.MULTILINE))
    _require(len(matches) == 1, consequence)
    opening = text.find("{", matches[0].end())
    _require(opening >= 0, consequence)
    depth = 0
    closing: int | None = None
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                closing = index
                break
    _require(closing is not None, consequence)
    return text[opening + 1 : closing]


def _unique_match_position(text: str, pattern: str, consequence: str) -> int:
    matches = list(re.finditer(pattern, text, flags=re.DOTALL))
    _require(len(matches) == 1, consequence)
    return matches[0].start()


def _unique_step_index(
    steps: list[dict[str, Any]], step_name: str, consequence: str
) -> int:
    matches = [index for index, step in enumerate(steps) if step.get("step") == step_name]
    _require(len(matches) == 1, consequence)
    return matches[0]


def _unique_ini_value(text: str, key: str, consequence: str) -> int:
    matches = re.findall(
        rf"^{re.escape(key)}\s*=\s*(0x[0-9A-Fa-f]+|\d+)\s*$",
        text,
        flags=re.MULTILINE,
    )
    _require(len(matches) == 1, consequence)
    return int(matches[0], 0)


def test_native_session_flow_state_enum_is_pinned() -> str:
    doc, fixture, states, _ = _load_fixture()
    state_ids = [state.get("state") for state in states]
    _require(
        len(state_ids) == len(set(state_ids)),
        "session-flow state lookup would silently choose between duplicate native state ids",
    )
    actual_states = {
        (
            state.get("state"),
            state.get("native_identifier"),
            state.get("native_region_id"),
            state.get("preferred_address"),
            state.get("vtable_address"),
        )
        for state in states
    }
    _require(
        actual_states == EXPECTED_STATES,
        "native session state enum, identifiers, region ids, or addresses drifted",
    )

    state_keys = {
        "native_identifier",
        "native_region_id",
        "preferred_address",
        "runtime_address",
        "state",
        "vtable_address",
    }
    _require(
        all(set(state) == state_keys for state in states),
        "native session state records would lose an address or gain an unaudited field",
    )
    nonzero_states = [
        state for state in states if int(state["preferred_address"], 16) != 0
    ]
    _require(
        any(state["state"] == "gameplay.courtyard" for state in nonzero_states),
        "runtime-relocation validation would inspect no real native state witness",
    )
    relocation_deltas = {
        int(state["runtime_address"], 16) - int(state["preferred_address"], 16)
        for state in nonzero_states
    }
    _require(
        len(relocation_deltas) == 1,
        "live session state addresses no longer share one executable relocation delta",
    )
    zero_runtime_states = {
        state["state"]
        for state in states
        if int(state["runtime_address"], 16) == 0
    }
    _require(
        zero_runtime_states == {"loading.boneyard"},
        "only the loader-owned Boneyard barrier may lack a native runtime address",
    )

    capture_source = _read(CAPTURE_SOURCE_PATH)
    state_body = _initializer_body(
        capture_source,
        r"constexpr\s+std::array<NativeStateDefinition,\s*12>\s+kNativeStates",
        "recorder state initializer nesting or cardinality drifted, so emitted enum provenance is unchecked",
    )
    source_rows = re.findall(
        r'^\s*\{"([^"]+)",\s*"([^"]+)",\s*(0x[0-9A-Fa-f]+|0),\s*'
        r"(0x[0-9A-Fa-f]+|0),\s*(-?\d+)\},\s*$",
        state_body,
        flags=re.MULTILINE,
    )
    _require(
        len(source_rows) > 0,
        "recorder state parser would compare an empty initializer against the live fixture",
    )
    source_ids = [row[0] for row in source_rows]
    _require(
        len(source_ids) == len(set(source_ids)),
        "recorder state emitter would silently choose between duplicate state ids",
    )
    source_states = {
        (
            state,
            native_identifier,
            int(region_id),
            f"0x{int(preferred, 0):08X}",
            f"0x{int(vtable, 0):08X}",
        )
        for state, native_identifier, preferred, vtable, region_id in source_rows
    }
    _require(
        source_states == EXPECTED_STATES,
        "recorder source would emit a different native session enum than the contracted graph",
    )

    state_section = _section(
        doc,
        "### Complete G13 stable state list",
        "### Complete legal cross-state edge set",
    )
    documented_ids = re.findall(r"^\| `([^`]+)` \|", state_section, flags=re.MULTILINE)
    _require(
        len(documented_ids) == len(set(documented_ids)),
        "session-flow document state lookup is ambiguous because a state row is duplicated",
    )
    _require(
        set(documented_ids) == {state[0] for state in EXPECTED_STATES},
        "session-flow document no longer enumerates every and only stable G13 state",
    )

    storage_section = _section(doc, "### Where the current state lives", "### Complete G13 stable state list")
    storage_rows = re.findall(
        r"^\| ([^|]+?) \| `([^`]+)` \|", storage_section, flags=re.MULTILINE
    )
    _require(
        any(owner == "Region assignment vector" for owner, _ in storage_rows),
        "current-state storage validation would inspect no authoritative region witness",
    )
    storage_owners = [owner for owner, _ in storage_rows]
    _require(
        len(storage_owners) == len(set(storage_owners)),
        "session-flow storage lookup is ambiguous because an owner row is duplicated",
    )
    storage = dict(storage_rows)
    expected_storage = {
        "Gameplay singleton": "DAT_0081C264",
        "Region assignment vector": "DAT_00819E84",
        "Pending transition": "Gameplay+0x78",
        "Active world/region": "DAT_0081C260",
        "Local gameplay actor/controller": "Gameplay+0x1358",
    }
    _require(
        {owner: storage.get(owner) for owner in expected_storage} == expected_storage,
        "browser session state would read the wrong current, pending, active, or actor storage",
    )

    layout = _read(BINARY_LAYOUT_PATH)
    expected_layout = {
        "gameplay_global": 0x0081C264,
        "region_assignment_array_global": 0x00819E84,
        "active_region_global": 0x0081C260,
    }
    actual_layout = {
        key: _unique_ini_value(
            layout,
            key,
            f"binary layout lookup is ambiguous or absent for session-state key {key}",
        )
        for key in expected_layout
    }
    _require(
        actual_layout == expected_layout,
        "capture layout would observe different native state storage than the G13 document",
    )
    return "12 stable native/composite states and current-state storage are exact"


def test_native_session_flow_legal_edge_set_is_pinned() -> str:
    doc, fixture, _, _ = _load_fixture()
    edges = fixture["transition_graph"]["edges"]
    edge_keys = [(edge.get("state"), edge.get("edge")) for edge in edges]
    _require(
        len(edge_keys) == len(set(edge_keys)),
        "session-flow graph lookup would silently choose between duplicate source/edge ids",
    )
    actual_edges = {
        (
            edge.get("state"),
            edge.get("edge"),
            edge.get("trigger"),
            edge.get("destination"),
        )
        for edge in edges
    }
    _require(
        actual_edges == EXPECTED_EDGES,
        "native legal edge set, trigger, or destination drifted",
    )

    capture_source = _read(CAPTURE_SOURCE_PATH)
    edge_body = _initializer_body(
        capture_source,
        r"constexpr\s+std::array<NativeEdgeDefinition,\s*23>\s+kNativeEdges",
        "recorder edge initializer nesting or cardinality drifted, so emitted graph provenance is unchecked",
    )
    source_rows = re.findall(
        r'^\s*\{"([^"]+)",\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]+)"\},\s*$',
        edge_body,
        flags=re.MULTILINE,
    )
    _require(
        len(source_rows) > 0,
        "recorder edge parser would compare an empty initializer against the live graph",
    )
    source_keys = [(row[0], row[1]) for row in source_rows]
    _require(
        len(source_keys) == len(set(source_keys)),
        "recorder graph emitter would silently choose between duplicate source/edge ids",
    )
    _require(
        set(source_rows) == EXPECTED_EDGES,
        "recorder source would emit a different legal edge set than the contracted graph",
    )

    edge_section = _section(
        doc,
        "### Complete legal cross-state edge set",
        "### Illegal requests and non-edges",
    )
    documented_rows = re.findall(
        r"^\| `([^`]+)` \| `([^`]+)` \| .* \| `([^`]+)` \|$",
        edge_section,
        flags=re.MULTILINE,
    )
    _require(
        len(documented_rows) > 0,
        "session-flow document edge parser would accept an empty legal-edge table",
    )
    documented_keys = [(row[0], row[1]) for row in documented_rows]
    _require(
        len(documented_keys) == len(set(documented_keys)),
        "session-flow document edge lookup is ambiguous because a source/edge row is duplicated",
    )
    expected_documented = {(state, edge, destination) for state, edge, _, destination in EXPECTED_EDGES}
    _require(
        set(documented_rows) == expected_documented,
        "session-flow document no longer enumerates every and only legal cross-state edge",
    )

    illegal = fixture["transition_graph"].get("illegal_edge_classes")
    _require(
        isinstance(illegal, list) and len(illegal) > 0,
        "illegal-edge validation would inspect nothing because the fixture lost its negative graph",
    )
    _require(
        len(illegal) == len(set(illegal)),
        "illegal-edge lookup is ambiguous because a rejected request class is duplicated",
    )
    _require(
        tuple(illegal) == EXPECTED_ILLEGAL_EDGE_CLASSES,
        "native illegal-edge and no-op classes drifted",
    )
    return "23 legal cross-state edges and eight illegal/no-op classes are exact"


def test_native_session_flow_transition_step_order_is_pinned() -> str:
    doc, _, _, transitions = _load_fixture()
    actual_timeline = tuple(
        (
            transition.get("edge"),
            transition.get("source"),
            transition.get("destination"),
            transition.get("trigger"),
            transition.get("before", {}).get("entity_count"),
            transition.get("after", {}).get("entity_count"),
        )
        for transition in transitions
    )
    _require(
        actual_timeline == EXPECTED_TIMELINE,
        "full-session live path, trigger, or before/after entity census drifted",
    )
    transition_names = [transition[0] for transition in actual_timeline]
    _require(
        len(transition_names) == len(set(transition_names)),
        "timeline lookup would silently choose between duplicate transition ids",
    )

    all_sequences: list[int] = []
    for transition in transitions:
        edge = transition["edge"]
        steps = transition.get("ordered_lifecycle_steps")
        _require(
            isinstance(steps, list) and len(steps) > 0,
            f"{edge} lifecycle ordering would inspect no recorded native steps",
        )
        sequences = [step.get("sequence") for step in steps]
        ticks = [step.get("tick") for step in steps]
        _require(
            all(isinstance(sequence, int) for sequence in sequences),
            f"{edge} lifecycle no longer carries integer native event sequence stamps",
        )
        _require(
            sequences == sorted(sequences) and len(sequences) == len(set(sequences)),
            f"{edge} lifecycle no longer has strict unambiguous native event order",
        )
        _require(
            all(isinstance(tick, int) for tick in ticks) and ticks == sorted(ticks),
            f"{edge} lifecycle tick stamps moved backward or became nonnumeric",
        )
        before_tick = transition.get("before", {}).get("tick")
        after_tick = transition.get("after", {}).get("tick")
        _require(
            isinstance(before_tick, int)
            and isinstance(after_tick, int)
            and before_tick <= ticks[0] <= ticks[-1] <= after_tick,
            f"{edge} lifecycle steps escaped their recorded before/after tick boundary",
        )
        all_sequences.extend(sequences)
    _require(
        len(all_sequences) > 0 and all_sequences == sorted(all_sequences),
        "full-session native event order is no longer monotonic across transitions",
    )
    _require(
        len(all_sequences) == len(set(all_sequences)),
        "full-session native event sequence lookup is ambiguous across transitions",
    )

    by_edge = {transition["edge"]: transition for transition in transitions}
    library_steps = by_edge["enter_library"]["ordered_lifecycle_steps"]
    library_order = (
        "switch.enter",
        "participant_churn.begin",
        "participant_churn.end",
        "region.cache.sleep.begin",
        "region.cache.sleep.end",
        "region.lifecycle.unregister",
        "region.wake.begin",
        "region.wake.end",
        "gameplay.attach.begin",
        "gameplay.attach.end",
        "switch.exit",
        "presentation.fade_in.begin",
        "presentation.fade_in.endpoint",
    )
    library_positions = [
        _unique_step_index(
            library_steps,
            step,
            f"ordinary Library switch cannot resolve exactly one {step} lifecycle boundary",
        )
        for step in library_order
    ]
    _require(
        library_positions == sorted(library_positions),
        "ordinary room transition teardown, publish/wake, attach, and fade-in order drifted",
    )
    detach_indices = [
        index
        for index, step in enumerate(library_steps)
        if step.get("step") in {
            "region.player_slot.detach.begin",
            "region.player_slot.detach.end",
        }
    ]
    _require(
        len(detach_indices) > 0,
        "ordinary room transition no longer witnesses player-slot detach around cache sleep",
    )
    for index in detach_indices:
        step_name = library_steps[index]["step"]
        if step_name.endswith(".begin"):
            _require(
                index + 1 < len(library_steps)
                and library_steps[index + 1].get("step") == "region.player_slot.detach.end",
                "ordinary room transition has a detach begin without its immediately paired native return",
            )
        else:
            _require(
                index > 0
                and library_steps[index - 1].get("step") == "region.player_slot.detach.begin",
                "ordinary room transition has a detach return without its immediately preceding native call",
            )
    first_detach = detach_indices[0]
    sleep_begin = library_positions[library_order.index("region.cache.sleep.begin")]
    sleep_end = library_positions[library_order.index("region.cache.sleep.end")]
    _require(
        library_positions[2] < first_detach < sleep_begin
        and any(sleep_begin < index < sleep_end for index in detach_indices),
        "ordinary switch must detach slot zero before sleep and preserve nested sleep detach calls",
    )

    startup_steps = by_edge["startup_office_then_return_courtyard"][
        "ordered_lifecycle_steps"
    ]
    office_switches = [
        index
        for index, step in enumerate(startup_steps)
        if step.get("step") == "switch.enter"
    ]
    _require(
        len(office_switches) == 2
        and (startup_steps[office_switches[0]].get("current_region"), startup_steps[office_switches[0]].get("target_region"))
        == (-1, 4)
        and (startup_steps[office_switches[1]].get("current_region"), startup_steps[office_switches[1]].get("target_region"))
        == (4, 0),
        "stock onboarding switch lookup must resolve the exact startup and Office-to-Courtyard calls",
    )
    fade_out = _unique_step_index(
        startup_steps,
        "presentation.fade_out.endpoint",
        "stock Office exit cannot resolve exactly one fade-out endpoint",
    )
    _require(
        office_switches[0] < fade_out < office_switches[1],
        "stock presentation fade-out endpoint must precede the synchronous room load",
    )

    death_steps = by_edge["terminal_death"]["ordered_lifecycle_steps"]
    _require(
        [step.get("step") for step in death_steps]
        == ["run.death.terminal_callback", "overlay.game_over.installed"],
        "terminal death must install Game Over immediately after the native terminal callback",
    )

    switch_source = _read(SWITCH_HOOK_PATH)
    switch_body = _function_body(
        switch_source,
        r"^void __fastcall HookGameplaySwitchRegion\([^\n]+\)\s*(?=\{)",
        "native switch hook body is missing or ambiguous, so transition ordering is unchecked",
    )
    hook_order = (
        (
            r"NativeSessionFlowCaptureBeginSwitch\(self,\s*region_index\)\s*;",
            "native switch hook cannot resolve exactly one transition-begin observer",
        ),
        (
            r"NativeSessionFlowCaptureObserveSwitchStep\(\s*\"participant_churn\.begin\"\s*,\s*self\s*,\s*region_index\s*\)\s*;",
            "native switch hook cannot resolve exactly one participant-cleanup begin",
        ),
        (
            r"PrepareGameplaySceneSwitchOnGameThread\(\s*gameplay_address\s*,\s*region_index\s*,\s*\"gameplay_switch_region_pre_dispatch\"\s*\)\s*;",
            "native switch hook cannot resolve exactly one scene-preparation call",
        ),
        (
            r"NativeSessionFlowCaptureObserveSwitchStep\(\s*\"participant_churn\.end\"\s*,\s*self\s*,\s*region_index\s*\)\s*;",
            "native switch hook cannot resolve exactly one participant-cleanup end",
        ),
        (
            r"\boriginal\(self,\s*region_index\)\s*;",
            "native switch hook cannot resolve exactly one stock switch dispatch",
        ),
        (
            r"NativeSessionFlowCaptureEndSwitch\(self,\s*region_index\)\s*;",
            "native switch hook cannot resolve exactly one transition-end observer",
        ),
    )
    hook_positions = [
        _unique_match_position(switch_body, pattern, message)
        for pattern, message in hook_order
    ]
    _require(
        hook_positions == sorted(hook_positions),
        "native switch hook would finish participant cleanup before the scene-preparation call returns",
    )

    layout = _read(BINARY_LAYOUT_PATH)
    _require(
        _unique_ini_value(
            layout,
            "switch_after_outgoing_unregister",
            "outgoing-unregister observer address is absent or ambiguous",
        )
        == 0x005CDEF1,
        "outgoing lifecycle unregister boundary moved away from 0x005CDEF1",
    )
    ordered_summary = (
        r"`fade-out endpoint -> seal if entering Arena -> transient participant cleanup\n"
        r"-> slot detach -> cache sleep -> lifecycle unregister -> publish target -> wake\n"
        r"-> attach -> old-region post callback -> target finalizer -> fade-in -> barrier\n"
        r"release -> unseal`"
    )
    _require(
        re.search(ordered_summary, doc) is not None,
        "document no longer keeps the complete transition order in one adjacent structural contract",
    )
    return "six live transitions preserve teardown/load/fade order and entity/tick boundaries"


def test_native_session_flow_input_seal_boundaries_are_pinned() -> str:
    doc, _, _, transitions = _load_fixture()
    timeline_names = [transition.get("edge") for transition in transitions]
    _require(
        timeline_names == [transition[0] for transition in EXPECTED_TIMELINE],
        "input-seal lookup cannot resolve the unique full-session run-entry witness",
    )
    _require(
        len(timeline_names) == len(set(timeline_names)),
        "input-seal lookup would silently choose between duplicate timeline transition ids",
    )
    start_run = transitions[timeline_names.index("start_run_pipeline")]
    steps = start_run["ordered_lifecycle_steps"]

    first_seals = [
        index
        for index, step in enumerate(steps)
        if step.get("step") == "input.seal"
        and step.get("current_region") == 0
        and step.get("target_region") == 5
    ]
    arena_seals = [
        index
        for index, step in enumerate(steps)
        if step.get("step") == "input.seal"
        and step.get("current_region") == 5
        and step.get("target_region") == 5
    ]
    all_seals = [
        index for index, step in enumerate(steps) if step.get("step") == "input.seal"
    ]
    _require(
        len(first_seals) == 1
        and len(arena_seals) == 1
        and sorted(first_seals + arena_seals) == all_seals,
        "run-entry seal lookup must resolve exactly the pre-teardown and Arena-start seal sites",
    )
    unseal = _unique_step_index(
        steps,
        "input.unseal",
        "run entry cannot resolve exactly one successful input-unseal boundary",
    )
    participant_begin = _unique_step_index(
        steps,
        "participant_churn.begin",
        "run entry cannot resolve exactly one participant-cleanup boundary",
    )
    unregister = _unique_step_index(
        steps,
        "region.lifecycle.unregister",
        "run entry cannot resolve exactly one outgoing lifecycle unregister",
    )
    wake = _unique_step_index(
        steps,
        "region.wake.begin",
        "run entry cannot resolve exactly one Arena wake boundary",
    )
    run_create = _unique_step_index(
        steps,
        "run.create.begin",
        "run entry cannot resolve exactly one Arena creation boundary",
    )
    attach = _unique_step_index(
        steps,
        "gameplay.attach.begin",
        "run entry cannot resolve exactly one Arena attach boundary",
    )
    fade_in = _unique_step_index(
        steps,
        "presentation.fade_in.endpoint",
        "run entry cannot resolve exactly one incoming fade-in endpoint",
    )
    wave_begin = _unique_step_index(
        steps,
        "run.wave.start.begin",
        "run entry cannot resolve exactly one first-wave start boundary",
    )
    wave_end = _unique_step_index(
        steps,
        "run.wave.start.end",
        "run entry cannot resolve exactly one first-wave return boundary",
    )
    detach_begins = [
        index
        for index, step in enumerate(steps)
        if step.get("step") == "region.player_slot.detach.begin"
    ]
    _require(
        len(detach_begins) > 0,
        "run-entry input seal would inspect no outgoing player-slot detach witness",
    )
    first_detach = min(detach_begins)
    _require(
        first_seals[0]
        < participant_begin
        < first_detach
        < unregister
        < arena_seals[0]
        < wake
        <= run_create
        < attach
        < fade_in
        < wave_begin
        < wave_end
        < unseal,
        "run entry must seal before teardown and unseal only after Arena fade-in and wave start",
    )
    _require(
        unseal == len(steps) - 1,
        "successful run-entry input unseal must be the final recorded lifecycle step",
    )
    sealed_interval = steps[first_seals[0] : unseal]
    _require(
        len(sealed_interval) > 0,
        "run-entry sealed-interval sweep would inspect no lifecycle steps",
    )
    _require(
        all(step.get("input_sealed") is True for step in sealed_interval),
        "run-entry lifecycle exposed gameplay input between the seal and successful release",
    )
    _require(
        steps[unseal].get("input_sealed") is False,
        "run-entry unseal event did not publish the released input state",
    )

    switch_source = _read(SWITCH_HOOK_PATH)
    switch_body = _function_body(
        switch_source,
        r"^void __fastcall HookGameplaySwitchRegion\([^\n]+\)\s*(?=\{)",
        "native switch hook body is missing or ambiguous, so the input seal is unchecked",
    )
    _require(
        re.search(
            r"if\s*\(region_index\s*==\s*kArenaRegionIndex\)\s*\{\s*"
            r"BeginBoneyardLoadingScreen\(\)\s*;\s*\}",
            switch_body,
            flags=re.DOTALL,
        )
        is not None,
        "Arena seal call must remain nested directly under the Arena-region condition",
    )
    seal_position = _unique_match_position(
        switch_body,
        r"BeginBoneyardLoadingScreen\(\)\s*;",
        "native run switch cannot resolve exactly one loading-seal call",
    )
    churn_position = _unique_match_position(
        switch_body,
        r"NativeSessionFlowCaptureObserveSwitchStep\(\s*\"participant_churn\.begin\"",
        "native run switch cannot resolve exactly one pre-teardown observer",
    )
    stock_position = _unique_match_position(
        switch_body,
        r"\boriginal\(self,\s*region_index\)\s*;",
        "native run switch cannot resolve exactly one stock switch dispatch",
    )
    _require(
        seal_position < churn_position < stock_position,
        "Arena input seal must activate before participant teardown and stock region dispatch",
    )

    loading_source = _read(LOADING_SCREEN_PATH)
    begin_body = _function_body(
        loading_source,
        r"^void BeginBoneyardLoadingScreen\(\)\s*(?=\{)",
        "Boneyard loading-start body is missing or ambiguous, so the seal point is unchecked",
    )
    begin_positions = (
        _unique_match_position(
            begin_body,
            r"BeginLoadingScreen\(\s*CurrentFlow\(\)\s*,\s*LoadingScreenStage::PreparingBoneyard\s*\)\s*;",
            "Boneyard loading start cannot resolve exactly one overlay activation",
        ),
        _unique_match_position(
            begin_body,
            r"NativeSessionFlowCaptureObserveInputSeal\(\)\s*;",
            "Boneyard loading start cannot resolve exactly one input-seal observer",
        ),
    )
    _require(
        begin_positions[0] < begin_positions[1],
        "Boneyard overlay must become active before the recorder publishes the input seal",
    )

    complete_body = _function_body(
        loading_source,
        r"^void CompleteLoadingScreen\(\)\s*(?=\{)",
        "loading completion body is missing or ambiguous, so successful unseal is unchecked",
    )
    completion_positions = (
        _unique_match_position(
            complete_body,
            r"g_loading_screen\.snapshot\.active\s*=\s*false\s*;",
            "loading completion cannot resolve exactly one overlay close",
        ),
        _unique_match_position(
            complete_body,
            r"NativeSessionFlowCaptureObserveInputUnseal\(\"input\.unseal\"\)\s*;",
            "loading completion cannot resolve exactly one successful input unseal",
        ),
    )
    _require(
        completion_positions[0] < completion_positions[1],
        "successful input unseal must publish only after the loading overlay closes",
    )
    cancel_body = _function_body(
        loading_source,
        r"^void CancelLoadingScreen\(\)\s*(?=\{)",
        "loading cancel body is missing or ambiguous, so failure unseal is unchecked",
    )
    _unique_match_position(
        cancel_body,
        r"NativeSessionFlowCaptureObserveInputUnseal\(\s*\"input\.unseal\.canceled\"\s*\)\s*;",
        "canceled loading can no longer resolve its distinct input-unseal reason",
    )

    _require(
        "[the native input model](native-input-model.md#loading-screen-input-seal-uigate)"
        in doc,
        "session-flow contract no longer imports the landed G14 input-seal authority",
    )
    _require(
        re.search(
            r"movement, key/mouse edges, holds, and cast\n"
            r"queues observed while sealed are dropped, never deferred",
            doc,
        )
        is not None,
        "session-flow lifecycle no longer preserves G14's drop-not-defer rule",
    )
    return "Arena entry seals before teardown and unseals after fade, wave start, and barrier release"


def test_first_wizard_college_admission_contract_is_pinned() -> str:
    doc = _read(DOC_PATH)
    section = _section(
        doc,
        "## 2026-08-25 correction: first story-Game Office admission before Create",
        "### Portable web consequence",
    )
    required = (
        "Game+0x87",
        "0x005CC800",
        "0x005CCE26",
        "0x005CFA80",
        "DAT_00B3BEDC",
        "0x005010C0",
        "(512,562)",
        "0x00509F10",
        "(412,924)..(612,924)",
        "0x00513BE0",
        "ARCH_INTRO_0",
        "POLISHER_INTRO_0",
        "(566,735)",
        "Integer(1500) == 3",
        "dynamic_sounds/wipeglass.wav",
        "Gameplay_SwitchRegion 0x005CDDD0",
        "0x00504AD0",
        "player progression +0x82C == -1",
        "(512,2024)",
        "(952.5,67.5)",
        "(952.5,157.5)",
        "-0.01f",
    )
    missing = [token for token in required if token not in section]
    _require(
        not missing,
        "first-wizard College admission lost recovered ownership/constants: "
        + ", ".join(missing),
    )
    _require(
        re.search(
            r"The flag belongs to one native `Game`, not `darkdata\.cfg`\.",
            section,
        )
        is not None,
        "College admission would be persisted under the wrong native owner",
    )
    _require(
        re.search(
            r"Office tick\s+`0x00509F10` does \*\*not\*\* force the actor south on entry",
            section,
        )
        is not None,
        "College admission regressed to the falsified automatic Office exit",
    )
    _require(
        "Office post-switch callback opens Create" in section,
        "College admission regressed to the falsified Create-before-Office order",
    )
    return "interactive story Office, exit-owned Create, and Courtyard handoff are pinned"
