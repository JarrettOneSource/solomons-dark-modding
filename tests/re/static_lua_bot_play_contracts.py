"""Contracts for owner-scoped local-player bot control."""

from __future__ import annotations

import re

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
        "local_player_takeover_primary_selection_actor",
        "local_player_takeover_primary_selection_before",
        "local_player_takeover_primary_selection_snapshot_pending",
        "local_player_takeover_primary_selection_restore_succeeded",
        "local_player_takeover_native_state_clear_succeeded",
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
        "bool ClearLocalPlayerControlTakeoverInputState(",
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
        "EnsureLocalPlayerControlBrainForTakeover(",
        "ClearLocalPlayerControlTakeoverInputState(",
        "RestoreLocalPlayerControlTakeoverPrimarySelection(",
    )
    _require_in_order(
        input_api,
        "bool EnsureLocalPlayerControlBrainForTakeover(",
        "kActorControlBrainMoveInputYOffset +",
        "kPlayerActorInitializeControlBrain",
        "CallPlayerActorInitializeControlBrainSafe(",
        "control_brain_is_live(control_brain_address)",
    )
    assert "pending_movement_frames.store(" in input_api
    assert "pending_injected_keyboard_control_frames.store(" in input_api
    assert "local_player_takeover_target_actor.store(" in input_api
    assert "if (state->active)" in input_api
    assert "state->actor_address = local_actor_address;" in input_api
    assert "state->actor_address == 0" in input_api
    clean_expression = input_api.split("state->clean =", 1)[1].split(
        "return true;",
        1,
    )[0]
    assert "pending_movement_x" in clean_expression
    assert "control_brain_move_x" in clean_expression
    assert "movement_input_x" in clean_expression
    assert "state->clean =" in input_api
    assert "!state->primary_selection_snapshot_pending" in clean_expression
    assert "state->primary_selection_restore_succeeded" in clean_expression
    assert "state->native_state_clear_succeeded" in clean_expression

    movement_hold = input_api.split(
        "bool QueueGameplayMovementHoldFrames(", 1
    )[1].split(
        "bool SetGameplayNativeControlAllowanceFrames(", 1
    )[0]
    assert "pending_movement_frames.store(" in movement_hold, (
        "movement is one replaceable direction intent, so repeated hold "
        "publication must be idempotent"
    )
    assert "pending_movement_frames.fetch_add(" not in movement_hold, (
        "a single overwritten direction cannot retain additive duration"
    )

    assert "pending_movement_frames.fetch_add(" not in local_input, (
        "failed application must not add duration to a newer movement intent"
    )
    assert "RestoreConsumedPendingFrame();" in local_input
    assert ".compare_exchange_strong(" in local_input

    clear_start = input_api.index(
        "bool ClearLocalPlayerControlTakeoverInputState("
    )
    clear_end = input_api.index(
        "bool EnsureLocalPlayerControlBrainForTakeover(",
        clear_start,
    )
    clear_body = input_api[clear_start:clear_end]
    for token in (
        "kGameplayCastIntentOffset",
        "kGameplayLocalMovementInputXOffset",
        "kGameplayLocalMovementInputYOffset",
        "kGameplayMouseLeftButtonOffset",
        "kGameplayMouseRightButtonOffset",
        "ClearWizardActorGameplayCastState(",
        "local_player_takeover_native_state_clear_succeeded",
    ):
        assert token in clear_body, (
            "takeover native handback lacks " + token
        )

    cast_clear_start = input_api.index(
        "bool ClearWizardActorGameplayCastState("
    )
    cast_clear_end = input_api.index(
        "bool ClearLocalPlayerGameplayCastState(",
        cast_clear_start,
    )
    cast_clear_body = input_api[cast_clear_start:cast_clear_end]
    for token in (
        "kActorPrimarySkillIdOffset",
        "kActorPreviousSkillIdOffset",
        "kActorPrimaryActionLatchE4Offset",
        "kActorPrimaryActionLatchE8Offset",
        "kActorPostGateActiveByteOffset",
        "kActorSpellTargetGroupByteOffset",
        "kActorSpellTargetSlotShortOffset",
        "kActorAimTargetXOffset",
        "kActorAimTargetYOffset",
        "kActorAimTargetAux0Offset",
        "kActorAimTargetAux1Offset",
        "kActorCurrentTargetActorOffset",
        "kActorCurrentTargetBucketDeltaOffset",
        "kActorControlBrainTargetSlotOffset",
        "kActorControlBrainTargetHandleOffset",
        "kActorControlBrainRetargetTicksOffset",
        "kActorControlBrainTargetCooldownTicksOffset",
        "kActorControlBrainActionCooldownTicksOffset",
        "kActorControlBrainActionBurstTicksOffset",
        "kActorControlBrainHeadingLockTicksOffset",
        "kActorControlBrainMoveInputXOffset",
        "kActorControlBrainMoveInputYOffset",
    ):
        assert token in cast_clear_body, (
            "takeover actor handback lacks " + token
        )

    target_write_start = control.index(
        "bool ApplyManualSpawnerPrimaryTargetState("
    )
    target_write_end = control.index(
        "bool IsPlayerActorPublishedInCurrentGameplaySlot(",
        target_write_start,
    )
    target_write_body = control[target_write_start:target_write_end]
    target_native_offsets = set(re.findall(
        r"kActor[A-Za-z0-9]+Offset",
        target_write_body,
    ))
    target_read_only_offsets = {
        "kActorPositionXOffset",
        "kActorPositionYOffset",
    }
    handback_native_offsets = set(re.findall(
        r"kActor[A-Za-z0-9]+Offset",
        cast_clear_body,
    ))
    assert (
        target_native_offsets - target_read_only_offsets
    ) <= handback_native_offsets, (
        "takeover target writes without handback coverage: " +
        repr(sorted(
            target_native_offsets -
            target_read_only_offsets -
            handback_native_offsets
        ))
    )

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
    assert control.count(
        "TryWriteActorAnimationStateIdDirect("
    ) == 2
    _require_in_order(
        control,
        "bool TryWriteTrackedLocalPlayerTakeoverPrimarySelection(",
        "local_player_takeover_primary_selection_before",
        "TryWriteActorAnimationStateIdDirect(",
        "bool RestoreLocalPlayerControlTakeoverPrimarySelection(",
        "TryWriteActorAnimationStateIdDirect(",
        "bool ApplyLocalPlayerControlTakeoverPrimarySelection(",
        "TryResolveLocalPlayerPrimaryCastDescriptor(",
        "TryWriteTrackedLocalPlayerTakeoverPrimarySelection(",
        "void __fastcall HookPurePrimarySpellStart(",
        "ApplyLocalPlayerControlTakeoverPrimarySelection(actor_address);",
        "TryListPurePrimaryProjectileActorAddressesInScene(",
        "original(self);",
        "TryFindNewPurePrimaryProjectileActorInScene(",
        "QueueLocalPlayerPrimaryCastForMultiplayer(actor_address);",
    )
    apply_start = control.index(
        "bool ApplyLocalPlayerControlTakeoverPrimarySelection("
    )
    apply_end = control.index(
        "bool QueueLocalPlayerPrimaryCastForMultiplayer(",
        apply_start,
    )
    apply_body = control[apply_start:apply_end]
    assert "TryWriteActorAnimationStateIdDirect(" not in apply_body
    assert apply_body.count(
        "TryWriteTrackedLocalPlayerTakeoverPrimarySelection("
    ) == 1
    restore_start = control.index(
        "bool RestoreLocalPlayerControlTakeoverPrimarySelection("
    )
    restore_end = apply_start
    restore_body = control[restore_start:restore_end]
    for token in (
        "local_player_takeover_primary_selection_snapshot_pending",
        "local_player_takeover_primary_selection_actor",
        "local_player_takeover_primary_selection_before",
        "local_player_takeover_primary_selection_restore_succeeded",
        "TryWriteActorAnimationStateIdDirect(",
        "ResolveActorAnimationStateId(snapshot_actor) == snapshot_state",
    ):
        assert token in restore_body, (
            "takeover primary-selection handback lacks " + token
        )
    _require_in_order(
        input_api,
        "bool ApplyPinnedLocalPlayerControlTakeoverTarget(",
        "ApplyLocalPlayerControlTakeoverPrimarySelection(",
        "ApplyManualSpawnerPrimaryTargetState(",
    )
    assert (
        '"Multiplayer local pure-primary cast not queued: stock emitted no '
        'matching projectile. actor="'
    ) in control
    _require_in_order(
        control,
        "original(self, param2, param3);",
        "if (local_player_takeover_active ||",
        "local_player_takeover_primary_cast_active",
        "(void)write_vector2(param2, native_move_x, native_move_y);",
        "float raw_move_x_after = 0.0f;",
    )
    assert "local_player_takeover_requested" in control
    assert "current_actor_matches_local_player" in control
    assert "(void)write_vector2(param3, control_x, control_y);" in control
    assert (
        "selection_pointer +\n"
        "                    kActorControlBrainMoveInputXOffset"
    ) in control
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
        '"primary_selection_snapshot_pending"',
        '"primary_selection_restore_succeeded"',
        '"native_state_clear_succeeded"',
        '"last_primary_selection_restored_state"',
    ):
        assert token in binding, f"Lua takeover binding lacks {token}"
    assert "GetLoadedLuaMod(state)" in binding
    assert "mod->descriptor.id" in binding
    assert "ClearLocalPlayerControlTakeoverForMod(mod->descriptor.id)" in close

    return (
        "The owner-scoped local-player takeover uses the slot-zero stock "
        "control path, primes its native primary, proves projectile emission, "
        "and clears every queued control on release"
    )


