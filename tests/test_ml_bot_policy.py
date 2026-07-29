#!/usr/bin/env python3
"""Numerical, serialization, Lua-parity, and trajectory tests for ML bots."""

from __future__ import annotations

import copy
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from ml_bot import spec  # noqa: E402
from ml_bot.bridge import RolloutRecord, parse_rollout_output  # noqa: E402
from ml_bot.model import (  # noqa: E402
    Adam,
    BotPolicy,
    export_lua_weights,
    generalized_advantage_estimate,
    load_model,
    ppo_epochs,
    save_model,
)
from train_bot_policy import prepare_rollout_batch  # noqa: E402


MODEL = ROOT / "models" / "bot-brain" / "policy-v1.json"
LUA_CONTRACT = ROOT / "tests" / "lua" / "ml_bot_policy_contract.lua"


def _record(
    *,
    tick: int,
    reward: float,
    value: float,
    done: bool = False,
) -> RolloutRecord:
    return RolloutRecord(
        trajectory_version=spec.TRAJECTORY_VERSION,
        episode_id=3,
        participant_id=42,
        simulation_tick=tick,
        observation=[0.01 * tick] * len(spec.OBSERVATION_NAMES),
        movement_mask=[True] * len(spec.MOVEMENT_ACTION_NAMES),
        cast_mask=[True] * len(spec.CAST_ACTION_NAMES),
        movement_action=1,
        cast_action=2,
        old_log_probability=-1.5,
        old_value=value,
        reward=reward,
        done=done,
    )


