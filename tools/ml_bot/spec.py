"""Exact policy-v3 model and rollout contracts shared by training tools."""

from __future__ import annotations

from typing import Any, Mapping

MODEL_FORMAT = "solomon-dark-bot-policy"
MODEL_VERSION = 3
OBSERVATION_VERSION = 3
TRAJECTORY_VERSION = 3
CHOICE_TRAJECTORY_VERSION = 3
ARCHITECTURE = "mlp-tanh-four-head-v3"
HIDDEN_SIZES = (512, 256)
CHOICE_HIDDEN_SIZE = 128

SECONDARY_SLOT_COUNT = 8
ENEMY_SLOT_COUNT = 8
PICKUP_SLOT_COUNT = 4
ALLY_SLOT_COUNT = 4
OBSTACLE_SLOT_COUNT = 8
HAZARD_SLOT_COUNT = 12
POTION_SLOT_COUNT = 12
EQUIPMENT_SLOT_COUNT = 7
MAX_CHOICE_OPTIONS = 16

# Fixed contract scales. These match policy_spec.lua; they are never fitted
# from a training batch.
MANA_SCALE = 2000.0
HP_SCALE = 1000.0
VELOCITY_SCALE = 1000.0
COOLDOWN_SCALE = 60.0
RANGE_SCALE = 1000.0
RADIUS_SCALE = 100.0
LEVEL_SCALE = 20.0
WAVE_SCALE = 20.0
ENEMY_COUNT_SCALE = 16.0
THREAT_COUNT_SCALE = 8.0
ALLY_COUNT_SCALE = 50.0
HISTORY_TIME_SCALE_MS = 5000.0
TARGET_ACTION_SCALE = 8.0
RAY_RANGE = 480.0
RAY_STEP = 60.0
PATCH_SPACING = 60.0
PATCH_RADIUS = 3
NAV_REFRESH_MS = 2000
MOVEMENT_LOOKAHEAD = 110.0
PICKUP_COUNT_SCALE = 8.0
MULTIPLIER_SCALE = 4.0
PICKUP_REQUEST_INTERVAL_MS = 500

# The target head receives twice the entropy pressure of movement/ability/aim
# so a fresh PPO run keeps exploring enemy-slot changes instead of collapsing
# onto the often-legal keep_current action.
MOVEMENT_ENTROPY_COEFFICIENT = 0.01
TARGET_ENTROPY_COEFFICIENT = 0.02
ABILITY_ENTROPY_COEFFICIENT = 0.01
AIM_ENTROPY_COEFFICIENT = 0.01
CHOICE_ENTROPY_COEFFICIENT = 0.05
CHOICE_EXPLORATION_TEMPERATURE = 1.25
CHOICE_FINAL_TEMPERATURE = 1.0
CHOICE_COVERAGE_THRESHOLD = 20

STATUS_DURATION_SCALE_SECONDS = 60.0
HAZARD_LIFETIME_SCALE_SECONDS = 60.0
HAZARD_TIME_TO_CONTACT_SCALE_SECONDS = 10.0
ENEMY_SPECIES_SCALE = 19.0
ENEMY_ANIMATION_STATE_SCALE = 255.0
HAZARD_TYPE_SCALE = 38.0
EQUIPMENT_CATALOG_SCALE = 46.0
EQUIPMENT_RARITY_SCALE = 2.0
EQUIPMENT_TARGET_KIND_SCALE = 8.0
EQUIPMENT_EFFECT_SCALE = 4.0
INVENTORY_COUNT_SATURATION = 99.0
AIM_OFFSET_WORLD = 60.0
SKILL_ID_SCALE = 81.0
SKILL_RANK_SCALE = 20.0
SKILL_BAND_SCALE = 8.0
SKILL_DAMAGE_SCALE = 500.0
SKILL_RADIUS_SCALE = 20.0
SKILL_DURATION_SCALE = 30.0
SKILL_VALUE_SCALE = 1250.0
SKILL_CONCENTRATION_SCALE = 25.0
SKILL_CHANCE_SCALE = 100.0
SKILL_QUANTITY_OR_STRENGTH_SCALE = 2100.0
PRIMARY_BUILD_INDEX_ENCODING = "base_band_identity_or_weld_pair_index"


