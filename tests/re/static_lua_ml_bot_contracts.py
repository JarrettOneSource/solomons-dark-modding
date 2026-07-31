"""Static contracts for the player-usable learned Lua bot."""

from __future__ import annotations

import json

from static_multiplayer_contract_support import _read, _require_in_order


def test_ml_bot_v2_native_loadout_schema_is_semantic_and_complete() -> str:
    header = _read("SolomonDarkModLoader/include/bot_runtime.h")
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
        assert token in header, f"ML v2 native loadout record lacks {token}"
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
        "The v2 ML seam publishes one semantic loadout schema with explicit "
        "resolution for primary, eight secondaries, and pending weld"
    )


def test_ml_bot_phase3_observation_masks_and_assists_are_pinned() -> str:
    manifest = json.loads(_read("mods/bot-brain/manifest.json"))
    spec = _read("mods/bot-brain/scripts/policy_spec.lua")
    geometry = _read(
        "mods/bot-brain/scripts/policy_geometry.lua"
    )
    descriptors = _read(
        "mods/bot-brain/scripts/policy_spell_descriptors.lua"
    )
    observation = _read(
        "mods/bot-brain/scripts/policy_observation.lua"
    )
    brain = _read("mods/bot-brain/scripts/brain.lua")
    main = _read("mods/bot-brain/scripts/main.lua")
    training = _read(
        "mods/bot-brain/scripts/policy_training.lua"
    )
    fixture = _read(
        "tests/lua/ml_bot_policy_v2_phase3.lua"
    )

    assert manifest["version"] == "1.2.0"
    capabilities = set(
        manifest["runtime"]["requiredCapabilities"]
    )
    assert {
        "state.replicated.read",
        "state.replicated.write",
        "nav.read",
        "spells.read",
        "bots.state.read",
        "bots.move",
        "bots.stop",
        "bots.cast",
    } <= capabilities
    settings = {
        entry["key"]: entry
        for entry in manifest["settings"]["entries"]
    }
    weld = settings["policy_weld_preference"]
    assert weld["default"] == "auto"
    assert {
        choice["value"] for choice in weld["choices"]
    } == {"prefer", "avoid", "auto"}
    # The loader's current list-schema ceiling is configuration, not a Lua
    # participant-count assumption.
    assert settings["roster"]["max_items"] == 32

    for token in (
        "model_version = 2",
        "observation_version = 2",
        "trajectory_version = 2",
        'architecture = "mlp-tanh-three-head-v2"',
        "hidden_sizes = {192, 96}",
        "#observation_names == 395",
        "secondary_slot_count = 8",
        "enemy_slot_count = 8",
        "pickup_slot_count = 4",
        "ally_slot_count = 4",
        "mana_scale = 2000.0",
        "hp_scale = 1000.0",
        "velocity_scale = 1000.0",
        "cooldown_scale = 60.0",
        '"keep_current"',
        '"enemy_8"',
        '"secondary_8"',
        '"ally_count_scaled"',
        '"secondary_recharge_multiplier_scaled"',
    ):
        assert token in spec, f"phase-3 policy spec lacks {token}"

    assert "sd.nav.test_segment" not in geometry
    assert "grid.refresh_pending == false" in geometry
    assert "self.spec.nav_refresh_ms" in geometry
    assert "self.spec.nav_subdivisions" in geometry
    assert "self.grid_build_count = self.grid_build_count + 1" in geometry
    assert "function Cache:walkable_at(world_x, world_y)" in geometry
    assert "function Cache:features(world_x, world_y)" in geometry
    assert "sd.nav.get_grid(subdivisions)" in geometry

    for token in (
        "sd.bots.get_loadout_details",
        "sd.bots.get_skill_choices",
        "sd.spells.list",
        "WELD_PAIRS",
        "pending_weld_build_id_resolved",
        "mana_cost_resolved",
        "cooldown_resolved",
        "range_resolved",
        "snapshot.cast_ready == true",
        "entry.entry_index",
        "entry_id == 52",
    ):
        assert token in descriptors, (
            f"phase-3 spell descriptors lack {token}"
        )

    _require_in_order(
        observation,
        "-- Block A: self.",
        "-- Block B: active primary.",
        "-- Block C: secondary slots.",
        "-- Block D: nearest enemies.",
        "-- Block E: persisted selected target.",
        "-- Block F: cached local geometry.",
        "-- Block G: replicated loot.",
        "-- Block I: nearest in-run participants other than self.",
        "-- Block H: aggregates, config, history, weld, and multipliers.",
    )
    for token in (
        "builder.geometry:refresh(now_ms, frame.scene_key)",
        "memory.enemy_position_history[actor_id]",
        "memory.target_actor_id",
        "participant.in_run == true",
        '"Native"',
        "participant.movement_intent_x",
        "participant.movement_intent_y",
        "resource_kind == 0",
        "resource_kind == 1",
        "function observation.select_target(",
        "function observation.build_cast_mask(",
        "capture.target_mask[mask_index] ~= true",
        "primary.range_resolved ~= true or",
        "secondary.range_resolved ~= true or",
        "secondary.affordable == true",
        "secondary.ready == true",
        "builder.test_segment",
    ):
        assert token in observation, (
            f"phase-3 observation contract lacks {token}"
        )
    assert "for _, participant in ipairs(multiplayer.participants or {})" in (
        observation
    )
    for forbidden in (
        "participant_count <= 4",
        "participant_count < 4",
        "math.min(#multiplayer.participants, 4)",
    ):
        assert forbidden not in observation

    _require_in_order(
        brain,
        "shared.policy_observation.capture(",
        "shared.policy_runtime:forward(",
        "capture.target_mask,",
        "shared.policy_observation.select_target(",
        "shared.policy_observation.build_cast_mask(",
        "issue_policy_cast(",
    )
    for token in (
        "details.pending_weld_build_id_resolved ~= true",
        'preference == "avoid"',
        'preference == "prefer"',
        'preference == "auto"',
        "learned[components[1]] ~= true",
        "request_nearby_pickup(",
        "capture.loadout.pickup_range <= 0.0",
        "pickup.pickup_range_multiplier",
        "sd.world.request_loot_pickup",
        "selected_target",
        "enemies = all_enemies",
    ):
        assert token in brain, f"phase-3 brain lacks {token}"

    for script in (
        "policy_geometry.lua",
        "policy_spell_descriptors.lua",
        "policy_observation.lua",
        "policy_training.lua",
    ):
        assert f'"scripts/{script}"' in main
    assert "policy_module.new(policy_spec, policy_weights, 20260729)" in main
    assert "policy_runtime_unavailable_reason" not in main
    assert "weights are unavailable until Phase 4" not in main
    assert "policy_geometry:reset(nil)" in main

    _require_in_order(
        training,
        "self:finish_pending(context, capture.metrics, false)",
        "context.policy_pending = {",
    )
    for token in (
        "trajectory_version = self.spec.trajectory_version",
        "target_mask = copy_mask(capture.target_mask)",
        "target_action = decision.target_action",
        "cast_mask = copy_mask(capture.cast_mask)",
        "old_log_probability = decision.log_probability",
        "old_value = decision.value",
    ):
        assert token in training, (
            f"trajectory v2 writer lacks {token}"
        )
    # Reward coefficients stay byte-for-byte represented as the audited v1
    # formula; Phase 3 adds no target-shaped term.
    for token in (
        "local reward = 0.002",
        "reward = reward + hp_delta * 1.25",
        "(previous_ratio - current_ratio) * 0.65",
        "math.min(wave_delta, 1) * 1.5",
        "reward = reward - 2.0",
        "math.max(-4.0, math.min(4.0, reward))",
    ):
        assert token in training
    assert "target" not in training[
        training.index("function Controller:reward("):
        training.index("function Controller:finish_pending(")
    ]

    for token in (
        "observation_count=395",
        "exact_order=true",
        "target_conditioned_masks=true",
        "actor_id_persistence=true",
        "ally_transition=true",
        "weld_transition=true",
        "pickup_transition=true",
        "guardian_far_return=true",
        "nav_grid_builds=",
        "trajectory_v2=true",
    ):
        assert token in fixture
    return (
        "Phase 3 pins 395 ordered observations, cached geometry, dynamic "
        "spell descriptors, actor-ID targeting, allies, assists, and "
        "trajectory v2 without changing the reward"
    )


