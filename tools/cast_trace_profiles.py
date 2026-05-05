from __future__ import annotations

from dataclasses import dataclass

import cast_state_probe as csp


@dataclass(frozen=True)
class TraceSpec:
    key: str
    name: str
    address: int
    patch_size: int


TRACE_LIBRARY: dict[str, tuple[int, int]] = {
    "builder_entry": (csp.read_runtime_layout_offset("trace_builder_entry"), 7),
    "builder_finalize": (csp.read_runtime_layout_offset("trace_builder_finalize"), 0),
    "builder_after_finalize": (csp.read_runtime_layout_offset("trace_builder_after_finalize"), 0),
    "builder_keep_object": (csp.read_runtime_layout_offset("trace_builder_keep_object"), 0),
    "builder_callback_load": (csp.read_runtime_layout_offset("trace_builder_callback_load"), 6),
    "sink_entry": (csp.read_runtime_layout_offset("trace_sink_entry"), 7),
    "sink_inner_call": (csp.read_runtime_layout_offset("trace_sink_inner_call"), 5),
    "builder_drop_object": (csp.read_runtime_layout_offset("trace_builder_drop_object"), 0),
    "builder_return": (csp.read_runtime_layout_offset("trace_builder_return"), 0),
    "post_builder": (csp.read_runtime_layout_offset("trace_post_builder"), 5),
    "post_builder_followup": (csp.read_runtime_layout_offset("trace_post_builder_followup"), 5),
}

TRACE_PROFILE_KEYS: dict[str, tuple[str, ...]] = {
    "safe_entry": (
        "builder_entry",
        "builder_finalize",
        "sink_entry",
    ),
    "full": (
        "builder_entry",
        "builder_finalize",
        "builder_after_finalize",
        "builder_keep_object",
        "builder_callback_load",
        "sink_entry",
        "sink_inner_call",
        "builder_drop_object",
        "builder_return",
        "post_builder",
        "post_builder_followup",
    ),
    "return_chain": (
        "builder_return",
        "post_builder",
        "post_builder_followup",
    ),
    "post_only": (
        "post_builder",
        "post_builder_followup",
    ),
    "entry_post": (
        "builder_entry",
        "post_builder",
        "post_builder_followup",
    ),
    "tail_return": (
        "builder_after_finalize",
        "builder_keep_object",
        "builder_drop_object",
        "builder_return",
        "post_builder",
        "post_builder_followup",
    ),
    "callback_return": (
        "builder_callback_load",
        "builder_return",
        "post_builder",
        "post_builder_followup",
    ),
    "sink_path": (
        "builder_callback_load",
        "sink_entry",
        "sink_inner_call",
        "builder_return",
        "post_builder",
        "post_builder_followup",
    ),
}

STABLE_TRACE_PROFILES: frozenset[str] = frozenset({"safe_entry"})


def trace_profile_names() -> tuple[str, ...]:
    return tuple(TRACE_PROFILE_KEYS.keys())


def trace_profile_is_stable(profile: str) -> bool:
    return profile in STABLE_TRACE_PROFILES


def build_trace_specs(prefix: str, profile: str) -> list[TraceSpec]:
    keys = TRACE_PROFILE_KEYS[profile]
    specs: list[TraceSpec] = []
    for key in keys:
        address, patch_size = TRACE_LIBRARY[key]
        specs.append(TraceSpec(key, f"{prefix}_{key}", address, patch_size))
    return specs
