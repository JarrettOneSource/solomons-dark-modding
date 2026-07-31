#!/usr/bin/env python3
"""Numerical, serialization, Lua-parity, and trajectory-v2 tests."""

from __future__ import annotations

import copy
import math
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
from ml_bot.bridge import (  # noqa: E402
    POLICY_LOAD_CHUNK_BYTES,
    RolloutRecord,
    SoloSession,
    parse_rollout_output,
)
from ml_bot.compositions import (  # noqa: E402
    TeamComposition,
    build_roster,
    load_compositions,
    select_compositions,
)
from ml_bot.expert import generate_expert_dataset  # noqa: E402
from ml_bot.model import (  # noqa: E402
    Adam,
    BotPolicy,
    behavior_clone_batch,
    export_lua_weights,
    generalized_advantage_estimate,
    load_model,
    ppo_batch,
    ppo_epochs,
    render_lua_weights,
    save_model,
    selected_log_probabilities,
)
from train_bot_policy import (  # noqa: E402
    partition_rollout_records,
    prepare_rollout_batch,
)


MODEL = ROOT / "models" / "bot-brain" / "policy-v2.json"
HISTORICAL_V1_MODEL = ROOT / "models" / "bot-brain" / "policy-v1.json"
LUA_WEIGHTS = ROOT / "mods" / "bot-brain" / "scripts" / "policy_weights.lua"
LUA_CONTRACT = ROOT / "tests" / "lua" / "ml_bot_policy_v3_phase3.lua"
COMPOSITIONS = ROOT / "tools" / "ml_bot" / "team-compositions.json"


def _record(
    *,
    tick: int,
    reward: float,
    value: float,
    done: bool = False,
    participant_id: int = 42,
    episode_id: int = 3,
) -> RolloutRecord:
    return RolloutRecord(
        trajectory_version=spec.TRAJECTORY_VERSION,
        episode_id=episode_id,
        participant_id=participant_id,
        simulation_tick=tick,
        observation=[0.01 * tick] * len(spec.OBSERVATION_NAMES),
        movement_mask=[True] * len(spec.MOVEMENT_ACTION_NAMES),
        target_mask=[True] * len(spec.TARGET_ACTION_NAMES),
        cast_mask=[True] * len(spec.CAST_ACTION_NAMES),
        movement_action=1,
        target_action=3,
        cast_action=2,
        old_log_probability=-2.5,
        old_value=value,
        reward=reward,
        done=done,
    )


