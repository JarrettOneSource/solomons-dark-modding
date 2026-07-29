"""Deterministic target-first semantic expert for policy-v2 bootstrap."""

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
    target_masks: Array
    cast_masks: Array
    movement_actions: Array
    target_actions: Array
    cast_actions: Array

    def subset(self, indices: Array) -> "ExpertDataset":
        return ExpertDataset(
            observations=self.observations[indices],
            movement_masks=self.movement_masks[indices],
            target_masks=self.target_masks[indices],
            cast_masks=self.cast_masks[indices],
            movement_actions=self.movement_actions[indices],
            target_actions=self.target_actions[indices],
            cast_actions=self.cast_actions[indices],
        )


def _set(row: Array, name: str, value: float) -> None:
    row[FEATURE[name]] = value


def _random_unit(rng: np.random.Generator) -> tuple[float, float]:
    angle = rng.uniform(-math.pi, math.pi)
    return math.cos(angle), math.sin(angle)


def _direction_action(x: float, y: float, movement_mask: Array) -> int:
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


def _target_score(enemy: dict[str, float]) -> float:
    # Low-health enemies dominate, then distance and inward velocity. The
    # score depends only on Block D values available to the target head.
    closing_speed = -(
        enemy["dx"] * enemy["velocity_dx"]
        + enemy["dy"] * enemy["velocity_dy"]
    )
    return (
        0.90 * enemy["hp_ratio"]
        + 0.08 * enemy["distance"]
        - 0.02 * closing_speed
    )


def _choose_target(
    enemies: list[dict[str, float]],
    current_slot: int | None,
) -> tuple[int, dict[str, float] | None]:
    if not enemies:
        return 0, None
    best = min(enemies, key=_target_score)
    if current_slot is not None:
        current = enemies[current_slot - 1]
        if _target_score(current) <= _target_score(best) + 0.055:
            return 0, current
    return int(best["slot"]), best


def _suggested_movement(
    *,
    hp_ratio: float,
    movement_target: dict[str, float] | None,
    threat: dict[str, float] | None,
    primary_range: float,
    edge_pressure: float,
    center_x: float,
    center_y: float,
) -> tuple[float, float]:
    if hp_ratio < 0.30 and threat is not None:
        return -threat["dx"], -threat["dy"]
    if edge_pressure > 0.82:
        return center_x, center_y
    if movement_target is None:
        return 0.0, 0.0
    if movement_target["distance"] > primary_range * 0.88:
        return movement_target["dx"], movement_target["dy"]
    if (
        threat is not None
        and movement_target["distance"] < primary_range * 0.42
    ):
        return -threat["dx"], -threat["dy"]
    if threat is not None:
        return -movement_target["dy"], movement_target["dx"]
    return 0.0, 0.0


def _set_target_summary(
    row: Array,
    target: dict[str, float] | None,
    primary_minimum: float,
    primary_range: float,
) -> None:
    _set(row, "primary_min_range_scaled", primary_minimum)
    _set(row, "primary_max_range_scaled", primary_range)
    if target is None:
        return
    contact = max(target["distance"] - target["radius"], 0.0)
    _set(row, "target_present", 1.0)
    _set(row, "target_dx", target["dx"])
    _set(row, "target_dy", target["dy"])
    _set(row, "target_distance_scaled", target["distance"])
    _set(row, "target_contact_distance_scaled", contact)
    _set(row, "target_hp_ratio", target["hp_ratio"])
    _set(row, "target_radius_scaled", target["radius"])
    _set(
        row,
        "target_in_primary_range",
        float(primary_minimum <= contact <= primary_range),
    )


