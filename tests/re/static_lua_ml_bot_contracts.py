"""Static contracts for the player-usable learned Lua bot."""

from __future__ import annotations

import json

from static_multiplayer_contract_support import _read, _require_in_order


def test_ml_bot_v2_native_loadout_schema_is_semantic_and_complete() -> str:
    header = _read(
        "SolomonDarkModLoader/include/bot_runtime.h"
    )
    binding = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_bots.cpp"
    )
    api = _read(
        "SolomonDarkModLoader/src/bot_runtime/public_api/"
        "loadout_details_api.inl"
    )

    for token in (
        "struct BotPrimaryLoadoutDetails",
        "entry_id",
        "combo_entry_id",
        "build_id_resolved",
        "mana_cost_resolved",
        "mana_charge_kind",
        "range_resolved",
        "range_source",
        "struct BotSecondaryLoadoutDetails",
        "cooldown_seconds",
        "cooldown_remaining_seconds",
        "cooldown_resolved",
        "pending_weld_build_id_resolved",
        "kSecondaryLoadoutSlotCount> secondaries",
    ):
        assert token in header, (
            f"ML v2 native loadout record lacks {token}"
        )
    for field in (
        "participant_id",
        "primary",
        "secondaries",
        "entry_id",
        "combo_entry_id",
        "build_id",
        "build_id_resolved",
        "mana_cost",
        "mana_cost_resolved",
        "mana_charge_kind",
        "range_min",
        "range_max",
        "range_resolved",
        "range_source",
        "slot",
        "cooldown_seconds",
        "cooldown_remaining_seconds",
        "cooldown_resolved",
        "pending_weld_build_id",
        "pending_weld_build_id_resolved",
    ):
        assert f'"{field}"' in binding, (
            f"sd.bots.get_loadout_details omits {field}"
        )

    assert "details.secondaries.size()" in binding
    assert "OverlayLiveSecondaryCooldowns(" in api
    assert "FindPendingSkillChoiceConst(" in api
    assert (
        "ReadParticipantLoadoutDetails(\n"
        "            bot_id,"
    ) in binding

    return (
        "The v2 ML seam publishes one fixed, semantic loadout schema with "
        "explicit resolution for primary, eight secondaries, and pending weld"
    )


