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

    def test_solo_control_compares_deterministic_cast_lifecycle_only(self) -> None:
        self.assertIn(
            "gather_bass_channel_play",
            MODULE.CAST_LIFECYCLE_TRIGGER_KEYS,
        )
        self.assertIn("gather_loop_stop", MODULE.CAST_LIFECYCLE_TRIGGER_KEYS)
        self.assertNotIn("rockhit_one_shot", MODULE.CAST_LIFECYCLE_TRIGGER_KEYS)

    def test_live_gate_is_audio_enabled_and_process_scoped(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("enable_audio=True", source)
        self.assertIn('"-EnableAudio"', source)
        self.assertIn("validate_owned_processes", source)
        self.assertIn("host_to_client", source)
        self.assertIn("client_to_host", source)
        self.assertIn("run_solo_case", source)
        self.assertNotIn("stop_games(", source)

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
