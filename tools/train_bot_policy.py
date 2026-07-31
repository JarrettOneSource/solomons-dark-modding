#!/usr/bin/env python3
"""Bootstrap, validate, and export the Lua Bots policy."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Sequence

import numpy as np

from ml_bot import spec
from ml_bot.expert import ExpertDataset, generate_expert_dataset, split_dataset
from ml_bot.model import (
    Adam,
    BotPolicy,
    ChoiceCoverage,
    behavior_clone_batch,
    choice_ppo_epochs,
    classification_accuracy,
    export_lua_weights,
    generalized_advantage_estimate,
    load_model,
    ppo_epochs,
    save_model,
    smdp_advantage_estimate,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "bot-brain" / "policy-v3.json"
DEFAULT_LUA = (
    ROOT / "mods" / "bot-brain" / "scripts" / "policy_weights.lua"
)
if os.name == "nt":
    DEFAULT_GAME_DIRECTORY = Path(
        "C:/Users/User/Documents/GitHub/SB Modding/"
        "Solomon Dark/SolomonDarkAbandonware"
    )
else:
    DEFAULT_GAME_DIRECTORY = Path(
        "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
        "Solomon Dark/SolomonDarkAbandonware"
    )
DEFAULT_LAUNCHER = (
    ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"
)
# A single choice-event response contains every reward in its semi-Markov
# interval. At 17 significant digits, this bound plus the maximum observation
# and option descriptors remains below the loader's 1-MiB response ceiling.
MAX_LIVE_ROLLOUT_STEPS = 8192
# A bootstrap policy can take several minutes to earn its first credited kill.
# This window measures only whether any XP reaches learned progression; it is
# deliberately not a time budget for earning a full level or skill choice.
DEFAULT_WAVE_INTEGRATION_TIMEOUT_SECONDS = 300.0


def _batch(
    dataset: ExpertDataset,
    indices: np.ndarray,
) -> tuple[np.ndarray, ...]:
    return (
        dataset.observations[indices],
        dataset.movement_masks[indices],
        dataset.target_masks[indices],
        dataset.ability_masks[indices],
        dataset.aim_masks[indices],
        dataset.movement_actions[indices],
        dataset.target_actions[indices],
        dataset.ability_actions[indices],
        dataset.aim_actions[indices],
    )


def _accuracies(
    policy: BotPolicy,
    dataset: ExpertDataset,
) -> tuple[float, float, float, float, float]:
    return classification_accuracy(
        policy,
        dataset.observations,
        dataset.movement_masks,
        dataset.target_masks,
        dataset.ability_masks,
        dataset.aim_masks,
        dataset.movement_actions,
        dataset.target_actions,
        dataset.ability_actions,
        dataset.aim_actions,
    )


def bootstrap(args: argparse.Namespace) -> int:
    data_rng = np.random.default_rng(args.seed)
    split_rng = np.random.default_rng(args.seed + 1)
    training_rng = np.random.default_rng(args.seed + 2)
    policy_rng = np.random.default_rng(args.seed + 3)
    dataset = generate_expert_dataset(args.samples, rng=data_rng)
    training, validation = split_dataset(dataset, rng=split_rng)
    policy = BotPolicy.initialize(
        policy_rng,
        metadata={
            "training_kind": "target_aim_potion_semantic_bootstrap_v3",
            "seed": args.seed,
            "expert_samples": args.samples,
            "movement_entropy_coefficient": (
                spec.MOVEMENT_ENTROPY_COEFFICIENT
            ),
            "target_entropy_coefficient": spec.TARGET_ENTROPY_COEFFICIENT,
            "ability_entropy_coefficient": (
                spec.ABILITY_ENTROPY_COEFFICIENT
            ),
            "aim_entropy_coefficient": spec.AIM_ENTROPY_COEFFICIENT,
            "choice_entropy_coefficient": spec.CHOICE_ENTROPY_COEFFICIENT,
            "choice_temperature_schedule": "1.25_to_1.0_after_coverage_20",
        },
    )
    optimizer = Adam(
        policy.parameter_arrays(),
        learning_rate=args.learning_rate,
    )

    last_loss = 0.0
    last_gradient_norm = 0.0
    for epoch in range(args.epochs):
        order = training_rng.permutation(training.observations.shape[0])
        for start in range(0, len(order), args.batch_size):
            indices = order[start : start + args.batch_size]
            last_loss, last_gradient_norm = behavior_clone_batch(
                policy,
                optimizer,
                *_batch(training, indices),
            )
        movement, target, ability, aim, joint = _accuracies(
            policy, validation
        )
        print(
            json.dumps(
                {
                    "epoch": epoch + 1,
                    "loss": last_loss,
                    "gradient_norm": last_gradient_norm,
                    "validation_movement_accuracy": movement,
                    "validation_target_accuracy": target,
                    "validation_ability_accuracy": ability,
                    "validation_aim_accuracy": aim,
                    "validation_joint_accuracy": joint,
                },
                sort_keys=True,
            )
        )

    training_accuracy = _accuracies(policy, training)
    validation_accuracy = _accuracies(policy, validation)
    gates = {
        "movement": args.minimum_movement_accuracy,
        "target": args.minimum_target_accuracy,
        "ability": args.minimum_ability_accuracy,
        "aim": args.minimum_aim_accuracy,
        "joint": args.minimum_joint_accuracy,
    }
    actual = {
        "movement": validation_accuracy[0],
        "target": validation_accuracy[1],
        "ability": validation_accuracy[2],
        "aim": validation_accuracy[3],
        "joint": validation_accuracy[4],
    }
    failed = [
        name
        for name, minimum in gates.items()
        if actual[name] < minimum
    ]
    if failed:
        raise RuntimeError(
            "bootstrap accuracy gate failed: "
            + ", ".join(
                f"{name}={actual[name]:.4f} < {gates[name]:.4f}"
                for name in failed
            )
        )

    policy.value_weight.fill(0.0)
    policy.value_bias.fill(0.0)
    policy.choice_value_weight.fill(0.0)
    policy.choice_value_bias.fill(0.0)
    policy.metadata.update(
        {
            "training_movement_accuracy": training_accuracy[0],
            "training_target_accuracy": training_accuracy[1],
            "training_ability_accuracy": training_accuracy[2],
            "training_aim_accuracy": training_accuracy[3],
            "training_joint_accuracy": training_accuracy[4],
            "validation_movement_accuracy": validation_accuracy[0],
            "validation_target_accuracy": validation_accuracy[1],
            "validation_ability_accuracy": validation_accuracy[2],
            "validation_aim_accuracy": validation_accuracy[3],
            "validation_joint_accuracy": validation_accuracy[4],
        }
    )
    model_path = Path(args.model).resolve()
    lua_path = Path(args.lua).resolve()
    save_model(policy, model_path)
    export_lua_weights(policy, lua_path)
    print(
        json.dumps(
            {
                "status": "ok",
                "model": str(model_path),
                "lua": str(lua_path),
                "shape": spec.model_shape(),
                "training_accuracy": {
                    "movement": training_accuracy[0],
                    "target": training_accuracy[1],
                    "ability": training_accuracy[2],
                    "aim": training_accuracy[3],
                    "joint": training_accuracy[4],
                },
                "validation_accuracy": actual,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def validate(args: argparse.Namespace) -> int:
    policy = load_model(Path(args.model))
    if args.lua:
        export_lua_weights(policy, Path(args.lua))
    print(
        json.dumps(
            {
                "status": "ok",
                "model": str(Path(args.model).resolve()),
                "shape": spec.model_shape(),
                "metadata": policy.metadata,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def prepare_rollout_batch(
    records: Sequence[object],
    bootstrap_records: Sequence[object],
    *,
    gamma: float,
    gae_lambda: float,
) -> dict[str, np.ndarray]:
    """Convert validated bridge records into one PPO update batch."""

    if not records:
        raise ValueError("live PPO requires at least one rollout record")

    observations = np.asarray(
        [record.observation for record in records],
        dtype=np.float64,
    )
    movement_masks = np.asarray(
        [record.movement_mask for record in records],
        dtype=np.bool_,
    )
    target_masks = np.asarray(
        [record.target_mask for record in records],
        dtype=np.bool_,
    )
    ability_masks = np.asarray(
        [record.ability_mask for record in records],
        dtype=np.bool_,
    )
    aim_masks = np.asarray(
        [record.aim_mask for record in records],
        dtype=np.bool_,
    )
    movement_actions = np.asarray(
        [record.movement_action for record in records],
        dtype=np.int64,
    )
    target_actions = np.asarray(
        [record.target_action for record in records],
        dtype=np.int64,
    )
    ability_actions = np.asarray(
        [record.ability_action for record in records],
        dtype=np.int64,
    )
    aim_actions = np.asarray(
        [record.aim_action for record in records],
        dtype=np.int64,
    )
    old_log_probabilities = np.asarray(
        [record.old_log_probability for record in records],
        dtype=np.float64,
    )
    old_values = np.asarray(
        [record.old_value for record in records],
        dtype=np.float64,
    )
    rewards = np.asarray(
        [record.reward for record in records],
        dtype=np.float64,
    )
    dones = np.asarray(
        [record.done for record in records],
        dtype=np.bool_,
    )
    for name, value in (
        ("observations", observations),
        ("old_log_probabilities", old_log_probabilities),
        ("old_values", old_values),
        ("rewards", rewards),
    ):
        if not np.all(np.isfinite(value)):
            raise FloatingPointError(f"{name} contains a non-finite value")

    groups: dict[tuple[int, int], list[int]] = {}
    for index, record in enumerate(records):
        key = (record.episode_id, record.participant_id)
        groups.setdefault(key, []).append(index)

    bootstrap_values: dict[tuple[int, int], float] = {}
    for record in bootstrap_records:
        key = (record.episode_id, record.participant_id)
        bootstrap_values.setdefault(key, float(record.old_value))

    advantages = np.zeros(len(records), dtype=np.float64)
    returns = np.zeros(len(records), dtype=np.float64)
    for key, indices in groups.items():
        ticks = [records[index].simulation_tick for index in indices]
        if any(right <= left for left, right in zip(ticks, ticks[1:])):
            raise ValueError(
                "simulation ticks are not strictly increasing within "
                f"trajectory {key}"
            )
        last_index = indices[-1]
        bootstrap_value = 0.0
        if not dones[last_index]:
            bootstrap_value = bootstrap_values.get(
                key,
                float(old_values[last_index]),
            )
        group_advantages, group_returns = generalized_advantage_estimate(
            rewards[indices],
            old_values[indices],
            dones[indices],
            bootstrap_value=bootstrap_value,
            gamma=gamma,
            gae_lambda=gae_lambda,
        )
        advantages[indices] = group_advantages
        returns[indices] = group_returns

    return {
        "observations": observations,
        "movement_masks": movement_masks,
        "target_masks": target_masks,
        "ability_masks": ability_masks,
        "aim_masks": aim_masks,
        "movement_actions": movement_actions,
        "target_actions": target_actions,
        "ability_actions": ability_actions,
        "aim_actions": aim_actions,
        "old_log_probabilities": old_log_probabilities,
        "advantages": advantages,
        "returns": returns,
        "rewards": rewards,
        "dones": dones,
    }


def prepare_choice_batch(
    records: Sequence[object],
    *,
    gamma: float,
    gae_lambda: float,
) -> dict[str, object]:
    """Build one complete variable-duration choice-event-v3 PPO batch."""

    if not records:
        raise ValueError("choice PPO requires at least one complete interval")
    if any(
        record.choice_mode != "learned" or not record.trainable
        for record in records
    ):
        raise ValueError("choice PPO accepts learned trainable records only")
    option_count = max(len(record.option_descriptors) for record in records)
    observations = np.asarray(
        [record.observation for record in records], dtype=np.float64
    )
    descriptors = np.zeros(
        (len(records), option_count, len(spec.OPTION_DESCRIPTOR_NAMES)),
        dtype=np.float64,
    )
    masks = np.zeros((len(records), option_count), dtype=np.bool_)
    for row, record in enumerate(records):
        count = len(record.option_descriptors)
        descriptors[row, :count] = np.asarray(
            record.option_descriptors, dtype=np.float64
        )
        masks[row, :count] = np.asarray(record.option_mask, dtype=np.bool_)
    selected = np.asarray(
        [record.selected_option for record in records], dtype=np.int64
    )
    old_log_probabilities = np.asarray(
        [record.old_log_probability for record in records], dtype=np.float64
    )
    old_values = np.asarray(
        [record.old_value for record in records], dtype=np.float64
    )
    next_values = np.asarray(
        [record.next_value for record in records], dtype=np.float64
    )
    durations = np.asarray(
        [record.duration_steps for record in records], dtype=np.int64
    )
    dones = np.asarray([record.done for record in records], dtype=np.bool_)
    groups: dict[tuple[int, int], list[int]] = {}
    for index, record in enumerate(records):
        groups.setdefault(
            (record.episode_id, record.participant_id), []
        ).append(index)
    advantages = np.zeros(len(records), dtype=np.float64)
    returns = np.zeros(len(records), dtype=np.float64)
    for key, indices in groups.items():
        ticks = [records[index].simulation_tick for index in indices]
        if any(right <= left for left, right in zip(ticks, ticks[1:])):
            raise ValueError(
                "choice event ticks are not strictly increasing within "
                f"trajectory {key}"
            )
        group_advantages, group_returns = smdp_advantage_estimate(
            [
                np.asarray(records[index].rewards, dtype=np.float64)
                for index in indices
            ],
            durations[indices],
            old_values[indices],
            next_values[indices],
            dones[indices],
            gamma=gamma,
            gae_lambda=gae_lambda,
        )
        advantages[indices] = group_advantages
        returns[indices] = group_returns
    arrays = (
        observations,
        descriptors,
        old_log_probabilities,
        old_values,
        next_values,
        advantages,
        returns,
    )
    if not all(np.all(np.isfinite(value)) for value in arrays):
        raise FloatingPointError("choice batch contains a non-finite value")
    return {
        "observations": observations,
        "option_descriptors": descriptors,
        "option_masks": masks,
        "selected_options": selected,
        "old_log_probabilities": old_log_probabilities,
        "advantages": advantages,
        "returns": returns,
        "durations": durations,
        "dones": dones,
        "accepted": np.asarray(
            [record.accepted for record in records], dtype=np.bool_
        ),
    }


def partition_choice_records(
    records: Sequence[object],
) -> tuple[list[object], list[object]]:
    """Separate strict learned and scripted choice-event-v3 records."""

    learned: list[object] = []
    scripted: list[object] = []
    for record in records:
        if record.choice_mode == "learned" and record.trainable:
            learned.append(record)
        elif record.choice_mode == "scripted" and not record.trainable:
            scripted.append(record)
        else:
            raise ValueError(
                "choice record mode and trainable flag disagree"
            )
    return learned, scripted


def validate_natural_choice_proof_records(
    records: Sequence[object],
    *,
    required: bool,
) -> None:
    """Keep the strict natural-choice gate acceptance-only."""

    if not required:
        return
    if not records:
        raise ValueError(
            "natural-choice acceptance proof produced no complete learned "
            "choice interval"
        )
    if not any(record.accepted for record in records):
        raise ValueError(
            "natural-choice acceptance proof did not apply its learned "
            "choice"
        )


def progression_experience_deltas(
    before: Sequence[Mapping[str, int]],
    after: Sequence[Mapping[str, int]],
) -> dict[str, int]:
    """Return exact per-participant episode XP deltas, rejecting rollback."""

    baseline = {
        int(row["participant_id"]): int(row["experience"])
        for row in before
    }
    current = {
        int(row["participant_id"]): int(row["experience"])
        for row in after
    }
    if set(baseline) != set(current):
        raise ValueError("episode progression participant set changed")
    deltas = {
        str(participant_id): current[participant_id] - experience
        for participant_id, experience in baseline.items()
    }
    if any(delta < 0 for delta in deltas.values()):
        raise ValueError(f"episode progression rolled back: {deltas}")
    return deltas


def concatenate_choice_batches(
    batches: Sequence[dict[str, object]],
) -> dict[str, np.ndarray]:
    if not batches:
        raise ValueError("no complete choice batches were supplied")
    maximum_options = max(
        np.asarray(batch["option_descriptors"]).shape[1]
        for batch in batches
    )
    padded_descriptors: list[np.ndarray] = []
    padded_masks: list[np.ndarray] = []
    for batch in batches:
        descriptors = np.asarray(batch["option_descriptors"])
        masks = np.asarray(batch["option_masks"])
        padding = maximum_options - descriptors.shape[1]
        padded_descriptors.append(
            np.pad(descriptors, ((0, 0), (0, padding), (0, 0)))
        )
        padded_masks.append(np.pad(masks, ((0, 0), (0, padding))))
    keys = (
        "observations",
        "selected_options",
        "old_log_probabilities",
        "advantages",
        "returns",
        "durations",
        "dones",
        "accepted",
    )
    result = {
        key: np.concatenate(
            [np.asarray(batch[key]) for batch in batches], axis=0
        )
        for key in keys
    }
    result["option_descriptors"] = np.concatenate(padded_descriptors, axis=0)
    result["option_masks"] = np.concatenate(padded_masks, axis=0)
    return result


def partition_rollout_records(
    records: Sequence[object],
    *,
    expected_participant_ids: Sequence[int],
) -> tuple[list[object], list[object]]:
    """Reserve one non-terminal bootstrap frame per learned trajectory."""

    expected = set(expected_participant_ids)
    if not expected:
        raise ValueError("expected learned participant ids must not be empty")
    groups: dict[tuple[int, int], list[int]] = {}
    for index, record in enumerate(records):
        key = (record.episode_id, record.participant_id)
        groups.setdefault(key, []).append(index)
    observed = {participant_id for _, participant_id in groups}
    if observed != expected:
        raise ValueError(
            "rollout participants do not match the learned composition: "
            f"expected={sorted(expected)} observed={sorted(observed)}"
        )

    bootstrap_indices: set[int] = set()
    for key, indices in groups.items():
        ticks = [records[index].simulation_tick for index in indices]
        if any(right <= left for left, right in zip(ticks, ticks[1:])):
            raise ValueError(
                "simulation ticks are not strictly increasing within "
                f"trajectory {key}"
            )
        last_index = indices[-1]
        if not records[last_index].done:
            bootstrap_indices.add(last_index)
    training = [
        record
        for index, record in enumerate(records)
        if index not in bootstrap_indices
    ]
    bootstrap = [
        record
        for index, record in enumerate(records)
        if index in bootstrap_indices
    ]
    if not training:
        raise ValueError("rollout partition produced no training records")
    return training, bootstrap


def _atomic_checkpoint(
    policy: BotPolicy,
    model_path: Path,
    lua_path: Path,
) -> None:
    model_path.parent.mkdir(parents=True, exist_ok=True)
    lua_path.parent.mkdir(parents=True, exist_ok=True)
    nonce = f"{os.getpid()}.{time.time_ns()}"
    temporary_model = model_path.with_name(
        f".{model_path.name}.{nonce}.tmp"
    )
    temporary_lua = lua_path.with_name(
        f".{lua_path.name}.{nonce}.tmp"
    )
    try:
        save_model(policy, temporary_model)
        export_lua_weights(policy, temporary_lua)
        os.replace(temporary_model, model_path)
        os.replace(temporary_lua, lua_path)
    finally:
        temporary_model.unlink(missing_ok=True)
        temporary_lua.unlink(missing_ok=True)


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _mean_ppo_metrics(metrics: Sequence[object]) -> dict[str, float]:
    names = (
        "policy_loss",
        "value_loss",
        "entropy",
        "movement_entropy",
        "target_entropy",
        "ability_entropy",
        "aim_entropy",
        "approximate_kl",
        "clip_fraction",
        "gradient_norm",
    )
    result = {
        name: float(np.mean([getattr(metric, name) for metric in metrics]))
        for name in names
    }
    if not all(math.isfinite(value) for value in result.values()):
        raise FloatingPointError("PPO produced a non-finite training metric")
    return result


def _mean_choice_metrics(metrics: Sequence[object]) -> dict[str, float]:
    names = (
        "policy_loss",
        "value_loss",
        "normalized_entropy",
        "raw_entropy",
        "approximate_kl",
        "clip_fraction",
        "gradient_norm",
        "temperature",
    )
    result = {
        f"choice_{name}": float(
            np.mean([getattr(metric, name) for metric in metrics])
        )
        for name in names
    }
    if not all(math.isfinite(value) for value in result.values()):
        raise FloatingPointError(
            "choice PPO produced a non-finite training metric"
        )
    return result


def resolve_rollout_timeout(
    rollout_steps: int,
    explicit_timeout: float | None,
) -> float:
    """Allow 25% headroom over the worst-case 10 Hz single-bot cadence."""

    if rollout_steps <= 0:
        raise ValueError("rollout-steps must be positive")
    if explicit_timeout is not None:
        if not math.isfinite(explicit_timeout) or explicit_timeout <= 0.0:
            raise ValueError("rollout-timeout must be finite and positive")
        return explicit_timeout
    return max(180.0, 60.0 + rollout_steps / 10.0 * 1.25)


def live_ppo(args: argparse.Namespace) -> int:
    from ml_bot.bridge import (
        BridgeError,
        SoloSession,
        WAVE_INTEGRATION_MIN_EXPERIENCE_DELTA,
    )
    from ml_bot.compositions import (
        load_compositions,
        select_compositions,
    )
    from verify_local_multiplayer_sync import VerifyFailure

    for name in (
        "iterations",
        "rollout_steps",
        "epochs",
        "batch_size",
        "choice_epochs",
        "choice_batch_size",
        "minimum_choice_batch",
    ):
        if getattr(args, name) <= 0:
            raise ValueError(f"{name.replace('_', '-')} must be positive")
    if args.rollout_steps > MAX_LIVE_ROLLOUT_STEPS:
        raise ValueError(
            "rollout-steps exceeds the strict choice-event transport bound "
            f"of {MAX_LIVE_ROLLOUT_STEPS}"
        )
    rollout_timeout = resolve_rollout_timeout(
        args.rollout_steps,
        args.rollout_timeout,
    )
    if (
        not math.isfinite(args.wave_startup_timeout)
        or args.wave_startup_timeout <= 0.0
    ):
        raise ValueError("wave-startup-timeout must be finite and positive")
    if args.learning_rate <= 0.0 or args.choice_learning_rate <= 0.0:
        raise ValueError("main and choice learning rates must be positive")
    for name in (
        "movement_entropy_coefficient",
        "target_entropy_coefficient",
        "ability_entropy_coefficient",
        "aim_entropy_coefficient",
        "choice_entropy_coefficient",
    ):
        value = getattr(args, name)
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(
                f"{name.replace('_', '-')} must be finite and non-negative"
            )

    policy = load_model(Path(args.model))
    optimizer = Adam(
        policy.parameter_arrays(),
        learning_rate=args.learning_rate,
    )
    choice_optimizer = Adam(
        policy.parameter_arrays(),
        learning_rate=args.choice_learning_rate,
    )
    coverage_metadata = policy.metadata.get("choice_coverage")
    choice_coverage = (
        ChoiceCoverage.from_dict(coverage_metadata)
        if isinstance(coverage_metadata, dict)
        else ChoiceCoverage()
    )
    policy.set_choice_temperature(choice_coverage.temperature)
    pending_choice_batches: list[dict[str, object]] = []
    rng = np.random.default_rng(args.seed)
    instance = args.instance or f"ml-bot-{os.getpid()}"
    output_directory = (
        Path(args.output_directory)
        if args.output_directory
        else ROOT / "runtime" / "ml-training" / instance
    ).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    compositions = select_compositions(
        load_compositions(Path(args.composition_config)),
        args.composition,
    )
    layouts: tuple[Path | None, ...]
    if args.boneyard_layout:
        resolved_layouts = tuple(
            Path(value).resolve()
            for value in args.boneyard_layout
        )
        for path in resolved_layouts:
            if not path.is_file() or path.suffix.lower() != ".boneyard":
                raise ValueError(
                    "boneyard layouts must be existing .boneyard files: "
                    f"{path}"
                )
        layouts = resolved_layouts
    else:
        layouts = (None,)

    maximum_port = max(args.local_port, args.unused_remote_port) + (
        args.iterations - 1
    ) * 2
    if maximum_port > 65535:
        raise ValueError("episode port schedule exceeds 65535")
    seed_rng = np.random.default_rng(args.seed)
    run_seeds: list[int] = []
    while len(run_seeds) < args.iterations:
        candidate = int(seed_rng.integers(1, 0x40000000))
        if candidate not in run_seeds:
            run_seeds.append(candidate)

    reports: list[dict[str, object]] = []
    started_at = time.monotonic()
    for iteration in range(1, args.iterations + 1):
        composition = compositions[(iteration - 1) % len(compositions)]
        boneyard = layouts[(iteration - 1) % len(layouts)]
        requested_seed = run_seeds[iteration - 1]
        episode_instance = (
            f"{instance[:38]}-e{iteration:04d}"
        )
        session = SoloSession(
            instance=episode_instance,
            game_directory=Path(args.game_directory),
            launcher_path=Path(args.launcher_path),
            runtime_root=Path(args.runtime_root),
            local_port=args.local_port + (iteration - 1) * 2,
            unused_remote_port=(
                args.unused_remote_port + (iteration - 1) * 2
            ),
            max_participants=composition.participant_count + 1,
            headless=not args.visible,
            element=args.element,
            discipline=args.discipline,
            boneyard_override=boneyard,
            multiplayer_transport=True,
            episode_mode=args.episode_mode,
            fresh_install=args.episode_mode == "curriculum",
        )
        launch: dict[str, object] | None = None
        try:
            launch = session.launch()
            session.wait_for_pipe(timeout=args.startup_timeout)
            session.drive_new_game_to_hub(
                timeout=args.startup_timeout
            )
            session.write_empty_roster()
            session.wait_for_empty_roster(
                timeout=args.startup_timeout
            )
            generation = session.load_policy(policy)
            seed_round_trip = session.set_run_seed(requested_seed)
            session.enable_god_mode()
            if args.episode_mode == "waves":
                session.write_composition(composition)
                session.wait_for_composition(
                    expected_bot_count=composition.participant_count,
                    expected_learned_count=composition.learned_count,
                    timeout=args.startup_timeout,
                )
            session.start_test_run(timeout=args.startup_timeout)
            if args.episode_mode == "curriculum":
                session.prepare_training_combat(
                    timeout=args.startup_timeout
                )
            session.clear_training()
            session.enable_training(
                seed=requested_seed,
                capacity=50000,
            )
            if args.episode_mode == "curriculum":
                session.write_composition(composition)
            session.wait_for_composition(
                expected_bot_count=composition.participant_count,
                expected_learned_count=composition.learned_count,
                timeout=args.startup_timeout,
            )
            session.wait_for_run_ready(
                expected_bot_count=composition.participant_count,
                expected_learned_count=composition.learned_count,
                timeout=args.startup_timeout,
            )
            session.wait_for_bot_materialized(
                expected_bot_count=composition.participant_count,
                expected_learned_count=composition.learned_count,
                timeout=args.startup_timeout,
            )
            run_identity = session.get_run_identity()
            if (
                run_identity["observed_seed"] != requested_seed
                or run_identity["run_nonce"] != requested_seed
            ):
                raise BridgeError(
                    "native run identity does not match the requested seed: "
                    f"requested={requested_seed} observed={run_identity}"
                )
            episode_start_status = session.status()
            if episode_start_status.get("clock_source") != "simulation":
                raise BridgeError(
                    "live trainer requires the simulation-time policy clock"
                )
            if int(
                episode_start_status.get("simulation_tick", "0")
            ) <= 0:
                raise BridgeError(
                    "live trainer did not observe a simulation tick"
                )
            learned_participant_ids = (
                session.learned_participant_ids()
            )
            if (
                len(learned_participant_ids)
                != composition.learned_count
            ):
                raise BridgeError(
                    "materialized learned participants do not match "
                    "the composition"
                )

            party_participant_ids = session.in_run_participant_ids()
            if len(party_participant_ids) != (
                composition.participant_count + 1
            ):
                raise BridgeError(
                    "in-run party does not match local player plus the "
                    f"configured composition: {party_participant_ids}"
                )
            party_progression_before = session.participant_progression(
                party_participant_ids
            )

            progression_before = session.participant_progression(
                learned_participant_ids
            )
            wave_start: dict[str, object] | None = None
            wave_integration: dict[str, object] | None = None
            natural_choice_proof: dict[str, object] | None = None
            natural_choice_proof_required = (
                args.require_natural_choice_proof and iteration == 1
            )
            if args.episode_mode == "waves":
                wave_start = session.start_stock_wave_episode(
                    learned_participant_ids[0],
                    timeout=args.wave_startup_timeout,
                )
                wave_integration = session.wait_for_wave_integration(
                    learned_participant_ids,
                    progression_before,
                    initial_status=episode_start_status,
                    timeout=args.wave_startup_timeout,
                )
                if natural_choice_proof_required:
                    natural_choice_proof = (
                        session.wait_for_natural_choice_proof(
                            learned_participant_ids,
                            progression_before,
                            initial_status=episode_start_status,
                            timeout=args.wave_startup_timeout,
                        )
                    )
            else:
                session.start_training_arena(
                    timeout=args.startup_timeout
                )
                session.wait_for_training_enemy(
                    timeout=args.startup_timeout
                )

            session.clear_main_training_stream()
            collection_initial_status = session.status()
            requested_records = args.rollout_steps
            collection_status = session.wait_for_rollouts(
                requested_records,
                timeout=rollout_timeout,
            )
            finished_status = session.finish_training_episode()
            progression_after = session.participant_progression(
                learned_participant_ids
            )
            party_progression_after = session.participant_progression(
                party_participant_ids
            )
            episode_experience_deltas = progression_experience_deltas(
                progression_before,
                progression_after,
            )
            party_experience_deltas = progression_experience_deltas(
                party_progression_before,
                party_progression_after,
            )
            party_progression_signatures = {
                (int(row["level"]), int(row["experience"]))
                for row in party_progression_after
            }
            party_progression_synchronized = (
                len(party_progression_signatures) == 1
            )
            if (
                args.episode_mode == "waves"
                and not party_progression_synchronized
            ):
                raise BridgeError(
                    "shared party progression diverged after the episode: "
                    f"{party_progression_after}"
                )
            main_count = int(finished_status.get("buffered", "0"))
            choice_count = int(
                finished_status.get("choice_buffered", "0")
            )
            if main_count < requested_records:
                raise BridgeError(
                    "finished episode lost main rollout records: "
                    f"{finished_status}"
                )
            records = session.drain_rollouts(main_count)
            all_choice_records = (
                session.drain_choice_rollouts(choice_count)
                if choice_count > 0
                else []
            )
            choice_records, scripted_choice_records = (
                partition_choice_records(all_choice_records)
            )
            validate_natural_choice_proof_records(
                choice_records,
                required=(
                    args.episode_mode == "waves"
                    and natural_choice_proof_required
                ),
            )
            session.clear_training()
            training_records, bootstrap_records = (
                partition_rollout_records(
                    records,
                    expected_participant_ids=(
                        learned_participant_ids
                    ),
                )
            )
            batch = prepare_rollout_batch(
                training_records,
                bootstrap_records,
                gamma=args.gamma,
                gae_lambda=args.gae_lambda,
            )
            if choice_records:
                unexpected_choice_participants = {
                    record.participant_id for record in choice_records
                } - set(learned_participant_ids)
                if unexpected_choice_participants:
                    raise BridgeError(
                        "choice records came from non-learned participants: "
                        f"{sorted(unexpected_choice_participants)}"
                    )
                pending_choice_batches.append(
                    prepare_choice_batch(
                        choice_records,
                        gamma=args.gamma,
                        gae_lambda=args.gae_lambda,
                    )
                )
                for record in choice_records:
                    choice_coverage.observe(
                        np.asarray(record.option_descriptors),
                        np.asarray(record.option_mask),
                        record.selected_option,
                    )
                policy.set_choice_temperature(
                    choice_coverage.temperature
                )
            metrics = ppo_epochs(
                policy,
                optimizer,
                batch["observations"],
                batch["movement_masks"],
                batch["target_masks"],
                batch["ability_masks"],
                batch["aim_masks"],
                batch["movement_actions"],
                batch["target_actions"],
                batch["ability_actions"],
                batch["aim_actions"],
                batch["old_log_probabilities"],
                batch["advantages"],
                batch["returns"],
                rng=rng,
                epochs=args.epochs,
                batch_size=args.batch_size,
                clip_ratio=args.clip_ratio,
                value_coefficient=args.value_coefficient,
                movement_entropy_coefficient=(
                    args.movement_entropy_coefficient
                ),
                target_entropy_coefficient=(
                    args.target_entropy_coefficient
                ),
                ability_entropy_coefficient=(
                    args.ability_entropy_coefficient
                ),
                aim_entropy_coefficient=args.aim_entropy_coefficient,
                maximum_gradient_norm=args.maximum_gradient_norm,
            )
            summary = _mean_ppo_metrics(metrics)
            pending_choice_count = sum(
                np.asarray(batch["observations"]).shape[0]
                for batch in pending_choice_batches
            )
            choice_summary: dict[str, float] = {}
            choice_update_records = 0
            if pending_choice_count >= args.minimum_choice_batch:
                choice_batch = concatenate_choice_batches(
                    pending_choice_batches
                )
                choice_metrics = choice_ppo_epochs(
                    policy,
                    choice_optimizer,
                    choice_batch["observations"],
                    choice_batch["option_descriptors"],
                    choice_batch["option_masks"],
                    choice_batch["selected_options"],
                    choice_batch["old_log_probabilities"],
                    choice_batch["advantages"],
                    choice_batch["returns"],
                    rng=rng,
                    epochs=args.choice_epochs,
                    batch_size=args.choice_batch_size,
                    clip_ratio=args.clip_ratio,
                    value_coefficient=args.value_coefficient,
                    entropy_coefficient=(
                        args.choice_entropy_coefficient
                    ),
                    maximum_gradient_norm=(
                        args.maximum_gradient_norm
                    ),
                )
                choice_summary = _mean_choice_metrics(choice_metrics)
                choice_update_records = pending_choice_count
                pending_choice_batches.clear()
            policy.metadata.update(
                {
                    "training_kind": "live_main_and_choice_smdp_ppo_v3",
                    "live_training_seed": args.seed,
                    "live_native_run_seed": requested_seed,
                    "live_training_iteration": iteration,
                    "live_training_episode_mode": args.episode_mode,
                    "live_training_natural_choice_proof_required": (
                        natural_choice_proof_required
                    ),
                    "live_training_rollout_steps": len(
                        training_records
                    ),
                    "live_training_rollout_timeout_seconds": (
                        rollout_timeout
                    ),
                    "live_training_composition": composition.name,
                    "movement_entropy_coefficient": (
                        args.movement_entropy_coefficient
                    ),
                    "target_entropy_coefficient": (
                        args.target_entropy_coefficient
                    ),
                    "ability_entropy_coefficient": (
                        args.ability_entropy_coefficient
                    ),
                    "aim_entropy_coefficient": (
                        args.aim_entropy_coefficient
                    ),
                    "choice_entropy_coefficient": (
                        args.choice_entropy_coefficient
                    ),
                    "choice_coverage": choice_coverage.to_dict(),
                    "choice_pending_complete_intervals": (
                        pending_choice_count - choice_update_records
                    ),
                }
            )
            checkpoint_model = (
                output_directory
                / f"policy-iteration-{iteration:04d}.json"
            )
            checkpoint_lua = (
                output_directory
                / f"policy-iteration-{iteration:04d}.lua"
            )
            _atomic_checkpoint(
                policy,
                checkpoint_model,
                checkpoint_lua,
            )
            previous_generation = generation
            next_generation = session.load_policy(policy)
            if next_generation <= previous_generation:
                raise BridgeError(
                    "hot-loaded policy generation did not advance"
                )
            generation = next_generation
            final_status = session.status()
            decision_delta = (
                int(
                    final_status.get(
                        "policy_decision_count",
                        "0",
                    )
                )
                - int(
                    collection_initial_status.get(
                        "policy_decision_count",
                        "0",
                    )
                )
            )
            movement_delta = (
                int(final_status.get("move_accepted", "0"))
                - int(
                    collection_initial_status.get(
                        "move_accepted",
                        "0",
                    )
                )
            )
            if decision_delta <= 0 or movement_delta <= 0:
                raise BridgeError(
                    "learned policy did not make live movement decisions"
                )
            trajectory_counts = {
                str(participant_id): sum(
                    record.participant_id == participant_id
                    for record in training_records
                )
                for participant_id in learned_participant_ids
            }
            if any(count <= 0 for count in trajectory_counts.values()):
                raise BridgeError(
                    "a learned participant produced no trajectories"
                )
            report: dict[str, object] = {
                "iteration": iteration,
                "environment_episode": iteration,
                "instance": episode_instance,
                "process_id": (
                    launch.get("processId") if launch else None
                ),
                "episode_mode": args.episode_mode,
                "profile_mode": (
                    "fresh-install"
                    if args.episode_mode == "curriculum"
                    else "isolated-temporary-profile"
                ),
                "rollout_timeout_seconds": rollout_timeout,
                "rollout_timeout_source": (
                    "explicit"
                    if args.rollout_timeout is not None
                    else "rollout-steps-autoscale"
                ),
                "requested_seed": requested_seed,
                "seed_round_trip": seed_round_trip,
                "observed_run_nonce": run_identity["run_nonce"],
                "observed_run_seed": run_identity["observed_seed"],
                "layout_sha256": session.layout_sha256(),
                "layout_override": (
                    str(boneyard) if boneyard is not None else None
                ),
                "composition": composition.to_log(),
                "learned_participant_ids": list(
                    learned_participant_ids
                ),
                "party_participant_ids": list(
                    party_participant_ids
                ),
                "trajectory_participant_count": len(
                    trajectory_counts
                ),
                "trajectory_counts": trajectory_counts,
                "rollout_steps": len(training_records),
                "bootstrap_records": len(bootstrap_records),
                "choice_complete_intervals": len(choice_records),
                "choice_events_total": len(all_choice_records),
                "scripted_choice_events_excluded": len(
                    scripted_choice_records
                ),
                "choice_update_records": choice_update_records,
                "choice_pending_complete_intervals": (
                    pending_choice_count - choice_update_records
                ),
                "choice_temperature": policy.choice_temperature,
                "choice_coverage_complete": choice_coverage.complete,
                "natural_choice_proof_required": (
                    natural_choice_proof_required
                ),
                "choice_intervals": [
                    {
                        "participant_id": record.participant_id,
                        "generation": record.generation,
                        "duration_steps": record.duration_steps,
                        "reward_count": len(record.rewards),
                        "reward_sum": float(sum(record.rewards)),
                        "trainable": record.trainable,
                        "accepted": record.accepted,
                    }
                    for record in choice_records
                ],
                "progression_before": progression_before,
                "progression_after": progression_after,
                "party_progression_before": party_progression_before,
                "party_progression_after": party_progression_after,
                "party_experience_deltas": party_experience_deltas,
                "party_progression_synchronized": (
                    party_progression_synchronized
                ),
                "wave_integration_gate": wave_integration,
                "wave_integration_min_experience_delta": (
                    WAVE_INTEGRATION_MIN_EXPERIENCE_DELTA
                ),
                "wave_experience_delta": (
                    int(wave_integration["experience_delta"])
                    if wave_integration is not None
                    else 0
                ),
                "episode_experience_deltas": (
                    episode_experience_deltas
                ),
                "episode_experience_delta_total": sum(
                    episode_experience_deltas.values()
                ),
                "natural_choice_proof": natural_choice_proof,
                "training_owner_level_up_choices": list(
                    session.training_owner_level_up_choices
                ),
                "wave_start": wave_start,
                "learned_skill_choices_seen_delta": (
                    int(
                        final_status.get(
                            "learned_skill_choices_seen",
                            "0",
                        )
                    )
                    - int(
                        episode_start_status.get(
                            "learned_skill_choices_seen",
                            "0",
                        )
                    )
                ),
                "learned_skill_choices_accepted_delta": (
                    int(
                        final_status.get(
                            "learned_skill_choices_accepted",
                            "0",
                        )
                    )
                    - int(
                        episode_start_status.get(
                            "learned_skill_choices_accepted",
                            "0",
                        )
                    )
                ),
                "episode_ids": sorted(
                    {
                        record.episode_id
                        for record in training_records
                    }
                ),
                "reward_mean": float(np.mean(batch["rewards"])),
                "reward_sum": float(np.sum(batch["rewards"])),
                "terminal_count": int(np.sum(batch["dones"])),
                "policy_generation": generation,
                "policy_generation_advanced": (
                    next_generation > previous_generation
                ),
                "policy_decision_delta": decision_delta,
                "move_accepted_delta": movement_delta,
                "buffer_dropped": int(
                    collection_status.get("dropped", "0")
                ),
                "choice_buffer_dropped": int(
                    collection_status.get("choice_dropped", "0")
                ),
                "checkpoint_model": str(checkpoint_model),
                "checkpoint_lua": str(checkpoint_lua),
                **summary,
                **choice_summary,
            }
            if (
                report["buffer_dropped"] != 0
                or report["choice_buffer_dropped"] != 0
            ):
                raise BridgeError("live trajectory buffer dropped records")
            reports.append(report)
            _atomic_json(
                output_directory
                / f"episode-{iteration:04d}.json",
                report,
            )
            print(json.dumps(report, sort_keys=True))
        finally:
            if launch is not None:
                try:
                    session.disable_training()
                except (
                    BridgeError,
                    VerifyFailure,
                    subprocess.TimeoutExpired,
                ):
                    pass
            session.close()

    final_model = output_directory / "policy-final.json"
    final_lua = output_directory / "policy-final.lua"
    _atomic_checkpoint(policy, final_model, final_lua)
    result = {
        "status": "ok",
        "instance_prefix": instance,
        "headless": not args.visible,
        "episode_mode": args.episode_mode,
        "natural_choice_proof_required": (
            args.require_natural_choice_proof
        ),
        "rollout_timeout_seconds": rollout_timeout,
        "rollout_timeout_source": (
            "explicit"
            if args.rollout_timeout is not None
            else "rollout-steps-autoscale"
        ),
        "environment_episode_count": len(reports),
        "requested_seeds": run_seeds,
        "distinct_seed_count": len(set(run_seeds)),
        "composition_names": [
            report["composition"]["name"] for report in reports
        ],
        "wave_experience_deltas": [
            report["wave_experience_delta"] for report in reports
        ],
        "iterations": reports,
        "elapsed_wall_seconds": time.monotonic() - started_at,
        "final_model": str(final_model),
        "final_lua": str(final_lua),
    }
    _atomic_json(output_directory / "live-training-report.json", result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="train the deterministic semantic seed policy",
    )
    bootstrap_parser.add_argument("--seed", type=int, default=20260730)
    bootstrap_parser.add_argument("--samples", type=int, default=6000)
    bootstrap_parser.add_argument("--epochs", type=int, default=20)
    bootstrap_parser.add_argument("--batch-size", type=int, default=128)
    bootstrap_parser.add_argument("--learning-rate", type=float, default=0.0015)
    bootstrap_parser.add_argument(
        "--minimum-movement-accuracy",
        type=float,
        default=0.85,
    )
    bootstrap_parser.add_argument(
        "--minimum-target-accuracy",
        type=float,
        default=0.75,
    )
    bootstrap_parser.add_argument(
        "--minimum-ability-accuracy",
        type=float,
        default=0.68,
    )
    bootstrap_parser.add_argument(
        "--minimum-aim-accuracy",
        type=float,
        default=0.90,
    )
    bootstrap_parser.add_argument(
        "--minimum-joint-accuracy",
        type=float,
        default=0.38,
    )
    bootstrap_parser.add_argument("--model", default=str(DEFAULT_MODEL))
    bootstrap_parser.add_argument("--lua", default=str(DEFAULT_LUA))
    bootstrap_parser.set_defaults(handler=bootstrap)

    validate_parser = subparsers.add_parser(
        "validate",
        help="strictly validate a saved model and optionally re-export Lua",
    )
    validate_parser.add_argument("--model", default=str(DEFAULT_MODEL))
    validate_parser.add_argument("--lua")
    validate_parser.set_defaults(handler=validate)

    live_parser = subparsers.add_parser(
        "live-ppo",
        help="train against a disposable accelerated game session",
    )
    live_parser.add_argument("--model", default=str(DEFAULT_MODEL))
    live_parser.add_argument("--iterations", type=int, default=10)
    live_parser.add_argument("--rollout-steps", type=int, default=1024)
    live_parser.add_argument("--epochs", type=int, default=4)
    live_parser.add_argument("--batch-size", type=int, default=128)
    live_parser.add_argument("--learning-rate", type=float, default=0.0003)
    live_parser.add_argument("--gamma", type=float, default=0.99)
    live_parser.add_argument("--gae-lambda", type=float, default=0.95)
    live_parser.add_argument("--clip-ratio", type=float, default=0.2)
    live_parser.add_argument("--value-coefficient", type=float, default=0.5)
    live_parser.add_argument(
        "--movement-entropy-coefficient",
        type=float,
        default=spec.MOVEMENT_ENTROPY_COEFFICIENT,
    )
    live_parser.add_argument(
        "--target-entropy-coefficient",
        type=float,
        default=spec.TARGET_ENTROPY_COEFFICIENT,
    )
    live_parser.add_argument(
        "--ability-entropy-coefficient",
        type=float,
        default=spec.ABILITY_ENTROPY_COEFFICIENT,
    )
    live_parser.add_argument(
        "--aim-entropy-coefficient",
        type=float,
        default=spec.AIM_ENTROPY_COEFFICIENT,
    )
    live_parser.add_argument(
        "--choice-entropy-coefficient",
        type=float,
        default=spec.CHOICE_ENTROPY_COEFFICIENT,
    )
    live_parser.add_argument(
        "--choice-learning-rate",
        type=float,
        default=0.0003,
    )
    live_parser.add_argument(
        "--choice-epochs",
        type=int,
        default=4,
    )
    live_parser.add_argument(
        "--choice-batch-size",
        type=int,
        default=32,
    )
    live_parser.add_argument(
        "--minimum-choice-batch",
        type=int,
        default=32,
    )
    live_parser.add_argument(
        "--maximum-gradient-norm",
        type=float,
        default=0.5,
    )
    live_parser.add_argument("--seed", type=int, default=20260730)
    live_parser.add_argument("--instance")
    live_parser.add_argument(
        "--composition-config",
        default=str(
            ROOT / "tools" / "ml_bot" / "team-compositions.json"
        ),
    )
    live_parser.add_argument(
        "--composition",
        action="append",
        default=[],
        help=(
            "composition name to include in rotation; repeat to set "
            "the rotation order"
        ),
    )
    live_parser.add_argument(
        "--boneyard-layout",
        action="append",
        default=[],
        help=(
            "validated .boneyard layout to rotate; repeat for multiple "
            "layouts (stock layout is used when omitted)"
        ),
    )
    live_parser.add_argument(
        "--game-directory",
        default=str(DEFAULT_GAME_DIRECTORY),
    )
    live_parser.add_argument(
        "--launcher-path",
        default=str(DEFAULT_LAUNCHER),
    )
    live_parser.add_argument(
        "--runtime-root",
        default=str(ROOT / "runtime"),
    )
    live_parser.add_argument("--output-directory")
    live_parser.add_argument("--local-port", type=int, default=49780)
    live_parser.add_argument(
        "--unused-remote-port",
        type=int,
        default=49781,
    )
    live_parser.add_argument("--startup-timeout", type=float, default=45.0)
    live_parser.add_argument(
        "--wave-startup-timeout",
        type=float,
        default=DEFAULT_WAVE_INTEGRATION_TIMEOUT_SECONDS,
        help=(
            "per-operation ceiling for stock Solomon routing and the "
            "positive-XP integration guard; also bounds the optional "
            "natural-choice acceptance proof"
        ),
    )
    live_parser.add_argument(
        "--require-natural-choice-proof",
        action="store_true",
        help=(
            "one-time acceptance probe: require a natural level-up, learned "
            "native choice apply, and complete interval in the first episode"
        ),
    )
    live_parser.add_argument(
        "--rollout-timeout",
        type=float,
        default=None,
        help=(
            "explicit rollout collection timeout in seconds; default is "
            "max(180, 60 + rollout_steps / 10 * 1.25)"
        ),
    )
    live_parser.add_argument(
        "--episode-mode",
        choices=("waves", "curriculum"),
        default="waves",
        help=(
            "stock XP-bearing waves (default) or the direct-spawn, "
            "XP-free curriculum drill"
        ),
    )
    live_parser.add_argument(
        "--element",
        choices=("fire", "water", "earth", "air", "ether"),
        default="fire",
    )
    live_parser.add_argument(
        "--discipline",
        choices=("mind", "body", "arcane"),
        default="arcane",
    )
    live_parser.add_argument(
        "--visible",
        action="store_true",
        help="show the training game window instead of using headless mode",
    )
    live_parser.set_defaults(handler=live_ppo)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, ValueError, RuntimeError, FloatingPointError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