class MlBotPolicyTests(unittest.TestCase):
    def test_seed_model_is_strict_and_passes_bootstrap_gates(self) -> None:
        policy = load_model(MODEL)
        shape = spec.model_shape()

        self.assertEqual(
            policy.input_weight.shape,
            (shape["hidden_size"], shape["observation_size"]),
        )
        self.assertGreaterEqual(
            policy.metadata["validation_movement_accuracy"],
            0.90,
        )
        self.assertGreaterEqual(
            policy.metadata["validation_cast_accuracy"],
            0.96,
        )
        self.assertGreaterEqual(
            policy.metadata["validation_joint_accuracy"],
            0.87,
        )

        invalid = copy.deepcopy(policy.to_dict())
        invalid["observation_names"][0] = "contract_drift"
        with self.assertRaisesRegex(ValueError, "observation_names"):
            BotPolicy.from_dict(invalid)

    def test_model_exports_use_repository_line_endings(self) -> None:
        policy = load_model(MODEL)
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "policy.json"
            lua_path = Path(directory) / "policy.lua"
            save_model(policy, model_path)
            export_lua_weights(policy, lua_path)

            for path in (model_path, lua_path):
                contents = path.read_bytes()
                self.assertNotIn(b"\r", contents)
                self.assertTrue(contents.endswith(b"\n"))

    def test_generalized_advantage_estimate_matches_known_values(self) -> None:
        advantages, returns = generalized_advantage_estimate(
            np.asarray([1.0, 2.0]),
            np.asarray([0.5, 0.25]),
            np.asarray([False, True]),
            gamma=0.9,
            gae_lambda=0.8,
        )
        np.testing.assert_allclose(advantages, [1.985, 1.75])
        np.testing.assert_allclose(returns, [2.485, 2.0])

    def test_ppo_update_is_finite_and_changes_parameters(self) -> None:
        rng = np.random.default_rng(1801)
        policy = BotPolicy.initialize(rng)
        count = 64
        observations = rng.uniform(
            -1.0,
            1.0,
            size=(count, len(spec.OBSERVATION_NAMES)),
        )
        movement_masks = np.ones(
            (count, len(spec.MOVEMENT_ACTION_NAMES)),
            dtype=np.bool_,
        )
        cast_masks = np.ones(
            (count, len(spec.CAST_ACTION_NAMES)),
            dtype=np.bool_,
        )
        actions = policy.act(
            observations,
            movement_masks,
            cast_masks,
            deterministic=False,
            rng=rng,
        )
        rewards = np.linspace(-0.25, 0.75, count)
        dones = np.zeros(count, dtype=np.bool_)
        dones[-1] = True
        advantages, returns = generalized_advantage_estimate(
            rewards,
            actions.values,
            dones,
        )
        before = {
            name: value.copy()
            for name, value in policy.parameter_arrays().items()
        }
        metrics = ppo_epochs(
            policy,
            Adam(policy.parameter_arrays(), learning_rate=0.0003),
            observations,
            movement_masks,
            cast_masks,
            actions.movement_actions,
            actions.cast_actions,
            actions.log_probabilities,
            advantages,
            returns,
            rng=rng,
            epochs=2,
            batch_size=16,
        )

        self.assertTrue(metrics)
        for metric in metrics:
            self.assertTrue(
                np.all(
                    np.isfinite(
                        [
                            metric.policy_loss,
                            metric.value_loss,
                            metric.entropy,
                            metric.approximate_kl,
                            metric.clip_fraction,
                        ]
                    )
                )
            )
        self.assertTrue(
            any(
                not np.array_equal(before[name], parameter)
                for name, parameter in policy.parameter_arrays().items()
            )
        )

    def test_rollout_parser_rejects_drift_and_accepts_valid_frame(self) -> None:
        observation = ",".join(["0"] * len(spec.OBSERVATION_NAMES))
        movement_mask = "1" * len(spec.MOVEMENT_ACTION_NAMES)
        cast_mask = "1" * len(spec.CAST_ACTION_NAMES)
        fields = [
            "R",
            str(spec.TRAJECTORY_VERSION),
            "2",
            "2305843009213704704",
            "100",
            "1",
            "2",
            "-0.5",
            "0.1",
            "0.2",
            "0",
            observation,
            movement_mask,
            cast_mask,
        ]
        records = parse_rollout_output(
            "\t".join(fields) + "\nbuffered=0\n",
            expected_count=1,
        )
        self.assertEqual(records[0].movement_action, 1)
        self.assertEqual(
            records[0].participant_id,
            2305843009213704704,
        )

        fields[12] = "1" + "0" * (len(movement_mask) - 1)
        with self.assertRaisesRegex(
            RuntimeError,
            "masked movement action",
        ):
            parse_rollout_output(
                "\t".join(fields),
                expected_count=1,
            )

    def test_rollout_batch_bootstraps_the_matching_trajectory(self) -> None:
        records = [
            _record(tick=10, reward=0.2, value=0.1),
            _record(tick=20, reward=0.3, value=0.2),
        ]
        bootstrap = [_record(tick=30, reward=0.0, value=0.4)]
        batch = prepare_rollout_batch(
            records,
            bootstrap,
            gamma=0.9,
            gae_lambda=0.8,
        )
        expected_advantages, expected_returns = (
            generalized_advantage_estimate(
                np.asarray([0.2, 0.3]),
                np.asarray([0.1, 0.2]),
                np.asarray([False, False]),
                bootstrap_value=0.4,
                gamma=0.9,
                gae_lambda=0.8,
            )
        )
        np.testing.assert_allclose(batch["advantages"], expected_advantages)
        np.testing.assert_allclose(batch["returns"], expected_returns)
        self.assertEqual(
            batch["observations"].shape,
            (2, len(spec.OBSERVATION_NAMES)),
        )

    def test_lua_and_python_inference_match(self) -> None:
        command = self._lua_command()
        if command is None:
            self.skipTest("Lua 5.4 or WSL Lua is unavailable")
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30.0,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        values = {}
        for line in completed.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
        self.assertEqual(values.get("training_ring_ok"), "true")

        observation = np.asarray(
            [
                ((index * 37) % 101 - 50) / 50
                for index in range(1, len(spec.OBSERVATION_NAMES) + 1)
            ]
        )
        movement_mask = np.asarray(
            [
                index % 3 != 0
                for index in range(
                    1,
                    len(spec.MOVEMENT_ACTION_NAMES) + 1,
                )
            ]
        )
        cast_mask = np.asarray(
            [
                index % 4 != 0
                for index in range(
                    1,
                    len(spec.CAST_ACTION_NAMES) + 1,
                )
            ]
        )
        forward = load_model(MODEL).forward(
            observation,
            movement_mask[None, :],
            cast_mask[None, :],
        )
        self.assertEqual(
            int(values["movement_action"]),
            int(np.argmax(forward.movement_probabilities[0])),
        )
        self.assertEqual(
            int(values["cast_action"]),
            int(np.argmax(forward.cast_probabilities[0])),
        )
        self.assertAlmostEqual(
            float(values["value"]),
            float(forward.values[0]),
            places=11,
        )
        np.testing.assert_allclose(
            np.fromstring(values["movement_probabilities"], sep=","),
            forward.movement_probabilities[0],
            rtol=2e-12,
            atol=2e-12,
        )
        np.testing.assert_allclose(
            np.fromstring(values["cast_probabilities"], sep=","),
            forward.cast_probabilities[0],
            rtol=2e-12,
            atol=2e-12,
        )

    def _lua_command(self) -> list[str] | None:
        lua = shutil.which("lua")
        if lua:
            return [lua, str(LUA_CONTRACT), str(ROOT)]

        wsl = shutil.which("wsl.exe")
        if wsl is None:
            system_wsl = Path("C:/Windows/System32/wsl.exe")
            if system_wsl.is_file():
                wsl = str(system_wsl)
        if not wsl:
            return None
        resolved = ROOT.resolve()
        if not resolved.drive:
            return None
        linux_root = (
            f"/mnt/{resolved.drive[0].lower()}/"
            + resolved.as_posix().split(":/", 1)[1]
        )
        return [
            wsl,
            "lua",
            f"{linux_root}/tests/lua/ml_bot_policy_contract.lua",
            linux_root,
        ]


if __name__ == "__main__":
    unittest.main()
