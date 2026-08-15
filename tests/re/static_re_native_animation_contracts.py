"""Static contracts for the G4 native animation reconstruction."""

from __future__ import annotations

import ast
import json
import math
import re
from pathlib import Path
from typing import Any

from static_re_contract_support import ROOT, StaticReTestFailure


DOC = ROOT / "docs/reverse-engineering/native-animation-state.md"
PROJECTILE_DOC = (
    ROOT / "docs/reverse-engineering/native-projectile-and-spell-mechanics.md"
)
ROADMAP = ROOT / "docs/browser-rebuild-roadmap.md"
GOLDEN = ROOT / "tests/fixtures/webgame/animation-goldens.json"
RECORDER = ROOT / "tools/record_animation_goldens.py"
SCENE_CAPTURE_CPP = ROOT / "SolomonDarkModLoader/src/native_scene_capture.cpp"
SCENE_CAPTURE_PUBLIC = (
    ROOT / "SolomonDarkModLoader/src/native_scene_capture/public_api.inl"
)
SCENE_CAPTURE_SERIALIZATION = (
    ROOT / "SolomonDarkModLoader/src/native_scene_capture/serialization.inl"
)
PLAYER_TICK_HOOK = (
    ROOT
    / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl"
)
EMITTER_BINDING = (
    ROOT
    / "SolomonDarkModLoader/src/lua_engine_bindings_debug/functions_native_scene_capture.inl"
)
NATIVE_SIM_RECORDER = ROOT / "tools/record_native_sim_goldens.py"


def _read(path: Path) -> str:
    if not path.is_file():
        raise StaticReTestFailure(
            f"G4 animation reconstruction cannot be checked because {path.relative_to(ROOT)} is absent"
        )
    return path.read_text(encoding="utf-8")


def _golden() -> dict[str, Any]:
    try:
        value = json.loads(_read(GOLDEN))
    except json.JSONDecodeError as error:
        raise StaticReTestFailure(
            f"animation goldens are not parseable JSON: {error}"
        ) from error
    if not isinstance(value, dict):
        raise StaticReTestFailure(
            "animation goldens lost their top-level object contract"
        )
    return value


def _section(text: str, marker: str) -> str:
    pattern = re.compile(
        rf"<!-- {re.escape(marker)}_BEGIN -->\n(.*?)\n<!-- {re.escape(marker)}_END -->",
        re.DOTALL,
    )
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise StaticReTestFailure(
            f"animation documentation no longer has one unambiguous {marker} contract section"
        )
    if not matches[0].strip():
        raise StaticReTestFailure(
            f"animation documentation leaves the {marker} contract empty"
        )
    return matches[0]


def _markdown_rows(section: str, context: str) -> dict[str, str]:
    lines = [line for line in section.splitlines() if line.startswith("|")]
    if not lines or not lines[0].startswith("| "):
        raise StaticReTestFailure(
            f"{context} no longer reaches a real Markdown table"
        )
    rows: dict[str, str] = {}
    data_rows = 0
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or not cells[0]:
            continue
        data_rows += 1
        key = cells[0].strip("`")
        if key in rows:
            raise StaticReTestFailure(
                f"{context} is ambiguous because row {key!r} appears more than once"
            )
        rows[key] = line
    if data_rows == 0:
        raise StaticReTestFailure(
            f"{context} parsed no state or transition rows, so its claims went unchecked"
        )
    return rows


