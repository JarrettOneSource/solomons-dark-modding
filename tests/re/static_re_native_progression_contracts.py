"""Static contracts for native XP, level-up offers, and skill effects."""

from __future__ import annotations

import ast
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

from static_re_contract_support import ROOT, StaticReTestFailure, read_text


DOC = ROOT / "docs/reverse-engineering/native-progression-and-skills.md"
SKILL_PICKER_DOC = ROOT / "docs/skill-picker-re.md"
AUDIO_EVENTS_DOC = ROOT / "docs/reverse-engineering/native-audio-events.md"
FIXTURE = ROOT / "tests/fixtures/webgame/progression-goldens.json"
RECORDER = ROOT / "tools/record_progression_goldens.py"
SKILL_CATALOG = ROOT / "docs/reverse-engineering/native-skill-catalog.json"
SPELL_WELDING_DOC = ROOT / "docs/reverse-engineering/spell-welding.md"
NATIVE_SKILLS_DOC = ROOT / "docs/reverse-engineering/native-skills-and-spells.md"

LEVEL_THRESHOLDS = (
    0,
    90,
    160,
    275,
    390,
    520,
    650,
    800,
    1060,
    1300,
    1600,
    2000,
    2400,
    2850,
    3400,
    4200,
    4800,
    5650,
    6000,
    6500,
    7200,
    7850,
    8900,
    9900,
    11000,
    12000,
    13000,
    14000,
    15000,
    16000,
    20000,
    25000,
    30000,
    35000,
    40000,
    45000,
    51000,
    57000,
    64000,
    71000,
    79000,
    88000,
    98000,
    110000,
    120000,
    130000,
    135000,
    150000,
    175000,
    200000,
    300000,
    400000,
    500000,
    600000,
    700000,
    800000,
    900000,
    1000000,
    1200000,
    1400000,
    1700000,
    2000000,
    2300000,
    2600000,
    3000000,
    3500000,
    4000000,
    4500000,
    5000000,
    5500000,
    6000000,
    6500000,
    7000000,
    7500000,
    8500000,
    10000000,
)

EXPECTED_MINIMUM_LEVELS = (
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 3, 25, 20, 20, 6,
    1, 1, 1, 20, 20, 4, 12, 8, 1, 1, 1, 1, 12, 20, 12, 20,
    1, 1, 1, 1, 20, 20, 18, 16, 1, 3, 1, 1, 20, 6, 25, 20,
    1, 1, 1, 18, 1, 8, 4, 10, 1, 1, 8, 5, 8, 25, 18, 12,
    1, 1, 10, 1, 10, 6, 25, 5, 1, 5, 10, 10, 10, 6, 10, 10,
    0, 0,
)
EXPECTED_ROOTS = (
    0, 1, 2, 3, 4, 5, 6, 7, 0, 0, 0, 0, 0, 0, 0, 0,
    1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2,
    3, 3, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4,
    7, 7, 7, 7, 7, 7, 7, 7, 6, 6, 6, 6, 6, 6, 6, 6,
    5, 5, 5, 5, 5, 5, 5, 5, 2, 1, 0, 4, 3, 7, 6, 5,
    -1, -1,
)
EXPECTED_CATEGORIES = (
    4, 4, 4, 4, 4, 4, 4, 4, 1, 0, 0, 2, 2, 4, 4, 2,
    1, 0, 0, 4, 4, 2, 0, 2, 1, 0, 0, 2, 0, 4, 2, 4,
    1, 0, 0, 2, 4, 4, 0, 0, 1, 2, 0, 0, 4, 2, 2, 4,
    2, 2, 2, 2, 1, 0, 2, 0, 0, 3, 3, 3, 3, 3, 3, 3,
    0, 3, 3, 3, 3, 3, 3, 3, 2, 2, 2, 0, 2, 2, 2, 2,
    0, 0,
)
EXPECTED_REQUIRES_ALL = {
    9: ((8, 1),),
    10: ((8, 1),),
    13: ((9, 1),),
    14: ((9, 1),),
    17: ((18, 1),),
    18: ((16, 1),),
    19: ((17, 1),),
    20: ((17, 1),),
    25: ((24, 1),),
    26: ((24, 1),),
    28: ((27, 1),),
    29: ((25, 1),),
    31: ((25, 1),),
    33: ((32, 1),),
    34: ((32, 1),),
    36: ((33, 1),),
    37: ((33, 1),),
    38: ((34, 1),),
    42: ((40, 1),),
    43: ((40, 1),),
    44: ((43, 1),),
    47: ((43, 1),),
    55: ((54, 1),),
    61: ((59, 1),),
    68: ((71, 1),),
    71: ((65, 1),),
    75: ((45, 1),),
}
EXPECTED_REQUIRES_ANY = {
    22: (16, 21, 23),
    30: (24, 27),
    39: (32, 35),
}
EXPECTED_FORBIDDEN = {
    13: ((14, 1),),
    14: ((13, 1),),
    19: ((20, 1),),
    20: ((19, 1),),
    29: ((31, 1),),
    31: ((29, 1),),
    36: ((37, 1),),
    37: ((36, 1),),
    44: ((47, 1),),
    47: ((44, 1),),
}


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StaticReTestFailure(
                f"progression golden JSON has ambiguous duplicate key {key!r}"
            )
        result[key] = value
    return result


def _load_json_object(path: Path, consequence: str) -> dict[str, Any]:
    try:
        value = json.loads(
            read_text(path), object_pairs_hook=_reject_duplicate_object_keys
        )
    except (json.JSONDecodeError, OSError) as error:
        raise StaticReTestFailure(f"{consequence}: {error}") from error
    if not isinstance(value, dict):
        raise StaticReTestFailure(f"{consequence}: top level is not an object")
    return value


