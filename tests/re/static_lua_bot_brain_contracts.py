"""Contracts for the autonomous synthetic-participant bot roster."""

from __future__ import annotations

import json
import re

from static_multiplayer_contract_support import _read, _require_in_order


def test_bot_loadout_details_are_cached_address_free_and_observation_safe() -> str:
    binding = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_bots.cpp"
    )
    runtime = _read(
        "SolomonDarkModLoader/src/bot_runtime.cpp"
    )
    helper = _read(
        "SolomonDarkModLoader/src/bot_runtime/helpers/"
        "loadout_details.inl"
    )
    api = _read(
        "SolomonDarkModLoader/src/bot_runtime/public_api/"
        "loadout_details_api.inl"
    )
    skill_choices = _read(
        "SolomonDarkModLoader/src/bot_runtime/public_api/"
        "skill_choices_api.inl"
    )
    skill_apply = _read(
        "SolomonDarkModLoader/src/bot_runtime/public_api/"
        "bot_skill_choice_api.inl"
    )
    native = "\n".join(
        (
            _read(
                "SolomonDarkModLoader/src/native_spell_stats/"
                "primary_and_secondary_resolution.inl"
            ),
            _read(
                "SolomonDarkModLoader/src/native_spell_stats/"
                "secondary_resolution.inl"
            ),
        )
    )
    live_probe = _read(
        "tests/re/run_live_native_spell_stats_probe.py"
    )
    layout = _read("config/binary-layout.ini")
    docs = _read("docs/lua-bots.md")

    assert (
        'RegisterFunction(state, &LuaBotsGetLoadoutDetails, '
        '"get_loadout_details")'
    ) in binding
    _require_in_order(
        api,
        "BotLoadoutRevisionTuplesEqual(",
        "cached->progression_runtime_address ==",
        "cached->actor_address == actor_address",
        "*details = cached->details",
        "OverlayLiveSecondaryCooldowns(",
        "pending_weld_build_id_resolved",
    )
    for token in (
        "loadout_revision",
        "spellbook_revision",
        "statbook_revision",
        "derived_stat_revision",
        "g_loadout_details_cache",
        "g_active_bot_weld_builds",
    ):
        assert token in runtime + api, (
            f"loadout revision cache lacks {token}"
        )

    assert "TryReadNativePrimarySpellStatsFromCurrentOutput(" in helper
    assert "TryReadNativeCurrentPrimarySelection(" in helper
    assert (
        "TryResolveNativePrimarySpellStatsPreservingSelection("
    ) in helper
    assert "CallSkillsWizardBuildPrimarySpellSafe(" not in helper + api
    assert "kSkillsWizardBuildPrimarySpell" not in helper + api
    _require_in_order(
        helper,
        "TryReadNativePrimarySpellStatsFromCurrentOutput(",
        "TryResolveNativePrimarySpellStatsPreservingSelection(",
    )
    _require_in_order(
        native,
        "bool TryResolveNativePrimarySpellStatsPreservingSelection(",
        "previous_current_spell_id",
        "TryResolveNativePrimarySpellStats(",
        "RestoreProgressionCurrentSpellIdIfNeeded(",
        "restored_current_spell_id != previous_current_spell_id",
    )
    _require_in_order(
        helper,
        "const bool frost_jet =",
        "TryResolveNativeFrostJetQueryRange(",
        'range_source = "native_frost_jet_query_range"',
        "TryReadPrimarySelectionPursuitRange(",
    )

    for token in (
        "standalone_wizard_progression_cooldown_current=0x64",
        "standalone_wizard_progression_cooldown_cap=0x68",
    ):
        assert token in layout
    for token in (
        "kPhasingEntryIndex = 15",
        "kTeleportEntryIndex = 48",
        "kNativeCooldownTicksPerSecond = 100.0f",
        "current_ticks / kNativeCooldownTicksPerSecond",
        "cap_ticks / kNativeCooldownTicksPerSecond",
    ):
        assert token in native, (
            f"validated secondary cooldown read lacks {token}"
        )

    _require_in_order(
        skill_choices,
        "weld_option_present",
        "TryReadNativePendingWeldBuildId(",
        "pending_choice->generation =",
        "pending_choice->pending_weld_build_id =",
    )
    _require_in_order(
        skill_apply,
        "selected_option.option_id ==",
        "!pending_choice.pending_weld_build_id_resolved",
        "bot spell welding choice has no generation-captured build",
        "pending_choice.pending_weld_build_id_resolved",
        "special_choice_activated",
        "existing->generation == pending_choice.generation",
        "PromoteActiveBotWeldBuildLocked(",
        "RemovePendingSkillChoice(",
    )

    push_block = binding.split(
        "void PushBotLoadoutDetails(", 1
    )[1].split("int LuaBotsGetLoadoutDetails(", 1)[0]
    for forbidden in (
        '"address"',
        '"pointer"',
        '"ptr"',
        '"seh"',
        '"exception"',
        '"output_values"',
    ):
        assert forbidden not in push_block, (
            f"loadout Lua result exposes native detail {forbidden}"
        )
    for token in (
        "`sd.bots.get_loadout_details(participant_id)`",
        "`loadout_revision`, `spellbook_revision`, `statbook_revision`,",
        "never invokes that mutating",
        "100 ticks per second",
        "`cooldown_resolved = false`",
    ):
        assert token in docs

    for token in (
        'environment["SDMOD_DISABLE_AUDIO"] = "1"',
        "register_owned_launch(result)",
        "stop_owned_process_ids(process_ids)",
        "sample.lua.bots",
        "schema_and_primary_mutation_probe",
        "cooldown_transition_probe",
        "roll_weld_offer",
        "apply_captured_weld",
        "refresh_profile_and_reconstruct_weld",
    ):
        assert token in live_probe, (
            f"Phase 2 live loadout acceptance lacks {token}"
        )
    acceptance_probe = live_probe.split(
        "class OwnedSoloSession:", 1
    )[1]
    for forbidden in (
        "csp.stop_game",
        "stop_owned_game_processes(",
        "kill_existing=True",
    ):
        assert forbidden not in acceptance_probe, (
            f"Phase 2 live loadout acceptance has unsafe cleanup {forbidden}"
        )

    return (
        "Bot loadout details are revision-cached, dynamically overlay the "
        "proven cooldown/weld state, and never expose native state"
    )