def _keyed_records(
    values: Any,
    key: str,
    expected_names: tuple[str, ...],
    context: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(values, list) or len(values) != len(expected_names):
        raise StaticReTestFailure(
            f"{context} no longer has the exact named recording census"
        )
    records: dict[str, dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get(key), str):
            raise StaticReTestFailure(
                f"{context} contains a recording without a usable {key} identity"
            )
        name = value[key]
        if name in records:
            raise StaticReTestFailure(
                f"{context} is ambiguous because recording {name!r} appears more than once"
            )
        records[name] = value
    if tuple(records) != expected_names:
        raise StaticReTestFailure(
            f"{context} no longer preserves the exact recording identities and order"
        )
    return records


def _require_tokens(text: str, tokens: tuple[str, ...], message: str) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise StaticReTestFailure(f"{message}; missing={missing}")


def _require_consecutive_ticks(rows: Any, context: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) < 20:
        raise StaticReTestFailure(
            f"{context} no longer reaches enough fixed-tick samples to check cadence"
        )
    ticks = [int(row["tick"]) for row in rows]
    if ticks[0] <= 0:
        raise StaticReTestFailure(
            f"{context} no longer begins on a real positive native tick"
        )
    if any(right != left + 1 for left, right in zip(ticks, ticks[1:])):
        raise StaticReTestFailure(
            f"{context} skips or duplicates a fixed tick, so frame cadence can drift"
        )
    return rows


def test_native_animation_state_lists_and_legal_transitions_are_pinned() -> str:
    doc = _read(DOC)
    roadmap = _read(ROADMAP)
    _require_tokens(
        doc,
        (
            "[`native-enemy-behavior.md`](native-enemy-behavior.md)",
            "[`native-scene-composition.md`](native-scene-composition.md)",
            "this document begins\n  at the action/state value that G3 produces",
            "supplies the sprite record and actor-local presentation values consumed by\n  that compositor",
        ),
        "G4 no longer cites the G3 decision boundary and G12 composition consumer",
    )

    wizard_rows = _markdown_rows(
        _section(doc, "WIZARD_PRESENTATION_STATES"),
        "wizard presentation-state list",
    )
    expected_wizard_states = {
        "absent",
        "idle",
        "walk",
        "action_tick_0(mode,K_previous)",
        "action_pose(mode,K)",
        "cast_pose_1`, `cast_pose_8`, `cast_pose_7",
        "hit_overlay(base)",
        "death_delay",
        "death_frame_0",
        "death_frame_1",
        "death_frame_2",
        "death_frame_3",
    }
    if set(wizard_rows) != expected_wizard_states:
        raise StaticReTestFailure(
            "wizard visible-state list no longer pins every locomotion, action, hit, and terminal state"
        )
    _require_tokens(
        wizard_rows["hit_overlay(base)"],
        ("+0x1D0", "2.0", "0.05", "40 ticks", "never interrupts"),
        "wizard hit overlay no longer preserves the body state with its exact interrupt rule",
    )
    _require_tokens(
        wizard_rows["death_delay"],
        ("D=0..150", "cannot be interrupted", "D=151"),
        "wizard terminal delay no longer pins its entry, boundary, and priority",
    )

    wizard_edges = _section(doc, "WIZARD_PRESENTATION_TRANSITIONS")
    _require_tokens(
        wizard_edges,
        (
            "absent -> idle",
            "idle <-> walk",
            "action_tick_0(mode,K_previous) -> action_pose(mode,K)",
            "action_pose(mode,K) -> action_pose(mode,K_next)",
            "hit_overlay(base) -> same underlying state",
            "action_pose|hit_overlay(base) -> death_delay",
            "death_delay -> death_frame_0 -> death_frame_1 -> death_frame_2 -> death_frame_3",
        ),
        "wizard legal transition graph or interrupt precedence is incomplete",
    )
    _require_tokens(
        doc,
        (
            "Death has highest presentation priority.",
            "movement\nand button release do not cancel that action",
            "Hit presentation interrupts\nneither action art nor locomotion",
        ),
        "wizard interruption semantics no longer prevent port-only animation resets",
    )

    enemy_rows = _markdown_rows(
        _section(doc, "ENEMY_PRESENTATION_STATE_LIST"),
        "enemy presentation-state list",
    )
    expected_enemy_rows = (
        "Badguy 0x3E8",
        "Skeleton 0x3E9",
        "SkeletonArcher 0x3EA",
        "SkeletonMage 0x3EB",
        "Imp 0x3EC",
        "GoodImp 0x3ED",
        "GreenImp 0x7FC",
        "Zombie 0x3EE",
        "Wraith 0x3EF",
        "DemonSkull 0x3F0",
        "Demon 0x3F1",
        "DireFaculty 0x3F2",
        "Heartmonger 0x3F3",
        "Crow 0x3F4",
        "Coffin 0x3F5",
        "Maggot 0x7FD",
        "Spider 0x809",
        "Cocoon 0x80A",
        "Portal 0x139D",
    )
    if tuple(enemy_rows) != expected_enemy_rows:
        raise StaticReTestFailure(
            "enemy visible-state table no longer names the exact 19 compiled families"
        )
    enemy_requirements = {
        "Badguy 0x3E8": ("invisible_alive", "death_handoff", "zero body facings"),
        "Skeleton 0x3E9": ("claw_windup/active/recovery", "weapon_windup/active/recovery", "pike_windup/active/recovery", "18 facings"),
        "SkeletonArcher 0x3EA": ("shot_windup/active/recovery", "+0x248", "18 facings"),
        "SkeletonMage 0x3EB": ("cast_windup/active/recovery", "shield_special", "18 facings"),
        "Imp 0x3EC": ("airborne", "contact/cooldown", "12 facings"),
        "GoodImp 0x3ED": ("ally_release", "12-facing"),
        "GreenImp 0x7FC": ("death_handoff", "12-facing"),
        "Zombie 0x3EE": ("punch_windup/active/recovery", "angular offset", "18 facings"),
        "Wraith 0x3EF": ("fade", "alpha/overlays", "18 facings"),
        "DemonSkull 0x3F0": ("beam", "scream", "24 facings"),
        "Demon 0x3F1": ("bomb_windup/active/recovery", "fire_special", "18 facings"),
        "DireFaculty 0x3F2": ("primary_windup/active/recovery", "secondary_windup/active/recovery", "29 banks x 18"),
        "Heartmonger 0x3F3": ("crow_attack", "summon", "18 facings"),
        "Crow 0x3F4": ("scan", "dive", "detached", "18 facings"),
        "Coffin 0x3F5": ("transition_delay", "no facing"),
        "Maggot 0x7FD": ("ballistic_emerge", "10 airborne orientations", "18 grounded facings"),
        "Spider 0x809": ("grab/hold", "suck", "18 facings"),
        "Cocoon 0x80A": ("attach", "release/death_handoff", "zero body facings"),
        "Portal 0x139D": ("materialize", "spawn_flash", "no heading facing"),
    }
    if set(enemy_requirements) != set(enemy_rows):
        raise StaticReTestFailure(
            "enemy state requirements no longer cover every named compiled family"
        )
    for family, tokens in enemy_requirements.items():
        _require_tokens(
            enemy_rows[family],
            tokens,
            f"{family} no longer pins its complete visible-state and facing identity",
        )

    enemy_edges = _markdown_rows(
        _section(doc, "ENEMY_PRESENTATION_TRANSITIONS"),
        "enemy legal-transition table",
    )
    expected_transition_rows = (
        "Badguy",
        "Skeleton",
        "SkeletonArcher",
        "SkeletonMage",
        "Imp / GreenImp",
        "GoodImp",
        "Zombie",
        "Wraith",
        "DemonSkull",
        "Demon",
        "DireFaculty",
        "Heartmonger",
        "Crow",
        "Coffin",
        "Maggot",
        "Spider",
        "Cocoon",
        "Portal",
    )
    if tuple(enemy_edges) != expected_transition_rows:
        raise StaticReTestFailure(
            "enemy legal-transition table no longer covers every family without an ambiguous duplicate"
        )
    transition_witnesses = {
        "Skeleton": ("windup -> active -> recovery", "death interrupts all"),
        "SkeletonArcher": ("shot_windup -> active -> recovery", "do not cancel"),
        "SkeletonMage": ("active <-> recovery", "death interrupts"),
        "DemonSkull": ("specials do not interrupt one another", "death interrupts"),
        "Spider": ("target loss", "death interrupts every state"),
        "Portal": ("materialize -> idle", "death is terminal"),
    }
    for family, tokens in transition_witnesses.items():
        _require_tokens(
            enemy_edges[family],
            tokens,
            f"{family} no longer pins the transition or interruption that changes visible art",
        )
    _require_tokens(
        roadmap,
        (
            "| G4 animation & presentation state machines | animre |",
            "**CLOSED 2026-08-05**",
            "reverse-engineering/native-animation-state.md",
            "tests/fixtures/webgame/animation-goldens.json",
            "`actor+0x238` is the wizard equipment/body pose selector",
        ),
        "browser rebuild roadmap no longer closes G4 with its concrete deliverables",
    )
    return "wizard and all 19 enemy-family presentation states and legal edges are pinned"


def test_native_animation_frame_programs_and_tick_anchor_are_pinned() -> str:
    doc = _read(DOC)
    clock_pattern = re.compile(
        r"fixed tick T \(100 Hz\)\n"
        r"  -> actor and action ticks write presentation fields\n"
        r"  -> zero or more further fixed ticks may run\n"
        r"  -> one render pass \(at most 60 Hz\) reads those fields"
    )
    if clock_pattern.search(doc) is None:
        raise StaticReTestFailure(
            "animation clock no longer preserves the exact fixed-tick-to-render nesting and order"
        )
    _require_tokens(
        doc,
        (
            "advances on **native fixed ticks**, not render frames",
            "100 Hz deterministic core",
            "p_next = p + base_rate * actor.attack_speed(+0x17C) * marker_rate_multiplier",
            "done   = p_next > end_frame",
        ),
        "animation cadence is no longer anchored to G1's fixed tick graph",
    )
    timing = _section(doc, "ANIMATION_FRAME_TIMING")
    _require_tokens(
        timing,
        (
            "branch A `[1,8,7,7,7]`, branch B `[8,7,7,7,7]`",
            "rate `0.075 * actor_delta`",
            "frame 0 lasts 2 ticks (`151..152`), frames 1 and 2 last 3 ticks",
            "`max(value-0.05,0)`",
            "`[4,5,6,7,8,9,10,11]`",
            "`[1 x8, 2, 3 x8, 2 x4, 1 x4]`",
            "`[1, 2 x11, 1]`",
            "`[3,4,5,6,7,6,7,6,7,6,7,6,7,8,8,8,8]`",
            "`[2 x24,3,4 x13,3,0 x3]`",
        ),
        "wizard Staff Cast 1 frame program or cadence is no longer exact",
    )
    _require_tokens(
        doc,
        (
            "| `1`, Staff melee `0x0044AE50`",
            "| `2`, Staff spin `0x00448750`",
            "| `3`, Staff Cast 1 `0x0044B170`",
            "| `4`, Staff Cast 2 `0x0044B7E0`",
            "| `5`, Staff one-shot",
            "| `6`, bare-hand Cast 1 `0x0044B400`",
            "| `7`, bare-hand Cast 2 `0x0044B5E0`",
            "| `8`, bare-hand one-shot",
            "| `9`, Wand Cast 1 `0x0044DF60`",
            "| `10`, Wand Cast 2 `0x0044E0D0`",
            "| `11`, Wand one-shot",
            "| `21`, cast spin `0x00448860`",
            "| `22`, sweep `0x004488F0`",
        ),
        "wizard action pose-program list no longer covers every recovered native mode",
    )

    golden = _golden()
    if golden.get("schema") != "solomon-dark-animation-goldens-v1":
        raise StaticReTestFailure(
            "animation fixture no longer declares the versioned G4 schema"
        )
    if golden.get("tick_graph") != {
        "fixed_tick_ms": 10,
        "render_rule": "one capture per native Region render; render frames sample the latest completed state and may skip fixed-tick poses",
        "fixed_tick_rule": "the additive observation lane records every local Player fixed tick while each render sequence is armed",
    }:
        raise StaticReTestFailure(
            "animation fixture no longer distinguishes fixed-tick advancement from render sampling"
        )
    wizard = _keyed_records(
        golden.get("wizard"),
        "name",
        (
            "idle",
            "idle_walk_idle",
            "idle_cast_idle",
            "idle_hit_overlay_idle",
            "cast_death_interrupt_frames",
        ),
        "wizard transition goldens",
    )
    for name, capture in wizard.items():
        _require_consecutive_ticks(
            capture.get("fixed_tick_frames"), f"wizard {name} recording"
        )

    walk_edges = [
        (edge["from"], edge["to"])
        for edge in wizard["idle_walk_idle"].get("transitions", [])
    ]
    if walk_edges != [
        ("absent", "idle"),
        ("idle", "walk"),
        ("walk", "idle"),
    ]:
        raise StaticReTestFailure(
            "wizard locomotion golden no longer covers idle-to-walk and walk-to-idle"
        )

    cast = wizard["idle_cast_idle"]
    cast_edges = cast.get("transitions")
    if not isinstance(cast_edges, list) or len(cast_edges) != 6:
        raise StaticReTestFailure(
            "wizard cast golden no longer reaches its exact six transition witnesses"
        )
    expected_cast_states = [
        "idle",
        "cast_pose_0",
        "cast_pose_1",
        "cast_pose_8",
        "cast_pose_7",
        "idle",
    ]
    if [edge["to"] for edge in cast_edges] != expected_cast_states:
        raise StaticReTestFailure(
            "wizard Staff Cast 1 golden no longer preserves the observed pose order"
        )
    cast_start = int(cast_edges[1]["tick"])
    if [int(edge["tick"]) - cast_start for edge in cast_edges[1:]] != [
        0,
        1,
        18,
        36,
        73,
    ]:
        raise StaticReTestFailure(
            "wizard Staff Cast 1 golden no longer pins its fixed-tick transition cadence"
        )
    cast_action_rows = [
        row
        for row in cast["fixed_tick_frames"]
        if int(row["action_count"]) == 1 and int(row["action_id"]) == 3
    ]
    if len(cast_action_rows) != 73:
        raise StaticReTestFailure(
            "wizard Staff Cast 1 golden no longer has one unambiguous 73-tick native action"
        )
    if [cast_action_rows[0]["pose_bank"], cast_action_rows[1]["pose_bank"]] != [0, 1]:
        raise StaticReTestFailure(
            "wizard Staff Cast 1 golden no longer proves insertion K=0 before first-tick K=1"
        )
    progress_deltas = [
        float(right["action_progress"]) - float(left["action_progress"])
        for left, right in zip(cast_action_rows, cast_action_rows[1:])
    ]
    if len(progress_deltas) != 72 or any(
        not math.isclose(delta, 0.05625, rel_tol=0.0, abs_tol=2.0e-6)
        for delta in progress_deltas
    ):
        raise StaticReTestFailure(
            "wizard Staff Cast 1 golden no longer advances by actor_delta times 0.075 on every fixed tick"
        )

    hit = wizard["idle_hit_overlay_idle"]
    hit_trigger = hit.get("trigger")
    if (
        not isinstance(hit_trigger, dict)
        or hit_trigger.get("method")
        != "existing typed-write probe seeds only shield capacity; a stock Skeleton hit drives the retail +0x1D0 pulse"
        or hit_trigger.get("escape_after_render_frames") != 4
        or not isinstance(hit_trigger.get("escape_position"), list)
        or len(hit_trigger["escape_position"]) != 2
    ):
        raise StaticReTestFailure(
            "wizard hit golden no longer isolates one stock hit before measuring the native decay"
        )
    hit_edges = [
        (edge["from"], edge["to"])
        for edge in hit.get("transitions", [])
    ]
    if ("idle", "hit_overlay") not in hit_edges or (
        "hit_overlay",
        "idle",
    ) not in hit_edges:
        raise StaticReTestFailure(
            "wizard hit golden no longer covers both entry and return without a body reset"
        )
    hit_rows = hit["fixed_tick_frames"]
    descending_pairs = [
        (float(left["magic_shield_hit_flash"]), float(right["magic_shield_hit_flash"]))
        for left, right in zip(hit_rows, hit_rows[1:])
        if 0.0 < float(right["magic_shield_hit_flash"]) < float(
            left["magic_shield_hit_flash"]
        )
    ]
    if len(descending_pairs) < 38:
        raise StaticReTestFailure(
            "wizard hit golden no longer reaches a complete native shield-pulse decay"
        )
    if any(
        not math.isclose(left - right, 0.05, rel_tol=0.0, abs_tol=2.0e-6)
        for left, right in descending_pairs
    ):
        raise StaticReTestFailure(
            "wizard hit golden no longer decays by exactly 0.05 per Player fixed tick"
        )

    death = wizard["cast_death_interrupt_frames"]
    death_edges = death.get("transitions")
    if not isinstance(death_edges, list) or len(death_edges) < 7:
        raise StaticReTestFailure(
            "wizard death golden no longer reaches cast interruption and all terminal frames"
        )
    if not any(
        str(edge["from"]).startswith("cast_pose_")
        and edge["to"] == "death_delay"
        for edge in death_edges
    ):
        raise StaticReTestFailure(
            "wizard death golden no longer proves that terminal state interrupts cast presentation"
        )
    terminal_rows = [
        row
        for row in death["fixed_tick_frames"]
        if 151 <= int(row["animation_duration_ticks"]) <= 161
    ]
    if len(terminal_rows) != 11:
        raise StaticReTestFailure(
            "wizard death golden no longer reaches the exact D=151 through D=161 cadence window"
        )
    expected_terminal_states = {
        151: "death_frame_0",
        152: "death_frame_0",
        153: "death_frame_1",
        154: "death_frame_1",
        155: "death_frame_1",
        156: "death_frame_2",
        157: "death_frame_2",
        158: "death_frame_2",
        159: "death_frame_3",
        160: "death_frame_3",
        161: "death_frame_3",
    }
    observed_terminal_states = {
        int(row["animation_duration_ticks"]): row["presentation_state"]
        for row in terminal_rows
    }
    if observed_terminal_states != expected_terminal_states:
        raise StaticReTestFailure(
            "wizard death golden no longer pins the two-tick frame zero and three-tick frames one/two"
        )

    skeleton = _keyed_records(
        golden.get("skeleton_family"),
        "name",
        ("skeleton", "skeleton_archer", "skeleton_mage"),
        "Skeleton-family animation goldens",
    )
    skeleton_contract = {
        "skeleton": (1001, 0x0E),
        "skeleton_archer": (1002, 0x11),
        "skeleton_mage": (1003, 0x12),
    }
    for name, capture in skeleton.items():
        expected_type, expected_action = skeleton_contract[name]
        frames = capture.get("frames")
        if not isinstance(frames, list) or len(frames) < 250:
            raise StaticReTestFailure(
                f"{name} golden no longer reaches enough live frames to cover combat and death"
            )
        if int(capture.get("type_id", 0)) != expected_type:
            raise StaticReTestFailure(
                f"{name} golden no longer identifies the intended native family"
            )
        states = {str(row.get("presentation_state")) for row in frames}
        if not {
            "attack_windup",
            "attack_active",
            "attack_recovery",
            "death",
        } <= states:
            raise StaticReTestFailure(
                f"{name} golden no longer covers windup, marker, recovery, and death handoff"
            )
        action_ids = {
            int(row["action_id"])
            for row in frames
            if isinstance(row.get("action_id"), int) and int(row["action_id"]) != 0
        }
        if action_ids != {expected_action}:
            raise StaticReTestFailure(
                f"{name} golden no longer resolves one unambiguous native action id"
            )
    return "fixed-tick wizard and Skeleton-family frame programs and transitions are pinned"


def test_native_animation_attachment_and_emitter_facings_are_pinned() -> str:
    doc = _read(DOC)
    projectile_doc = _read(PROJECTILE_DOC)
    attachment = _section(doc, "ANIMATION_ATTACHMENT")
    _require_tokens(
        attachment,
        (
            "`#460..#483`",
            "`g+0x590`",
            "unarmed hand/socket reference bank",
            "`#484..#603`",
            "`g+0x5A0`",
            "five 24-facing bare-hand cast/attachment pose banks",
            "`#796..#867`",
            "three 24-facing **wand** pose banks",
            "`#3244..#3483`",
            "ten 24-facing **staff** pose banks",
            "equipment/body render-pose selector",
            "record = Clothes[#3244 + 24*K + f]",
            "world_emitter = actor.position + local",
            "deliberately NO actor scale",
            "0x0061AF10",
            "each **render**",
            "0x0053B830",
            "**fixed-tick cast\n   event**",
        ),
        "Staff attachment formula no longer pins the named point runs, transform, and evaluation clocks",
    )
    facing = _section(doc, "ANIMATION_FACING")
    _require_tokens(
        facing,
        (
            "`f=((int)heading+7)/15; if f>=24 f-=24`",
            "`f=truncTowardZero((heading+10)/20); positiveMod(f,18)`",
            "`f=truncTowardZero((heading+15)/30); positiveMod(f,12)`",
            "airborne Maggot",
            "Coffin, Cocoon, Portal",
        ),
        "actor heading no longer maps to every family's discrete facing count",
    )
    _require_tokens(
        projectile_doc,
        (
            "| `#460..#483` | 24 | 1 × 24 | 2 | `[g+0x590]`",
            "| `#484..#603` | 120 | 5 × 24",
            "| `#796..#867` | 72 | **3 × 24**",
            "| `#3244..#3483` | 240 | **10 × 24**",
            "every facing is now `observed`, not `derived_only`",
        ),
        "projectile consumer no longer agrees with G4's named attachment arrays and live facing status",
    )

    golden = _golden()
    emitter = golden.get("cast_glyph_emitter")
    if not isinstance(emitter, dict):
        raise StaticReTestFailure(
            "animation fixture no longer contains a cast-glyph emitter recording"
        )
    if emitter.get("formula_under_test") != (
        "facing = ((int)heading + 7) / 15; if facing >= 24 then facing -= 24"
    ):
        raise StaticReTestFailure(
            "emitter golden no longer states the native one-subtract facing formula under test"
        )
    if emitter.get("observation_method") != (
        "forced actor heading followed by a synchronous call through retail 0x0053B830; output then matched to Clothes.bundle point 1"
    ):
        raise StaticReTestFailure(
            "emitter golden no longer distinguishes retail observation from formula replay"
        )
    facings = emitter.get("facings")
    if not isinstance(facings, list) or len(facings) != 24:
        raise StaticReTestFailure(
            "emitter golden no longer has one independent observation for every facing"
        )
    observed_ids = [int(row["facing"]) for row in facings]
    if observed_ids != list(range(24)):
        raise StaticReTestFailure(
            "emitter golden is missing, duplicates, or reorders a native facing observation"
        )
    epsilon = float(golden["header"]["epsilon"]["world_units"])
    if epsilon != 1.0e-4:
        raise StaticReTestFailure(
            "emitter golden no longer pins the justified sub-motion world-unit epsilon"
        )
    for expected_facing, row in enumerate(facings):
        if row.get("status") != "observed" or row.get("derived_only") is not False:
            raise StaticReTestFailure(
                f"emitter facing {expected_facing} lost its independent-observation status"
            )
        if not math.isclose(
            float(row["forced_heading_degrees"]),
            expected_facing * 15.0,
            rel_tol=0.0,
            abs_tol=epsilon,
        ) or not math.isclose(
            float(row["observed_heading_degrees"]),
            expected_facing * 15.0,
            rel_tol=0.0,
            abs_tol=epsilon,
        ):
            raise StaticReTestFailure(
                f"emitter facing {expected_facing} no longer observes its independently forced heading"
            )
        if row.get("pose_bank") != 7 or row.get("sprite_record") != 3412 + expected_facing:
            raise StaticReTestFailure(
                f"emitter facing {expected_facing} no longer selects Staff bank 7's shipped record"
            )
        if row.get("point_index") != 1:
            raise StaticReTestFailure(
                f"emitter facing {expected_facing} no longer reads point index one"
            )
        if row.get("attachment_object_type") != 7004 or int(
            row.get("attachment_address", 0)
        ) <= 0:
            raise StaticReTestFailure(
                f"emitter facing {expected_facing} no longer proves a live Staff 7004 attachment object"
            )
        if row.get("retail_resolver_preferred_address") != "0x0053B830":
            raise StaticReTestFailure(
                f"emitter facing {expected_facing} no longer records the retail resolver call target"
            )
        residual = row.get("asset_match_residual")
        if not isinstance(residual, list) or len(residual) != 2 or max(
            abs(float(value)) for value in residual
        ) > epsilon:
            raise StaticReTestFailure(
                f"emitter facing {expected_facing} no longer matches its shipped Staff point within epsilon"
            )
    wrap = emitter.get("wrap_observation")
    if not isinstance(wrap, dict) or wrap.get("heading_degrees") != 359.0 or wrap.get(
        "observed_facing"
    ) != 0:
        raise StaticReTestFailure(
            "emitter golden no longer independently observes the heading-359 one-subtract wrap"
        )
    bank_zero = emitter.get("bank_zero_reference")
    if not isinstance(bank_zero, dict) or {
        "facing": bank_zero.get("facing"),
        "pose_bank": bank_zero.get("pose_bank"),
        "sprite_record": bank_zero.get("sprite_record"),
        "point_index": bank_zero.get("point_index"),
    } != {"facing": 19, "pose_bank": 0, "sprite_record": 3263, "point_index": 1}:
        raise StaticReTestFailure(
            "emitter golden no longer pins the live first-cast bank-zero Staff reference"
        )

    wizard = golden.get("wizard")
    if not isinstance(wizard, list) or len(wizard) != 5:
        raise StaticReTestFailure(
            "attachment transform check no longer reaches the exact wizard capture census"
        )
    attached_draws = [
        draw
        for capture in wizard
        for frame in capture.get("frames", [])
        for draw in frame.get("sprites", [])
        if draw.get("attachment_matrix") is not None
    ]
    if not attached_draws:
        raise StaticReTestFailure(
            "attachment transform check reached no live Staff or wand draw witness"
        )
    witness = attached_draws[0]
    if witness.get("atlas") != "Clothes" or not 3244 <= int(
        witness.get("sprite_index", -1)
    ) <= 3723:
        raise StaticReTestFailure(
            "attachment transform witness no longer comes from the paired Staff art arrays"
        )
    matrix = witness.get("attachment_matrix")
    if not isinstance(matrix, list) or len(matrix) != 16 or witness.get(
        "transform_kind"
    ) != "matrix4x4":
        raise StaticReTestFailure(
            "attachment transform witness no longer carries the evaluated native 4x4 matrix"
        )
    return "Staff pose-bank attachment and all 24 independently observed emitter facings are pinned"


def test_native_animation_lighting_shadow_and_camera_constants_are_pinned() -> str:
    doc = _read(DOC)
    lighting = _section(doc, "ANIMATION_LIGHTING_SHADOW")
    _require_tokens(
        lighting,
        (
            "Puppet_RenderDispatch 0x00624B40",
            "Complex\nLighting enabled (`0x00B3BCA8`)",
            "`0x0057F980`, `0x0057F0E0`, or the transformed query `0x0057E490`",
            "actor `+0xCC`",
            "With\nComplex Lighting disabled the scalar is `1`",
            "Complex Shadows and Multiple Shadows are the stock\nglobals `0x00B3BCA9` and `0x00B3BCAA`",
            "Anim_Bouncer",
            "`(x,y+2)`, scale `(1,0.75)`",
            "[`Fog, lighting, tint, alpha, and blend`](native-scene-composition.md#fog-lighting-tint-alpha-and-blend)",
            "15 world units along\nheading with radius `2.6`, intensity `1`, flag `1`",
        ),
        "actor lighting and shadow model no longer pins native sampling while citing G12 composition",
    )
    camera = _section(doc, "ANIMATION_CAMERA")
    _require_tokens(
        camera,
        (
            "`+0x80` scale",
            "`+0x8BCC/+0x8BD0` primary origin",
            "`+0x8BD4/+0x8BD8` primary size",
            "`+0x8BDC/+0x8BE0` expanded origin",
            "`+0x8BEC/+0x8BF0` culling origin",
            "`+0x8E04/+0x8E08` shake magnitude/accumulator",
            "`0x0063ED80` / `0x00462110`",
            "interpolation remains `0.25`",
            "Skeleton\ndeath requests shake intensity `0.1`",
            "camera culling must not pause an actor's fixed-tick phase",
        ),
        "animation camera constants no longer reconcile native-camera-control at the presentation boundary",
    )

    golden = _golden()
    wizard = golden.get("wizard")
    skeleton = golden.get("skeleton_family")
    if not isinstance(wizard, list) or len(wizard) != 5 or not isinstance(
        skeleton, list
    ) or len(skeleton) != 3:
        raise StaticReTestFailure(
            "camera payload check no longer reaches every wizard and Skeleton-family recording"
        )
    cameras = [capture.get("camera_reference") for capture in wizard + skeleton]
    if len(cameras) != 8:
        raise StaticReTestFailure(
            "camera payload check no longer has one reference for each live actor recording"
        )
    expected_camera_keys = {
        "scale",
        "world_bounds",
        "primary_view",
        "expanded_view",
        "culling_view",
        "shake_magnitude",
        "shake_accumulator",
    }
    for index, value in enumerate(cameras):
        if not isinstance(value, dict) or set(value) != expected_camera_keys:
            raise StaticReTestFailure(
                f"camera reference {index} no longer distinguishes semantic, expanded, culling, and shake state"
            )
        if float(value["scale"]) <= 0.0:
            raise StaticReTestFailure(
                f"camera reference {index} no longer records a runnable native projection scale"
            )
        for rect_name in ("world_bounds", "primary_view", "expanded_view", "culling_view"):
            rect = value[rect_name]
            if not isinstance(rect, list) or len(rect) != 4:
                raise StaticReTestFailure(
                    f"camera reference {index} no longer records the four-field {rect_name} rectangle"
                )

    sprite_draws = [
        draw
        for capture in wizard
        for frame in capture.get("frames", [])
        for draw in frame.get("sprites", [])
    ]
    if not sprite_draws:
        raise StaticReTestFailure(
            "lighting payload check reached no live actor sprite submission"
        )
    lit_draws = [draw for draw in sprite_draws if draw.get("lighting_scalar") is not None]
    if not lit_draws:
        raise StaticReTestFailure(
            "lighting payload check reached no actor draw carrying the native light scalar"
        )
    for index, draw in enumerate(lit_draws):
        tint = draw.get("tint")
        if not isinstance(tint, dict) or set(tint) != {"r", "g", "b", "a"}:
            raise StaticReTestFailure(
                f"lit actor draw {index} no longer keeps RGBA tint separate from its light scalar"
            )
        if not math.isfinite(float(draw["lighting_scalar"])):
            raise StaticReTestFailure(
                f"lit actor draw {index} no longer records a finite native light sample"
            )
    return "actor light/shadow inputs and camera constants consumed by animation are pinned"


def test_native_animation_recorder_is_self_provenanced_settled_and_bounded() -> str:
    recorder = _read(RECORDER)
    try:
        tree = ast.parse(recorder)
    except SyntaxError as error:
        raise StaticReTestFailure(
            f"animation recorder is not runnable Python: {error}"
        ) from error
    main_functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    ]
    if len(main_functions) != 1:
        raise StaticReTestFailure(
            "animation recorder no longer has one unambiguous executable main function"
        )
    argument_calls = [
        node
        for node in ast.walk(main_functions[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
    ]
    if len(argument_calls) != 2:
        raise StaticReTestFailure(
            "animation recorder no longer exposes exactly output and raw-root controls"
        )
    argument_names = []
    for call in argument_calls:
        if not call.args or not isinstance(call.args[0], ast.Constant) or not isinstance(
            call.args[0].value, str
        ):
            raise StaticReTestFailure(
                "animation recorder has an ambiguous non-literal command-line option"
            )
        argument_names.append(call.args[0].value)
    if set(argument_names) != {"--output", "--raw-root"}:
        raise StaticReTestFailure(
            "animation recorder permits provenance input instead of deriving it itself"
        )
    for forbidden in (
        "--source-commit",
        "--source-tree",
        "--game-binary-sha256",
        "--loader-sha256",
        "--process-id",
    ):
        if forbidden in recorder:
            raise StaticReTestFailure(
                f"animation recorder accepts forbidden hand-authored provenance through {forbidden}"
            )
    source_position = recorder.find("source = source_revision()")
    launch_position = recorder.find("launch = session.launch()")
    cleanup_position = recorder.find("cleanup = session.close()")
    encode_position = recorder.find("encoded = json.dumps(document")
    if min(source_position, launch_position, cleanup_position, encode_position) < 0:
        raise StaticReTestFailure(
            "animation recorder lost a source, launch, cleanup, or serialization execution witness"
        )
    if not source_position < launch_position < cleanup_position < encode_position:
        raise StaticReTestFailure(
            "animation recorder no longer derives provenance before launch and cleanup before fixture publication"
        )
    _require_tokens(
        recorder,
        (
            "INSTANCE = \"anm-g4\"",
            "PORTS = (52331, 52332)",
            "SETTLE_SAMPLE_FLOOR = 40",
            "SETTLE_SECONDS_FLOOR = 2.0",
            "for independent_capture in range(2):",
            "session.assert_wait_target_runnable(f\"{label} structural settle\")",
            "signature == prior_signature",
            "raw_directory.mkdir(parents=True, exist_ok=False)",
            "windows_sha256(GAME_BINARY)",
            "windows_sha256(LOADER)",
            "windows_sha256(STAGED_LOADER)",
            'settle_actor_surface(\n            session, "wizard cast target"\n        )',
            "for attempt in range(1, 9):",
            "sd.input.hold_mouse_left_frames(24)",
            "sd.input.pin_manual_primary_target(target)",
            "len(matches) <= 1",
            "values.get(\"found\") in {\"0\", \"1\"}",
        ),
        "animation recorder no longer enforces isolation, runnability, settle, provenance, or ambiguity refusal",
    )
    native_sim = _read(NATIVE_SIM_RECORDER)
    if 'environment["SDMOD_DISABLE_AUDIO"] = "1"' not in native_sim:
        raise StaticReTestFailure(
            "animation recorder's owned solo launcher no longer disables stock audio"
        )

    capture_cpp = _read(SCENE_CAPTURE_CPP)
    capture_public = _read(SCENE_CAPTURE_PUBLIC)
    serialization = _read(SCENE_CAPTURE_SERIALIZATION)
    player_tick = _read(PLAYER_TICK_HOOK)
    emitter_binding = _read(EMITTER_BINDING)
    _require_tokens(
        capture_cpp,
        ("kMaximumFixedTickAnimationSamples = 4096",),
        "native animation observation lane no longer has its 4096-sample fail-closed bound",
    )
    _require_tokens(
        capture_public,
        (
            "frame_count == 0 || frame_count > 512",
            "native scene capture is busy with label",
            "refuses to overwrite any sequence output or temporary file",
            "fixed-tick animation history exceeded its 4096-sample bound",
            "if (capture.action_count == 1)",
            "could not resolve the local player fixed-tick action",
        ),
        "native animation capture seam no longer separates busy/broken states, bounds output, or refuses ambiguous actions",
    )
    if "capture.action_count > 0" in capture_public:
        raise StaticReTestFailure(
            "native animation capture seam may silently select among duplicate queued actions"
        )
    _require_tokens(
        player_tick,
        ("NativeSceneCaptureObservePlayerFixedTick(\n            actor_address,\n            local_simulation_tick);",),
        "local Player fixed ticks no longer feed the animation observation lane after stock tick",
    )
    _require_tokens(
        serialization,
        (
            'stream << ",\\n  \\"player_fixed_tick_animation\\": ";',
            'stream << ",\\"magic_shield_hit_flash\\":";',
            'stream << ",\\"action_count\\":" << fixed_tick->action_count',
            '<< ",\\"action_id\\":" << fixed_tick->action_id',
            '<< ",\\"action_progress\\":";',
        ),
        "scene fixture serialization no longer carries animation cadence and hit-state fields",
    )
    _require_tokens(
        emitter_binding,
        (
            "ResolveExecutableLuaAddress(\n        memory, kEmitterPreferredAddress)",
            "retail cast-glyph emitter is not executable",
            "returned = emitter(\n            reinterpret_cast<void*>(player.actor_address), result);",
            "player.attachment_visual_lane.current_object_address",
            "player.attachment_visual_lane.current_object_type_id",
        ),
        "cast-emitter probe no longer calls runnable retail code and reports the live equipment sink",
    )

    golden = _golden()
    header = golden.get("header")
    if not isinstance(header, dict):
        raise StaticReTestFailure(
            "animation fixture no longer carries recorder-derived provenance"
        )
    if header.get("instance") != "anm-g4" or header.get(
        "worktree_dirty_at_capture_start"
    ) is not False:
        raise StaticReTestFailure(
            "animation fixture was not recorded from the clean isolated anm-g4 checkout"
        )
    for key in ("source_commit_sha", "source_tree_sha"):
        if re.fullmatch(r"[0-9a-f]{40}", str(header.get(key, ""))) is None:
            raise StaticReTestFailure(
                f"animation fixture no longer derives a full Git {key}"
            )
    for key in (
        "game_binary_sha256",
        "loader_sha256",
        "staged_loader_sha256",
    ):
        if re.fullmatch(r"[0-9a-f]{64}", str(header.get(key, ""))) is None:
            raise StaticReTestFailure(
                f"animation fixture no longer derives the external runtime {key}"
            )
    if header["loader_sha256"] != header["staged_loader_sha256"]:
        raise StaticReTestFailure(
            "animation fixture was captured with a staged loader different from its Release build"
        )
    if header.get("fixed_tick_ms") != 10 or header.get("epsilon") != {
        "world_units": 0.0001,
        "screen_pixels": 0.001,
        "justification": "native positions and attachment points are float32/x87 values; 1e-4 world units exceeds representation noise while staying below observed motion, and 0.001 screen pixels matches the native scene serializer",
    }:
        raise StaticReTestFailure(
            "animation fixture header no longer pins its tick anchor and epsilon justification"
        )
    if int(header.get("process_id", 0)) <= 0 or not str(
        header.get("executable_path", "")
    ).endswith(r"runtime\animre-live\instances\anm-g4\stage\SolomonDark.exe"):
        raise StaticReTestFailure(
            "animation fixture no longer identifies the exact launched anm-g4 executable"
        )

    wizard = golden.get("wizard")
    skeleton = golden.get("skeleton_family")
    emitter = golden.get("cast_glyph_emitter")
    if not isinstance(wizard, list) or len(wizard) != 5:
        raise StaticReTestFailure(
            "provenance check no longer reaches all five wizard recordings"
        )
    if not isinstance(skeleton, list) or len(skeleton) != 3:
        raise StaticReTestFailure(
            "provenance check no longer reaches all three Skeleton-family recordings"
        )
    if not isinstance(emitter, dict):
        raise StaticReTestFailure(
            "provenance check no longer reaches the emitter recording"
        )
    child_headers = [capture.get("header") for capture in wizard]
    child_headers += [capture.get("header") for capture in skeleton]
    child_headers.append(emitter.get("header"))
    provenance_keys = {
        "instance",
        "process_id",
        "executable_path",
        "source_commit_sha",
        "source_tree_sha",
        "worktree_dirty_at_capture_start",
        "game_binary_sha256",
        "loader_sha256",
        "staged_loader_sha256",
        "fixed_tick_ms",
        "epsilon",
    }
    if len(child_headers) != 9 or any(
        not isinstance(value, dict)
        or {key: value.get(key) for key in provenance_keys}
        != {key: header.get(key) for key in provenance_keys}
        for value in child_headers
    ):
        raise StaticReTestFailure(
            "animation fixture carries conflicting provenance copies across its live recordings"
        )
    if emitter["header"].get("capture_method") != (
        "forced heading plus synchronous call-through to retail cast emitter 0x0053B830"
    ):
        raise StaticReTestFailure(
            "emitter recording no longer identifies its independent retail observation method"
        )

    cast_target = wizard[2].get("target_receipt")
    if (
        not isinstance(cast_target, dict)
        or int(cast_target.get("actor_address", 0)) <= 0
        or int(cast_target.get("type_id", 0)) != 1001
        or int(cast_target.get("request_id", 0)) <= 0
        or int(cast_target.get("stock_spawner_address_observed", 0)) <= 0
        or cast_target.get("capture_retirement") != {
            "requested": True,
            "already_absent": False,
        }
    ):
        raise StaticReTestFailure(
            "wizard cast golden no longer proves a settled live Skeleton target and its retirement"
        )

    settle_gates = [golden.get("settle_gate")]
    settle_gates.append(wizard[2].get("settle_gate"))
    settle_gates += [capture.get("settle_gate") for capture in skeleton]
    settle_gates += [
        capture.get("spawn_receipt", {})
        .get("death_witness", {})
        .get("settle_gate")
        for capture in skeleton
    ]
    if len(settle_gates) != 8 or any(not isinstance(gate, dict) for gate in settle_gates):
        raise StaticReTestFailure(
            "animation fixture no longer records every initial, cast-target, combat, and death structural settle gate"
        )
    for gate_index, gate in enumerate(settle_gates):
        captures = gate.get("captures")
        if not isinstance(captures, list) or len(captures) != 2:
            raise StaticReTestFailure(
                f"animation settle gate {gate_index} no longer has two independent captures"
            )
        hashes = []
        for capture_index, capture in enumerate(captures):
            if int(capture.get("stable_samples", 0)) < 40 or float(
                capture.get("stable_seconds", 0.0)
            ) < 2.0:
                raise StaticReTestFailure(
                    f"animation settle gate {gate_index}.{capture_index} no longer spans 40 stable samples and two seconds"
                )
            if capture.get("animated_element_set") != []:
                raise StaticReTestFailure(
                    f"animation settle gate {gate_index}.{capture_index} no longer has a reproducible empty structural animation set"
                )
            digest = str(capture.get("structural_signature_sha256", ""))
            if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise StaticReTestFailure(
                    f"animation settle gate {gate_index}.{capture_index} no longer hashes its structural payload"
                )
            hashes.append(digest)
        if hashes[0] != hashes[1]:
            raise StaticReTestFailure(
                f"animation settle gate {gate_index} no longer reproduces across independent captures"
            )

    cleanup = golden.get("cleanup")
    if not isinstance(cleanup, list) or len(cleanup) != 1:
        raise StaticReTestFailure(
            "animation fixture no longer has one exact-owned-process cleanup receipt"
        )
    receipt = cleanup[0]
    if (
        receipt.get("instance") != "anm-g4"
        or int(receipt.get("processId", 0)) != int(header["process_id"])
        or receipt.get("pathMatched") is not True
        or receipt.get("stopped") is not True
        or receipt.get("expectedPath") != receipt.get("actualPath")
    ):
        raise StaticReTestFailure(
            "animation fixture no longer proves exact path-matched cleanup of its launched PID"
        )
    return "animation recorder provenance, settle gates, ambiguity checks, bounds, and cleanup are pinned"