class MlBotPolicyTests(unittest.TestCase):
    def test_contract_is_exact_policy_v2(self) -> None:
        self.assertEqual(spec.MODEL_VERSION, 2)
        self.assertEqual(spec.OBSERVATION_VERSION, 2)
        self.assertEqual(spec.TRAJECTORY_VERSION, 2)
        self.assertEqual(spec.ARCHITECTURE, "mlp-tanh-three-head-v2")
        self.assertEqual(spec.HIDDEN_SIZES, (192, 96))
        self.assertEqual(len(spec.OBSERVATION_NAMES), 395)
        self.assertEqual(len(set(spec.OBSERVATION_NAMES)), 395)
        self.assertEqual(len(spec.MOVEMENT_ACTION_NAMES), 9)
        self.assertEqual(len(spec.TARGET_ACTION_NAMES), 9)
        self.assertEqual(len(spec.CAST_ACTION_NAMES), 10)
        self.assertEqual(
            spec.model_shape(),
            {
                "observation_size": 395,
                "hidden_sizes": [192, 96],
                "movement_action_size": 9,
                "target_action_size": 9,
                "cast_action_size": 10,
                "value_size": 1,
            },
        )
        self.assertEqual(spec.MANA_SCALE, 2000.0)
        self.assertEqual(spec.HP_SCALE, 1000.0)
        self.assertEqual(spec.VELOCITY_SCALE, 1000.0)
        self.assertEqual(spec.COOLDOWN_SCALE, 60.0)

    def test_seed_model_is_strict_and_passes_bootstrap_gates(self) -> None:
        policy = load_model(MODEL)
        self.assertEqual(policy.input_weight.shape, (192, 395))
        self.assertEqual(policy.hidden_weight.shape, (96, 192))
        self.assertEqual(policy.movement_weight.shape, (9, 96))
        self.assertEqual(policy.target_weight.shape, (9, 96))
        self.assertEqual(policy.cast_weight.shape, (10, 96))
        self.assertEqual(policy.value_weight.shape, (96,))
        self.assertEqual(
            policy.metadata["training_kind"],
            "target_first_semantic_behavior_cloning_v2",
        )
        self.assertGreaterEqual(
            policy.metadata["validation_movement_accuracy"],
            0.90,
        )
        self.assertGreaterEqual(
            policy.metadata["validation_target_accuracy"],
            0.80,
        )
        self.assertGreaterEqual(
            policy.metadata["validation_cast_accuracy"],
            0.92,
        )
        self.assertGreaterEqual(
            policy.metadata["validation_joint_accuracy"],
            0.72,
        )

        invalid = copy.deepcopy(policy.to_dict())
        invalid["observation_names"][0] = "contract_drift"
        with self.assertRaisesRegex(ValueError, "observation_names"):
            BotPolicy.from_dict(invalid)
        invalid = copy.deepcopy(policy.to_dict())
        invalid["parameters"]["hidden_weight"] = invalid["parameters"][
            "hidden_weight"
        ][:-1]
        with self.assertRaisesRegex(ValueError, "hidden_weight has shape"):
            BotPolicy.from_dict(invalid)

    def test_v1_model_is_rejected_with_a_clear_error(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "v1 artifacts are incompatible.*policy-v2",
        ):
            load_model(HISTORICAL_V1_MODEL)

    def test_json_and_lua_artifacts_are_identical_exports(self) -> None:
        policy = load_model(MODEL)
        self.assertEqual(
            render_lua_weights(policy).encode("utf-8"),
            LUA_WEIGHTS.read_bytes(),
        )

    def test_model_exports_use_repository_line_endings(self) -> None:
        policy = load_model(MODEL)
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "policy.json"
            lua_path = Path(directory) / "policy.lua"
            save_model(policy, model_path)
            export_lua_weights(policy, lua_path)
            reloaded = load_model(model_path)
            for name, parameter in policy.parameter_arrays().items():
                np.testing.assert_array_equal(
                    parameter,
                    reloaded.parameter_arrays()[name],
                )
            for path in (model_path, lua_path):
                contents = path.read_bytes()
                self.assertNotIn(b"\r", contents)
                self.assertTrue(contents.endswith(b"\n"))

    def test_hot_reload_stages_sub_limit_chunks_before_commit(self) -> None:
        policy = load_model(MODEL)
        session = object.__new__(SoloSession)
        calls: list[str] = []

        def fake_lua(code: str, *, timeout: float = 15.0) -> str:
            del timeout
            calls.append(code)
            if "load_parameters(candidate)" in code:
                return "generation=7"
            return "ok=true"

        session.lua = fake_lua
        self.assertEqual(session.load_policy(policy), 7)
        self.assertGreater(len(calls), 4)
        self.assertLess(
            max(len(code.encode("utf-8")) for code in calls),
            1024 * 1024,
        )
        self.assertEqual(POLICY_LOAD_CHUNK_BYTES, 512 * 1024)
        self.assertIn("__sdmod_ml_policy_staging", calls[0])
        self.assertEqual(
            sum("staging.parts[" in code for code in calls),
            math.ceil(
                len(render_lua_weights(policy)) / POLICY_LOAD_CHUNK_BYTES
            ),
        )
        self.assertIn("load_parameters(candidate)", calls[-1])

        failed_calls: list[str] = []

        def fail_mid_transfer(
            code: str,
            *,
            timeout: float = 15.0,
        ) -> str:
            del timeout
            failed_calls.append(code)
            if "staging.parts[2]" in code:
                raise RuntimeError("injected transfer failure")
            return "ok=true"

        session.lua = fail_mid_transfer
        with self.assertRaisesRegex(RuntimeError, "injected transfer failure"):
            session.load_policy(policy)
        self.assertFalse(
            any(
                "load_parameters(candidate)" in code
                for code in failed_calls
            )
        )
        self.assertEqual(
            failed_calls[-1],
            "_G.__sdmod_ml_policy_staging = nil",
        )

    def test_target_first_bootstrap_batch_is_finite_and_legal(self) -> None:
        rng = np.random.default_rng(90210)
        dataset = generate_expert_dataset(512, rng=rng)
        self.assertEqual(dataset.observations.shape, (512, 395))
        self.assertTrue(np.all(np.isfinite(dataset.observations)))
        rows = np.arange(512)
        self.assertTrue(
            np.all(
                dataset.movement_masks[rows, dataset.movement_actions]
            )
        )
        self.assertTrue(
            np.all(dataset.target_masks[rows, dataset.target_actions])
        )
        self.assertTrue(np.all(dataset.cast_masks[rows, dataset.cast_actions]))
        self.assertTrue(np.any(dataset.target_actions == 0))
        self.assertTrue(np.any(dataset.target_actions > 0))

        policy = BotPolicy.initialize(np.random.default_rng(90211))
        loss, gradient_norm = behavior_clone_batch(
            policy,
            Adam(policy.parameter_arrays(), learning_rate=0.001),
            dataset.observations,
            dataset.movement_masks,
            dataset.target_masks,
            dataset.cast_masks,
            dataset.movement_actions,
            dataset.target_actions,
            dataset.cast_actions,
        )
        self.assertTrue(math.isfinite(loss))
        self.assertTrue(math.isfinite(gradient_norm))

    def test_composite_log_probability_sums_all_three_heads(self) -> None:
        rng = np.random.default_rng(1800)
        policy = BotPolicy.initialize(rng)
        rows = 8
        observations = rng.uniform(-1.0, 1.0, size=(rows, 395))
        movement_masks = np.ones((rows, 9), dtype=np.bool_)
        target_masks = np.ones((rows, 9), dtype=np.bool_)
        cast_masks = np.ones((rows, 10), dtype=np.bool_)
        actions = policy.act(
            observations,
            movement_masks,
            target_masks,
            cast_masks,
            deterministic=False,
            rng=rng,
        )
        expected = (
            selected_log_probabilities(
                actions.movement_probabilities,
                actions.movement_actions,
            )
            + selected_log_probabilities(
                actions.target_probabilities,
                actions.target_actions,
            )
            + selected_log_probabilities(
                actions.cast_probabilities,
                actions.cast_actions,
            )
        )
        np.testing.assert_allclose(actions.log_probabilities, expected)

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
        count = 48
        observations = rng.uniform(-1.0, 1.0, size=(count, 395))
        movement_masks = np.ones((count, 9), dtype=np.bool_)
        target_masks = np.ones((count, 9), dtype=np.bool_)
        cast_masks = np.ones((count, 10), dtype=np.bool_)
        actions = policy.act(
            observations,
            movement_masks,
            target_masks,
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
            target_masks,
            cast_masks,
            actions.movement_actions,
            actions.target_actions,
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
                            metric.movement_entropy,
                            metric.target_entropy,
                            metric.cast_entropy,
                            metric.approximate_kl,
                            metric.clip_fraction,
                            metric.gradient_norm,
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

    def test_target_entropy_default_resists_keep_current_collapse(self) -> None:
        self.assertEqual(
            spec.TARGET_ENTROPY_COEFFICIENT,
            2.0 * spec.MOVEMENT_ENTROPY_COEFFICIENT,
        )
        self.assertEqual(
            spec.TARGET_ENTROPY_COEFFICIENT,
            2.0 * spec.CAST_ENTROPY_COEFFICIENT,
        )
        rng = np.random.default_rng(1802)
        policy = BotPolicy.initialize(rng)
        policy.target_weight.fill(0.0)
        policy.target_bias.fill(0.0)
        policy.target_bias[0] = 3.0
        rows = 32
        observations = np.zeros((rows, 395))
        movement_masks = np.zeros((rows, 9), dtype=np.bool_)
        movement_masks[:, 0] = True
        target_masks = np.ones((rows, 9), dtype=np.bool_)
        cast_masks = np.zeros((rows, 10), dtype=np.bool_)
        cast_masks[:, 0] = True
        before = policy.act(
            observations,
            movement_masks,
            target_masks,
            cast_masks,
            deterministic=True,
        )
        before_entropy = -np.sum(
            before.target_probabilities[0]
            * np.log(before.target_probabilities[0])
        )
        metrics = ppo_batch(
            policy,
            Adam(policy.parameter_arrays(), learning_rate=0.01),
            observations,
            movement_masks,
            target_masks,
            cast_masks,
            before.movement_actions,
            before.target_actions,
            before.cast_actions,
            before.log_probabilities,
            np.zeros(rows),
            before.values,
            movement_entropy_coefficient=0.0,
            target_entropy_coefficient=spec.TARGET_ENTROPY_COEFFICIENT,
            cast_entropy_coefficient=0.0,
        )
        after = policy.act(
            observations,
            movement_masks,
            target_masks,
            cast_masks,
            deterministic=True,
        )
        after_entropy = -np.sum(
            after.target_probabilities[0]
            * np.log(after.target_probabilities[0])
        )
        self.assertGreater(after_entropy, before_entropy)
        self.assertGreater(metrics.target_entropy, 0.0)

    def test_rollout_parser_is_strict_trajectory_v2(self) -> None:
        observation = ",".join(["0"] * len(spec.OBSERVATION_NAMES))
        movement_mask = "1" * len(spec.MOVEMENT_ACTION_NAMES)
        target_mask = "1" * len(spec.TARGET_ACTION_NAMES)
        cast_mask = "1" * len(spec.CAST_ACTION_NAMES)
        fields = [
            "R",
            str(spec.TRAJECTORY_VERSION),
            "2",
            "2305843009213704705",
            "100",
            "1",
            "3",
            "2",
            "-0.5",
            "0.1",
            "0.2",
            "0",
            observation,
            movement_mask,
            target_mask,
            cast_mask,
        ]
        records = parse_rollout_output(
            "\t".join(fields) + "\nbuffered=0\n",
            expected_count=1,
        )
        self.assertEqual(records[0].target_action, 3)
        self.assertEqual(
            records[0].participant_id,
            2305843009213704705,
        )

        invalid = fields.copy()
        invalid[14] = "1" + "0" * (len(target_mask) - 1)
        with self.assertRaisesRegex(RuntimeError, "masked target action"):
            parse_rollout_output("\t".join(invalid), expected_count=1)
        invalid = fields.copy()
        invalid[1] = "1"
        with self.assertRaisesRegex(RuntimeError, "trajectory-v1.*trajectory-v2"):
            parse_rollout_output("\t".join(invalid), expected_count=1)
        with self.assertRaisesRegex(RuntimeError, "15 fields"):
            parse_rollout_output(
                "\t".join(fields[:-1]),
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
        self.assertEqual(batch["observations"].shape, (2, 395))
        self.assertEqual(batch["target_masks"].shape, (2, 9))
        np.testing.assert_array_equal(batch["target_actions"], [3, 3])

    def test_multi_participant_rollouts_reserve_matching_bootstraps(
        self,
    ) -> None:
        records = [
            _record(
                tick=10,
                reward=0.1,
                value=0.2,
                participant_id=41,
            ),
            _record(
                tick=10,
                reward=0.3,
                value=0.4,
                participant_id=42,
            ),
            _record(
                tick=20,
                reward=0.5,
                value=0.6,
                participant_id=41,
            ),
            _record(
                tick=20,
                reward=0.7,
                value=0.8,
                participant_id=42,
            ),
        ]
        training, bootstrap = partition_rollout_records(
            records,
            expected_participant_ids=(41, 42),
        )
        self.assertEqual(
            [record.participant_id for record in training],
            [41, 42],
        )
        self.assertEqual(
            [record.participant_id for record in bootstrap],
            [41, 42],
        )
        batch = prepare_rollout_batch(
            training,
            bootstrap,
            gamma=0.9,
            gae_lambda=0.8,
        )
        self.assertEqual(batch["observations"].shape, (2, 395))
        with self.assertRaisesRegex(
            ValueError,
            "do not match the learned composition",
        ):
            partition_rollout_records(
                records,
                expected_participant_ids=(41,),
            )

    def test_team_composition_rotation_is_config_driven(self) -> None:
        compositions = load_compositions(COMPOSITIONS)
        self.assertTrue(any(item.kind == "solo" for item in compositions))
        self.assertTrue(any(item.kind == "mixed" for item in compositions))
        self.assertTrue(
            any(item.kind == "multi-learned" for item in compositions)
        )
        selected = select_compositions(
            compositions,
            ("solo-learned", "multi-learned-2"),
        )
        self.assertEqual(
            [item.name for item in selected],
            ["solo-learned", "multi-learned-2"],
        )
        roster = build_roster(
            TeamComposition(
                "fixture",
                1,
                ("skirmisher", "guardian", "striker"),
            ),
            element="fire",
            discipline="arcane",
        )
        self.assertEqual(
            [row["behavior"] for row in roster],
            ["learned", "skirmisher", "guardian", "striker"],
        )
        # No parser-side participant maximum: the cap-raise workstream can
        # expand only configuration.
        large = TeamComposition("future-cap", 51, ())
        self.assertEqual(
            len(
                build_roster(
                    large,
                    element="fire",
                    discipline="arcane",
                )
            ),
            51,
        )

    def test_seed_round_trip_uses_the_native_rng_contract(self) -> None:
        session = object.__new__(SoloSession)
        calls: list[str] = []

        def fake_lua(code: str, *, timeout: float = 15.0) -> str:
            del timeout
            calls.append(code)
            return (
                "requested_seed=12345\n"
                "accepted_seed=12345\n"
                "observed_seed=12345\n"
            )

        session.lua = fake_lua
        self.assertEqual(
            session.set_run_seed(12345),
            {
                "requested_seed": 12345,
                "accepted_seed": 12345,
                "observed_seed": 12345,
            },
        )
        self.assertIn("sd.rng.set_seed(requested)", calls[0])
        self.assertIn("sd.rng.get_seed()", calls[0])

    def test_lua_policy_v3_phase3_contract_fixture(self) -> None:
        values = self._run_lua_contract()
        expected = {
            "observation_count": "1279",
            "exact_order": "true",
            "finite": "true",
            "exact_geometry": "true",
            "enemy_status_transition": "true",
            "target_motion_facing": "true",
            "obstacle_transition": "true",
            "unknown_hazard_retained": "true",
            "hazard_transition": "true",
            "potion_transition": "true",
            "equipment_transition": "true",
            "permanent_potion_masks": "true",
            "aim_family_masks": "true",
            "target_conditioned_ability_masks": "true",
            "choice_descriptor_count": "56",
            "choice_permutation_invariant": "true",
            "choice_generation_exactly_once": "true",
            "choice_duration_steps": "2",
            "scripted_choice_excluded": "true",
            "trajectory_v3": "true",
        }
        for key, expected_value in expected.items():
            self.assertEqual(values.get(key), expected_value, key)
        self.assertEqual(values.get("geometry_builds"), "2")

    def _run_lua_contract(self) -> dict[str, str]:
        command = self._lua_command()
        if command is None:
            self.skipTest("Lua 5.4 or WSL Lua is unavailable")
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=60.0,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        values = {}
        for line in completed.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
        return values

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
