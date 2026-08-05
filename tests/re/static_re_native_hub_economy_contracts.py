"""Static contracts for the G8 native hub, economy, and Solomon Dig reconstruction."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    assert_recorded_hash_matches_file,
)


DOC_PATH = ROOT / "docs/reverse-engineering/native-hub-and-economy.md"
GOLDEN_PATH = ROOT / "tests/fixtures/webgame/hub-economy-goldens.json"
RECORDER_PATH = ROOT / "tests/re/record_live_hub_economy_goldens.py"
HAGATHA_CATALOG_PATH = (
    ROOT / "docs/reverse-engineering/native-hagatha-perk-catalog.json"
)
INTENT_SCHEMA_PATH = ROOT / "webgame-contracts/intent-schema.json"
RNG_DOC_PATH = ROOT / "docs/reverse-engineering/native-movement-and-tick.md"
DIG_DOC_PATH = ROOT / "docs/design/dig-npc-movement-lock-2026-07-28.md"
MULTIPLAYER_MODEL_PATH = ROOT / "docs/multiplayer-participant-model.md"
NATIVE_CALLS_PATH = (
    ROOT
    / "SolomonDarkModLoader/src/lua_engine_bindings_debug/functions_native_calls.inl"
)
DEBUG_REGISTRATION_PATH = (
    ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_debug.cpp"
)
MEMORY_TOOLING_DOC_PATH = ROOT / "docs/lua-memory-tooling.md"

EXPECTED_SOURCE_REVISION = "acc4ef5d7a2a03ae4f4b7b3350cb06f13960836d"
EXPECTED_RETAIL_SHA256 = (
    "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
)
EXPECTED_LOADER_SHA256 = (
    "93017506384cf86a69f5a4452c7061265f38028fb6bf03a779fe6804ca5867bd"
)
EXPECTED_FIXTURE_SHA256 = (
    "770fa976c9faea7eab731ba6d40b3798c548546dfec6a62780862b0b59c3ae3f"
)

EXPECTED_REGIONS = {
    0: {
        "type_id": 4001,
        "name": "Courtyard",
        "actor_count": 22,
        "type_counts": {
            1: ("PlayerWizard", 1),
            2007: ("CollegeObstacle", 8),
            2008: ("CollegeStatue", 1),
            5001: ("PerkWitch", 1),
            5002: ("Student", 6),
            5003: ("Annalist", 1),
            5004: ("PotionGuy", 1),
            5005: ("ItemsGuy", 1),
            5007: ("Tyrannia", 1),
            5008: ("Teacher", 1),
        },
    },
    1: {
        "type_id": 4002,
        "name": "Mortuary",
        "actor_count": 22,
        "type_counts": {
            1: ("PlayerWizard", 1),
            2041: ("CustomObject", 10),
            5017: ("Memorator", 1),
            5018: ("Painting", 10),
        },
    },
    2: {
        "type_id": 4004,
        "name": "Library",
        "actor_count": 7,
        "type_counts": {
            1: ("PlayerWizard", 1),
            2041: ("CustomObject", 4),
            5013: ("Librarian", 1),
            5016: ("Dowser", 1),
        },
    },
    3: {
        "type_id": 4003,
        "name": "StoreRoom",
        "actor_count": 4,
        "type_counts": {
            1: ("PlayerWizard", 1),
            2041: ("CustomObject", 3),
        },
    },
    4: {
        "type_id": 4005,
        "name": "Office",
        "actor_count": 3,
        "type_counts": {
            1: ("PlayerWizard", 1),
            2041: ("CustomObject", 1),
            5012: ("ArchChancellor", 1),
        },
    },
}

EXPECTED_NAMED_ACTORS = {
    0: {
        5001: ("PerkWitch", 1340.0, 280.0, 15.0),
        5004: ("PotionGuy", 1397.0, 664.0, 30.0),
        5003: ("Annalist", 895.5, 455.5, 8.0),
        5005: ("ItemsGuy", 1700.5, 449.5, 25.0),
        5007: ("Tyrannia", 669.0, 705.5, 10.0),
        5008: ("Teacher", 576.5, 710.5, 25.0),
    },
    1: {5017: ("Memorator", 628.0, 770.0, 25.0)},
    2: {
        5013: ("Librarian", 512.0, 595.0, 55.0),
        5016: ("Dowser", 900.0, 642.5, 25.0),
    },
    4: {5012: ("ArchChancellor", 514.0, 467.0, 55.0)},
}

EXPECTED_COURTYARD_OBSTACLES = {
    (1458.5, 320.5, 40.0),
    (955.5, 239.5, 40.0),
    (749.5, 162.5, 40.0),
    (1893.0, 490.0, 40.0),
    (1746.0, 534.0, 40.0),
    (1840.0, 715.0, 40.0),
    (628.0, 215.0, 40.0),
    (956.0, 169.0, 40.0),
}

EXPECTED_PAINTINGS = {
    (512.0, 697.0): 0,
    (350.0, 683.0): 1,
    (673.0, 683.0): 100,
    (744.0, 540.0): 3,
    (590.0, 540.0): 4,
    (434.0, 540.0): 5,
    (279.0, 540.0): 6,
    (354.0, 400.0): 7,
    (512.0, 400.0): 8,
    (670.0, 400.0): 9,
}

HAGATHA_CATALOG = (
    (0, "LIFE CHARM", 200),
    (1, "MANA CHARM", 200),
    (2, "SPEED CHARM", 250),
    (3, "ITEM CHARM", 1000),
    (4, "GOLD CHARM", 500),
    (5, "SEEKER'S CHARM", 200),
    (6, "REVELATION CHARM", 800),
    (7, "CHEAT DEATH CHARM", 5000),
    (8, "PERKY CHARM", 1500),
    (9, "SCATTER CURSE", 150),
    (10, "WAR CHARM", 800),
    (11, "CURING CHARM", 250),
    (12, "THE LAST WORD CHARM", 500),
    (13, "SPELLWELDER'S CHARM", 2000),
    (14, "WEIRD CASTER CHARM", 2500),
    (15, "DRINKER'S CHARM", 1000),
    (16, "GLASS CANNON CURSE", 1000),
    (17, "SORCEROR'S CHARM", 3000),
    (18, "FOCUS CHARM", 1000),
    (19, "DISFIGURING CURSE", 3000),
    (20, "BARE HANDS CHARM", 500),
    (21, "SPLIT MIND CHARM", 4000),
    (22, "CURSE BOSSES", 2000),
    (23, "ARCANE ATTRACTOR CHARM", 2000),
    (24, "SERENDIPITY CHARM", 1000),
    (25, "REVERIE CHARM", 1000),
    (26, "BRUTE'S CHARM", 3000),
    (27, "TONIC", 1000),
)

FOMENTIUS_OFFERS = {
    (7001, 0): (150, 2, 4, True),
    (7001, 1): (75, 2, 7, True),
    (7001, 5): (200, 1, 2, False),
    (7012, 0): (300, 2, 3, True),
    (7012, 1): (1200, 1, 1, False),
    (7008, 0): (50, 1, 2, True),
    (7001, 3): (100, 1, 3, True),
    (7001, 2): (2500, 1, 1, False),
    (7001, 4): (1500, 1, 1, False),
}

FOMENTIUS_REQUESTS = (3, 6, 3, 2, 18, 2, 3, 8, 8)
FOMENTIUS_RETURN_ADDRESSES = (
    "0x005C89B4",
    "0x005C8A33",
    "0x005C8AB2",
    "0x005C8B31",
    "0x005C8BA9",
    "0x005C8C1A",
    "0x005C8C9F",
    "0x005C8D24",
    "0x005C8D97",
)


def _read(path: Path, consequence: str) -> str:
    if not path.is_file():
        raise StaticReTestFailure(consequence)
    return path.read_text(encoding="utf-8")


def _require_tokens(text: str, tokens: tuple[str, ...], consequence: str) -> None:
    # These claims are intentionally whitespace-insensitive prose/code anchors.
    # Mechanisms which depend on statement structure use _require_regex below.
    flattened = " ".join(text.split())
    missing = [
        token
        for token in tokens
        if " ".join(token.split()) not in flattened
    ]
    if missing:
        raise StaticReTestFailure(f"{consequence}: {missing}")


def _require_regex(text: str, pattern: str, consequence: str) -> re.Match[str]:
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if match is None:
        raise StaticReTestFailure(consequence)
    return match


def _load_fixture() -> tuple[str, str, dict[str, Any], dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
    doc = _read(DOC_PATH, "the native hub/economy implementation contract is absent")
    recorder = _read(
        RECORDER_PATH,
        "the live hub/economy golden no longer has a reviewable recorder",
    )
    raw_fixture = _read(
        GOLDEN_PATH,
        "the standalone native hub/economy live fixture is absent",
    )
    try:
        fixture = json.loads(raw_fixture)
    except json.JSONDecodeError as exc:
        raise StaticReTestFailure(
            f"the native hub/economy golden is not reviewable JSON: {exc}"
        ) from exc

    if fixture.get("schema") != "solomon-dark-native-hub-economy-goldens-v1":
        raise StaticReTestFailure(
            "hub/economy consumers would parse an unrecognized golden schema"
        )
    if fixture.get("recorded_live") is not True:
        raise StaticReTestFailure(
            "hub/economy outcomes are no longer declared as live retail recordings"
        )
    if fixture.get("source_revision") != EXPECTED_SOURCE_REVISION:
        raise StaticReTestFailure(
            "hub/economy golden lost the exact clean source revision used for capture"
        )

    hash_matches = list(
        re.finditer(
            r"hub-economy-goldens\.json.*?SHA-256 `([0-9a-f]{64})`",
            doc,
            re.DOTALL,
        )
    )
    if len(hash_matches) != 1:
        raise StaticReTestFailure(
            "hub/economy documentation must name one unambiguous committed-fixture hash"
        )
    recorded_hash = hash_matches[0].group(1)
    if recorded_hash != EXPECTED_FIXTURE_SHA256:
        raise StaticReTestFailure(
            "hub/economy fixture provenance no longer names the reviewed live recording"
        )
    assert_recorded_hash_matches_file(
        recorded_hash,
        GOLDEN_PATH,
        "native hub/economy standalone live golden",
    )

    census = fixture.get("hub_entity_census")
    if not isinstance(census, dict):
        raise StaticReTestFailure(
            "hub entity census is no longer a named live recording section"
        )
    regions = census.get("regions")
    if not isinstance(regions, list) or len(regions) != 5:
        raise StaticReTestFailure(
            "hub census must retain exactly the five fixed retail regions"
        )
    region_indices = [region.get("region_index") for region in regions]
    if region_indices != [0, 1, 2, 3, 4]:
        raise StaticReTestFailure(
            "hub census lost exact five-region identity and native ordering"
        )
    regions_by_index = {region["region_index"]: region for region in regions}
    if len(regions_by_index) != 5:
        raise StaticReTestFailure(
            "hub region lookup is ambiguous because a region index is duplicated"
        )

    traders = fixture.get("trader_captures")
    if not isinstance(traders, list) or len(traders) != 3:
        raise StaticReTestFailure(
            "trader golden must retain three distinct progression/RNG states"
        )
    progression_ids = [
        capture.get("progression_state", {}).get("id") for capture in traders
    ]
    expected_progression_ids = [
        "fresh",
        "life_charm_previously_mixed",
        "last_word_owned",
    ]
    if progression_ids != expected_progression_ids:
        raise StaticReTestFailure(
            "trader golden lost a named fresh, first-mixed, or owned progression witness"
        )
    traders_by_state = {
        capture["progression_state"]["id"]: capture for capture in traders
    }
    if len(traders_by_state) != 3:
        raise StaticReTestFailure(
            "trader progression-state lookup is ambiguous because an id is duplicated"
        )
    for expected_index, capture in enumerate(traders, start=1):
        rolls = capture.get("shlorio_dowsing_rolls")
        if not isinstance(rolls, list) or len(rolls) != 8:
            raise StaticReTestFailure(
                f"trader state {expected_index} no longer carries eight live Dowsing trials"
            )

    dig_trials = fixture.get("dig_trials")
    if not isinstance(dig_trials, list) or len(dig_trials) != 8:
        raise StaticReTestFailure(
            "Solomon Dig distribution must retain eight independent live trials"
        )
    if [trial.get("trial_index") for trial in dig_trials] != list(range(1, 9)):
        raise StaticReTestFailure(
            "Solomon Dig trial lookup is ambiguous or no longer ordered 1 through 8"
        )

    return doc, recorder, fixture, regions_by_index, traders_by_state


def _require_header(
    header: Any,
    *,
    instance: str,
    method: str,
    trial_count: int,
    consequence: str,
) -> None:
    expected = {
        "instance": instance,
        "source_revision": EXPECTED_SOURCE_REVISION,
        "retail_executable_sha256": EXPECTED_RETAIL_SHA256,
        "loader_sha256": EXPECTED_LOADER_SHA256,
        "capture_method": method,
        "trial_count": trial_count,
    }
    if header != expected:
        raise StaticReTestFailure(consequence)


def _resolve_single_actor(
    region: dict[str, Any],
    type_id: int,
    consequence: str,
) -> dict[str, Any]:
    actors = region.get("actors")
    if not isinstance(actors, list) or len(actors) != region.get("actor_count"):
        raise StaticReTestFailure(
            "hub actor sweep did not reach the region's declared live population"
        )
    candidates = [actor for actor in actors if actor.get("type_id") == type_id]
    if len(candidates) != 1:
        raise StaticReTestFailure(consequence)
    return candidates[0]


def _literal_assignment(recorder: str, name: str) -> Any:
    tree = ast.parse(recorder)
    candidates: list[ast.AST] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            candidates.append(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            candidates.append(node.value)
    if len(candidates) != 1:
        raise StaticReTestFailure(
            f"recorder lookup for {name} is absent or ambiguous"
        )
    try:
        return ast.literal_eval(candidates[0])
    except (ValueError, TypeError) as exc:
        raise StaticReTestFailure(
            f"recorder constant {name} is no longer a reviewable literal"
        ) from exc


def _normalized_rng_state(state: Any, consequence: str) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise StaticReTestFailure(consequence)
    words = state.get("state_words")
    if not isinstance(words, list) or len(words) != 55:
        raise StaticReTestFailure(consequence)
    if state.get("divisor") != 100000:
        raise StaticReTestFailure(consequence)
    if not isinstance(state.get("index_a"), int) or not isinstance(
        state.get("index_b"), int
    ):
        raise StaticReTestFailure(consequence)
    return {
        "index_a": state["index_a"],
        "index_b": state["index_b"],
        "divisor": state["divisor"],
        "state_words": words,
    }


def test_native_hub_entity_census_and_interactions_are_pinned() -> str:
    doc, _, fixture, regions, _ = _load_fixture()

    census = fixture["hub_entity_census"]
    _require_header(
        census.get("header"),
        instance="hub-g8-capture-01",
        method="sd.scene.switch_region plus sd.world.list_actors live retail snapshots",
        trial_count=5,
        consequence="hub census header lost instance, SHA, method, or five-region trial provenance",
    )
    if census.get("capture_method") != (
        "sd.scene.switch_region plus sd.world.list_actors live retail snapshots"
    ):
        raise StaticReTestFailure(
            "hub census no longer names the live region/actor observation seam"
        )

    for region_index, expected in EXPECTED_REGIONS.items():
        region = regions[region_index]
        observed_counts = {
            int(type_id): (row.get("class"), row.get("count"))
            for type_id, row in region.get("type_counts", {}).items()
        }
        if (
            region.get("region_type_id") != expected["type_id"]
            or region.get("name") != expected["name"]
            or region.get("actor_count") != expected["actor_count"]
            or observed_counts != expected["type_counts"]
        ):
            raise StaticReTestFailure(
                f"{expected['name']} lost its exact native type and live entity census"
            )

    for region_index, expected_actors in EXPECTED_NAMED_ACTORS.items():
        if not expected_actors:
            raise StaticReTestFailure(
                "named hub actor sweep has no witness and would assert nothing"
            )
        for type_id, expected in expected_actors.items():
            actor = _resolve_single_actor(
                regions[region_index],
                type_id,
                f"hub actor type {type_id} is absent or ambiguous in its fixed room",
            )
            observed = (
                actor.get("class"),
                actor.get("x"),
                actor.get("y"),
                actor.get("radius"),
            )
            if observed != expected:
                raise StaticReTestFailure(
                    f"hub actor type {type_id} lost its semantic class, center, or click radius"
                )

    courtyard_actors = regions[0]["actors"]
    obstacles = {
        (actor.get("x"), actor.get("y"), actor.get("radius"))
        for actor in courtyard_actors
        if actor.get("type_id") == 2007
    }
    if obstacles != EXPECTED_COURTYARD_OBSTACLES:
        raise StaticReTestFailure(
            "Courtyard collision layout lost one of its eight exact CollegeObstacle witnesses"
        )
    statue = _resolve_single_actor(
        regions[0],
        2008,
        "Courtyard CollegeStatue is absent or ambiguous",
    )
    if (statue.get("x"), statue.get("y"), statue.get("radius")) != (
        961.0,
        834.0,
        50.0,
    ):
        raise StaticReTestFailure(
            "Courtyard statue no longer pins its gameplay collision center and radius"
        )

    mortuary_actors = regions[1]["actors"]
    paintings = [
        actor for actor in mortuary_actors if actor.get("type_id") == 5018
    ]
    if len(paintings) != 10:
        raise StaticReTestFailure(
            "Mortuary actor sweep did not reach all ten interactive Paintings"
        )
    observed_paintings = {
        (actor.get("x"), actor.get("y")): actor.get("eulogy_index")
        for actor in paintings
    }
    if len(observed_paintings) != 10 or observed_paintings != EXPECTED_PAINTINGS:
        raise StaticReTestFailure(
            "Mortuary Painting lookup lost an exact position/eulogy mapping or became ambiguous"
        )
    if any(actor.get("radius") != 15.0 for actor in paintings):
        raise StaticReTestFailure(
            "Mortuary Painting interaction targets no longer use the recorded radius 15"
        )

    schema_text = _read(
        INTENT_SCHEMA_PATH,
        "G14 intent schema is absent, so hub controls have no shared verb contract",
    )
    try:
        intent_schema = json.loads(schema_text)
    except json.JSONDecodeError as exc:
        raise StaticReTestFailure(
            f"G14 intent schema is not reviewable JSON: {exc}"
        ) from exc
    definitions = intent_schema.get("$defs", {})
    interact = definitions.get("interactIntent")
    menu_nav = definitions.get("menuNavIntent")
    if not isinstance(interact, dict) or not isinstance(menu_nav, dict):
        raise StaticReTestFailure(
            "hub interaction would invent verbs because G14 interact/menu_nav definitions vanished"
        )
    if interact.get("required") != ["kind", "target", "phase"]:
        raise StaticReTestFailure(
            "hub interact intents no longer require semantic target and press/release phase"
        )
    if interact.get("properties", {}).get("phase", {}).get("enum") != [
        "press",
        "release",
    ]:
        raise StaticReTestFailure(
            "hub interact intent no longer preserves the G14 press/release edge pair"
        )
    if menu_nav.get("properties", {}).get("command", {}).get("enum") != [
        "up",
        "down",
        "left",
        "right",
        "confirm",
        "back",
        "next",
        "previous",
    ]:
        raise StaticReTestFailure(
            "hub service dialogs no longer share G14's complete menu_nav command vocabulary"
        )

    _require_tokens(
        doc,
        (
            "[`native-scene-composition.md`](native-scene-composition.md)",
            "G12/rendre owns how these rooms and actors are drawn",
            "distance_squared > 5 * actor_radius^2 + 1500",
            "hub.npc.hagatha",
            "hub.npc.fomentius",
            "hub.npc.annalist",
            "hub.npc.luthacus",
            "hub.npc.tyrannia",
            "hub.npc.teacher",
            "hub.npc.memorator",
            "hub.painting.<eulogy_index>",
            "hub.npc.librarian",
            "hub.npc.shlorio",
            "hub.npc.arch_chancellor",
            "hub.run_entry",
            "`Gameplay+0x1CD8`",
            "`Gameplay+0x1CDC = 1`",
            "`Gameplay+0x1CDD = 1`",
        ),
        "hub entity behavior lost a named interaction, G12 boundary, or alternate-population gate",
    )
    _require_regex(
        doc,
        r"Their interaction vtable slot `\+0x68`\s+is the no-op `0x0055C300`",
        "roaming Students could be mistaken for talk targets because their no-op interaction slot drifted",
    )
    _require_regex(
        doc,
        r"^\| `hub\.npc\.hagatha` \| `WITCH_INTRO`, then `WITCH_Q` \| .*?!BUYPERKS.*?\|.*?$",
        "Hagatha's actor no longer maps directly to her dialogue and PerkShop action",
    )
    _require_regex(
        doc,
        r"^\| `hub\.run_entry` \| Stock `MapPicker` \| Courtyard control at `Gameplay\+0xE00`.*?$",
        "run entry could be mistaken for a world Portal because its UI control row drifted",
    )
    return "five-room hub census, collision targets, NPC actions, and G14 intent mapping are pinned"


def test_native_hub_price_formulas_and_transaction_constants_are_pinned() -> str:
    doc, _, _, _, traders = _load_fixture()

    catalog_text = _read(
        HAGATHA_CATALOG_PATH,
        "Hagatha's reviewable native selector catalog is absent",
    )
    try:
        catalog = json.loads(catalog_text)
    except json.JSONDecodeError as exc:
        raise StaticReTestFailure(
            f"Hagatha selector catalog is not reviewable JSON: {exc}"
        ) from exc
    perks = catalog.get("perks")
    if not isinstance(perks, list) or len(perks) != 28:
        raise StaticReTestFailure(
            "Hagatha price table sweep did not reach all 28 native selectors"
        )
    observed_catalog = tuple(
        (row.get("selector"), row.get("name"), row.get("price")) for row in perks
    )
    if observed_catalog != HAGATHA_CATALOG:
        raise StaticReTestFailure(
            "Hagatha's exact selector names or base-price constants drifted"
        )
    base_prices = {selector: price for selector, _, price in HAGATHA_CATALOG}

    expected_states = {
        "fresh": (set(), set(), 0, 27),
        "life_charm_previously_mixed": ({0}, set(), 0, 27),
        "last_word_owned": ({12}, {12}, 1, 26),
    }
    if len(expected_states) != 3:
        raise StaticReTestFailure(
            "Hagatha progression price matrix has no named witness states"
        )
    for state_id, (mixed, owned, placeholders, visible_count) in expected_states.items():
        capture = traders[state_id]
        progression = capture["progression_state"]
        if progression.get("perk_catalog_limit") != 29:
            raise StaticReTestFailure(
                f"{state_id} no longer witnesses Hagatha's live catalog limit 29"
            )
        if set(progression.get("first_mixed_selectors", ())) != mixed:
            raise StaticReTestFailure(
                f"{state_id} lost its exact first-mix price-gate state"
            )
        if set(progression.get("owned_selectors", ())) != owned:
            raise StaticReTestFailure(
                f"{state_id} lost its exact owned-offer gate state"
            )
        hagatha = capture.get("hagatha", {})
        offers = hagatha.get("offers")
        if not isinstance(offers, list) or len(offers) != visible_count:
            raise StaticReTestFailure(
                f"{state_id} no longer exposes its complete Hagatha visible catalog"
            )
        if hagatha.get("owned_offer_placeholder_count") != placeholders:
            raise StaticReTestFailure(
                f"{state_id} no longer pins owned Hagatha offers as placeholders"
            )
        selectors = [offer.get("selector") for offer in offers]
        if len(set(selectors)) != len(offers):
            raise StaticReTestFailure(
                f"{state_id} Hagatha selector lookup became ambiguous through duplicates"
            )
        expected_selectors = set(range(28)) - {8} - owned
        if set(selectors) != expected_selectors:
            raise StaticReTestFailure(
                f"{state_id} lost selector 8 exclusion or an owned-selector offer gate"
            )
        for offer in offers:
            selector = offer["selector"]
            expected_price = (
                base_prices[selector] if selector in mixed else base_prices[selector] * 3
            )
            if (
                offer.get("price") != expected_price
                or offer.get("quantity") != 1
                or offer.get("type_id") != 7009
            ):
                raise StaticReTestFailure(
                    f"Hagatha selector {selector} no longer follows base-or-triple first-mix pricing"
                )

    for state_id, capture in traders.items():
        fomentius = capture.get("fomentius", {})
        offers = fomentius.get("offers")
        if not isinstance(offers, list) or len(offers) < 5:
            raise StaticReTestFailure(
                f"{state_id} Fomentius catalog sweep did not reach the five guaranteed offer families"
            )
        keys = [(offer.get("type_id"), offer.get("variant_id")) for offer in offers]
        if len(set(keys)) != len(offers):
            raise StaticReTestFailure(
                f"{state_id} grouped Fomentius lookup is ambiguous through duplicate type/variant rows"
            )
        if not set(keys).issubset(FOMENTIUS_OFFERS):
            raise StaticReTestFailure(
                f"{state_id} Fomentius stock contains an offer outside the nine native families"
            )
        guaranteed = {key for key, row in FOMENTIUS_OFFERS.items() if row[3]}
        if not guaranteed.issubset(keys):
            raise StaticReTestFailure(
                f"{state_id} Fomentius stock lost a guaranteed potion/item family"
            )
        for offer in offers:
            key = (offer["type_id"], offer["variant_id"])
            price, minimum, maximum, _ = FOMENTIUS_OFFERS[key]
            if (
                offer.get("price") != price
                or not minimum <= offer.get("quantity", 0) <= maximum
            ):
                raise StaticReTestFailure(
                    f"Fomentius offer {key} escaped its exact price or rolled quantity bounds"
                )
        if fomentius.get("stock_count") != sum(
            offer["quantity"] for offer in offers
        ):
            raise StaticReTestFailure(
                f"{state_id} Fomentius grouped quantities no longer equal native stock objects"
            )

    all_rolls = [
        roll
        for capture in traders.values()
        for roll in capture["shlorio_dowsing_rolls"]
    ]
    if len(all_rolls) != 24:
        raise StaticReTestFailure(
            "Shlorio price sweep did not reach all 24 live rolled inventories"
        )
    for roll in all_rolls:
        offers = roll.get("offers")
        if not isinstance(offers, list) or len(offers) not in (3, 4):
            raise StaticReTestFailure(
                "Shlorio live roll no longer contains the native three-or-four offer count"
            )
        if roll.get("gold_before") - roll.get("gold_after") != roll.get(
            "reroll_fee_before"
        ):
            raise StaticReTestFailure(
                "Shlorio DOWSE no longer debits exactly the current participant fee"
            )
        if roll.get("reroll_fee_before") != 650 or roll.get(
            "reroll_fee_after"
        ) != 650:
            raise StaticReTestFailure(
                "Shlorio no-purchase trials no longer preserve the observed 650 runtime fee"
            )
        for offer in offers:
            price = offer.get("price")
            if not isinstance(price, int) or not 5000 <= price <= 5700 or price % 50:
                raise StaticReTestFailure(
                    "Shlorio offer escaped (Integer(15)+100)*50 pricing"
                )

    _require_regex(
        doc,
        r"individual_price\(selector\) =\n"
        r"    base\[selector\]\s+if first_mixed\[selector\] != 0\n"
        r"    3 \* base\[selector\]\s+otherwise\n\n"
        r"bulk_price = floor\(sum\(individual_price\(member\)\) / 2 \+ 0\.5\)\n"
        r"           = ceil\(sum\(individual_price\(member\)\) / 2\)",
        "Hagatha individual and bulk price formulas no longer preserve their branch and rounding structure",
    )
    _require_tokens(
        doc,
        (
            "The common Shop purchase callback `0x0056BF70`",
            "`item+0x5C`",
            "`0x005A7C60` with `-price` and `false`",
            "there is no sell price, buyback, cancellation refund, or later refund path",
            "next_dowsing_fee = (Integer(10) + 10) * 50   // 500..950",
            "`(Integer(15)+100)*50`, exactly 5000..5700 in steps of 50",
        ),
        "shop transaction constants, no-refund rule, or Shlorio price formulas drifted",
    )

    native_calls = _read(
        NATIVE_CALLS_PATH,
        "Hagatha's two-argument price probe implementation is absent",
    )
    registration = _read(
        DEBUG_REGISTRATION_PATH,
        "Hagatha's price probe is not exposed to Lua execution",
    )
    memory_doc = _read(
        MEMORY_TOOLING_DOC_PATH,
        "Hagatha's additive price probe has no tooling contract",
    )
    signature = "int LuaDebugCallStdcallU32U32RetU32(lua_State* state) {"
    starts = [match.start() for match in re.finditer(re.escape(signature), native_calls)]
    if len(starts) != 1:
        raise StaticReTestFailure(
            "Hagatha price probe function definition is absent or ambiguous"
        )
    end_marker = "// sd.debug.resolve_native_primary_spell_stats"
    end = native_calls.find(end_marker, starts[0])
    if end < 0:
        raise StaticReTestFailure(
            "Hagatha price probe body cannot be bounded before the next debug helper"
        )
    body = native_calls[starts[0]:end]
    _require_regex(
        body,
        r"ResolveExecutableLuaAddress\(memory, requested_function_address\);\s*"
        r"if \(function_address == 0\) \{\s*lua_pushnil\(state\);\s*return 1;\s*\}",
        "Hagatha price probe could call an unresolved or non-executable address",
    )
    _require_regex(
        body,
        r"using StdcallU32U32RetU32Fn =\s*"
        r"std::uint32_t\(__stdcall\*\)\(std::uint32_t, std::uint32_t\);.*?"
        r"std::uint32_t result = 0;\s*bool ok = false;\s*__try \{\s*"
        r"result = fn\(arg0, arg1\);\s*ok = true;\s*\}.*?"
        r"if \(!ok\) \{\s*lua_pushnil\(state\);\s*return 1;\s*\}\s*"
        r"lua_pushinteger\(state, static_cast<lua_Integer>\(result\)\);",
        "Hagatha price probe lost stdcall cleanup, SEH failure handling, or valid-zero return semantics",
    )
    _require_regex(
        registration,
        r"RegisterFunction\(\s*state,\s*&LuaDebugCallStdcallU32U32RetU32,\s*"
        r'"call_stdcall_u32_u32_ret_u32"\s*\);',
        "Hagatha price probe implementation exists but is not registered under its documented Lua name",
    )
    if "sd.debug.call_stdcall_u32_u32_ret_u32(function_address, arg0, arg1)" not in memory_doc:
        raise StaticReTestFailure(
            "Hagatha price probe is registered but missing from the Lua memory-tooling contract"
        )
    return "Fomentius, Hagatha, and Shlorio prices plus the bounded price probe are pinned"


def test_native_hub_inventory_generation_and_rng_provenance_are_pinned() -> str:
    doc, recorder, fixture, _, traders = _load_fixture()

    expected_recorder_constants = {
        "APP_TICK_SEED_MULTIPLIER": 0xEF3,
        "NATIVE_RNG_SEED": 0x00401120,
        "NATIVE_RNG_INTEGER": 0x00401170,
        "NATIVE_RNG_FLOAT": 0x00401310,
        "NATIVE_STOCK_GENERATOR": 0x005C8960,
        "NATIVE_HAGATHA_PRICE": 0x005A7CA0,
        "DOWSING_ACTION": 0x0055FAF0,
        "SHOP_ADD_OFFER": 0x0055ACB0,
        "ACTIVE_RNG_POINTER": 0x00818B08,
        "APP_GLOBAL": 0x00B401A8,
        "DOWSING_COST": 0x0081A430,
    }
    if not expected_recorder_constants:
        raise StaticReTestFailure(
            "hub inventory generation constant sweep has no native witness"
        )
    for name, expected in expected_recorder_constants.items():
        if _literal_assignment(recorder, name) != expected:
            raise StaticReTestFailure(
                f"inventory-generation path lost exact native constant {name}"
            )

    stock_returns = _literal_assignment(recorder, "RNG_STOCK_RETURNS")
    expected_stock_returns = {int(value, 16) for value in FOMENTIUS_RETURN_ADDRESSES}
    if stock_returns != expected_stock_returns:
        raise StaticReTestFailure(
            "Fomentius generation trace no longer resolves all nine exact Integer call sites"
        )
    if _literal_assignment(recorder, "DOWSING_INTEGER_RETURNS") != {
        0x00554A94,
        0x0055FE2A,
        0x0055FE8E,
    }:
        raise StaticReTestFailure(
            "Shlorio generation trace lost count, selector, or price call-site identity"
        )
    if _literal_assignment(recorder, "DOWSING_FLOAT_RETURN") != 0x0055FDE9:
        raise StaticReTestFailure(
            "Shlorio generation trace no longer isolates its one presentation Float call"
        )

    capture_contract = fixture.get("capture_contract")
    expected_capture_contract = {
        "allowed_instance_prefix": "hub-*",
        "allowed_udp_ports": list(range(52311, 52319)),
        "audio_disabled": True,
        "dig_trials": 8,
        "dowsing_rolls_per_trader_capture": 8,
        "instances": 8,
        "sd_rng_set_seed_used": False,
        "trader_progression_states": 3,
    }
    if capture_contract != expected_capture_contract:
        raise StaticReTestFailure(
            "live hub/economy recorder escaped its eight-instance, port, audio, or no-set_seed contract"
        )
    if re.search(r"sd\.rng\.set_seed\s*\(", recorder):
        raise StaticReTestFailure(
            "trader recorder incorrectly treats sd.rng.set_seed as authoritative"
        )

    state_hashes: list[str] = []
    for state_id, capture in traders.items():
        expected_instance = {
            "fresh": "hub-g8-capture-01",
            "life_charm_previously_mixed": "hub-g8-capture-02",
            "last_word_owned": "hub-g8-capture-03",
        }[state_id]
        _require_header(
            capture.get("header"),
            instance=expected_instance,
            method="live retail Lua exec plus native function tracing and full active RNG snapshots",
            trial_count=8,
            consequence=f"{state_id} trader header lost instance, SHA, method, or eight-roll provenance",
        )
        evidence = capture.get("seed_evidence")
        if not isinstance(evidence, dict):
            raise StaticReTestFailure(
                f"{state_id} trader stock has no explicit seed/stream evidence"
            )
        if (
            evidence.get("stream_identity_proven") is not True
            or evidence.get("integer_call_count") != 9
            or tuple(evidence.get("integer_requests", ())) != FOMENTIUS_REQUESTS
            or tuple(evidence.get("integer_return_addresses", ()))
            != FOMENTIUS_RETURN_ADDRESSES
        ):
            raise StaticReTestFailure(
                f"{state_id} no longer proves Fomentius consumed nine ordered calls on the active stream"
            )
        if (
            evidence.get("seed_trace_hit_count_for_active_stream") != 0
            or evidence.get("construction_seed") is not None
            or evidence.get("construction_app_tick") is not None
            or evidence.get("construction_seed_matches_tick_times_0xEF3") is not False
            or evidence.get("portable_from_seed_alone") is not False
        ):
            raise StaticReTestFailure(
                f"{state_id} invents a portable construction seed the live pipe could not observe"
            )
        state = _normalized_rng_state(
            evidence.get("state_immediately_before_generation"),
            f"{state_id} pre-generation RNG snapshot is incomplete",
        )
        encoded = json.dumps(
            state,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        actual_state_hash = hashlib.sha256(encoded).hexdigest()
        if evidence.get("state_sha256") != actual_state_hash:
            raise StaticReTestFailure(
                f"{state_id} RNG state hash no longer matches its 58-dword snapshot"
            )
        state_hashes.append(actual_state_hash)
        _normalized_rng_state(
            capture.get("rng_state_after_generation"),
            f"{state_id} post-generation RNG snapshot is incomplete",
        )

    if len(state_hashes) != 3 or len(set(state_hashes)) != 3:
        raise StaticReTestFailure(
            "trader golden no longer contains three distinct full RNG states"
        )

    all_rolls = [
        roll
        for capture in traders.values()
        for roll in capture["shlorio_dowsing_rolls"]
    ]
    if len(all_rolls) != 24:
        raise StaticReTestFailure(
            "Dowsing generation sweep did not reach all 24 live rolls"
        )
    for roll in all_rolls:
        offers = roll.get("offers")
        if not isinstance(offers, list) or len(offers) not in (3, 4):
            raise StaticReTestFailure(
                "Dowsing generation no longer yields a witnessed three-or-four offer list"
            )
        requests = roll.get("integer_requests")
        returns = roll.get("integer_return_addresses")
        if not isinstance(requests, list) or not isinstance(returns, list) or len(
            requests
        ) != len(returns):
            raise StaticReTestFailure(
                "Dowsing roll lost one-to-one request/return call provenance"
            )
        if requests[0] != 2 or returns[0] != "0x0055FE2A":
            raise StaticReTestFailure(
                "Dowsing offer count is no longer the identified Integer(2)+3 draw"
            )
        selector_requests = [
            request
            for request, return_address in zip(requests, returns)
            if return_address == "0x00554A94"
        ]
        price_requests = [
            request
            for request, return_address in zip(requests, returns)
            if return_address == "0x0055FE8E"
        ]
        if len(selector_requests) < len(offers) or set(selector_requests) != {47}:
            raise StaticReTestFailure(
                "Dowsing item selection no longer proves the 47-entry retry path"
            )
        if len(price_requests) != len(offers) or set(price_requests) != {15}:
            raise StaticReTestFailure(
                "Dowsing price generation no longer uses one Integer(15) per offer"
            )
        if roll.get("all_calls_used_active_stream") is not True:
            raise StaticReTestFailure(
                "Dowsing count/item/price calls are no longer tied to the captured active stream"
            )
        if roll.get("float_requests") != [
            {"scaled_range_bits": 1036831949, "signed": False}
        ] or roll.get("float_return_addresses") != ["0x0055FDE9"]:
            raise StaticReTestFailure(
                "Dowsing no longer isolates exactly one Float(0.1,false) presentation draw"
            )
        _normalized_rng_state(
            roll.get("rng_before"),
            "Dowsing before-state is not a complete 58-dword native stream",
        )
        _normalized_rng_state(
            roll.get("rng_after"),
            "Dowsing after-state is not a complete 58-dword native stream",
        )

    _require_tokens(
        recorder,
        (
            "session.assert_process_runnable()",
            "BROKEN: launcher exited",
            "BUSY_TIMEOUT: Lua pipe never became runnable",
            "BROKEN: pre-existing hub-* target processes would make ownership ambiguous",
            "existing sd.debug.call_thiscall_ret_u32 against live Game",
            '"sd_rng_set_seed_used": False',
        ),
        "live recorder can no longer distinguish broken from busy, refuse ambiguity, or prove a real native replay",
    )
    _require_tokens(
        doc,
        (
            "construction_seed = App[+0x28] * 0xEF3",
            "The construction app tick and seed are therefore `null` in the fixture",
            "`portable_from_seed_alone` is false",
            "Their constructor `0x00501B80` consumes both native",
            "`Integer(3) == 1`",
            "Generator `0x005C8960`",
            "`0x005CFA80` calls the generator",
            "`0x005CF920`",
            "It reads the catalog limit through `*(DAT_008199CC)+0xF0C`",
            "result `+2`: 2..4",
            "one only when result equals 1",
            "one only when result equals 3",
        ),
        "inventory generation lost its native call path, gates, or nonportable seeding consequence",
    )
    rng_doc = _read(
        RNG_DOC_PATH,
        "G1 RNG contract is absent, so hub rolls have no primitive definition",
    )
    _require_tokens(
        rng_doc,
        (
            "seed = *(int *)(*(App **)0x00b401a8 + 0x28) * 0xEF3",
            "per-object field at `this+0xE4`",
            "rounds to float32 three separate times",
            "A signed float request costs **two** stream words",
        ),
        "hub RNG provenance no longer cites G1's app-tick seed and exact float cost",
    )
    return "Fomentius/Hagatha/Shlorio generation and full active-stream provenance are pinned"


def test_native_hub_dig_and_run_boundary_fields_are_pinned() -> str:
    doc, recorder, fixture, _, _ = _load_fixture()

    dig_trials = fixture["dig_trials"]
    if len(dig_trials) != 8:
        raise StaticReTestFailure(
            "Solomon Dig state/yield sweep did not reach eight live trials"
        )
    expected_reward_delta = {"2011": 0, "2012": 0, "2013": 0, "2038": 0}
    for trial_index, trial in enumerate(dig_trials, start=1):
        _require_header(
            trial.get("header"),
            instance=f"hub-g8-capture-{trial_index:02d}",
            method="live retail proximity/dialog drive with before/after currency, inventory, reward-actor and arena-state snapshots",
            trial_count=1,
            consequence=f"Dig trial {trial_index} lost instance, SHA, method, or one-trial provenance",
        )
        trigger = trial.get("trigger", {})
        if trigger.get("mechanism") != "participant proximity to live type 5009 actor":
            raise StaticReTestFailure(
                f"Dig trial {trial_index} no longer uses native participant proximity"
            )
        if trigger.get("g14_intents_used") != ["menu_nav.confirm"]:
            raise StaticReTestFailure(
                f"Dig trial {trial_index} no longer records its G14 dialogue intent"
            )
        transitions = trial.get("state_transitions")
        if not isinstance(transitions, list) or len(transitions) < 3:
            raise StaticReTestFailure(
                f"Dig trial {trial_index} did not reach live state 0, acquisition, state 1, and completion observations"
            )
        if transitions[0].get("dig_state") != 0 or transitions[0].get(
            "participant_acquired"
        ) is not False:
            raise StaticReTestFailure(
                f"Dig trial {trial_index} lost its pre-acquisition state-0 witness"
            )
        if not any(
            row.get("participant_acquired") is True for row in transitions
        ):
            raise StaticReTestFailure(
                f"Dig trial {trial_index} never witnessed native participant acquisition"
            )
        if not any(row.get("dig_state") == 1 for row in transitions):
            raise StaticReTestFailure(
                f"Dig trial {trial_index} never witnessed the native narration state"
            )
        before = trial.get("before", {})
        after = trial.get("after_native_completion", {})
        if (
            trial.get("consumed_gold") != 0
            or trial.get("consumed_inventory_items") != []
            or trial.get("direct_yield") != []
            or trial.get("direct_reward_actor_delta") != expected_reward_delta
            or before.get("gold") != after.get("gold")
            or before.get("inventory") != after.get("inventory")
            or after.get("arena_dig_complete") != 1
            or after.get("dig_state") not in (3, 4)
            or after.get("participant_acquired") is not True
            or after.get("target_gameplay_slot") != 0
        ):
            raise StaticReTestFailure(
                f"Dig trial {trial_index} no longer proves zero economic yield and native Arena completion"
            )

    distribution = fixture.get("observed_dig_distribution")
    if not isinstance(distribution, dict) or distribution.get("trial_count") != 8:
        raise StaticReTestFailure(
            "Dig distribution summary no longer covers its eight underlying live trials"
        )
    expected_zeroes = [0] * 8
    if (
        distribution.get("direct_yield_counts") != expected_zeroes
        or distribution.get("gold_deltas") != expected_zeroes
        or distribution.get("inventory_changed") != [False] * 8
        or distribution.get("reward_actor_deltas") != [expected_reward_delta] * 8
    ):
        raise StaticReTestFailure(
            "Dig distribution summary no longer agrees with probability-one zero direct yield"
        )

    recorder_tree = ast.parse(recorder)
    dig_functions = [
        node
        for node in recorder_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "capture_dig_trial"
    ]
    if len(dig_functions) != 1:
        raise StaticReTestFailure(
            "Dig recorder function lookup is absent or ambiguous"
        )
    dig_source = ast.get_source_segment(recorder, dig_functions[0])
    if not isinstance(dig_source, str) or "local_sync.place_player" not in dig_source:
        raise StaticReTestFailure(
            "Dig recorder no longer drives the real native proximity rail"
        )
    forbidden_writes = (
        "write_i32",
        "write_u32",
        "write_u8",
        "write_ptr",
        "+ 0x220",
        "+ 0x902A",
    )
    leaked = [token for token in forbidden_writes if token in dig_source]
    if leaked:
        raise StaticReTestFailure(
            f"Dig recorder writes the state/yield fields it claims to observe: {leaked}"
        )
    _require_tokens(
        dig_source,
        (
            "session.assert_process_runnable()",
            "BROKEN: testrun start failed",
            "BUSY_TIMEOUT: hub never became ready for testrun",
            "BROKEN: Solomon Dig disappeared before completing",
            "BUSY_TIMEOUT: Solomon Dig did not complete trial",
        ),
        "Dig probe can no longer distinguish dead setup from a busy native transaction",
    )

    _require_tokens(
        doc,
        (
            "`Solomon_Dig` is factory type 5009",
            "Lantern type 5010",
            "`+0x220` | interaction state",
            "`+0x2A0` | a gameplay participant has been acquired",
            "`+0x2A4` | selected gameplay slot",
            "`Arena+0x902A = 1`",
            "| Complete Solomon prelude | 0 | 0 | 0 | 0 | `Arena+0x902A = 1` | 1 |",
            "host remains the only wave/enemy/world authority",
        ),
        "Solomon Dig lost its type, state fields, zero-yield outcome, or split multiplayer authority",
    )
    dig_doc = _read(
        DIG_DOC_PATH,
        "the prior Solomon Dig ownership contract is absent",
    )
    _require_tokens(
        dig_doc,
        (
            "`Solomon_Dig` is native type `0x1391` (factory id 5009)",
            "`arena + 0x902A = 1`",
            "The host remains the world, wave, and enemy authority.",
        ),
        "G8 Dig semantics no longer build on the proven native completion/authority boundary",
    )

    boundary_rows = (
        r"^\| Gameplay \| `\+0x1C90` \| participant name used as the retained Sack name prefix \|$",
        r"^\| Gameplay \| `\+0x13B8` \| active inventory root \|$",
        r"^\| Gameplay \| `\+0x1410` \| seven equipment sinks \|$",
        r"^\| local player actor \(`\*\(Gameplay\+0x1358\)`\) \| `\+0x1C0` \| boolean controlling ordinary equipment/backpack transfer; exact producer semantics unresolved \|$",
        r"^\| progression \(`\*\*\(Gameplay\+0x1654\)`\) \| `\+0x7D8` \| Last Word owned flag controlling ground-Sack/Gold sweep \|$",
    )
    if not boundary_rows:
        raise StaticReTestFailure(
            "hub/run boundary row sweep has no exact field witness"
        )
    for pattern in boundary_rows:
        _require_regex(
            doc,
            pattern,
            "completed-run archival lost an exact producer field or consumer meaning",
        )
    _require_tokens(
        doc,
        (
            "Game-over archival `0x005C9670` calls completed-run processor `0x005BE320`",
            "Earthly Possessions | Stuff | Dead Stuff | Bag | Loot",
            "Sack suffix consumes `Integer(5)`",
            "type-2013 Sack",
            "type-2012 Gold actor",
            "profile `+0x8C`",
            "persistence helper `0x005BE0B0`",
            "selected Boneyard String | Gameplay `+0x1BD8`",
            "map unlock bitmap | Gameplay `+0x1CDC`, 50 bytes",
            "purchase request | initiating participant",
            "run-entry selection and shared transition | host/session authority",
        ),
        "hub/run state contract lost retained items, gold, map fields, persistence, or multiplayer purchase authority",
    )
    multiplayer_model = _read(
        MULTIPLAYER_MODEL_PATH,
        "participant-owned inventory/economy model is absent",
    )
    _require_tokens(
        multiplayer_model,
        (
            "Luthacus storage plus Fomentius and Hagatha purchases remain",
            "owner-local stock UI operations and publish their resulting participant state.",
            "Loot pickup must",
            "credit that mutable participant state, not `DAT_0081A388` global gold",
        ),
        "hub purchases could regress to a single process-global ledger instead of participant ownership",
    )
    return "Solomon Dig zero-yield completion and every recovered hub/run boundary field are pinned"
