"""Static contracts for elemental primary damage and synthetic wave respawn."""

from __future__ import annotations

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    read_text,
)


def require_tokens(
    text: str,
    label: str,
    tokens: tuple[str, ...],
) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise StaticReTestFailure(
            f"{label} lacks required token(s): {', '.join(missing)}"
        )


def test_four_element_primary_slot_gates_share_one_audited_registry() -> str:
    layout = read_text(ROOT / "config/binary-layout.ini")
    seams = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams.h"
    )
    storage = read_text(
        ROOT /
        "SolomonDarkModLoader/src/gameplay_seams/address_storage.inl"
    )
    bindings = read_text(
        ROOT /
        "SolomonDarkModLoader/src/gameplay_seams/"
        "state_and_address_bindings.inl"
    )
    gates = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_casting/native_cast_gate_patches.inl"
    )
    hooks = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "gameplay_hooks/player_cast_hooks.inl"
    )
    dispatch = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "player_cast_hooks_effect_and_dispatch.inl"
    )
    design = read_text(
        ROOT / "docs/design/bot-combat-parity-2026-07-29.md"
    )

    require_tokens(
        layout,
        "binary layout",
        (
            "spell_cast_010_slot_gate_branch=0x0053E4E8",
            "spell_cast_018_first_damage_slot_gate_branch=0x0053FCD8",
            "spell_cast_018_chain_damage_slot_gate_branch=0x00540767",
            "spell_cast_020_damage_slot_gate_branch=0x0054423A",
            "spell_cast_028_slot_gate_branch=0x00544C92",
        ),
    )
    require_tokens(
        "\n".join((seams, storage, bindings)),
        "Air gate address seams",
        (
            "kSpellCast018FirstDamageSlotGateBranch",
            "kSpellCast018ChainDamageSlotGateBranch",
            '"spell_cast_018_first_damage_slot_gate_branch"',
            '"spell_cast_018_chain_damage_slot_gate_branch"',
        ),
    )
    require_tokens(
        gates,
        "unified primary gate registry",
        (
            "NativePrimarySlotGatePolicy",
            "ParticipantPresentation",
            "HostOwnedLuaDamage",
            "g_native_primary_slot_gate_patches",
            '"spell_cast_010_fire_slot_gate"',
            '"spell_cast_018_first_damage_slot_gate"',
            '"spell_cast_018_chain_damage_slot_gate"',
            '"spell_cast_020_water_damage_slot_gate"',
            '"spell_cast_028_earth_slot_gate"',
            "ValidateNativePrimarySlotGatePatches",
            "ScopedNativePrimarySlotGatePatches",
            "AcquireNativePrimarySlotGatePatch",
            "ReleaseNativePrimarySlotGatePatch",
        ),
    )
    require_tokens(
        "\n".join((hooks, dispatch)),
        "native primary dispatch scopes",
        (
            "ScopedNativePrimarySlotGatePatches primary_slot_gates(",
            "primary_slot_gates.ready()",
            "primary_slot_gates.error_message()",
        ),
    )
    for forbidden in (
        "g_scoped_frost_jet_damage_slot_gate_patch",
        "IsAuthoritativeHostLuaBrainFrostJetCast",
    ):
        if forbidden in gates or forbidden in hooks or forbidden in dispatch:
            raise StaticReTestFailure(
                f"single-spell primary gate remains: {forbidden}"
            )
    require_tokens(
        design,
        "native four-primary audit",
        (
            "`0x0053E4E8`",
            "`0x0053FCD8`",
            "`0x00540767`",
            "`0x0054423A`",
            "`0x00544C92`",
            "13 accepted Air casts and zero authoritative enemy HP edges",
        ),
    )
    return (
        "Fire, Water, Earth, and both Air damage branches use one "
        "opcode-validated authority-scoped primary gate registry"
    )