def test_ml_bot_is_simulation_timed_local_and_native_action_routed() -> str:
    manifest = json.loads(_read("mods/bot-brain/manifest.json"))
    model = json.loads(_read("models/bot-brain/policy-v2.json"))
    historical_v1 = json.loads(
        _read("models/bot-brain/policy-v1.json")
    )
    runtime_tick = _read(
        "SolomonDarkModLoader/include/runtime_tick_service.h"
    )
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
    python_spec = _read("tools/ml_bot/spec.py")
    python_model = _read("tools/ml_bot/model.py")
    expert = _read("tools/ml_bot/expert.py")
    weights = _read("mods/bot-brain/scripts/policy_weights.lua")

    assert manifest["version"] == "1.2.0"
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
    assert model["version"] == 2
    assert model["observation_version"] == 2
    assert model["architecture"] == "mlp-tanh-three-head-v2"
    assert model["hidden_sizes"] == [192, 96]
    assert model["observation_size"] == 395
    assert model["movement_action_size"] == 9
    assert model["target_action_size"] == 9
    assert model["cast_action_size"] == 10
    assert model["value_size"] == 1
    assert len(model["observation_names"]) == model["observation_size"]
    assert len(model["movement_action_names"]) == 9
    assert len(model["target_action_names"]) == 9
    assert len(model["cast_action_names"]) == 10
    assert set(model["parameters"]) == {
        "input_weight",
        "input_bias",
        "hidden_weight",
        "hidden_bias",
        "movement_weight",
        "movement_bias",
        "target_weight",
        "target_bias",
        "cast_weight",
        "cast_bias",
        "value_weight",
        "value_bias",
    }
    assert historical_v1["version"] == 1
    assert historical_v1["architecture"] == "mlp-tanh-two-head-v1"
    for token in (
        "MODEL_VERSION = 2",
        "OBSERVATION_VERSION = 2",
        "TRAJECTORY_VERSION = 2",
        'ARCHITECTURE = "mlp-tanh-three-head-v2"',
        "HIDDEN_SIZES = (192, 96)",
        "if len(names) != 395:",
        "TARGET_ACTION_NAMES = (",
        "MOVEMENT_ENTROPY_COEFFICIENT = 0.01",
        "TARGET_ENTROPY_COEFFICIENT = 0.02",
        "CAST_ENTROPY_COEFFICIENT = 0.01",
        "policy v1 artifacts are incompatible",
    ):
        assert token in python_spec
    for token in (
        "class ForwardPass:",
        "first_hidden: Array",
        "second_hidden: Array",
        "target_probabilities: Array",
        "target_actions: Array",
        '"hidden_weight": self.hidden_weight',
        '"target_weight": self.target_weight',
        "movement_log + target_log + cast_log",
        "movement_entropy_coefficient",
        "target_entropy_coefficient",
        "cast_entropy_coefficient",
    ):
        assert token in python_model
    for token in (
        "class ExpertDataset:",
        "target_masks: Array",
        "target_actions: Array",
        "def _choose_target(",
        "target_action, selected = _choose_target(",
        "prevents v1 wrapper-selected target supervision",
        "selected=selected,",
    ):
        assert token in expert
    for token in (
        '["version"] = 2',
        '["observation_version"] = 2',
        '["architecture"] = "mlp-tanh-three-head-v2"',
        '["hidden_sizes"] = { 192, 96 }',
        '["target_action_size"] = 9',
        '["hidden_weight"] =',
        '["target_weight"] =',
    ):
        assert token in weights

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
    for token in (
        "policy_interval_ms = 100",
        "manager_interval_ms = 100",
        "(tick_count - state.last_simulation_tick_count) *",
        "tick_interval_ms",
        'debug.clock_source = "simulation"',
        "policy_training:begin_episode()",
    ):
        assert token in main
    for script in (
        "policy_spec.lua",
        "policy_weights.lua",
        "policy.lua",
        "policy_observation.lua",
        "policy_training.lua",
    ):
        assert f'require_mod("scripts/{script}")' in main
    for token in (
        "function Manager:tick(now_ms, authority, simulation_tick)",
        "simulation_tick)",
    ):
        assert token in roster

    _require_in_order(
        brain,
        "choose_pending_skill(context, skill_choices)",
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
        "sd.bots.choose_skill",
        "sd.world.request_loot_pickup",
        "shared.policy_training:record(",
    ):
        assert token in brain

    for token in (
        "validate_weights",
        "masked_softmax",
        "parameters.hidden_weight",
        "movement_action = movement_index - 1",
        "target_action = target_index - 1",
        "cast_action = cast_index - 1",
        "math.log(movement_probability)",
        "math.log(target_probability)",
        "cast_mask_builder(target_index - 1)",
        "policy v1 artifacts are incompatible",
        "function Runtime:load(candidate)",
    ):
        assert token in policy
    for token in (
        "local function copy_metrics(value)",
        "trajectory_version = self.spec.trajectory_version",
        "old_log_probability = decision.log_probability",
        "old_value = decision.value",
        "function Controller:drain(max_records)",
        "function Controller:load_parameters(candidate)",
    ):
        assert token in training

    assert "[switch]$Headless" in solo_launcher
    assert "[switch]$DisableMultiplayerTransport" in solo_launcher
    assert '$arguments += "--headless"' in solo_launcher
    assert '"--multiplayer", "off"' not in solo_launcher
    for token in (
        "register_owned_launch",
        "stop_owned_process_ids",
        "MAX_ROLLOUTS_PER_RESPONSE = 256",
        "POLICY_LOAD_CHUNK_BYTES = 512 * 1024",
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
        "target_mask: list[bool]",
        "target_action: int",
        "if len(fields) != 16:",
        "trajectory-v1 frames are incompatible",
        "record.target_mask",
        "record.target_action",
        "__sdmod_ml_policy_staging",
        "policy staging request exceeds the loader pipe limit",
        "load_parameters(candidate)",
    ):
        assert token in bridge
    assert "PinRunLifecycleManualEnemyTestState();" in gameplay_pump
    _require_in_order(
        trainer,
        "session.write_empty_roster(",
        "session.set_run_seed(",
        "session.start_test_run(",
        "session.prepare_training_combat(",
        "session.write_composition(",
        "session.wait_for_run_ready(",
        "session.wait_for_bot_materialized(",
        "session.prime_learned_progression(",
        "session.start_training_arena(",
        "session.wait_for_training_enemy(",
    )
    verifier = _read("tools/verify_ml_bot_live.py").split(
        "def verify(", 1
    )[1]
    _require_in_order(
        verifier,
        "session.write_empty_roster(",
        "session.set_run_seed(",
        "session.start_test_run(",
        "session.prepare_training_combat(",
        "session.write_composition(",
        "session.wait_for_run_ready(",
        "session.wait_for_bot_materialized(",
        "session.prime_learned_progression(",
        "_apply_one_weld(",
        "_spawn_enemy(",
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
        "batch[\"target_masks\"]",
        "batch[\"target_actions\"]",
        "movement_entropy_coefficient",
        "target_entropy_coefficient",
        "cast_entropy_coefficient",
        "_atomic_checkpoint(",
        "session.load_policy(policy)",
        '"learned policy did not make live movement decisions"',
        '"live trajectory buffer dropped records"',
    ):
        assert token in trainer
    for token in (
        "MINIMUM_LIVE_DISPLACEMENT = 1.0",
        "displacement < MINIMUM_LIVE_DISPLACEMENT",
        "request_distance > pickup_range",
        "last_pickup_request_distance",
    ):
        assert token in _read("tools/verify_ml_bot_live.py")

    return (
        "The bot keeps its simulation clock, strict v2 runtime, native action "
        "routing, historical-v1 rejection, and exact-process training bridge"
    )


