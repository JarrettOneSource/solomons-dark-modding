#!/usr/bin/env python3
"""Numerical, serialization, Lua-parity, and trajectory-v3 tests."""

from __future__ import annotations

import copy
from dataclasses import replace
import json
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
    MAX_CHOICE_ROLLOUTS_PER_RESPONSE,
    MAX_ROLLOUTS_PER_RESPONSE,
    POLICY_LOAD_CHUNK_BYTES,
    ChoiceRolloutRecord,
    RolloutRecord,
    SoloSession,
    parse_choice_rollout_output,
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
    ChoiceCoverage,
    behavior_clone_batch,
    choice_ppo_batch,
    export_lua_weights,
    generalized_advantage_estimate,
    load_model,
    ppo_epochs,
    render_lua_weights,
    save_model,
    selected_log_probabilities,
    smdp_advantage_estimate,
)
from train_bot_policy import (  # noqa: E402
    MAX_LIVE_ROLLOUT_STEPS,
    concatenate_choice_batches,
    partition_choice_records,
    partition_rollout_records,
    prepare_choice_batch,
    prepare_rollout_batch,
)


MODEL = ROOT / "models" / "bot-brain" / "policy-v3.json"
HISTORICAL_V1_MODEL = ROOT / "models" / "bot-brain" / "policy-v1.json"
HISTORICAL_V2_MODEL = ROOT / "models" / "bot-brain" / "policy-v2.json"
LUA_WEIGHTS = ROOT / "mods" / "bot-brain" / "scripts" / "policy_weights.lua"
LUA_CONTRACT = ROOT / "tests" / "lua" / "ml_bot_policy_contract.lua"
LUA_PHASE3 = ROOT / "tests" / "lua" / "ml_bot_policy_v3_phase3.lua"
COMPOSITIONS = ROOT / "tools" / "ml_bot" / "team-compositions.json"


def _main_record(
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
        ability_mask=[True] * len(spec.ABILITY_ACTION_NAMES),
        aim_mask=[True] * len(spec.AIM_ACTION_NAMES),
        movement_action=1,
        target_action=3,
        ability_action=2,
        aim_action=4,
        old_log_probability=-4.5,
        old_value=value,
        reward=reward,
        done=done,
    )


def _choice_record(
    *,
    tick: int = 10,
    generation: int = 1,
    duration: int = 2,
    done: bool = True,
    option_count: int = 3,
    participant_id: int = 42,
) -> ChoiceRolloutRecord:
    descriptors = [
        [((row + 1) * (column + 3) % 17) / 17.0 for column in range(56)]
        for row in range(option_count)
    ]
    return ChoiceRolloutRecord(
        choice_trajectory_version=spec.CHOICE_TRAJECTORY_VERSION,
        episode_id=4,
        participant_id=participant_id,
        generation=generation,
        simulation_tick=tick,
        observation=[0.0] * len(spec.OBSERVATION_NAMES),
        option_descriptors=descriptors,
        option_mask=[True] * option_count,
        selected_option=1,
        old_log_probability=-math.log(option_count),
        old_value=0.1,
        next_value=0.0 if done else 0.2,
        duration_steps=duration,
        rewards=[0.2] * duration,
        done=done,
        choice_mode="learned",
        trainable=True,
        accepted=True,
    )


