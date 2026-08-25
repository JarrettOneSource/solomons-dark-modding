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
NPC_INTERACTIONS_DOC_PATH = (
    ROOT / "docs/reverse-engineering/native-hub-npc-interactions.md"
)
NPC_MARKER_CATALOG_PATH = (
    ROOT / "docs/reverse-engineering/native-hub-npc-marker-catalog.json"
)
GOLDEN_PATH = ROOT / "tests/fixtures/webgame/hub-economy-goldens.json"
RECORDER_PATH = ROOT / "tests/re/record_live_hub_economy_goldens.py"
HAGATHA_CATALOG_PATH = (
    ROOT / "docs/reverse-engineering/native-hagatha-perk-catalog.json"
)
TRADER_CATALOG_PATH = (
    ROOT / "docs/reverse-engineering/native-hub-trader-catalog.json"
)
INVENTORY_CAPTURE_PATH = (
    ROOT / "tests/fixtures/webgame/menu-reference-captures/inventory-screen.png"
)
TRADER_CAPTURE_MANIFEST_PATH = (
    ROOT / "tests/fixtures/webgame/native-hub-trader-ui-captures.json"
)
UNFORGE_CAPTURE_MANIFEST_PATH = (
    ROOT / "tests/fixtures/webgame/native-inventory-unforge-captures.json"
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
EXPECTED_INVENTORY_CAPTURE_SHA256 = (
    "0d99c6bb3f1815aa061fd4ee49e7bfccbd0ee058ea69b0e8936155c7e5156d8b"
)
EXPECTED_UNFORGE_CAPTURE_HASHES = {
    "menu-reference-captures/inventory-unforge-confirm.png":
        "eea3d09bf56a38b352d2c4eb53b47f29e45ff9eb8d941ef9ef0b3f857c4cca7a",
    "menu-reference-captures/inventory-unforge-result-recipeless-staff.png":
        "5da6181a98edb94bd5c0e9fa70e17aa37f311020781ea2e1514e82d4a8dfd4f4",
}

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


def test_native_hub_npc_markers_and_profile_help_rows_are_pinned() -> str:
    catalog = json.loads(NPC_MARKER_CATALOG_PATH.read_text(encoding="utf-8"))
    if catalog.get("schema") != "solomon-dark-native-hub-npc-markers-v1":
        raise StaticReTestFailure("native Hub NPC marker catalog schema drifted")
    if catalog.get("source", {}).get("sha256") != EXPECTED_RETAIL_SHA256:
        raise StaticReTestFailure("native Hub NPC marker catalog lost retail identity")
    common = catalog.get("common_contract", {})
    if common != {
        "dialogue_pointer_offset": "0x154",
        "dialogue_availability_offset": "0x04",
        "facing_scale_offset": "0x15C",
        "phase_offset": "0x160",
        "style_offset": "0x164",
        "marker_x_offset": "0x168",
        "marker_y_offset": "0x16C",
        "phase_initial_draw": {"function": "Integer", "exclusive_bound": 5000},
        "root_offset": {"x_magnitude": 30, "y": -60},
        "alpha": {
            "formula": "sin(phase_degrees*pi/180)*0.25+0.75",
            "minimum": 0.5,
            "maximum": 1.0,
        },
        "record_index_formula": "style*2+(facing_scale<0?1:0)",
        "record_order": ["talk-right", "talk-left", "help-right", "help-left"],
        "general_modal_gate": "DAT_00B3BCA0",
    }:
        raise StaticReTestFailure("common native actor marker fields or formula drifted")
    if catalog.get("region_banks") != [
        {"region": "courtyard", "atlas": "College", "records": [59, 60, 61, 62], "game_object_field": "0x2468"},
        {"region": "mortuary", "atlas": "Memoratorium", "records": [24, 25, 26, 27], "game_object_field": "0x08C8"},
        {"region": "library", "atlas": "Library", "records": [17, 18, 19, 20], "game_object_field": "0x0A40"},
        {"region": "storeroom", "atlas": "Storage", "records": [7, 8, 9, 10], "game_object_field": "0x0598"},
        {"region": "office", "atlas": "Office", "records": [13, 14, 15, 16], "game_object_field": "0x05B8"},
    ]:
        raise StaticReTestFailure("native Hub Region marker banks are incomplete")
    actors = catalog.get("survival_actors")
    if not isinstance(actors, list) or [
        (row.get("interaction_id"), row.get("type_id"), row.get("style"),
         row.get("side"), row.get("record"), row.get("phase_advances"),
         row.get("profile_hint_index"))
        for row in actors
    ] != [
        ("hagatha", 5001, "help", "right", 61, False, None),
        ("annalist", 5003, "talk", "right", 59, True, 0),
        ("fomentius", 5004, "help", "right", 61, True, 1),
        ("luthacus", 5005, "talk", "left", 60, True, 2),
        ("skorcha", 5007, "talk", "variant-1-left-otherwise-right", None, True, None),
        ("teacher", 5008, "help", "left", 62, False, None),
        ("arch-chancellor", 5012, "help", "right", 15, True, None),
        ("librarian", 5013, "help", "right", 19, True, None),
        ("shlorio", 5016, "help", "left", 20, True, None),
        ("memorator", 5017, "help", "left", 27, True, None),
    ]:
        raise StaticReTestFailure("native survival actor marker membership drifted")
    story_office = catalog.get("first_story_office_actors")
    if not isinstance(story_office, list) or [
        (
            row.get("interaction_id"),
            row.get("type_id"),
            row.get("position"),
            row.get("interaction_radius"),
            row.get("marker_record"),
            row.get("dialogue"),
        )
        for row in story_office
    ] != [
        (
            "arch-chancellor-story-0",
            5012,
            [514, 467],
            55,
            15,
            ["ARCH_INTRO_0", "ARCH_Q1_0", "ARCH_Q2_0", "ARCH_Q3_0", "ARCH_DISMISS_0"],
        ),
        (
            "polisher-story-0",
            5011,
            [566, 735],
            15,
            14,
            ["POLISHER_INTRO_0", "POLISHER_Q1_0", "POLISHER_Q2_0", "POLISHER_DISMISS_0"],
        ),
    ]:
        raise StaticReTestFailure("native first-story Office marker/dialogue membership drifted")
    polisher = story_office[1]
    if (
        polisher.get("art_records") != [23, 24, 25, 26]
        or polisher.get("phase_speed") != 0.05
        or polisher.get("phase_float_draw") != 0.25
        or polisher.get("reverse_draw_count") != 1500
        or polisher.get("reverse_draw_value") != 3
        or polisher.get("loop") != "dynamic_sounds/wipeglass.wav"
        or polisher.get("loop_full_distance") != 50
        or polisher.get("loop_silent_distance") != 200
    ):
        raise StaticReTestFailure("native first-story Polisher presentation contract drifted")
    help_table = catalog.get("profile_hint_table", {})
    if (
        help_table.get("profile_offset_start") != "0x9A"
        or help_table.get("fresh_values") != [True] * 10
        or [row.get("clearer") for row in help_table.get("rows", [])[:3]]
        != ["0x005018A0", "0x005018B0", "0x005018C0"]
        or [row.get("owner") for row in help_table.get("rows", [])[:3]]
        != ["annalist-onboarding", "fomentius-onboarding", "luthacus-onboarding"]
    ):
        raise StaticReTestFailure("native profile help rows or corrected Fomentius owner drifted")
    callout = catalog.get("pristine_callout", {})
    if (
        callout.get("target_type_id") != 5003
        or callout.get("arrow") != {
            "atlas": "UI", "record": 28, "offset": [15, -65], "rotation_degrees": 200,
        }
        or callout.get("text", {}).get("value") != "WALK INTO WIZARDS\nTO TALK TO THEM"
        or callout.get("text", {}).get("group") != 1
        or callout.get("text", {}).get("rgba") != [0.85, 0.73, 0.44, 1.0]
    ):
        raise StaticReTestFailure("native pristine-profile walk-to-talk callout drifted")
    doc = _read(NPC_INTERACTIONS_DOC_PATH, "native Hub NPC interaction report is absent")
    _require_tokens(
        doc,
        (
            "The former Hagatha attribution was wrong",
            "Fomentius",
            "WALK INTO WIZARDS\\nTO TALK TO THEM",
            "fixed_tick % 80 > 40",
            "Chat` constructor `0x004F5D90` sets `DAT_008199F0`",
            "profile `+0xCC[10]` as ids `0..9`",
            "`SAY_EULOGY_<live portrait id>`",
            "### First story Office admission subset",
            "ARCH_INTRO_0",
            "POLISHER_INTRO_0",
            "dynamic_sounds/wipeglass.wav",
        ),
        "native NPC report lost marker ownership, onboarding, Chat order, or live Painting ids",
    )
    return "all native Hub NPC marker banks, actors, help rows, and onboarding branches are pinned"

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


def test_native_hub_trader_ui_family_and_inventory_capture_are_pinned() -> str:
    doc = _read(DOC_PATH, "the native hub/trader UI implementation contract is absent")
    raw_catalog = _read(
        TRADER_CATALOG_PATH,
        "the machine-readable native hub/trader catalog is absent",
    )
    try:
        catalog = json.loads(raw_catalog)
    except json.JSONDecodeError as exc:
        raise StaticReTestFailure(
            f"the native hub/trader catalog is not reviewable JSON: {exc}"
        ) from exc
    if catalog.get("schema_version") != 9:
        raise StaticReTestFailure("hub/trader consumers lost the complete UI-family schema")
    if catalog.get("source", {}).get("sha256") != EXPECTED_RETAIL_SHA256:
        raise StaticReTestFailure("hub/trader UI provenance no longer names retail 0.72.5")

    interaction = catalog.get("interaction", {})
    potion_belt = interaction.get("potion_belt", {})
    if (
        potion_belt.get("input_owner") != "0x005CB360"
        or potion_belt.get("action_owner") != "0x005D8120"
        or potion_belt.get("refresh_owner") != "0x005D50E0"
        or potion_belt.get("health", {}).get("zero_based_slot") != 3
        or potion_belt.get("health", {}).get("wasd_default_key") != "3"
        or potion_belt.get("mana", {}).get("zero_based_slot") != 4
        or potion_belt.get("mana", {}).get("wasd_default_key") != "4"
        or potion_belt.get("accepted_use_dispatcher") != "0x0056D1B0"
    ):
        raise StaticReTestFailure("native Health/Mana belt ownership or defaults drifted")
    rail = interaction.get("hub_shortcut_rail", {})
    if (
        rail.get("render_owner") != "0x00500250"
        or rail.get("action_owner") != "0x005D8120"
        or rail.get("region_dispatcher") != "0x00514A20"
        or rail.get("service_distance_gate") is not False
        or rail.get("members") != [
            {"order": 0, "id": "annalist", "control_offset": "0xF68", "level_picker_record": 0, "stock_action": "diagnostic log Annalist?"},
            {"order": 1, "id": "hagatha", "control_offset": "0x101C", "level_picker_record": 6, "stock_action": "open HAGATHA'S CHARMS AND CURSES"},
            {"order": 2, "id": "luthacus", "control_offset": "0x10D0", "level_picker_record": 4, "stock_action": "open LUTHACUS' SCAVENGED GOODS"},
            {"order": 3, "id": "fomentius", "control_offset": "0x1184", "level_picker_record": 5, "stock_action": "open FOMENTIUS' USEFUL THYNGS"},
            {"order": 4, "id": "shlorio", "control_offset": "0x1238", "level_picker_record": 2, "stock_action": "open SHLORIO'S DISCOUNT DOWSING"},
        ]
    ):
        raise StaticReTestFailure("five-member native Hub shortcut rail drifted")

    ui = catalog.get("ui")
    if not isinstance(ui, dict):
        raise StaticReTestFailure("hub/trader catalog lost its UI ownership section")
    transaction_audio = catalog.get("transaction_audio")
    if not isinstance(transaction_audio, dict) or transaction_audio.get("native_tick_ms") != 10:
        raise StaticReTestFailure("hub/trader transaction audio ownership disappeared")
    assets = transaction_audio.get("assets")
    if not isinstance(assets, dict) or {
        name: (assets.get(name, {}).get("registry_index"), assets.get(name, {}).get("sha256"))
        for name in (
            "click", "backpack_close", "badaction", "dropcoins",
            "openpanel", "distortreality", "pickskill",
        )
    } != {
        "click": (0, "8aeebcfeb69625bee2ee78fe9c63939e6b40edcc89d5facf2c0d35e1b5920307"),
        "backpack_close": (4, "32fa4ca58d0fe1eb967bb50f20dffc0edb98b25ca74c719edc2b70b9e4312319"),
        "badaction": (6, "0ca71924473e6a45156f0dbd450ff7a158d39015179697c83c7b04824e3256d6"),
        "dropcoins": (25, "b72d44080d99fdae8e7dce83b5f1b6a553d503a753df2deacea7ee8829ba4376"),
        "openpanel": (64, "637a76288c852d813921c7789b211f573f88c56d6036e2e1f3e1cf558f0ae743"),
        "distortreality": (23, "3fa59accc564838ea1896f95539ee0acecd9345c3e2c1adceaadee0dd870194e"),
        "pickskill": (1, "494d1b973bd3f319199199ec9cf851491caee10c3d72dbe61acda69d28daabe4"),
    }:
        raise StaticReTestFailure("exact hub/trader sound registry assets drifted")
    if {
        name: (assets.get(name, {}).get("registry_index"), assets.get(name, {}).get("sha256"))
        for name in ("fizzle", "unforge")
    } != {
        "fizzle": (32, "938420950d859ebc00a9b1a37e548c7c2183a8504689b32aab3de3c683899e76"),
        "unforge": (100, "173db629737f50f3a958358dc9f88fb3b25528ee93298f2f95416517747fa9e2"),
    } or transaction_audio.get("unforge") != {
        "success": {"sound": "unforge", "function": "0x005D6DF0", "member_offset": "0x1148"},
        "failure": {"sound": "fizzle", "function": "0x005D6DF0", "member_offset": "0x598"},
    }:
        raise StaticReTestFailure("unforge success/failure audio ownership drifted")
    if transaction_audio.get("ordinary_purchase") != {
        "success": {"call_site": "0x0056C10E", "sound": "dropcoins"},
        "rejected": {"call_site": "0x0056C1A6", "sound": "badaction"},
        "activation_click_before_callback": "0x0055F054",
    }:
        raise StaticReTestFailure("ordinary purchase click/outcome sequencing drifted")
    if transaction_audio.get("teardown", {}).get("standalone_inventory_open") != {
        "sound": None,
        "keyboard_call_site": "0x005CB3A3",
        "hud_call_site": "0x005D8165",
        "opener": "0x005C6F10",
        "constructor": "0x00560380",
    }:
        raise StaticReTestFailure("silent InventoryScreen open ownership drifted")
    dowsing_audio = transaction_audio.get("dowsing_roll", {})
    if (
        dowsing_audio.get("rng_order_prefix")
        != ["Float(0.1,false) for distortion pitch", "Integer(2) for offer count"]
        or dowsing_audio.get("echo", {}).get("tick_offsets") != [0, 25, 50, 75]
        or dowsing_audio.get("echo", {}).get("gains") != [1.0, 0.25, 0.0625, 0.015625]
        or dowsing_audio.get("distortion", {}).get("pitch") != "0.8 + Float(0.1,false)"
        or transaction_audio.get("dowsing_purchase", {}).get("rng_order_suffix")
        != ["Integer(10) for next fee", "Float(0.1,false) for distortion pitch"]
        or transaction_audio.get("dowsing_purchase", {}).get("distortion", {}).get("pitch")
        != "1.0 + Float(0.1,false)"
    ):
        raise StaticReTestFailure("dowsing SoundEcho, distortion, or RNG ordering drifted")
    inventory = ui.get("inventory_screen")
    shops = ui.get("shop_family")
    hagatha = ui.get("hagatha_perk_pane")
    dowsing = ui.get("dowsing_presentation")
    dialogue = ui.get("dialogue")
    if any(not isinstance(member, dict) for member in (inventory, shops, hagatha, dowsing, dialogue)):
        raise StaticReTestFailure("inventory, shop, subclass, or Chat membership disappeared")
    if (
        ui.get("stage_pixels") != [1600, 900]
        or ui.get("coordinate_space")
        != "direct 1600x900 stage pixels; no 1280x720 conversion"
    ):
        raise StaticReTestFailure("native hub UI direct-stage geometry drifted")
    if (
        inventory.get("backpack_columns"),
        inventory.get("backpack_rows"),
        inventory.get("backpack_authored_cells"),
    ) != (22, 4, 88):
        raise StaticReTestFailure("inventory no longer retains the recovered 22 by 4 grid")
    if inventory.get("backpack_fill_order") != "column-major: index / 4 selects x; index % 4 selects y":
        raise StaticReTestFailure("inventory no longer retains the recovered column-major slot order")
    if (
        inventory.get("backpack_slot_center_origin") != [60, 532]
        or inventory.get("backpack_slot_visible_origin") != [24, 496]
        or inventory.get("backpack_slot_pitch") != [75, 75]
        or inventory.get("backpack_slot_extent") != [72, 72]
        or inventory.get("backpack_slot_rgba") != [1.0, 1.0, 1.0, 0.4]
        or inventory.get("stats_content_rect") != [103, 89, 320, 320]
        or inventory.get("equip_content_rect") != [1177, 89, 320, 320]
    ):
        raise StaticReTestFailure("InventoryScreen live-draw geometry drifted")
    if inventory.get("mode_geometry") != {
        "companion": {
            "left_content_rect": [103, 89, 320, 320],
            "right_content_rect": [1177, 89, 320, 320],
            "player_preview": False,
        },
        "standalone": {
            "left_content_rect": [50, 89, 320, 320],
            "right_content_rect": [1230, 89, 320, 320],
            "player_preview": {
                "center": [800, 249],
                "heading_index": 9,
                "heading_degrees": 135,
                "scale": 1.25,
            },
        },
    }:
        raise StaticReTestFailure("standalone and companion InventoryScreen geometry drifted")
    if inventory.get("starter_loadout") != {
        "constructor": "0x005CFA80",
        "recipe_uid": 0,
        "equipment": {
            "hat": {"name": "Hat", "native_type_id": 7005, "icon_records": [34, 38]},
            "robe": {"name": "Robe", "native_type_id": 7006, "icon_records": [64, 67]},
            "weapon": {"name": "Staff", "native_type_id": 7004, "icon_records": [72]},
        },
        "backpack": [
            {"slot": 0, "name": "Health Potion", "native_type_id": 7001, "native_subtype": 0},
            {"slot": 1, "name": "Mana Potion", "native_type_id": 7001, "native_subtype": 1},
        ],
        "visual_lane_aliases": {
            "primary": "hat",
            "secondary": "robe",
            "attachment": "weapon",
            "hand_boxes": ["weapon", "weapon"],
        },
        "equipment_color_source": "current wizard appearance primary color plus white secondary",
    }:
        raise StaticReTestFailure("InventoryScreen lost the stock five-object starter loadout")
    if inventory.get("item_icon_render_contract") != {
        "scale": "natural atlas logical size; no fit-to-cell scaling",
        "ring": {"render": "0x005788B0", "translation": [0, 0], "rotation_degrees": 0},
        "amulet": {
            "render": "0x00578910",
            "translation": [0, -5],
            "rotation_degrees": 0,
            "layer_order": ["shared record 30 or 31", "recipe-specific record 18 through 29"],
        },
        "staff": {
            "render": "0x00578A90",
            "translation": [-22.94306, 32.76608],
            "rotation_degrees": 35,
            "matrix": [0.81915, 0.57358, -0.57358, 0.81915, -22.94306, 32.76608],
        },
        "hat": {"render": "0x005779B0", "translation": [0, 0], "rotation_degrees": 0},
        "robe": {"render": "0x00577B90", "translation": [0, 0], "rotation_degrees": 0},
        "wand": {
            "render": "0x00579720",
            "translation": [0, 0],
            "rotation_degrees": 45,
            "matrix": [0.70711, 0.70711, -0.70711, 0.70711, 0, 0],
        },
        "recipe_color_source": ["effective_color1", "effective_color2"],
        "recipe_color_consumers": ["hat", "robe"],
        "untinted_classes": ["ring", "amulet", "staff", "wand"],
        "recipe_color_catalog": "docs/reverse-engineering/native-item-catalog.json",
        "null_recipe_color": "native white default",
    }:
        raise StaticReTestFailure("equipment item icon transforms, scale, or tint ownership drifted")
    if inventory.get("primary_spell_pane") != {
        "owner": "0x00562520",
        "field_offsets": {
            "name": "+0x4B0",
            "damage": "+0x4D0",
            "mana_cost": "+0x508",
            "mana_heal": "+0x55C",
        },
        "format_strings": ["damage: %s", "mana cost: %s", "mana heal: %s"],
        "heading_text_baseline_y": 226,
        "heading_glyph_visible_y": [215, 226],
        "content_text_baseline_y": [251, 273, 286, 299],
        "content_glyph_visible_y": [[239, 253], [259, 274], [273, 287], [286, 300]],
        "content_baseline_gaps": [22, 13, 13],
        "heading_font_logical_size": [26, 26],
        "content_font_logical_size": [32, 32],
        "content_glyph_scale": 1.0,
        "content_horizontal_advance_scale": 0.9,
        "content_text_left": {"standalone": 95, "companion": 148},
        "content_first_visible_x": {"standalone": 96, "companion": 149},
        "settled_glyph_peak_rgb": [200, 243, 243],
        "standalone_heading_rect": [86, 207, 227, 24],
        "standalone_body_rect": [86, 230, 227, 79],
        "companion_x_shift": 53,
        "inline_unit_suffix": {
            "builder": "0x00663B30",
            "source_addresses": ["0x007A0190", "0x007A0214", "0x007A0294"],
            "texts": [" / SEC", " / SECOND"],
            "scale": 0.7,
            "horizontal_advance_scale": 0.63,
            "offset": [0, 1],
            "italic": True,
        },
        "panel_contract": "separate adjoining opaque heading and body rectangles; never one merged rectangle",
    }:
        raise StaticReTestFailure("PRIMARY SPELL ExactText geometry or inline-unit styling drifted")
    equipment_sinks = inventory.get("equipment_sink_render_contract")
    if not isinstance(equipment_sinks, dict) or (
        equipment_sinks.get("owner") != "0x00561300"
        or equipment_sinks.get("rect_builder") != "0x005504D0"
        or equipment_sinks.get("painter") != "0x00575450"
        or equipment_sinks.get("item_render_dispatch") != "item vtable +0x0C"
        or equipment_sinks.get("owner_offsets")
        != {
            "hat": "+0x18",
            "robe": "+0x1C",
            "ring0": "+0x20",
            "ring1": "+0x24",
            "ring2": "+0x28",
            "amulet": "+0x2C",
            "weapon": "+0x30",
        }
        or equipment_sinks.get("sink_sizes")
        != {"normal": [72, 72], "small_flag_0x14": [46, 46], "tall_flag_0x15": [72, 108]}
        or equipment_sinks.get("opaque_interior_rgba") != [0.1, 0.1, 0.09, 1.0]
        or equipment_sinks.get("opaque_interior_painter") != "0x0041DD70"
        or equipment_sinks.get("tall_frame")
        != {"wrapper": "0x004A2FF0", "nine_slice": "0x004153B0", "outline_only": True}
        or equipment_sinks.get("tall_item_clip_flag")
        != "DAT_00819E5E = 1 around item vtable +0x0C"
        or equipment_sinks.get("companion_sinks")
        != {
            "hat": {"center": [1337, 179], "rect": [1301, 143, 72, 72], "frame": "Inventory.10"},
            "robe": {"center": [1337, 277], "rect": [1301, 223, 72, 108], "frame": "tall primitive"},
            "weapon_left": {"center": [1257, 259], "rect": [1221, 223, 72, 72], "frame": "Inventory.10"},
            "weapon_right": {"center": [1417, 259], "rect": [1381, 223, 72, 72], "frame": "Inventory.10"},
            "amulet": {"center": [1270, 192], "rect": [1247, 169, 46, 46], "frame": "Inventory.9"},
            "ring0": {"center": [1270, 326], "rect": [1247, 303, 46, 46], "frame": "Inventory.9"},
            "ring1": {"center": [1404, 326], "rect": [1381, 303, 46, 46], "frame": "Inventory.9"},
            "ring2_locked": {"center": [-9999, -9999], "rect": [-10022, -10022, 46, 46], "frame": "Inventory.9"},
        }
        or equipment_sinks.get("item_clip_owners")
        != ["backpack", "storage", "StoreGrid", "dowsing result grid", "equipment sink"]
        or equipment_sinks.get("unclipped_owner") != "InventoryDragger"
        or equipment_sinks.get("accepting_highlight")
        != "compatible equipment sinks are green only while a backpack object is held"
    ):
        raise StaticReTestFailure("equipment sink geometry, clipping, or painter ownership drifted")
    interaction = inventory.get("interaction_contract")
    if not isinstance(interaction, dict):
        raise StaticReTestFailure("InventoryScreen lost its native input-object ownership")
    if (
        interaction.get("selection_owner") != "InventoryGrid"
        or interaction.get("pointer_press") != "0x0056F760"
        or interaction.get("pointer_release") != "0x0056FC90"
        or interaction.get("drag_threshold_pixels") != 10
        or interaction.get("double_activation_window_native_ticks") != 50
        or interaction.get("double_activation_window_ms_at_100_hz") != 500
    ):
        raise StaticReTestFailure("InventoryScreen press, release, or double-activation timing drifted")
    potion_use = interaction.get("potion_use")
    if not isinstance(potion_use, dict) or (
        potion_use.get("dispatcher") != "0x0056D1B0"
        or potion_use.get("accepted_sound_call_site") != "0x0056D246"
        or potion_use.get("accepted_sound_registry_index") != 24
        or potion_use.get("accepted_sound_registry_member_offset") != "0x438"
        or potion_use.get("accepted_sound_path") != "sounds\\drink"
        or potion_use.get("accepted_sound_sha256")
        != "61fdcc02a31b1c1c43264cb6ed8d02717e9dba2c5123167ad6e309053e28f322"
        or potion_use.get("subtypes") != {
            "0": {"effect": "set current health to maximum"},
            "1": {"effect": "set current mana to maximum"},
            "2": {
                "effect": "quadruple all attack damage",
                "duration_native_ticks": 6000,
                "duration_seconds": 60,
            },
            "3": {
                "effect": "clear poison and grant poison immunity",
                "duration_native_ticks": 1000,
                "duration_seconds": 10,
            },
            "4": {
                "effect": "grant concentration of all skills at once",
                "duration_native_ticks": 6000,
                "duration_seconds": 60,
            },
            "5": {"effect": "set current health and mana to maximum"},
        }
        or potion_use.get("accepted_stack_mutation")
        != "decrement exactly one; remove and destroy the live item when the stack reaches zero"
    ):
        raise StaticReTestFailure("native potion double-activation dispatcher or effect table drifted")
    item_info = interaction.get("item_info")
    if not isinstance(item_info, dict) or (
        item_info.get("owner") != "ItemInfo"
        or item_info.get("vtable") != "0x007946A4"
        or item_info.get("constructor") != "0x00553B80"
        or item_info.get("render") != "0x005C3A60"
        or item_info.get("content_builder") != "0x0057C4B0"
        or item_info.get("initial_delay_native_ticks") != 20
        or item_info.get("content_wrap_width") != 300
        or item_info.get("content_margin") != 25
        or item_info.get("equipment_without_recipe") != "name only"
        or item_info.get("equipment_catalog_membership")
        != {"recipes": 47, "sets": 7, "item_and_set_fx": 86}
        or item_info.get("potion_instruction") != "Double-click to drink"
        or item_info.get("potion_copy") != {
            "health-potion": "Restores your health to maximum",
            "mana-potion": "Restores your mana to maximum",
            "wizard-chug": "Quadruples the damage of all attacks for 60 seconds",
            "antidote": "Cures poisoning and grants immunity to poison for 10 seconds",
            "mind-chug": "Grants concentration of all skills (at once) for 60 seconds",
            "rejuvenation-potion": "Restores your health and mana to maximum",
        }
    ):
        raise StaticReTestFailure("ItemInfo ownership, delay, or complete potion copy drifted")
    store_hover = interaction.get("store_grid_hover")
    if not isinstance(store_hover, dict) or (
        store_hover.get("owner") != "StoreGrid"
        or store_hover.get("constructor") != "0x0055C740"
        or store_hover.get("vtable") != "0x00794B8C"
        or store_hover.get("hover_slot") != "+0xCC"
        or store_hover.get("hover_handler") != "0x0055E2C0"
        or store_hover.get("hover_box_field") != "StoreGrid+0x110"
        or store_hover.get("hover_box_constructor") != "0x005C38F0"
        or store_hover.get("hover_box_vtable") != "0x0079AE14"
        or store_hover.get("hover_box_render") != "0x005C3A60"
        or store_hover.get("hover_box_destructor") != "0x005C39B0"
        or store_hover.get("horizontal_layout") != "0x005AADE0"
        or store_hover.get("vertical_layout") != "0x005AB060"
        or store_hover.get("initial_delay_native_ticks") != 0
        or store_hover.get("audio") is not None
        or store_hover.get("content_builder") != "item vtable +0x2C"
        or store_hover.get("content_wrap_width") != 300
        or store_hover.get("content_margin") != 25
        or store_hover.get("source_gap") != 35
        or store_hover.get("source_exclusion_size") != 70
        or store_hover.get("current_item_field") != "StoreGrid+0xF8"
        or store_hover.get("selected_item_field") != "StoreGrid+0xFC"
        or store_hover.get("previous_selection_field") != "StoreGrid+0x100"
        or store_hover.get("pointer_current_handler")
        != "0x0055CEE0; invokes vtable +0xCC only when current item changes"
        or store_hover.get("pointer_press_handler")
        != "0x00565D40 -> 0x0055D680; changes selection without changing current item or invoking vtable +0xCC"
        or store_hover.get("selected_ordinary_item")
        != "remains kind zero; existing HoverBox survives first click and normal details rebuild on selected-cell re-entry"
        or store_hover.get("kind_one_special_item")
        != "separate dormant special-row variant; no retail Shop producer; diagnostic literal Hover over special item! and no HoverBox"
        or store_hover.get("price_branch") != {
            "owner_flag": "Shop+0x289",
            "enabled_for": ["Shop", "PerkShop", "DowsingShop"],
            "disabled_for": ["InventoryShop"],
            "format": "    Price: %d",
        }
        or store_hover.get("perk_shop_suffix") != {
            "vtable_slot": "Shop+0xC0",
            "builder": "0x00554690",
            "bundle": "    Bulk discount: 50%",
            "first_mix": "    High price due to first mixing.",
        }
        or store_hover.get("teardown") != [
            "current-cell change",
            "pointer exit",
            "purchase rebuild",
            "service close",
        ]
    ):
        raise StaticReTestFailure("StoreGrid HoverBox ownership, copy, or geometry drifted")
    owned_perk_hover = interaction.get("hagatha_owned_perk_hover")
    if not isinstance(owned_perk_hover, dict) or (
        owned_perk_hover.get("owner") != "InventoryScreen pointer handler"
        or owned_perk_hover.get("handler") != "0x0056FC90"
        or owned_perk_hover.get("current_index_field") != "InventoryScreen+0x5CC"
        or owned_perk_hover.get("source")
        != "progression selector list/count +0x7C0/+0x7C4"
        or owned_perk_hover.get("grid") != {
            "columns": 3,
            "rows": 3,
            "cell_size": 60,
            "order": "row-major occupied entries only",
        }
        or owned_perk_hover.get("temporary_item_constructor") != "0x00550490"
        or owned_perk_hover.get("content_builder") != "0x00573E90"
        or owned_perk_hover.get("initial_delay_native_ticks") != 0
        or owned_perk_hover.get("audio") is not None
        or owned_perk_hover.get("content_margin") != 25
        or owned_perk_hover.get("source_gap") != 25
        or owned_perk_hover.get("source_exclusion_size") != 60
        or owned_perk_hover.get("empty_cells") != "no hit target and no HoverBox"
        or owned_perk_hover.get("bundle_art")
        != "decorative; no owned-pane HoverBox"
    ):
        raise StaticReTestFailure("Hagatha owned-perk HoverBox ownership or geometry drifted")
    dragger = interaction.get("dragger")
    if not isinstance(dragger, dict) or {
        key: dragger.get(key)
        for key in ("owner", "vtable", "constructor", "update", "render", "pointer_move", "pointer_release")
    } != {
        "owner": "InventoryDragger",
        "vtable": "0x00794294",
        "constructor": "0x00550990",
        "update": "0x0056E950",
        "render": "0x005579A0",
        "pointer_move": "0x0055E030",
        "pointer_release": "0x0056EC30",
    }:
        raise StaticReTestFailure("InventoryDragger lifecycle ownership drifted")
    unforge = interaction.get("unforge")
    if not isinstance(unforge, dict) or (
        unforge.get("owner") != "InventoryDragger backpack-source lower-boundary release"
        or unforge.get("type_gate") != "0x00550450"
        or unforge.get("transaction") != "0x005D6DF0"
        or unforge.get("target_rect") != [1500, 800, 100, 100]
        or unforge.get("target_record")
        != {"atlas": "UI", "record": 75, "center": [1562, 868]}
        or unforge.get("target_red_multiplier")
        != "sin(native_tick * pi / 180) * 0.2 + 0.6"
        or unforge.get("click_action") is not None
        or unforge.get("eligible_native_type_ids")
        != [7002, 7003, 7004, 7005, 7006, 7008, 7011]
        or unforge.get("ineligible_native_type_ids")
        != [7000, 7001, 7009, 7010, 7012]
        or unforge.get("nonempty_sack") != "restore without mutation"
        or unforge.get("empty_sack")
        != "skip confirmation and transmute to Integer(4)+2 gold"
        or unforge.get("recipe_less_equipment")
        != "confirm, then transmute to Integer(4)+2 gold"
    ):
        raise StaticReTestFailure("Inventory unforge target, type gate, or source ownership drifted")
    if unforge.get("confirmation") != {
        "title": "REALLY UNFORGE THIS?",
        "body": "Unforging grants you a permanent small bonus to your stats, but utterly destroys the item.",
        "primary_button": "unforge",
        "secondary_button": "cancel",
    } or unforge.get("message_box_layout") != {
        "line_builder": "0x005BCCB0",
        "widest_line_field": "+0x80",
        "finalizer": "MsgBox vtable +0xB4 -> 0x005AB2C0",
        "center_x": 801.5,
        "inner_width": "max(rendered line widths) + 141",
        "confirmation_reference_rect": [544.5, 387.5, 514, 326],
        "staff_result_reference_rect": [606.5, 396.5, 390, 308],
        "result_rule": "measure title in menu font and summary/outcome in medium font; keep every result line unwrapped",
    } or unforge.get("recipe_selector") != {
        "attempt_count_field": "+0x874",
        "bound": "count < 5 ? 7 : count + 3",
        "overflow": "selected > 7 and Integer(6) == 3 redirects to gold; other values fizzle",
        "retry_rows": [
            "full rejuvenation while already full through count 5",
            "Mind Dredge unless Integer(100) == 25",
        ],
    }:
        raise StaticReTestFailure("Inventory unforge confirmation or selector loop drifted")
    expected_unforge_outcomes = [
        {"selector": 0, "kind": "full_rejuvenation", "text": "Full rejuvenation", "mutation": "restore HP/MP and zero global plus category-2 cooldowns"},
        {"selector": 1, "kind": "offensive_damage", "text": "+%d damage for all offensive spells", "field": "+0x84", "early_values": [1, 2], "late_values": [1]},
        {"selector": 2, "kind": "mana_cost", "text": "-%d mana cost for all spells", "field": "+0x88", "early_values": [1, 2], "late_values": [1]},
        {"selector": 3, "kind": "mind_dredge", "text": "Transmuted to Mind Dredge (+1 skill points at next level)", "field": "+0x48", "chance": "Integer(100) == 25"},
        {"selector": 4, "kind": "maximum_health", "text": "+%d to maximum health", "field": "+0x6C", "early_values": [10], "late_values": [5, 10]},
        {"selector": 5, "kind": "maximum_mana", "text": "+%d to maximum mana", "field": "+0x78", "early_values": [20], "late_values": [10, 20]},
        {"selector": 6, "kind": "experience", "text": "+%d%% faster experience gain", "field": "+0x8C", "early_values": [5, 10], "late_values": [1, 2]},
        {"selector": 7, "kind": "gold", "text": "Transmuted to %d gold coins", "values": [10, 20, 30, 40, 50, 60]},
    ]
    if unforge.get("outcomes") != expected_unforge_outcomes or unforge.get(
        "destructive_failure"
    ) != {
        "title": "FAILED UNFORGING!",
        "body": ["Spellbreaking fizzles!", "No bonus"],
        "item_destroyed": True,
    }:
        raise StaticReTestFailure("Inventory unforge authored outcome table drifted")
    if interaction.get("luthacus_inventory_shop") != {
        "callback": "0x0056CD00",
        "backpack_second_activation": "ordinary InventoryScreen use or equip",
        "backpack_to_storage": "drag only",
        "storage_to_backpack": ["second activation", "drag"],
        "valid_drop": "only the opposite owner",
        "invalid_drop": "restore the same source object without mutation",
    }:
        raise StaticReTestFailure("Luthacus asymmetric drag and activation ownership drifted")
    if interaction.get("service_companion_inventory") != {
        "dispatcher": "0x00514A20",
        "services": ["Shop", "PerkShop", "InventoryShop", "DowsingShop pre-roll", "DowsingShop result"],
        "relationship": "an independently allocated InventoryScreen remains attached beneath every service overlay",
        "selection_owners": ["service Shop grid", "companion InventoryGrid", "InventoryShop storage grid"],
        "post_purchase": {
            "ordinary_0x0056BF70": "debit, remove Shop object, insert the same live object through 0x0055FF20, invoke InventoryScreen vtable +0xB4 rebuild",
            "dowsing_0x0056D110": "use ordinary purchase before fee reroll and flash",
            "perk_0x0056C340": "apply and remove perk offer, then rebuild the charm pane without backpack insertion",
        },
        "companion_actions_while_service_open": [
            "select",
            "ItemInfo after 20 ticks",
            "same-object second activation within 50 ticks",
            "drag",
            "equip",
            "unequip",
        ],
    }:
        raise StaticReTestFailure("service companion InventoryScreen ownership or purchase rebuild drifted")
    required_clothing = interaction.get("required_clothing")
    if not isinstance(required_clothing, dict) or (
        required_clothing.get("hat", {}).get("title")
        != "A WIZARD WOULD NEVER REMOVE HIS HAT!"
        or required_clothing.get("robe", {}).get("title")
        != "A WIZARD WOULD NEVER REMOVE HIS ROBE!"
        or required_clothing.get("hat", {}).get("primary_button") != "OKAY"
        or required_clothing.get("robe", {}).get("primary_button") != "OKAY"
        or required_clothing.get("direct_removal")
        != "reject, restore the equipped object, and open MsgBox"
    ):
        raise StaticReTestFailure("mandatory Hat/Robe release branches drifted")
    trace = inventory.get("live_draw_trace")
    if not isinstance(trace, dict) or (
        trace.get("hooked_draw_functions") != ["0x004142E0", "0x004143D0", "0x00414540"]
        or trace.get("settled_first_frame_draw_count") != 481
        or trace.get("client_pixels") != [1600, 900]
    ):
        raise StaticReTestFailure("InventoryScreen live draw-call provenance disappeared")
    if (
        shops.get("ordinary_columns"),
        shops.get("ordinary_rows"),
        shops.get("ordinary_retained_capacity"),
    ) != (7, 4, 28):
        raise StaticReTestFailure("ordinary Shop lost its complete 7 by 4 StoreGrid")
    if shops.get("background_tile_repeat") != [4, 2]:
        raise StaticReTestFailure("ordinary Shop lost its distinct 4 by 2 background tiling pass")
    if shops.get("background_color") != {"red": 0.85, "green": 1.0, "blue": 0.85}:
        raise StaticReTestFailure("ordinary Shop background color modulation drifted")
    if (
        shops.get("price_font_logical_size") != [26, 26]
        or shops.get("price_text_baseline_offset_from_slot_visible_top") != 67
        or shops.get("first_row_price_glyph_visible_y") != [113, 124]
        or shops.get("first_column_price_glyph_right_edge_x") != 605
    ):
        raise StaticReTestFailure("ordinary Shop price font or traced glyph placement drifted")
    if (
        shops.get("constructor_layout_argument") != [215, -20, 604, 400]
        or shops.get("settled_stage_rect") != [498, -20, 604, 430]
        or shops.get("grid_slot_center_origin") != [575, 92.5]
        or shops.get("grid_slot_visible_origin") != [539, 56.5]
        or shops.get("grid_slot_pitch") != [75, 75]
        or shops.get("grid_slot_extent") != [72, 72]
        or shops.get("grid_slot_rgba") != [1.0, 1.0, 1.0, 0.6]
        or shops.get("slide_owner")
        != "Shop::Update 0x00550D80; DowsingShop override 0x005512F0"
        or shops.get("slide_formula")
        != "root_y = -20 - (1 - attached_inventory_reveal) * 100"
        or shops.get("slide_easing") != "linear fixed-tick; no easing curve"
        or shops.get("reveal_step_per_native_tick") != 0.025
        or shops.get("native_tick_hz") != 100
    ):
        raise StaticReTestFailure("common Shop settled root or exact StoreGrid geometry drifted")
    if shops.get("done_detail_visible_rects") != {
        "UI.72": [714.5, 358, 171, 58],
        "UI.12": [732.5, 361.5, 135, 47],
        "UI.86": [737, 366, 126, 38],
    }:
        raise StaticReTestFailure("common Shop DONE/detail stack geometry drifted")
    if shops.get("done_detail_color_pass") != {
        "UI.72_rgba": [1.0, 1.0, 1.0, 1.0],
        "UI.12_rgba": [1.0, 1.0, 1.0, 0.85],
        "UI.86_rgba": [0.75, 1.0, 0.75, 1.0],
        "DONE_text_rgba": [1.0, 1.0, 1.0, 1.0],
        "alpha_basis": "each alpha is multiplied by the service root alpha",
    }:
        raise StaticReTestFailure("common Shop DONE/detail renderer-state pass drifted")
    if (
        shops.get("title_glyph_visible_y") != [14, 34]
        or shops.get("title_text_baseline_y") != 32
        or shops.get("done_text_visible_rect") != [760, 374, 80, 20]
        or shops.get("done_text_baseline_y") != 392
    ):
        raise StaticReTestFailure("common Shop title or DONE text placement drifted")
    if shops.get("activation") != "first activation selects; activating the same selected cell invokes the subclass callback":
        raise StaticReTestFailure("shop selection and second-activation dispatch drifted")
    if (
        shops.get("affordable_price_rgba") != [0.85, 0.73, 0.44, 1.0]
        or shops.get("unaffordable_price_rgba") != [1.0, 0.5, 0.5, 1.0]
        or shops.get("shared_gold_hex") != "#D9BA70"
        or shops.get("background_composite_passes") != ["normal", "additive"]
        or shops.get("background_tile_extent") != [264, 264]
        or shops.get("background_clip_rect") != [498, -20, 604, 400]
        or shops.get("background_blend_state_field") != "RenderContext+0x3F1"
        or shops.get("background_blend_state_apply") != "0x004208A0"
    ):
        raise StaticReTestFailure("shop color or duplicate background composite passes drifted")
    if ui.get("dowsing_retained_capacity") != 9 or ui.get("dowsing_columns") != 3:
        raise StaticReTestFailure("DowsingShop lost its complete 3 by 3 result family")
    if ui.get("dowsing_states") != [
        "pre-roll",
        "result",
        "insufficient-funds-msgbox",
        "roll-flash",
        "purchase-flash",
    ]:
        raise StaticReTestFailure("DowsingShop state membership drifted")
    if hagatha != {
        "owner": "companion InventoryScreen left pane",
        "outer_content_rect": [103, 89, 320, 320],
        "title": "CHARMS/CURSES",
        "title_glyph_visible_rect": [169, 139, 168, 15],
        "title_text_baseline_y": 152.5,
        "title_rgba": [0.85, 0.73, 0.44, 1.0],
        "inner_panel_rect": [139, 129, 227, 238],
        "inner_panel_fill_rgba": [0.1, 0.1, 0.09, 1.0],
        "inner_panel_outline_rgba": [1.0, 1.0, 1.0, 1.0],
        "inner_panel_outline_pixels": 1,
        "inner_panel_background_atlas_record": None,
        "slot_atlas_record": "Inventory.10",
        "slot_visible_origin": [164.2, 169.2],
        "slot_visible_extent": [57.6, 57.6],
        "slot_pitch": [60, 60],
        "slot_scale": 0.8,
        "empty_slot_rgb": [0.5, 0.5, 0.5],
        "occupied_slot_rgb": [1.0, 1.0, 1.0],
        "owned_icon_atlas": "Skills",
        "owned_icon_record": "127 + selector",
        "columns": 3,
        "rows": 3,
        "bundle_atlas_record": "Inventory.5",
        "bundle_visible_rect": [207, 263, 92, 50],
    }:
        raise StaticReTestFailure("Hagatha lost the traced companion InventoryScreen perk pane")
    if dowsing != {
        "pre_roll": {
            "mirror_header_visible_rect": [693, 54.5, 214, 41],
            "reference_drop_rect": [750, 101, 100, 149],
            "button_visible_rect": [623.5, 265.5, 353, 69],
            "button_hit_rect": [675, 265.5, 250, 69],
            "button_side_visible_rects": [[669, 259.5, 70, 85], [861, 259.5, 70, 85]],
            "button_records": {
                "idle_body": 101,
                "pressed_body": 102,
                "fixed_side": 54,
            },
            "pressed_copy_offset": [6, 6],
            "hover_visual_branch": None,
            "button_art_rgba": [1.0, 1.0, 1.0, 1.0],
            "label": "DOWSE",
            "label_text_baseline_y": 302,
            "fee_text_baseline_y": 322.5,
            "label_and_fee_rgba": [0.85, 0.73, 0.44, 1.0],
        },
        "result": {
            "slot_visible_origin": [689, 94],
            "slot_visible_extent": [72, 72],
            "slot_pitch": [75, 75],
            "columns": 3,
            "rows": 3,
            "background_record": "UI.49",
            "background_composite_passes": ["normal", "additive"],
            "background_color": {
                "red": 1.0,
                "green_range": [0.6, 0.8],
                "blue": 1.0,
                "green_formula": "sin(nativeTick * 0.5 * pi / 180) * 0.1 + 0.7",
                "period_native_ticks": 720,
            },
        },
    }:
        raise StaticReTestFailure("DowsingShop pre-roll or result composition drifted")
    if ui.get("dowsing_flash") != {
        "state_field": "DowsingShop+0x360",
        "set_to": 1.0,
        "decrement_per_native_tick": 0.05,
        "duration_native_ticks": 20,
        "duration_ms_at_100_hz": 200,
        "color_rgba": [1.0, 0.0, 0.0, "state_field"],
        "triggers": [
            {
                "event": "accepted dowsing roll",
                "write": "0x0055FD99",
            },
            {
                "event": "accepted dowsing offer purchase after clear, fee reroll, and distortion request",
                "write": "0x0056D194",
            },
        ],
        "non_triggers": [
            "insufficient roll funds",
            "rejected offer purchase",
            "service restore with active offers",
            "selection or hover",
            "Done or range teardown",
        ],
    }:
        raise StaticReTestFailure("DowsingShop red-flash timing or trigger drifted")
    if ui.get("insufficient_gold_msgbox") != {
        "title": "NOT ENOUGH GOLD!",
        "body": "Peering into the mirror at the endless, swirling, impossible colors of the ether is debilitating.  It is unthinkable that anyone would do so without just compensation, plus a little extra.",
        "primary_button": "OKAY",
    }:
        raise StaticReTestFailure("DowsingShop insufficient-gold MsgBox copy drifted")
    if (
        dialogue.get("owner") != "Chat"
        or dialogue.get("vtable") != "0x0079061C"
        or dialogue.get("panel_nine_slice_helper") != "0x00417760"
        or dialogue.get("panel_edge_uv_fraction") != 0.05
        or dialogue.get("panel_center_uv_origin") != [0.95, 0.95]
        or dialogue.get("stage_rect") != [476.5, 26, 647, 420]
        or dialogue.get("content_rect") != [561.5, 111, 477, 250]
        or dialogue.get("corner_centers")
        != [[521, 70.5], [1079, 70.5], [521, 401.5], [1079, 401.5]]
        or dialogue.get("title_text_baseline_y") != 90
        or dialogue.get("primary_choice_text_baseline_y") != 226
        or dialogue.get("secondary_choice_text_baseline_y") != 256
        or dialogue.get("done_text_baseline_y") != 396
        or dialogue.get("default_text_rgba") != [0.85, 0.73, 0.44, 1.0]
        or dialogue.get("primary_action_rgba") != [0.55, 0.75, 0.55, 1.0]
        or dialogue.get("primary_action_scale") != 1.25
        or dialogue.get("fade_step_per_native_tick") != 0.05
        or dialogue.get("curtain_alpha") != 0
        or dialogue.get("normal_scroll_pixels_per_tick") != 0.125
        or dialogue.get("accelerated_scroll_pixels_per_tick") != 0.8
    ):
        raise StaticReTestFailure("trader Chat ownership, geometry, or timing drifted")
    emphasis = dialogue.get("inline_emphasis")
    if (
        not isinstance(emphasis, dict)
        or emphasis.get("source_delimiter") != "*"
        or emphasis.get("exact_text_command_marker") != "_"
        or emphasis.get("command_marker_field") != "ExactText+0x4D414"
        or emphasis.get("italic_command") != "i"
        or emphasis.get("italic_factor_field") != "ExactText+0x4D418"
        or emphasis.get("italic_factor") != 0.125
        or emphasis.get("font_line_height_field") != "ExactText+0xD410"
        or emphasis.get("font_line_height") != 24
        or emphasis.get("glyph_quad_horizontal_delta_pixels") != 3
        or "_iless_i" not in emphasis.get("chat_string_rewrite", "")
    ):
        raise StaticReTestFailure("Chat inline ExactText emphasis ownership or quad shear drifted")
    msgbox = ui.get("msgbox")
    if not isinstance(msgbox, dict) or (
        msgbox.get("owner") != "MsgBox"
        or msgbox.get("vtable") != "0x00788E04"
        or msgbox.get("fade_step_per_native_tick") != 0.035
        or msgbox.get("curtain_alpha_multiplier") != 0.75
        or msgbox.get("horizontal_edge_record") != 10
        or msgbox.get("vertical_edge_record") != 79
        or msgbox.get("background_enabled_field") != "HoverBox+0xB8"
        or msgbox.get("background_enabled_default") is not True
        or msgbox.get("background_enable_write") != "0x005C3957"
        or msgbox.get("background_render_branch") != "0x005C46E5..0x005C4818"
        or msgbox.get("ui_atlas_record_array_base_offset") != "0x38"
        or msgbox.get("ui_atlas_record_stride") != "0xC4"
        or msgbox.get("layout_rect_at_full_alpha") != [560.5, 183, 479, 334]
        or msgbox.get("interior_background_record") != 49
        or msgbox.get("interior_background_object_offset") != "UI atlas+0x25BC"
        or msgbox.get("interior_fill")
        != "repeat UI 49 from the clip top-left and scissor surplus tiles to the clip rectangle"
        or msgbox.get("interior_clip_inflate_pixels") != 25
        or msgbox.get("interior_clip_rect") != [535.5, 158, 529, 384]
        or msgbox.get("interior_visibility")
        != "authored UI 49 obscures the companion InventoryScreen/service inside the clip; the companion remains visible outside it beneath the curtain"
        or msgbox.get("outer_visible_rect") != [522, 145.5, 556, 409]
        or msgbox.get("inner_nine_slice_record") != 17
        or msgbox.get("inner_nine_slice_object_offset") != "UI atlas+0x0D3C"
        or msgbox.get("inner_nine_slice_helper") != "0x00417760"
        or msgbox.get("inner_nine_slice_edge_uv_fraction") != 0.05
        or msgbox.get("inner_nine_slice_inflate_pixels") != 20
        or msgbox.get("inner_visible_rect") != [540.5, 163, 519, 374]
        or msgbox.get("skull_header_visible_rect") != [669, 97, 262, 67]
        or msgbox.get("primary_button_record") != 101
        or msgbox.get("primary_button_pressed_record") != 102
        or msgbox.get("primary_button_visible_rect") != [623.5, 397.5, 353, 69]
        or msgbox.get("primary_button_hit_rect") != [702, 397.5, 196, 69]
        or msgbox.get("primary_button_pressed_copy_offset") != [6, 6]
        or msgbox.get("primary_button_side_visible_rects")
        != [[696, 391.5, 70, 85], [834, 391.5, 70, 85]]
        or msgbox.get("primary_button_art_rgba") != [1.0, 1.0, 1.0, 1.0]
        or msgbox.get("primary_button_text_rgba") != [0.85, 0.73, 0.44, 1.0]
        or msgbox.get("arrow_centers_and_scales")
        != [[800, 592, 1], [725, 579, 0.75], [875, 579, 0.75]]
        or msgbox.get("title_text_baseline_y") != 252
        or msgbox.get("body_text_baseline_y") != 287.5
        or msgbox.get("primary_button_text_baseline_y") != 440
    ):
        raise StaticReTestFailure("dowsing MsgBox ownership, composition, or reveal timing drifted")
    if ui.get("browser_asset_policy", {}).get("visible_html_controls") is not False:
        raise StaticReTestFailure("visible generic HTML controls can replace stock atlas presentation")

    functions = catalog.get("functions")
    required_functions = {
        "shop_update": "0x00550D80",
        "shop_render": "0x00557D40",
        "shop_item_detail_render": "0x00565E00",
        "inventory_screen_render": "0x00568B90",
        "inventory_stats_render": "0x00562520",
        "equipment_pane_render": "0x00561300",
        "equipment_sink_rect": "0x005504D0",
        "equipment_sink_render": "0x00575450",
        "primitive_rect_render": "0x0041DD70",
        "primitive_nine_slice_render": "0x004153B0",
        "tall_sink_frame_render": "0x004A2FF0",
        "inventory_grid_render": "0x0055A070",
        "chat_render": "0x004F9380",
        "chat_update": "0x004FFEE0",
        "chat_action": "0x004FFC40",
        "exact_text_render": "0x0043BCD0",
        "exact_text_command_aware_wrap": "0x0043D230",
        "hoverbox_constructor": "0x005C38F0",
        "msgbox_render": "0x005C4530",
        "ui_panel_render": "0x005C3F40",
        "hagatha_perk_pane_primitive": "0x00550CC0",
        "ordinary_purchase": "0x0056BF70",
        "perk_purchase": "0x0056C340",
        "inventory_transfer": "0x0056CD00",
        "dowsing_purchase": "0x0056D110",
        "dowsing_update": "0x005512F0",
        "dowsing_state_rebuild": "0x0055F9F0",
        "dowsing_render": "0x00558160",
        "dowsing_action": "0x0055FAF0",
        "dowsing_flash_render": "0x00551350",
        "button_hot_rect": "0x00427710",
        "ui_labeled_control_render": "0x005C60F0",
        "dialog_finalize": "0x005AB5C0",
        "inventory_unforge_type_gate": "0x00550450",
        "inventory_unforge_transaction": "0x005D6DF0",
    }
    if not isinstance(functions, dict) or any(
        functions.get(name) != address for name, address in required_functions.items()
    ):
        raise StaticReTestFailure("hub/trader UI ownership or purchase dispatch addresses drifted")

    if not INVENTORY_CAPTURE_PATH.is_file():
        raise StaticReTestFailure("the stock 1600 by 900 inventory visual fixture is absent")
    actual_hash = hashlib.sha256(INVENTORY_CAPTURE_PATH.read_bytes()).hexdigest()
    if actual_hash != EXPECTED_INVENTORY_CAPTURE_SHA256:
        raise StaticReTestFailure("the stock inventory visual fixture no longer matches its reviewed capture")
    png = INVENTORY_CAPTURE_PATH.read_bytes()[:24]
    if png[:8] != b"\x89PNG\r\n\x1a\n" or int.from_bytes(png[16:20], "big") != 1600 or int.from_bytes(png[20:24], "big") != 900:
        raise StaticReTestFailure("the inventory visual fixture lost its exact 1600 by 900 client dimensions")

    raw_capture_manifest = _read(
        TRADER_CAPTURE_MANIFEST_PATH,
        "the stock trader/Chat visual capture manifest is absent",
    )
    try:
        capture_manifest = json.loads(raw_capture_manifest)
    except json.JSONDecodeError as exc:
        raise StaticReTestFailure(
            f"the stock trader/Chat visual capture manifest is not reviewable JSON: {exc}"
        ) from exc
    captures = capture_manifest.get("captures")
    provenance = capture_manifest.get("provenance")
    if (
        capture_manifest.get("schema_version") != 1
        or not isinstance(captures, list)
        or len(captures) != 18
        or not isinstance(provenance, dict)
        or provenance.get("executable_sha256") != EXPECTED_RETAIL_SHA256
        or provenance.get("client_pixels") != [1600, 900]
        or "debugger-instrumented/runtime-staged" not in provenance.get("instrumentation_disclosure", "")
    ):
        raise StaticReTestFailure("stock trader/Chat capture provenance or complete state census drifted")
    required_capture_states = {
        "Fomentius Shop with companion InventoryScreen",
        "Fomentius selected affordable offer",
        "Hagatha PerkShop with companion InventoryScreen",
        "Hagatha selected perk",
        "Luthacus InventoryShop with both containers",
        "Luthacus selected backpack object",
        "Shlorio DowsingShop pre-roll",
        "Shlorio DowsingShop result grid",
        "Shlorio insufficient-gold MsgBox",
        "Fomentius Chat intro",
        "Fomentius Chat question state",
        "Hagatha Chat intro",
        "Hagatha Chat question state",
        "Luthacus Chat intro",
        "Luthacus Chat question state",
        "Shlorio Chat intro",
        "Shlorio Chat question state",
        "Shlorio scrolling price explanation",
    }
    if {capture.get("state") for capture in captures if isinstance(capture, dict)} != required_capture_states:
        raise StaticReTestFailure("stock trader/Chat capture state membership drifted")
    for capture in captures:
        if not isinstance(capture, dict):
            raise StaticReTestFailure("stock trader/Chat capture row is not an object")
        relative_path = capture.get("file")
        expected_hash = capture.get("sha256")
        if not isinstance(relative_path, str) or not isinstance(expected_hash, str):
            raise StaticReTestFailure("stock trader/Chat capture row lost its path or hash")
        capture_path = TRADER_CAPTURE_MANIFEST_PATH.parent / relative_path
        if not capture_path.is_file() or hashlib.sha256(capture_path.read_bytes()).hexdigest() != expected_hash:
            raise StaticReTestFailure(f"stock trader/Chat capture drifted: {relative_path}")
        capture_png = capture_path.read_bytes()[:24]
        if (
            capture_png[:8] != b"\x89PNG\r\n\x1a\n"
            or int.from_bytes(capture_png[16:20], "big") != 1600
            or int.from_bytes(capture_png[20:24], "big") != 900
        ):
            raise StaticReTestFailure(f"stock trader/Chat capture lost 1600 by 900 dimensions: {relative_path}")

    raw_unforge_manifest = _read(
        UNFORGE_CAPTURE_MANIFEST_PATH,
        "the clean-stock Inventory unforge capture manifest is absent",
    )
    try:
        unforge_manifest = json.loads(raw_unforge_manifest)
    except json.JSONDecodeError as exc:
        raise StaticReTestFailure(
            f"the Inventory unforge capture manifest is not reviewable JSON: {exc}"
        ) from exc
    unforge_captures = unforge_manifest.get("captures")
    unforge_provenance = unforge_manifest.get("provenance")
    if (
        unforge_manifest.get("schema_version") != 1
        or not isinstance(unforge_captures, list)
        or len(unforge_captures) != 2
        or not isinstance(unforge_provenance, dict)
        or unforge_provenance.get("executable_sha256") != EXPECTED_RETAIL_SHA256
        or unforge_provenance.get("executable_bytes") != 4_723_200
        or unforge_provenance.get("client_pixels") != [1600, 900]
        or "no loader" not in unforge_provenance.get("runtime", "")
    ):
        raise StaticReTestFailure("clean-stock Inventory unforge provenance drifted")
    actual_unforge_hashes = {
        capture.get("file"): capture.get("sha256")
        for capture in unforge_captures
        if isinstance(capture, dict)
    }
    if actual_unforge_hashes != EXPECTED_UNFORGE_CAPTURE_HASHES:
        raise StaticReTestFailure("clean-stock Inventory unforge capture membership drifted")
    for relative_path, expected_hash in EXPECTED_UNFORGE_CAPTURE_HASHES.items():
        capture_path = UNFORGE_CAPTURE_MANIFEST_PATH.parent / relative_path
        if (
            not capture_path.is_file()
            or hashlib.sha256(capture_path.read_bytes()).hexdigest() != expected_hash
        ):
            raise StaticReTestFailure(f"clean-stock Inventory unforge capture drifted: {relative_path}")
        capture_png = capture_path.read_bytes()[:24]
        if (
            capture_png[:8] != b"\x89PNG\r\n\x1a\n"
            or int.from_bytes(capture_png[16:20], "big") != 1600
            or int.from_bytes(capture_png[20:24], "big") != 900
        ):
            raise StaticReTestFailure(
                f"clean-stock Inventory unforge capture lost 1600 by 900 dimensions: {relative_path}"
            )

    _require_tokens(
        doc,
        (
            "Full stock UI correction and presentation closure",
            "`Shop` | `0x00794D7C`",
            "`PerkShop` | `0x00790374`",
            "`InventoryShop` | `0x0079044C`",
            "`DowsingShop` | `0x00790524`",
            "`InventoryGrid` | `0x00794C64`",
            "`InventoryScreen` | `0x00794F54`",
            "`Chat` | `0x0079061C`",
            "`MsgBox` | `0x00788E04`",
            "seven columns by four rows",
            "22 columns by 4 rows (88 authored slots)",
            "alpha `0.6`",
            "alpha `0.4`",
            "`#D9BA70`",
            "`#FF8080`",
            "`sin(nativeTick * 0.5 * pi / 180) * 0.1 + 0.7`",
            "The UI atlas object array starts at `+0x38` with stride `0xc4`",
            "repeats UI 49 from that clip's top-left",
            "calls native nine-slice helper `0x00417760` with UI 17",
            "renderer helper `0x00417760`",
            "`_c(.55f,.75f,.55f)_s(1.25)`",
            "recipe-UID-0 loadout",
            "translated `(0,-5)`",
            "rotated `+35` degrees",
            "rotated `+45` degrees",
            "`effective_color1` and `effective_color2`",
            "`InventoryScreen::PointerPress` at `0x0056f760`",
            "`InventoryDragger`",
            "`ItemInfo`",
            "`Double-click to drink`",
            "`A WIZARD WOULD NEVER REMOVE HIS HAT!`",
            "`A WIZARD WOULD NEVER REMOVE HIS ROBE!`",
            "the anvil is an unforge sink, not an exit control",
            "`0x005D6DF0`",
            "`+0x874`",
            "`sounds\\\\unforge`",
        ),
        "native hub/trader UI documentation lost a sibling class or recovered grid member",
    )
    return "stock InventoryScreen, every trader UI sibling, Chat, MsgBox, and purchase dispatcher are pinned"


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
    npc_doc = _read(
        NPC_INTERACTIONS_DOC_PATH,
        "the native Hub NPC interaction contract is absent",
    )

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
    _require_tokens(
        npc_doc,
        (
            "`0x004736D0`: `MOV AL,1; RET`",
            "Semicus is constructed unconditionally",
            "The normal survival builders contain only one conditional named-actor producer",
            "Every normal Courtyard construction calls `Integer(3)`",
            "next zero-to-one occupancy edge",
            "Hub-resume reconstruction",
        ),
        "Hub NPC actor gating or Courtyard reconstruction ownership drifted",
    )
    return "five-room hub census, exact NPC gates, Region population lifecycle, actions, and G14 mapping are pinned"


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
