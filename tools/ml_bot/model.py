"""Auditable NumPy implementation of the strict ML bot policy-v4 model."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from . import spec

Array = np.ndarray


def _as_float64(value: Any) -> Array:
    return np.asarray(value, dtype=np.float64)


def _as_bool(value: Any) -> Array:
    return np.asarray(value, dtype=np.bool_)


def _require_shape(name: str, value: Array, shape: tuple[int, ...]) -> None:
    if value.shape != shape:
        raise ValueError(f"{name} has shape {value.shape}, expected {shape}")
    if not np.all(np.isfinite(value)):
        raise ValueError(f"{name} contains a non-finite value")


def _validate_mask(name: str, mask: Array, rows: int, columns: int) -> Array:
    normalized = _as_bool(mask)
    _require_shape(name, normalized, (rows, columns))
    if not np.all(np.any(normalized, axis=1)):
        raise ValueError(f"{name} contains a row with no legal action")
    return normalized


def masked_softmax(
    logits: Array,
    mask: Array,
    *,
    temperature: float = 1.0,
) -> Array:
    logits = _as_float64(logits)
    if logits.ndim != 2:
        raise ValueError("logits must be a rank-2 array")
    if not math.isfinite(temperature) or temperature <= 0.0:
        raise ValueError("softmax temperature must be positive and finite")
    mask = _validate_mask("mask", mask, *logits.shape)
    tempered = logits / temperature
    masked = np.where(mask, tempered, -np.inf)
    maximum = np.max(masked, axis=1, keepdims=True)
    exponentials = np.where(mask, np.exp(masked - maximum), 0.0)
    return exponentials / np.sum(exponentials, axis=1, keepdims=True)


def selected_log_probabilities(probabilities: Array, actions: Array) -> Array:
    probabilities = _as_float64(probabilities)
    actions = np.asarray(actions, dtype=np.int64)
    if probabilities.ndim != 2 or actions.shape != (probabilities.shape[0],):
        raise ValueError("probabilities/actions batch shape mismatch")
    if np.any(actions < 0) or np.any(actions >= probabilities.shape[1]):
        raise ValueError("action index is outside the policy head")
    selected = probabilities[np.arange(probabilities.shape[0]), actions]
    if np.any(selected <= 0.0):
        raise ValueError("selected action is masked or has zero probability")
    return np.log(selected)


def sample_categorical(probabilities: Array, rng: np.random.Generator) -> Array:
    probabilities = _as_float64(probabilities)
    thresholds = rng.random(probabilities.shape[0])
    cumulative = np.cumsum(probabilities, axis=1)
    actions = np.sum(cumulative < thresholds[:, None], axis=1)
    return np.minimum(actions, probabilities.shape[1] - 1).astype(np.int64)


@dataclass(frozen=True)
class ForwardPass:
    observations: Array
    first_hidden: Array
    second_hidden: Array
    movement_probabilities: Array
    target_probabilities: Array
    ability_probabilities: Array
    aim_probabilities: Array
    values: Array


@dataclass(frozen=True)
class ChoiceForwardPass:
    observations: Array
    first_hidden: Array
    second_hidden: Array
    option_descriptors: Array
    option_hidden: Array
    raw_scores: Array
    probabilities: Array
    values: Array
    temperature: float


@dataclass(frozen=True)
class ActionBatch:
    movement_actions: Array
    target_actions: Array
    ability_actions: Array
    aim_actions: Array
    log_probabilities: Array
    values: Array
    movement_probabilities: Array
    target_probabilities: Array
    ability_probabilities: Array
    aim_probabilities: Array


@dataclass(frozen=True)
class ChoiceActionBatch:
    selected_options: Array
    log_probabilities: Array
    values: Array
    probabilities: Array
    temperature: float


@dataclass(frozen=True)
class PpoMetrics:
    policy_loss: float
    value_loss: float
    entropy: float
    movement_entropy: float
    target_entropy: float
    ability_entropy: float
    aim_entropy: float
    approximate_kl: float
    clip_fraction: float
    gradient_norm: float


@dataclass(frozen=True)
class ChoicePpoMetrics:
    policy_loss: float
    value_loss: float
    normalized_entropy: float
    raw_entropy: float
    approximate_kl: float
    clip_fraction: float
    gradient_norm: float
    temperature: float


@dataclass
class ChoiceCoverage:
    """Selection coverage that controls the frozen 1.25 -> 1.0 schedule."""

    selection_counts: dict[str, int] = field(default_factory=dict)
    offered_keys: set[str] = field(default_factory=set)

    @staticmethod
    def _keys(descriptor: Array) -> tuple[str, ...]:
        descriptor = _as_float64(descriptor)
        _require_shape(
            "choice coverage descriptor",
            descriptor,
            (len(spec.OPTION_DESCRIPTOR_NAMES),),
        )
        family_keys = [
            f"family:{name.removeprefix('family_')}"
            for index, name in enumerate(spec.OPTION_DESCRIPTOR_NAMES)
            if name.startswith("family_") and descriptor[index] > 0.5
        ]
        if not family_keys:
            family_keys.append("family:unknown")
        if descriptor[spec.OPTION_DESCRIPTOR_NAMES.index("is_weld")] > 0.5:
            elements = tuple(
                int(descriptor[spec.OPTION_DESCRIPTOR_NAMES.index(name)] > 0.5)
                for name in (
                    "weld_element_ether",
                    "weld_element_fire",
                    "weld_element_air",
                    "weld_element_water",
                    "weld_element_earth",
                )
            )
            build = descriptor[
                spec.OPTION_DESCRIPTOR_NAMES.index(
                    "weld_build_index_scaled"
                )
            ]
            family_keys.append(
                "weld:" + "".join(str(value) for value in elements)
                + f":{build:.9g}"
            )
        return tuple(sorted(set(family_keys)))

    def observe(
        self,
        option_descriptors: Array,
        option_mask: Array,
        selected_option: int,
    ) -> None:
        descriptors = _as_float64(option_descriptors)
        if descriptors.ndim != 2 or descriptors.shape[1] != len(
            spec.OPTION_DESCRIPTOR_NAMES
        ):
            raise ValueError("choice coverage descriptors have wrong shape")
        mask = _as_bool(option_mask)
        _require_shape(
            "choice coverage mask", mask, (descriptors.shape[0],)
        )
        if not np.any(mask):
            raise ValueError("choice coverage mask has no valid option")
        if not 0 <= selected_option < descriptors.shape[0] or not mask[
            selected_option
        ]:
            raise ValueError("selected choice option is not valid")
        for option_index in np.flatnonzero(mask):
            self.offered_keys.update(self._keys(descriptors[option_index]))
        for key in self._keys(descriptors[selected_option]):
            self.selection_counts[key] = self.selection_counts.get(key, 0) + 1

    @property
    def complete(self) -> bool:
        return bool(self.offered_keys) and all(
            self.selection_counts.get(key, 0)
            >= spec.CHOICE_COVERAGE_THRESHOLD
            for key in self.offered_keys
        )

    @property
    def temperature(self) -> float:
        if self.complete:
            return spec.CHOICE_FINAL_TEMPERATURE
        return spec.CHOICE_EXPLORATION_TEMPERATURE

    def to_dict(self) -> dict[str, object]:
        return {
            "offered_keys": sorted(self.offered_keys),
            "selection_counts": {
                key: self.selection_counts[key]
                for key in sorted(self.selection_counts)
            },
            "complete": self.complete,
            "temperature": self.temperature,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ChoiceCoverage":
        offered = value.get("offered_keys", [])
        counts = value.get("selection_counts", {})
        if not isinstance(offered, list) or not all(
            isinstance(key, str) for key in offered
        ):
            raise ValueError("choice coverage offered_keys must be strings")
        if not isinstance(counts, Mapping):
            raise ValueError("choice coverage selection_counts must be an object")
        normalized_counts: dict[str, int] = {}
        for key, count in counts.items():
            if not isinstance(key, str) or not isinstance(count, int) or count < 0:
                raise ValueError("choice coverage counts must be non-negative integers")
            normalized_counts[key] = count
        return cls(normalized_counts, set(offered))


class Adam:
    """Minimal Adam optimizer over a named dictionary of arrays."""

    def __init__(
        self,
        parameters: Mapping[str, Array],
        *,
        learning_rate: float,
        beta1: float = 0.9,
        beta2: float = 0.999,
        epsilon: float = 1e-8,
    ) -> None:
        if learning_rate <= 0.0:
            raise ValueError("learning_rate must be positive")
        self.learning_rate = float(learning_rate)
        self.beta1 = float(beta1)
        self.beta2 = float(beta2)
        self.epsilon = float(epsilon)
        self.step_count = 0
        self.first = {
            name: np.zeros_like(parameter)
            for name, parameter in parameters.items()
        }
        self.second = {
            name: np.zeros_like(parameter)
            for name, parameter in parameters.items()
        }

    def step(
        self,
        parameters: Mapping[str, Array],
        gradients: Mapping[str, Array],
        *,
        maximum_gradient_norm: float | None = None,
    ) -> float:
        missing = set(parameters) ^ set(gradients)
        if missing:
            raise ValueError(
                f"optimizer parameter/gradient keys differ: {sorted(missing)}"
            )
        squared_norm = sum(
            float(np.sum(np.square(gradient)))
            for gradient in gradients.values()
        )
        gradient_norm = math.sqrt(squared_norm)
        scale = 1.0
        if (
            maximum_gradient_norm is not None
            and maximum_gradient_norm > 0.0
            and gradient_norm > maximum_gradient_norm
        ):
            scale = maximum_gradient_norm / gradient_norm

        self.step_count += 1
        beta1_correction = 1.0 - self.beta1**self.step_count
        beta2_correction = 1.0 - self.beta2**self.step_count
        for name, parameter in parameters.items():
            gradient = gradients[name] * scale
            if not np.all(np.isfinite(gradient)):
                raise FloatingPointError(
                    f"non-finite gradient for parameter {name}"
                )
            self.first[name] = (
                self.beta1 * self.first[name]
                + (1.0 - self.beta1) * gradient
            )
            self.second[name] = (
                self.beta2 * self.second[name]
                + (1.0 - self.beta2) * np.square(gradient)
            )
            first_hat = self.first[name] / beta1_correction
            second_hat = self.second[name] / beta2_correction
            parameter -= (
                self.learning_rate
                * first_hat
                / (np.sqrt(second_hat) + self.epsilon)
            )
        return gradient_norm


class BotPolicy:
    def __init__(
        self,
        *,
        input_weight: Array,
        input_bias: Array,
        hidden_weight: Array,
        hidden_bias: Array,
        movement_weight: Array,
        movement_bias: Array,
        target_weight: Array,
        target_bias: Array,
        ability_weight: Array,
        ability_bias: Array,
        aim_weight: Array,
        aim_bias: Array,
        value_weight: Array,
        value_bias: Array,
        choice_option_weight: Array,
        choice_option_bias: Array,
        choice_score_weight: Array,
        choice_score_bias: Array,
        choice_value_weight: Array,
        choice_value_bias: Array,
        choice_temperature: float = spec.CHOICE_EXPLORATION_TEMPERATURE,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        for name, value in locals().copy().items():
            if name not in {"self", "metadata", "choice_temperature"}:
                setattr(self, name, _as_float64(value).copy())
        self.choice_temperature = float(choice_temperature)
        self.metadata = dict(metadata or {})
        self.validate()

    @classmethod
    def initialize(
        cls,
        rng: np.random.Generator,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> "BotPolicy":
        observation_size = len(spec.OBSERVATION_NAMES)
        first_hidden_size, second_hidden_size = spec.HIDDEN_SIZES
        movement_size = len(spec.MOVEMENT_ACTION_NAMES)
        target_size = len(spec.TARGET_ACTION_NAMES)
        ability_size = len(spec.ABILITY_ACTION_NAMES)
        aim_size = len(spec.AIM_ACTION_NAMES)
        descriptor_size = len(spec.OPTION_DESCRIPTOR_NAMES)
        choice_hidden_size = spec.CHOICE_HIDDEN_SIZE

        def xavier(rows: int, columns: int) -> Array:
            limit = math.sqrt(6.0 / (rows + columns))
            return rng.uniform(-limit, limit, size=(rows, columns))

        value_limit = math.sqrt(6.0 / (second_hidden_size + 1))
        return cls(
            input_weight=xavier(first_hidden_size, observation_size),
            input_bias=np.zeros(first_hidden_size),
            hidden_weight=xavier(second_hidden_size, first_hidden_size),
            hidden_bias=np.zeros(second_hidden_size),
            movement_weight=xavier(movement_size, second_hidden_size),
            movement_bias=np.zeros(movement_size),
            target_weight=xavier(target_size, second_hidden_size),
            target_bias=np.zeros(target_size),
            ability_weight=xavier(ability_size, second_hidden_size),
            ability_bias=np.zeros(ability_size),
            aim_weight=xavier(aim_size, second_hidden_size),
            aim_bias=np.zeros(aim_size),
            value_weight=rng.uniform(
                -value_limit, value_limit, size=second_hidden_size
            ),
            value_bias=np.zeros(1),
            choice_option_weight=xavier(
                choice_hidden_size, second_hidden_size + descriptor_size
            ),
            choice_option_bias=np.zeros(choice_hidden_size),
            choice_score_weight=xavier(1, choice_hidden_size)[0],
            choice_score_bias=np.zeros(1),
            choice_value_weight=rng.uniform(
                -value_limit, value_limit, size=second_hidden_size
            ),
            choice_value_bias=np.zeros(1),
            metadata=metadata,
        )

    def parameter_arrays(self) -> dict[str, Array]:
        return {
            name: getattr(self, name)
            for name in (
                "input_weight",
                "input_bias",
                "hidden_weight",
                "hidden_bias",
                "movement_weight",
                "movement_bias",
                "target_weight",
                "target_bias",
                "ability_weight",
                "ability_bias",
                "aim_weight",
                "aim_bias",
                "value_weight",
                "value_bias",
                "choice_option_weight",
                "choice_option_bias",
                "choice_score_weight",
                "choice_score_bias",
                "choice_value_weight",
                "choice_value_bias",
            )
        }

    def validate(self) -> None:
        observation_size = len(spec.OBSERVATION_NAMES)
        first_hidden_size, second_hidden_size = spec.HIDDEN_SIZES
        descriptor_size = len(spec.OPTION_DESCRIPTOR_NAMES)
        expected = {
            "input_weight": (first_hidden_size, observation_size),
            "input_bias": (first_hidden_size,),
            "hidden_weight": (second_hidden_size, first_hidden_size),
            "hidden_bias": (second_hidden_size,),
            "movement_weight": (
                len(spec.MOVEMENT_ACTION_NAMES),
                second_hidden_size,
            ),
            "movement_bias": (len(spec.MOVEMENT_ACTION_NAMES),),
            "target_weight": (
                len(spec.TARGET_ACTION_NAMES),
                second_hidden_size,
            ),
            "target_bias": (len(spec.TARGET_ACTION_NAMES),),
            "ability_weight": (
                len(spec.ABILITY_ACTION_NAMES),
                second_hidden_size,
            ),
            "ability_bias": (len(spec.ABILITY_ACTION_NAMES),),
            "aim_weight": (len(spec.AIM_ACTION_NAMES), second_hidden_size),
            "aim_bias": (len(spec.AIM_ACTION_NAMES),),
            "value_weight": (second_hidden_size,),
            "value_bias": (1,),
            "choice_option_weight": (
                spec.CHOICE_HIDDEN_SIZE,
                second_hidden_size + descriptor_size,
            ),
            "choice_option_bias": (spec.CHOICE_HIDDEN_SIZE,),
            "choice_score_weight": (spec.CHOICE_HIDDEN_SIZE,),
            "choice_score_bias": (1,),
            "choice_value_weight": (second_hidden_size,),
            "choice_value_bias": (1,),
        }
        for name, parameter in self.parameter_arrays().items():
            _require_shape(name, parameter, expected[name])
        if self.choice_temperature not in (
            spec.CHOICE_EXPLORATION_TEMPERATURE,
            spec.CHOICE_FINAL_TEMPERATURE,
        ):
            raise ValueError(
                "choice_temperature must be the exploration or final "
                "policy-v4 schedule value"
            )

    def set_choice_temperature(self, temperature: float) -> None:
        self.choice_temperature = float(temperature)
        self.validate()

    def _encode(self, observations: Array) -> tuple[Array, Array, Array]:
        observations = _as_float64(observations)
        if observations.ndim == 1:
            observations = observations[None, :]
        rows = observations.shape[0]
        _require_shape(
            "observations", observations, (rows, len(spec.OBSERVATION_NAMES))
        )
        first_hidden = np.tanh(
            observations @ self.input_weight.T + self.input_bias
        )
        second_hidden = np.tanh(
            first_hidden @ self.hidden_weight.T + self.hidden_bias
        )
        return observations, first_hidden, second_hidden

    def forward(
        self,
        observations: Array,
        movement_masks: Array,
        target_masks: Array,
        ability_masks: Array,
        aim_masks: Array,
    ) -> ForwardPass:
        observations, first_hidden, second_hidden = self._encode(observations)
        rows = observations.shape[0]
        movement_masks = _validate_mask(
            "movement_masks", movement_masks, rows, len(spec.MOVEMENT_ACTION_NAMES)
        )
        target_masks = _validate_mask(
            "target_masks", target_masks, rows, len(spec.TARGET_ACTION_NAMES)
        )
        ability_masks = _validate_mask(
            "ability_masks", ability_masks, rows, len(spec.ABILITY_ACTION_NAMES)
        )
        aim_masks = _validate_mask(
            "aim_masks", aim_masks, rows, len(spec.AIM_ACTION_NAMES)
        )
        return ForwardPass(
            observations=observations,
            first_hidden=first_hidden,
            second_hidden=second_hidden,
            movement_probabilities=masked_softmax(
                second_hidden @ self.movement_weight.T + self.movement_bias,
                movement_masks,
            ),
            target_probabilities=masked_softmax(
                second_hidden @ self.target_weight.T + self.target_bias,
                target_masks,
            ),
            ability_probabilities=masked_softmax(
                second_hidden @ self.ability_weight.T + self.ability_bias,
                ability_masks,
            ),
            aim_probabilities=masked_softmax(
                second_hidden @ self.aim_weight.T + self.aim_bias,
                aim_masks,
            ),
            values=second_hidden @ self.value_weight + self.value_bias[0],
        )

    def forward_choice(
        self,
        observations: Array,
        option_descriptors: Array,
        option_masks: Array,
    ) -> ChoiceForwardPass:
        observations, first_hidden, second_hidden = self._encode(observations)
        descriptors = _as_float64(option_descriptors)
        rows = observations.shape[0]
        if descriptors.ndim != 3:
            raise ValueError("option_descriptors must be a rank-3 array")
        option_count = descriptors.shape[1]
        _require_shape(
            "option_descriptors",
            descriptors,
            (rows, option_count, len(spec.OPTION_DESCRIPTOR_NAMES)),
        )
        if option_count <= 0 or option_count > spec.MAX_CHOICE_OPTIONS:
            raise ValueError(
                "choice option count must be in [1, "
                f"{spec.MAX_CHOICE_OPTIONS}]"
            )
        option_masks = _validate_mask(
            "option_masks", option_masks, rows, option_count
        )
        state = np.broadcast_to(
            second_hidden[:, None, :],
            (rows, option_count, second_hidden.shape[1]),
        )
        joined = np.concatenate((state, descriptors), axis=2)
        option_hidden = np.tanh(
            joined @ self.choice_option_weight.T + self.choice_option_bias
        )
        raw_scores = (
            option_hidden @ self.choice_score_weight + self.choice_score_bias[0]
        )
        probabilities = masked_softmax(
            raw_scores,
            option_masks,
            temperature=self.choice_temperature,
        )
        return ChoiceForwardPass(
            observations=observations,
            first_hidden=first_hidden,
            second_hidden=second_hidden,
            option_descriptors=descriptors,
            option_hidden=option_hidden,
            raw_scores=raw_scores,
            probabilities=probabilities,
            values=(
                second_hidden @ self.choice_value_weight
                + self.choice_value_bias[0]
            ),
            temperature=self.choice_temperature,
        )

    def act(
        self,
        observations: Array,
        movement_masks: Array,
        target_masks: Array,
        ability_masks: Array,
        aim_masks: Array,
        *,
        deterministic: bool,
        rng: np.random.Generator | None = None,
    ) -> ActionBatch:
        forward = self.forward(
            observations,
            movement_masks,
            target_masks,
            ability_masks,
            aim_masks,
        )

        def choose(probabilities: Array) -> Array:
            if deterministic:
                return np.argmax(probabilities, axis=1)
            if rng is None:
                raise ValueError("stochastic action selection requires rng")
            return sample_categorical(probabilities, rng)

        movement_actions = choose(forward.movement_probabilities)
        target_actions = choose(forward.target_probabilities)
        ability_actions = choose(forward.ability_probabilities)
        aim_actions = choose(forward.aim_probabilities)
        log_probabilities = sum(
            selected_log_probabilities(probabilities, actions)
            for probabilities, actions in (
                (forward.movement_probabilities, movement_actions),
                (forward.target_probabilities, target_actions),
                (forward.ability_probabilities, ability_actions),
                (forward.aim_probabilities, aim_actions),
            )
        )
        return ActionBatch(
            movement_actions=movement_actions,
            target_actions=target_actions,
            ability_actions=ability_actions,
            aim_actions=aim_actions,
            log_probabilities=log_probabilities,
            values=forward.values.copy(),
            movement_probabilities=forward.movement_probabilities,
            target_probabilities=forward.target_probabilities,
            ability_probabilities=forward.ability_probabilities,
            aim_probabilities=forward.aim_probabilities,
        )

    def act_choice(
        self,
        observations: Array,
        option_descriptors: Array,
        option_masks: Array,
        *,
        deterministic: bool,
        rng: np.random.Generator | None = None,
    ) -> ChoiceActionBatch:
        forward = self.forward_choice(
            observations, option_descriptors, option_masks
        )
        if deterministic:
            selected = np.argmax(forward.probabilities, axis=1)
        else:
            if rng is None:
                raise ValueError("stochastic choice selection requires rng")
            selected = sample_categorical(forward.probabilities, rng)
        return ChoiceActionBatch(
            selected_options=selected,
            log_probabilities=selected_log_probabilities(
                forward.probabilities, selected
            ),
            values=forward.values.copy(),
            probabilities=forward.probabilities,
            temperature=forward.temperature,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **spec.contract_metadata(),
            "choice_temperature": self.choice_temperature,
            "metadata": {
                key: self.metadata[key] for key in sorted(self.metadata)
            },
            "parameters": {
                name: parameter.tolist()
                for name, parameter in self.parameter_arrays().items()
            },
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BotPolicy":
        model = dict(value)
        spec.validate_model_contract(model)
        parameters = model.get("parameters")
        if not isinstance(parameters, Mapping):
            raise ValueError("policy-v4 model parameters must be an object")
        required = {
            "input_weight",
            "input_bias",
            "hidden_weight",
            "hidden_bias",
            "movement_weight",
            "movement_bias",
            "target_weight",
            "target_bias",
            "ability_weight",
            "ability_bias",
            "aim_weight",
            "aim_bias",
            "value_weight",
            "value_bias",
            "choice_option_weight",
            "choice_option_bias",
            "choice_score_weight",
            "choice_score_bias",
            "choice_value_weight",
            "choice_value_bias",
        }
        if set(parameters) != required:
            raise ValueError(
                "model parameter names do not match the strict policy-v4 contract"
            )
        metadata = model.get("metadata")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise ValueError("model metadata must be an object")
        temperature = model.get("choice_temperature")
        if not isinstance(temperature, (int, float)):
            raise ValueError("policy-v4 choice_temperature must be numeric")
        return cls(
            **{name: _as_float64(parameters[name]) for name in sorted(required)},
            choice_temperature=float(temperature),
            metadata=metadata,
        )


def save_model(policy: BotPolicy, path: Path) -> None:
    policy.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(policy.to_dict(), indent=2, sort_keys=True) + "\n")


def load_model(path: Path) -> BotPolicy:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("model root must be an object")
    return BotPolicy.from_dict(value)


def _lua_number(value: float) -> str:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("cannot export a non-finite Lua number")
    text = format(value, ".17g")
    return "0" if text == "-0" else text


def _lua_value(value: Any, indent: int = 0) -> str:
    prefix = " " * indent
    child_prefix = " " * (indent + 2)
    if isinstance(value, Mapping):
        lines = ["{"]
        for key, item in value.items():
            lines.append(
                f"{child_prefix}[{json.dumps(str(key))}] = "
                f"{_lua_value(item, indent + 2)},"
            )
        lines.append(f"{prefix}}}")
        return "\n".join(lines)
    if isinstance(value, (list, tuple, np.ndarray)):
        items = list(value)
        if not items:
            return "{}"
        if all(
            isinstance(item, (int, float, np.integer, np.floating))
            for item in items
        ):
            return "{ " + ", ".join(_lua_number(item) for item in items) + " }"
        lines = ["{"]
        for item in items:
            lines.append(f"{child_prefix}{_lua_value(item, indent + 2)},")
        lines.append(f"{prefix}}}")
        return "\n".join(lines)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, np.integer, np.floating)):
        return _lua_number(value)
    raise TypeError(f"unsupported Lua export value {type(value).__name__}")


def render_lua_weights(policy: BotPolicy) -> str:
    policy.validate()
    return (
        "-- Generated by tools/train_bot_policy.py. Do not edit.\nreturn "
        + _lua_value(policy.to_dict())
        + "\n"
    )


def export_lua_weights(policy: BotPolicy, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(render_lua_weights(policy))


def _zero_gradients(policy: BotPolicy) -> dict[str, Array]:
    return {
        name: np.zeros_like(parameter)
        for name, parameter in policy.parameter_arrays().items()
    }


def _head_classification_delta(probabilities: Array, actions: Array) -> Array:
    rows = probabilities.shape[0]
    delta = probabilities.copy()
    delta[np.arange(rows), actions] -= 1.0
    return delta / rows


def _backpropagate_hidden(
    policy: BotPolicy,
    observations: Array,
    first_hidden: Array,
    second_hidden: Array,
    second_hidden_delta: Array,
    gradients: dict[str, Array],
) -> None:
    second_preactivation_delta = second_hidden_delta * (
        1.0 - np.square(second_hidden)
    )
    gradients["hidden_weight"] = second_preactivation_delta.T @ first_hidden
    gradients["hidden_bias"] = np.sum(second_preactivation_delta, axis=0)
    first_hidden_delta = second_preactivation_delta @ policy.hidden_weight
    first_preactivation_delta = first_hidden_delta * (
        1.0 - np.square(first_hidden)
    )
    gradients["input_weight"] = first_preactivation_delta.T @ observations
    gradients["input_bias"] = np.sum(first_preactivation_delta, axis=0)


def behavior_clone_batch(
    policy: BotPolicy,
    optimizer: Adam,
    observations: Array,
    movement_masks: Array,
    target_masks: Array,
    ability_masks: Array,
    aim_masks: Array,
    movement_actions: Array,
    target_actions: Array,
    ability_actions: Array,
    aim_actions: Array,
    *,
    maximum_gradient_norm: float = 1.0,
) -> tuple[float, float]:
    observations = _as_float64(observations)
    rows = observations.shape[0]
    actions = tuple(
        np.asarray(value, dtype=np.int64)
        for value in (
            movement_actions,
            target_actions,
            ability_actions,
            aim_actions,
        )
    )
    for name, value in zip(
        ("movement", "target", "ability", "aim"), actions, strict=True
    ):
        if value.shape != (rows,):
            raise ValueError(f"behavior-cloning {name} actions have wrong shape")

    forward = policy.forward(
        observations, movement_masks, target_masks, ability_masks, aim_masks
    )
    probabilities = (
        forward.movement_probabilities,
        forward.target_probabilities,
        forward.ability_probabilities,
        forward.aim_probabilities,
    )
    loss = -float(
        np.mean(
            sum(
                selected_log_probabilities(head, action)
                for head, action in zip(probabilities, actions, strict=True)
            )
        )
    )
    deltas = tuple(
        _head_classification_delta(head, action)
        for head, action in zip(probabilities, actions, strict=True)
    )
    gradients = _zero_gradients(policy)
    second_hidden_delta = np.zeros_like(forward.second_hidden)
    for name, delta, weight in zip(
        ("movement", "target", "ability", "aim"),
        deltas,
        (
            policy.movement_weight,
            policy.target_weight,
            policy.ability_weight,
            policy.aim_weight,
        ),
        strict=True,
    ):
        gradients[f"{name}_weight"] = delta.T @ forward.second_hidden
        gradients[f"{name}_bias"] = np.sum(delta, axis=0)
        second_hidden_delta += delta @ weight
    _backpropagate_hidden(
        policy,
        forward.observations,
        forward.first_hidden,
        forward.second_hidden,
        second_hidden_delta,
        gradients,
    )
    gradient_norm = optimizer.step(
        policy.parameter_arrays(),
        gradients,
        maximum_gradient_norm=maximum_gradient_norm,
    )
    policy.validate()
    return loss, gradient_norm


def classification_accuracy(
    policy: BotPolicy,
    observations: Array,
    movement_masks: Array,
    target_masks: Array,
    ability_masks: Array,
    aim_masks: Array,
    movement_actions: Array,
    target_actions: Array,
    ability_actions: Array,
    aim_actions: Array,
) -> tuple[float, float, float, float, float]:
    predicted = policy.act(
        observations,
        movement_masks,
        target_masks,
        ability_masks,
        aim_masks,
        deterministic=True,
    )
    expected = tuple(
        np.asarray(value, dtype=np.int64)
        for value in (
            movement_actions,
            target_actions,
            ability_actions,
            aim_actions,
        )
    )
    correct = (
        predicted.movement_actions == expected[0],
        predicted.target_actions == expected[1],
        predicted.ability_actions == expected[2],
        predicted.aim_actions == expected[3],
    )
    return (*[float(np.mean(value)) for value in correct], float(np.mean(np.logical_and.reduce(correct))))


def generalized_advantage_estimate(
    rewards: Array,
    values: Array,
    dones: Array,
    *,
    bootstrap_value: float = 0.0,
    gamma: float = 0.99,
    gae_lambda: float = 0.95,
) -> tuple[Array, Array]:
    rewards = _as_float64(rewards)
    values = _as_float64(values)
    dones = _as_bool(dones)
    if rewards.ndim != 1 or values.shape != rewards.shape:
        raise ValueError("rewards and values must be matching rank-1 arrays")
    if dones.shape != rewards.shape:
        raise ValueError("dones shape does not match rewards")
    if not 0.0 <= gamma <= 1.0 or not 0.0 <= gae_lambda <= 1.0:
        raise ValueError("gamma and gae_lambda must be in [0, 1]")
    advantages = np.zeros_like(rewards)
    next_value = float(bootstrap_value)
    next_advantage = 0.0
    for index in range(len(rewards) - 1, -1, -1):
        continuation = 0.0 if dones[index] else 1.0
        delta = rewards[index] + gamma * next_value * continuation - values[index]
        next_advantage = (
            delta + gamma * gae_lambda * continuation * next_advantage
        )
        advantages[index] = next_advantage
        next_value = values[index]
    return advantages, advantages + values


def smdp_advantage_estimate(
    reward_sequences: Sequence[Array],
    durations: Array,
    values: Array,
    next_values: Array,
    dones: Array,
    *,
    gamma: float = 0.99,
    gae_lambda: float = 0.95,
) -> tuple[Array, Array]:
    durations = np.asarray(durations, dtype=np.int64)
    values = _as_float64(values)
    next_values = _as_float64(next_values)
    dones = _as_bool(dones)
    count = len(reward_sequences)
    for name, array in (
        ("durations", durations),
        ("values", values),
        ("next_values", next_values),
        ("dones", dones),
    ):
        if array.shape != (count,):
            raise ValueError(f"choice {name} has wrong shape")
    if np.any(durations < 0):
        raise ValueError("choice durations must be non-negative")
    if not 0.0 <= gamma <= 1.0 or not 0.0 <= gae_lambda <= 1.0:
        raise ValueError("gamma and gae_lambda must be in [0, 1]")
    interval_returns = np.zeros(count, dtype=np.float64)
    for index, rewards in enumerate(reward_sequences):
        rewards = _as_float64(rewards)
        _require_shape(
            f"choice rewards {index}", rewards, (int(durations[index]),)
        )
        interval_returns[index] = sum(
            gamma**offset * float(reward)
            for offset, reward in enumerate(rewards)
        )
    advantages = np.zeros(count, dtype=np.float64)
    next_advantage = 0.0
    for index in range(count - 1, -1, -1):
        duration = int(durations[index])
        continuation = 0.0 if dones[index] else 1.0
        delta = (
            interval_returns[index]
            + gamma**duration * continuation * next_values[index]
            - values[index]
        )
        next_advantage = (
            delta
            + (gamma * gae_lambda) ** duration
            * continuation
            * next_advantage
        )
        advantages[index] = next_advantage
    return advantages, advantages + values


def _entropy_gradient(probabilities: Array) -> tuple[Array, Array]:
    safe_log = np.zeros_like(probabilities)
    positive = probabilities > 0.0
    safe_log[positive] = np.log(probabilities[positive])
    entropy = -np.sum(probabilities * safe_log, axis=1)
    gradient = -probabilities * (safe_log + entropy[:, None])
    return entropy, gradient


def _policy_head_delta(
    probabilities: Array,
    actions: Array,
    log_probability_delta: Array,
    entropy_coefficients: Array,
) -> tuple[Array, Array]:
    rows = probabilities.shape[0]
    delta = -probabilities.copy()
    delta[np.arange(rows), actions] += 1.0
    delta *= log_probability_delta[:, None]
    entropy, entropy_gradient = _entropy_gradient(probabilities)
    delta += -entropy_coefficients[:, None] * entropy_gradient / rows
    return delta, entropy


def _validate_ppo_vectors(rows: int, values: Mapping[str, Array]) -> None:
    for name, value in values.items():
        if value.shape != (rows,):
            raise ValueError(f"{name} has the wrong batch shape")


def ppo_batch(
    policy: BotPolicy,
    optimizer: Adam,
    observations: Array,
    movement_masks: Array,
    target_masks: Array,
    ability_masks: Array,
    aim_masks: Array,
    movement_actions: Array,
    target_actions: Array,
    ability_actions: Array,
    aim_actions: Array,
    old_log_probabilities: Array,
    advantages: Array,
    returns: Array,
    *,
    clip_ratio: float = 0.2,
    value_coefficient: float = 0.5,
    movement_entropy_coefficient: float = spec.MOVEMENT_ENTROPY_COEFFICIENT,
    target_entropy_coefficient: float = spec.TARGET_ENTROPY_COEFFICIENT,
    ability_entropy_coefficient: float = spec.ABILITY_ENTROPY_COEFFICIENT,
    aim_entropy_coefficient: float = spec.AIM_ENTROPY_COEFFICIENT,
    maximum_gradient_norm: float = 0.5,
) -> PpoMetrics:
    observations = _as_float64(observations)
    rows = observations.shape[0]
    actions = tuple(
        np.asarray(value, dtype=np.int64)
        for value in (
            movement_actions,
            target_actions,
            ability_actions,
            aim_actions,
        )
    )
    old_log_probabilities = _as_float64(old_log_probabilities)
    advantages = _as_float64(advantages)
    returns = _as_float64(returns)
    _validate_ppo_vectors(
        rows,
        {
            "movement_actions": actions[0],
            "target_actions": actions[1],
            "ability_actions": actions[2],
            "aim_actions": actions[3],
            "old_log_probabilities": old_log_probabilities,
            "advantages": advantages,
            "returns": returns,
        },
    )
    coefficients = (
        movement_entropy_coefficient,
        target_entropy_coefficient,
        ability_entropy_coefficient,
        aim_entropy_coefficient,
    )
    if clip_ratio <= 0.0 or any(
        not math.isfinite(value) or value < 0.0 for value in coefficients
    ):
        raise ValueError("PPO clip/entropy coefficients are invalid")
    forward = policy.forward(
        observations, movement_masks, target_masks, ability_masks, aim_masks
    )
    probabilities = (
        forward.movement_probabilities,
        forward.target_probabilities,
        forward.ability_probabilities,
        forward.aim_probabilities,
    )
    new_log_probabilities = sum(
        selected_log_probabilities(head, action)
        for head, action in zip(probabilities, actions, strict=True)
    )
    ratios = np.exp(new_log_probabilities - old_log_probabilities)
    clipped_ratios = np.clip(ratios, 1.0 - clip_ratio, 1.0 + clip_ratio)
    policy_loss = -float(
        np.mean(np.minimum(ratios * advantages, clipped_ratios * advantages))
    )
    active = (
        ((advantages >= 0.0) & (ratios <= 1.0 + clip_ratio))
        | ((advantages < 0.0) & (ratios >= 1.0 - clip_ratio))
    )
    log_probability_delta = np.where(
        active, -(advantages * ratios) / rows, 0.0
    )
    deltas: list[Array] = []
    entropies: list[Array] = []
    for head, action, coefficient in zip(
        probabilities, actions, coefficients, strict=True
    ):
        delta, entropy = _policy_head_delta(
            head,
            action,
            log_probability_delta,
            np.full(rows, coefficient),
        )
        deltas.append(delta)
        entropies.append(entropy)
    value_errors = forward.values - returns
    value_loss = float(np.mean(np.square(value_errors)))
    value_delta = 2.0 * value_coefficient * value_errors / rows
    gradients = _zero_gradients(policy)
    second_hidden_delta = value_delta[:, None] * policy.value_weight[None, :]
    for name, delta, weight in zip(
        ("movement", "target", "ability", "aim"),
        deltas,
        (
            policy.movement_weight,
            policy.target_weight,
            policy.ability_weight,
            policy.aim_weight,
        ),
        strict=True,
    ):
        gradients[f"{name}_weight"] = delta.T @ forward.second_hidden
        gradients[f"{name}_bias"] = np.sum(delta, axis=0)
        second_hidden_delta += delta @ weight
    gradients["value_weight"] = forward.second_hidden.T @ value_delta
    gradients["value_bias"] = np.asarray([np.sum(value_delta)])
    _backpropagate_hidden(
        policy,
        forward.observations,
        forward.first_hidden,
        forward.second_hidden,
        second_hidden_delta,
        gradients,
    )
    gradient_norm = optimizer.step(
        policy.parameter_arrays(),
        gradients,
        maximum_gradient_norm=maximum_gradient_norm,
    )
    policy.validate()
    entropy_means = [float(np.mean(value)) for value in entropies]
    return PpoMetrics(
        policy_loss=policy_loss,
        value_loss=value_loss,
        entropy=sum(entropy_means),
        movement_entropy=entropy_means[0],
        target_entropy=entropy_means[1],
        ability_entropy=entropy_means[2],
        aim_entropy=entropy_means[3],
        approximate_kl=float(
            np.mean(old_log_probabilities - new_log_probabilities)
        ),
        clip_fraction=float(np.mean(np.abs(ratios - 1.0) > clip_ratio)),
        gradient_norm=gradient_norm,
    )


def choice_ppo_batch(
    policy: BotPolicy,
    optimizer: Adam,
    observations: Array,
    option_descriptors: Array,
    option_masks: Array,
    selected_options: Array,
    old_log_probabilities: Array,
    advantages: Array,
    returns: Array,
    *,
    clip_ratio: float = 0.2,
    value_coefficient: float = 0.5,
    entropy_coefficient: float = spec.CHOICE_ENTROPY_COEFFICIENT,
    maximum_gradient_norm: float = 0.5,
) -> ChoicePpoMetrics:
    observations = _as_float64(observations)
    rows = observations.shape[0]
    selected_options = np.asarray(selected_options, dtype=np.int64)
    old_log_probabilities = _as_float64(old_log_probabilities)
    advantages = _as_float64(advantages)
    returns = _as_float64(returns)
    _validate_ppo_vectors(
        rows,
        {
            "selected_options": selected_options,
            "old_log_probabilities": old_log_probabilities,
            "advantages": advantages,
            "returns": returns,
        },
    )
    if clip_ratio <= 0.0 or not math.isfinite(entropy_coefficient) or entropy_coefficient < 0.0:
        raise ValueError("choice PPO clip/entropy coefficients are invalid")
    forward = policy.forward_choice(
        observations, option_descriptors, option_masks
    )
    masks = _as_bool(option_masks)
    new_log_probabilities = selected_log_probabilities(
        forward.probabilities, selected_options
    )
    ratios = np.exp(new_log_probabilities - old_log_probabilities)
    clipped_ratios = np.clip(ratios, 1.0 - clip_ratio, 1.0 + clip_ratio)
    policy_loss = -float(
        np.mean(np.minimum(ratios * advantages, clipped_ratios * advantages))
    )
    active = (
        ((advantages >= 0.0) & (ratios <= 1.0 + clip_ratio))
        | ((advantages < 0.0) & (ratios >= 1.0 - clip_ratio))
    )
    log_probability_delta = np.where(
        active, -(advantages * ratios) / rows, 0.0
    )
    valid_counts = np.sum(masks, axis=1)
    normalizers = np.where(valid_counts > 1, np.log(valid_counts), np.inf)
    entropy_coefficients = entropy_coefficient / normalizers
    score_delta, raw_entropy = _policy_head_delta(
        forward.probabilities,
        selected_options,
        log_probability_delta,
        entropy_coefficients,
    )
    score_delta /= forward.temperature
    normalized_entropy = np.zeros_like(raw_entropy)
    np.divide(
        raw_entropy,
        np.log(valid_counts),
        out=normalized_entropy,
        where=valid_counts > 1,
    )
    value_errors = forward.values - returns
    value_loss = float(np.mean(np.square(value_errors)))
    value_delta = 2.0 * value_coefficient * value_errors / rows
    gradients = _zero_gradients(policy)
    gradients["choice_score_weight"] = np.einsum(
        "ro,roh->h", score_delta, forward.option_hidden
    )
    gradients["choice_score_bias"] = np.asarray([np.sum(score_delta)])
    option_hidden_delta = (
        score_delta[:, :, None] * policy.choice_score_weight[None, None, :]
    )
    option_preactivation_delta = option_hidden_delta * (
        1.0 - np.square(forward.option_hidden)
    )
    state = np.broadcast_to(
        forward.second_hidden[:, None, :],
        (
            rows,
            forward.option_descriptors.shape[1],
            forward.second_hidden.shape[1],
        ),
    )
    joined = np.concatenate((state, forward.option_descriptors), axis=2)
    gradients["choice_option_weight"] = np.einsum(
        "roh,roi->hi", option_preactivation_delta, joined
    )
    gradients["choice_option_bias"] = np.sum(
        option_preactivation_delta, axis=(0, 1)
    )
    joined_delta = option_preactivation_delta @ policy.choice_option_weight
    state_delta = np.sum(
        joined_delta[:, :, : spec.HIDDEN_SIZES[1]], axis=1
    )
    gradients["choice_value_weight"] = (
        forward.second_hidden.T @ value_delta
    )
    gradients["choice_value_bias"] = np.asarray([np.sum(value_delta)])
    state_delta += value_delta[:, None] * policy.choice_value_weight[None, :]
    _backpropagate_hidden(
        policy,
        forward.observations,
        forward.first_hidden,
        forward.second_hidden,
        state_delta,
        gradients,
    )
    gradient_norm = optimizer.step(
        policy.parameter_arrays(),
        gradients,
        maximum_gradient_norm=maximum_gradient_norm,
    )
    policy.validate()
    return ChoicePpoMetrics(
        policy_loss=policy_loss,
        value_loss=value_loss,
        normalized_entropy=float(np.mean(normalized_entropy)),
        raw_entropy=float(np.mean(raw_entropy)),
        approximate_kl=float(
            np.mean(old_log_probabilities - new_log_probabilities)
        ),
        clip_fraction=float(np.mean(np.abs(ratios - 1.0) > clip_ratio)),
        gradient_norm=gradient_norm,
        temperature=forward.temperature,
    )


def _ppo_epochs(
    batch_function: Any,
    policy: BotPolicy,
    optimizer: Adam,
    arrays: Sequence[Array],
    *,
    rng: np.random.Generator,
    epochs: int,
    batch_size: int,
    kwargs: Mapping[str, Any],
) -> list[Any]:
    count = len(arrays[0])
    if count == 0:
        raise ValueError("PPO requires at least one transition")
    if epochs <= 0 or batch_size <= 0:
        raise ValueError("epochs and batch_size must be positive")
    metrics: list[Any] = []
    for _ in range(epochs):
        order = rng.permutation(count)
        for start in range(0, count, batch_size):
            indices = order[start : start + batch_size]
            metrics.append(
                batch_function(
                    policy,
                    optimizer,
                    *(value[indices] for value in arrays),
                    **kwargs,
                )
            )
    return metrics


def ppo_epochs(
    policy: BotPolicy,
    optimizer: Adam,
    observations: Array,
    movement_masks: Array,
    target_masks: Array,
    ability_masks: Array,
    aim_masks: Array,
    movement_actions: Array,
    target_actions: Array,
    ability_actions: Array,
    aim_actions: Array,
    old_log_probabilities: Array,
    advantages: Array,
    returns: Array,
    *,
    rng: np.random.Generator,
    epochs: int = 4,
    batch_size: int = 128,
    **kwargs: Any,
) -> list[PpoMetrics]:
    normalized_advantages = _as_float64(advantages).copy()
    if len(normalized_advantages) > 1 and np.std(normalized_advantages) > 1e-12:
        normalized_advantages = (
            normalized_advantages - np.mean(normalized_advantages)
        ) / np.std(normalized_advantages)
    arrays = tuple(
        np.asarray(value)
        for value in (
            observations,
            movement_masks,
            target_masks,
            ability_masks,
            aim_masks,
            movement_actions,
            target_actions,
            ability_actions,
            aim_actions,
            old_log_probabilities,
            normalized_advantages,
            returns,
        )
    )
    return _ppo_epochs(
        ppo_batch,
        policy,
        optimizer,
        arrays,
        rng=rng,
        epochs=epochs,
        batch_size=batch_size,
        kwargs=kwargs,
    )


def choice_ppo_epochs(
    policy: BotPolicy,
    optimizer: Adam,
    observations: Array,
    option_descriptors: Array,
    option_masks: Array,
    selected_options: Array,
    old_log_probabilities: Array,
    advantages: Array,
    returns: Array,
    *,
    rng: np.random.Generator,
    epochs: int = 4,
    batch_size: int = 32,
    **kwargs: Any,
) -> list[ChoicePpoMetrics]:
    normalized_advantages = _as_float64(advantages).copy()
    if len(normalized_advantages) > 1 and np.std(normalized_advantages) > 1e-12:
        normalized_advantages = (
            normalized_advantages - np.mean(normalized_advantages)
        ) / np.std(normalized_advantages)
    arrays = tuple(
        np.asarray(value)
        for value in (
            observations,
            option_descriptors,
            option_masks,
            selected_options,
            old_log_probabilities,
            normalized_advantages,
            returns,
        )
    )
    return _ppo_epochs(
        choice_ppo_batch,
        policy,
        optimizer,
        arrays,
        rng=rng,
        epochs=epochs,
        batch_size=batch_size,
        kwargs=kwargs,
    )


def concatenate_gae(
    episodes: Iterable[Mapping[str, Array]],
    *,
    gamma: float = 0.99,
    gae_lambda: float = 0.95,
) -> tuple[Array, Array]:
    all_advantages: list[Array] = []
    all_returns: list[Array] = []
    for episode in episodes:
        advantages, returns = generalized_advantage_estimate(
            episode["rewards"],
            episode["values"],
            episode["dones"],
            gamma=gamma,
            gae_lambda=gae_lambda,
        )
        all_advantages.append(advantages)
        all_returns.append(returns)
    if not all_advantages:
        raise ValueError("no episodes were supplied")
    return np.concatenate(all_advantages), np.concatenate(all_returns)
