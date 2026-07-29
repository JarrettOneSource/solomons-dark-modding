"""Single-source policy and rollout contracts shared by training tools."""

from __future__ import annotations

MODEL_FORMAT = "solomon-dark-bot-policy"
MODEL_VERSION = 1
OBSERVATION_VERSION = 1
TRAJECTORY_VERSION = 1
ARCHITECTURE = "mlp-tanh-two-head-v1"
HIDDEN_SIZE = 48

OBSERVATION_NAMES = (
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
    "inventory_distinct_scaled",
    "inventory_stack_scaled",
    "potion_stack_scaled",
    "equipment_valid",
    "hat_equipped",
    "robe_equipped",
    "weapon_equipped",
    "ring_count_scaled",
    "amulet_equipped",
    "gold_scaled",
    "progression_active_scaled",
    "progression_visible_scaled",
    "secondary_slot_count_scaled",
    "inventory_truncated",
    "progression_truncated",
    "offensive_damage_multiplier_scaled",
    "offensive_mana_multiplier_scaled",
    "cast_speed_multiplier_scaled",
    "secondary_recharge_multiplier_scaled",
    "primary_available",
    "secondary_1_available",
    "secondary_2_available",
    "secondary_3_available",
    "secondary_4_available",
    "secondary_5_available",
    "secondary_6_available",
    "secondary_7_available",
    "secondary_8_available",
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
)

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
    "cast_mask",
    "movement_action",
    "cast_action",
    "old_log_probability",
    "old_value",
    "reward",
    "done",
)


def model_shape() -> dict[str, int]:
    return {
        "observation_size": len(OBSERVATION_NAMES),
        "hidden_size": HIDDEN_SIZE,
        "movement_action_size": len(MOVEMENT_ACTION_NAMES),
        "cast_action_size": len(CAST_ACTION_NAMES),
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
        "cast_action_names": list(CAST_ACTION_NAMES),
    }


def validate_model_contract(model: dict[str, object]) -> None:
    expected = contract_metadata()
    for key, value in expected.items():
        if model.get(key) != value:
            raise ValueError(
                f"model contract mismatch for {key}: "
                f"expected {value!r}, got {model.get(key)!r}"
            )