def _set_secondary_descriptors(
    row: Array,
    *,
    rng: np.random.Generator,
    mana_ratio: float,
    current_target: dict[str, float] | None,
) -> list[dict[str, float | bool]]:
    secondary_count = int(rng.integers(0, 9))
    secondaries: list[dict[str, float | bool]] = []
    for slot in range(1, 9):
        prefix = f"secondary_{slot}_"
        occupied = slot <= secondary_count
        descriptor: dict[str, float | bool] = {
            "occupied": occupied,
            "range": 0.0,
            "ready": False,
            "affordable": False,
        }
        if occupied:
            element = int(rng.integers(0, 5))
            mana_cost = rng.uniform(0.015, 0.22)
            spell_range = rng.uniform(0.12, 0.72)
            ready = rng.random() < 0.82
            affordable = mana_ratio >= mana_cost
            descriptor.update(
                {
                    "range": spell_range,
                    "ready": ready,
                    "affordable": affordable,
                }
            )
            _set(row, prefix + "occupied", 1.0)
            for element_index, name in enumerate(
                ("fire", "water", "earth", "air", "ether")
            ):
                _set(
                    row,
                    prefix + "element_" + name,
                    float(element_index == element),
                )
            _set(row, prefix + "band_index_scaled", rng.uniform(0.0, 1.0))
            _set(row, prefix + "mana_cost_scaled", mana_cost)
            _set(row, prefix + "range_scaled", spell_range)
            _set(row, prefix + "cooldown_scaled", rng.uniform(0.0, 1.0))
            _set(row, prefix + "ready", float(ready))
            _set(row, prefix + "affordable", float(affordable))
            in_current_range = (
                current_target is not None
                and current_target["distance"] <= spell_range
            )
            _set(
                row,
                prefix + "in_range_of_target",
                float(in_current_range),
            )
        secondaries.append(descriptor)
    return secondaries


def _build_cast_mask(
    *,
    selected: dict[str, float] | None,
    cast_ready: bool,
    primary_affordable: bool,
    primary_minimum: float,
    primary_range: float,
    secondaries: list[dict[str, float | bool]],
) -> Array:
    mask = np.zeros(len(spec.CAST_ACTION_NAMES), dtype=np.bool_)
    mask[0] = True
    if selected is None or not cast_ready:
        return mask
    contact = max(selected["distance"] - selected["radius"], 0.0)
    mask[1] = (
        primary_affordable
        and primary_minimum <= contact <= primary_range
    )
    for slot, secondary in enumerate(secondaries, start=1):
        mask[slot + 1] = bool(
            secondary["occupied"]
            and secondary["ready"]
            and secondary["affordable"]
            and selected["distance"] <= float(secondary["range"])
        )
    return mask


def _choose_cast(
    row: Array,
    mask: Array,
    selected: dict[str, float] | None,
) -> int:
    if selected is None:
        return 0
    use_secondary = (
        row[FEATURE["self_mana_ratio"]] > 0.58
        and selected["hp_ratio"] > 0.36
        and row[FEATURE["wave_scaled"]] > 0.06
    )
    if use_secondary:
        for action in range(2, len(spec.CAST_ACTION_NAMES)):
            if mask[action]:
                return action
    if mask[1]:
        return 1
    for action in range(2, len(spec.CAST_ACTION_NAMES)):
        if mask[action]:
            return action
    return 0