def test_wave_respawn_applies_same_actor_contract_to_synthetic_participants() -> str:
    gameplay_api = read_text(
        ROOT /
        "SolomonDarkModLoader/include/mod_loader_gameplay_api.inl"
    )
    respawn = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_local_player_respawn.inl"
    )
    entity = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "participant_entity_state.inl"
    )
    lifecycle = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "bot_registry_and_movement_participant_lifecycle.inl"
    )
    wave = read_text(
        ROOT /
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "death_spectator_sync.inl"
    )
    wave_intelligence = read_text(
        ROOT / "SolomonDarkModLoader/src/wave_intelligence.cpp"
    )
    wave_intelligence_api = read_text(
        ROOT / "SolomonDarkModLoader/include/wave_intelligence.h"
    )
    remote_vitals = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/"
        "native_remote_vitals_and_playback.inl"
    )
    locomotion = read_text(
        ROOT /
        "SolomonDarkModLoader/src/mod_loader_gameplay/bot_movement/"
        "locomotion_and_animation.inl"
    )
    game_over = read_text(
        ROOT /
        "SolomonDarkModLoader/src/multiplayer_local_transport/"
        "run_game_over_sync.inl"
    )
    design = read_text(
        ROOT / "docs/design/bot-combat-parity-2026-07-29.md"
    )

    require_tokens(
        gameplay_api,
        "participant respawn API",
        (
            "TryRespawnHostOwnedSyntheticParticipantsAt(",
            "respawn_epoch",
            "run_nonce",
        ),
    )
    require_tokens(
        respawn,
        "same-actor respawn primitive",
        (
            "struct WizardRespawnTarget",
            "TryRespawnWizardActorAt(",
            "TryRespawnLocalPlayerAt(",
            "TryRespawnHostOwnedSyntheticParticipantsAt(",
            "ParticipantControllerKind::LuaBrain",
            "last_applied_wave_respawn_run_nonce",
            "last_applied_wave_respawn_epoch",
            "ClearWizardActorGameplayCastState(",
            "RestoreWizardActorAliveRegistrationState(",
            "RebindSceneActorCell(",
            "PublishParticipantGameplaySnapshot(",
            "multiplayer::StopBot(binding.bot_id)",
        ),
    )
    stop_intent = respawn.find(
        "multiplayer::StopBot(binding.bot_id)"
    )
    quiesce_binding = respawn.find(
        "QuiesceDeadWizardBinding(&binding)"
    )
    if not 0 <= stop_intent < quiesce_binding:
        raise StaticReTestFailure(
            "synthetic respawn does not retire the pre-death movement "
            "intent before resetting its live binding"
        )
    if (
        "TryWriteField(actor_address, "
        "kActorMoveStepScaleOffset, 0.0f)"
    ) in locomotion:
        raise StaticReTestFailure(
            "dead-bot quiescence still destroys the native move-step "
            "scale required after same-actor respawn"
        )
    require_tokens(
        "\n".join((entity, lifecycle)),
        "per-binding respawn epoch",
        (
            "last_applied_wave_respawn_run_nonce",
            "last_applied_wave_respawn_epoch",
        ),
    )
    require_tokens(
        wave,
        "host wave-respawn participant application",
        (
            "SnapshotLastCompletedWave()",
            "TryRespawnHostOwnedSyntheticParticipantsAt(",
            "command.epoch",
            "command.run_nonce",
            "host_synthetic_respawn",
            "TryRespawnLocalPlayerAt(",
        ),
    )
    if "summary.phase != WavePhase::Completed" in wave:
        raise StaticReTestFailure(
            "wave respawn still samples the transient completed phase"
        )
    require_tokens(
        "\n".join((wave_intelligence, wave_intelligence_api)),
        "durable wave-completion latch",
        (
            "last_completed_wave",
            "SnapshotLastCompletedWave()",
            "update.completed_wave",
        ),
    )
    synthetic_call = wave.find(
        "TryRespawnHostOwnedSyntheticParticipantsAt("
    )
    local_call = wave.find("TryRespawnLocalPlayerAt(")
    epoch_commit = wave.find(
        "g_last_applied_wave_respawn_epoch = command.epoch"
    )
    if not (
        0 <= synthetic_call < local_call < epoch_commit
    ):
        raise StaticReTestFailure(
            "wave-respawn epoch is committed before all same-actor "
            "participant respawns converge"
        )
    require_tokens(
        remote_vitals,
        "client B alive transition",
        (
            "if (!authoritative_dead)",
            "RestoreWizardActorAliveRegistrationState(actor_address)",
            "binding->native_remote_death_epoch_active = false",
        ),
    )
    require_tokens(
        game_over,
        "all-dead loss rule",
        (
            "IsParticipantTerminallyDead",
            "RefreshHostRunGameOverCommand",
            "host_all_players_dead",
        ),
    )
    require_tokens(
        design,
        "synthetic lifecycle design",
        (
            "never enumerates host-owned Lua participants",
            "Bots therefore cannot respawn on a timer",
            "participant ID, actor, progression, loadout, and transport",
        ),
    )
    return (
        "each host wave-respawn epoch restores every Lua participant "
        "through the same idempotent same-actor lifecycle as slot 0"
    )