def _observation_names() -> tuple[str, ...]:
    names: list[str] = []
    names.extend(
        (
            "self_hp_ratio",
            "self_mana_ratio",
            "self_level_scaled",
            "wave_scaled",
            "self_move_speed_scaled",
            "self_moving",
            "self_cast_active",
            "self_cast_ready",
            "self_poisoned",
            "self_webbed",
            "self_damage_x4",
            "self_status_active",
            "self_mana_current_scaled",
            "self_mana_max_scaled",
            "self_hp_max_scaled",
        )
    )
    names.extend(
        (
            "primary_element_fire",
            "primary_element_water",
            "primary_element_earth",
            "primary_element_air",
            "primary_element_ether",
            "primary_welded",
            "primary_build_index_scaled",
            "primary_mana_cost_scaled",
            "primary_range_min_scaled",
            "primary_range_max_scaled",
            "primary_affordable",
        )
    )
    for slot in range(1, 9):
        prefix = f"secondary_{slot}_"
        names.extend(
            prefix + suffix
            for suffix in (
                "occupied",
                "element_fire",
                "element_water",
                "element_earth",
                "element_air",
                "element_ether",
                "band_index_scaled",
                "mana_cost_scaled",
                "range_scaled",
                "cooldown_scaled",
                "ready",
                "affordable",
                "in_range_of_target",
            )
        )
    for slot in range(1, 9):
        prefix = f"enemy_{slot}_"
        names.extend(
            prefix + suffix
            for suffix in (
                "present",
                "dx",
                "dy",
                "distance_scaled",
                "hp_ratio",
                "radius_scaled",
                "velocity_dx",
                "velocity_dy",
                "in_primary_range",
                "is_current_target",
            )
        )
    names.extend(
        (
            "target_present",
            "target_dx",
            "target_dy",
            "target_distance_scaled",
            "target_contact_distance_scaled",
            "target_hp_ratio",
            "target_radius_scaled",
            "target_in_primary_range",
            "primary_min_range_scaled",
            "primary_max_range_scaled",
        )
    )
    names.extend(
        f"clearance_{direction}_scaled"
        for direction in (
            "east",
            "southeast",
            "south",
            "southwest",
            "west",
            "northwest",
            "north",
            "northeast",
        )
    )
    for row in range(1, 8):
        for column in range(1, 8):
            if row != 4 or column != 4:
                names.append(f"walkability_patch_row_{row}_col_{column}")
    for slot in range(1, 5):
        prefix = f"pickup_{slot}_"
        names.extend(
            prefix + suffix
            for suffix in (
                "present",
                "dx",
                "dy",
                "distance_scaled",
                "type_gold",
                "type_health_orb",
                "type_mana_orb",
                "type_item_carrier",
            )
        )
    names.append("pickup_count_scaled")
    for slot in range(1, 5):
        prefix = f"ally_{slot}_"
        names.extend(
            prefix + suffix
            for suffix in (
                "present",
                "dx",
                "dy",
                "distance_scaled",
                "hp_ratio",
                "mana_ratio",
                "alive",
                "is_human",
                "intent_dx",
                "intent_dy",
            )
        )
    names.append("ally_count_scaled")
    names.extend(
        (
            "enemy_count_scaled",
            "threat_count_scaled",
            "nearest_enemy_dx",
            "nearest_enemy_dy",
            "nearest_enemy_distance_scaled",
            "nearest_threat_dx",
            "nearest_threat_dy",
            "nearest_threat_distance_scaled",
            "escape_dx",
            "escape_dy",
            "suggested_move_dx",
            "suggested_move_dy",
            "arena_center_dx",
            "arena_center_dy",
            "arena_center_distance_scaled",
            "arena_x_normalized",
            "arena_y_normalized",
            "edge_pressure",
            "element_fire",
            "element_water",
            "element_earth",
            "element_air",
            "element_ether",
            "discipline_mind",
            "discipline_body",
            "discipline_arcane",
            "hp_delta",
            "mana_delta",
            "target_hp_delta",
            "enemy_count_delta",
            "previous_move_dx",
            "previous_move_dy",
            "previous_cast_primary",
            "previous_cast_secondary",
            "time_since_damage_scaled",
            "time_since_cast_scaled",
            "time_since_move_scaled",
            "previous_target_action_scaled",
            "previous_target_switched",
            "has_spell_welding_skill",
            "weld_offer_pending",
            "offensive_damage_multiplier_scaled",
            "offensive_mana_multiplier_scaled",
            "cast_speed_multiplier_scaled",
            "secondary_recharge_multiplier_scaled",
        )
    )

    # Block J: participant-scoped potion timers.
    names.extend(
        (
            "self_damage_x4_remaining_scaled",
            "self_poison_immunity_remaining_scaled",
            "self_all_concentration_remaining_scaled",
        )
    )

    # Block K: identity, facing, telegraph, and combat status for the existing
    # eight enemy slots.
    enemy_extension_suffixes = (
        "species_index_scaled",
        "species_known",
        "role_melee",
        "role_ranged",
        "role_caster",
        "role_spawner",
        "role_exploder",
        "role_boss",
        "role_flying",
        "role_stationary",
        "facing_dx",
        "facing_dy",
        "anim_state_scaled",
        "telegraph_known",
        "winding_up",
        "attack_active",
        "recovering",
        "slowed",
        "slow_remaining_scaled",
        "frozen",
        "frozen_remaining_scaled",
        "poisoned",
        "poison_remaining_scaled",
        "webbed",
        "webbed_remaining_scaled",
        "turn_undead",
        "turn_undead_remaining_scaled",
    )
    for slot in range(1, 9):
        prefix = f"enemy_{slot}_"
        names.extend(prefix + suffix for suffix in enemy_extension_suffixes)

    # Block L: persisted target motion and facing.
    names.extend(
        (
            "target_velocity_dx",
            "target_velocity_dy",
            "target_facing_dx",
            "target_facing_dy",
        )
    )

    # Block M: eight nearest exact collision primitives.
    obstacle_suffixes = (
        "present",
        "nearest_dx",
        "nearest_dy",
        "clearance_scaled",
        "normal_dx",
        "normal_dy",
        "radius_scaled",
        "extent_x_scaled",
        "extent_y_scaled",
        "kind_circle",
        "kind_segment",
        "kind_polygon",
        "is_participant",
        "is_destructible",
    )
    for slot in range(1, 9):
        prefix = f"obstacle_{slot}_"
        names.extend(prefix + suffix for suffix in obstacle_suffixes)

    # Block N: twelve hostile hazards. Unknown classes remain present with
    # type_known=0, exactly as in the frozen Lua contract.
    hazard_suffixes = (
        "present",
        "hazard_type_index_scaled",
        "type_known",
        "dx",
        "dy",
        "distance_scaled",
        "velocity_dx",
        "velocity_dy",
        "radius_scaled",
        "time_to_contact_scaled",
        "remaining_time_scaled",
        "kind_projectile",
        "kind_area",
        "kind_beam",
        "homing",
        "targeting_self",
        "source_enemy",
    )
    for slot in range(1, 13):
        prefix = f"hazard_{slot}_"
        names.extend(prefix + suffix for suffix in hazard_suffixes)
    names.append("hazard_count_scaled")

    # Block O: twelve count-ranked potion descriptors and totals.
    potion_suffixes = (
        "present",
        "count_scaled",
        "stock_health",
        "stock_mana",
        "stock_wizard_chug",
        "stock_antidote",
        "stock_mind_chug",
        "stock_rejuvenation",
        "custom",
        "restores_hp_fraction",
        "restores_mana_fraction",
        "damage_multiplier_scaled",
        "cures_poison",
        "poison_immunity_duration_scaled",
        "concentrates_all",
        "effect_duration_scaled",
        "custom_effect_known",
        "identity_hash_a",
        "identity_hash_b",
    )
    for slot in range(1, 13):
        prefix = f"potion_{slot}_"
        names.extend(prefix + suffix for suffix in potion_suffixes)
    names.extend(("potion_type_count_scaled", "potion_total_count_scaled"))

    # Block P: seven equipped-item descriptors.
    equipment_suffixes = (
        "present",
        "catalog_known",
        "identity_hash_a",
        "identity_hash_b",
        "rarity_scaled",
        "level_scaled",
        "set_complete",
        "offense_effect_scaled",
        "resource_effect_scaled",
        "mobility_effect_scaled",
        "defense_effect_scaled",
        "targeted_effect_present",
        "target_kind_scaled",
        "target_magnitude_scaled",
        "special_feature_present",
    )
    for slot in ("hat", "robe", "weapon", "ring_1", "ring_2", "ring_3", "amulet"):
        prefix = f"equipment_{slot}_"
        names.extend(prefix + suffix for suffix in equipment_suffixes)

    # Block Q: bounded inventory taxonomy totals.
    names.extend(
        (
            "inventory_item_total_count_scaled",
            "inventory_potion_count_scaled",
            "inventory_equipment_count_scaled",
            "inventory_sack_count_scaled",
            "inventory_misc_count_scaled",
            "inventory_perk_count_scaled",
            "inventory_map_count_scaled",
            "inventory_registered_custom_count_scaled",
            "inventory_unknown_count_scaled",
        )
    )

    if len(names) != 1279:
        raise AssertionError(
            f"policy-v3 observation contract has {len(names)} names, expected 1279"
        )
    return tuple(names)


