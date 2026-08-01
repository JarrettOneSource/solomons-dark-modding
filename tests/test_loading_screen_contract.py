from __future__ import annotations

import hashlib
import re
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKGROUND = ROOT / "assets/loading/Wizards_dire_BG.png"
EXPECTED_BACKGROUND_SHA256 = (
    "251365e025129972707b436d441d52ae2c5f8199bc3f80a1c4e03b2a28a1180c"
)


class LoadingScreenContractTests(unittest.TestCase):
    def test_owner_approved_background_is_exact_1920_by_1080_copy(self) -> None:
        data = BACKGROUND.read_bytes()
        self.assertEqual(
            hashlib.sha256(data).hexdigest(),
            EXPECTED_BACKGROUND_SHA256,
        )
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", data[16:24]), (1920, 1080))

    def test_progress_is_discrete_monotonic_native_stage_data(self) -> None:
        source = (
            ROOT / "SolomonDarkModLoader/src/loading_screen.cpp"
        ).read_text(encoding="utf-8")
        progress_values = [
            float(value)
            for value in re.findall(
                r'\{LoadingScreenStage::\w+,\s*"[^"]+",\s*"[^"]+",\s*([0-9.]+)f\}',
                source,
            )
        ]

        self.assertEqual(len(progress_values), 20)
        self.assertEqual(progress_values, sorted(progress_values))
        self.assertEqual(progress_values[-1], 1.0)
        self.assertIn("definition.progress > current.progress", source)
        self.assertIn('"boneyard_loader"', source)
        self.assertIn('"pending_level_kind"', source)
        self.assertIn("IsArenaRegion(arena)", source)
        self.assertEqual(source.count("std::uintptr_t path_word_6"), 4)
        self.assertNotIn("progress +=", source)

    def test_renderer_cover_crops_and_delays_presentation_only(self) -> None:
        renderer = (
            ROOT / "SolomonDarkModLoader/src/loading_screen_renderer.cpp"
        ).read_text(encoding="utf-8")
        native_present = (
            ROOT
            / "SolomonDarkModLoader/src/loading_screen_native_present.cpp"
        ).read_text(encoding="utf-8")
        internal = (
            ROOT / "SolomonDarkModLoader/src/loading_screen_internal.h"
        ).read_text(encoding="utf-8")
        for token in (
            "kBottomBandHeightFraction = 0.18f",
            "kProgressBarWidthFraction = 0.60f",
            "viewport_aspect > image_aspect",
            "visible_height =",
            "visible_width =",
            "D3DTEXF_LINEAR",
        ):
            self.assertIn(token, renderer)
        self.assertIn(
            "kLoadingScreenPresentationDelayMs = 150",
            internal,
        )
        self.assertIn("device->BeginScene()", native_present)
        self.assertIn("device->EndScene()", native_present)
        self.assertIn("device->Present(", native_present)
        self.assertIn(
            "SDMOD_LOADING_SCREEN_CAPTURE_DIRECTORY",
            native_present,
        )
        self.assertNotIn("progress +=", renderer)

    def test_multiplayer_progress_comes_from_join_and_barrier_state(self) -> None:
        join = (
            ROOT / "SolomonDarkModLoader/src/multiplayer_join_flow.cpp"
        ).read_text(encoding="utf-8")
        progress = (
            ROOT
            / "SolomonDarkModLoader/src/multiplayer_join_flow/"
            "loading_screen_progress.inl"
        ).read_text(encoding="utf-8")
        phase = (
            ROOT
            / "SolomonDarkModLoader/src/multiplayer_join_flow/"
            "phase_state.inl"
        ).read_text(encoding="utf-8")
        tick = (
            ROOT
            / "SolomonDarkModLoader/src/multiplayer_join_flow/"
            "tick_state_machine.inl"
        ).read_text(encoding="utf-8")
        barrier = (
            ROOT
            / "SolomonDarkModLoader/src/multiplayer_local_transport/"
            "run_loading_barrier_sync.inl"
        ).read_text(encoding="utf-8")

        self.assertIn("phase_state.inl", join)
        self.assertIn("loading_screen_progress.inl", phase)
        self.assertIn("UpdateLoadingScreenForRuntime", tick)
        self.assertIn("LoadingScreenStage::ConnectingTransport", progress)
        for token in (
            "LoadingScreenStage::JoiningLobby",
            "LoadingScreenStage::AuthenticatingSession",
            "runtime.transport_route_ready",
            "runtime.host_settings_checkpoint_received",
            "LoadingScreenStage::ReceivingHostCheckpoint",
            "runtime.world_snapshot.valid",
            "runtime.host_wave_checkpoint_run_nonce",
            "LoadingScreenStage::MaterializingParticipants",
        ):
            self.assertIn(token, progress)
        self.assertNotIn(
            "LoadingScreenStage::WaitingForParticipants",
            progress,
        )
        self.assertIn(
            'if (reason != "new_run")',
            barrier,
        )
        self.assertIn(
            "LoadingScreenStage::ReceivingRunPlan",
            barrier,
        )
        self.assertIn(
            "runtime_state.world_snapshot.valid",
            barrier,
        )
        self.assertIn(
            "runtime_state.host_wave_checkpoint_run_nonce",
            barrier,
        )
        self.assertIn(
            "!visible_participant_ids.empty()",
            barrier,
        )
        self.assertIn("LoadingScreenStage::WaitingForParticipants", barrier)
        self.assertIn("LoadingScreenStage::ConfirmingParticipants", barrier)
        self.assertIn("CompleteLoadingScreen();", barrier)

    def test_host_loadout_barrier_keeps_the_image_and_suppresses_the_bar(self) -> None:
        header = (
            ROOT / "SolomonDarkModLoader/include/loading_screen.h"
        ).read_text(encoding="utf-8")
        state = (
            ROOT / "SolomonDarkModLoader/src/loading_screen.cpp"
        ).read_text(encoding="utf-8")
        renderer = (
            ROOT / "SolomonDarkModLoader/src/loading_screen_renderer.cpp"
        ).read_text(encoding="utf-8")
        progress = (
            ROOT
            / "SolomonDarkModLoader/src/multiplayer_join_flow/"
            "loading_screen_progress.inl"
        ).read_text(encoding="utf-8")

        self.assertIn("bool progress_bar_visible = true;", header)
        self.assertIn("void BeginLoadingScreenBarrier(", header)
        self.assertIn("current.progress_bar_visible = false;", state)
        self.assertIn("if (snapshot.progress_bar_visible)", renderer)
        self.assertIn("JoinFlowPhase::WaitingForHostLoadout", progress)
        self.assertIn(
            '"Waiting for host to pick loadout"',
            progress,
        )
        self.assertIn("BeginLoadingScreenBarrier(", progress)
        self.assertIn(
            "kLoadingScreenPresentationDelayMs = 150",
            (
                ROOT
                / "SolomonDarkModLoader/src/loading_screen_internal.h"
            ).read_text(encoding="utf-8"),
        )

    def test_lua_runtime_exposes_actual_loading_screen_state(self) -> None:
        bindings = (
            ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp"
        ).read_text(encoding="utf-8")
        harness = (
            ROOT / "tools/_real_flow_e2e/runtime.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "PushLoadingScreenSnapshot(state, GetLoadingScreenSnapshot());",
            bindings,
        )
        self.assertIn('"loading_screen"', bindings)
        self.assertIn('emit("loading.active"', harness)
        self.assertIn('state["loadingScreen"]["active"]', harness)
        self.assertIn('"progress_bar_visible"', bindings)

    def test_asset_is_staged_packaged_and_loaded_from_sdmod_assets(self) -> None:
        materializer = (
            ROOT
            / "SolomonDarkModLauncher/src/Staging/"
            "LoadingScreenAssetMaterializer.cs"
        ).read_text(encoding="utf-8")
        package = (ROOT / "scripts/New-BetaReleasePackage.ps1").read_text(
            encoding="utf-8"
        )
        loader = (
            ROOT / "SolomonDarkModLoader/src/mod_loader.cpp"
        ).read_text(encoding="utf-8") + (
            ROOT / "SolomonDarkModLoader/src/mod_loader/initialize.inl"
        ).read_text(encoding="utf-8")

        self.assertIn('".sdmod"', materializer)
        self.assertIn('"assets"', materializer)
        self.assertIn('Copy-Item (Join-Path $root "assets")', package)
        self.assertIn('"Wizards_dire_BG.png"', loader)

        ui_project = (
            ROOT
            / "SolomonDarkModLauncher.UI/"
            "SolomonDarkModLauncher.UI.csproj"
        ).read_text(encoding="utf-8")
        ui_view = (
            ROOT
            / "SolomonDarkModLauncher.UI/src/Views/MainWindow.xaml"
        ).read_text(encoding="utf-8")
        ui_progress_path = (
            ROOT
            / "SolomonDarkModLauncher.UI/src/ViewModels/"
            "MatchLoadingProgress.cs"
        )
        ui_view_model = (
            ROOT
            / "SolomonDarkModLauncher.UI/src/ViewModels/"
            "MainWindowViewModel.cs"
        ).read_text(encoding="utf-8")
        ui_theme = (
            ROOT
            / "SolomonDarkModLauncher.UI/src/Themes/"
            "LauncherTheme.xaml"
        ).read_text(encoding="utf-8")
        command_executor = (
            ROOT
            / "SolomonDarkModLauncher/src/App/"
            "LauncherCommandExecutor.cs"
        ).read_text(encoding="utf-8")
        # Owner direction (2026-07-27): the desktop launcher window never
        # presents the match loading screen. The art ships to the staged
        # game only; the launcher keeps its plain utility progress UI.
        self.assertFalse(ui_progress_path.exists())
        self.assertNotIn("Wizards_dire_BG", ui_project)
        self.assertNotIn("Wizards_dire_BG", ui_view)
        self.assertNotIn("MatchLoadingProgressBarStyle", ui_view)
        self.assertNotIn("MatchLoadingProgressBarStyle", ui_theme)
        self.assertNotIn("MatchLoading", ui_view_model)
        self.assertNotIn("UpdateProgressScope", command_executor)

    def test_live_verifier_uses_only_the_fieldfix_instances_and_ports(self) -> None:
        verifier = (
            ROOT / "tools/verify_loading_screen.py"
        ).read_text(encoding="utf-8")

        self.assertIn('INSTANCE_PREFIX = "ffix"', verifier)
        self.assertIn("HOST_PORT = 49711", verifier)
        self.assertIn("CLIENT_PORT = 49712", verifier)
        self.assertIn("enable_audio=False", verifier)
        self.assertIn("disable_multiplayer_transport=(", verifier)
        self.assertIn("quick_start=multiplayer_enabled", verifier)
        self.assertIn("stop_exact_game_processes(launch)", verifier)
        self.assertNotIn("kill_existing=True", verifier)

        launcher_verifier = (
            ROOT / "tools/verify_match_loading_screen.py"
        ).read_text(encoding="utf-8")
        self.assertIn('INSTANCE_NAME = "ffix-loading"', launcher_verifier)
        self.assertIn("PORT = 49712", launcher_verifier)
        self.assertIn('"disableAudio": True', launcher_verifier)
        self.assertIn('"gameLaunched": False', launcher_verifier)
        self.assertIn(
            "visibleStateUnchanged",
            launcher_verifier,
        )
        self.assertIn("OVERLAY_MARKERS", launcher_verifier)
        self.assertIn("Reading the host's grimoire", launcher_verifier)
        self.assertIn('"Match loading progress"', launcher_verifier)
        self.assertIn(
            'record["overlayAbsent"] = True',
            launcher_verifier,
        )
        self.assertNotIn("Start-Process SolomonDark.exe", launcher_verifier)


if __name__ == "__main__":
    unittest.main()
