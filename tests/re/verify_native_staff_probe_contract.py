#!/usr/bin/env python3
"""Verify the deferred native Staff-effect probe remains safely wired."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def require(source: str, fragment: str, label: str) -> None:
    if fragment not in source:
        raise AssertionError(f"{label}: missing {fragment!r}")


def main() -> int:
    layout = read("config/binary-layout.ini")
    seams = read("SolomonDarkModLoader/src/gameplay_seams.h")
    seam_storage = read(
        "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl"
    )
    seam_bindings = read(
        "SolomonDarkModLoader/src/gameplay_seams/state_and_address_bindings.inl"
    )
    types = read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/native_function_types.inl"
    )
    state = read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/runtime_request_state.inl"
    )
    api = read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_gameplay_action_queues.inl"
    )
    pump = read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_pump_loop.inl"
    )
    native_probe = read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/native_staff_behavior_probe.inl"
    )
    dispatch = read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks.inl"
    )
    lifecycle = read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_keyboard_injection.inl"
    )
    lua_calls = read(
        "SolomonDarkModLoader/src/lua_engine_bindings_debug/functions_native_calls.inl"
    )
    lua_registration = read("SolomonDarkModLoader/src/lua_engine_bindings_debug.cpp")
    harness = read("tools/multiplayer_staff_behavior_harness.py")

    require(layout, "staff_effect_resolver=0x0053B9F0", "layout")
    require(seams, "extern uintptr_t kStaffEffectResolver;", "seam declaration")
    require(seam_storage, "uintptr_t kStaffEffectResolver = 0;", "seam storage")
    require(
        seam_bindings,
        'SDMOD_ADDR("gameplay.hooks", "staff_effect_resolver", kStaffEffectResolver)',
        "seam binding",
    )
    require(
        types,
        "using StaffEffectResolverFn = void(__thiscall*)(void* self, std::uint32_t variant);",
        "typed resolver",
    )

    for fragment in (
        "struct PendingNativeStaffEffectProbe",
        "struct NativeStaffEffectProbeResult",
        "pending_native_staff_effect_probes",
        "next_native_staff_effect_probe_serial = 1",
    ):
        require(state, fragment, "request state")
    for fragment in (
        "bool QueueNativeStaffEffectProbe(",
        "bool GetNativeStaffEffectProbeResult(",
        "pending_native_staff_effect_probes",
    ):
        require(api, fragment, "public queue API")
    for fragment in (
        "native_staff_effect_probes.push_back(",
        "ExecuteNativeStaffEffectProbe(",
        "native_staff_effect_probe_result",
    ):
        require(pump, fragment, "gameplay pump")
    for fragment in (
        "CallNativeStaffEffectResolverSafe(",
        "ResolveGameAddressOrZero(kStaffEffectResolver)",
        "*hp_before = captured_hp_before;",
        "resolver(reinterpret_cast<void*>(source_actor), variant);",
        "*hp_after = captured_hp_after;",
    ):
        require(native_probe, fragment, "native probe")
    require(dispatch, '#include "native_staff_behavior_probe.inl"', "dispatch include")
    if lifecycle.count("pending_native_staff_effect_probes.clear();") != 2:
        raise AssertionError("lifecycle: Staff queue must reset on initialize and shutdown")

    for fragment in (
        "LuaDebugQueueNativeStaffEffectProbe",
        "LuaDebugGetNativeStaffEffectProbeResult",
    ):
        require(lua_calls, fragment, "Lua implementation")
        require(lua_registration, fragment, "Lua registration")
    for fragment in (
        "sd.debug.queue_native_staff_effect_probe(",
        "sd.debug.get_native_staff_effect_probe_result(",
    ):
        require(harness, fragment, "Staff behavior harness")
    for forbidden in ("call_thiscall_u32(", "STAFF_EFFECT_RESOLVER ="):
        if forbidden in harness:
            raise AssertionError(
                f"Staff behavior harness directly re-enters native resolver: {forbidden!r}"
            )

    print("PASS: deferred native Staff-effect probe contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
