#!/usr/bin/env python3
"""Static contracts for dead-player progression and wave respawn ordering."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TRANSPORT = (
    ROOT
    / "SolomonDarkModLoader"
    / "src"
    / "multiplayer_local_transport.cpp"
)
TRANSPORT_PARTS = (
    ROOT
    / "SolomonDarkModLoader"
    / "src"
    / "multiplayer_local_transport"
)
DOC = (
    ROOT
    / "docs"
    / "reverse-engineering"
    / "native-player-death-spectator.md"
)
LAYOUT = ROOT / "config" / "binary-layout.ini"
GAMEPLAY_HEADER = (
    ROOT / "SolomonDarkModLoader" / "src" / "gameplay_seams.h"
)
GAMEPLAY_OFFSET_DECLARATIONS = (
    ROOT
    / "SolomonDarkModLoader"
    / "src"
    / "gameplay_seams"
    / "progression_and_actor_offsets.inl"
)
GAMEPLAY_STATE = (
    ROOT
    / "SolomonDarkModLoader"
    / "src"
    / "mod_loader_gameplay"
    / "public_api_state_getters.inl"
)
GAMEPLAY_RESPAWN = (
    ROOT
    / "SolomonDarkModLoader"
    / "src"
    / "mod_loader_gameplay"
    / "public_api_local_player_respawn.inl"
)
REMOTE_VITALS = (
    ROOT
    / "SolomonDarkModLoader"
    / "src"
    / "mod_loader_gameplay"
    / "bot_movement"
    / "native_remote_vitals_and_playback.inl"
)
SCENE_DRIVE = (
    ROOT
    / "SolomonDarkModLoader"
    / "src"
    / "mod_loader_gameplay"
    / "scene_and_animation_drive_profiles.inl"
)
VERIFIER = (
    ROOT
    / "tools"
    / "verify_multiplayer_dead_progression_round_respawn.py"
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_dead_picker_uses_only_the_stock_screen_virtual_gate() -> None:
    """Dead picker advances only through its stock screen virtual."""

    transport = read(TRANSPORT)
    picker = read(
        TRANSPORT_PARTS
        / "level_up_native_picker_presentation.inl"
    )
    death = read(TRANSPORT_PARTS / "death_spectator_sync.inl")
    required = (
        "kLevelUpScreenTickVtableOffset = 0x08",
        "NativeLevelUpScreenTickFn",
        "g_dead_level_up_screen_tick_hook",
    )
    assert all(token in transport for token in required)
    for token in (
        "HookDeadLevelUpScreenTick",
        "ArmDeadLevelUpScreenTickBridge",
        "kActorAnimationDriveStateByteOffset",
        "saved_drive_state",
        "alive_drive_state",
        "original(screen)",
        "g_dead_level_up_screen_tick_offer_id",
        "DisarmDeadLevelUpScreenTickBridgeForOffer",
        "g_local_death_spectator.phase",
    ):
        assert token in picker
    bridge_write = picker.index("alive_drive_state")
    bridged_original = picker.index("original(screen)", bridge_write)
    assert (
        bridge_write
        < bridged_original
        < picker.index(
            "(void)memory.TryWriteField",
            bridged_original,
        )
    )
    assert "HasPendingLocalLevelUpChoice(runtime_state)" in death
    picker_input_gate = death.index(
        "if (HasPendingLocalLevelUpChoice(runtime_state))"
    )
    spectator_consume = death.index(
        "ClearQueuedGameplayMouseLeft()",
        picker_input_gate,
    )
    assert "ClearQueuedGameplayMouseLeft()" not in death[
        picker_input_gate:spectator_consume
    ]


def test_wave_respawn_is_a_transport_sequence_barrier() -> None:
    """Wave respawn rejects pre-respawn vitals authority."""

    death = read(TRANSPORT_PARTS / "death_spectator_sync.inl")
    correction = read(
        TRANSPORT_PARTS / "participant_vitals_correction.inl"
    )
    for token in (
        "g_last_applied_wave_respawn_authority_packet_sequence",
        "RetirePreRespawnHostParticipantVitalsCorrections",
        "g_queued_host_participant_vitals_corrections.clear()",
        "pending_participant_vitals_corrections_by_participant",
        "last_participant_vitals_correction_send_ms_by_participant",
        "packet.header.sequence",
    ):
        assert token in death
    assert (
        death.index("RetirePreRespawnHostParticipantVitalsCorrections();")
        < death.index(
            "g_host_wave_respawn.command = WaveRespawnCommand"
        )
    )
    for token in (
        "g_last_applied_wave_respawn_authority_packet_sequence",
        "IsPacketSequenceNewer(",
        "packet.header.sequence",
    ):
        assert token in correction
    barrier = correction.index(
        "g_last_applied_wave_respawn_authority_packet_sequence"
    )
    death_replay = correction.index(
        "TryApplyAuthoritativeLocalPlayerDeath"
    )
    assert barrier < death_replay


def test_re_note_records_picker_respawn_and_same_actor_findings() -> None:
    """Dead progression RE note records lifecycle findings."""

    note = read(DOC)
    for token in (
        "## Dead-player level-up presentation",
        "`FUN_0066F920`",
        "slot `+0x08`",
        "## Wave completion respawn and stale death authority",
        "Packet header sequences are shared across packet kinds",
        "## Loadout identity across respawn",
        "same-actor boundary",
        "## Stock Boneyard spawn publication and run-start placement",
        "`FUN_00462410`",
        "## Corpse registration and participant-scoped retirement",
        "`WorldCellGrid_RebindActor`",
    ):
        assert token in note


def test_respawn_uses_live_arena_spawn_and_restores_actor_registration() -> None:
    """Both local and remote respawn restore the stock actor lifecycle."""

    layout = read(LAYOUT)
    header = read(GAMEPLAY_HEADER) + read(
        GAMEPLAY_OFFSET_DECLARATIONS
    )
    state = read(GAMEPLAY_STATE)
    local_respawn = read(GAMEPLAY_RESPAWN)
    remote_vitals = read(REMOTE_VITALS)
    scene_drive = read(SCENE_DRIVE)
    death = read(TRANSPORT_PARTS / "death_spectator_sync.inl")
    for token in (
        "actor_grid_member_flag=0x36",
        "actor_render_sort_bias=0xA0",
        "arena_player_spawn_x=0x8ED0",
        "arena_player_spawn_y=0x8ED4",
        "arena_player_spawn_facing=0x8EF0",
    ):
        assert token in layout
    for token in (
        "kActorGridMemberFlagOffset",
        "kActorRenderSortBiasOffset",
        "kArenaPlayerSpawnXOffset",
        "kArenaPlayerSpawnYOffset",
        "kArenaPlayerSpawnFacingOffset",
    ):
        assert token in header
    for token in (
        "player_spawn_valid",
        "player_spawn_x",
        "player_spawn_y",
        "player_spawn_facing",
    ):
        assert token in state
    for token in (
        "CaptureHostWaveRespawnSpawnIfNeeded",
        "TryGetWorldState(&world)",
        "world.player_spawn_valid",
        "world.player_spawn_x",
        "world.player_spawn_y",
    ):
        assert token in death
    for token in (
        "RestoreWizardActorAliveRegistrationState",
        "RebindSceneActorCell",
    ):
        assert token in local_respawn
    for token in (
        "RestoreWizardActorAliveRegistrationState",
        "CallWorldCellGridRebindActorSafe",
    ):
        assert token in remote_vitals
    for token in (
        "kActorRenderSortBiasOffset",
        "0.0f",
        "kActorGridMemberFlagOffset",
    ):
        assert token in scene_drive


def test_live_gate_is_isolated_and_reads_exact_actor_state() -> None:
    """Dead progression live gate uses stock input and exact actor reads."""

    verifier = read(VERIFIER)
    for token in (
        "kill_existing=False",
        "select_available_windows_udp_ports(4)",
        "game_process_ids(launch)",
        "stop_game_processes(process_ids)",
        "query_progression_snapshot",
        "inventory.item_rows",
        "inventory.book_rows",
        "assert_same_actor_loadout_after_respawn",
        "assert_staff_preserved_without_duplication",
        "client-dead-spectator-level-up-picker.png",
        "client-immediate-round-respawn-clean.png",
        "player_spawn_valid",
        "_place_client_far_from_spawn",
        "respawn_tick_peer_views",
        "grid_member_flag",
        "render_sort_bias",
        'scenario_label="grace-respawn"',
        'scenario_label="immediate-round-respawn"',
        'f"client-{scenario_label}-death-location-cleared.png"',
        'f"host-{scenario_label}-death-location-cleared.png"',
        'f"host-{scenario_label}-spawn.png"',
        "stable_post_respawn_samples",
        "exact_pid_stock_window_click",
        'launch["clientProcessId"]',
        '"--global-only"',
    ):
        assert token in verifier
    assert "stop_games(" not in verifier