def test_ml_bot_is_simulation_timed_local_and_native_action_routed() -> str:
    manifest = json.loads(_read("mods/bot-brain/manifest.json"))
    model = json.loads(_read("models/bot-brain/policy-v1.json"))
    runtime_tick = _read("SolomonDarkModLoader/include/runtime_tick_service.h")
    tick_state = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "runtime_request_state.inl"
    )
    tick_hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/player_actor_tick_hook.inl"
    )
    main = _read("mods/bot-brain/scripts/main.lua")
    roster = _read("mods/bot-brain/scripts/roster.lua")
    brain = _read("mods/bot-brain/scripts/brain.lua")
    policy = _read("mods/bot-brain/scripts/policy.lua")
    policy_spec = _read("mods/bot-brain/scripts/policy_spec.lua")
    observation = _read(
        "mods/bot-brain/scripts/policy_observation.lua"
    )
    training = _read("mods/bot-brain/scripts/policy_training.lua")
    solo_launcher = _read("scripts/Launch-LocalSoloSession.ps1")
    gameplay_bindings = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )
    run_lifecycle_api = _read(
        "SolomonDarkModLoader/src/run_lifecycle/"
        "public_api_and_install.inl"
    )
    manual_enemy_spawning = _read(
        "SolomonDarkModLoader/src/run_lifecycle/run_and_enemy_hooks/"
        "manual_enemy_spawning.inl"
    )
    gameplay_pump = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_pump_loop.inl"
    )
    trainer = _read("tools/train_bot_policy.py")
    bridge = _read("tools/ml_bot/bridge.py")

    assert manifest["version"] == "1.1.0"
    learned = next(
        choice
        for entry in manifest["settings"]["entries"]
        if entry["key"] == "roster"
        for field in entry["item"]["fields"]
        if field["key"] == "behavior"
        for choice in field["choices"]
        if choice["value"] == "learned"
    )
    assert learned["label"] == "Learned — ML movement and casting"
    assert "no Python, GPU, or network service" in manifest["description"]

    assert model["format"] == "solomon-dark-bot-policy"
    assert model["version"] == 1
    assert model["observation_version"] == 1
    assert model["architecture"] == "mlp-tanh-two-head-v1"
    assert model["hidden_size"] == 48
    assert model["observation_size"] == 87
    assert model["movement_action_size"] == 9
    assert model["cast_action_size"] == 10
    assert len(model["observation_names"]) == model["observation_size"]
    assert len(model["movement_action_names"]) == 9
    assert len(model["cast_action_names"]) == 10

    assert "kGameplaySimulationTickIntervalMs = 10" in runtime_tick
    assert "local_player_simulation_tick_count" in tick_state
    _require_in_order(
        tick_hook,
        "const auto simulation_tick_count = "
        "PublishLocalPlayerTickOwnership(",
        "kGameplaySimulationTickIntervalMs,",
        "simulation_tick_count,",
        "PumpLuaWorkOnGameplayThread(lua_tick_context)",
    )

    for script in (
        "policy_spec.lua",
        "policy_weights.lua",
        "policy.lua",
        "policy_observation.lua",
        "policy_training.lua",
    ):
        assert f'require_mod("scripts/{script}")' in main
    for token in (
        "policy_interval_ms = 100",
        "manager_interval_ms = 100",
        "(tick_count - state.last_simulation_tick_count) *",
        "tick_interval_ms",
        'debug.clock_source = "simulation"',
        "policy_training:begin_episode()",
    ):
        assert token in main, f"learned bot clock lacks: {token}"
    for token in (
        "function Manager:tick(now_ms, authority, simulation_tick)",
        "simulation_tick)",
    ):
        assert token in roster, f"roster tick forwarding lacks: {token}"

    _require_in_order(
        brain,
        "choose_pending_skill(context)",
        'if context.row.behavior == "learned" then',
        "think_with_policy(",
    )
    for token in (
        'learned = {',
        "shared.policy_observation.capture(",
        "shared.policy_runtime:forward(",
        "context.bot:move_to(target.x, target.y)",
        "context.bot:stop()",
        "context.bot:cast(",
        "action.skill_slot,",
        "shared.policy_training:record(",
    ):
        assert token in brain, f"learned native action route lacks: {token}"

    for token in (
        "validate_weights",
        "masked_softmax",
        "movement_action = movement_index - 1",
        "cast_action = cast_index - 1",
        "math.log(movement_probability)",
        "function Runtime:load(candidate)",
    ):
        assert token in policy, f"Lua inference lacks: {token}"
    for token in (
        '"inventory_distinct_scaled"',
        '"potion_stack_scaled"',
        '"hat_equipped"',
        '"robe_equipped"',
        '"weapon_equipped"',
        '"ring_count_scaled"',
        '"amulet_equipped"',
        '"secondary_8_available"',
        '"previous_cast_secondary"',
    ):
        assert token in policy_spec, f"policy contract lacks: {token}"
    for token in (
        "participant.owned_progression",
        "owned.inventory_items",
        "owned.equipment",
        "owned.progression_book_entries",
        "owned.ability_loadout",
        "owned.derived_stats",
        "movement_mask",
        "cast_mask",
        "sd.nav.test_segment",
        "snapshot.cast_ready",
    ):
        assert token in observation, f"observation/masking lacks: {token}"

    _require_in_order(
        training,
        "self:finish_pending(context, capture.metrics, false)",
        "context.policy_pending = {",
    )
    for token in (
        "local function copy_metrics(value)",
        "trajectory_version = self.spec.trajectory_version",
        "old_log_probability = decision.log_probability",
        "old_value = decision.value",
        "function Controller:drain(max_records)",
        "function Controller:load_parameters(candidate)",
    ):
        assert token in training, f"trajectory bridge lacks: {token}"

    assert "[switch]$Headless" in solo_launcher
    assert "[switch]$DisableMultiplayerTransport" in solo_launcher
    assert '$arguments += "--headless"' in solo_launcher
    assert '"--multiplayer", "off"' not in solo_launcher
    for token in (
        "register_owned_launch",
        "stop_owned_process_ids",
        "MAX_ROLLOUTS_PER_RESPONSE = 256",
        "RUN_READY_STABILITY_SECONDS = 0.35",
        "def drain_rollouts(",
        "def load_policy(",
        "def enable_training(",
        "def wait_for_run_ready(",
        "def wait_for_bot_materialized(",
        "def prime_training_progression(",
        "def start_training_arena(",
        "def wait_for_training_enemy(",
        "sd.__settings_invoke_action(",
        "def write_empty_roster(",
        "def wait_for_empty_roster(",
        '"-DisableMultiplayerTransport"',
        "def prepare_training_combat(",
        "recover_untracked_wave = true",
        "allow_direct_arena_spawn = true",
        "sd.world.list_actors()",
        "sd.gameplay.set_manual_enemy_spawner_test_mode(true)",
        'last.get("session_state") == "in-boneyard"',
        'last.get("session_state") == "not-in-game"',
        'last.get("loading_released") == "true"',
        'last.get("loading_released") == "false"',
        "if transport_enabled",
    ):
        assert token in bridge, f"live session bridge lacks: {token}"
    assert "PinRunLifecycleManualEnemyTestState();" in gameplay_pump
    for workflow in (trainer, _read("tools/verify_ml_bot_live.py")):
        _require_in_order(
            workflow,
            "session.write_empty_roster(",
            "session.start_test_run(",
            "session.prepare_training_combat(",
            "session.write_learned_roster(",
            "session.wait_for_run_ready(",
            "session.wait_for_bot_materialized(",
            "session.prime_training_progression(",
            "session.start_training_arena(",
            "session.wait_for_training_enemy(",
        )
    _require_in_order(
        brain,
        "pcall(sd.world.get_replicated_actors)",
        "pcall(sd.world.list_actors)",
        "context.steering.live_enemies(",
    )
    assert '"allow_direct_arena_spawn"' in gameplay_bindings
    for token in (
        "allow_direct_arena_spawn && !manual_test_mode",
        "TryDispatchDirectManualRunEnemySpawnWithoutSpawner()",
    ):
        assert token in run_lifecycle_api
    for token in (
        "queued.allow_direct_arena_spawn",
        "manual_enemy_spawner_test_mode.load",
        "multiplayer::IsLuaModSimulationAuthority()",
        "direct arena spawn requires simulation authority.",
        "DispatchExactRunEnemySpawn(request, 0)",
    ):
        assert token in manual_enemy_spawning
    for token in (
        'subparsers.add_parser(\n        "live-ppo"',
        "prepare_rollout_batch(",
        "generalized_advantage_estimate(",
        "ppo_epochs(",
        "_atomic_checkpoint(",
        "session.load_policy(policy)",
        '"learned policy had no accepted live movement"',
        '"learned policy had no accepted live attacks"',
    ):
        assert token in trainer, f"live PPO workflow lacks: {token}"
    for token in (
        "MINIMUM_LIVE_DISPLACEMENT = 1.0",
        "MINIMUM_ACCEPTANCE_TICKS = 25",
        "maximum_distance >= MINIMUM_LIVE_DISPLACEMENT",
        "tick - first_tick >= MINIMUM_ACCEPTANCE_TICKS",
    ):
        assert token in _read("tools/verify_ml_bot_live.py"), (
            f"live movement proof lacks: {token}"
        )

    return (
        "The learned bot uses the real 10 ms simulation counter, observes "
        "combat/loadout state, masks semantic actions, drives native bot "
        "movement and casts, and trains through an exact-process bridge"
    )
