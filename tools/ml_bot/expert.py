"""Deterministic semantic expert used to bootstrap the shipped policy."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from . import spec

Array = np.ndarray
FEATURE = {
    name: index
    for index, name in enumerate(spec.OBSERVATION_NAMES)
}


@dataclass(frozen=True)
class ExpertDataset:
    observations: Array
    movement_masks: Array
    cast_masks: Array
    movement_actions: Array
    cast_actions: Array

    def subset(self, indices: Array) -> "ExpertDataset":
        return ExpertDataset(
            observations=self.observations[indices],
            movement_masks=self.movement_masks[indices],
            cast_masks=self.cast_masks[indices],
            movement_actions=self.movement_actions[indices],
            cast_actions=self.cast_actions[indices],
        )


def _set(row: Array, name: str, value: float) -> None:
    row[FEATURE[name]] = value


def _direction_action(
    x: float,
    y: float,
    movement_mask: Array,
) -> int:
    length = math.hypot(x, y)
    if length <= 1e-9:
        return 0
    x /= length
    y /= length
    best_action = 0
    best_alignment = -math.inf
    for action, (direction_x, direction_y) in enumerate(
        spec.MOVEMENT_DIRECTIONS
    ):
        if action == 0 or not movement_mask[action]:
            continue
        alignment = x * direction_x + y * direction_y
        if alignment > best_alignment:
            best_action = action
            best_alignment = alignment
    return best_action


def _suggested_movement(row: Array) -> tuple[float, float]:
    hp_ratio = row[FEATURE["self_hp_ratio"]]
    target_present = row[FEATURE["target_present"]] > 0.5
    target_distance = row[FEATURE["target_distance_scaled"]]
    primary_range = row[FEATURE["primary_max_range_scaled"]]
    threat_count = row[FEATURE["threat_count_scaled"]]
    edge_pressure = row[FEATURE["edge_pressure"]]

    if hp_ratio < 0.30 and threat_count > 0.0:
        desired_x = row[FEATURE["escape_dx"]]
        desired_y = row[FEATURE["escape_dy"]]
    elif edge_pressure > 0.82:
        desired_x = row[FEATURE["arena_center_dx"]]
        desired_y = row[FEATURE["arena_center_dy"]]
    elif target_present and target_distance > primary_range * 0.88:
        desired_x = row[FEATURE["target_dx"]]
        desired_y = row[FEATURE["target_dy"]]
    elif target_present and threat_count > 0.0:
        target_x = row[FEATURE["target_dx"]]
        target_y = row[FEATURE["target_dy"]]
        if target_distance < primary_range * 0.42:
            desired_x = row[FEATURE["escape_dx"]]
            desired_y = row[FEATURE["escape_dy"]]
        else:
            orbit_sign = (
                -1.0
                if row[FEATURE["arena_y_normalized"]] > 0.0
                else 1.0
            )
            desired_x = -target_y * orbit_sign
            desired_y = target_x * orbit_sign
    elif edge_pressure > 0.45:
        desired_x = row[FEATURE["arena_center_dx"]]
        desired_y = row[FEATURE["arena_center_dy"]]
    else:
        desired_x = 0.0
        desired_y = 0.0
    return desired_x, desired_y


def _expert_movement(row: Array, movement_mask: Array) -> int:
    return _direction_action(
        row[FEATURE["suggested_move_dx"]],
        row[FEATURE["suggested_move_dy"]],
        movement_mask,
    )


def _expert_cast(row: Array, cast_mask: Array) -> int:
    if (
        row[FEATURE["target_present"]] <= 0.5
        or row[FEATURE["target_in_primary_range"]] <= 0.5
        or row[FEATURE["self_cast_ready"]] <= 0.5
        or row[FEATURE["self_mana_ratio"]] < 0.08
    ):
        return 0

    use_secondary = (
        row[FEATURE["self_mana_ratio"]] > 0.62
        and row[FEATURE["target_hp_ratio"]] > 0.48
        and row[FEATURE["wave_scaled"]] > 0.08
    )
    if use_secondary:
        for action in range(2, len(spec.CAST_ACTION_NAMES)):
            if cast_mask[action]:
                return action
    if cast_mask[1]:
        return 1
    return 0


def _random_unit(rng: np.random.Generator) -> tuple[float, float]:
    angle = rng.uniform(-math.pi, math.pi)
    return math.cos(angle), math.sin(angle)


def _equipped_item_count(row: Array) -> int:
    return sum(
        row[FEATURE[name]] > 0.5
        for name in (
            "hat_equipped",
            "robe_equipped",
            "weapon_equipped",
            "amulet_equipped",
        )
    )


def generate_expert_dataset(
    count: int,
    *,
    rng: np.random.Generator,
) -> ExpertDataset:
    if count <= 0:
        raise ValueError("expert sample count must be positive")

    observation_count = len(spec.OBSERVATION_NAMES)
    movement_count = len(spec.MOVEMENT_ACTION_NAMES)
    cast_count = len(spec.CAST_ACTION_NAMES)
    observations = np.zeros((count, observation_count), dtype=np.float64)
    movement_masks = np.ones((count, movement_count), dtype=np.bool_)
    cast_masks = np.zeros((count, cast_count), dtype=np.bool_)
    cast_masks[:, 0] = True
    movement_actions = np.zeros(count, dtype=np.int64)
    cast_actions = np.zeros(count, dtype=np.int64)

    for index in range(count):
        row = observations[index]
        hp_ratio = rng.uniform(0.06, 1.0)
        mana_ratio = rng.uniform(0.0, 1.0)
        _set(row, "self_hp_ratio", hp_ratio)
        _set(row, "self_mana_ratio", mana_ratio)
        _set(row, "self_level_scaled", rng.uniform(0.03, 0.8))
        _set(row, "wave_scaled", rng.uniform(0.0, 0.75))
        _set(row, "self_move_speed_scaled", rng.uniform(0.25, 0.85))
        _set(row, "self_moving", float(rng.random() < 0.75))
        cast_active = rng.random() < 0.08
        cast_ready = not cast_active and rng.random() < 0.88
        _set(row, "self_cast_active", float(cast_active))
        _set(row, "self_cast_ready", float(cast_ready))
        _set(row, "self_poisoned", float(rng.random() < 0.12))
        _set(row, "self_webbed", float(rng.random() < 0.08))
        _set(row, "self_damage_x4", float(rng.random() < 0.06))
        _set(row, "self_status_active", float(rng.random() < 0.20))

        primary_range = rng.uniform(0.18, 0.52)
        primary_minimum = rng.uniform(0.0, min(0.06, primary_range * 0.2))
        _set(row, "primary_min_range_scaled", primary_minimum)
        _set(row, "primary_max_range_scaled", primary_range)
        _set(row, "primary_available", 1.0)

        target_present = rng.random() < 0.84
        target_x, target_y = _random_unit(rng)
        target_distance = rng.uniform(0.025, 1.0)
        target_radius = rng.uniform(0.01, 0.09)
        target_contact = max(target_distance - target_radius, 0.0)
        target_in_range = (
            target_present
            and target_contact >= primary_minimum
            and target_contact <= primary_range
        )
        _set(row, "target_present", float(target_present))
        if target_present:
            _set(row, "target_dx", target_x)
            _set(row, "target_dy", target_y)
            _set(row, "target_distance_scaled", target_distance)
            _set(row, "target_contact_distance_scaled", target_contact)
            _set(row, "target_hp_ratio", rng.uniform(0.05, 1.0))
            _set(row, "target_radius_scaled", target_radius)
        _set(row, "target_in_primary_range", float(target_in_range))

        enemy_count = int(rng.integers(0, 13))
        if target_present:
            enemy_count = max(enemy_count, 1)
        threat_count = min(enemy_count, int(rng.integers(0, 6)))
        _set(row, "enemy_count_scaled", enemy_count / 16.0)
        _set(row, "threat_count_scaled", threat_count / 8.0)
        if enemy_count > 0:
            _set(row, "nearest_enemy_dx", target_x)
            _set(row, "nearest_enemy_dy", target_y)
            _set(row, "nearest_enemy_distance_scaled", target_distance)
        threat_x, threat_y = _random_unit(rng)
        if threat_count > 0:
            threat_distance = rng.uniform(0.02, 0.42)
            _set(row, "nearest_threat_dx", threat_x)
            _set(row, "nearest_threat_dy", threat_y)
            _set(row, "nearest_threat_distance_scaled", threat_distance)
            _set(row, "escape_dx", -threat_x)
            _set(row, "escape_dy", -threat_y)
        else:
            _set(row, "escape_dx", -target_x if target_present else 0.0)
            _set(row, "escape_dy", -target_y if target_present else 0.0)

        arena_x = rng.uniform(-1.0, 1.0)
        arena_y = rng.uniform(-1.0, 1.0)
        center_length = max(math.hypot(arena_x, arena_y), 1e-9)
        _set(row, "arena_center_dx", -arena_x / center_length)
        _set(row, "arena_center_dy", -arena_y / center_length)
        _set(
            row,
            "arena_center_distance_scaled",
            min(center_length * 0.55, 1.0),
        )
        _set(row, "arena_x_normalized", arena_x)
        _set(row, "arena_y_normalized", arena_y)
        _set(row, "edge_pressure", max(abs(arena_x), abs(arena_y)))

        distinct_items = int(rng.integers(0, 22))
        total_stack = distinct_items + int(rng.integers(0, 28))
        potion_stack = int(rng.integers(0, 9))
        _set(row, "inventory_distinct_scaled", distinct_items / 32.0)
        _set(row, "inventory_stack_scaled", total_stack / 64.0)
        _set(row, "potion_stack_scaled", potion_stack / 16.0)
        equipment_valid = rng.random() < 0.96
        _set(row, "equipment_valid", float(equipment_valid))
        for name in (
            "hat_equipped",
            "robe_equipped",
            "weapon_equipped",
            "amulet_equipped",
        ):
            _set(
                row,
                name,
                float(equipment_valid and rng.random() < 0.72),
            )
        ring_count = (
            int(rng.integers(0, 4)) if equipment_valid else 0
        )
        _set(row, "ring_count_scaled", ring_count / 3.0)
        _set(row, "gold_scaled", rng.uniform(0.0, 1.0))
        _set(row, "progression_active_scaled", rng.uniform(0.02, 0.65))
        _set(row, "progression_visible_scaled", rng.uniform(0.05, 0.8))
        _set(row, "inventory_truncated", float(rng.random() < 0.01))
        _set(row, "progression_truncated", float(rng.random() < 0.01))
        _set(
            row,
            "offensive_damage_multiplier_scaled",
            rng.uniform(0.15, 0.8),
        )
        _set(
            row,
            "offensive_mana_multiplier_scaled",
            rng.uniform(0.15, 0.8),
        )
        _set(row, "cast_speed_multiplier_scaled", rng.uniform(0.15, 0.8))
        _set(
            row,
            "secondary_recharge_multiplier_scaled",
            rng.uniform(0.15, 0.8),
        )

        secondary_count = int(rng.integers(0, 5))
        _set(
            row,
            "secondary_slot_count_scaled",
            secondary_count / 8.0,
        )
        for slot in range(1, 9):
            available = slot <= secondary_count
            _set(row, f"secondary_{slot}_available", float(available))

        element = int(rng.integers(0, 5))
        discipline = int(rng.integers(0, 3))
        for element_index, name in enumerate(
            ("fire", "water", "earth", "air", "ether")
        ):
            _set(
                row,
                f"element_{name}",
                float(element_index == element),
            )
        for discipline_index, name in enumerate(
            ("mind", "body", "arcane")
        ):
            _set(
                row,
                f"discipline_{name}",
                float(discipline_index == discipline),
            )

        _set(row, "hp_delta", rng.uniform(-0.35, 0.12))
        _set(row, "mana_delta", rng.uniform(-0.4, 0.25))
        _set(row, "target_hp_delta", rng.uniform(-0.4, 0.02))
        _set(row, "enemy_count_delta", rng.uniform(-0.5, 0.5))
        previous_action = int(rng.integers(0, movement_count))
        previous_x, previous_y = spec.MOVEMENT_DIRECTIONS[previous_action]
        _set(row, "previous_move_dx", previous_x)
        _set(row, "previous_move_dy", previous_y)
        _set(row, "previous_cast_primary", float(rng.random() < 0.25))
        _set(row, "previous_cast_secondary", float(rng.random() < 0.12))
        _set(row, "time_since_damage_scaled", rng.uniform(0.0, 1.0))
        _set(row, "time_since_cast_scaled", rng.uniform(0.0, 1.0))
        _set(row, "time_since_move_scaled", rng.uniform(0.0, 1.0))

        for action in range(1, movement_count):
            if rng.random() < 0.08:
                movement_masks[index, action] = False
        suggested_x, suggested_y = _suggested_movement(row)
        _set(row, "suggested_move_dx", suggested_x)
        _set(row, "suggested_move_dy", suggested_y)
        movement_actions[index] = _expert_movement(
            row,
            movement_masks[index],
        )

        if target_in_range and cast_ready:
            cast_masks[index, 1] = True
            for slot in range(1, secondary_count + 1):
                cast_masks[index, slot + 1] = True
        cast_actions[index] = _expert_cast(row, cast_masks[index])

        if _equipped_item_count(row) == 0:
            _set(row, "equipment_valid", float(equipment_valid))

    return ExpertDataset(
        observations=observations,
        movement_masks=movement_masks,
        cast_masks=cast_masks,
        movement_actions=movement_actions,
        cast_actions=cast_actions,
    )


def split_dataset(
    dataset: ExpertDataset,
    *,
    rng: np.random.Generator,
    validation_fraction: float = 0.2,
) -> tuple[ExpertDataset, ExpertDataset]:
    count = dataset.observations.shape[0]
    if not 0.0 < validation_fraction < 1.0:
        raise ValueError("validation_fraction must be between zero and one")
    validation_count = max(1, int(round(count * validation_fraction)))
    order = rng.permutation(count)
    return (
        dataset.subset(order[validation_count:]),
        dataset.subset(order[:validation_count]),
    )