class MlBotPolicyTests(unittest.TestCase):
    def test_contract_is_exact_policy_v3(self) -> None:
        self.assertEqual(spec.MODEL_VERSION, 3)
        self.assertEqual(spec.OBSERVATION_VERSION, 3)
        self.assertEqual(spec.TRAJECTORY_VERSION, 3)
        self.assertEqual(spec.CHOICE_TRAJECTORY_VERSION, 3)
        self.assertEqual(spec.ARCHITECTURE, "mlp-tanh-four-head-v3")
        self.assertEqual(spec.HIDDEN_SIZES, (512, 256))
        self.assertEqual(spec.CHOICE_HIDDEN_SIZE, 128)
        self.assertEqual(len(spec.OBSERVATION_NAMES), 1279)
        self.assertEqual(len(set(spec.OBSERVATION_NAMES)), 1279)
        self.assertEqual(len(spec.OPTION_DESCRIPTOR_NAMES), 56)
        self.assertEqual(
            spec.model_shape(),
            {
                "observation_size": 1279,
                "hidden_sizes": [512, 256],
                "movement_action_size": 9,
                "target_action_size": 9,
                "ability_action_size": 22,
                "aim_action_size": 9,
                "value_size": 1,
                "option_descriptor_size": 56,
                "choice_hidden_size": 128,
                "choice_value_size": 1,
            },
        )
        self.assertEqual(spec.INVENTORY_COUNT_SATURATION, 99.0)
        self.assertEqual(spec.CHOICE_ENTROPY_COEFFICIENT, 0.05)
        self.assertEqual(spec.CHOICE_EXPLORATION_TEMPERATURE, 1.25)
        self.assertEqual(spec.CHOICE_FINAL_TEMPERATURE, 1.0)
        self.assertEqual(spec.CHOICE_COVERAGE_THRESHOLD, 20)
        self.assertEqual(MAX_ROLLOUTS_PER_RESPONSE, 16)
        self.assertEqual(MAX_CHOICE_ROLLOUTS_PER_RESPONSE, 1)
        self.assertEqual(MAX_LIVE_ROLLOUT_STEPS, 8192)

        maximum_float = "-1.7976931348623157e+308"
        main_frame = "\t".join(
            (
                "R", "3", "1", "2305843009213704705", "999999999",
                "8", "8", "21", "8", maximum_float, maximum_float,
                maximum_float, "0",
                ",".join([maximum_float] * 1279),
                "1" * 9, "1" * 9, "1" * 22, "1" * 9,
            )
        )
        main_response = json.dumps(
            {
                "ok": True,
                "print_output": "\n".join(
                    [main_frame] * MAX_ROLLOUTS_PER_RESPONSE
                ),
                "results": [],
                "error": "",
            }
        ).encode()
        self.assertLess(len(main_response), 1024 * 1024)

        descriptors = ";".join(
            [",".join([maximum_float] * 56)] * spec.MAX_CHOICE_OPTIONS
        )
        choice_frame = "\t".join(
            (
                "C", "3", "1", "2305843009213704705", "999", "999999999",
                "15", maximum_float, maximum_float, maximum_float,
                str(MAX_LIVE_ROLLOUT_STEPS),
                "1", "1", "1", "learned",
                ",".join([maximum_float] * 1279),
                "1" * spec.MAX_CHOICE_OPTIONS,
                descriptors,
                ",".join(
                    ["-3.9999999999999996"] * MAX_LIVE_ROLLOUT_STEPS
                ),
            )
        )
        choice_response = json.dumps(
            {
                "ok": True,
                "print_output": choice_frame,
                "results": [],
                "error": "",
            }
        ).encode()
        self.assertLess(len(choice_response), 1024 * 1024)

    def test_seed_model_is_strict_v3_and_bootstrap_is_finite(self) -> None:
        policy = load_model(MODEL)
        self.assertEqual(policy.input_weight.shape, (512, 1279))
        self.assertEqual(policy.hidden_weight.shape, (256, 512))
        self.assertEqual(policy.movement_weight.shape, (9, 256))
        self.assertEqual(policy.target_weight.shape, (9, 256))
        self.assertEqual(policy.ability_weight.shape, (22, 256))
        self.assertEqual(policy.aim_weight.shape, (9, 256))
        self.assertEqual(policy.choice_option_weight.shape, (128, 312))
        self.assertEqual(policy.choice_score_weight.shape, (128,))
        self.assertEqual(policy.choice_value_weight.shape, (256,))
        self.assertEqual(
            policy.metadata["training_kind"],
            "target_aim_potion_semantic_bootstrap_v3",
        )
        for head in ("movement", "target", "ability", "aim", "joint"):
            value = policy.metadata[f"validation_{head}_accuracy"]
            self.assertTrue(math.isfinite(value))
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

        invalid = copy.deepcopy(policy.to_dict())
        invalid["observation_names"][0] = "contract_drift"
        with self.assertRaisesRegex(ValueError, "observation_names"):
            BotPolicy.from_dict(invalid)
        invalid = copy.deepcopy(policy.to_dict())
        invalid["parameters"]["choice_option_weight"] = invalid[
            "parameters"
        ]["choice_option_weight"][:-1]
        with self.assertRaisesRegex(ValueError, "choice_option_weight has shape"):
            BotPolicy.from_dict(invalid)

    def test_v1_and_v2_models_are_rejected_clearly(self) -> None:
        for path in (HISTORICAL_V1_MODEL, HISTORICAL_V2_MODEL):
            with self.subTest(path=path.name), self.assertRaisesRegex(
                ValueError,
                "v1/v2 artifacts are incompatible.*policy-v3",
            ):
                load_model(path)

    def test_json_and_lua_artifacts_are_identical_exports(self) -> None:
        policy = load_model(MODEL)
        self.assertEqual(
            render_lua_weights(policy).encode("utf-8"),
            LUA_WEIGHTS.read_bytes(),
        )

    def test_model_round_trip_preserves_every_parameter(self) -> None:
        policy = load_model(MODEL)
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "policy.json"
            lua_path = Path(directory) / "policy.lua"
            save_model(policy, model_path)
            export_lua_weights(policy, lua_path)
            reloaded = load_model(model_path)
            for name, parameter in policy.parameter_arrays().items():
                np.testing.assert_array_equal(
                    parameter, reloaded.parameter_arrays()[name]
                )
            self.assertEqual(
                policy.choice_temperature, reloaded.choice_temperature
            )
            for path in (model_path, lua_path):
                contents = path.read_bytes()
                self.assertNotIn(b"\r", contents)
                self.assertTrue(contents.endswith(b"\n"))

    def test_hot_reload_stages_large_artifact_before_atomic_commit(self) -> None:
        policy = load_model(MODEL)
        session = object.__new__(SoloSession)
        calls: list[str] = []

        def fake_lua(code: str, *, timeout: float = 15.0) -> str:
            del timeout
            calls.append(code)
            return "generation=7" if "load_parameters(candidate)" in code else "ok=true"

        session.lua = fake_lua
        self.assertEqual(session.load_policy(policy), 7)
        self.assertGreater(len(calls), 10)
        self.assertLess(
            max(len(code.encode("utf-8")) for code in calls), 1024 * 1024
        )
        self.assertEqual(POLICY_LOAD_CHUNK_BYTES, 512 * 1024)
        self.assertIn("@ml-bot-policy-v3-hot-reload", calls[-1])
        self.assertEqual(
            sum("staging.parts[" in code for code in calls),
            math.ceil(len(render_lua_weights(policy)) / POLICY_LOAD_CHUNK_BYTES),
        )

        failed_calls: list[str] = []

        def fail_mid_transfer(code: str, *, timeout: float = 15.0) -> str:
            del timeout
            failed_calls.append(code)
            if "staging.parts[2]" in code:
                raise RuntimeError("injected transfer failure")
            return "ok=true"

        session.lua = fail_mid_transfer
        with self.assertRaisesRegex(RuntimeError, "injected transfer failure"):
            session.load_policy(policy)
        self.assertFalse(
            any("load_parameters(candidate)" in code for code in failed_calls)
        )
        self.assertEqual(
            failed_calls[-1], "_G.__sdmod_ml_policy_staging = nil"
        )

    def test_target_aim_potion_bootstrap_batch_is_finite_and_legal(self) -> None:
        dataset = generate_expert_dataset(
            256, rng=np.random.default_rng(90210)
        )
        self.assertEqual(dataset.observations.shape, (256, 1279))
        self.assertTrue(np.all(np.isfinite(dataset.observations)))
        rows = np.arange(256)
        for masks, actions in (
            (dataset.movement_masks, dataset.movement_actions),
            (dataset.target_masks, dataset.target_actions),
            (dataset.ability_masks, dataset.ability_actions),
            (dataset.aim_masks, dataset.aim_actions),
        ):
            self.assertTrue(np.all(masks[rows, actions]))
        self.assertTrue(np.any(dataset.ability_actions >= 10))
        self.assertTrue(np.any(dataset.aim_actions > 0))
        policy = BotPolicy.initialize(np.random.default_rng(90211))
        loss, gradient_norm = behavior_clone_batch(
            policy,
            Adam(policy.parameter_arrays(), learning_rate=0.001),
            *(getattr(dataset, name) for name in (
                "observations",
                "movement_masks",
                "target_masks",
                "ability_masks",
                "aim_masks",
                "movement_actions",
                "target_actions",
                "ability_actions",
                "aim_actions",
            )),
        )
        self.assertTrue(math.isfinite(loss))
        self.assertTrue(math.isfinite(gradient_norm))

    def test_composite_log_probability_sums_all_four_heads(self) -> None:
        rng = np.random.default_rng(1800)
        policy = BotPolicy.initialize(rng)
        observations = rng.uniform(-1.0, 1.0, size=(8, 1279))
        mask9 = np.ones((8, 9), dtype=np.bool_)
        mask22 = np.ones((8, 22), dtype=np.bool_)
        actions = policy.act(
            observations,
            mask9,
            mask9,
            mask22,
            mask9,
            deterministic=False,
            rng=rng,
        )
        expected = sum(
            selected_log_probabilities(probabilities, selected)
            for probabilities, selected in (
                (actions.movement_probabilities, actions.movement_actions),
                (actions.target_probabilities, actions.target_actions),
                (actions.ability_probabilities, actions.ability_actions),
                (actions.aim_probabilities, actions.aim_actions),
            )
        )
        np.testing.assert_allclose(actions.log_probabilities, expected)

    def test_main_ppo_update_is_finite_and_changes_parameters(self) -> None:
        rng = np.random.default_rng(1801)
        policy = BotPolicy.initialize(rng)
        count = 24
        observations = rng.uniform(-1.0, 1.0, size=(count, 1279))
        mask9 = np.ones((count, 9), dtype=np.bool_)
        mask22 = np.ones((count, 22), dtype=np.bool_)
        actions = policy.act(
            observations, mask9, mask9, mask22, mask9,
            deterministic=False, rng=rng,
        )
        rewards = np.linspace(-0.25, 0.75, count)
        dones = np.zeros(count, dtype=np.bool_)
        dones[-1] = True
        advantages, returns = generalized_advantage_estimate(
            rewards, actions.values, dones
        )
        before = {
            name: value.copy() for name, value in policy.parameter_arrays().items()
        }
        metrics = ppo_epochs(
            policy,
            Adam(policy.parameter_arrays(), learning_rate=0.0003),
            observations,
            mask9,
            mask9,
            mask22,
            mask9,
            actions.movement_actions,
            actions.target_actions,
            actions.ability_actions,
            actions.aim_actions,
            actions.log_probabilities,
            advantages,
            returns,
            rng=rng,
            epochs=1,
            batch_size=12,
        )
        self.assertTrue(metrics)
        for metric in metrics:
            self.assertTrue(
                all(
                    math.isfinite(getattr(metric, name))
                    for name in metric.__dataclass_fields__
                )
            )
        self.assertTrue(
            any(
                not np.array_equal(before[name], parameter)
                for name, parameter in policy.parameter_arrays().items()
            )
        )

    def test_choice_smdp_update_and_normalized_entropy_are_finite(self) -> None:
        rewards = [np.asarray([1.0, 2.0]), np.asarray([], dtype=np.float64)]
        advantages, returns = smdp_advantage_estimate(
            rewards,
            np.asarray([2, 0]),
            np.asarray([0.5, 0.2]),
            np.asarray([0.2, 0.0]),
            np.asarray([False, True]),
            gamma=0.9,
            gae_lambda=0.8,
        )
        expected_second = -0.2
        expected_first = (
            1.0 + 0.9 * 2.0 + 0.9**2 * 0.2 - 0.5
            + (0.9 * 0.8) ** 2 * expected_second
        )
        np.testing.assert_allclose(advantages, [expected_first, expected_second])
        np.testing.assert_allclose(returns, advantages + [0.5, 0.2])

        rng = np.random.default_rng(1803)
        policy = BotPolicy.initialize(rng)
        observations = rng.uniform(-1.0, 1.0, size=(8, 1279))
        descriptors = rng.uniform(-1.0, 1.0, size=(8, 4, 56))
        masks = np.ones((8, 4), dtype=np.bool_)
        actions = policy.act_choice(
            observations, descriptors, masks,
            deterministic=False, rng=rng,
        )
        before = policy.choice_score_weight.copy()
        metrics = choice_ppo_batch(
            policy,
            Adam(policy.parameter_arrays(), learning_rate=0.0003),
            observations,
            descriptors,
            masks,
            actions.selected_options,
            actions.log_probabilities,
            np.linspace(-1.0, 1.0, 8),
            np.zeros(8),
        )
        self.assertTrue(
            all(
                math.isfinite(getattr(metrics, name))
                for name in metrics.__dataclass_fields__
            )
        )
        self.assertLessEqual(metrics.normalized_entropy, 1.0 + 1e-12)
        self.assertFalse(np.array_equal(before, policy.choice_score_weight))

    def test_choice_temperature_waits_for_every_offered_key(self) -> None:
        descriptor = np.zeros((2, 56))
        descriptor[0, spec.OPTION_DESCRIPTOR_NAMES.index("family_fire")] = 1.0
        descriptor[1, spec.OPTION_DESCRIPTOR_NAMES.index("family_water")] = 1.0
        coverage = ChoiceCoverage()
        for _ in range(20):
            coverage.observe(descriptor, np.asarray([True, True]), 0)
        self.assertEqual(coverage.temperature, 1.25)
        for _ in range(20):
            coverage.observe(descriptor, np.asarray([True, True]), 1)
        self.assertTrue(coverage.complete)
        self.assertEqual(coverage.temperature, 1.0)
        self.assertEqual(
            ChoiceCoverage.from_dict(coverage.to_dict()).to_dict(),
            coverage.to_dict(),
        )

    def test_main_rollout_parser_is_strict_trajectory_v3(self) -> None:
        fields = [
            "R", "3", "2", "2305843009213704705", "100",
            "1", "3", "2", "4", "-0.5", "0.1", "0.2", "0",
            ",".join(["0"] * 1279),
            "1" * 9,
            "1" * 9,
            "1" * 22,
            "1" * 9,
        ]
        records = parse_rollout_output("\t".join(fields), expected_count=1)
        self.assertEqual(records[0].ability_action, 2)
        self.assertEqual(records[0].aim_action, 4)
        invalid = fields.copy()
        invalid[1] = "2"
        with self.assertRaisesRegex(RuntimeError, "v1/v2.*trajectory-v3"):
            parse_rollout_output("\t".join(invalid), expected_count=1)
        invalid = fields.copy()
        invalid[16] = "1" + "0" * 21
        with self.assertRaisesRegex(RuntimeError, "masked ability action"):
            parse_rollout_output("\t".join(invalid), expected_count=1)

    def test_choice_rollout_parser_is_strict_and_complete(self) -> None:
        descriptor = ",".join(["0"] * 56)
        fields = [
            "C", "3", "4", "42", "9", "100", "1",
            "-0.693", "0.1", "0", "2", "1", "1", "1", "learned",
            ",".join(["0"] * 1279),
            "11",
            descriptor + ";" + descriptor,
            "0.2,0.3",
        ]
        records = parse_choice_rollout_output(
            "\t".join(fields), expected_count=1
        )
        self.assertEqual(records[0].duration_steps, 2)
        self.assertEqual(len(records[0].option_descriptors), 2)
        invalid = fields.copy()
        invalid[18] = "0.2"
        with self.assertRaisesRegex(RuntimeError, "vector has 1 entries"):
            parse_choice_rollout_output("\t".join(invalid), expected_count=1)
        invalid = fields.copy()
        invalid[14] = "scripted"
        with self.assertRaisesRegex(RuntimeError, "trainable flag"):
            parse_choice_rollout_output("\t".join(invalid), expected_count=1)

    def test_main_and_choice_batch_partitioning(self) -> None:
        main = [
            _main_record(tick=10, reward=0.2, value=0.1),
            _main_record(tick=20, reward=0.3, value=0.2),
            _main_record(tick=30, reward=0.1, value=0.4, done=True),
        ]
        training, bootstrap = partition_rollout_records(
            main, expected_participant_ids=(42,)
        )
        self.assertEqual(len(training), 3)
        self.assertEqual(bootstrap, [])
        batch = prepare_rollout_batch(
            training, bootstrap, gamma=0.9, gae_lambda=0.8
        )
        self.assertEqual(batch["observations"].shape, (3, 1279))
        self.assertEqual(batch["ability_masks"].shape, (3, 22))

        first = prepare_choice_batch(
            [_choice_record(option_count=2)], gamma=0.9, gae_lambda=0.8
        )
        second = prepare_choice_batch(
            [_choice_record(option_count=4)], gamma=0.9, gae_lambda=0.8
        )
        combined = concatenate_choice_batches([first, second])
        self.assertEqual(combined["option_descriptors"].shape, (2, 4, 56))
        self.assertEqual(combined["option_masks"].shape, (2, 4))
        self.assertFalse(combined["option_masks"][0, 2])

        descriptor = ",".join(["0"] * 56)
        observation = ",".join(["0"] * 1279)

        def choice_frame(
            participant_id: int,
            mode: str,
            trainable: bool,
        ) -> str:
            return "\t".join(
                (
                    "C", "3", "4", str(participant_id), "9", "100", "0",
                    "0", "0", "0", "0", "1",
                    "1" if trainable else "0", "1", mode,
                    observation, "1", descriptor, "",
                )
            )

        session = object.__new__(SoloSession)
        call_count = 0

        def fake_lua(code: str, *, timeout: float = 15.0) -> str:
            nonlocal call_count
            del timeout
            self.assertIn("drain_choices(1, true)", code)
            call_count += 1
            if call_count == 1:
                return choice_frame(42, "learned", True)
            return choice_frame(43, "scripted", False)

        session.lua = fake_lua
        learned, scripted = session.drain_choice_rollouts(2)
        self.assertEqual(call_count, 2)
        learned_rows, scripted_rows = partition_choice_records(
            [scripted, learned]
        )
        self.assertEqual(learned_rows, [learned])
        self.assertEqual(scripted_rows, [scripted])
        with self.assertRaisesRegex(ValueError, "mode and trainable"):
            partition_choice_records(
                [replace(scripted, trainable=True)]
            )

    def test_multi_participant_rollouts_are_cap_agnostic(self) -> None:
        records = [
            _main_record(tick=10, reward=0.1, value=0.2, participant_id=41),
            _main_record(tick=10, reward=0.3, value=0.4, participant_id=42),
            _main_record(tick=20, reward=0.5, value=0.6, participant_id=41),
            _main_record(tick=20, reward=0.7, value=0.8, participant_id=42),
        ]
        training, bootstrap = partition_rollout_records(
            records, expected_participant_ids=(41, 42)
        )
        self.assertEqual([record.participant_id for record in training], [41, 42])
        self.assertEqual([record.participant_id for record in bootstrap], [41, 42])
        roster = build_roster(
            TeamComposition("future-cap", 51, ()),
            element="fire",
            discipline="arcane",
        )
        self.assertEqual(len(roster), 51)

    def test_team_composition_rotation_is_config_driven(self) -> None:
        compositions = load_compositions(COMPOSITIONS)
        self.assertTrue(any(item.kind == "solo" for item in compositions))
        self.assertTrue(any(item.kind == "mixed" for item in compositions))
        self.assertTrue(any(item.kind == "multi-learned" for item in compositions))
        selected = select_compositions(
            compositions, ("solo-learned", "multi-learned-2")
        )
        self.assertEqual(
            [item.name for item in selected],
            ["solo-learned", "multi-learned-2"],
        )

    def test_seed_round_trip_uses_native_rng_contract(self) -> None:
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

    def test_lua_python_contract_and_inference_parity(self) -> None:
        values = self._run_lua(LUA_CONTRACT)
        self.assertEqual(values["observation_count"], "1279")
        self.assertEqual(values["option_descriptor_count"], "56")
        self.assertEqual(values["hidden_sizes"], "512,256")
        self.assertEqual(values["choice_hidden_size"], "128")
        self.assertEqual(
            values["observation_names"].split(","),
            list(spec.OBSERVATION_NAMES),
        )
        self.assertEqual(
            values["option_descriptor_names"].split(","),
            list(spec.OPTION_DESCRIPTOR_NAMES),
        )
        self.assertEqual(
            values["movement_names"].split(","),
            list(spec.MOVEMENT_ACTION_NAMES),
        )
        self.assertEqual(
            values["target_names"].split(","),
            list(spec.TARGET_ACTION_NAMES),
        )
        self.assertEqual(
            values["ability_names"].split(","),
            list(spec.ABILITY_ACTION_NAMES),
        )
        self.assertEqual(
            values["aim_names"].split(","),
            list(spec.AIM_ACTION_NAMES),
        )
        self.assertEqual(values["v1_rejected"], "true")
        self.assertEqual(values["v2_rejected"], "true")
        self.assertEqual(values["main_only_reset_ok"], "true")
        self.assertEqual(values["training_ring_ok"], "true")

        policy = load_model(MODEL)
        observation = np.asarray(
            [((index * 37) % 101 - 50) / 50 for index in range(1, 1280)]
        )[None, :]
        movement_mask = np.asarray(
            [[index % 3 != 0 for index in range(1, 10)]]
        )
        target_mask = np.asarray(
            [[index % 4 != 0 for index in range(1, 10)]]
        )
        target_action = int(values["target_action"])
        ability_mask = np.asarray(
            [[(index + target_action) % 5 != 0 for index in range(1, 23)]]
        )
        ability_mask[0, 0] = True
        ability_action = int(values["ability_action"])
        aim_mask = np.asarray(
            [[(index + ability_action) % 4 != 0 for index in range(1, 10)]]
        )
        aim_mask[0, 0] = True
        main = policy.act(
            observation,
            movement_mask,
            target_mask,
            ability_mask,
            aim_mask,
            deterministic=True,
        )
        self.assertEqual(main.movement_actions[0], int(values["movement_action"]))
        self.assertEqual(main.target_actions[0], target_action)
        self.assertEqual(main.ability_actions[0], ability_action)
        self.assertEqual(main.aim_actions[0], int(values["aim_action"]))
        for name, probabilities in (
            ("movement", main.movement_probabilities[0]),
            ("target", main.target_probabilities[0]),
            ("ability", main.ability_probabilities[0]),
            ("aim", main.aim_probabilities[0]),
        ):
            np.testing.assert_allclose(
                probabilities,
                np.fromstring(values[f"{name}_probabilities"], sep=","),
                rtol=2e-10,
                atol=2e-12,
            )
        self.assertAlmostEqual(
            main.log_probabilities[0], float(values["log_probability"]), places=10
        )
        self.assertAlmostEqual(main.values[0], float(values["value"]), places=10)

        descriptors = np.asarray(
            [
                [((row + 1) * (column + 5) % 29 - 14) / 14 for column in range(56)]
                for row in range(3)
            ]
        )[None, :, :]
        choice = policy.act_choice(
            observation,
            descriptors,
            np.asarray([[True, False, True]]),
            deterministic=True,
        )
        self.assertEqual(
            choice.selected_options[0], int(values["choice_action"])
        )
        np.testing.assert_allclose(
            choice.probabilities[0],
            np.fromstring(values["choice_probabilities"], sep=","),
            rtol=2e-10,
            atol=2e-12,
        )
        self.assertAlmostEqual(
            choice.values[0], float(values["choice_value"]), places=10
        )
        self.assertAlmostEqual(
            choice.log_probabilities[0],
            float(values["choice_log_probability"]),
            places=10,
        )

    def test_phase3_contract_fixture_stays_green(self) -> None:
        values = self._run_lua(LUA_PHASE3)
        self.assertEqual(values["observation_count"], "1279")
        self.assertEqual(values["finite"], "true")
        self.assertEqual(values["trajectory_v3"], "true")
        self.assertEqual(values["permanent_potion_masks"], "true")

    def _run_lua(self, script: Path) -> dict[str, str]:
        lua = shutil.which("lua")
        if lua is None:
            self.skipTest("Lua is unavailable")
        completed = subprocess.run(
            [lua, str(script), str(ROOT)],
            check=False,
            capture_output=True,
            text=True,
            timeout=180.0,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return dict(
            line.split("=", 1)
            for line in completed.stdout.splitlines()
            if "=" in line
        )


if __name__ == "__main__":
    unittest.main()