def test_ml_bot_phase5_rotation_and_live_acceptance_are_pinned() -> str:
    bridge = _read("tools/ml_bot/bridge.py")
    compositions = _read("tools/ml_bot/compositions.py")
    composition_config = json.loads(
        _read("tools/ml_bot/team-compositions.json")
    )
    trainer = _read("tools/train_bot_policy.py")
    live = _read("tools/verify_ml_bot_live.py")
    scripted = _read("tools/verify_lua_bot_brain.py")
    launcher = _read("scripts/Launch-LocalSoloSession.ps1")
    brain = _read("mods/bot-brain/scripts/brain.lua")
    binding = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )
    transport_header = _read(
        "SolomonDarkModLoader/include/multiplayer_local_transport.h"
    )
    pickup_queue = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "public_cast_loot_queue_api.inl"
    )
    pickup_handler = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "loot_pickup_packet_handlers.inl"
    )
    pickup_authority = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "loot_pickup_authority.inl"
    )

    configured = composition_config["compositions"]
    assert composition_config["schema_version"] == 1
    assert any(row["learned_count"] == 1 and not row["scripted_behaviors"]
               for row in configured)
    assert any(row["learned_count"] == 1 and row["scripted_behaviors"]
               for row in configured)
    assert any(row["learned_count"] > 1 and not row["scripted_behaviors"]
               for row in configured)
    assert {
        behavior
        for row in configured
        for behavior in row["scripted_behaviors"]
    } == {"skirmisher", "guardian", "striker"}
    for token in (
        "class TeamComposition:",
        "def load_compositions(",
        "def select_compositions(",
        "def build_roster(",
        "range(1, composition.learned_count + 1)",
    ):
        assert token in compositions
    for forbidden in (
        "MAX_PARTICIPANTS",
        "maximum_participants",
        "min(composition.learned_count",
    ):
        assert forbidden not in compositions

    for token in (
        "def set_run_seed(self, seed: int)",
        "sd.rng.set_seed(requested)",
        "sd.rng.get_seed()",
        "run seed did not round-trip exactly",
        "def get_run_identity(self)",
        "participant.run_nonce",
        "def write_composition(",
        "def learned_participant_ids(",
        "def prime_learned_progression(",
        "self.layout_sha256()",
        '"-TestSurvivalBoneyardOverride"',
        '"-MaxParticipants"',
        "str(self.max_participants)",
    ):
        assert token in bridge, f"Phase-5 bridge lacks {token}"
    assert "slot <= 3" not in bridge

    _require_in_order(
        trainer,
        "for iteration in range(1, args.iterations + 1):",
        "session = SoloSession(",
        "session.set_run_seed(requested_seed)",
        "session.write_composition(composition)",
        "partition_rollout_records(",
        "ppo_epochs(",
        "_atomic_checkpoint(",
        "session.load_policy(policy)",
        "session.close()",
    )
    for token in (
        '"requested_seed": requested_seed',
        '"observed_run_nonce": run_identity["run_nonce"]',
        '"layout_sha256": session.layout_sha256()',
        '"composition": composition.to_log()',
        '"trajectory_participant_count"',
        '"trajectory_counts"',
        '"policy_generation_advanced"',
        "candidate not in run_seeds",
        "max_participants=composition.participant_count + 1",
    ):
        assert token in trainer, f"Phase-5 trainer lacks {token}"

    for token in (
        "[string]$TestSurvivalBoneyardOverride",
        "SDMOD_TEST_SURVIVAL_BONEYARD_OVERRIDE",
        "requestedBoneyardSha256",
        "stagedBoneyardSha256",
        "Test survival boneyard override must be a .boneyard",
    ):
        assert token in launcher, f"solo layout plumbing lacks {token}"

    for token in (
        "observation_count",
        "observation_finite",
        "movement_mask_mismatches",
        "target_mask_mismatches",
        "cast_mask_mismatches",
        "actor-ID target persistence after enemy re-sort",
        "primary_welded",
        "pickup observation block population",
        "native exactly-once pickup credit",
        "team ally observation population",
        "secondary_beyond_primary_accepted",
        "policy target selected",
        "policy secondary accepted",
    ):
        assert token in live, f"Phase-5 live verifier lacks {token}"
    offline_solo = live.split(
        "def _verify_offline_solo_ally_zero(", 1
    )[1].split("def verify(", 1)[0]
    _require_in_order(
        offline_solo,
        "session.start_test_run(",
        "session.prepare_training_combat(",
        "session.write_composition(solo)",
    )
    for token in (
        'context.row.behavior == "learned"',
        "pcall(sd.gameplay.get_manual_enemy_spawner_state)",
        "manual_state.manual_mode == true",
        "not manual_policy_run",
    ):
        assert token in brain, (
            f"manual learned-policy pre-wave integration lacks {token}"
        )
    for token in (
        "policy.version",
        "mlp-tanh-three-head-v2",
        "policy.observation_size",
        "policy.target_actions",
        "def _prime_scripted_primary()",
        "sd.bots.get_loadout_details(participant_id)",
        "sd.bots.debug_sync_level_up",
        "def _prepare_stock_arena(",
        "BOT_ARENA_SEPARATION_DISTANCE",
        "sd.__settings_invoke_action(",
        "'respawn_bot'",
        "and wave >= 1",
        'result["primaryPrime"] = _prime_scripted_primary()',
    ):
        assert token in scripted, (
            f"scripted-bot regression verifier lacks {token}"
        )
    scripted_gate_order = (
        'result["waveStart"] = start',
        'result["arenaTransition"] = _prepare_stock_arena(run_views)',
        'result["primaryPrime"] = _prime_scripted_primary()',
        "monitored = _monitor_run(",
    )
    assert [
        scripted.index(token) for token in scripted_gate_order
    ] == sorted(scripted.index(token) for token in scripted_gate_order), (
        "scripted-bot regression must enter the stock arena before "
        "materializing and priming the accepted roster"
    )

    assert "sd.world.request_loot_pickup" in brain
    assert "context.request_loot_pickup" in brain
    assert "pickup_id,\n          context.participant_id" in brain
    assert "pickup request queued network_drop_id=" in brain
    assert (
        "QueueSyntheticParticipantLootPickupRequest(" in transport_header
    )
    assert (
        "participant_id == 0\n"
        "            ? multiplayer::QueueLocalLootPickupRequest("
    ) in binding
    for token in (
        "bool QueueSyntheticParticipantLootPickupRequest(",
        "IsLuaControlledParticipant(*participant)",
        "TryFindHostRunLootDropByNetworkId(",
        "ApplyLootPickupRequestPacket(",
        "TransportPeerEndpoint{}",
    ):
        assert token in pickup_queue, (
            f"synthetic pickup ingress lacks {token}"
        )
    assert "if (!g_local_transport.is_host ||" in pickup_handler
    assert "if (!host_synthetic_ingress)" in pickup_handler
    assert "host_synthetic_ingress &&" in pickup_authority
    assert "IsLuaControlledParticipant(*participant)" in pickup_authority
    assert "memory.pickup_request_accepted[pickup_id] ~= true" in brain

    return (
        "Phase 5 pins disposable seeded episodes, config-driven solo/mixed/"
        "multi-learned rotation, participant-grouped PPO, strict live v2 "
        "behavior checks, and semantic host pickup ingress"
    )