OBSERVATION_NAMES = _observation_names()

MOVEMENT_ACTION_NAMES = (
    "idle",
    "east",
    "southeast",
    "south",
    "southwest",
    "west",
    "northwest",
    "north",
    "northeast",
)

MOVEMENT_DIRECTIONS = (
    (0.0, 0.0),
    (1.0, 0.0),
    (2**-0.5, 2**-0.5),
    (0.0, 1.0),
    (-2**-0.5, 2**-0.5),
    (-1.0, 0.0),
    (-2**-0.5, -2**-0.5),
    (0.0, -1.0),
    (2**-0.5, -2**-0.5),
)

TARGET_ACTION_NAMES = (
    "keep_current",
    "enemy_1",
    "enemy_2",
    "enemy_3",
    "enemy_4",
    "enemy_5",
    "enemy_6",
    "enemy_7",
    "enemy_8",
)

ABILITY_ACTION_NAMES = (
    "none",
    "primary",
    "secondary_1",
    "secondary_2",
    "secondary_3",
    "secondary_4",
    "secondary_5",
    "secondary_6",
    "secondary_7",
    "secondary_8",
    "drink_potion_1",
    "drink_potion_2",
    "drink_potion_3",
    "drink_potion_4",
    "drink_potion_5",
    "drink_potion_6",
    "drink_potion_7",
    "drink_potion_8",
    "drink_potion_9",
    "drink_potion_10",
    "drink_potion_11",
    "drink_potion_12",
)