def test_botcombat_live_harnesses_require_applied_damage_and_peer_respawn() -> str:
    bot_match = read_text(ROOT / "tools/run_bot_match.py")
    matrix = read_text(
        ROOT / "tools/verify_bot_primary_damage_matrix.py"
    )
    respawn = read_text(ROOT / "tools/verify_bot_wave_respawn.py")
    config = read_text(ROOT / "tools/bot_match.example.json")
    nameplate = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_bots.cpp"
    )

    require_tokens(
        "\n".join((bot_match, matrix)),
        "permanent four-element applied-damage matrix",
        (
            'ELEMENTS = ("fire", "air", "water", "earth")',
            '"four_fighter_damage_matrix_satisfied"',
            '"damageDealtEdges"',
            '"damageDealt"',
            "validate_element_result(",
            "len(fighters) == 4",
            "len(damaging) == 4",
            'mode="matrix"',
            "validate_backbuffer",
            "STUCK_TELEPORT_MARKER",
        ),
    )
    matrix_validator = matrix[
        matrix.index("def validate_element_result("):
        matrix.index("def accepted_element_run(")
    ]
    if "accepted" in matrix_validator.casefold():
        raise StaticReTestFailure(
            "primary matrix treats accepted casts as a result"
        )
    require_tokens(
        config,
        "botcombat isolation contract",
        (
            '"/mnt/d/codex-evidence/botcombat-20260729"',
            '"localPort": 50611',
            '"unusedRemotePort": 50612',
        ),
    )
    require_tokens(
        respawn,
        "permanent native synthetic respawn verifier",
        (
            "HOST_PORT = 50611",
            "CLIENT_PORT = 50612",
            'CLIENT_NAME = "client B"',
            'environment["SDMOD_DISABLE_AUDIO"] = "1"',
            '"-NoTileWindows"',
            "queue_native_magic_hit_behavior_probe(",
            "get_native_magic_hit_behavior_probe_result(",
            "route_slot_zero_to_retail_waves(",
            '"arrival_valid"',
            '"arrivalDistance"',
            "sd.hub.trigger_solomon_dig()",
            "state_is_dead(",
            "validate_respawn_transition(",
            '"element": "air"',
            "__botcombat_respawn_target_hold",
            '"other_bots_active"',
            '"host_slot_zero_movement_hold_armed"',
            '"client_b_movement_hold_armed"',
            "combat_movement_enabled",
            '"local_player_x"',
            '"spawn_nav_traversable"',
            '"actor_nav_traversable"',
            '"first_respawn_mp"',
            '"first_respawn_max_mp"',
            "take_enemy_damage_observations()",
            "clientBTargetability",
            "__botcombat_respawn_targetability",
            "get_replicated_actors()",
            "nameplate_health_ratio",
            "capture_backbuffer",
            "validate_backbuffer",
            "Stop-RemoteLatencyPeer.ps1",
        ),
    )
    for forbidden in (
        "import verify_local_multiplayer_sync",
        "sd.debug.write_float",
        "sd.gameplay.start_waves",
        "sd.world.trigger_enemy_death",
        "Stop-Process",
    ):
        if forbidden in respawn:
            raise StaticReTestFailure(
                f"synthetic respawn verifier uses forbidden shortcut: "
                f"{forbidden}"
            )
    require_tokens(
        nameplate,
        "client B authoritative HP-bar query",
        (
            "float health_ratio = 0.0f;",
            "&health_ratio))",
            '"health_ratio"',
        ),
    )
    return (
        "permanent harnesses require per-fighter enemy HP edges and "
        "same-actor host/client B native wave respawn without HP writes"
    )
