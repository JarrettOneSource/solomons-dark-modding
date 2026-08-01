from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
SCRIPT = TOOLS / "verify_multiplayer_replicated_audio_events.py"

if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

SPEC = importlib.util.spec_from_file_location(
    "verify_multiplayer_replicated_audio_events",
    SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReplicatedAudioEventVerifierTests(unittest.TestCase):
    def test_windows_process_paths_compare_case_and_separator_insensitively(self) -> None:
        self.assertEqual(
            MODULE.normalize_windows_path(
                r"C:\SD Audio\instances\pair-host\stage\SolomonDark.exe"
            ),
            MODULE.normalize_windows_path(
                "c:/sd audio/instances/pair-host/stage/SolomonDark.exe"
            ),
        )

    def test_trigger_contract_accepts_event_faithful_replication(self) -> None:
        counts = {key: 0 for key in MODULE.TRIGGER_COUNT_KEYS}
        for key in (
            "boulder_ctor",
            "startboulder_one_shot",
            "gather_loop_start",
            "gather_bass_channel_play",
        ):
            counts[key] = 1
        # Stock calls Stop once while selecting Earth (a no-op at refcount 0)
        # and once for the real release transition.
        counts["gather_loop_stop"] = 2

        MODULE.assert_trigger_contract(
            label="host_to_client",
            local_counts=counts,
            remote_counts=dict(counts),
        )

    def test_trigger_contract_rejects_restarted_remote_loop(self) -> None:
        local = {key: 0 for key in MODULE.TRIGGER_COUNT_KEYS}
        for key in (
            "boulder_ctor",
            "startboulder_one_shot",
            "gather_loop_start",
            "gather_bass_channel_play",
        ):
            local[key] = 1
        local["gather_loop_stop"] = 2
        remote = dict(local)
        remote["gather_loop_start"] = 9
        remote["gather_loop_stop"] = 9
        remote["gather_bass_channel_play"] = 9

        with self.assertRaisesRegex(
            MODULE.VerifyFailure,
            "replicated Earth audio diverged",
        ):
            MODULE.assert_trigger_contract(
                label="host_to_client",
                local_counts=local,
                remote_counts=remote,
            )

    def test_trigger_contract_rejects_extra_local_stop_transition(self) -> None:
        counts = {key: 0 for key in MODULE.TRIGGER_COUNT_KEYS}
        for key in (
            "boulder_ctor",
            "startboulder_one_shot",
            "gather_loop_start",
            "gather_bass_channel_play",
        ):
            counts[key] = 1
        counts["gather_loop_stop"] = 3

        with self.assertRaisesRegex(
            MODULE.VerifyFailure,
            "local Earth lifecycle",
        ):
            MODULE.assert_trigger_contract(
                label="solo",
                local_counts=counts,
            )

    def test_lightning_damage_event_contract_accepts_two_tick_jitter(self) -> None:
        parity = MODULE.assert_lightning_damage_event_parity(
            label="client_to_host",
            local_events=[MODULE.LIGHTNING_DAMAGE_TICK] * 170,
            remote_events=[MODULE.LIGHTNING_DAMAGE_TICK] * 168,
        )

        self.assertEqual(parity["local_damage_tick_count"], 170)
        self.assertEqual(parity["remote_damage_tick_count"], 168)
        self.assertAlmostEqual(parity["damage_delta"], 0.05)

    def test_lightning_damage_event_contract_accepts_coalesced_hp_writes(self) -> None:
        parity = MODULE.assert_lightning_damage_event_parity(
            label="client_to_host",
            local_events=[MODULE.LIGHTNING_DAMAGE_TICK] * 170,
            remote_events=[MODULE.LIGHTNING_DAMAGE_TICK * 10] * 17,
        )

        self.assertEqual(parity["local_raw_transition_count"], 170)
        self.assertEqual(parity["remote_raw_transition_count"], 17)
        self.assertEqual(parity["local_damage_tick_count"], 170)
        self.assertEqual(parity["remote_damage_tick_count"], 170)

    def test_lightning_damage_event_contract_rejects_zero_remote_damage(self) -> None:
        with self.assertRaisesRegex(
            MODULE.VerifyFailure,
            "did not damage the authority in both origins",
        ):
            MODULE.assert_lightning_damage_event_parity(
                label="client_to_host",
                local_events=[MODULE.LIGHTNING_DAMAGE_TICK] * 170,
                remote_events=[],
            )

    def test_lightning_damage_event_contract_rejects_remote_tick_loss(self) -> None:
        with self.assertRaisesRegex(
            MODULE.VerifyFailure,
            "damage events diverged",
        ):
            MODULE.assert_lightning_damage_event_parity(
                label="client_to_host",
                local_events=[MODULE.LIGHTNING_DAMAGE_TICK] * 170,
                remote_events=[MODULE.LIGHTNING_DAMAGE_TICK] * 130,
            )

    def test_solo_control_compares_deterministic_cast_lifecycle_only(self) -> None:
        self.assertIn(
            "gather_bass_channel_play",
            MODULE.CAST_LIFECYCLE_TRIGGER_KEYS,
        )
        self.assertIn("gather_loop_stop", MODULE.CAST_LIFECYCLE_TRIGGER_KEYS)
        self.assertNotIn("rockhit_one_shot", MODULE.CAST_LIFECYCLE_TRIGGER_KEYS)

    def test_live_gate_is_audio_enabled_and_process_scoped(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        frost_source = (
            TOOLS / "verify_multiplayer_frost_loop_lifecycle.py"
        ).read_text(encoding="utf-8")
        self.assertIn("enable_audio=True", source)
        self.assertIn('"-EnableAudio"', source)
        self.assertIn("validate_owned_processes", source)
        self.assertIn("host_to_client", source)
        self.assertIn("client_to_host", source)
        self.assertIn("run_solo_case", source)
        self.assertIn("run_lightning_damage_parity", source)
        self.assertIn("COLLECT_LIGHTNING_DAMAGE_MONITOR_LUA", source)
        self.assertNotIn("stop_games(", source)
        self.assertIn('INSTANCE_PREFIX = "sfx"', frost_source)
        self.assertIn("HOST_PORT = 48611", frost_source)
        self.assertIn("CLIENT_PORT = 48612", frost_source)
        self.assertIn("enable_audio=False", frost_source)
        self.assertIn(
            "sd.debug.get_native_audio_channels(false)",
            frost_source,
        )
        self.assertIn("remote_stop_latency_ms", frost_source)
        self.assertIn("no_outliving_owned_loop", frost_source)
        self.assertIn("audio.stop_owned_processes(", frost_source)
        self.assertNotIn("trace_function", frost_source)
        self.assertNotIn("enable_audio=True", frost_source)
        self.assertNotIn("stop_games(", frost_source)

    def test_owned_cleanup_revalidates_path_before_exact_pid_stop(self) -> None:
        expected = {
            3210: Path(
                "/mnt/c/audio/instances/audio-host/stage/SolomonDark.exe"
            )
        }
        windows_path = (
            r"C:\audio\instances\audio-host\stage\SolomonDark.exe"
        )
        with (
            mock.patch.object(
                MODULE,
                "query_processes",
                side_effect=[{3210: windows_path}, {}],
            ),
            mock.patch.object(
                MODULE,
                "path_for_powershell",
                return_value=windows_path,
            ),
            mock.patch.object(MODULE, "stop_game_processes") as stop,
        ):
            stopped = MODULE.stop_owned_processes(expected)

        stop.assert_called_once_with((3210,))
        self.assertEqual(stopped, {"3210": windows_path})

    def test_owned_cleanup_refuses_reused_pid(self) -> None:
        expected = {
            3210: Path(
                "/mnt/c/audio/instances/audio-host/stage/SolomonDark.exe"
            )
        }
        with (
            mock.patch.object(
                MODULE,
                "query_processes",
                return_value={3210: r"C:\other\SolomonDark.exe"},
            ),
            mock.patch.object(
                MODULE,
                "path_for_powershell",
                return_value=(
                    r"C:\audio\instances\audio-host\stage\SolomonDark.exe"
                ),
            ),
            mock.patch.object(MODULE, "stop_game_processes") as stop,
        ):
            with self.assertRaisesRegex(
                MODULE.VerifyFailure,
                "refusing to stop PID",
            ):
                MODULE.stop_owned_processes(expected)

        stop.assert_not_called()

    def test_window_activation_is_exact_pid_and_path_scoped(self) -> None:
        expected = {
            3210: Path(
                "/mnt/c/audio/instances/audio-host/stage/SolomonDark.exe"
            )
        }
        windows_path = (
            r"C:\audio\instances\audio-host\stage\SolomonDark.exe"
        )
        completed = mock.Mock(
            returncode=0,
            stdout="activated SolomonDark pid=3210 hwnd=42\n",
            stderr="",
        )
        with (
            mock.patch.object(
                MODULE,
                "validate_owned_processes",
                return_value={"3210": windows_path},
            ) as validate,
            mock.patch.object(
                MODULE,
                "path_for_powershell",
                return_value=r"C:\repo\scripts\activate_window.py",
            ),
            mock.patch.object(
                MODULE.subprocess,
                "run",
                return_value=completed,
            ) as run,
        ):
            activated = MODULE.activate_owned_game_window(3210, expected)

        self.assertEqual(validate.call_count, 2)
        self.assertIn(r"C:\repo\scripts\activate_window.py", run.call_args.args[0])
        self.assertEqual(activated["process_id"], 3210)
        self.assertEqual(activated["after"], windows_path)

    def test_window_activation_refuses_unowned_pid(self) -> None:
        with self.assertRaisesRegex(
            MODULE.VerifyFailure,
            "refusing to activate unowned PID",
        ):
            MODULE.activate_owned_game_window(
                9876,
                {
                    3210: Path(
                        "/mnt/c/audio/instances/audio-host/stage/SolomonDark.exe"
                    )
                },
            )

    def test_post_stock_cast_state_is_not_replayed_after_native_activity(self) -> None:
        source = (
            ROOT
            / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/"
            "pending_cast_processing.inl"
        ).read_text(encoding="utf-8")
        ownership_comment = (
            "// ProcessPendingBotCast runs after stock. Re-arm only a startup that"
        )
        section = source.split(ownership_comment, 1)[1].split(
            "if (refresh_ongoing_target_state)",
            1,
        )[0]

        self.assertIn("native_activity_after_stock", section)
        self.assertIn("ongoing.startup_in_progress", section)
        self.assertIn("!ongoing.post_stock_dispatch_attempted", section)
        self.assertIn("!native_activity_after_stock", section)
        self.assertNotIn("kActorPreviousSkillIdOffset", section)

    def test_multiplayer_lightning_normalizes_the_organic_wave_target(self) -> None:
        spell_source = (
            ROOT
            / "SolomonDarkModLoader/src/run_lifecycle/spell_cast_hooks.inl"
        ).read_text(encoding="utf-8")
        air_hook = spell_source.split(
            "void __fastcall HookSpellCast_018",
            1,
        )[1].split("void __fastcall HookSpellCast_020", 1)[0]
        self.assertIn(
            "TryResolveLocalMultiplayerAirPrimaryNativeTarget",
            air_hook,
        )
        self.assertIn(
            "context.primary_target_actor_address = target_actor_address",
            air_hook,
        )
        self.assertNotIn("ApplyNativePrimaryTargetHandle(", air_hook)

        target_refresh_hook = spell_source.split(
            "void __fastcall HookAirLightningPrimaryTargetRefresh",
            1,
        )[1].split("void* __fastcall HookAirLightningChainTarget", 1)[0]
        self.assertIn("original(self, unused_edx)", target_refresh_hook)
        self.assertIn(
            "kActorSpellTargetGroupByteOffset",
            target_refresh_hook,
        )
        self.assertIn(
            "stock_target_group < kAirLightningSpecialTargetGroup",
            target_refresh_hook,
        )
        self.assertIn("ApplyNativePrimaryTargetHandle(", target_refresh_hook)
        self.assertLess(
            target_refresh_hook.index("original(self, unused_edx)"),
            target_refresh_hook.index("ApplyNativePrimaryTargetHandle("),
        )

        input_source = (
            ROOT
            / "SolomonDarkModLoader/src/mod_loader_gameplay/"
            "public_api_input_queueing.inl"
        ).read_text(encoding="utf-8")
        handle_writer = input_source.split(
            "bool ApplyNativePrimaryTargetHandle(",
            1,
        )[1].split(
            "bool QueueLocalPlayerNativeDispatcherPrimaryCast(",
            1,
        )[0]
        self.assertIn("kActorSpellTargetGroupByteOffset", handle_writer)
        self.assertIn("kActorSpellTargetSlotShortOffset", handle_writer)
        self.assertNotIn("kActorAimTargetXOffset", handle_writer)
        self.assertNotIn("ApplyWizardActorFacingState", handle_writer)

        target_source = (
            ROOT
            / "SolomonDarkModLoader/src/multiplayer_local_transport/"
            "cast_target_resolution.inl"
        ).read_text(encoding="utf-8")
        resolver = target_source.split(
            "bool TryResolveLocalMultiplayerAirPrimaryNativeTargetInternal(",
            1,
        )[1].split("bool IsRunEnemyAlignedWithPlayerCastAim(", 1)[0]
        self.assertIn("IsLocalTransportEnabled()", resolver)
        self.assertNotIn("IsLocalTransportClient()", resolver)
        self.assertIn("TryFindLocalRunEnemyForCastAim(", resolver)
        self.assertIn("ResolveLocalRunEnemyNetworkActorId(target_actor)", resolver)
        self.assertIn("target_actor.dead", resolver)

    def test_client_damage_claims_use_exact_native_damage_events_only(self) -> None:
        damage_hook = (
            ROOT
            / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
            "badguy_damage_hook.inl"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "CaptureLocalReplicatedEnemyDamageBeforeNativeCall",
            damage_hook,
        )
        self.assertIn(
            "ResolveDamageSourceParticipantId(context_source)",
            damage_hook,
        )
        self.assertIn(
            "ObserveLocalPlayerReplicatedRunEnemyDamageEvent",
            damage_hook,
        )
        self.assertLess(
            damage_hook.index("capture.hp_before - hp_after"),
            damage_hook.index(
                "ObserveLocalPlayerReplicatedRunEnemyDamageEvent"
            ),
        )

        reconciliation = (
            ROOT
            / "SolomonDarkModLoader/src/mod_loader_gameplay/"
            "world_snapshot_reconciliation/run_enemy_health_and_status.inl"
        ).read_text(encoding="utf-8")
        self.assertNotIn(
            "multiplayer::QueueLocalEnemyDamageClaim(",
            reconciliation,
        )
        self.assertNotIn(
            "multiplayer::ObserveReplicatedRunEnemyDamage(",
            reconciliation,
        )

        damage_sync = (
            ROOT
            / "SolomonDarkModLoader/src/multiplayer_local_transport/"
            "client_enemy_damage_sync.inl"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "ObserveLocalPlayerReplicatedRunEnemyDamageEventInternal",
            damage_sync,
        )
        self.assertIn(
            "g_local_native_spell_damage_dispatch_skill_id",
            damage_sync,
        )
        self.assertIn(
            "recent_cast ? g_local_transport.recent_local_cast_skill_id : 0",
            damage_sync,
        )
        self.assertNotIn("BuildSceneActorMapByAddress", damage_sync)
        self.assertNotIn(
            "ObserveReplicatedRunEnemyDamageInternal",
            damage_sync,
        )

        transport_header = (
            ROOT
            / "SolomonDarkModLoader/include/multiplayer_local_transport.h"
        ).read_text(encoding="utf-8")
        self.assertNotIn(
            "void ObserveReplicatedRunEnemyDamage(",
            transport_header,
        )

    def test_exact_damage_accumulator_releases_paired_hp_cursors_after_quiescence(
        self,
    ) -> None:
        damage_sync = (
            ROOT
            / "SolomonDarkModLoader/src/multiplayer_local_transport/"
            "client_enemy_damage_sync.inl"
        ).read_text(encoding="utf-8")
        observe_section = damage_sync.split(
            "void ObserveLocalPlayerReplicatedRunEnemyDamageEventInternal(",
            1,
        )[1].split(
            "bool SendLocalEnemyDamageClaim(",
            1,
        )[0]
        send_section = damage_sync.split(
            "void SendObservedLocalEnemyDamageClaims(",
            1,
        )[1].split(
            "std::vector<QueuedLocalEnemyDamageClaim> TakeQueuedLocalEnemyDamageClaims(",
            1,
        )[0]
        self.assertIn("observed.in_flight_claim_sequence != 0", send_section)
        self.assertIn("observed.skill_id", send_section)
        self.assertIn(
            "observed.pending_damage - claim_damage",
            send_section,
        )
        self.assertIn(
            "observed.in_flight_after_hp = claim_after_hp",
            send_section,
        )
        self.assertNotIn(
            "observed.reference_hp_valid = false",
            observe_section,
        )
        self.assertIn(
            "kEnemyDamageClaimReferenceHoldMs",
            send_section,
        )
        self.assertIn(
            "now_ms - observed.last_damage_observed_ms >=",
            send_section,
        )
        self.assertIn(
            "observed.reference_hp_valid = false",
            send_section,
        )
        self.assertIn(
            "g_local_transport.last_enemy_claimed_hp_by_network_id.erase("
            "network_actor_id);",
            "".join(send_section.split()),
        )

    def test_bounded_release_edge_is_presented_once_immediately_before_stock(self) -> None:
        tick_source = (
            ROOT
            / "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
            "actor_tick/player_actor_tick_hook.inl"
        ).read_text(encoding="utf-8")
        edge_section = tick_source.split(
            "const bool apply_bounded_release_edge =",
            1,
        )[1].split("InvokeWithParticipantConcentrationContext(", 1)[0]

        self.assertIn("ongoing_cast.bounded_release_requested", edge_section)
        self.assertIn(
            "ongoing_cast.bounded_release_edge_pending",
            edge_section,
        )
        self.assertIn(
            "ongoing_cast.bounded_release_edge_pending = false",
            edge_section,
        )
        self.assertIn("ClearSelectionBrainTarget", edge_section)
        self.assertIn("kActorControlBrainStateIdOffset", edge_section)
        self.assertIn("kUnknownAnimationStateId", edge_section)
        self.assertNotIn("kActorPrimarySkillIdOffset", edge_section)
        self.assertNotIn("kActorPreviousSkillIdOffset", edge_section)

        processing_source = (
            ROOT
            / "SolomonDarkModLoader/src/mod_loader_gameplay/bot_casting/"
            "pending_cast_processing.inl"
        ).read_text(encoding="utf-8")
        release_section = processing_source.split(
            "const float finalized_release_charge =",
            1,
        )[1].split("const std::string release_reason =", 1)[0]
        self.assertNotIn("kActorPrimarySkillIdOffset", release_section)
        self.assertNotIn("kActorPreviousSkillIdOffset", release_section)
        self.assertIn(
            "ongoing.bounded_release_edge_pending = true",
            processing_source,
        )


if __name__ == "__main__":
    unittest.main()