def test_bot_play_for_me_reuses_one_brain_and_owner_control_rails() -> str:
    import json

    manifest = json.loads(_read("mods/bot-brain/manifest.json"))
    main = _read("mods/bot-brain/scripts/main.lua")
    local_player = _read("mods/bot-brain/scripts/local_player.lua")
    brain = _read("mods/bot-brain/scripts/brain.lua")
    steering = _read("mods/bot-brain/scripts/steering.lua")
    observation = _read(
        "mods/bot-brain/scripts/policy_observation.lua"
    )
    lua_contract = _read(
        "tests/lua/bot_play_for_me_contract.lua"
    )

    assert manifest["id"] == "bot.brain"
    assert manifest["version"] == "1.2.0"
    assert manifest["minimumLoaderVersion"] == "0.1.0-beta.29"
    capabilities = set(
        manifest["runtime"]["requiredCapabilities"]
    )
    assert {
        "input.local_player.takeover",
        "draw.local.immediate",
        "draw.text",
        "draw.primitives",
    } <= capabilities
    settings = {
        entry["key"]: entry
        for entry in manifest["settings"]["entries"]
    }
    assert settings["play_for_me"]["default"] is False
    assert settings["play_for_me"]["scope"] == "local"
    assert settings["play_for_me_toggle"]["default"] == "F9"
    assert settings["play_for_me_toggle"]["scope"] == "local"
    behavior_values = {
        choice["value"]
        for choice in settings["play_for_me_behavior"]["choices"]
    }
    assert behavior_values == {
        "skirmisher",
        "guardian",
        "striker",
        "learned",
    }

    _require_in_order(
        main,
        'require_mod("scripts/brain.lua")',
        'require_mod("scripts/local_player.lua")',
        "local_player.new(",
        "local_controller:tick(now_ms, event)",
        "manager:poll_skill_choices(authority)",
        "if now_ms - state.last_tick_ms <",
    )
    assert "local_controller:set_desired(" in main
    assert "local_controller:set_behavior(" in main
    assert "local_controller:reset_run(false)" in main

    for token in (
        "self.brain.new(",
        "self.brain.think(",
        "self.brain.reset_run(",
        "sd.input.set_local_player_takeover",
        "sd.input.set_local_player_takeover_target",
        "sd.input.hold_movement_frames",
        "sd.input.hold_mouse_left_frames",
        "LOCAL_PRIMARY_HOLD_FRAMES = 3",
        "sd.input.press_binding",
        "sd.runtime.choose_level_up_option",
        "sd.world.request_loot_pickup(network_drop_id)",
        'sd.draw.text("BOT PLAYING  [F9]"',
    ):
        assert token in local_player, f"local adapter lacks {token}"
    assert "PROFILES" not in local_player
    assert "kite_direction" not in local_player
    assert "flee_threshold" not in local_player
    _require_in_order(
        local_player,
        "function Controller:tick(now_ms, event)",
        "self:update_runtime_state()",
        "self.brain.poll_skill_choice(self.context)",
        "self:can_drive(participant)",
    )
    assert "function Handle:mp()" in local_player
    assert "function Handle:max_mp()" in local_player
    assert "function Manager:poll_skill_choices(authority)" in _read(
        "mods/bot-brain/scripts/roster.lua"
    )

    assert "context.read_skill_choices" in brain
    assert "context.choose_skill" in brain
    assert "context.request_loot_pickup" in brain
    assert "brain.poll_skill_choice" in brain
    assert "math.random(1, #choices.options)" in brain
    assert "CAST_MANA_HOLD_LOW_RATIO = 0.10" in brain
    assert "CAST_MANA_RESUME_HIGH_RATIO = 0.80" in brain
    assert "mana hold-start participant_id=" in brain
    assert "mana hold-end participant_id=" in brain
    assert "context.mana_cast_hold" in brain
    assert "context.bot:mp(), context.bot:max_mp()" in brain
    assert "excluded_participant_id" in brain
    assert "context.shared.cast_hold_ms,\n      target)" in brain
    assert "actor_address" not in steering
    assert "actor_address" not in observation
    assert "sd.world.get_run_enemy_by_network_id" in local_player
    assert "sd.world.list_actors" in local_player
    assert "nearest_distance_squared" in local_player

    for token in (
        "assert(controller.debug.release_clean)",
        "assert(input_state.pending_movement_frames == 0)",
        "assert(input_state.pending_mouse_left_frames == 0)",
        "assert(input_state.pending_scancode_count == 0)",
        "assert(input_state.target_actor_address == 0)",
        "assert(not input_state.primary_selection_snapshot_pending)",
        "assert(input_state.primary_selection_restore_succeeded)",
        "spectator_active = true",
        "assert(controller.debug.activation_count == 3)",
    ):
        assert token in lua_contract

    return (
        "Bot Play For Me adapts the existing bot brain to owner-local stock "
        "controls, auto-levels and picks up through existing owner rails, "
        "and proves clean death, respawn, and toggle release"
    )