def _set_environment_features(
    row: Array,
    *,
    rng: np.random.Generator,
    enemies: list[dict[str, float]],
    movement_target: dict[str, float] | None,
    hp_ratio: float,
    primary_range: float,
) -> tuple[float, float]:
    for direction in (
        "east",
        "southeast",
        "south",
        "southwest",
        "west",
        "northwest",
        "north",
        "northeast",
    ):
        _set(row, f"clearance_{direction}_scaled", rng.uniform(0.1, 1.0))
    for patch_row in range(1, 8):
        for column in range(1, 8):
            if patch_row != 4 or column != 4:
                _set(
                    row,
                    f"walkability_patch_row_{patch_row}_col_{column}",
                    float(rng.random() > 0.14),
                )

    pickup_count = int(rng.integers(0, 7))
    for slot in range(1, 5):
        prefix = f"pickup_{slot}_"
        if slot > pickup_count:
            continue
        pickup_x, pickup_y = _random_unit(rng)
        _set(row, prefix + "present", 1.0)
        _set(row, prefix + "dx", pickup_x)
        _set(row, prefix + "dy", pickup_y)
        _set(row, prefix + "distance_scaled", rng.uniform(0.02, 0.9))
        kind = int(rng.integers(0, 4))
        for kind_index, name in enumerate(
            ("gold", "health_orb", "mana_orb", "item_carrier")
        ):
            _set(
                row,
                prefix + "type_" + name,
                float(kind_index == kind),
            )
    _set(row, "pickup_count_scaled", pickup_count / 8.0)

    ally_count = int(rng.integers(0, 9))
    for slot in range(1, 5):
        prefix = f"ally_{slot}_"
        if slot > ally_count:
            continue
        ally_x, ally_y = _random_unit(rng)
        intent_x, intent_y = _random_unit(rng)
        _set(row, prefix + "present", 1.0)
        _set(row, prefix + "dx", ally_x)
        _set(row, prefix + "dy", ally_y)
        _set(row, prefix + "distance_scaled", rng.uniform(0.03, 1.0))
        _set(row, prefix + "hp_ratio", rng.uniform(0.05, 1.0))
        _set(row, prefix + "mana_ratio", rng.uniform(0.0, 1.0))
        _set(row, prefix + "alive", float(rng.random() > 0.08))
        _set(row, prefix + "is_human", float(rng.random() < 0.45))
        _set(row, prefix + "intent_dx", intent_x)
        _set(row, prefix + "intent_dy", intent_y)
    _set(row, "ally_count_scaled", ally_count / 50.0)

    threat_count = sum(enemy["distance"] < 0.34 for enemy in enemies)
    _set(row, "enemy_count_scaled", len(enemies) / 16.0)
    _set(row, "threat_count_scaled", threat_count / 8.0)
    nearest = enemies[0] if enemies else None
    if nearest is not None:
        _set(row, "nearest_enemy_dx", nearest["dx"])
        _set(row, "nearest_enemy_dy", nearest["dy"])
        _set(row, "nearest_enemy_distance_scaled", nearest["distance"])
    threat = next(
        (enemy for enemy in enemies if enemy["distance"] < 0.34),
        None,
    )
    if threat is not None:
        _set(row, "nearest_threat_dx", threat["dx"])
        _set(row, "nearest_threat_dy", threat["dy"])
        _set(row, "nearest_threat_distance_scaled", threat["distance"])
        _set(row, "escape_dx", -threat["dx"])
        _set(row, "escape_dy", -threat["dy"])

    arena_x = rng.uniform(-1.0, 1.0)
    arena_y = rng.uniform(-1.0, 1.0)
    center_length = max(math.hypot(arena_x, arena_y), 1e-9)
    center_x = -arena_x / center_length
    center_y = -arena_y / center_length
    edge_pressure = max(abs(arena_x), abs(arena_y))
    _set(row, "arena_center_dx", center_x)
    _set(row, "arena_center_dy", center_y)
    _set(
        row,
        "arena_center_distance_scaled",
        min(center_length * 0.55, 1.0),
    )
    _set(row, "arena_x_normalized", arena_x)
    _set(row, "arena_y_normalized", arena_y)
    _set(row, "edge_pressure", edge_pressure)
    suggested_x, suggested_y = _suggested_movement(
        hp_ratio=hp_ratio,
        movement_target=movement_target,
        threat=threat,
        primary_range=primary_range,
        edge_pressure=edge_pressure,
        center_x=center_x,
        center_y=center_y,
    )
    _set(row, "suggested_move_dx", suggested_x)
    _set(row, "suggested_move_dy", suggested_y)
    return suggested_x, suggested_y


