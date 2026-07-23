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
    multiplayer_verifier = _read(
        "tools/verify_lua_timer_multiplayer.py"
    )
    multiplayer_verifier_tests = _read(
        "tests/test_lua_timer_multiplayer_verifier.py"
    )
    workflow = _read(".github/workflows/lua-authoring-contracts.yml")

    assert "RegisterLuaTimerBindings(mod->state)" in bindings
    assert "lua_createtable(mod->state, 0, 29);" in bindings
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
    for token in (
        'ACCEPTANCE_MOD_ID = "sample.lua.timer_lab"',
        "STATE_PROBE",
        "RESET_PROBE",
        "RELEASE_PROBE",
        "CAPACITY_PROBE",
        "_setup_probe",
        "timer_state_matches",
        "setup_matches",
        "capacity_matches",
        "--confirm-scheduling",
        "tile_windows=False",
        "kill_existing=False",
        "exact_mod_id=ACCEPTANCE_MOD_ID",
        "stop_game_processes(launched_process_ids)",
    ):
        assert token in multiplayer_verifier, (
            f"Lua timer multiplayer verifier lacks: {token}"
        )
    for token in (
        "test_state_matcher_requires_exact_peer_local_result",
        "test_setup_and_capacity_require_exact_limits",
        "test_scheduling_confirmation_is_required_before_contact",
        "test_disposable_pair_is_required_before_contact",
        "test_failed_launch_does_not_contact_unowned_lua_pipes",
        "test_incomplete_process_ledger_stops_only_owned_process",
        "test_run_proves_timer_completion_capacity_and_isolation",
    ):
        assert token in multiplayer_verifier_tests, (
            f"Lua timer multiplayer verifier tests lack: {token}"
        )
    assert (
        "python -m unittest tests.test_lua_timer_multiplayer_verifier"
        in workflow
    )

    return (
        "sd.timer provides bounded per-mod after/every/sequence scheduling, "
        "runs from monotonic runtime ticks, and has exact two-peer local "
        "capacity and lifecycle acceptance"
    )
