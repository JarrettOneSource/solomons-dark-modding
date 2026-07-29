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


if __name__ == "__main__":
    unittest.main()