def test_lua_bot_brain_is_rostered_native_routed_and_damage_gated() -> str:
    manifest = json.loads(_read("mods/bot-brain/manifest.json"))
    main = _read("mods/bot-brain/scripts/main.lua")
    roster = _read("mods/bot-brain/scripts/roster.lua")
    brain = _read("mods/bot-brain/scripts/brain.lua")
    steering = _read("mods/bot-brain/scripts/steering.lua")
    cast_range_test = _read("tools/test_bot_brain_cast_range.lua")
    combat_verifier = _read("tools/verify_bot_cast_in_range.py")
    docs = _read("docs/lua-bot-brain.md")
    verifier = _read("tools/verify_bot_polish.py")
    spawn_binding = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_bots/"
        "participant_handle_bindings.inl"
    )
    selection_priming = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "standalone_materialization_selection_priming.inl"
    )
    stuck_tracker = _read(
        "SolomonDarkModLoader/include/bot_stuck_progress.h"
    )
    stuck_motion = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_pathfinding_motion_update.inl"
    )
    settings_store = _read(
        "SolomonDarkModLauncher/src/ModSettings/ModSettingsStore.cs"
    )
    settings_migration = _read(
        "SolomonDarkModLauncher/src/ModSettings/"
        "BotBrainRosterSettingsMigration.cs"
    )
    stage_builder = _read(
        "SolomonDarkModLauncher/src/Staging/StageBuilder.cs"
    )
    design = _read("docs/design/bot-polish-2026-07-28.md")

    assert manifest["id"] == "bot.brain"
    assert manifest["name"] == "Lua Bots"
    assert manifest["version"] == "1.2.0"
    assert manifest["summary"] == (
        "Bot teammates and an optional bot brain for your own player."
    )
    assert manifest["description"] == (
        "Adds bot teammates to your lobby and can play your local "
        "character for you. Toggle Bot Play For Me at any time or press "
        "F9; turning it off returns clean control immediately. Local "
        "play uses the same skirmisher, guardian, striker, or learned "
        "brain as bot teammates and works for the host or a client "
        "through normal multiplayer authority and replication. Bot "
        "teammates still fill real player slots, appear in the member "
        "list, draw enemy attention, and move, cast, die, and respawn "
        "like human players. The learned policy runs locally inside Lua "
        "with no Python, GPU, or network service."
    )
    assert manifest["minimumLoaderVersion"] == "0.1.0-beta.28"
    assert manifest["enabled"] is False
    assert manifest["runtime"]["entryScript"] == "scripts/main.lua"
    required_capabilities = set(
        manifest["runtime"]["requiredCapabilities"]
    )
    for capability in (
        "events.runtime.tick",
        "state.replicated.read",
        "settings.list",
        "nav.read",
        "waves.read",
        "bots.runtime",
        "bots.state.read",
        "bots.create",
        "bots.move",
        "bots.stop",
        "bots.cast",
    ):
        assert capability in required_capabilities, (
            f"bot brain manifest lacks {capability}"
        )

    entries = {
        entry["key"]: entry
        for entry in manifest["settings"]["entries"]
    }
    assert "persona_name" not in entries
    roster_entry = entries["roster"]
    assert roster_entry["type"] == "list"
    assert roster_entry["scope"] == "host"
    assert roster_entry["min_items"] == 0
    assert roster_entry["max_items"] == 32
    fields = {
        field["key"]: field
        for field in roster_entry["item"]["fields"]
    }
    assert set(fields) == {
        "name",
        "element",
        "behavior",
        "discipline",
    }
    assert [choice["value"] for choice in fields["element"]["choices"]] == [
        "fire",
        "water",
        "earth",
        "air",
        "ether",
    ]
    assert [
        choice["value"]
        for choice in fields["behavior"]["choices"]
    ] == ["skirmisher", "guardian", "striker", "learned"]
    assert fields["behavior"]["label"] == "Behavior"
    assert [
        choice["value"]
        for choice in fields["discipline"]["choices"]
    ] == ["mind", "body", "arcane"]
    assert fields["discipline"]["label"] == "Discipline"

    _require_in_order(
        main,
        'sd.settings.get("roster")',
        'sd.settings.on_changed(function(key, new_value, old_value)',
        'elseif key == "roster" then',
        "manager:apply(",
        'sd.events.on("runtime.tick"',
        "manager:tick(",
        "tonumber(event.tick_count) or 0)",
    )
    _require_in_order(
        roster,
        "rows_match(existing.row, normalized_row)",
        "self:retire_context(context)",
        "self.contexts = next_contexts",
        "self:ensure_context(",
    )
    _require_in_order(
        brain,
        "sd.bots.get_primary_attack_window",
        "context.steering.nearest_cast_target",
        "issue_movement(",
        "issue_primary_cast(context, now_ms, target)",
    )
    approach_start = brain.find("if not context.fleeing and")
    approach_end = brain.find("context.debug.mode = \"approach\"", approach_start)
    assert approach_start >= 0 and approach_end > approach_start
    approach_block = brain[approach_start:approach_end]
    assert "threat_count == 0" not in approach_block, (
        "an outside-range threat still blocks the existing approach path"
    )

    nearest_cast_start = steering.find(
        "function steering.nearest_cast_target(")
    nearest_cast_end = steering.find(
        "function steering.nearest_enemy(", nearest_cast_start)
    assert nearest_cast_start >= 0 and nearest_cast_end > nearest_cast_start
    nearest_cast_block = steering[nearest_cast_start:nearest_cast_end]
    assert "contact_distance" not in nearest_cast_block, (
        "cast eligibility still subtracts target radius instead of checking "
        "the target center used by the native spell query"
    )

    for token in (
        "outside-range threat must use existing approach movement",
        "bot cast with target center outside native spell range",
        "in-range bot did not cast",
        "low-HP flee behavior was replaced by approach",
    ):
        assert token in cast_range_test, (
            f"bot cast-range behavior test lacks: {token}"
        )
    for token in (
        "damage_edge_count",
        "applied_damage_links(",
        "authorized_fireball_damage_links(",
        "applied no enemy damage",
        "cast outside its native range",
        '"combatAcceptance": "applied enemy HP damage edges"',
    ):
        assert token in combat_verifier, (
            f"bot applied-damage verifier lacks: {token}"
        )

    for token in (
        "sd.state.is_authority",
        'sd.settings.is_keybind_down("focus_bot_key")',
        'sd.settings.on_action("respawn_bot"',
        'rawset(_G, "bot_brain_debug"',
        "manager:reset_run(true)",
        "manager:reset_run(false)",
    ):
        assert token in main, f"bot roster wiring lacks: {token}"
    for token in (
        "sd.bots.spawn",
        "sd.bots.list",
        "context.bot:despawn()",
        "class = context.row.element",
        "discipline = context.row.discipline",
        "roster entry ",
        "last_spawn_attempt_ms",
        "self.brain.new(",
        'tostring(message or "") == "lobby full"',
        '" bots active"',
        '" — lobby full"',
        "capacity_refused_count",
    ):
        assert token in roster, f"bot roster reconciliation lacks: {token}"
    for token in (
        "cast_interval_ms = 500",
        "cast_interval_ms = 300",
        "flee_threshold = 0.35",
        "flee_threshold = 0.20",
        "leash_radius = 260.0",
        "engage_radius = 380.0",
        "engage_radius = 240.0",
        'controller_kind or "") == "Native"',
        "ward_distance < previous - 0.5",
        "sd.nav.test_segment",
        "context.bot:move_to(target.x, target.y)",
        "context.bot:cast(",
        "sd.bots.get_skill_choices",
        "sd.bots.choose_skill",
        "element_bands[context.row.element]",
        "primary_entries[option_id] ~= true",
        'context.row.behavior == "guardian"',
        "priority[band[1]] = 1",
    ):
        assert token in brain, f"bot behavior policy lacks: {token}"

    for token in (
        "behavior = tostring(row.behavior or \"\")",
        "discipline = tostring(row.discipline or \"\")",
        "left.behavior == right.behavior",
        "left.discipline == right.discipline",
        "DISCIPLINE_IDS",
    ):
        assert token in roster, f"roster vocabulary/loadout lacks: {token}"
    assert "row.discipline ~= \"guardian\"" not in brain
    assert "PROFILES[row.discipline]" not in brain

    _require_in_order(
        settings_store,
        "BotBrainRosterSettingsMigration.TryMigrateFile(path)",
        "File.Exists(path)",
    )
    _require_in_order(
        settings_migration,
        'row["behavior"] = legacyBehavior;',
        'row["discipline"] = "arcane";',
        "WriteAtomically(settingsPath, root);",
    )
    assert "BotBrainRosterSettingsMigration.TryMigrateStage(" in stage_builder

    for token in (
        'lua_getfield(state, table_index, "discipline")',
        'discipline_text == "mind"',
        'discipline_text == "body"',
        'discipline_text != "arcane"',
        "request.character_profile.discipline_id =",
    ):
        assert token in spawn_binding, (
            f"sd.bots.spawn lacks native Discipline parsing: {token}"
        )
    _require_in_order(
        selection_priming,
        "NativeSkillRowForDiscipline(",
        "CharacterDisciplineId::Mind:",
        "return 6;",
        "CharacterDisciplineId::Body:",
        "return 5;",
        "CharacterDisciplineId::Arcane:",
        "return 7;",
    )
    _require_in_order(
        selection_priming,
        "slot_progression_inner != progression_address",
        "Gameplay-slot bot progression is not the bot's slot-owned native book.",
        "discipline_skill_row =",
        "PrimeGameplaySlotBotBaseBookState(",
        "progression_address,",
        "discipline_skill_row,",
        "ActivateProfilePrimaryRows(",
        "CallActorProgressionRefreshSafe(",
    )
    _require_in_order(
        selection_priming,
        "bool PrimeGameplaySlotBotBaseBookState(",
        "kStockBaseBookRowCount = 8",
        "kStandaloneWizardProgressionEntryStatbookOffset",
        "kStatbookMaxLevelOffset",
        "internal_id != row",
        "kStandaloneWizardProgressionActiveFlagOffset",
        "kPlayerProgressionDisciplineSkillRowOffset,",
        "selected_row != discipline_skill_row",
    )
    _require_in_order(
        selection_priming,
        "bool ActivateProfilePrimaryRows(",
        "TryResolveNativePrimarySelectionForProfile(",
        "kStandaloneWizardProgressionActiveFlagOffset",
        "if (active == 0)",
        "CallPlayerAppearanceApplyChoiceSafe(",
        "entry_index,",
        "false,",
        "return active > 0;",
    )
    assert re.search(
        r"kPlayerProgressionDisciplineSkillRowOffset[\s\S]{0,160}"
        r"choice_ids\[3\]",
        selection_priming,
    ) is None

    for token in (
        "kBotStuckWindowMs = 30000",
        "kBotStuckTeleportCooldownMs = 10000",
        "opening_nearest_distance",
        "closing_nearest_distance",
        "midpoint_ms",
        "sample.waypoint_progress",
        "DiscardBotStuckWaypointProgress",
        "distance_progress <",
    ):
        assert token in stuck_tracker, (
            f"rolling stuck tracker lacks: {token}"
        )
    _require_in_order(
        stuck_motion,
        "multiplayer::IsLuaModSimulationAuthority()",
        "ParticipantControllerKind::LuaBrain",
        "ObserveBotStuckProgress(",
        "ResolveNativeBotSpawnPlacement(",
        '"stuck_teleport"',
        "TeleportPlayerFamilyActorAndRebind(",
        "StopBotPathMotion(binding, false)",
        "StopWizardBotActorMotion(binding->actor_address)",
        "multiplayer::StopBot(binding->bot_id)",
        "RecordBotStuckTeleport(",
        "PublishParticipantGameplaySnapshot(*binding)",
        '"[bots] stuck teleport. bot_id="',
    )
    path_failure = re.search(
        r"if \(!TryBuildBotPath\([\s\S]*?\n\s*\}",
        stuck_motion,
    )
    assert path_failure is not None
    assert "multiplayer::StopBot" not in path_failure.group(0)
    assert "if (!final_waypoint &&" in stuck_motion
    _require_in_order(
        stuck_motion,
        "if (!arrived_at_target)",
        "DiscardBotStuckWaypointProgress(",
        "binding->stuck_waypoint_anchor_valid = true",
        "action=rebuild",
    )
    for token in (
        "`0x005D0290`",
        "Mind (0)   -> row 6",
        "Body (1)   -> row 5",
        "Arcane (2) -> row 7",
        "`0x005E3080`",
        "`+0x244..+0x263`",
        "`+0x158/+0x15C`",
        "Name-label",
    ):
        assert token in design, f"bot-polish root-cause record lacks: {token}"

    for token in (
        "actor.tracked_enemy == true",
        "inverse_distance_weight",
        "arena.center_x - bot_x",
        "perimeter_bias",
        "center_alignment",
        "local tangent_x, tangent_y",
        "path_traversable == true",
        "movement_candidates",
        "constrain_to_guardian_leash",
        "current_distance > movement_radius",
        "nearest_cast_target",
        "nearest_enemy",
        "approach_direction",
    ):
        assert token in steering, f"bot steering policy lacks: {token}"

    combined_lua = main + roster + brain + steering
    for forbidden in (
        r"sd\.bots\.(?:create|update|move_to|cast|destroy|clear)\s*\(",
        r"sd\.debug",
        r"actor_address",
        r"kLocalPlayerActorGlobal",
        r"HookMonsterPathfindingRefreshTarget",
        r"write_(?:float|ptr|u32|i32)",
        r"persona_name",
    ):
        assert re.search(forbidden, combined_lua) is None, (
            f"bot brain contains forbidden legacy path: {forbidden}"
        )

    for token in (
        "schema accepts up to 32 rows",
        "a changed name",
        "Behavior",
        "Mind",
        "Body",
        "Arcane",
        "`sd.nav.test_segment`",
        "`bot:cast(0, target.x, target.y, 80)`",
        "nearest living human",
        "260 world units",
        "faster 300 ms cadence",
        "flees only below 20% HP",
        "ms2-host",
        "49211/49212",
    ):
        assert token in docs, f"bot roster documentation lacks: {token}"

    for token in (
        'INSTANCE_PREFIX = "botpolish"',
        "HOST_PORT = 50011",
        "CLIENT_PORT = 50012",
        'EXACT_MOD_ID = "bot.brain"',
        "enable_audio=False",
        "stop_exact_game_processes(launch)",
        '"stuckTeleportElapsedMs"',
        '"stuckTeleportPlacementValidated"',
        '"slowReachableTeleportCount"',
        '"humanClickTeleportCount"',
        "test_native_movement_collision",
        '"host-four-slot-lobby.png"',
        '"client-b-four-slot-lobby.png"',
    ):
        assert token in verifier, f"bot-polish acceptance lacks: {token}"
    assert "test_wave_override=" not in verifier
    assert "stop_game_processes(" not in verifier
    assert "verify_local_multiplayer_sync" not in verifier

    return (
        "The opt-in ordered roster fills up to four capacity-bounded seats "
        "with three scripted profiles plus a learned movement/casting "
        "policy and native per-bot Discipline on authority ticks, while "
        "combat acceptance requires bot-attributed enemy HP damage inside "
        "the equipped spell's native range"
    )


