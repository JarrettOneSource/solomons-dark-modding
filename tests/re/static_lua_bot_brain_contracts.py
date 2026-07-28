"""Contracts for the autonomous synthetic-participant bot roster."""

from __future__ import annotations

import json
import re

from static_multiplayer_contract_support import _read, _require_in_order


def test_lua_bot_brain_is_rostered_native_routed_and_wave_five_gated() -> str:
    manifest = json.loads(_read("mods/bot-brain/manifest.json"))
    main = _read("mods/bot-brain/scripts/main.lua")
    roster = _read("mods/bot-brain/scripts/roster.lua")
    brain = _read("mods/bot-brain/scripts/brain.lua")
    steering = _read("mods/bot-brain/scripts/steering.lua")
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
    assert manifest["version"] == "1.0.1"
    assert manifest["summary"] == (
        "Bot teammates that play like real players."
    )
    assert manifest["description"] == (
        "Adds bot teammates to your lobby. Bots fill real player slots: "
        "they show up in the member list, enemies target them, and they "
        "fight, die, and respawn like human players. Name each bot and "
        "choose its element and how it fights in the launcher's mod "
        "settings. Changes apply live, and in multiplayer the host's "
        "roster syncs to everyone. Requires v0.1.0-beta.22 or newer."
    )
    assert manifest["minimumLoaderVersion"] == "0.1.0-beta.22"
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
    assert roster_entry["max_items"] == 4
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
    ] == ["skirmisher", "guardian", "striker"]
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
        "manager:tick(now_ms, authority)",
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
        "movement_radius",
        "sd.nav.test_segment",
        "context.bot:move_to(target.x, target.y)",
        "context.bot:cast(",
        "sd.bots.get_skill_choices",
        "sd.bots.choose_skill",
        'context.row.element == "fire"',
        'context.row.behavior == "guardian"',
        "priority[16] = 2",
        "priority[18] = 3",
        "priority[17] = 4",
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
    assert "CallPlayerAppearanceApplyChoiceSafe(" not in selection_priming
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
        "zero to four ordered rows",
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
        "with three Lua Behavior profiles and native per-bot Discipline on "
        "authority ticks while retaining the existing combat gate"
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