AIM_ACTION_NAMES = (
    "center",
    "east",
    "southeast",
    "south",
    "southwest",
    "west",
    "northwest",
    "north",
    "northeast",
)

# Exact ordered 56-value choice-option descriptor contract.
OPTION_DESCRIPTOR_NAMES = (
    "present",
    "option_id_index_scaled",
    "catalog_known",
    "apply_count_scaled",
    "learned_rank_scaled",
    "effective_rank_scaled",
    "cap_rank_scaled",
    "max_rank_scaled",
    "band_index_scaled",
    "family_element",
    "family_discipline",
    "family_ether",
    "family_fire",
    "family_air",
    "family_water",
    "family_earth",
    "family_arcane",
    "family_mind",
    "family_body",
    "family_advanced",
    "family_runtime_only",
    "is_primary",
    "is_secondary",
    "is_passive",
    "is_utility",
    "is_weld",
    "is_health_up",
    "is_mana_up",
    "weld_element_ether",
    "weld_element_fire",
    "weld_element_air",
    "weld_element_water",
    "weld_element_earth",
    "weld_build_index_scaled",
    "mana_cost_scaled",
    "damage_min_scaled",
    "damage_max_scaled",
    "range_scaled",
    "cooldown_scaled",
    "radius_scaled",
    "duration_scaled",
    "value_scaled",
    "concentration_scaled",
    "chance_scaled",
    "quantity_or_strength_scaled",
    "mana_cost_present",
    "damage_min_present",
    "damage_max_present",
    "range_present",
    "cooldown_present",
    "radius_present",
    "duration_present",
    "value_present",
    "concentration_present",
    "chance_present",
    "quantity_or_strength_present",
)

