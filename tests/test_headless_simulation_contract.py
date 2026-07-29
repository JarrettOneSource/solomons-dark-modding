#!/usr/bin/env python3
"""Contracts for hidden, precision-preserving headless simulation."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class HeadlessSimulationContractTests(unittest.TestCase):
    def test_launcher_routes_only_single_player_headless_launches(self) -> None:
        parser = read(
            "SolomonDarkModLauncher/src/Commands/LauncherCommandParser.cs"
        )
        launcher = read(
            "SolomonDarkModLauncher/src/Launch/StagedGameLauncher.cs"
        )

        self.assertIn('arg == "--headless"', parser)
        self.assertIn("headless && mode != LauncherMode.Launch", parser)
        self.assertIn(
            "MultiplayerLaunchMode.Host or MultiplayerLaunchMode.Join",
            parser,
        )
        self.assertIn("HeadlessLaunchEnvironment.Apply(", launcher)
        self.assertIn("disableAudio || headless", launcher)
        self.assertIn("CreateNoWindow = headless", launcher)
        self.assertIn("ProcessWindowStyle.Hidden", launcher)
        self.assertIn(
            "waitForInputIdle: !disableAudio && !headless",
            launcher,
        )

    def test_native_tick_uses_stock_batch_and_render_skip_fields(self) -> None:
        native = read(
            "SolomonDarkModLoader/src/headless_simulation.cpp"
        )
        app_tick = read(
            "SolomonDarkModLoader/src/background_focus_bypass.cpp"
        )
        layout = read("config/binary-layout.ini")

        expected_fields = {
            "scheduler_baseline": "0x00000C04",
            "scheduler_tick": "0x00000C08",
            "render_skip": "0x00000C1C",
            "simulation_batch": "0x00000D9C",
        }
        section = layout.split("[headless.fields]", 1)[1].split(
            "\n[", 1
        )[0]
        for key, value in expected_fields.items():
            self.assertRegex(
                section,
                rf"(?m)^{re.escape(key)}={re.escape(value)}$",
            )
            self.assertIn(f'"{key}"', native)

        self.assertIn("const std::int32_t scheduler_tick = -1;", native)
        self.assertIn("kTargetBatchDurationMilliseconds = 250.0", native)
        self.assertIn("kMaximumSimulationBatchSize = 262144", native)
        self.assertIn("ShowWindow(state.game_window, SW_HIDE)", native)
        self.assertIn(
            "kGameplaySceneSettleMilliseconds = 1000",
            native,
        )
        self.assertIn("GetLoadingScreenSnapshot().active", app_tick)
        self.assertIn("if (now_ms < state.scene_settle_deadline_ms)", native)
        self.assertIn(
            "state.original_simulation_batch_size",
            native,
        )
        self.assertIn("ObserveHeadlessSimulationWindow(hwnd);", app_tick)
        self.assertIn("IsHeadlessGameplaySceneActive()", app_tick)
        for scene_kind in ("arena", "region", "tutorial"):
            self.assertIn(f'scene.kind == "{scene_kind}"', app_tick)
        self.assertIn("if (!simulation_scene_active)", native)
        self.assertIn("state.original_simulation_batch_size", native)
        self.assertNotIn("0x00820230", native)
        self.assertNotIn("kGameTimingScaleGlobal", native)

        prepare = app_tick.index("PrepareHeadlessSimulationTick(")
        stock = app_tick.index("original(app, edx);", prepare)
        finish = app_tick.index("FinishHeadlessSimulationTick(app);", stock)
        self.assertLess(prepare, stock)
        self.assertLess(stock, finish)

    def test_status_reports_native_activation(self) -> None:
        status = read("SolomonDarkModLoader/src/startup_status.cpp")
        monitor = read(
            "SolomonDarkModLauncher/src/Launch/"
            "LoaderStartupStatusMonitor.cs"
        )
        json_console = read(
            "SolomonDarkModLauncher/src/App/LauncherJsonConsole.cs"
        )

        self.assertIn("headlessSimulationEnabled", status)
        self.assertIn("HeadlessSimulationEnabled", monitor)
        self.assertIn(
            "StartupStatus.HeadlessSimulationEnabled",
            json_console,
        )

    def test_solo_automation_can_request_headless_without_network_flags(
        self,
    ) -> None:
        launcher = read("scripts/Launch-LocalSoloSession.ps1")

        self.assertIn("[switch]$Headless", launcher)
        self.assertIn("[switch]$DisableMultiplayerTransport", launcher)
        self.assertIn('if ($Headless) {', launcher)
        self.assertIn('$arguments += "--headless"', launcher)
        self.assertIn("headlessEnabled = [bool]$Headless", launcher)
        self.assertIn(
            "multiplayerTransportEnabled = "
            "-not [bool]$DisableMultiplayerTransport",
            launcher,
        )
        self.assertIn(
            'if (-not $DisableMultiplayerTransport) {',
            launcher,
        )
        self.assertIn("[string]$ResultOutputPath", launcher)
        self.assertIn(
            "[System.IO.File]::WriteAllText($ResultOutputPath, $summaryJson)",
            launcher,
        )
        self.assertNotIn('"--multiplayer", "off"', launcher)

    def test_solo_automation_validates_and_hashes_boneyard_override(
        self,
    ) -> None:
        launcher = read("scripts/Launch-LocalSoloSession.ps1")
        self.assertIn(
            "[string]$TestSurvivalBoneyardOverride",
            launcher,
        )
        self.assertIn(
            "SDMOD_TEST_SURVIVAL_BONEYARD_OVERRIDE",
            launcher,
        )
        self.assertIn("'^\\.boneyard$'", launcher)
        self.assertIn("requestedBoneyardSha256", launcher)
        self.assertIn("stagedBoneyardSha256", launcher)
        self.assertIn(
            '"stage\\data\\levels\\survival.boneyard"',
            launcher,
        )

    def test_live_trainer_uses_disposable_seeded_composition_sessions(
        self,
    ) -> None:
        trainer = read("tools/train_bot_policy.py")
        bridge = read("tools/ml_bot/bridge.py")
        composition = read(
            "tools/ml_bot/team-compositions.json"
        )
        self.assertIn("for iteration in range(1, args.iterations + 1)", trainer)
        self.assertIn("session = SoloSession(", trainer)
        self.assertIn(
            "max_participants=composition.participant_count + 1",
            trainer,
        )
        self.assertIn("finally:", trainer)
        self.assertIn("session.close()", trainer)
        self.assertIn("session.set_run_seed(requested_seed)", trainer)
        self.assertIn('"observed_run_nonce"', trainer)
        self.assertIn('"layout_sha256"', trainer)
        self.assertIn('"composition"', trainer)
        self.assertIn("trajectory_counts", trainer)
        self.assertIn("sd.rng.set_seed(requested)", bridge)
        self.assertNotIn("slot <= 3", bridge)
        for behavior in ("skirmisher", "guardian", "striker"):
            self.assertIn(f'"{behavior}"', composition)
        self.assertIn('"learned_count": 2', composition)

    def test_solo_bridge_completes_on_the_published_launch_result(
        self,
    ) -> None:
        bridge = read("tools/ml_bot/bridge.py")
        self.assertIn(
            "self.launch_wrapper_process = subprocess.Popen(",
            bridge,
        )
        self.assertIn(
            "requested and staged boneyard hashes do not match",
            bridge,
        )
        self.assertIn("if result_path.is_file():", bridge)
        self.assertIn("self._reap_launch_wrapper()", bridge)
        self.assertNotIn(
            "completed = subprocess.run(\n"
            "                arguments,\n"
            "                cwd=ROOT,\n"
            "                stdout=subprocess.DEVNULL",
            bridge,
        )

    def test_pair_godmode_waits_for_the_lua_state_handoff(self) -> None:
        launcher = read("scripts/Launch-LocalMultiplayerPair.ps1")
        godmode = launcher.split(
            "function Enable-InstanceGodMode {", 1
        )[1].split("function Get-StagedGraphicsResolution {", 1)[0]
        self.assertIn("$deadline = (Get-Date).AddSeconds(30)", godmode)
        self.assertIn("while ((Get-Date) -lt $deadline)", godmode)
        self.assertIn("} catch {", godmode)
        self.assertIn("Start-Sleep -Milliseconds 250", godmode)
        self.assertIn("if sd.state.is_authority() then", godmode)
        self.assertIn("sd.bots.list() or {}", godmode)
        self.assertIn(
            "state.progression_runtime_state_address",
            godmode,
        )
        self.assertIn("emit('sustained_bots'", godmode)


if __name__ == "__main__":
    unittest.main()
