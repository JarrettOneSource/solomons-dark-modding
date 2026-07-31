#!/usr/bin/env python3
"""Deterministic contract tests for the policy-v3 live verifier controls."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from ml_bot import spec  # noqa: E402
from ml_bot.model import BotPolicy  # noqa: E402
import verify_ml_bot_live as live  # noqa: E402


class MlBotV3LiveVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = BotPolicy.initialize(np.random.default_rng(20260731))
        self.observation = np.zeros((1, len(spec.OBSERVATION_NAMES)))
        self.movement_mask = np.ones(
            (1, len(spec.MOVEMENT_ACTION_NAMES)), dtype=np.bool_
        )
        self.target_mask = np.ones(
            (1, len(spec.TARGET_ACTION_NAMES)), dtype=np.bool_
        )
        self.ability_mask = np.ones(
            (1, len(spec.ABILITY_ACTION_NAMES)), dtype=np.bool_
        )
        self.aim_mask = np.ones(
            (1, len(spec.AIM_ACTION_NAMES)), dtype=np.bool_
        )

    def _act(self, policy: BotPolicy):
        return policy.act(
            self.observation,
            self.movement_mask,
            self.target_mask,
            self.ability_mask,
            self.aim_mask,
            deterministic=True,
        )

    def test_forced_policy_controls_all_four_heads(self) -> None:
        controlled = live._forced_policy(
            self.policy,
            movement_action=6,
            target_action=4,
            ability_action=17,
            aim_action=8,
        )
        action = self._act(controlled)
        self.assertEqual(action.movement_actions.tolist(), [6])
        self.assertEqual(action.target_actions.tolist(), [4])
        self.assertEqual(action.ability_actions.tolist(), [17])
        self.assertEqual(action.aim_actions.tolist(), [8])

    def test_weld_choice_policy_scores_weld_above_primary(self) -> None:
        controlled = live._learned_weld_policy(self.policy)
        descriptors = np.zeros(
            (1, 3, len(spec.OPTION_DESCRIPTOR_NAMES)), dtype=np.float64
        )
        descriptors[0, 0, spec.OPTION_DESCRIPTOR_NAMES.index("is_primary")] = 1
        descriptors[0, 1, spec.OPTION_DESCRIPTOR_NAMES.index("is_weld")] = 1
        choice = controlled.act_choice(
            self.observation,
            descriptors,
            np.asarray([[True, True, True]]),
            deterministic=True,
        )
        self.assertEqual(choice.selected_options.tolist(), [1])
        self.assertGreater(
            choice.probabilities[0, 1], choice.probabilities[0, 0]
        )

    def test_hazard_and_obstacle_controls_are_feature_conditional(self) -> None:
        obstacle = live._obstacle_reactive_policy(self.policy, 3)
        self.assertEqual(self._act(obstacle).movement_actions.tolist(), [0])
        self.observation[
            0, spec.OBSERVATION_NAMES.index("obstacle_1_present")
        ] = 1.0
        self.assertEqual(self._act(obstacle).movement_actions.tolist(), [3])
        self.observation.fill(0.0)

        hazard = live._hazard_reactive_policy(self.policy, 3)
        self.assertEqual(self._act(hazard).movement_actions.tolist(), [0])
        for suffix in ("present", "type_known", "kind_projectile"):
            self.observation[
                0,
                spec.OBSERVATION_NAMES.index(f"hazard_7_{suffix}"),
            ] = 1.0
        self.assertEqual(self._act(hazard).movement_actions.tolist(), [3])
        self.observation[
            0, spec.OBSERVATION_NAMES.index("hazard_7_type_known")
        ] = 0.0
        self.assertEqual(self._act(hazard).movement_actions.tolist(), [0])

    def test_velocity_to_aim_action_uses_nearest_direction(self) -> None:
        self.assertEqual(live._aim_action_for_velocity(5.0, 0.1), 1)
        self.assertEqual(live._aim_action_for_velocity(-3.0, 4.0), 4)
        self.assertEqual(live._aim_action_for_velocity(0.0, -2.0), 7)
        with self.assertRaisesRegex(Exception, "too small"):
            live._aim_action_for_velocity(0.0, 0.0)

    def test_velocity_lead_policy_reads_target_motion(self) -> None:
        controlled = live._velocity_lead_policy(self.policy)
        self.assertEqual(self._act(controlled).aim_actions.tolist(), [0])
        velocity_x = spec.OBSERVATION_NAMES.index("target_velocity_dx")
        velocity_y = spec.OBSERVATION_NAMES.index("target_velocity_dy")
        self.observation[0, velocity_x] = 0.01
        self.assertEqual(self._act(controlled).aim_actions.tolist(), [1])
        self.observation[0, velocity_x] = -0.01
        self.observation[0, velocity_y] = -0.01
        self.assertEqual(self._act(controlled).aim_actions.tolist(), [6])

    def test_potion_rows_are_ranked_by_slot_and_keep_legality(self) -> None:
        rows = live._potion_slots(
            {
                "potion_rows": (
                    "1:5:2:true,2:0:7:false,4:3:1:false"
                )
            }
        )
        self.assertEqual(
            rows,
            {5: (1, 2, True), 0: (2, 7, False), 3: (4, 1, False)},
        )
        with self.assertRaisesRegex(Exception, "invalid potion row"):
            live._potion_slots({"potion_rows": "1:5:2"})

    def test_contract_validator_requires_exact_v3_shape_and_masks(self) -> None:
        values = {
            "observation_version": "3",
            "observation_count": str(len(spec.OBSERVATION_NAMES)),
            "observation_finite": "true",
            "observation": ",".join(
                "0" for _ in spec.OBSERVATION_NAMES
            ),
            "movement_mask": "1" * len(spec.MOVEMENT_ACTION_NAMES),
            "target_mask": "1" * len(spec.TARGET_ACTION_NAMES),
            "ability_mask": "1" * len(spec.ABILITY_ACTION_NAMES),
            "aim_mask": "1" * len(spec.AIM_ACTION_NAMES),
            "selected_actions_legal": "true",
            "movement_mask_mismatches": "0",
            "target_mask_mismatches": "0",
            "ability_mask_mismatches": "0",
            "aim_mask_mismatches": "0",
        }
        observation = live._validate_contract(values)
        self.assertEqual(len(observation), 1279)
        broken = dict(values, ability_mask="1" * 21)
        with self.assertRaisesRegex(Exception, "invalid live ability_mask"):
            live._validate_contract(broken)


if __name__ == "__main__":
    unittest.main()