TRAJECTORY_FIELDS = (
    "trajectory_version",
    "episode_id",
    "participant_id",
    "simulation_tick",
    "observation",
    "movement_mask",
    "target_mask",
    "ability_mask",
    "aim_mask",
    "movement_action",
    "target_action",
    "ability_action",
    "aim_action",
    "old_log_probability",
    "old_value",
    "reward",
    "done",
)

CHOICE_TRAJECTORY_FIELDS = (
    "choice_trajectory_version",
    "episode_id",
    "participant_id",
    "generation",
    "simulation_tick",
    "observation",
    "option_descriptors",
    "option_mask",
    "selected_option",
    "old_log_probability",
    "old_value",
    "next_value",
    "duration_steps",
    "rewards",
    "done",
    "choice_mode",
    "trainable",
    "accepted",
)


def model_shape() -> dict[str, object]:
    return {
        "observation_size": len(OBSERVATION_NAMES),
        "hidden_sizes": list(HIDDEN_SIZES),
        "movement_action_size": len(MOVEMENT_ACTION_NAMES),
        "target_action_size": len(TARGET_ACTION_NAMES),
        "ability_action_size": len(ABILITY_ACTION_NAMES),
        "aim_action_size": len(AIM_ACTION_NAMES),
        "value_size": 1,
        "option_descriptor_size": len(OPTION_DESCRIPTOR_NAMES),
        "choice_hidden_size": CHOICE_HIDDEN_SIZE,
        "choice_value_size": 1,
    }


def contract_metadata() -> dict[str, object]:
    return {
        "format": MODEL_FORMAT,
        "version": MODEL_VERSION,
        "observation_version": OBSERVATION_VERSION,
        "architecture": ARCHITECTURE,
        **model_shape(),
        "observation_names": list(OBSERVATION_NAMES),
        "movement_action_names": list(MOVEMENT_ACTION_NAMES),
        "target_action_names": list(TARGET_ACTION_NAMES),
        "ability_action_names": list(ABILITY_ACTION_NAMES),
        "aim_action_names": list(AIM_ACTION_NAMES),
        "option_descriptor_names": list(OPTION_DESCRIPTOR_NAMES),
    }


def validate_model_contract(model: Mapping[str, Any]) -> None:
    if (
        model.get("version") in (1, 2)
        or model.get("observation_version") in (1, 2)
        or model.get("architecture")
        in ("mlp-tanh-two-head-v1", "mlp-tanh-three-head-v2")
        or model.get("observation_size") in (87, 395)
    ):
        raise ValueError(
            "ML bot policy v1/v2 artifacts are incompatible with the strict "
            "policy-v3 loader; train or load policy-v3.json"
        )
    expected = contract_metadata()
    for key, value in expected.items():
        if model.get(key) != value:
            raise ValueError(
                f"policy-v3 model contract mismatch for {key}: "
                f"expected {value!r}, got {model.get(key)!r}"
            )
