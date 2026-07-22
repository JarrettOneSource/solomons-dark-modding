#!/usr/bin/env python3
"""Build the curated native enemy/runtime catalog from the object catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ENEMY_SPECS: list[dict[str, Any]] = [
    {
        "type_id": 0x3E8,
        "name": "Badguy",
        "display_name": "BADGUY BASE",
        "allegiance": "hostile_base",
        "family": "shared_base",
        "config_fields": ["HP", "DAMAGE", "EXTRA DAMAGE", "CHASE SPEED", "ATTACK SPEED", "XP BONUS", "PATHFINDING", "FLANKING", "DROP selectors"],
        "behavior": [
            "Supplies the common target refresh, chase/pathfinding, contact, death/reward, and drop-selection ABI.",
            "Concrete enemies inherit the base combat fields and override family state, rendering, contact, or death slots as needed.",
        ],
        "evidence_functions": {
            "constructor": "0x00473390",
            "target_refresh": "0x00483480",
            "shared_chase_tick": "0x004835F0",
            "base_contact": "0x0048A290",
            "death_rewards": "0x004819D0",
            "special_death_mode": "0x00477020",
            "drop_selector": "0x0047C070",
        },
        "spawned_types": [],
        "drop_policy": "common_selector",
    },
    {
        "type_id": 0x3E9,
        "name": "Skeleton",
        "display_name": "SKELETON",
        "allegiance": "hostile",
        "family": "skeleton",
        "config_fields": ["HEADGEAR", "WEAPON", "ARMOR", "FLAMING"],
        "behavior": [
            "Selects unarmed, sword, mace, flail, axe, or pike combat behavior from the weapon field.",
            "Headgear and armor change both presentation and wave-modified durability; FLAMING owns a Fire child effect.",
            "Death disassembles the articulated body, preserves equipment-specific pieces, grants rewards, and then runs the common drop selector.",
        ],
        "evidence_functions": {"tick": "0x00484B90", "render": "0x0048DEE0", "death_presentation": "0x0048D2A0"},
        "spawned_types": [0x7E3],
        "drop_policy": "common_selector",
    },
    {
        "type_id": 0x3EA,
        "name": "SkeletonArcher",
        "display_name": "SKELETON ARCHER",
        "allegiance": "hostile",
        "family": "skeleton",
        "config_fields": ["WEAPON", "ACCURACY", "RANGE", "ARROW TYPE", "HEADGEAR", "FLAMING", "MULTI-ARROW MODE", "EXTRA ARROWS", "STRAFING"],
        "behavior": [
            "Maintains range and optional strafe state before firing Arrow objects.",
            "Arrow type chooses normal, fire, or poison payload; accuracy, scatter/random-shot mode, and extra-arrow count are independent controls.",
        ],
        "evidence_functions": {"tick": "0x00485200", "fire_arrow": "0x00477B90", "render": "0x0048F450"},
        "spawned_types": [0x7DA],
        "drop_policy": "common_selector",
    },
    {
        "type_id": 0x3EB,
        "name": "SkeletonMage",
        "display_name": "SKELETON MAGE",
        "allegiance": "hostile",
        "family": "skeleton",
        "config_fields": ["ELEMENT", "RANGE", "HEADGEAR", "CLOAK", "SHIELD SELF", "SHIELD OTHERS", "SHIELD HP", "SHIELD INTERVAL", "FLAMING"],
        "behavior": [
            "Element selection dispatches fire, guided/ether, frost, poison, or lightning-family casting behavior.",
            "Self-shield and ally-shield toggles have separate strength fields and share the configured recast interval.",
        ],
        "evidence_functions": {"tick": "0x00490860", "spell_dispatch": "0x0047FDE0", "render": "0x00491720"},
        "spawned_types": [0x7EB, 0x7EC, 0x7E3],
        "drop_policy": "common_selector",
    },
    {
        "type_id": 0x3EC,
        "name": "Imp",
        "display_name": "IMP",
        "allegiance": "hostile",
        "family": "imp",
        "config_fields": ["SPLITS"],
        "behavior": [
            "Uses the shared flying chase/contact loop.",
            "On death, SPLITS creates child Imps through the enemy-config spawn path; children can retain a reduced split count, so the behavior is recursive.",
        ],
        "evidence_functions": {"tick": "0x00485DC0", "render": "0x00492E10", "split_death": "0x004824A0"},
        "spawned_types": [0x3EC],
        "drop_policy": "common_selector",
    },
    {
        "type_id": 0x3ED,
        "name": "GoodImp",
        "display_name": "GOOD IMP",
        "allegiance": "player_ally",
        "family": "imp",
        "config_fields": ["ally lifetime and inherited combat payload"],
        "behavior": [
            "Targets enemies rather than the player and participates as a temporary allied actor.",
            "Lifetime expiry releases the ally and emits its final Fire presentation rather than using hostile split/drop behavior.",
        ],
        "evidence_functions": {"initialize": "0x0052A050", "tick": "0x0052C1A0", "render": "0x00492E10"},
        "spawned_types": [0x7E3],
        "drop_policy": "none_ally",
    },
    {
        "type_id": 0x3EE,
        "name": "Zombie",
        "display_name": "ZOMBIE",
        "allegiance": "hostile",
        "family": "zombie",
        "config_fields": ["FLYBLOWN", "BODY TYPE", "POISON PUNCH DPS", "POISON POOL DPS", "POISON DURATION"],
        "behavior": [
            "Contact applies knockback and can attach a Poisoned modifier using the configured punch DPS and duration.",
            "The flyblown/body selectors change presentation; death can leave a PoisonPool carrying the configured pool DPS.",
        ],
        "evidence_functions": {"tick": "0x004863A0", "render": "0x00493390", "attack_and_modifiers": "0x0047DB90"},
        "spawned_types": [0x1B6D, 0x1B72, 0x806],
        "drop_policy": "common_selector",
    },
    {
        "type_id": 0x3EF,
        "name": "Wraith",
        "display_name": "WRAITH",
        "allegiance": "hostile",
        "family": "wraith",
        "config_fields": ["FLAMING"],
        "behavior": [
            "Alternates approach, orbit/retreat, attack, and fade visibility states rather than using only straight chase.",
            "Its hit path creates the Dazzle status modifier; FLAMING adds the shared burning presentation.",
        ],
        "evidence_functions": {"initialize": "0x00486BB0", "tick": "0x00486C30", "render": "0x00496220"},
        "spawned_types": [0x1B6E, 0x7E3],
        "drop_policy": "common_selector",
    },
    {
        "type_id": 0x3F0,
        "name": "DemonSkull",
        "display_name": "THE DISCORPOREAL",
        "allegiance": "hostile_boss",
        "family": "boss",
        "config_fields": ["EYE LASERS", "MOUTH BEAM", "SPIT FIRE", "SPIT IMPS", "EYE LASER DAMAGE", "BEAM DPS", "FIRE DPS"],
        "behavior": [
            "A bitfield enables eye-laser, mouth-beam, and Unholy Spit scheduling; bite/lunge, scream, and flair are separate animation/action states.",
            "Eye-laser state creates two EyeLaser objects. Mouth beam performs its own geometric collision scan and leaves Green Fire presentation/remnants.",
            "SPIT IMPS is copied into Unholy Spit and changes detonation payload; it is not an independently scheduled fourth ranged attack.",
        ],
        "evidence_functions": {"schedule_attack": "0x00474930", "tick": "0x004963C0", "render": "0x004974D0", "event_dispatch": "0x00498180", "mouth_beam": "0x0044FFE0", "spit_action": "0x00449A00", "unholy_spit_impact": "0x005EA6F0"},
        "spawned_types": [0x7FF, 0x7FB, 0x7FA, 0x7FC],
        "drop_policy": "common_selector",
    },
    {
        "type_id": 0x3F1,
        "name": "Demon",
        "display_name": "LESSER DEMON",
        "allegiance": "hostile_boss",
        "family": "boss",
        "config_fields": ["SPLITS"],
        "behavior": [
            "Uses a multi-part articulated Demon-atlas renderer and a dedicated boss action state machine.",
            "Its attack event creates DemonBomb; death creates the configured number of radial Imp children inheriting team/combat scalars.",
        ],
        "evidence_functions": {"tick": "0x00487300", "render": "0x00498BA0", "event_dispatch": "0x0049A270", "death_split": "0x00482930"},
        "spawned_types": [0x7F7, 0x3EC, 0x7E3],
        "drop_policy": "common_selector",
    },
    {
        "type_id": 0x3F2,
        "name": "DireFaculty",
        "display_name": "DIRE FACULTY",
        "allegiance": "hostile_boss",
        "family": "boss",
        "config_fields": ["PRIMARY ATTACK", "SECONDARY ATTACK", "HAT", "GENDER", "PRIMARY DAMAGE", "SECONDARY DAMAGE"],
        "behavior": [
            "Primary indexes 0..2 dispatch Death Missile, Blightning, and Direball. Secondary indexes 0..2 dispatch Acid Pain, Tragic Circle, and Ring of Dire.",
            "The stock UI/config strings expose primary index 3 FAUST JET and secondary index 3 THING OF ICE, but the recovered event dispatcher has no corresponding branch. These are compiled labels with no stock behavior, not unimplemented catalog guesses.",
        ],
        "evidence_functions": {"attack_trigger": "0x00475340", "tick": "0x0049D0D0", "render": "0x0049DF30", "event_dispatch": "0x004804D0", "death": "0x0049E8F0"},
        "spawned_types": [0x800, 0x801, 0x802, 0x804],
        "drop_policy": "common_selector",
    },
    {
        "type_id": 0x3F3,
        "name": "Heartmonger",
        "display_name": "HEARTMONGER",
        "allegiance": "hostile_boss",
        "family": "boss",
        "config_fields": ["CROWS", "CHANCE TO BLIND", "SKELEFRIENDS"],
        "behavior": [
            "Initialization allocates the configured Crow helpers at evenly spaced orbit phases; the parent updates and owns them while alive.",
            "Crows scan periodically, dive, apply Heartmonger primary damage, and can blind only the player when the configured percentage roll succeeds.",
            "SKELEFRIENDS selects a randomized summon interval; expiry can spawn Skeleton, SkeletonArcher, or one/two Imps with selected wave modifiers.",
            "Death detaches surviving crows into the arena helper list before the common reward/drop and fragment presentation completes.",
        ],
        "evidence_functions": {"initialize": "0x00488F20", "tick": "0x00489000", "render": "0x0049F870", "crow_strike": "0x0047A160", "death": "0x0049FB60"},
        "spawned_types": [0x3F4, 0x3E9, 0x3EA, 0x3EC],
        "drop_policy": "common_selector",
    },
    {
        "type_id": 0x3F4,
        "name": "Crow",
        "display_name": "HEARTMONGER CROW",
        "allegiance": "hostile_helper",
        "family": "heartmonger_helper",
        "config_fields": ["parent identity", "orbit phase", "target identity"],
        "behavior": [
            "Orbits a Heartmonger parent, scans for a valid target on a cadence, dives once selected, and then returns to orbit.",
            "Parent death clears ownership and registers the helper independently; Crow is not a normal reward/drop-bearing Badguy actor.",
        ],
        "evidence_functions": {"constructor": "0x00475480", "tick": "0x0047EA70", "strike": "0x0047A160"},
        "spawned_types": [],
        "drop_policy": "none_helper",
    },
    {
        "type_id": 0x3F5,
        "name": "Coffin",
        "display_name": "COFFIN",
        "allegiance": "hostile",
        "family": "coffin",
        "config_fields": ["MAX MAGGOTS", "MAGGOT HP", "MAGGOT DAMAGE", "MAGGOT POISON DAMAGE"],
        "behavior": [
            "Runs closed, opening/charging, delay, and open/active states; opening creates initial Maggots and the active state can replenish them up to the live-child limit.",
            "Each Maggot inherits configured HP, primary damage, poison damage, arena/team identity, and a parent identity used for live-count accounting.",
            "The open state also scans nearby actors for Coffin poison/damage logic and excludes Golem from the poison modifier.",
        ],
        "evidence_functions": {"initialize": "0x00487F30", "tick": "0x004A2760", "spawn_maggot": "0x00479C30", "render": "0x0049AC90", "alternate_render": "0x0049AEE0", "death": "0x0049B310"},
        "spawned_types": [0x7FD, 0x1B72],
        "drop_policy": "common_selector",
    },
    {
        "type_id": 0x7FC,
        "name": "GreenImp",
        "display_name": "GREEN IMP",
        "allegiance": "hostile",
        "family": "imp",
        "config_fields": ["inherited Unholy Spit payload"],
        "behavior": [
            "Uses the Imp chase logic and a distinct render class.",
            "Unholy Spit with SPIT IMPS enabled samples its trajectory and spawns Green Imps only where the arena placement predicate succeeds.",
        ],
        "evidence_functions": {"constructor": "0x00474D20", "tick": "0x00485DC0", "render": "0x004930D0", "spit_spawn_owner": "0x005EA6F0"},
        "spawned_types": [],
        "drop_policy": "common_selector",
    },
    {
        "type_id": 0x7FD,
        "name": "Maggot",
        "display_name": "MAGGOT",
        "allegiance": "hostile_child",
        "family": "coffin",
        "config_fields": ["parent identity", "inherited HP", "inherited damage", "inherited poison damage"],
        "behavior": [
            "Emerges ballistically from one of the Coffin lid/edge launch paths, then transitions to crawling behavior.",
            "A valid bite applies primary damage and optional poison (except to Golem), then immediately invokes Maggot death; the bite is single-use.",
            "Parent loss/out-of-range cleanup and the normal bite/death path update the Coffin live-child count through the stored parent identity.",
        ],
        "evidence_functions": {"initialize": "0x00487F60", "tick": "0x0048B2A0", "emergence": "0x0047E410", "parent_accounting": "0x00487FD0", "contact_behavior": "0x004881A0", "death": "0x0049C830"},
        "spawned_types": [0x1B72],
        "drop_policy": "suppressed_in_drop_selector",
    },
    {
        "type_id": 0x809,
        "name": "Spider",
        "display_name": "SPIDER",
        "allegiance": "hostile",
        "family": "spider",
        "config_fields": ["SPIT WEBS", "COCOON HP", "SUCK DPS"],
        "behavior": [
            "The movement/action state machine covers walking, hop/lunge, web-spit startup, and a grab/suck state.",
            "Web spit creates Silk, not Cocoon directly; Silk collision applies Mod_Webbed with the cocoon-strength payload, and reaching the web threshold asks the target actor to create Cocoon.",
            "Grab contact applies primary damage once, follows the held target, and applies half of configured suck DPS every 25 ticks while the target remains valid.",
        ],
        "evidence_functions": {"tick": "0x00489610", "behavior": "0x0047A580", "spit_eligibility": "0x00475DB0", "spawn_silk": "0x00475AC0", "hop_lunge": "0x00475CD0", "contact": "0x0048BC80", "render": "0x004A1670", "death": "0x00482D60"},
        "spawned_types": [0x808, 0x1B79, 0x80A],
        "drop_policy": "common_selector",
    },
    {
        "type_id": 0x80A,
        "name": "Cocoon",
        "display_name": "COCOON",
        "allegiance": "hostile_child",
        "family": "spider",
        "config_fields": ["target actor identity", "fixed creation position", "target-side maximum web payload"],
        "behavior": [
            "Mod_Webbed reaching its threshold calls the target actor's Cocoon helper; the actor creates Cocoon only when its previously stored Cocoon identity no longer resolves, preventing duplicates on one target.",
            "Cocoon stores the target actor identity, remains fixed at its initialization position while the web state immobilizes the target, and its contact/death handler monitors that actor before release presentation and common death state.",
        ],
        "evidence_functions": {"constructor": "0x0047BAE0", "initialize": "0x0047BB50", "tick": "0x00475D10", "contact_or_release": "0x0048BCE0", "web_modifier_merge": "0x00627BD0", "target_create_or_refresh": "0x0052C680"},
        "spawned_types": [],
        "drop_policy": "suppressed_in_drop_selector",
    },
    {
        "type_id": 0x139D,
        "name": "Portal",
        "display_name": "IMP PORTAL",
        "allegiance": "hostile_spawner",
        "family": "portal",
        "config_fields": ["IMP FREQUENCY"],
        "behavior": [
            "Materializes for ten ticks and then remains stationary while animating.",
            "IMP FREQUENCY selects one of six exact lower/upper time ranges. Each bound is multiplied by the global timing scale at 0x00820230 and converted to an integer before being stored at actor +0x234/+0x238.",
            "When the countdown expires, the normal reset samples the inclusive stored lower..upper range. A separate one-in-eight roll instead samples 0..upper-1, after which an ejected airborne Imp inherits the Portal team and primary damage.",
        ],
        "frequency_presets": [
            {"enum": 0, "label": "VERY LOW", "lower": 8.0, "upper": 10.0},
            {"enum": 1, "label": "LOW", "lower": 6.0, "upper": 8.0},
            {"enum": 2, "label": "NORMAL", "lower": 3.0, "upper": 4.0},
            {"enum": 3, "label": "HIGH", "lower": 2.0, "upper": 3.0},
            {"enum": 4, "label": "VERY HIGH", "lower": 1.0, "upper": 2.0},
            {"enum": 5, "label": "YOU WILL DIE", "lower": 0.25, "upper": 0.5},
        ],
        "evidence_functions": {"tick": "0x00489CC0", "render": "0x004A1B30", "alternate_render": "0x004A1CB0", "contact": "0x0048C370", "death": "0x004A1FA0"},
        "spawned_types": [0x3EC],
        "drop_policy": "common_selector",
    },
]


WAVE_FLAGS = [
    ("HPUP", 0x01, "HP x1.5"),
    ("HPDOWN", 0x02, "HP x0.5"),
    ("STRONG", 0x03, "damage fields x1.5"),
    ("WEAK", 0x04, "damage fields x0.5"),
    ("FAST", 0x05, "chase-speed multiplier"),
    ("SLOW", 0x06, "chase and attack speed x0.5"),
    ("XPBONUS", 0x07, "write the native XP-bonus multiplier constant"),
    ("BURNING", 0x08, "FLAMING=1 and chase/attack speed x1.5"),
    ("HELM", 0x09, "headgear 1 plus flat HP"),
    ("HORNED", 0x0A, "headgear 2 plus flat HP"),
    ("HOODED", 0x0B, "headgear 3 plus flat HP"),
    ("LEADING", 0x0C, "archer accuracy mode 1"),
    ("SCATTERSHOT", 0x0D, "archer accuracy mode 2"),
    ("RANGEUP", 0x0E, "range mode 2"),
    ("RANGEDOWN", 0x0F, "range mode 1"),
    ("RANGEEASY", 0x10, "range mode 3"),
    ("SHIELD", 0x11, "self shield; strength 50; interval 10"),
    ("SHIELDOTHERS", 0x12, "ally shield; strength 50; interval 10"),
    ("SHIELDSTRONG", 0x13, "shield strength x9"),
    ("SHIELDFAST", 0x14, "shield interval /2"),
    ("SPLIT", 0x15, "random split count 1..2"),
    ("SPLITMANY", 0x16, "wave-scaled split count"),
    ("MANYMAGGOTS", 0x17, "max maggots 50"),
    ("STRONGMAGGOTS", 0x18, "maggot HP=5 and damage=5"),
    ("POISONARROW", 0x19, "arrow type 2 and derived extra damage"),
    ("FIREARROW", 0x1A, "arrow type 1"),
    ("ARMOR", 0x1B, "armor enabled and HP adjusted"),
    ("SWORD", 0x1C, "skeleton weapon 1 and stat adjustment"),
    ("MACE", 0x1D, "skeleton weapon 2 and stat adjustment"),
    ("FLAIL", 0x1E, "skeleton weapon 3 and stat adjustment"),
    ("AXE", 0x1F, "skeleton weapon 4 and stat adjustment"),
    ("PIKE", 0x20, "skeleton weapon 5 and stat adjustment"),
    ("CASTFIRE", 0x21, "mage element fire and damage scaling"),
    ("CASTLIGHTNING", 0x22, "mage element lightning and damage scaling"),
    ("CASTFROST", 0x23, "mage element frost and damage scaling"),
    ("CASTPOISON", 0x24, "mage element poison and damage scaling"),
    ("ROTTEN", 0x25, "flyblown zombie plus derived poison fields"),
    ("DEATHIMPS", 0x27, "death-imp count 5"),
    ("DEATHIMPSMANY", 0x28, "death-imp count 15"),
    ("ARMORMAYBE", 0x2A, "random armor byte"),
    ("NOSKELETONS", 0x2B, "multiply config +0x60 by the native reduction constant"),
    ("MORESKELETONS", 0x2C, "clear config byte +0x94"),
    ("RANDOMSHOT", 0x31, "archer accuracy mode 3"),
]


SHARED_PIPELINE = {
    "factory": "0x005B7080",
    "config_parser": "0x004AFBC0",
    "defaults": "0x00640240",
    "wave_flag_parser": "0x0062E070",
    "build_enemy_config": "0x0046B390",
    "apply_config": "0x00462790",
    "create_from_config": "0x00463B50",
    "spawn_and_register": "0x00469580",
    "target_refresh": "0x00483480",
    "shared_chase_tick": "0x004835F0",
    "base_contact": "0x0048A290",
    "death_rewards": "0x004819D0",
    "special_death_mode": "0x00477020",
    "drop_selector": "0x0047C070",
    "clear_target": "0x00484B30",
    "release_callbacks": "0x00482E90",
}


DROP_PIPELINE = {
    "selector": "0x0047C070",
    "rng_seed": "actor +0x1C0",
    "config_selectors": {
        "+0xCC": "orbs",
        "+0xCD": "powerups",
        "+0xCE": "items",
        "+0xCF": "gold",
        "+0xD0": "specific items",
        "+0xD1": "potions",
    },
    "arena_disable_mask_at_0x8F04": {
        "bit_0": "gold",
        "bit_1": "potions",
        "bit_2": "powerups",
        "bit_3": "orbs",
        "bit_4": "key",
        "bit_5": "items",
    },
    "selection_rule": "Build eligible candidates independently, then materialize exactly one uniformly selected candidate.",
    "materializers": [
        {"kind": "key", "function": "0x00468440", "type_id": 0x1B64},
        {"kind": "orb", "function": "factory", "type_id": 0x7DB},
        {"kind": "gold", "function": "0x0046AA90", "type_id": 0x7DC, "notes": "chunks at 25 and merges into sacks"},
        {"kind": "item", "function": "0x0046A360", "type_id": None},
        {"kind": "powerup", "function": "factory", "type_id": 0x7F6},
        {"kind": "potion", "function": "0x0046AE20", "type_id": 0x1B59},
    ],
    "explicitly_suppressed_type_ids": [0x7FD, 0x80A],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-object-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def selected_slots(raw: dict[str, Any]) -> dict[str, str]:
    wanted = {"0x04", "0x08", "0x1C", "0x28", "0x4C", "0x50", "0x6C"}
    return {
        slot["offset"]: slot["function"]
        for slot in raw["vtable_slots"]
        if slot["offset"] in wanted
    }


def compact_art_uses(raw: dict[str, Any]) -> list[dict[str, Any]]:
    fields = (
        "atlas",
        "destination_kind",
        "first_record",
        "last_record",
        "consumer_function",
        "vtable_slot",
    )
    return [{field: use[field] for field in fields if field in use} for use in raw["class_art_uses"]]


def build_catalog(game_object_catalog: Path) -> dict[str, Any]:
    source = json.loads(game_object_catalog.read_text(encoding="utf-8"))
    by_id = {entry["type_id"]: entry for entry in source["types"]}
    expected_ids = [spec["type_id"] for spec in ENEMY_SPECS]
    if len(expected_ids) != len(set(expected_ids)):
        raise ValueError("duplicate enemy type ID in curated specifications")
    missing = [type_id for type_id in expected_ids if type_id not in by_id]
    if missing:
        raise ValueError("enemy types missing from object catalog: %r" % missing)

    enemies: list[dict[str, Any]] = []
    for spec in ENEMY_SPECS:
        raw = by_id[spec["type_id"]]
        if raw["class"] != spec["name"]:
            raise ValueError(
                "type 0x%X class drifted: expected %s, got %s"
                % (spec["type_id"], spec["name"], raw["class"])
            )
        enemy = dict(spec)
        enemy.update(
            {
                "type_id_hex": raw["type_id_hex"],
                "allocation_size": raw["allocation_size"],
                "allocation_size_hex": raw["allocation_size_hex"],
                "constructor": raw["constructor_address"],
                "vtable": raw["vtable"],
                "selected_vtable_slots": selected_slots(raw),
                "direct_class_art_uses": compact_art_uses(raw),
            }
        )
        enemies.append(enemy)

    atlas_names = sorted(
        {
            use["atlas"]
            for enemy in enemies
            for use in enemy["direct_class_art_uses"]
        }
    )
    spawned_types = sorted(
        {type_id for enemy in enemies for type_id in enemy["spawned_types"]}
    )
    return {
        "schema": "solomon-dark-native-enemy-catalog-v1",
        "source": {
            "game_object_catalog": str(game_object_catalog),
            "factory": "0x005B7080",
            "config_parser": "0x004AFBC0",
            "wave_flag_parser": "0x0062E070",
            "build_enemy_config": "0x0046B390",
        },
        "summary": {
            "enemy_runtime_type_count": len(enemies),
            "hostile_or_spawner_count": sum(
                1 for enemy in enemies if enemy["allegiance"].startswith("hostile")
            ),
            "ally_count": sum(1 for enemy in enemies if enemy["allegiance"] == "player_ally"),
            "direct_art_atlases": atlas_names,
            "spawned_type_ids": spawned_types,
        },
        "shared_pipeline": SHARED_PIPELINE,
        "wave_flags": [
            {"token": token, "internal_code": code, "internal_code_hex": "0x%02X" % code, "effect": effect}
            for token, code, effect in WAVE_FLAGS
        ],
        "wave_flag_parser_anomalies": [
            "An unreachable duplicate FLAG_ARMOR comparison maps to internal code 0x29 after the earlier FLAG_ARMOR branch already returns 0x1B.",
            "FLAG_ARMORMAYBE maps to 0x2A, not 0x29.",
            "BuildEnemyConfig handles internal codes 0x2D..0x30, but the recovered text parser emits none of them.",
        ],
        "drop_pipeline": DROP_PIPELINE,
        "enemies": enemies,
    }


def main() -> int:
    args = parse_args()
    output = build_catalog(args.game_object_catalog)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(output["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
