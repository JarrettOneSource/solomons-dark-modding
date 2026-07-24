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
    ):
        assert token in note


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
        "stable_post_respawn_samples",
        "exact_pid_stock_window_click",
        'launch["clientProcessId"]',
        '"--global-only"',
    ):
        assert token in verifier
    assert "stop_games(" not in verifier
