"""Contracts for owner-scoped local-player bot control."""

from __future__ import annotations

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_local_player_takeover_is_owner_scoped_and_stock_routed() -> str:
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    binding = "\n".join((
        _read("SolomonDarkModLoader/src/lua_engine_bindings_input.cpp"),
        _read(
            "SolomonDarkModLoader/src/lua_engine_bindings_input/"
            "local_player_takeover.inl"
        ),
    ))
    public_header = _read(
        "SolomonDarkModLoader/include/mod_loader_public_api.inl"
    )
    request_state = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "runtime_request_state.inl"
    )
    input_api = "\n".join((
        _read(
            "SolomonDarkModLoader/src/mod_loader_gameplay/"
            "public_api_input_queueing.inl"
        ),
        _read(
            "SolomonDarkModLoader/src/mod_loader_gameplay/"
            "public_api_local_player_takeover.inl"
        ),
    ))
    local_input = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/local_player_stock_input_runtime.inl"
    )
    player_tick = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/player_actor_tick_hook.inl"
    )
    control = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_control_hooks.inl"
    )
    cast = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_cast_hooks.inl"
    )
    mouse = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_mouse_refresh_hook.inl"
    )
    close = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    assert '"input.local_player.takeover"' in engine
    for token in (
        "SetLocalPlayerControlTakeover(",
        "SetLocalPlayerControlTakeoverTarget(",
        "TryGetLocalPlayerControlTakeoverState(",
        "ClearLocalPlayerControlTakeoverForMod(",
    ):
        assert token in public_header, f"takeover public API lacks {token}"
    for token in (
        "local_player_takeover_active",
        "local_player_takeover_owner_mod_id",
        "local_player_takeover_target_actor",
        "local_player_takeover_target_x",
        "local_player_takeover_target_y",
    ):
        assert token in request_state, f"takeover state lacks {token}"

    _require_in_order(
        input_api,
        "bool SetLocalPlayerControlTakeover(",
        "owner_mod_id.empty()",
        "local_player_takeover_owner_mod_id",
        "local_player_takeover_active.store(",
    )
    _require_in_order(
        input_api,
        "void ClearLocalPlayerControlTakeoverInputState()",
        "pending_movement_frames.store(",
        "ClearQueuedGameplayMouseLeft()",
        "local_player_takeover_target_actor.store(",
        "ClearWizardActorGameplayCastState(",
    )
    _require_in_order(
        input_api,
        "bool SetLocalPlayerControlTakeover(",
        "if (!enabled)",
        "local_player_takeover_active.store(",
        "ClearLocalPlayerControlTakeoverInputState(",
    )
    assert "pending_movement_frames.store(" in input_api
    assert "pending_injected_keyboard_control_frames.store(" in input_api
    assert "local_player_takeover_target_actor.store(" in input_api
    assert "state->clean =" in input_api

    assert "IsLocalPlayerControlTakeoverActive()" in local_input
    _require_in_order(
        player_tick,
        "PumpLuaWorkOnGameplayThread(lua_tick_context)",
        "ScopedLocalPlayerScriptedMovementInput scripted_movement_input(",
        "original(self);",
    )
    assert "takeover_active_" in local_input
    assert "movement_x = 0.0f" in local_input
    assert "IsLocalPlayerControlTakeoverActive()" in control
    assert "ApplyPinnedLocalPlayerControlTakeoverTarget(" in control
    assert "IsLocalPlayerControlTakeoverActive()" in mouse
    assert "TryGetLocalPlayerControlTakeoverTarget(" in cast
    assert "world_point[0] = takeover_target_x" in cast
    assert "world_point[1] = takeover_target_y" in cast

    for token in (
        "LuaInputSetLocalPlayerTakeover",
        "LuaInputSetLocalPlayerTakeoverTarget",
        "LuaInputGetLocalPlayerTakeoverState",
        '"set_local_player_takeover"',
        '"set_local_player_takeover_target"',
        '"get_local_player_takeover_state"',
    ):
        assert token in binding, f"Lua takeover binding lacks {token}"
    assert "GetLoadedLuaMod(state)" in binding
    assert "mod->descriptor.id" in binding
    assert "ClearLocalPlayerControlTakeoverForMod(mod->descriptor.id)" in close

    return (
        "The owner-scoped local-player takeover uses the slot-zero stock "
        "control path and clears every queued control on release"
    )