def test_lua_bot_brain_late_join_waits_for_complete_host_settings() -> str:
    engine = _read("SolomonDarkModLoader/src/lua_engine.cpp")
    mod_loading = _read(
        "SolomonDarkModLoader/src/lua_engine_mod_loading.cpp"
    )
    settings = _read(
        "SolomonDarkModLoader/src/lua_settings_runtime.cpp"
    )
    verifier = _read("tools/verify_bot_publication_flow.py")
    launcher = _read("scripts/Launch-BotPublicationPair.ps1")

    _require_in_order(
        engine,
        "InitializeLuaSettingsForMod(mod, error_message)",
        "ShouldDeferLuaEntryForHostSettings(mod)",
        "entry_script_deferred_for_host_settings = true",
        "return true",
        "luaL_newstate()",
    )
    _require_in_order(
        settings,
        "RequiresHostSettingsBarrier",
        '"settings.list"',
        "HaveCompleteReplicatedHostSettings",
        "IsActiveClientSession()",
        "TryGetReplicatedValue",
    )
    _require_in_order(
        settings,
        "if (mod->entry_script_deferred_for_host_settings)",
        "HaveCompleteReplicatedHostSettings(*mod)",
        "authoritative host settings ready before entry script",
        "CreateLuaStateForMod(",
        "started deferred entry script after host settings",
        "InitializeLuaHotReloadState(mod)",
        "ApplyEffectiveChange(",
    )
    assert (
        "entry script waiting for the authoritative host-settings checkpoint"
        in mod_loading
    )

    for token in (
        'INSTANCE_PREFIX = "bpub"',
        "HOST_PORT = 49411",
        "CLIENT_PORT = 49412",
        "clientStartupRosterWasNotLocalDefault",
        "clientOnChangedCount",
        "clientEntryOrdering",
        "waitingLogOffset",
        "authoritativeReadyMonotonicMs",
        "entryStartedMonotonicMs",
        "downloadedModCount",
        "nonemptyCrashArtifacts",
    ):
        assert token in verifier, (
            f"publication verifier lacks late-join proof: {token}"
        )
    assert "verify_local_multiplayer_sync" not in verifier

    for token in (
        '$hostPort = 49411',
        '$clientPort = 49412',
        '$hostInstance = "bpub-host"',
        '$clientInstance = "bpub-client"',
        'SDMOD_DISABLE_AUDIO = "1"',
        'SDMOD_MULTIPLAYER_TRANSPORT = "local_udp"',
        '"--multiplayer", "join"',
        '"--lobby-id", $LobbyId',
    ):
        assert token in launcher, (
            f"publication pair launcher lacks isolation contract: {token}"
        )

    return (
        "A late-joining client starts Lua Bots only after the complete "
        "authoritative host-settings checkpoint and proves one-change "
        "mid-session convergence on the isolated publication pair"
    )
