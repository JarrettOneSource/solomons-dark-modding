"""Contracts for the bounded per-mod Lua timer scheduler."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_timers_are_bounded_local_and_tick_driven() -> str:
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings.cpp")
    timer = _read("SolomonDarkModLoader/src/lua_engine_bindings_timer.cpp")
    events = _read("SolomonDarkModLoader/src/lua_engine_events.cpp")
    internal = _read("SolomonDarkModLoader/src/lua_engine_internal.h")
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    project = _read("SolomonDarkModLoader/SolomonDarkModLoader.vcxproj")
    documentation = _read("docs/lua-timer.md")
    roadmap = _read("docs/lua-seam-roadmap.md")
    manifest = _read("mods/lua_timer_lab/manifest.json")
    sample = _read("mods/lua_timer_lab/scripts/main.lua")
    verifier = _read("tools/verify_lua_timers.py")

    assert "RegisterLuaTimerBindings(mod->state)" in bindings
    assert "lua_createtable(mod->state, 0, 21);" in bindings
    assert "std::vector<LuaTimerEntry> timers" in internal
    assert '"timer.local.scheduler"' in engine
    assert "ClearLuaTimersForMod(mod)" in engine
    assert "lua_engine_bindings_timer.cpp" in project

    for token in (
        "kLuaTimerMaximumDelayMs",
        "kLuaTimerMaximumSequenceSteps = 64",
        "kLuaTimerMaximumScheduledCallbacksPerMod = 256",
        "kLuaTimerMaximumCallbacksPerTick = 64",
        "context.monotonic_milliseconds",
        "std::vector<std::uint64_t> due_ids",
        "timer->due_ms = context.monotonic_milliseconds + timer->interval_ms",
        'RegisterFunction(state, &LuaTimerAfter, "after")',
        'RegisterFunction(state, &LuaTimerEvery, "every")',
        'RegisterFunction(state, &LuaTimerSequence, "sequence")',
        'RegisterFunction(state, &LuaTimerCancel, "cancel")',
        'RegisterFunction(state, &LuaTimerClear, "clear")',
        'lua_setfield(state, -2, "timer")',
        "timer callback ",
    ):
        assert token in timer, f"Lua timer implementation lacks: {token}"

    assert "mod->runtime_tick_registered || HasLuaTimers(mod.get())" in events
    _require_in_order(
        events,
        "BeginLuaDrawFrame(mod->descriptor.id)",
        "DispatchLuaTimersToMod(mod, context)",
        "DispatchEventToMod(",
        "CommitLuaDrawFrame(mod->descriptor.id)",
    )

    assert '"enabled": false' in manifest
    assert '"timer.local.scheduler"' in manifest
    assert "sd.timer.after" in sample
    assert "sd.timer.every" in sample
    assert "sd.timer.sequence" in sample

    for token in (
        "## API",
        "## Scheduling and limits",
        "## Multiplayer",
        "never replicated",
        "256 scheduled callbacks",
        "64 callbacks",
        "timer.local.scheduler",
    ):
        assert token in documentation, f"Lua timer documentation lacks: {token}"
    assert "**Implemented 2026-07-22.** `sd.timer`" in roadmap
    for token in (
        "sd.timer.after(90",
        "sd.timer.every(50",
        "sd.timer.sequence({",
        "sd.timer.cancel(cancelled)",
        "repeating callback count mismatch",
        "sequence order mismatch",
    ):
        assert token in verifier, f"Lua timer verifier lacks: {token}"

    return (
        "sd.timer provides bounded per-mod after/every/sequence scheduling, "
        "runs from monotonic runtime ticks, and stays local in multiplayer"
    )
