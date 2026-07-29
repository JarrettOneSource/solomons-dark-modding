"""Exact policy-v2 model and rollout contracts shared by training tools."""

from __future__ import annotations

from typing import Any, Mapping

MODEL_FORMAT = "solomon-dark-bot-policy"
MODEL_VERSION = 2
OBSERVATION_VERSION = 2
TRAJECTORY_VERSION = 2
ARCHITECTURE = "mlp-tanh-three-head-v2"
HIDDEN_SIZES = (192, 96)

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

# The target head receives twice the entropy pressure of movement/cast so a
# fresh PPO run keeps exploring enemy-slot changes instead of collapsing onto
# the often-legal keep_current action.
MOVEMENT_ENTROPY_COEFFICIENT = 0.01
TARGET_ENTROPY_COEFFICIENT = 0.02
CAST_ENTROPY_COEFFICIENT = 0.01


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
    if len(names) != 395:
        raise AssertionError(
            f"policy-v2 observation contract has {len(names)} names, expected 395"
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

CAST_ACTION_NAMES = (
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
)

TRAJECTORY_FIELDS = (
    "trajectory_version",
    "episode_id",
    "participant_id",
    "simulation_tick",
    "observation",
    "movement_mask",
    "target_mask",
    "cast_mask",
    "movement_action",
    "target_action",
    "cast_action",
    "old_log_probability",
    "old_value",
    "reward",
    "done",
)


def model_shape() -> dict[str, object]:
    return {
        "observation_size": len(OBSERVATION_NAMES),
        "hidden_sizes": list(HIDDEN_SIZES),
        "movement_action_size": len(MOVEMENT_ACTION_NAMES),
        "target_action_size": len(TARGET_ACTION_NAMES),
        "cast_action_size": len(CAST_ACTION_NAMES),
        "value_size": 1,
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
        "cast_action_names": list(CAST_ACTION_NAMES),
    }


def validate_model_contract(model: Mapping[str, Any]) -> None:
    if (
        model.get("version") == 1
        or model.get("observation_version") == 1
        or model.get("architecture") == "mlp-tanh-two-head-v1"
    ):
        raise ValueError(
            "ML bot policy v1 artifacts are incompatible with the strict "
            "policy-v2 loader; train or load policy-v2.json"
        )
    expected = contract_metadata()
    for key, value in expected.items():
        if model.get(key) != value:
            raise ValueError(
                f"policy-v2 model contract mismatch for {key}: "
                f"expected {value!r}, got {model.get(key)!r}"
            )