def _unique_rows(
    value: Any,
    *,
    identity: str,
    consequence: str,
) -> dict[int, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise StaticReTestFailure(f"{consequence}: no real rows were reached")
    result: dict[int, dict[str, Any]] = {}
    for row_index, row in enumerate(value):
        if not isinstance(row, dict) or type(row.get(identity)) is not int:
            raise StaticReTestFailure(
                f"{consequence}: row {row_index} has no integer {identity}"
            )
        row_id = int(row[identity])
        if row_id in result:
            raise StaticReTestFailure(
                f"{consequence}: duplicate {identity} {row_id} is ambiguous"
            )
        result[row_id] = row
    return result


def _require_tokens(text: str, tokens: Iterable[str], consequence: str) -> None:
    token_list = tuple(tokens)
    if not token_list:
        raise StaticReTestFailure(f"{consequence}: contract supplied no witnesses")
    missing = [token for token in token_list if token not in text]
    if missing:
        raise StaticReTestFailure(
            f"{consequence}: missing semantic witness(es) {missing}"
        )


def _top_level_function(tree: ast.Module, name: str, consequence: str) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(matches) != 1:
        raise StaticReTestFailure(
            f"{consequence}: expected one unambiguous {name}, found {len(matches)}"
        )
    return matches[0]


def _source_segment(source: str, node: ast.AST, consequence: str) -> str:
    segment = ast.get_source_segment(source, node)
    if not segment:
        raise StaticReTestFailure(f"{consequence}: source segment was unreachable")
    return segment


def _close(actual: float, expected: float, tolerance: float, consequence: str) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
        raise StaticReTestFailure(
            f"{consequence}: expected {expected!r}, recorded {actual!r}"
        )


def test_native_level_up_presentation_and_picker_reveal_are_pinned() -> str:
    picker = read_text(SKILL_PICKER_DOC)
    audio = read_text(AUDIO_EVENTS_DOC)
    _require_tokens(
        picker,
        (
            "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3",
            "`0x0067C250` consumes every crossed threshold",
            "tail-calls\n   `0x005C88B0` exactly once",
            "writes float `180.0` to PlayerActor `+0x168`",
            "BadGuys record 73",
            "180 ticks / 1.8 s",
            "36--60 ticks, not one fixed 60-tick lifetime",
            "`x = RandomFloat(30, true)`",
            "`y = -20 - RandomFloat(playerY - viewportTop, false)`",
            "exact five-word order",
            "unsigned Y magnitude, signed-X magnitude, signed-X sign, unsigned angle",
            "closed endpoint domain and intermediate float32 stores",
            "The X sign\n   is chosen by the second word's bit 6",
            "moves Y by\n   `-0.1` per tick",
            "`sin(particleTimer degrees)` as uniform scale",
            "there is no\n   independent random-alpha multiplier",
            "`0x005299A0` observes the same `+0x168` timer",
            "`(actor[+0x268] + 1) * 2.6 + sin(timer degrees)`",
            "`2.6 - RandomFloat(0.2, false)` is not stored",
            "rather than adding a second\n   player light",
            "opening reveal is therefore 40\nticks / 0.4 s at 100 Hz",
            "`0.5 * revealAlpha`",
            "`revealAlpha^3`",
            "must not replay the threshold\nsound/effect",
            "does not\ncall `0x005C88B0`",
            "entry 64 `sounds\\openpanel`",
            "entry 102 `sounds\\unlockskill`",
            "pointer hover and any non-native keyboard/gamepad focus graph supplied by a\n  port",
            "entry 1\n  `sounds\\pickskill`",
            "pitch `0.75`",
            "10-tick blank\n  rebuild handoff",
            "clears `+0x604` at\n  `0x0066FCE4`",
            "selector 17 `SORCEROR'S CHARM` is exactly `progression + 0x7DD`",
            "entry 93 `sounds\\summon`",
            "pitch `0.8`",
            "increments deferred choices at `progression + 0x48`",
            "record 57 at the SAVE SKILL rectangle and record 56 at ROLL AGAIN",
            "Entry 53 `sounds\\levelupskill` is loaded but no retail",
        ),
        "native level-up presentation lost a timer, render lane, queue, or audio witness",
    )
    _require_tokens(
        audio,
        (
            "| `level.up` | One local level-award invocation crosses at least "
            "one threshold | `0x0067C30B -> 0x005C88B0 -> 0x00528A3E`",
            "Gain `1.0`, once after `0x0067C250` has looped every threshold "
            "crossed by that award",
            "Asset 52 has one distinct skill consumer: `skill.turn_undead.cast`",
            "`0x00647F6B` and `0x00647FBE` inside `0x00647EF0` issue\n"
            "two point requests at pitch multipliers `2` then `3`",
        ),
        "native audio map merged the level transition back into Turn Undead",
    )
    return "level-up actor effect, picker reveal lanes, queue semantics, and corrected audio ownership are pinned"


def test_native_progression_level_curve_and_xp_awards_are_pinned() -> str:
    doc = read_text(DOC)
    section_matches = re.findall(
        r"(?ms)^### Exact level curve\n(?P<body>.*?)(?=^## Level-up offer pool and selection$)",
        doc,
    )
    if len(section_matches) != 1:
        raise StaticReTestFailure(
            "native level curve must occupy one unambiguous documented section"
        )
    table_rows = re.findall(
        r"(?m)^\| (?P<l1>\d+|-) \| (?P<t1>\d+|-) "
        r"\| (?P<l2>\d+|-) \| (?P<t2>\d+|-) "
        r"\| (?P<l3>\d+|-) \| (?P<t3>\d+|-) \|$",
        section_matches[0],
    )
    if len(table_rows) != 26:
        raise StaticReTestFailure(
            "native level curve table no longer has its 26 explicit structural rows"
        )
    recovered: dict[int, int] = {}
    for row_index, row in enumerate(table_rows):
        for column in range(0, 6, 2):
            level_text, threshold_text = row[column], row[column + 1]
            if (level_text == "-") != (threshold_text == "-"):
                raise StaticReTestFailure(
                    f"native level curve row {row_index} has a half-empty level/threshold cell"
                )
            if level_text == "-":
                continue
            level = int(level_text)
            if level in recovered:
                raise StaticReTestFailure(
                    f"native level curve contains ambiguous duplicate level {level}"
                )
            recovered[level] = int(threshold_text)
    if len(LEVEL_THRESHOLDS) != 76:
        raise StaticReTestFailure(
            "native level curve contract itself lost the 76 recovered thresholds"
        )
    if sorted(recovered) != list(range(76)):
        raise StaticReTestFailure(
            "native level curve no longer names every level 0 through 75 exactly once"
        )
    for level, expected in enumerate(LEVEL_THRESHOLDS):
        if recovered[level] != expected:
            raise StaticReTestFailure(
                f"native level {level} threshold changed from exact value {expected}"
            )
    cap_pattern = re.compile(
        r"\*\*Stock cap defect and browser rule\.\*\* Level 75 is entered at "
        r"8,500,000 XP\..*?last table value, 10,000,000, is the threshold to "
        r"leave level 75\..*?MUST clamp at level 75.*?issue no further offers",
        re.DOTALL,
    )
    if cap_pattern.search(section_matches[0]) is None:
        raise StaticReTestFailure(
            "native level-cap contract no longer distinguishes the stock overrun from the browser clamp"
        )

    factor_rows = re.findall(
        r"(?m)^\| (normal|survival) \| ([^|]+?) \| (`[^`]+`) \|$",
        doc,
    )
    expected_factors = [
        ("normal", "1", "`1`"),
        ("normal", "2", "`0.75`"),
        ("normal", "3-4", "`0.75^2 = 0.5625`"),
        ("normal", "5+", "`0.75^3 = 0.421875`"),
        ("survival", "1", "`1`"),
        ("survival", "2-5", "`0.9`"),
        ("survival", "6-15", "`0.9 * 0.8 = 0.72`"),
        ("survival", "16-30", "`0.9 * 0.8 * 0.7 = 0.504`"),
        ("survival", "31+", "`0.9 * 0.8 * 0.7 * 0.6 = 0.3024`"),
    ]
    if factor_rows != expected_factors:
        raise StaticReTestFailure(
            "native XP level multipliers no longer pin all normal and survival brackets exactly"
        )

    family_sections = re.findall(
        r"(?ms)^### One-player family rewards\n(?P<body>.*?)(?=^### Exact level curve$)",
        doc,
    )
    if len(family_sections) != 1:
        raise StaticReTestFailure(
            "native XP family census must occupy one unambiguous documented section"
        )
    family_rows = [
        (family.strip(), baseline)
        for family, baseline in re.findall(
            r"(?m)^\| ([^|]+?) \| (\d+|none) \|.*\|$",
            family_sections[0],
        )
    ]
    expected_families = [
        ("Badguy base/fallback", "10"),
        ("Skeleton / Skeleton Archer / Skeleton Mage", "10"),
        ("Imp", "2"),
        ("Good Imp", "none"),
        ("Zombie", "210"),
        ("Wraith", "4"),
        ("Demon Skull", "7000"),
        ("Demon", "800"),
        ("Dire Faculty", "4020"),
        ("Heartmonger", "4000"),
        ("Crow", "none"),
        ("Coffin", "200"),
        ("Green Imp", "2"),
        ("Maggot", "0"),
        ("Spider", "30"),
        ("Cocoon", "10"),
        ("Portal", "600"),
        ("XP Bonus helper", "4"),
    ]
    if family_rows != expected_families:
        raise StaticReTestFailure(
            "native XP family census no longer covers all 19 enemy types plus the XP helper with exact baselines"
        )
    _require_tokens(
        doc,
        (
            "raw_reward = 2 * (evaluated_recipe_xp + runtime_bonus_xp) * arena_player_count",
            "actor_reward = raw_reward * Gameplay.xp_scalar",
            "credited_xp = actor_reward * difficulty_level_factor(level)",
            "* (1 + actor_xp_bonus)",
            "recipe `+0xD4`",
            "enemy actor\n`+0x174`",
            "enemy `+0x178`",
            "`Gameplay+0x1AB8`",
            "Arena `+0x9024`",
        ),
        "native XP award pipeline lost a formula term or its actor/gameplay/Arena state location",
    )

    fixture = _load_json_object(FIXTURE, "native XP golden is unreadable")
    kills = fixture.get("xp_kills")
    if not isinstance(kills, list) or len(kills) != 3:
        raise StaticReTestFailure(
            "native XP golden no longer contains exactly Skeleton, Imp, and Wraith kills"
        )
    expected_kills = (
        ("Skeleton", 1001, 10.0, 4.25),
        ("Imp", 1004, 2.0, 0.85),
        ("Wraith", 1007, 4.0, 1.70),
    )
    for event, (family, type_id, baseline, credited) in zip(kills, expected_kills):
        if not isinstance(event, dict):
            raise StaticReTestFailure(f"native XP {family} event is not reviewable data")
        if event.get("family") != family or event.get("type_id") != type_id:
            raise StaticReTestFailure(
                f"native XP {family} kill lost its exact family/type identity"
            )
        _close(
            float(event.get("unscaled_family_reward", -1)),
            baseline,
            1e-9,
            f"native XP {family} family baseline",
        )
        _close(
            float(event.get("observed_arena_xp_scalar", -1)),
            0.425,
            2e-7,
            f"native XP {family} Arena multiplier",
        )
        _close(
            float(event.get("observed_xp_gain", -1)),
            credited,
            5e-7,
            f"native XP {family} credited amount",
        )
        before = event.get("before")
        presented = event.get("after_death_presenter_before_xp_award")
        after = event.get("after")
        if not all(isinstance(value, dict) for value in (before, presented, after)):
            raise StaticReTestFailure(
                f"native XP {family} event lost a before/presenter/after actor snapshot"
            )
        _close(
            float(presented["xp"]),
            float(before["xp"]),
            1e-9,
            f"native XP {family} synthetic presenter boundary",
        )
        _close(
            float(after["xp"]) - float(before["xp"]),
            credited,
            5e-7,
            f"native XP {family} native grant delta",
        )
    return "76 thresholds, all 19 enemy types, and three live family awards are exact"


def test_native_progression_offer_pool_selection_and_rng_are_pinned() -> str:
    fixture = _load_json_object(FIXTURE, "native offer golden is unreadable")
    rules = _unique_rows(
        fixture.get("offer_rule_rows"),
        identity="id",
        consequence="native offer eligibility matrix",
    )
    if sorted(rules) != list(range(82)):
        raise StaticReTestFailure(
            "native offer eligibility matrix no longer names each public skill ID 0..81"
        )
    if not (
        len(EXPECTED_MINIMUM_LEVELS)
        == len(EXPECTED_ROOTS)
        == len(EXPECTED_CATEGORIES)
        == 82
    ):
        raise StaticReTestFailure(
            "native offer contract itself lost one of its 82-field rule vectors"
        )
    for skill_id in range(82):
        row = rules[skill_id]
        scalar_fields = (
            ("minimum_player_level", EXPECTED_MINIMUM_LEVELS[skill_id]),
            ("root_id", EXPECTED_ROOTS[skill_id]),
            ("category", EXPECTED_CATEGORIES[skill_id]),
        )
        for field, expected in scalar_fields:
            if row.get(field) != expected:
                raise StaticReTestFailure(
                    f"native offer rule {skill_id} changed its exact {field} from {expected}"
                )
        actual_all = tuple(
            (int(pair["skill_id"]), int(pair["minimum_rank"]))
            for pair in row.get("requires_all", [])
        )
        actual_any = tuple(int(value) for value in row.get("requires_any", []))
        actual_forbidden = tuple(
            (int(pair["skill_id"]), int(pair["minimum_rank"]))
            for pair in row.get("forbidden_if_at_least", [])
        )
        if actual_all != EXPECTED_REQUIRES_ALL.get(skill_id, ()):
            raise StaticReTestFailure(
                f"native offer rule {skill_id} changed its all-prerequisite set"
            )
        if actual_any != EXPECTED_REQUIRES_ANY.get(skill_id, ()):
            raise StaticReTestFailure(
                f"native offer rule {skill_id} changed its any-prerequisite set"
            )
        if actual_forbidden != EXPECTED_FORBIDDEN.get(skill_id, ()):
            raise StaticReTestFailure(
                f"native offer rule {skill_id} changed its mutual-exclusion set"
            )

    level_ups = fixture.get("level_ups")
    if not isinstance(level_ups, list) or len(level_ups) != 3:
        raise StaticReTestFailure(
            "native offer golden no longer contains the three required level-up witnesses"
        )
    expected_offers = (
        (2, 100, (48, 49, 57), 48),
        (3, 170, (65, 49, 9), 65),
        (4, 280, (49, 56, 9), 49),
    )
    actor_addresses: set[int] = set()
    progression_addresses: set[int] = set()
    for capture, (level, xp, option_ids, selected_id) in zip(
        level_ups, expected_offers
    ):
        if not isinstance(capture, dict):
            raise StaticReTestFailure(
                f"native level {level} offer witness is not a reviewable object"
            )
        offer = capture.get("offer")
        rng = capture.get("offer_rng")
        selection = capture.get("selection")
        before = capture.get("before")
        after = capture.get("after")
        if not all(
            isinstance(value, dict)
            for value in (offer, rng, selection, before, after)
        ):
            raise StaticReTestFailure(
                f"native level {level} offer lost its offer/RNG/selection/state envelope"
            )
        options = offer.get("options")
        if not isinstance(options, list) or len(options) != len(option_ids):
            raise StaticReTestFailure(
                f"native level {level} offer no longer exposes its full ordered pool"
            )
        if tuple(option.get("id") for option in options) != option_ids:
            raise StaticReTestFailure(
                f"native level {level} ordered offer pool changed from {option_ids}"
            )
        if (
            capture.get("requested_level") != level
            or capture.get("requested_experience") != xp
            or offer.get("level") != level
            or offer.get("experience") != xp
            or before.get("level") != level - 1
            or after.get("level") != level
        ):
            raise StaticReTestFailure(
                f"native level {level} offer no longer brackets its exact level/XP transition"
            )
        if (
            selection.get("option_id") != selected_id
            or selection.get("option_index_one_based") != 1
            or selection.get("apply_count") != 1
        ):
            raise StaticReTestFailure(
                f"native level {level} selected choice changed from first option {selected_id}"
            )
        if rng != {
            "builder_mutates_seed_field": False,
            "builder_reseeds_each_call": True,
            "seed": 79225,
            "seed_source": "progression+0x834",
            "stream": "actor-private level-up offer RNG",
        }:
            raise StaticReTestFailure(
                f"native level {level} offer lost its actor-private RNG identity and seed rule"
            )
        actor_addresses.add(int(before["actor_address"]))
        progression_addresses.add(int(before["progression_address"]))
    if len(actor_addresses) != 1 or len(progression_addresses) != 1:
        raise StaticReTestFailure(
            "native offer golden silently mixed more than one actor/progression into one seed sequence"
        )

    doc = read_text(DOC)
    _require_tokens(
        doc,
        (
            "active_gameplay_rng.Integer(1_000_000)",
            "fresh **actor-private\n   level-up offer RNG**",
            "The builder does not write `+0x834`",
            "Spell Welding build-pair choice at",
            "`0x0067DE7A..0x0067DE82`",
            "IDs `72..79` have their corresponding global content-unlock bit",
            "Spell Welding 52 additionally requires more than one learned elemental",
            "The ordinary picker has no unconditional reroll or skip",
            "selector` span). Reopening with unchanged book/level/private seed",
            "Construction, every skill acquisition, and the explicit charm\nreroll action do",
            "20% `RandomInt(5)==1` Insight chance",
        ),
        "native offer documentation lost a named RNG, unlock, weld, or resolution rule",
    )
    _require_tokens(
        doc,
        (
            "`mana_cost(i, effective(i)+1) <= actor.maxMP`",
            "`mana_cost(i, actor.level+1) <= actor.maxMP`",
            "append each discipline-root row **twice** instead",
            "`min(desired, count(+0x864))` IDs in the actor list at `+0x860`",
            "result `1` takes the related-skill branch",
            "`keep_started = (Integer(2)==1)`",
            "overwrite it with `Integer(5)!=2`",
            "overwrite it with `Integer(10)!=2`",
            "Draw candidate pointers uniformly **with replacement**",
            "native uniqueness byte `+0x04 = 1`",
            "displayed offer cannot contain the same skill ID twice",
            "A category-4 candidate is always retried",
            "category-1 row and fewer than 50 such collisions",
            "On attempt 100, append every ID",
            "except 52 that passes the first global-disable",
            "On attempt 200, stop and return an undersized pool",
            "active gameplay RNG** at",
            "This second shuffle is\n   also not Fisher-Yates.",
        ),
        "native offer selection lost an exact affordability, weighting, pruning, retry, or shuffle rule",
    )
    phase_order_pattern = re.compile(
        r"(?ms)^#### Exact candidate assembly and draw\n"
        r".*?^1\. \*\*Seed and desired count\.\*\*"
        r".*?^2\. \*\*Build the root-priority pool\.\*\*"
        r".*?^3\. \*\*Build and pre-shuffle the general pool\.\*\*"
        r".*?^4\. \*\*Copy forced-prefix entries\.\*\*"
        r".*?^5\. \*\*Inject one root-priority entry when space remains\.\*\*"
        r".*?^6\. \*\*Optionally inject Spell Welding\.\*\*"
        r".*?^7\. \*\*Apply the learned-skill pruning draw\.\*\*"
        r".*?^8\. \*\*Merge and fill\.\*\*"
        r".*?^9\. \*\*Final display shuffle\.\*\*"
    )
    if phase_order_pattern.search(doc) is None:
        raise StaticReTestFailure(
            "native offer phase order changed, so private/shared RNG consumption and display order are no longer pinned"
        )
    return "all 82 eligibility rows and three captured native offers are exact"


def test_native_progression_acquisition_seed_writers_are_complete() -> str:
    doc = read_text(DOC)
    _require_tokens(
        doc,
        (
            "### 2026-08-27 complete `+0x834` writer and acquisition-xref closure",
            "`0x0065966A` in `0x006594E0`",
            "`0x00660359` in `Skills_Wizard::Acquire 0x00660320`",
            "`0x006714FC` in `LevelupScreen::Activate 0x00671470`",
            "19 sites in seven functions",
            "Insight consumes a second word",
            "selection draws first; acquisition reseed follows",
            "twelve non-disabled acquisition calls",
            "thirteen `Integer(1_000_000)` words",
            "SAVE SKILL/defer",
        ),
        "native acquisition seed writer and caller closure drifted",
    )
    return "all offer-seed writers and acquisition caller draw counts are pinned"


def test_native_creativity_insight_rng_presentation_and_apply_are_pinned() -> str:
    _require_tokens(
        read_text(SKILL_PICKER_DOC),
        (
            "### 2026-08-28 active-RNG and feedback correction",
            "`0x0066FB6C` loads the RNG object through global slot `0x00818B08`",
            "`alpha = 0.5 + 0.5*sin(2*screenAgeTicks*pi/180)`",
            "`Insight Bonus: Skill +2`",
            "active-card index `+0x5F8 == -1`",
            "the separate apply function `0x00671470`",
        ),
        "native Creativity Insight owner, presentation, or apply closure drifted",
    )
    _require_tokens(
        read_text(DOC),
        (
            "must not use a separately initialized secondary-effect stream",
            "`0x0067EA49..0x0067EABD` submits the marked card/icon again",
            "`(0.85,0.73,0.44)`",
            "card-detail builder `0x00671174..0x0067128A`",
            "Actual\nactivation `0x00671470`",
        ),
        "native progression report lost the complete Creativity Insight branch",
    )
    return "Creativity Insight uses active gameplay RNG and one visible double-rank card"


def test_native_secondary_cooldown_and_action_gate_is_pinned() -> str:
    doc = read_text(DOC)
    _require_tokens(
        doc,
        (
            "## 2026-08-20 shared secondary cooldown and action gate closure",
            "`PlayerWizard +0x1EC` has its no-interrupt latch set",
            "At neutral Faster Caster this occupies exactly 51 fixed updates",
            "`0x0078489C = 150.0` fixed ticks",
            "clears every active row current strictly below the common capacity",
            "`max(progression +0xD0, progression +0xD4 + 4*row.category)`",
            "values `75..99` bypass that copy",
            "Phasing displays the 150-tick common fan",
            "Teleport displays its\nlonger 6,000-tick row fan",
        ),
        "native secondary cooldown/action contract lost a gate, timer, or recharge rule",
    )
    return "secondary no-interrupt, global/row cooldown, Focus, and Faster Caster are pinned"


def test_native_spell_welding_picker_art_contract_is_pinned() -> str:
    doc = read_text(SPELL_WELDING_DOC)
    _require_tokens(
        doc,
        (
            "triangle\n`P0/P1/P2` uses the first component color",
            "triangle `P1/P2/P3` uses the\nsecond",
            "deterministic x87 float-to-integer rounding before ARGB packing",
            "No\nrandom number is consumed by this overlay path.",
            "normal Welding offer uses Skills frame record 14",
            "actual synthetic icon records are `108..117`, not `81..90`",
            "Skills record 13 in white at scale `1.15`",
            "draws the synthetic icon twice (shadow then main)",
            "`Welded Lighting + Fireball`",
            "There are no six\ncomponent-name/learned-level rows",
            "`Burning Bolt`",
            "`Crawling Shock`",
            "exact `ARCANE ` (including its trailing space)",
            "medium name, maximum width 140",
            "body-font lowercase `primary cast`",
            "centered, white, unshadowed quick-description",
            "vertically centered around local Y 230",
            "source case preserved",
            "black shadows at `(+1,+1)`",
            "conditional eighth call draws `casting` or\n`concentrate`",
            "Website offer\nparity therefore suppresses this lane",
        ),
        "native Spell Welding picker lost a recovered mesh, frame, icon, title, or evidence boundary",
    )
    rows = re.findall(
        r"(?m)^\| (10\d\d) \| (1\d\d) \| `([^`]+)` \| `([^`]+)` \| ([\d, ]+) \|$",
        doc,
    )
    expected = [
        (str(1000 + index), str(108 + index))
        for index in range(10)
    ]
    if [(build, record) for build, record, _, _, _ in rows] != expected:
        raise StaticReTestFailure(
            "native Spell Welding picker no longer maps all ten builds to records 108..117"
        )
    recipes = [
        tuple(int(value) for value in recipe.split(", "))
        for _, _, _, _, recipe in rows
    ]
    if recipes != [
        (8, 16, 10, 18, 9, 17),
        (8, 32, 10, 34, 9, 33),
        (8, 24, 10, 25, 9, 26),
        (16, 24, 18, 25, 17, 26),
        (32, 24, 34, 25, 33, 26),
        (16, 32, 18, 34, 17, 33),
        (8, 40, 10, 43, 9, 42),
        (16, 40, 18, 43, 17, 42),
        (32, 40, 34, 43, 33, 42),
        (24, 40, 25, 43, 26, 42),
    ]:
        raise StaticReTestFailure(
            "native Spell Welding stat rebuild lost one of its six-ID recipes"
        )
    synthetic_names = [name for _, _, name, _, _ in rows]
    if synthetic_names != [
        "Burning Bolt",
        "Frost Missile",
        "Ball Lightning",
        "Flame Lash",
        "Blizzard Beam",
        "Steam Jet",
        "Ethereal Boulder",
        "Meteor Swarm",
        "Hailstones",
        "Crawling Shock",
    ]:
        raise StaticReTestFailure(
            "native Spell Welding picker lost one of its synthetic names"
        )
    pair_descriptions = [description for _, _, _, description, _ in rows]
    if pair_descriptions != [
        "Welded Magic Missile + Fireball",
        "Welded Magic Missile + Frost Jet",
        "Welded Magic Missile + Lightning",
        "Welded Lighting + Fireball",
        "Welded Lightning + Frost Jet",
        "Welded Fireball + Frost Jet",
        "Welded Magic Missile + Boulder",
        "Welded Fireball + Boulder",
        "Welded Frost Jet + Boulder",
        "Welded Lightning + Boulder",
    ]:
        raise StaticReTestFailure(
            "native Spell Welding picker lost one of its exact white pair descriptions"
        )
    return "all ten weld cards pin split art, synthetic names, white pair text, and records 108..117"


def test_native_skill_picker_text_and_palette_abi_is_pinned() -> str:
    doc = read_text(NATIVE_SKILLS_DOC)
    for token in (
        "Level-up card art and text ABI",
        "`#FFE5FF`, `#FFCBCB`, `#E5FFFF`, `#CBCBFF`, `#CBFFCB`, `#FFE5CB`,",
        "`#CBD8FF`, and `#E5E5E5`",
        "medium name at Y `452.5`, maximum width 140",
        "body-font lowercase `primary cast`",
        "`secondary cast`",
        "vertically centered around Y `532.5`",
        "opaque black at `(+1,+1)`",
        "Medium height is 16 with a 17-pixel line step",
        "` ETHER`, ` FIRE`, ` AIR`, ` WATER`, ` EARTH`, `BODY `, `MIND `, and",
        "`ARCANE `",
        "preserves source case",
        "`RING OF FIRE 2` uses the uppercase medium advance 135",
        "lowercase advances 82/116/69",
        "Current offer-surface parity must\nsuppress this lane",
    ):
        if token not in doc:
            raise StaticReTestFailure(
                f"native skill picker text/palette ABI lost witness {token!r}"
            )
    return "skill picker palette, case, font lanes, spacing, and anchors are pinned"


def test_native_staff_admission_distinguishes_movement_and_current_contact() -> str:
    doc = " ".join(read_text(NATIVE_SKILLS_DOC).split())
    for token in (
        "admission owner has **two** ordered contact sources",
        "`PlayerWizard +0x13C`",
        "count `+0x144` and backing",
        "array `+0x150`",
        "strict float `0.01` threshold",
        "`0x0054AD54..0x0054AD7B`",
        "jumps to `0x0054B662`",
        "A stationary wizard therefore cannot start or repeat a Staff action",
        "Region's transient collision",
        "capture byte `+0x47C`",
        "result count `+0x480`",
        "`radiusA + radiusB + 0.1`",
        "there is no facing test on this walk-into-hostile branch",
        "the actor-list fallback for that tick",
        "strict absolute heading delta below 50 degrees",
        "equipped item type `0x1B5C`",
        "does not recompute center distance",
        "`PlayerActor_MoveStep` call at `0x0054B050`",
        "Both `CMP [ESI+0xE4],0` branches occur after",
        "Movement input, velocity, world/dynamic collision, gait, and footsteps continue",
        "Competing casts and a second Staff action remain blocked",
    ):
        if token not in doc:
            raise StaticReTestFailure(
                f"native Staff contact ownership lost witness {token!r}"
            )
    return (
        "Staff admission is movement-gated before both contact sources while live actions "
        "retain locomotion"
    )


def test_native_progression_five_live_effect_formulas_are_pinned() -> str:
    fixture = _load_json_object(FIXTURE, "native skill-effect golden is unreadable")
    effects = _unique_rows(
        fixture.get("skill_effects"),
        identity="skill_id",
        consequence="native representative skill effects",
    )
    expected_ids = {23, 56, 57, 64, 79}
    if set(effects) != expected_ids:
        raise StaticReTestFailure(
            "native effect golden no longer proves exactly Firewalker, Mana Up, Channel Mana, Health Up, and Regenerate"
        )
    expected_formulas = {
        23: "actor_hoarded_mp(+0x740) += scalar mHoard = 50 MP; unlike rank-table hoards, Mana Up does not scale Firewalker's reserve",
        56: "max_mp = base_mp + mValue[1] = base_mp + 100",
        57: "mana_recovery = base_recovery * (1 + mValue[1] / 100) = base_recovery * 1.25",
        64: "max_hp = base_hp + mValue[1] = base_hp + 50",
        79: "hp_delta = native_updates * ((1.5 + health_regeneration / 10) / game_timing_scale), capped at max_hp",
    }
    expected_names = {
        23: "Firewalker",
        56: "Mana Up",
        57: "Channel Mana",
        64: "Health Up",
        79: "Regenerate",
    }
    for skill_id in (56, 57, 64, 79, 23):
        effect = effects[skill_id]
        before = effect.get("before")
        after = effect.get("after")
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise StaticReTestFailure(
                f"native {expected_names[skill_id]} effect lost its before/after actor witness"
            )
        if (
            effect.get("name") != expected_names[skill_id]
            or effect.get("rank") != 1
            or effect.get("formula") != expected_formulas[skill_id]
        ):
            raise StaticReTestFailure(
                f"native {expected_names[skill_id]} rank-1 formula changed"
            )
        if int(after["tick"]) <= int(before["tick"]):
            raise StaticReTestFailure(
                f"native {expected_names[skill_id]} effect is no longer tick-ordered"
            )
        for phase_name, snapshot in (("before", before), ("after", after)):
            if snapshot.get("progression_address") != snapshot.get("actor_plus_0x200"):
                raise StaticReTestFailure(
                    f"native {expected_names[skill_id]} {phase_name} snapshot no longer resolves actor+0x200 to that actor's progression"
                )
            if type(snapshot.get("actor_plus_0x300")) is not int or snapshot["actor_plus_0x300"] <= 0:
                raise StaticReTestFailure(
                    f"native {expected_names[skill_id]} {phase_name} snapshot lost its actor+0x300 progression handle"
                )

    mana_up = effects[56]
    _close(float(mana_up["before"]["max_mp"]), 100.0, 1e-6, "Mana Up input max MP")
    _close(float(mana_up["after"]["max_mp"]), 200.0, 1e-6, "Mana Up output max MP")
    channel = effects[57]
    _close(float(channel["before"]["mana_recovery"]), 10.0, 1e-6, "Channel Mana input recovery")
    _close(float(channel["after"]["mana_recovery"]), 12.5, 1e-6, "Channel Mana output recovery")
    health = effects[64]
    _close(float(health["before"]["max_hp"]), 50.0, 1e-6, "Health Up input max HP")
    _close(float(health["after"]["max_hp"]), 100.0, 1e-6, "Health Up output max HP")

    regenerate = effects[79]
    if regenerate.get("observed_tick_delta") != 60:
        raise StaticReTestFailure(
            "Regenerate per-tick golden no longer spans exactly 60 native updates"
        )
    expected_per_tick = (
        1.5 + float(regenerate["before"]["health_regeneration"]) / 10.0
    ) / float(regenerate["before"]["game_timing_scale"])
    _close(expected_per_tick, 0.016, 1e-12, "Regenerate formula-derived HP per tick")
    _close(
        float(regenerate.get("expected_hp_per_tick", -1)),
        expected_per_tick,
        1e-12,
        "Regenerate recorded expected HP per tick",
    )
    _close(
        float(regenerate.get("observed_hp_per_tick", -1)),
        expected_per_tick,
        2e-6,
        "Regenerate observed HP per tick",
    )
    _close(
        float(regenerate["after"]["hp"]) - float(regenerate["before"]["hp"]),
        float(regenerate.get("observed_hp_delta", -1)),
        1e-9,
        "Regenerate before/after HP delta",
    )

    firewalker = effects[23]
    _close(float(firewalker["before"]["max_mp"]), 200.0, 1e-6, "Firewalker Mana Up control")
    _close(float(firewalker["after"]["max_mp"]), 200.0, 1e-6, "Firewalker unchanged max MP")
    _close(float(firewalker["before"]["hoarded_mp"]), 0.0, 1e-6, "Firewalker input hoard")
    _close(float(firewalker["after"]["hoarded_mp"]), 50.0, 1e-6, "Firewalker absolute 50-MP hoard")
    if firewalker["after"].get("toggles", {}).get("firewalker") is not True:
        raise StaticReTestFailure(
            "Firewalker 50-MP hoard no longer follows an active actor-local toggle"
        )
    return "five rank-1 formulas replay from tick-stamped native actor state"


def test_native_progression_actor_layout_and_all_skill_rows_are_pinned() -> str:
    fixture = _load_json_object(FIXTURE, "native actor-layout golden is unreadable")
    expected_layout = {
        "actor_direct_progression": "actor+0x200",
        "actor_progression_handle": "actor+0x300",
        "effective_rank": "row+0x22",
        "hoarded_mp": "progression+0x740",
        "hp_current_max": "progression+0x70/+0x74",
        "level": "progression+0x30",
        "mp_current_max": "progression+0x7C/+0x80",
        "next_threshold": "progression+0x3C",
        "offer_seed": "progression+0x834",
        "permanent_rank": "row+0x20",
        "previous_threshold": "progression+0x38",
        "skill_row_stride": "0x70",
        "skill_table_count": "progression+0x24",
        "skill_table_pointer": "progression+0x20",
        "toggles": "progression+0x8DC/+0x8DD/+0x8DE",
        "xp": "progression+0x34",
    }
    if fixture.get("actor_layout") != expected_layout:
        raise StaticReTestFailure(
            "native per-actor progression locations changed or became incomplete"
        )
    isolation = fixture.get("per_actor_isolation")
    if not isinstance(isolation, dict) or set(isolation) != {
        "effect_bot_final",
        "local_player_after_progression_bot_mutation",
        "local_player_before_progression_bot_mutation",
        "progression_bot_after_effect_mutation",
        "progression_bot_before_effect_mutation",
    }:
        raise StaticReTestFailure(
            "native per-actor isolation proof lost one of its five named snapshots"
        )
    local_before = isolation["local_player_before_progression_bot_mutation"]
    local_after = isolation["local_player_after_progression_bot_mutation"]
    bot_before = isolation["progression_bot_before_effect_mutation"]
    bot_after = isolation["progression_bot_after_effect_mutation"]
    if not all(
        isinstance(value, dict)
        for value in (local_before, local_after, bot_before, bot_after)
    ):
        raise StaticReTestFailure(
            "native per-actor isolation snapshots are no longer reviewable objects"
        )
    if (
        local_before["actor_address"] == bot_before["actor_address"]
        or local_before["progression_address"] == bot_before["progression_address"]
        or local_before["skill_table_address"] == bot_before["skill_table_address"]
        or local_before["offer_seed"] == bot_before["offer_seed"]
    ):
        raise StaticReTestFailure(
            "native player and bot no longer prove distinct actor, progression, book, and seed identity"
        )
    local_unchanged_fields = (
        "actor_address",
        "progression_address",
        "skill_table_address",
        "base_hp",
        "base_mp",
        "max_hp",
        "max_mp",
        "mana_recovery",
        "hoarded_mp",
        "toggles",
        "skills",
    )
    for field in local_unchanged_fields:
        if local_before.get(field) != local_after.get(field):
            raise StaticReTestFailure(
                f"bot skill mutation leaked into local-player actor field {field}"
            )
    expected_bot_ranks = {
        "23": {"effective_rank": 1, "permanent_rank": 1},
        "56": {"effective_rank": 1, "permanent_rank": 1},
        "57": {"effective_rank": 1, "permanent_rank": 1},
        "64": {"effective_rank": 1, "permanent_rank": 1},
        "79": {"effective_rank": 0, "permanent_rank": 0},
    }
    if bot_after.get("skills") != expected_bot_ranks:
        raise StaticReTestFailure(
            "native bot book no longer contains only its four selected representative ranks"
        )

    doc = read_text(DOC)
    row_matches = re.findall(
        r"(?m)^\| (?P<id>\d+) \| \*\*(?P<name>[^*]+)\.\*\* "
        r"(?P<effect>.+) \| (?P<confidence>HIGH-LIVE|HIGH|MEDIUM|LOW) \|$",
        doc,
    )
    if len(row_matches) != 82:
        raise StaticReTestFailure(
            "native per-skill document no longer contains 82 structurally explicit effect rows"
        )
    documented: dict[int, tuple[str, str, str]] = {}
    for raw_id, name, effect, confidence in row_matches:
        skill_id = int(raw_id)
        if skill_id in documented:
            raise StaticReTestFailure(
                f"native per-skill document contains ambiguous duplicate effect row {skill_id}"
            )
        if not effect.strip():
            raise StaticReTestFailure(
                f"native skill {skill_id} has no runtime-effect claim to implement"
            )
        documented[skill_id] = (name, effect, confidence)
    if sorted(documented) != list(range(82)):
        raise StaticReTestFailure(
            "native per-skill document no longer covers every public ID 0..81 exactly once"
        )

    catalog = _load_json_object(SKILL_CATALOG, "native skill catalog is unreadable")
    catalog_rows = _unique_rows(
        catalog.get("skills"),
        identity="id",
        consequence="native skill catalog identity",
    )
    if sorted(catalog_rows) != list(range(82)):
        raise StaticReTestFailure(
            "native skill catalog no longer supplies one name for every documented effect"
        )
    medium_ids = {29, 33, 53}
    live_ids = {23, 56, 57, 64, 79}
    for skill_id in range(82):
        name, effect, confidence = documented[skill_id]
        if name != catalog_rows[skill_id].get("name"):
            raise StaticReTestFailure(
                f"native skill {skill_id} effect row no longer names its catalog identity"
            )
        config = catalog_rows[skill_id].get("config")
        indexed_properties = set(re.findall(r"\b(m[A-Za-z0-9_]+)\[r\]", effect))
        if indexed_properties and not isinstance(config, dict):
            raise StaticReTestFailure(
                f"native skill {skill_id} formula names rank properties but its catalog config is unavailable"
            )
        missing_properties = sorted(indexed_properties - set(config or {}))
        if missing_properties:
            raise StaticReTestFailure(
                f"native skill {skill_id} formula references catalog properties that do not exist: {missing_properties}"
            )
        expected_confidence = (
            "LOW"
            if skill_id == 81
            else "MEDIUM"
            if skill_id in medium_ids
            else "HIGH-LIVE"
            if skill_id in live_ids
            else "HIGH"
        )
        if confidence != expected_confidence:
            raise StaticReTestFailure(
                f"native skill {skill_id} confidence changed from {expected_confidence} without new evidence"
            )
    closure_claims = {
        16: (
            "row-16 `mDamage[r]` minus row-18 `mDamage[r]`",
            "private random seed",
            "impact presentation precede",
        ),
        17: (
            "`360/N`",
            "pre-ticked ten times",
            "Contact consumes an Ember without running its retirement mode",
        ),
        18: (
            "`visual_scale=(mRadius[r]-10)*0.18+1`",
            "dimension `visual_scale*110`",
            "`mDamage[r]*0.5`",
        ),
        19: (
            "Ember::Tick 0x0060D7E0",
            "GoodImp::Tick 0x0052C1A0",
            "`mDamage[r]*0.5`",
            "`300` ticks",
            "Contact-consumed Embers do not convert",
        ),
        20: (
            "life `1`",
            "footprint dimension `110`",
            "Contact-consumed Embers do not immolate",
        ),
        22: (
            "exactly `200` ticks",
            "`mDamage[r]/200`",
            "maximum per-tick damage",
        ),
        26: (
            "wizard `+0x288`",
            "`+0x14=25` native ticks",
            "minimum movement factor",
        ),
        28: (
            "frequency_factor = 1 + mSpeed[r]/100",
            "trunc(numerator / frequency_factor)",
            "uniform integer `numerator` in `[30,120]`",
            "strike frequency, not cloud translation",
        ),
    }
    for skill_id, claims in closure_claims.items():
        effect = documented[skill_id][1]
        missing_claims = [claim for claim in claims if claim not in effect]
        if missing_claims:
            raise StaticReTestFailure(
                f"native skill {skill_id} lost fresh static closure claims: {missing_claims}"
            )
    return "all 82 catalog rows and the player/bot-private ABI are explicit"


def test_native_progression_golden_and_recorder_provenance_are_pinned() -> str:
    fixture = _load_json_object(FIXTURE, "native progression golden is unreadable")
    header = fixture.get("header")
    expected_header_keys = {
        "audio_disabled",
        "build_loader_sha256",
        "capture",
        "capture_method",
        "captured_utc",
        "cleanup",
        "fixture_is_machine_recorded",
        "format",
        "game_binary_path",
        "game_binary_sha256",
        "gameplay_rng_setup",
        "headless",
        "instance",
        "launch_executable_path",
        "launch_process_id",
        "loader_sha256",
        "offer_rng_seed_write",
        "ports",
        "provenance_derivation",
        "source_commit_sha",
        "source_tree_sha",
        "worktree_dirty_at_capture_start",
    }
    if not isinstance(header, dict) or set(header) != expected_header_keys:
        raise StaticReTestFailure(
            "native progression golden lost its complete standard provenance header"
        )
    if (
        header.get("format") != "solomon-dark-native-golden-v1"
        or header.get("capture") != "progression_xp_offers_and_skill_effects"
        or header.get("fixture_is_machine_recorded") is not True
        or header.get("instance") != "prog-golden"
        or header.get("ports") != [52381, 52382]
        or header.get("audio_disabled") is not True
        or header.get("headless") is not True
    ):
        raise StaticReTestFailure(
            "native progression golden escaped its machine-recorded instance, port, headless, or audio-off boundary"
        )
    if re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
        str(header.get("captured_utc", "")),
    ) is None:
        raise StaticReTestFailure(
            "native progression golden no longer records an unambiguous UTC capture time"
        )
    expected_source = {
        "source_commit_sha": "8deaa9400cc1df33748976aa0464e8016c11a46b",
        "source_tree_sha": "a3bc978196605af4ec9b5f6a3be9c0660cd1ae40",
    }
    for field, expected in expected_source.items():
        if header.get(field) != expected:
            raise StaticReTestFailure(
                f"native progression golden changed its exact recorded {field}"
            )
    expected_external_hashes = {
        "game_binary_sha256": "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3",
        "loader_sha256": "642879f09136456e79e3a045fe2999598a109eed246aee5a6bee5ae66c46c5c1",
        "build_loader_sha256": "642879f09136456e79e3a045fe2999598a109eed246aee5a6bee5ae66c46c5c1",
    }
    for field, expected in expected_external_hashes.items():
        if header.get(field) != expected:
            raise StaticReTestFailure(
                f"native progression golden no longer identifies its captured {field}"
            )
    if header.get("provenance_derivation") != {
        "cli_overrides_permitted": False,
        "hashes": "recorder-owned Windows Get-FileHash queries",
        "source": "recorder-owned Windows git.exe queries",
    }:
        raise StaticReTestFailure(
            "native progression golden provenance is no longer recorder-derived and override-free"
        )
    cleanup = header.get("cleanup")
    if not isinstance(cleanup, list) or len(cleanup) != 1:
        raise StaticReTestFailure(
            "native progression golden no longer has exactly one owned-process cleanup receipt"
        )
    receipt = cleanup[0]
    if not isinstance(receipt, dict) or (
        receipt.get("processId") != header.get("launch_process_id")
        or receipt.get("actualPath") != header.get("launch_executable_path")
        or receipt.get("expectedPath") != header.get("launch_executable_path")
        or receipt.get("pathMatched") is not True
        or receipt.get("stopped") is not True
    ):
        raise StaticReTestFailure(
            "native progression golden cleanup no longer proves exact-path owned-PID termination"
        )
    capture_method = str(header.get("capture_method", ""))
    _require_tokens(
        capture_method,
        (
            "stock wave spawner and native death presenter",
            "retail progression XP grant seam",
            "native bot level sync/offer/apply seam",
            "actor-private offer seed at progression+0x834",
            "retail ActorProgressionRefresh",
            "tick-stamped native progression reads",
        ),
        "native progression golden no longer discloses its exact live capture boundary",
    )

    recorder = read_text(RECORDER)
    try:
        tree = ast.parse(recorder)
    except SyntaxError as error:
        raise StaticReTestFailure(
            f"native progression recorder is not runnable Python: {error}"
        ) from error
    main = _top_level_function(
        tree, "main", "native progression recorder entrypoint"
    )
    argument_calls = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
    ]
    if len(argument_calls) != 2:
        raise StaticReTestFailure(
            "native progression recorder no longer exposes exactly output and raw-evidence controls"
        )
    argument_names: list[str] = []
    for call in argument_calls:
        if (
            not call.args
            or not isinstance(call.args[0], ast.Constant)
            or not isinstance(call.args[0].value, str)
        ):
            raise StaticReTestFailure(
                "native progression recorder has an ambiguous non-literal CLI option"
            )
        argument_names.append(call.args[0].value)
    if argument_names != ["--output", "--raw-evidence"]:
        raise StaticReTestFailure(
            "native progression recorder accepted a provenance override or lost a recording sink"
        )
    forbidden_flags = (
        "--source-commit",
        "--source-tree",
        "--game-binary-sha256",
        "--loader-sha256",
        "--process-id",
    )
    for flag in forbidden_flags:
        if flag in recorder:
            raise StaticReTestFailure(
                f"native progression recorder accepts forbidden hand-authored provenance through {flag}"
            )

    source_revision = _top_level_function(
        tree, "source_revision", "native progression source provenance"
    )
    _require_tokens(
        _source_segment(
            recorder, source_revision, "native progression source provenance"
        ),
        (
            '"commit_sha": _windows_git("rev-parse", "HEAD")',
            '"tree_sha": _windows_git("rev-parse", "HEAD^{tree}")',
            '"worktree_dirty": bool(_windows_git("status", "--porcelain"))',
        ),
        "native progression recorder stopped deriving source provenance itself",
    )
    build_document = _top_level_function(
        tree, "build_document", "native progression provenance builder"
    )
    _require_tokens(
        _source_segment(
            recorder, build_document, "native progression provenance builder"
        ),
        (
            '"game_binary_sha256": windows_sha256(GAME_BINARY)',
            '"loader_sha256": windows_sha256(STAGED_LOADER)',
            '"build_loader_sha256": windows_sha256(LOADER)',
            '"cli_overrides_permitted": False',
        ),
        "native progression recorder stopped deriving binary provenance itself",
    )
    powershell_probe = _top_level_function(
        tree, "_powershell", "native progression PowerShell probe"
    )
    _require_tokens(
        _source_segment(
            recorder, powershell_probe, "native progression PowerShell probe"
        ),
        (
            "subprocess.run(",
            '"$PSVersionTable.PSVersion.Major"',
            "completed.returncode == 0 and completed.stdout.strip().isdigit()",
            '"powershell.exe resolved but is not runnable"',
        ),
        "native progression recorder checks existence but no longer proves PowerShell runnability",
    )
    wait_until = _top_level_function(
        tree, "_wait_until", "native progression readiness probe"
    )
    while_nodes = [node for node in ast.walk(wait_until) if isinstance(node, ast.While)]
    if len(while_nodes) != 1 or not while_nodes[0].body:
        raise StaticReTestFailure(
            "native progression readiness probe lost its one bounded nonempty loop"
        )
    first_wait_statement = while_nodes[0].body[0]
    if not (
        isinstance(first_wait_statement, ast.Expr)
        and isinstance(first_wait_statement.value, ast.Call)
        and isinstance(first_wait_statement.value.func, ast.Attribute)
        and isinstance(first_wait_statement.value.func.value, ast.Name)
        and first_wait_statement.value.func.value.id == "session"
        and first_wait_statement.value.func.attr == "assert_wait_target_runnable"
    ):
        raise StaticReTestFailure(
            "native progression readiness probe no longer distinguishes broken ownership before retrying busy state"
        )
    wait_source = _source_segment(
        recorder, wait_until, "native progression readiness probe"
    )
    if "remained busy through timeout" not in wait_source:
        raise StaticReTestFailure(
            "native progression readiness probe no longer reports busy timeout separately from broken ownership"
        )

    execution_witnesses = (
        "    source = source_revision()",
        "        launch = session.launch()",
        "        session.wait_for_pipe()",
        '        session.wait_for_scene("hub")',
        "        cleanup = session.close()",
        "        document = build_document(",
        '    serialized = json.dumps(document, indent=2, sort_keys=True) + "\\n"',
        '    args.output.write_text(serialized, encoding="utf-8")',
        '        args.raw_evidence.write_text(serialized, encoding="utf-8")',
    )
    execution_positions = [recorder.find(witness) for witness in execution_witnesses]
    if any(position < 0 for position in execution_positions) or execution_positions != sorted(
        execution_positions
    ):
        raise StaticReTestFailure(
            "native progression recorder no longer derives source before launch, proves the live pipe, cleans before publication, or writes identical fixture/evidence copies"
        )
    cleanup_pattern = re.compile(
        r"(?m)^    finally:\n"
        r"^        if session\.process_ids:\n"
        r"^            session\.close\(\)$"
    )
    if cleanup_pattern.search(recorder) is None:
        raise StaticReTestFailure(
            "native progression recorder exact-PID cleanup is no longer nested in an unconditional finally block"
        )
    twin_write_pattern = re.compile(
        r"(?m)^    args\.output\.write_text\(serialized, encoding=\"utf-8\"\)\n"
        r"^    if args\.raw_evidence is not None:\n"
        r"^        args\.raw_evidence\.parent\.mkdir\(parents=True, exist_ok=True\)\n"
        r"^        args\.raw_evidence\.write_text\(serialized, encoding=\"utf-8\"\)$"
    )
    if twin_write_pattern.search(recorder) is None:
        raise StaticReTestFailure(
            "native progression fixture and raw-evidence copy no longer serialize the same recording bytes"
        )
    return "live header and self-derived, runnable, exact-PID recorder lifecycle are pinned"
