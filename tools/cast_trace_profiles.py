from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TraceSpec:
    key: str
    name: str
    address: int
    patch_size: int


TRACE_LIBRARY: dict[str, tuple[int, int]] = {
    "builder_entry": (0x0044F5F0, 7),
    "builder_finalize": (0x0045ADA0, 0),
    "builder_after_finalize": (0x0044FED8, 0),
    "builder_keep_object": (0x0044FEE9, 0),
    "builder_callback_load": (0x0044FF03, 6),
    "sink_entry": (0x00624610, 7),
    "sink_inner_call": (0x00624652, 5),
    "builder_drop_object": (0x0044FF0F, 0),
    "builder_return": (0x0044FF38, 0),
    "post_builder": (0x0052DB09, 5),
    "post_builder_followup": (0x0052DB0B, 5),
}

TRACE_PROFILE_KEYS: dict[str, tuple[str, ...]] = {
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


def trace_profile_names() -> tuple[str, ...]:
    return tuple(TRACE_PROFILE_KEYS.keys())


def build_trace_specs(prefix: str, profile: str) -> list[TraceSpec]:
    keys = TRACE_PROFILE_KEYS[profile]
    specs: list[TraceSpec] = []
    for key in keys:
        address, patch_size = TRACE_LIBRARY[key]
        specs.append(TraceSpec(key, f"{prefix}_{key}", address, patch_size))
    return specs
