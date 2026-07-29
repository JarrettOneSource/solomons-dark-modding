"""Small, auditable NumPy actor-critic used by Lua Bot training."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from . import spec

Array = np.ndarray


def _as_float64(value: Any) -> Array:
    return np.asarray(value, dtype=np.float64)


def _as_bool(value: Any) -> Array:
    return np.asarray(value, dtype=np.bool_)


def _require_shape(name: str, value: Array, shape: tuple[int, ...]) -> None:
    if value.shape != shape:
        raise ValueError(
            f"{name} has shape {value.shape}, expected {shape}"
        )
    if not np.all(np.isfinite(value)):
        raise ValueError(f"{name} contains a non-finite value")


def _validate_mask(name: str, mask: Array, rows: int, columns: int) -> Array:
    normalized = _as_bool(mask)
    _require_shape(name, normalized, (rows, columns))
    if not np.all(np.any(normalized, axis=1)):
        raise ValueError(f"{name} contains a row with no legal action")
    return normalized


def masked_softmax(logits: Array, mask: Array) -> Array:
    logits = _as_float64(logits)
    if logits.ndim != 2:
        raise ValueError("logits must be a rank-2 array")
    mask = _validate_mask("mask", mask, *logits.shape)
    masked = np.where(mask, logits, -np.inf)
    maximum = np.max(masked, axis=1, keepdims=True)
    exponentials = np.where(mask, np.exp(masked - maximum), 0.0)
    denominator = np.sum(exponentials, axis=1, keepdims=True)
    return exponentials / denominator


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
    hidden: Array
    movement_probabilities: Array
    cast_probabilities: Array
    values: Array


@dataclass(frozen=True)
class ActionBatch:
    movement_actions: Array
    cast_actions: Array
    log_probabilities: Array
    values: Array
    movement_probabilities: Array
    cast_probabilities: Array


@dataclass(frozen=True)
class PpoMetrics:
    policy_loss: float
    value_loss: float
    entropy: float
    approximate_kl: float
    clip_fraction: float


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
        movement_weight: Array,
        movement_bias: Array,
        cast_weight: Array,
        cast_bias: Array,
        value_weight: Array,
        value_bias: Array,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.input_weight = _as_float64(input_weight).copy()
        self.input_bias = _as_float64(input_bias).copy()
        self.movement_weight = _as_float64(movement_weight).copy()
        self.movement_bias = _as_float64(movement_bias).copy()
        self.cast_weight = _as_float64(cast_weight).copy()
        self.cast_bias = _as_float64(cast_bias).copy()
        self.value_weight = _as_float64(value_weight).copy()
        self.value_bias = _as_float64(value_bias).copy()
        self.metadata = dict(metadata or {})
        self.validate()

    @classmethod
    def initialize(
        cls,
        rng: np.random.Generator,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> "BotPolicy":
        shape = spec.model_shape()
        observation_size = shape["observation_size"]
        hidden_size = shape["hidden_size"]
        movement_size = shape["movement_action_size"]
        cast_size = shape["cast_action_size"]

        hidden_limit = math.sqrt(6.0 / (observation_size + hidden_size))
        movement_limit = math.sqrt(6.0 / (hidden_size + movement_size))
        cast_limit = math.sqrt(6.0 / (hidden_size + cast_size))
        value_limit = math.sqrt(6.0 / (hidden_size + 1))
        return cls(
            input_weight=rng.uniform(
                -hidden_limit,
                hidden_limit,
                size=(hidden_size, observation_size),
            ),
            input_bias=np.zeros(hidden_size),
            movement_weight=rng.uniform(
                -movement_limit,
                movement_limit,
                size=(movement_size, hidden_size),
            ),
            movement_bias=np.zeros(movement_size),
            cast_weight=rng.uniform(
                -cast_limit,
                cast_limit,
                size=(cast_size, hidden_size),
            ),
            cast_bias=np.zeros(cast_size),
            value_weight=rng.uniform(
                -value_limit,
                value_limit,
                size=hidden_size,
            ),
            value_bias=np.zeros(1),
            metadata=metadata,
        )

    def parameter_arrays(self) -> dict[str, Array]:
        return {
            "input_weight": self.input_weight,
            "input_bias": self.input_bias,
            "movement_weight": self.movement_weight,
            "movement_bias": self.movement_bias,
            "cast_weight": self.cast_weight,
            "cast_bias": self.cast_bias,
            "value_weight": self.value_weight,
            "value_bias": self.value_bias,
        }

    def validate(self) -> None:
        shape = spec.model_shape()
        observation_size = shape["observation_size"]
        hidden_size = shape["hidden_size"]
        movement_size = shape["movement_action_size"]
        cast_size = shape["cast_action_size"]
        expected = {
            "input_weight": (hidden_size, observation_size),
            "input_bias": (hidden_size,),
            "movement_weight": (movement_size, hidden_size),
            "movement_bias": (movement_size,),
            "cast_weight": (cast_size, hidden_size),
            "cast_bias": (cast_size,),
            "value_weight": (hidden_size,),
            "value_bias": (1,),
        }
        for name, parameter in self.parameter_arrays().items():
            _require_shape(name, parameter, expected[name])

    def forward(
        self,
        observations: Array,
        movement_masks: Array,
        cast_masks: Array,
    ) -> ForwardPass:
        observations = _as_float64(observations)
        if observations.ndim == 1:
            observations = observations[None, :]
        rows = observations.shape[0]
        _require_shape(
            "observations",
            observations,
            (rows, len(spec.OBSERVATION_NAMES)),
        )
        movement_masks = _validate_mask(
            "movement_masks",
            movement_masks,
            rows,
            len(spec.MOVEMENT_ACTION_NAMES),
        )
        cast_masks = _validate_mask(
            "cast_masks",
            cast_masks,
            rows,
            len(spec.CAST_ACTION_NAMES),
        )

        hidden = np.tanh(
            observations @ self.input_weight.T + self.input_bias
        )
        movement_logits = (
            hidden @ self.movement_weight.T + self.movement_bias
        )
        cast_logits = hidden @ self.cast_weight.T + self.cast_bias
        values = hidden @ self.value_weight + self.value_bias[0]
        return ForwardPass(
            observations=observations,
            hidden=hidden,
            movement_probabilities=masked_softmax(
                movement_logits,
                movement_masks,
            ),
            cast_probabilities=masked_softmax(cast_logits, cast_masks),
            values=values,
        )

    def act(
        self,
        observations: Array,
        movement_masks: Array,
        cast_masks: Array,
        *,
        deterministic: bool,
        rng: np.random.Generator | None = None,
    ) -> ActionBatch:
        forward = self.forward(observations, movement_masks, cast_masks)
        if deterministic:
            movement_actions = np.argmax(
                forward.movement_probabilities,
                axis=1,
            )
            cast_actions = np.argmax(forward.cast_probabilities, axis=1)
        else:
            if rng is None:
                raise ValueError("stochastic action selection requires rng")
            movement_actions = sample_categorical(
                forward.movement_probabilities,
                rng,
            )
            cast_actions = sample_categorical(
                forward.cast_probabilities,
                rng,
            )
        log_probabilities = selected_log_probabilities(
            forward.movement_probabilities,
            movement_actions,
        ) + selected_log_probabilities(
            forward.cast_probabilities,
            cast_actions,
        )
        return ActionBatch(
            movement_actions=movement_actions,
            cast_actions=cast_actions,
            log_probabilities=log_probabilities,
            values=forward.values.copy(),
            movement_probabilities=forward.movement_probabilities,
            cast_probabilities=forward.cast_probabilities,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **spec.contract_metadata(),
            "metadata": dict(self.metadata),
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
            raise ValueError("model parameters must be an object")
        required = {
            "input_weight",
            "input_bias",
            "movement_weight",
            "movement_bias",
            "cast_weight",
            "cast_bias",
            "value_weight",
            "value_bias",
        }
        if set(parameters) != required:
            raise ValueError(
                "model parameter names do not match the v1 contract"
            )
        metadata = model.get("metadata")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise ValueError("model metadata must be an object")
        return cls(
            **{
                name: _as_float64(parameters[name])
                for name in sorted(required)
            },
            metadata=metadata,
        )


def save_model(policy: BotPolicy, path: Path) -> None:
    policy.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(
            json.dumps(policy.to_dict(), indent=2, sort_keys=True) + "\n"
        )


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
    if text == "-0":
        return "0"
    return text


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
            lines.append(
                f"{child_prefix}{_lua_value(item, indent + 2)},"
            )
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
    shape = spec.model_shape()
    value: dict[str, Any] = {
        "format": spec.MODEL_FORMAT,
        "version": spec.MODEL_VERSION,
        "observation_version": spec.OBSERVATION_VERSION,
        "architecture": spec.ARCHITECTURE,
        **shape,
        "observation_names": spec.OBSERVATION_NAMES,
        "movement_action_names": spec.MOVEMENT_ACTION_NAMES,
        "cast_action_names": spec.CAST_ACTION_NAMES,
        "parameters": {
            name: parameter
            for name, parameter in policy.parameter_arrays().items()
        },
        "metadata": policy.metadata,
    }
    return "-- Generated by tools/train_bot_policy.py. Do not edit.\nreturn " + (
        _lua_value(value)
    ) + "\n"


def export_lua_weights(policy: BotPolicy, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(render_lua_weights(policy))


def _zero_gradients(policy: BotPolicy) -> dict[str, Array]:
    return {
        name: np.zeros_like(parameter)
        for name, parameter in policy.parameter_arrays().items()
    }


def behavior_clone_batch(
    policy: BotPolicy,
    optimizer: Adam,
    observations: Array,
    movement_masks: Array,
    cast_masks: Array,
    movement_actions: Array,
    cast_actions: Array,
    *,
    maximum_gradient_norm: float = 1.0,
) -> tuple[float, float]:
    observations = _as_float64(observations)
    rows = observations.shape[0]
    movement_actions = np.asarray(movement_actions, dtype=np.int64)
    cast_actions = np.asarray(cast_actions, dtype=np.int64)
    if movement_actions.shape != (rows,) or cast_actions.shape != (rows,):
        raise ValueError("behavior-cloning action batch shape mismatch")

    forward = policy.forward(observations, movement_masks, cast_masks)
    movement_log = selected_log_probabilities(
        forward.movement_probabilities,
        movement_actions,
    )
    cast_log = selected_log_probabilities(
        forward.cast_probabilities,
        cast_actions,
    )
    loss = -float(np.mean(movement_log + cast_log))

    movement_delta = forward.movement_probabilities.copy()
    movement_delta[np.arange(rows), movement_actions] -= 1.0
    movement_delta /= rows
    cast_delta = forward.cast_probabilities.copy()
    cast_delta[np.arange(rows), cast_actions] -= 1.0
    cast_delta /= rows

    gradients = _zero_gradients(policy)
    gradients["movement_weight"] = movement_delta.T @ forward.hidden
    gradients["movement_bias"] = np.sum(movement_delta, axis=0)
    gradients["cast_weight"] = cast_delta.T @ forward.hidden
    gradients["cast_bias"] = np.sum(cast_delta, axis=0)
    hidden_delta = (
        movement_delta @ policy.movement_weight
        + cast_delta @ policy.cast_weight
    )
    preactivation_delta = hidden_delta * (
        1.0 - np.square(forward.hidden)
    )
    gradients["input_weight"] = (
        preactivation_delta.T @ forward.observations
    )
    gradients["input_bias"] = np.sum(preactivation_delta, axis=0)

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
    cast_masks: Array,
    movement_actions: Array,
    cast_actions: Array,
) -> tuple[float, float, float]:
    predicted = policy.act(
        observations,
        movement_masks,
        cast_masks,
        deterministic=True,
    )
    movement_actions = np.asarray(movement_actions, dtype=np.int64)
    cast_actions = np.asarray(cast_actions, dtype=np.int64)
    movement_accuracy = float(
        np.mean(predicted.movement_actions == movement_actions)
    )
    cast_accuracy = float(np.mean(predicted.cast_actions == cast_actions))
    joint_accuracy = float(
        np.mean(
            (predicted.movement_actions == movement_actions)
            & (predicted.cast_actions == cast_actions)
        )
    )
    return movement_accuracy, cast_accuracy, joint_accuracy


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
        delta = (
            rewards[index]
            + gamma * next_value * continuation
            - values[index]
        )
        next_advantage = (
            delta
            + gamma * gae_lambda * continuation * next_advantage
        )
        advantages[index] = next_advantage
        next_value = values[index]
    return advantages, advantages + values


def _entropy_gradient(probabilities: Array) -> tuple[Array, Array]:
    safe_log = np.zeros_like(probabilities)
    positive = probabilities > 0.0
    safe_log[positive] = np.log(probabilities[positive])
    entropy = -np.sum(probabilities * safe_log, axis=1)
    gradient = -probabilities * (safe_log + entropy[:, None])
    return entropy, gradient


def ppo_batch(
    policy: BotPolicy,
    optimizer: Adam,
    observations: Array,
    movement_masks: Array,
    cast_masks: Array,
    movement_actions: Array,
    cast_actions: Array,
    old_log_probabilities: Array,
    advantages: Array,
    returns: Array,
    *,
    clip_ratio: float = 0.2,
    value_coefficient: float = 0.5,
    entropy_coefficient: float = 0.01,
    maximum_gradient_norm: float = 0.5,
) -> PpoMetrics:
    observations = _as_float64(observations)
    rows = observations.shape[0]
    movement_actions = np.asarray(movement_actions, dtype=np.int64)
    cast_actions = np.asarray(cast_actions, dtype=np.int64)
    old_log_probabilities = _as_float64(old_log_probabilities)
    advantages = _as_float64(advantages)
    returns = _as_float64(returns)
    for name, value in (
        ("movement_actions", movement_actions),
        ("cast_actions", cast_actions),
        ("old_log_probabilities", old_log_probabilities),
        ("advantages", advantages),
        ("returns", returns),
    ):
        if value.shape != (rows,):
            raise ValueError(f"{name} has the wrong batch shape")
    if clip_ratio <= 0.0:
        raise ValueError("clip_ratio must be positive")

    forward = policy.forward(observations, movement_masks, cast_masks)
    movement_log = selected_log_probabilities(
        forward.movement_probabilities,
        movement_actions,
    )
    cast_log = selected_log_probabilities(
        forward.cast_probabilities,
        cast_actions,
    )
    new_log_probabilities = movement_log + cast_log
    ratios = np.exp(new_log_probabilities - old_log_probabilities)
    clipped_ratios = np.clip(
        ratios,
        1.0 - clip_ratio,
        1.0 + clip_ratio,
    )
    surrogate = np.minimum(
        ratios * advantages,
        clipped_ratios * advantages,
    )
    policy_loss = -float(np.mean(surrogate))

    active = (
        ((advantages >= 0.0) & (ratios <= 1.0 + clip_ratio))
        | ((advantages < 0.0) & (ratios >= 1.0 - clip_ratio))
    )
    log_probability_delta = np.where(
        active,
        -(advantages * ratios) / rows,
        0.0,
    )

    movement_delta = -forward.movement_probabilities
    movement_delta[
        np.arange(rows),
        movement_actions,
    ] += 1.0
    movement_delta *= log_probability_delta[:, None]
    cast_delta = -forward.cast_probabilities
    cast_delta[np.arange(rows), cast_actions] += 1.0
    cast_delta *= log_probability_delta[:, None]

    movement_entropy, movement_entropy_gradient = _entropy_gradient(
        forward.movement_probabilities
    )
    cast_entropy, cast_entropy_gradient = _entropy_gradient(
        forward.cast_probabilities
    )
    movement_delta += (
        -entropy_coefficient
        * movement_entropy_gradient
        / rows
    )
    cast_delta += (
        -entropy_coefficient
        * cast_entropy_gradient
        / rows
    )

    value_errors = forward.values - returns
    value_loss = float(np.mean(np.square(value_errors)))
    value_delta = (
        2.0 * value_coefficient * value_errors / rows
    )

    gradients = _zero_gradients(policy)
    gradients["movement_weight"] = movement_delta.T @ forward.hidden
    gradients["movement_bias"] = np.sum(movement_delta, axis=0)
    gradients["cast_weight"] = cast_delta.T @ forward.hidden
    gradients["cast_bias"] = np.sum(cast_delta, axis=0)
    gradients["value_weight"] = forward.hidden.T @ value_delta
    gradients["value_bias"] = np.asarray([np.sum(value_delta)])

    hidden_delta = (
        movement_delta @ policy.movement_weight
        + cast_delta @ policy.cast_weight
        + value_delta[:, None] * policy.value_weight[None, :]
    )
    preactivation_delta = hidden_delta * (
        1.0 - np.square(forward.hidden)
    )
    gradients["input_weight"] = (
        preactivation_delta.T @ forward.observations
    )
    gradients["input_bias"] = np.sum(preactivation_delta, axis=0)

    optimizer.step(
        policy.parameter_arrays(),
        gradients,
        maximum_gradient_norm=maximum_gradient_norm,
    )
    policy.validate()

    entropy = float(np.mean(movement_entropy + cast_entropy))
    approximate_kl = float(
        np.mean(old_log_probabilities - new_log_probabilities)
    )
    clip_fraction = float(
        np.mean(np.abs(ratios - 1.0) > clip_ratio)
    )
    return PpoMetrics(
        policy_loss=policy_loss,
        value_loss=value_loss,
        entropy=entropy,
        approximate_kl=approximate_kl,
        clip_fraction=clip_fraction,
    )


def ppo_epochs(
    policy: BotPolicy,
    optimizer: Adam,
    observations: Array,
    movement_masks: Array,
    cast_masks: Array,
    movement_actions: Array,
    cast_actions: Array,
    old_log_probabilities: Array,
    advantages: Array,
    returns: Array,
    *,
    rng: np.random.Generator,
    epochs: int = 4,
    batch_size: int = 128,
    clip_ratio: float = 0.2,
    value_coefficient: float = 0.5,
    entropy_coefficient: float = 0.01,
    maximum_gradient_norm: float = 0.5,
) -> list[PpoMetrics]:
    observations = _as_float64(observations)
    count = observations.shape[0]
    if count == 0:
        raise ValueError("PPO requires at least one transition")
    if epochs <= 0 or batch_size <= 0:
        raise ValueError("epochs and batch_size must be positive")

    normalized_advantages = _as_float64(advantages).copy()
    if count > 1:
        standard_deviation = float(np.std(normalized_advantages))
        if standard_deviation > 1e-12:
            normalized_advantages = (
                normalized_advantages
                - float(np.mean(normalized_advantages))
            ) / standard_deviation

    arrays = (
        observations,
        _as_bool(movement_masks),
        _as_bool(cast_masks),
        np.asarray(movement_actions, dtype=np.int64),
        np.asarray(cast_actions, dtype=np.int64),
        _as_float64(old_log_probabilities),
        normalized_advantages,
        _as_float64(returns),
    )
    metrics: list[PpoMetrics] = []
    for _ in range(epochs):
        order = rng.permutation(count)
        for start in range(0, count, batch_size):
            indices = order[start : start + batch_size]
            batch = [value[indices] for value in arrays]
            metrics.append(
                ppo_batch(
                    policy,
                    optimizer,
                    *batch,
                    clip_ratio=clip_ratio,
                    value_coefficient=value_coefficient,
                    entropy_coefficient=entropy_coefficient,
                    maximum_gradient_norm=maximum_gradient_norm,
                )
            )
    return metrics


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