def generate_expert_dataset(
    count: int,
    *,
    rng: np.random.Generator,
) -> ExpertDataset:
    if count <= 0:
        raise ValueError("expert sample count must be positive")

    observations = np.zeros(
        (count, len(spec.OBSERVATION_NAMES)),
        dtype=np.float64,
    )
    movement_masks = np.ones(
        (count, len(spec.MOVEMENT_ACTION_NAMES)),
        dtype=np.bool_,
    )
    target_masks = np.zeros(
        (count, len(spec.TARGET_ACTION_NAMES)),
        dtype=np.bool_,
    )
    cast_masks = np.zeros(
        (count, len(spec.CAST_ACTION_NAMES)),
        dtype=np.bool_,
    )
    movement_actions = np.zeros(count, dtype=np.int64)
    target_actions = np.zeros(count, dtype=np.int64)
    cast_actions = np.zeros(count, dtype=np.int64)

    for index, row in enumerate(observations):
        hp_ratio = rng.uniform(0.06, 1.0)
        mana_ratio = rng.uniform(0.0, 1.0)
        max_mana = rng.uniform(50.0, 1625.0)
        max_hp = rng.uniform(50.0, 875.0)
        _set(row, "self_hp_ratio", hp_ratio)
        _set(row, "self_mana_ratio", mana_ratio)
        _set(row, "self_level_scaled", rng.uniform(0.03, 0.8))
        _set(row, "wave_scaled", rng.uniform(0.0, 0.75))
        _set(row, "self_move_speed_scaled", rng.uniform(0.12, 0.85))
        _set(row, "self_moving", float(rng.random() < 0.75))
        cast_active = rng.random() < 0.08
        cast_ready = not cast_active and rng.random() < 0.88
        _set(row, "self_cast_active", float(cast_active))
        _set(row, "self_cast_ready", float(cast_ready))
        _set(row, "self_poisoned", float(rng.random() < 0.12))
        _set(row, "self_webbed", float(rng.random() < 0.08))
        _set(row, "self_damage_x4", float(rng.random() < 0.06))
        _set(row, "self_status_active", float(rng.random() < 0.20))
        _set(row, "self_mana_current_scaled", mana_ratio * max_mana / 2000.0)
        _set(row, "self_mana_max_scaled", max_mana / 2000.0)
        _set(row, "self_hp_max_scaled", max_hp / 1000.0)

        primary_element = int(rng.integers(0, 5))
        for element_index, name in enumerate(
            ("fire", "water", "earth", "air", "ether")
        ):
            _set(
                row,
                "primary_element_" + name,
                float(element_index == primary_element),
            )
            _set(
                row,
                "element_" + name,
                float(element_index == primary_element),
            )
        welded = rng.random() < 0.18
        primary_cost = rng.uniform(0.015, 0.16)
        primary_minimum = rng.uniform(0.0, 0.05)
        primary_range = rng.uniform(0.18, 0.62)
        primary_affordable = mana_ratio >= primary_cost
        _set(row, "primary_welded", float(welded))
        _set(row, "primary_build_index_scaled", rng.uniform(0.0, 0.9))
        _set(row, "primary_mana_cost_scaled", primary_cost)
        _set(row, "primary_range_min_scaled", primary_minimum)
        _set(row, "primary_range_max_scaled", primary_range)
        _set(row, "primary_affordable", float(primary_affordable))

        enemy_count = int(rng.integers(0, 9))
        enemies: list[dict[str, float]] = []
        distances = sorted(rng.uniform(0.03, 1.0, size=enemy_count))
        for slot, distance in enumerate(distances, start=1):
            direction_x, direction_y = _random_unit(rng)
            velocity_x, velocity_y = rng.uniform(-0.45, 0.45, size=2)
            radius = rng.uniform(0.01, 0.09)
            enemy = {
                "slot": float(slot),
                "dx": direction_x,
                "dy": direction_y,
                "distance": float(distance),
                "hp_ratio": float(rng.uniform(0.04, 1.0)),
                "radius": radius,
                "velocity_dx": float(velocity_x),
                "velocity_dy": float(velocity_y),
            }
            enemies.append(enemy)

        current_slot = None
        if enemies and rng.random() < 0.58:
            current_slot = int(rng.integers(1, len(enemies) + 1))
        current_target = (
            enemies[current_slot - 1]
            if current_slot is not None
            else None
        )
        for enemy in enemies:
            slot = int(enemy["slot"])
            prefix = f"enemy_{slot}_"
            contact = max(enemy["distance"] - enemy["radius"], 0.0)
            _set(row, prefix + "present", 1.0)
            _set(row, prefix + "dx", enemy["dx"])
            _set(row, prefix + "dy", enemy["dy"])
            _set(row, prefix + "distance_scaled", enemy["distance"])
            _set(row, prefix + "hp_ratio", enemy["hp_ratio"])
            _set(row, prefix + "radius_scaled", enemy["radius"])
            _set(row, prefix + "velocity_dx", enemy["velocity_dx"])
            _set(row, prefix + "velocity_dy", enemy["velocity_dy"])
            _set(
                row,
                prefix + "in_primary_range",
                float(primary_minimum <= contact <= primary_range),
            )
            _set(
                row,
                prefix + "is_current_target",
                float(slot == current_slot),
            )

        # Block E contains only the persisted pre-decision target. The target
        # label below is derived from Block D, never copied from this wrapper
        # summary, which prevents v1 wrapper-selected target supervision.
        _set_target_summary(
            row,
            current_target,
            primary_minimum,
            primary_range,
        )
        target_masks[index, 0] = current_target is not None or not enemies
        for enemy in enemies:
            target_masks[index, int(enemy["slot"])] = True
        target_action, selected = _choose_target(enemies, current_slot)
        target_actions[index] = target_action

        secondaries = _set_secondary_descriptors(
            row,
            rng=rng,
            mana_ratio=mana_ratio,
            current_target=current_target,
        )
        cast_masks[index] = _build_cast_mask(
            selected=selected,
            cast_ready=cast_ready,
            primary_affordable=primary_affordable,
            primary_minimum=primary_minimum,
            primary_range=primary_range,
            secondaries=secondaries,
        )
        cast_actions[index] = _choose_cast(
            row,
            cast_masks[index],
            selected,
        )

        for action in range(1, len(spec.MOVEMENT_ACTION_NAMES)):
            if rng.random() < 0.08:
                movement_masks[index, action] = False
        suggested_x, suggested_y = _set_environment_features(
            row,
            rng=rng,
            enemies=enemies,
            movement_target=(
                current_target
                if current_target is not None
                else (enemies[0] if enemies else None)
            ),
            hp_ratio=hp_ratio,
            primary_range=primary_range,
        )
        movement_actions[index] = _direction_action(
            suggested_x,
            suggested_y,
            movement_masks[index],
        )

        discipline = int(rng.integers(0, 3))
        for discipline_index, name in enumerate(("mind", "body", "arcane")):
            _set(
                row,
                "discipline_" + name,
                float(discipline_index == discipline),
            )
        _set(row, "hp_delta", rng.uniform(-0.35, 0.12))
        _set(row, "mana_delta", rng.uniform(-0.4, 0.25))
        _set(row, "target_hp_delta", rng.uniform(-0.4, 0.02))
        _set(row, "enemy_count_delta", rng.uniform(-0.5, 0.5))
        previous_action = int(
            rng.integers(0, len(spec.MOVEMENT_ACTION_NAMES))
        )
        previous_x, previous_y = spec.MOVEMENT_DIRECTIONS[previous_action]
        _set(row, "previous_move_dx", previous_x)
        _set(row, "previous_move_dy", previous_y)
        _set(row, "previous_cast_primary", float(rng.random() < 0.25))
        _set(row, "previous_cast_secondary", float(rng.random() < 0.12))
        _set(row, "time_since_damage_scaled", rng.uniform(0.0, 1.0))
        _set(row, "time_since_cast_scaled", rng.uniform(0.0, 1.0))
        _set(row, "time_since_move_scaled", rng.uniform(0.0, 1.0))
        _set(
            row,
            "previous_target_action_scaled",
            rng.integers(0, 9) / 8.0,
        )
        _set(row, "previous_target_switched", float(rng.random() < 0.42))
        _set(row, "has_spell_welding_skill", float(welded))
        _set(row, "weld_offer_pending", float(rng.random() < 0.03))
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

    return ExpertDataset(
        observations=observations,
        movement_masks=movement_masks,
        target_masks=target_masks,
        cast_masks=cast_masks,
        movement_actions=movement_actions,
        target_actions=target_actions,
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
