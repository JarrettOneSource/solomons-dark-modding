"""Target-, aim-, potion-, and drop-aware semantic expert for v4 bootstrap.

The expert labels the four main action heads. Native skill choices are never
labelled here: the option scorer learns exclusively from choice-event-v4 SMDP
records, so the retired scripted skill manager cannot become ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from . import spec

Array = np.ndarray
FEATURE = {name: index for index, name in enumerate(spec.OBSERVATION_NAMES)}


@dataclass(frozen=True)
class ExpertDataset:
    observations: Array
    movement_masks: Array
    target_masks: Array
    ability_masks: Array
    aim_masks: Array
    movement_actions: Array
    target_actions: Array
    ability_actions: Array
    aim_actions: Array

    def subset(self, indices: Array) -> "ExpertDataset":
        return ExpertDataset(
            **{
                name: getattr(self, name)[indices]
                for name in self.__dataclass_fields__
            }
        )


def _set(row: Array, name: str, value: float) -> None:
    row[FEATURE[name]] = value


def _unit(x: float, y: float) -> tuple[float, float]:
    length = math.hypot(x, y)
    if length <= 1e-12:
        return 0.0, 0.0
    return x / length, y / length


def _direction_action(x: float, y: float, mask: Array) -> int:
    x, y = _unit(x, y)
    if x == 0.0 and y == 0.0:
        return 0
    best = 0
    alignment = -math.inf
    for action, (direction_x, direction_y) in enumerate(
        spec.MOVEMENT_DIRECTIONS
    ):
        if action == 0 or not mask[action]:
            continue
        candidate = x * direction_x + y * direction_y
        if candidate > alignment:
            best = action
            alignment = candidate
    return best


def _make_enemy(
    row: Array,
    slot: int,
    rng: np.random.Generator,
) -> dict[str, float]:
    angle = rng.uniform(-math.pi, math.pi)
    distance = rng.uniform(0.08, 1.0)
    dx, dy = math.cos(angle), math.sin(angle)
    hp = rng.uniform(0.05, 1.0)
    velocity_x, velocity_y = rng.uniform(-0.75, 0.75, size=2)
    prefix = f"enemy_{slot}_"
    values = {
        "present": 1.0,
        "dx": dx,
        "dy": dy,
        "distance_scaled": distance,
        "hp_ratio": hp,
        "radius_scaled": rng.uniform(0.1, 0.8),
        "velocity_dx": velocity_x,
        "velocity_dy": velocity_y,
        "in_primary_range": float(distance <= 0.5),
        "is_current_target": 0.0,
        "facing_dx": rng.uniform(-1.0, 1.0),
        "facing_dy": rng.uniform(-1.0, 1.0),
        "winding_up": float(rng.random() < 0.15),
        "attack_active": float(rng.random() < 0.12),
    }
    for suffix, value in values.items():
        _set(row, prefix + suffix, value)
    return {
        "slot": float(slot),
        "dx": dx,
        "dy": dy,
        "distance": distance,
        "hp": hp,
        "velocity_x": velocity_x,
        "velocity_y": velocity_y,
        "winding_up": values["winding_up"],
    }


def _choose_target(
    enemies: list[dict[str, float]],
    current_slot: int | None,
) -> tuple[int, dict[str, float] | None]:
    if not enemies:
        return 0, None

    def score(enemy: dict[str, float]) -> float:
        return (
            0.72 * enemy["hp"]
            + 0.24 * enemy["distance"]
            - 0.04 * enemy["winding_up"]
        )

    selected = min(enemies, key=score)
    if current_slot is not None:
        current = enemies[current_slot - 1]
        if score(current) <= score(selected) + 0.04:
            return 0, current
    return int(selected["slot"]), selected


def _set_target(row: Array, target: dict[str, float] | None) -> None:
    if target is None:
        return
    _set(row, "target_present", 1.0)
    _set(row, "target_dx", target["dx"])
    _set(row, "target_dy", target["dy"])
    _set(row, "target_distance_scaled", target["distance"])
    _set(row, "target_contact_distance_scaled", target["distance"])
    _set(row, "target_hp_ratio", target["hp"])
    _set(row, "target_in_primary_range", float(target["distance"] <= 0.5))
    _set(row, "target_velocity_dx", target["velocity_x"])
    _set(row, "target_velocity_dy", target["velocity_y"])


def _set_secondaries(
    row: Array,
    rng: np.random.Generator,
    target: dict[str, float] | None,
    mana_ratio: float,
) -> tuple[list[bool], list[bool]]:
    legal: list[bool] = []
    free_aim: list[bool] = []
    count = int(rng.integers(1, 9))
    for slot in range(1, 9):
        prefix = f"secondary_{slot}_"
        occupied = slot <= count
        ready = occupied and rng.random() < 0.86
        mana_cost = rng.uniform(0.015, 0.28)
        affordable = occupied and mana_ratio >= mana_cost
        spell_range = rng.uniform(0.18, 0.95)
        in_range = target is not None and target["distance"] <= spell_range
        is_legal = bool(ready and affordable and in_range)
        is_free = occupied and rng.random() < 0.42
        legal.append(is_legal)
        free_aim.append(is_free)
        if occupied:
            _set(row, prefix + "occupied", 1.0)
            _set(row, prefix + "band_index_scaled", slot / 8.0)
            _set(row, prefix + "mana_cost_scaled", mana_cost)
            _set(row, prefix + "range_scaled", spell_range)
            _set(row, prefix + "cooldown_scaled", rng.uniform(0.0, 1.0))
            _set(row, prefix + "ready", float(ready))
            _set(row, prefix + "affordable", float(affordable))
            _set(row, prefix + "in_range_of_target", float(in_range))
    return legal, free_aim


POTION_TYPES = (
    "stock_health",
    "stock_mana",
    "stock_wizard_chug",
    "stock_antidote",
    "stock_mind_chug",
    "stock_rejuvenation",
    "custom",
)
PERMANENTLY_MASKED_POTIONS = {
    "stock_wizard_chug",
    "stock_antidote",
    "stock_mind_chug",
}


def _set_potions(
    row: Array,
    rng: np.random.Generator,
) -> tuple[list[str | None], list[bool]]:
    slots: list[str | None] = []
    legal: list[bool] = []
    count = int(rng.integers(0, 13))
    for slot in range(1, 13):
        prefix = f"potion_{slot}_"
        if slot > count:
            slots.append(None)
            legal.append(False)
            continue
        potion_type = POTION_TYPES[int(rng.integers(0, len(POTION_TYPES)))]
        slots.append(potion_type)
        actionable = potion_type not in PERMANENTLY_MASKED_POTIONS
        legal.append(actionable)
        _set(row, prefix + "present", 1.0)
        _set(row, prefix + "count_scaled", rng.uniform(0.12, 1.0))
        _set(row, prefix + potion_type, 1.0)
        if potion_type in ("stock_health", "stock_rejuvenation"):
            _set(row, prefix + "restores_hp_fraction", 0.5)
        if potion_type in ("stock_mana", "stock_rejuvenation"):
            _set(row, prefix + "restores_mana_fraction", 0.5)
        if potion_type == "custom":
            _set(row, prefix + "custom_effect_known", 1.0)
            if rng.random() < 0.5:
                _set(row, prefix + "restores_hp_fraction", 0.35)
            else:
                _set(row, prefix + "restores_mana_fraction", 0.35)
    _set(row, "potion_type_count_scaled", count / 12.0)
    _set(row, "potion_total_count_scaled", min(count / 12.0, 1.0))
    return slots, legal


def _choose_ability(
    *,
    row: Array,
    target: dict[str, float] | None,
    hp_ratio: float,
    mana_ratio: float,
    secondary_legal: list[bool],
    potion_types: list[str | None],
    potion_legal: list[bool],
    ability_mask: Array,
) -> int:
    if hp_ratio < 0.38:
        for slot, (kind, legal) in enumerate(
            zip(potion_types, potion_legal, strict=True), start=1
        ):
            if legal and kind in ("stock_health", "stock_rejuvenation", "custom"):
                if row[FEATURE[f"potion_{slot}_restores_hp_fraction"]] > 0.0:
                    return 9 + slot
    if mana_ratio < 0.28:
        for slot, (kind, legal) in enumerate(
            zip(potion_types, potion_legal, strict=True), start=1
        ):
            if legal and kind in ("stock_mana", "stock_rejuvenation", "custom"):
                if row[FEATURE[f"potion_{slot}_restores_mana_fraction"]] > 0.0:
                    return 9 + slot
    if target is None:
        return 0
    legal_slots = [
        slot for slot, legal in enumerate(secondary_legal, start=1) if legal
    ]
    if legal_slots:
        # The selected enemy is known before this range-aware ability choice.
        # A stable lowest-slot tie-break keeps bootstrap supervision learnable;
        # PPO remains free to discover stronger spell-specific preferences.
        return 1 + legal_slots[0]
    if ability_mask[1]:
        return 1
    return 0


def _set_hazard(
    row: Array,
    rng: np.random.Generator,
) -> tuple[float, float]:
    if rng.random() >= 0.55:
        return 0.0, 0.0
    angle = rng.uniform(-math.pi, math.pi)
    dx, dy = math.cos(angle), math.sin(angle)
    _set(row, "hazard_1_present", 1.0)
    _set(row, "hazard_1_type_known", float(rng.random() < 0.85))
    _set(row, "hazard_1_dx", dx)
    _set(row, "hazard_1_dy", dy)
    _set(row, "hazard_1_distance_scaled", rng.uniform(0.02, 0.45))
    _set(row, "hazard_1_time_to_contact_scaled", rng.uniform(0.0, 0.5))
    _set(row, "hazard_count_scaled", rng.uniform(0.05, 0.5))
    return dx, dy


DROP_TYPES = (
    "gold",
    "health_orb",
    "mana_orb",
    "stock_health",
    "stock_mana",
    "stock_wizard_chug",
    "stock_antidote",
    "stock_mind_chug",
    "stock_rejuvenation",
    "custom",
    "equipment",
    "wizard_key",
    "powerup",
    "unknown_item",
)


def _set_pickups(
    row: Array,
    rng: np.random.Generator,
) -> None:
    count = int(rng.integers(0, spec.PICKUP_SLOT_COUNT + 1))
    for slot in range(1, count + 1):
        prefix = f"pickup_{slot}_"
        angle = rng.uniform(-math.pi, math.pi)
        dx, dy = math.cos(angle), math.sin(angle)
        distance = rng.uniform(0.03, 0.75)
        drop_type = DROP_TYPES[int(rng.integers(0, len(DROP_TYPES)))]
        _set(row, prefix + "present", 1.0)
        _set(row, prefix + "dx", dx)
        _set(row, prefix + "dy", dy)
        _set(row, prefix + "distance_scaled", distance)

        if drop_type == "gold":
            _set(row, prefix + "type_gold", 1.0)
        elif drop_type == "health_orb":
            _set(row, prefix + "type_health_orb", 1.0)
        elif drop_type == "mana_orb":
            _set(row, prefix + "type_mana_orb", 1.0)
        elif drop_type == "powerup":
            _set(row, prefix + "type_powerup", 1.0)
        else:
            _set(row, prefix + "type_item_carrier", 1.0)
            _set(row, prefix + "item_stack_count_scaled", rng.uniform(0.15, 0.6))
            _set(row, prefix + "item_amount_scaled", rng.uniform(0.15, 0.6))
            if drop_type != "unknown_item":
                _set(row, prefix + "item_identity_known", 1.0)
                if drop_type == "custom":
                    _set(row, prefix + "item_custom", 1.0)
                elif drop_type == "equipment":
                    _set(row, prefix + "item_is_equipment", 1.0)
                elif drop_type == "wizard_key":
                    _set(row, prefix + "item_is_wizard_key", 1.0)
                else:
                    _set(row, prefix + "item_" + drop_type, 1.0)
    _set(row, "pickup_count_scaled", count / spec.PICKUP_COUNT_SCALE)


def generate_expert_dataset(
    count: int,
    *,
    rng: np.random.Generator,
) -> ExpertDataset:
    if count <= 0:
        raise ValueError("expert dataset count must be positive")
    observations = np.zeros((count, len(spec.OBSERVATION_NAMES)))
    movement_masks = np.ones((count, len(spec.MOVEMENT_ACTION_NAMES)), dtype=np.bool_)
    target_masks = np.zeros((count, len(spec.TARGET_ACTION_NAMES)), dtype=np.bool_)
    ability_masks = np.zeros((count, len(spec.ABILITY_ACTION_NAMES)), dtype=np.bool_)
    aim_masks = np.zeros((count, len(spec.AIM_ACTION_NAMES)), dtype=np.bool_)
    movement_actions = np.zeros(count, dtype=np.int64)
    target_actions = np.zeros(count, dtype=np.int64)
    ability_actions = np.zeros(count, dtype=np.int64)
    aim_actions = np.zeros(count, dtype=np.int64)

    for index, row in enumerate(observations):
        hp_ratio = rng.uniform(0.08, 1.0)
        mana_ratio = rng.uniform(0.05, 1.0)
        _set(row, "self_hp_ratio", hp_ratio)
        _set(row, "self_mana_ratio", mana_ratio)
        _set(row, "self_mana_current_scaled", mana_ratio)
        _set(row, "self_cast_ready", 1.0)
        _set(row, "primary_affordable", float(mana_ratio >= 0.08))
        _set(row, "primary_max_range_scaled", 0.5)
        _set(row, "enemy_count_scaled", 0.0)

        enemy_count = int(rng.integers(0, 9))
        enemies = [
            _make_enemy(row, slot, rng) for slot in range(1, enemy_count + 1)
        ]
        _set(row, "enemy_count_scaled", enemy_count / 8.0)
        current_slot = (
            int(rng.integers(1, enemy_count + 1))
            if enemy_count > 0 and rng.random() < 0.48
            else None
        )
        if current_slot is not None:
            _set(row, f"enemy_{current_slot}_is_current_target", 1.0)
        target_masks[index, 0] = True
        if enemy_count:
            target_masks[index, 1 : enemy_count + 1] = True
        target_action, target = _choose_target(enemies, current_slot)
        target_actions[index] = target_action
        _set_target(row, target)

        secondary_legal, free_aim = _set_secondaries(
            row, rng, target, mana_ratio
        )
        potion_types, potion_legal = _set_potions(row, rng)
        # Drop fixtures use an index-scoped stream so widening observations
        # cannot perturb the established target/ability/aim curriculum RNG.
        drop_rng = np.random.default_rng(0xD09A0000 + index)
        _set_pickups(row, drop_rng)
        wizard_key_count = int(drop_rng.integers(0, 4))
        if wizard_key_count > 0:
            _set(
                row,
                "inventory_wizard_key_count_scaled",
                math.log1p(wizard_key_count) / math.log(100.0),
            )
            _set(row, "inventory_has_wizard_key", 1.0)
        ability_masks[index, 0] = True
        ability_masks[index, 1] = bool(
            target is not None and mana_ratio >= 0.08 and target["distance"] <= 0.5
        )
        for slot, legal in enumerate(secondary_legal, start=2):
            ability_masks[index, slot] = legal
        for slot, legal in enumerate(potion_legal, start=10):
            ability_masks[index, slot] = legal
        ability = _choose_ability(
            row=row,
            target=target,
            hp_ratio=hp_ratio,
            mana_ratio=mana_ratio,
            secondary_legal=secondary_legal,
            potion_types=potion_types,
            potion_legal=potion_legal,
            ability_mask=ability_masks[index],
        )
        ability_actions[index] = ability

        hazard_x, hazard_y = _set_hazard(row, rng)
        aim_masks[index, 0] = True
        aim_x = aim_y = 0.0
        if 2 <= ability <= 9 and free_aim[ability - 2]:
            aim_masks[index, :] = True
            assert target is not None
            aim_x = target["velocity_x"] * 0.72 - hazard_x * 0.38
            aim_y = target["velocity_y"] * 0.72 - hazard_y * 0.38
        aim_actions[index] = _direction_action(
            aim_x, aim_y, aim_masks[index]
        )

        if hp_ratio < 0.30 and enemies:
            move_x, move_y = -enemies[0]["dx"], -enemies[0]["dy"]
        elif hazard_x != 0.0 or hazard_y != 0.0:
            move_x, move_y = -hazard_x, -hazard_y
        elif target is not None and target["distance"] > 0.48:
            move_x, move_y = target["dx"], target["dy"]
        elif target is not None:
            move_x, move_y = -target["dy"], target["dx"]
        else:
            move_x = move_y = 0.0
        _set(row, "suggested_move_dx", move_x)
        _set(row, "suggested_move_dy", move_y)
        movement_actions[index] = _direction_action(
            move_x, move_y, movement_masks[index]
        )

    return ExpertDataset(
        observations=observations,
        movement_masks=movement_masks,
        target_masks=target_masks,
        ability_masks=ability_masks,
        aim_masks=aim_masks,
        movement_actions=movement_actions,
        target_actions=target_actions,
        ability_actions=ability_actions,
        aim_actions=aim_actions,
    )


def split_dataset(
    dataset: ExpertDataset,
    *,
    rng: np.random.Generator,
    validation_fraction: float = 0.2,
) -> tuple[ExpertDataset, ExpertDataset]:
    count = dataset.observations.shape[0]
    if count < 2:
        raise ValueError("expert split requires at least two samples")
    if not 0.0 < validation_fraction < 1.0:
        raise ValueError("validation_fraction must be in (0, 1)")
    order = rng.permutation(count)
    validation_count = max(1, min(count - 1, round(count * validation_fraction)))
    return (
        dataset.subset(order[validation_count:]),
        dataset.subset(order[:validation_count]),
    )
