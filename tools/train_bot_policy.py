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
    behavior_clone_batch,
    classification_accuracy,
    export_lua_weights,
    generalized_advantage_estimate,
    load_model,
    ppo_epochs,
    save_model,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "bot-brain" / "policy-v1.json"
DEFAULT_LUA = (
    ROOT / "mods" / "bot-brain" / "scripts" / "policy_weights.lua"
)
DEFAULT_GAME_DIRECTORY = Path(
    "C:/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
DEFAULT_LAUNCHER = (
    ROOT / "dist" / "launcher" / "SolomonDarkModLauncher.exe"
)


def _batch(
    dataset: ExpertDataset,
    indices: np.ndarray,
) -> tuple[np.ndarray, ...]:
    return (
        dataset.observations[indices],
        dataset.movement_masks[indices],
        dataset.cast_masks[indices],
        dataset.movement_actions[indices],
        dataset.cast_actions[indices],
    )


def _accuracies(
    policy: BotPolicy,
    dataset: ExpertDataset,
) -> tuple[float, float, float]:
    return classification_accuracy(
        policy,
        dataset.observations,
        dataset.movement_masks,
        dataset.cast_masks,
        dataset.movement_actions,
        dataset.cast_actions,
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
            "training_kind": "semantic_behavior_cloning",
            "seed": args.seed,
            "expert_samples": args.samples,
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
        movement, cast, joint = _accuracies(policy, validation)
        print(
            json.dumps(
                {
                    "epoch": epoch + 1,
                    "loss": last_loss,
                    "gradient_norm": last_gradient_norm,
                    "validation_movement_accuracy": movement,
                    "validation_cast_accuracy": cast,
                    "validation_joint_accuracy": joint,
                },
                sort_keys=True,
            )
        )

    training_accuracy = _accuracies(policy, training)
    validation_accuracy = _accuracies(policy, validation)
    gates = {
        "movement": args.minimum_movement_accuracy,
        "cast": args.minimum_cast_accuracy,
        "joint": args.minimum_joint_accuracy,
    }
    actual = {
        "movement": validation_accuracy[0],
        "cast": validation_accuracy[1],
        "joint": validation_accuracy[2],
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
    policy.metadata.update(
        {
            "training_movement_accuracy": training_accuracy[0],
            "training_cast_accuracy": training_accuracy[1],
            "training_joint_accuracy": training_accuracy[2],
            "validation_movement_accuracy": validation_accuracy[0],
            "validation_cast_accuracy": validation_accuracy[1],
            "validation_joint_accuracy": validation_accuracy[2],
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
                    "cast": training_accuracy[1],
                    "joint": training_accuracy[2],
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
    cast_masks = np.asarray(
        [record.cast_mask for record in records],
        dtype=np.bool_,
    )
    movement_actions = np.asarray(
        [record.movement_action for record in records],
        dtype=np.int64,
    )
    cast_actions = np.asarray(
        [record.cast_action for record in records],
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
        "cast_masks": cast_masks,
        "movement_actions": movement_actions,
        "cast_actions": cast_actions,
        "old_log_probabilities": old_log_probabilities,
        "advantages": advantages,
        "returns": returns,
        "rewards": rewards,
        "dones": dones,
    }


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


def _mean_ppo_metrics(metrics: Sequence[object]) -> dict[str, float]:
    names = (
        "policy_loss",
        "value_loss",
        "entropy",
        "approximate_kl",
        "clip_fraction",
    )
    result = {
        name: float(np.mean([getattr(metric, name) for metric in metrics]))
        for name in names
    }
    if not all(math.isfinite(value) for value in result.values()):
        raise FloatingPointError("PPO produced a non-finite training metric")
    return result


def live_ppo(args: argparse.Namespace) -> int:
    from ml_bot.bridge import BridgeError, SoloSession
    from verify_local_multiplayer_sync import VerifyFailure

    for name in ("iterations", "rollout_steps", "epochs", "batch_size"):
        if getattr(args, name) <= 0:
            raise ValueError(f"{name.replace('_', '-')} must be positive")
    if args.rollout_timeout <= 0.0:
        raise ValueError("rollout-timeout must be positive")

    policy = load_model(Path(args.model))
    optimizer = Adam(
        policy.parameter_arrays(),
        learning_rate=args.learning_rate,
    )
    rng = np.random.default_rng(args.seed)
    instance = args.instance or f"ml-bot-{os.getpid()}"
    output_directory = (
        Path(args.output_directory)
        if args.output_directory
        else ROOT / "runtime" / "ml-training" / instance
    ).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)

    session = SoloSession(
        instance=instance,
        game_directory=Path(args.game_directory),
        launcher_path=Path(args.launcher_path),
        runtime_root=Path(args.runtime_root),
        local_port=args.local_port,
        unused_remote_port=args.unused_remote_port,
        headless=not args.visible,
        element=args.element,
        discipline=args.discipline,
    )
    launch: dict[str, object] | None = None
    initial_status: dict[str, str] = {}
    reports: list[dict[str, object]] = []
    started_at = time.monotonic()
    try:
        launch = session.launch()
        session.wait_for_pipe(timeout=args.startup_timeout)
        session.drive_new_game_to_hub(timeout=args.startup_timeout)
        session.write_empty_roster()
        session.wait_for_empty_roster(timeout=args.startup_timeout)
        generation = session.load_policy(policy)
        session.enable_god_mode()
        session.start_test_run(timeout=args.startup_timeout)
        session.prepare_training_combat(
            timeout=args.startup_timeout
        )
        session.write_learned_roster()
        session.wait_for_learned_bot(timeout=args.startup_timeout)
        session.wait_for_run_ready(timeout=args.startup_timeout)
        session.wait_for_bot_materialized(
            timeout=args.startup_timeout
        )
        session.prime_training_progression(
            timeout=args.startup_timeout
        )
        session.start_training_arena(
            timeout=args.startup_timeout
        )
        session.wait_for_training_enemy(
            timeout=args.startup_timeout
        )
        initial_status = session.status()
        if initial_status.get("clock_source") != "simulation":
            raise BridgeError(
                "live trainer requires the simulation-time policy clock"
            )
        if int(initial_status.get("simulation_tick", "0")) <= 0:
            raise BridgeError(
                "live trainer did not observe a published simulation tick"
            )

        for iteration in range(1, args.iterations + 1):
            session.clear_training()
            session.enable_training(
                seed=args.seed + iteration - 1,
                capacity=max(args.rollout_steps * 3, 1024),
            )
            collection_status = session.wait_for_rollouts(
                args.rollout_steps + 1,
                timeout=args.rollout_timeout,
            )
            session.disable_training()
            records = session.drain_rollouts(args.rollout_steps + 1)
            session.clear_training()

            batch = prepare_rollout_batch(
                records[:-1],
                records[-1:],
                gamma=args.gamma,
                gae_lambda=args.gae_lambda,
            )
            metrics = ppo_epochs(
                policy,
                optimizer,
                batch["observations"],
                batch["movement_masks"],
                batch["cast_masks"],
                batch["movement_actions"],
                batch["cast_actions"],
                batch["old_log_probabilities"],
                batch["advantages"],
                batch["returns"],
                rng=rng,
                epochs=args.epochs,
                batch_size=args.batch_size,
                clip_ratio=args.clip_ratio,
                value_coefficient=args.value_coefficient,
                entropy_coefficient=args.entropy_coefficient,
                maximum_gradient_norm=args.maximum_gradient_norm,
            )
            summary = _mean_ppo_metrics(metrics)
            policy.metadata.update(
                {
                    "training_kind": "live_ppo",
                    "live_training_seed": args.seed,
                    "live_training_iteration": iteration,
                    "live_training_rollout_steps": args.rollout_steps,
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
            next_generation = session.load_policy(policy)
            if next_generation <= generation:
                raise BridgeError(
                    "hot-loaded policy generation did not advance"
                )
            generation = next_generation
            report: dict[str, object] = {
                "iteration": iteration,
                "rollout_steps": args.rollout_steps,
                "episode_ids": sorted(
                    {record.episode_id for record in records[:-1]}
                ),
                "reward_mean": float(np.mean(batch["rewards"])),
                "reward_sum": float(np.sum(batch["rewards"])),
                "terminal_count": int(np.sum(batch["dones"])),
                "policy_generation": generation,
                "buffer_dropped": int(
                    collection_status.get("dropped", "0")
                ),
                "checkpoint_model": str(checkpoint_model),
                "checkpoint_lua": str(checkpoint_lua),
                **summary,
            }
            if report["buffer_dropped"] != 0:
                raise BridgeError("live trajectory buffer dropped records")
            reports.append(report)
            print(json.dumps(report, sort_keys=True))

        final_model = output_directory / "policy-final.json"
        final_lua = output_directory / "policy-final.lua"
        _atomic_checkpoint(policy, final_model, final_lua)
        final_status = session.status()
        decision_delta = (
            int(final_status.get("policy_decision_count", "0"))
            - int(initial_status.get("policy_decision_count", "0"))
        )
        movement_delta = (
            int(final_status.get("move_accepted", "0"))
            - int(initial_status.get("move_accepted", "0"))
        )
        cast_delta = (
            int(final_status.get("cast_accepted", "0"))
            - int(initial_status.get("cast_accepted", "0"))
        )
        if decision_delta <= 0:
            raise BridgeError("learned policy made no live decisions")
        if movement_delta <= 0:
            raise BridgeError("learned policy had no accepted live movement")
        if cast_delta <= 0:
            raise BridgeError("learned policy had no accepted live attacks")

        result = {
            "status": "ok",
            "instance": instance,
            "headless": not args.visible,
            "process_id": launch.get("processId") if launch else None,
            "iterations": reports,
            "policy_generation": generation,
            "policy_decision_delta": decision_delta,
            "move_accepted_delta": movement_delta,
            "cast_accepted_delta": cast_delta,
            "simulation_tick": int(
                final_status.get("simulation_tick", "0")
            ),
            "elapsed_wall_seconds": time.monotonic() - started_at,
            "final_model": str(final_model),
            "final_lua": str(final_lua),
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="train the deterministic semantic seed policy",
    )
    bootstrap_parser.add_argument("--seed", type=int, default=20260729)
    bootstrap_parser.add_argument("--samples", type=int, default=24000)
    bootstrap_parser.add_argument("--epochs", type=int, default=28)
    bootstrap_parser.add_argument("--batch-size", type=int, default=256)
    bootstrap_parser.add_argument("--learning-rate", type=float, default=0.002)
    bootstrap_parser.add_argument(
        "--minimum-movement-accuracy",
        type=float,
        default=0.90,
    )
    bootstrap_parser.add_argument(
        "--minimum-cast-accuracy",
        type=float,
        default=0.96,
    )
    bootstrap_parser.add_argument(
        "--minimum-joint-accuracy",
        type=float,
        default=0.87,
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
        "--entropy-coefficient",
        type=float,
        default=0.01,
    )
    live_parser.add_argument(
        "--maximum-gradient-norm",
        type=float,
        default=0.5,
    )
    live_parser.add_argument("--seed", type=int, default=20260729)
    live_parser.add_argument("--instance")
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
    live_parser.add_argument("--rollout-timeout", type=float, default=180.0)
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
