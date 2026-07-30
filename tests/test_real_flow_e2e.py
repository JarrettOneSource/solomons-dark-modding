from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from PIL import Image

from tools._real_flow_e2e.config import ConfigError, HarnessConfig
from tools._real_flow_e2e.evidence import (
    EvidenceError,
    packet_accounting,
    rendered_enemy_assertion,
    steam_transport_assertion,
    write_manifest,
)
from tools._real_flow_e2e.runtime import (
    damage_click_targets,
    damage_enemy_with_real_input,
    normalize_state,
)
from tools._real_flow_e2e.wan import _damage_remote_enemy
from tools._real_flow_e2e.windows import (
    ProcessRecord,
    WindowsHarnessError,
    close_exact_owned_processes,
)
from tools._real_flow_e2e.ws20 import Ws20Peer


ROOT = Path(__file__).resolve().parents[1]


class RealFlowE2ETests(unittest.TestCase):
    def _config_document(self, root: Path) -> dict[str, object]:
        source = root / "source"
        package = root / "package"
        game = root / "game"
        (source / ".git").mkdir(parents=True)
        (package / "launcher").mkdir(parents=True)
        game.mkdir()
        (package / "SolomonDarkMultiplayerBeta.exe").touch()
        (package / "launcher/SolomonDarkModLauncher.exe").touch()
        (game / "SolomonDark.exe").touch()
        return {
            "schemaVersion": 1,
            "runName": "netrepro-contract",
            "topology": "loopback_windows",
            "sourceRoot": str(source),
            "packageRoot": str(package),
            "gameDirectory": str(game),
            "evidenceRoot": str(root / "evidence"),
            "directoryUrl": "https://solomondarker.com",
            "privacy": "friends",
            "expectedSourceSha": "1" * 40,
            "timeoutSeconds": 120,
            "samplingSeconds": 0.25,
            "host": {
                "platform": "windows_local",
                "launcherScope": "real-host",
                "instance": "real-host",
                "playerName": "Host",
                "pipeName": "RealFlowHost",
                "participantId": "0x1001",
                "localPort": 50711,
                "remoteHost": "127.0.0.1",
                "remotePort": 50712,
                "matchStartActions": [
                    {
                        "kind": "click",
                        "x": 0.95,
                        "y": 0.94,
                    }
                ],
            },
            "client": {
                "platform": "windows_local",
                "launcherScope": "real-client",
                "instance": "real-client",
                "playerName": "client B",
                "pipeName": "RealFlowClient",
                "participantId": "0x1002",
                "localPort": 50712,
                "remoteHost": "127.0.0.1",
                "remotePort": 50711,
                "matchStartActions": [],
            },
        }

    def _load_document(
        self,
        root: Path,
        document: dict[str, object],
    ) -> HarnessConfig:
        config = root / "real-flow.json"
        config.write_text(
            json.dumps(document),
            encoding="utf-8",
        )
        return HarnessConfig.load(config)

    def _render_state(self, *, projected: bool = False) -> dict[str, object]:
        return {
            "viewport": {"width": 100, "height": 100},
            "camera": {
                "sceneAvailable": True,
                "originX": 0.0,
                "originY": 0.0,
                "scale": 1.0,
            },
            "replicatedEnemies": [
                {
                    "network_id": 101,
                    "dead": False,
                    "screen_valid": projected,
                    "screen_x": 50.0,
                    "screen_y": 50.0,
                }
            ],
            "enemyBindings": [
                {
                    "network_id": 101,
                    "address": 4096,
                    "matched": True,
                    "parked": False,
                    "removed": False,
                }
            ],
            "nativeEnemies": [
                {
                    "network_id": 101,
                    "dead": False,
                    "x": 50.0,
                    "y": 50.0,
                }
            ],
        }

    def test_loopback_config_is_confined_to_reserved_ports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = self._config_document(root)
            config = self._load_document(root, document)

            self.assertEqual(config.host.local_port, 50711)
            self.assertEqual(config.client.local_port, 50712)

            document["host"]["localPort"] = 50713  # type: ignore[index]
            with self.assertRaisesRegex(ConfigError, "50711/50712"):
                self._load_document(root, document)

    def test_nfo_config_requires_exact_stage_ports_and_own_proton(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = self._config_document(root)
            proton = root / "GE-Proton.tar.gz"
            proton.touch()
            document["topology"] = "wan_udp_nfo"
            document["protonArchive"] = str(proton)
            host = document["host"]  # type: ignore[assignment]
            client = document["client"]  # type: ignore[assignment]
            host["localPort"] = 51611
            host["remotePort"] = 51612
            host["remoteHost"] = "203.0.113.10"
            client["platform"] = "linux_ssh_proton"
            client["localPort"] = 51612
            client["remotePort"] = 51611
            client["remoteHost"] = "198.51.100.20"
            client["ssh"] = {
                "target": "nfo-test",
                "stageRoot": "/root/sd-netrepro-20260729",
            }

            config = self._load_document(root, document)

            self.assertEqual(
                config.client.ssh.stage_root,  # type: ignore[union-attr]
                "/root/sd-netrepro-20260729",
            )
            document["client"]["ssh"]["stageRoot"] = "/root/other"  # type: ignore[index]
            with self.assertRaisesRegex(
                ConfigError,
                "/root/sd-netrepro-20260729",
            ):
                self._load_document(root, document)

    def test_ws20_config_requires_windows_ssh_and_confined_stage(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = self._config_document(root)
            document["topology"] = "steam_windows_ws20"
            host = document["host"]  # type: ignore[assignment]
            client = document["client"]  # type: ignore[assignment]
            for peer in (host, client):
                peer["localPort"] = 0
                peer["remotePort"] = 0
                peer["remoteHost"] = ""
            client["platform"] = "windows_ssh"
            client["ssh"] = {
                "target": "temporary-user@workstation.example",
                "keyPath": "/run/user/1000/ws20-key",
                "stageRoot": r"%USERPROFILE%\sd-netrepro-stage",
            }

            config = self._load_document(root, document)

            self.assertEqual(config.client.platform, "windows_ssh")
            redacted = config.redacted()
            self.assertNotIn("sshTarget", redacted["client"])
            self.assertNotIn("keyPath", json.dumps(redacted))
            self.assertEqual(
                redacted["client"]["sshStageRoot"],
                r"%USERPROFILE%\sd-netrepro-stage",
            )
            document["client"]["ssh"]["stageRoot"] = (  # type: ignore[index]
                r"C:\Users\temporary-user\other"
            )
            with self.assertRaisesRegex(ConfigError, "sd-netrepro-stage"):
                self._load_document(root, document)

    def test_repro_controller_contains_no_forbidden_start_seam(
        self,
    ) -> None:
        paths = [
            ROOT / "tools/verify_real_flow_e2e.py",
            ROOT / "tools/_real_flow_e2e/runtime.py",
            ROOT / "tools/_real_flow_e2e/windows.py",
            ROOT / "tools/_real_flow_e2e/remote.py",
            ROOT / "tools/_real_flow_e2e/wan.py",
            ROOT / "tools/_real_flow_e2e/ws20.py",
            ROOT / "scripts/Run-RealFlowRemotePeer.sh",
            ROOT / "scripts/Run-RealFlowWindowsSessionWorker.ps1",
        ]
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in paths
        )

        for forbidden in (
            "sd.gameplay.start_waves",
            "sd.hub.start_testrun",
            "sd.hub.trigger_solomon_dig",
        ):
            self.assertNotIn(forbidden, combined)
        self.assertIn(
            "approach_solomon_and_complete_dialogue(\n"
            "            config.source_root,\n"
            "            host,",
            combined,
        )

    def test_every_launched_peer_enables_telemetry_and_disables_audio(
        self,
    ) -> None:
        windows = (
            ROOT / "tools/_real_flow_e2e/windows.py"
        ).read_text(encoding="utf-8")
        remote = (
            ROOT / "scripts/Run-RealFlowRemotePeer.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('"SDMOD_NETWORK_TELEMETRY": "1"', windows)
        self.assertIn('"SDMOD_DISABLE_AUDIO": "1"', windows)
        self.assertIn("SDMOD_NETWORK_TELEMETRY=1", remote)
        self.assertIn("SDMOD_DISABLE_AUDIO=1", remote)

    def test_nfo_game_input_targets_the_exact_staged_executable(
        self,
    ) -> None:
        remote = (
            ROOT / "scripts/Run-RealFlowRemotePeer.sh"
        ).read_text(encoding="utf-8")
        input_helper = (
            ROOT / "tools/win32_real_input.cpp"
        ).read_text(encoding="utf-8")
        game_click = remote.split(
            "game_click() {", 1
        )[1].split("invoke_lua() {", 1)[0]

        self.assertIn(
            'expected_game="$package_root/.sdmod-test-data/'
            '$scope/SolomonDarkMultiplayerBeta/runtime/instances/'
            '$instance/stage/SolomonDark.exe"',
            game_click,
        )
        self.assertIn('"$expected_game_windows"', game_click)
        self.assertIn("click-path", game_click)
        self.assertIn(
            "FindGameWindowForExactPath(expected_path.c_str())",
            input_helper,
        )
        self.assertIn(
            "ProcessPathMatches(process_id, search->expected_path)",
            input_helper,
        )

    def test_nfo_window_inventory_tolerates_disappearing_windows(
        self,
    ) -> None:
        remote = (
            ROOT / "scripts/Run-RealFlowRemotePeer.sh"
        ).read_text(encoding="utf-8")
        windows = remote.split(
            "windows_list() {", 1
        )[1].split("launcher_window() {", 1)[0]

        self.assertIn(
            "2>/dev/null | tr '\\n' ' ' || true",
            windows,
        )

    def test_observer_mod_is_inert_and_has_no_gameplay_callbacks(
        self,
    ) -> None:
        script = (
            ROOT
            / "tools/_real_flow_e2e/observer_mod/scripts/main.lua"
        ).read_text(encoding="utf-8")

        self.assertNotIn("sd.on_", script)
        self.assertNotIn("sd.events", script)
        self.assertNotIn("sd.player.set", script)
        self.assertNotIn("sd.debug.write", script)

    def test_render_assertion_rejects_unrelated_world_texture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "uniform.png"
            image = Image.new("RGB", (100, 100), (90, 100, 110))
            for y in range(8):
                for x in range(8):
                    image.putpixel((x, y), (200, 10, 220))
            image.save(capture)

            with self.assertRaisesRegex(EvidenceError, "visually uniform"):
                rendered_enemy_assertion(self._render_state(), capture)

    def test_render_assertion_projects_bound_native_actor_through_camera(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "native-camera.png"
            image = Image.new("RGB", (100, 100), (20, 20, 20))
            for y in range(45, 56):
                for x in range(45, 56):
                    image.putpixel(
                        (x, y),
                        (220, 180, 40) if (x + y) % 2 else (40, 80, 220),
                    )
            image.save(capture)

            result = rendered_enemy_assertion(
                self._render_state(),
                capture,
            )

            self.assertEqual(
                result["accepted"][0]["projectionSource"],
                "native-camera",
            )

    def test_render_assertion_accepts_enemy_health_bar_signature(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "health-bar.png"
            image = Image.new("RGB", (100, 100), (20, 20, 20))
            for y in range(12, 16):
                for x in range(10, 40):
                    image.putpixel((x, y), (210, 20, 20))
            image.save(capture)

            result = rendered_enemy_assertion(
                self._render_state(),
                capture,
            )

            self.assertTrue(result["enemyHealthBarCandidates"])
            self.assertEqual(
                result["accepted"][0]["signature"]
                if "signature" in result["accepted"][0]
                else result["accepted"][0][
                    "enemyHealthBarCandidates"
                ][0]["signature"],
                "enemy-health-bar",
            )

    def test_cleanup_accepts_a_process_that_exits_before_close(
        self,
    ) -> None:
        class RacingPowerShell:
            def run(self, script: str, *, timeout: float) -> str:
                raise WindowsHarnessError(
                    "refusing PID 8184; path changed to"
                )

        record = ProcessRecord(
            pid=8184,
            parent_pid=1,
            executable_path=r"C:\owned\SolomonDark.exe",
            command_line="",
        )
        with mock.patch(
            "tools._real_flow_e2e.windows.exact_owned_processes",
            side_effect=[[record], [], []],
        ):
            result = close_exact_owned_processes(
                RacingPowerShell(),  # type: ignore[arg-type]
                (),
            )

        self.assertTrue(result["allExitedGracefully"])
        self.assertEqual(
            result["gracefulRequests"][0]["result"],
            "exited-before-close",
        )

    def test_cleanup_still_rejects_a_live_process_path_mismatch(
        self,
    ) -> None:
        class MismatchedPowerShell:
            def run(self, script: str, *, timeout: float) -> str:
                raise WindowsHarnessError("process path changed")

        record = ProcessRecord(
            pid=8184,
            parent_pid=1,
            executable_path=r"C:\owned\SolomonDark.exe",
            command_line="",
        )
        with (
            mock.patch(
                "tools._real_flow_e2e.windows.exact_owned_processes",
                side_effect=[[record], [record]],
            ),
            self.assertRaisesRegex(
                WindowsHarnessError,
                "process path changed",
            ),
        ):
            close_exact_owned_processes(
                MismatchedPowerShell(),  # type: ignore[arg-type]
                (),
            )

    def test_packet_accounting_preserves_fragment_rejections(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            telemetry = Path(directory) / "network-telemetry.jsonl"
            rows = [
                {"event": "telemetry_start"},
                {
                    "event": "fragment_receive",
                    "kind": 31,
                    "sequence": 4,
                    "accepted": True,
                    "assembly_complete": False,
                    "logical_bytes": 1200,
                    "datagram_bytes": 1250,
                },
                {
                    "event": "fragment_receive",
                    "kind": 31,
                    "sequence": 6,
                    "accepted": False,
                    "assembly_complete": False,
                    "logical_bytes": 0,
                    "datagram_bytes": 1250,
                },
            ]
            telemetry.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )

            result = packet_accounting(telemetry)

            self.assertEqual(result["rejectedByKind"], {"31": 1})
            self.assertEqual(
                result["fragmentByKind"]["31"]["rejected"],
                1,
            )
            self.assertEqual(
                result["sequences"]["fragment_receive"]["31"][
                    "inferredMissingWithinKind"
                ],
                1,
            )

    def test_packet_accounting_reports_actual_steam_api_rejections(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            telemetry = Path(directory) / "network-telemetry.jsonl"
            rows = [
                {"event": "telemetry_start"},
                {
                    "event": "steam_send_result",
                    "kind": 5,
                    "sequence": 17,
                    "bytes": 1200,
                    "accepted": False,
                    "result_code": 25,
                },
                {
                    "event": "steam_send_result",
                    "kind": 5,
                    "sequence": 17,
                    "bytes": 1200,
                    "accepted": True,
                    "result_code": 1,
                },
                {
                    "event": "steam_route_status",
                    "connection_state": 3,
                    "pending_unreliable_bytes": 200,
                    "pending_reliable_bytes": 500,
                    "unacked_reliable_bytes": 300,
                    "queue_time_microseconds": 220000,
                    "using_relay": True,
                },
                {
                    "event": "steam_route_status",
                    "connection_state": 3,
                    "pending_unreliable_bytes": 0,
                    "pending_reliable_bytes": 0,
                    "unacked_reliable_bytes": 0,
                    "queue_time_microseconds": 1000,
                    "using_relay": False,
                },
            ]
            telemetry.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )

            result = packet_accounting(telemetry)

            self.assertEqual(
                result["steamSendResults"],
                {
                    "attempts": 2,
                    "accepted": 1,
                    "rejected": 1,
                    "resultCodes": {"1": 1, "25": 1},
                },
            )
            self.assertEqual(result["rejectedByKind"], {"5": 1})
            self.assertEqual(
                result["steamRouteStatus"],
                {
                    "samples": 2,
                    "connectedSamples": 2,
                    "relaySamples": 1,
                    "maximumQueueTimeMicroseconds": 220000,
                    "p95QueueTimeMicroseconds": 220000,
                    "maximumPendingUnreliableBytes": 200,
                    "maximumPendingReliableBytes": 500,
                    "maximumUnackedReliableBytes": 300,
                },
            )

    def test_steam_transport_assertion_requires_route_and_no_result_25(
        self,
    ) -> None:
        healthy = {
            "steamSendResults": {
                "attempts": 4,
                "accepted": 4,
                "rejected": 0,
                "resultCodes": {"1": 4},
            },
            "steamRouteStatus": {
                "samples": 3,
                "connectedSamples": 3,
                "relaySamples": 3,
                "maximumQueueTimeMicroseconds": 220000,
                "p95QueueTimeMicroseconds": 180000,
            },
        }
        self.assertEqual(
            steam_transport_assertion(healthy, role="host"),
            {
                "result25Count": 0,
                "routeSamples": 3,
                "connectedRouteSamples": 3,
                "relaySamples": 3,
                "maximumQueueTimeMicroseconds": 220000,
                "p95QueueTimeMicroseconds": 180000,
            },
        )

        saturated = json.loads(json.dumps(healthy))
        saturated["steamSendResults"]["resultCodes"]["25"] = 1
        with self.assertRaisesRegex(
            EvidenceError,
            "result-25 backpressure",
        ):
            steam_transport_assertion(saturated, role="client B")

        missing_route = json.loads(json.dumps(healthy))
        missing_route["steamRouteStatus"]["samples"] = 0
        missing_route["steamRouteStatus"]["connectedSamples"] = 0
        with self.assertRaisesRegex(
            EvidenceError,
            "connected Steam route",
        ):
            steam_transport_assertion(missing_route, role="host")

    def test_runtime_state_includes_steam_send_failure_counters(
        self,
    ) -> None:
        state = normalize_state(
            {
                "mp.steam_send_failures": "7",
                "mp.steam_reliable_send_failures": "3",
                "mp.last_steam_send_failure_result": "25",
            }
        )

        self.assertEqual(state["multiplayer"]["steamSendFailures"], 7)
        self.assertEqual(
            state["multiplayer"]["steamReliableSendFailures"],
            3,
        )
        self.assertEqual(
            state["multiplayer"]["lastSteamSendFailureResult"],
            25,
        )

    def test_runtime_state_includes_native_camera_projection(
        self,
    ) -> None:
        state = normalize_state(
            {
                "camera.available": "true",
                "camera.scene_available": "true",
                "camera.origin_x": "1250",
                "camera.origin_y": "-100",
                "camera.width": "1600",
                "camera.height": "900",
                "camera.center_x": "2050",
                "camera.center_y": "350",
                "camera.scale": "1",
            }
        )

        self.assertEqual(
            state["camera"],
            {
                "available": True,
                "sceneAvailable": True,
                "originX": 1250.0,
                "originY": -100.0,
                "width": 1600.0,
                "height": 900.0,
                "centerX": 2050.0,
                "centerY": 350.0,
                "scale": 1.0,
            },
        )

    def test_damage_targets_prioritize_interior_actor_over_nearest_edge(
        self,
    ) -> None:
        targets = damage_click_targets(
            [
                {
                    "screen_valid": True,
                    "screen_x": 468.0,
                    "screen_y": 22.0,
                    "x": 554.0,
                    "y": 133.0,
                },
                {
                    "screen_valid": True,
                    "screen_x": 1000.0,
                    "screen_y": 500.0,
                    "x": 900.0,
                    "y": 800.0,
                },
            ],
            {"x": 514.0, "y": 150.0},
            {"width": 1600, "height": 900},
            {"sceneAvailable": False},
        )

        self.assertEqual(
            targets[:2],
            [
                (0.625, 500.0 / 900.0),
                (0.2925, 22.0 / 900.0),
            ],
        )

    def test_damage_targets_use_stock_cursor_projection_when_draw_is_stale(
        self,
    ) -> None:
        targets = damage_click_targets(
            [
                {
                    "screen_valid": False,
                    "screen_x": 2046.0,
                    "screen_y": 207.0,
                    "x": 2046.0,
                    "y": 207.0,
                }
            ],
            {"x": 2050.0, "y": 250.0},
            {"width": 1600, "height": 900},
            {
                "sceneAvailable": True,
                "originX": 1250.0,
                "originY": -100.0,
                "scale": 1.0,
            },
        )

        self.assertEqual(targets[0], (796.0 / 1600.0, 307.0 / 900.0))

    def test_damage_targets_keep_offscreen_ray_as_fallback(
        self,
    ) -> None:
        targets = damage_click_targets(
            [
                {
                    "screen_valid": False,
                    "screen_x": 0.0,
                    "screen_y": 0.0,
                    "x": 400.0,
                    "y": -80.0,
                },
                {
                    "screen_valid": False,
                    "screen_x": 0.0,
                    "screen_y": 0.0,
                    "x": 800.0,
                    "y": 500.0,
                },
            ],
            {"x": 500.0, "y": 20.0},
            {"width": 1000, "height": 1000},
            {
                "sceneAvailable": True,
                "originX": 0.0,
                "originY": 0.0,
                "scale": 1.0,
            },
        )

        self.assertEqual(targets[0], (0.8, 0.5))
        self.assertEqual(targets[1], (0.49, 0.01))

    def test_damage_probe_refreshes_native_target_before_each_click(
        self,
    ) -> None:
        def state(enemy_x: float, hp: float) -> dict[str, object]:
            return {
                "scene": {"name": "testrun"},
                "viewport": {"width": 1000, "height": 1000},
                "camera": {
                    "sceneAvailable": True,
                    "originX": 0.0,
                    "originY": 0.0,
                    "scale": 1.0,
                },
                "player": {
                    "valid": True,
                    "x": 50.0,
                    "y": 50.0,
                    "hp": 50.0,
                },
                "replicatedEnemies": [
                    {
                        "network_id": 101,
                        "dead": False,
                        "hp": hp,
                        "x": enemy_x,
                        "y": 100.0,
                        "screen_valid": False,
                        "screen_x": enemy_x,
                        "screen_y": 100.0,
                    },
                    {
                        "network_id": 102,
                        "dead": False,
                        "hp": 2.5,
                        "x": 1000.0 - enemy_x,
                        "y": 900.0,
                        "screen_valid": False,
                        "screen_x": 1000.0 - enemy_x,
                        "screen_y": 900.0,
                    }
                ],
            }

        class FakePipe:
            def __init__(self) -> None:
                self.states = iter(
                    [
                        state(100.0, 2.5),
                        state(200.0, 2.5),
                        state(200.0, 1.5),
                    ]
                )

            def state(self) -> dict[str, object]:
                return next(self.states)

        clicks: list[tuple[float, float, int]] = []

        def click(
            _source: Path,
            _peer: object,
            x: float,
            y: float,
            hold_ms: int,
        ) -> str:
            clicks.append((x, y, hold_ms))
            return "ok"

        with (
            mock.patch(
                "tools._real_flow_e2e.runtime._click",
                side_effect=click,
            ),
            mock.patch(
                "tools._real_flow_e2e.runtime.time.sleep",
                return_value=None,
            ),
        ):
            result = damage_enemy_with_real_input(
                ROOT,
                object(),
                FakePipe(),  # type: ignore[arg-type]
                timeout=5.0,
            )

        self.assertEqual(
            clicks,
            [
                (0.1, 0.1, 90),
                (0.8, 0.9, 90),
            ],
        )
        self.assertEqual(result["hpAfter"], 1.5)

    def test_nfo_damage_probe_refreshes_native_camera_target(
        self,
    ) -> None:
        def state(enemy_x: float, hp: float) -> dict[str, object]:
            return {
                "scene": {"name": "testrun"},
                "viewport": {"width": 1000, "height": 1000},
                "camera": {
                    "sceneAvailable": True,
                    "originX": 0.0,
                    "originY": 0.0,
                    "scale": 1.0,
                },
                "player": {
                    "valid": True,
                    "x": 50.0,
                    "y": 50.0,
                    "hp": 50.0,
                },
                "replicatedEnemies": [
                    {
                        "network_id": 101,
                        "dead": False,
                        "hp": hp,
                        "x": enemy_x,
                        "y": 100.0,
                        "screen_valid": False,
                        "screen_x": 900.0,
                        "screen_y": 900.0,
                    }
                ],
            }

        class FakePipe:
            def __init__(self) -> None:
                self.states = iter(
                    [
                        state(100.0, 2.5),
                        state(200.0, 2.5),
                        state(200.0, 1.5),
                    ]
                )

            def state(self) -> dict[str, object]:
                return next(self.states)

        class Remote:
            def __init__(self) -> None:
                self.clicks: list[tuple[float, float]] = []

            def click_game(self, x: float, y: float) -> dict[str, float]:
                self.clicks.append((x, y))
                return {"xFraction": x, "yFraction": y}

        remote = Remote()
        with mock.patch(
            "tools._real_flow_e2e.wan.time.sleep",
            return_value=None,
        ):
            result = _damage_remote_enemy(
                remote,  # type: ignore[arg-type]
                FakePipe(),  # type: ignore[arg-type]
                timeout=5.0,
            )

        self.assertEqual(remote.clicks, [(0.1, 0.1), (0.2, 0.1)])
        self.assertEqual(result["hpAfter"], 1.5)

    def test_damage_probe_concentrates_one_bounded_remote_click_burst(
        self,
    ) -> None:
        def state(hp: float) -> dict[str, object]:
            return {
                "scene": {"name": "testrun"},
                "viewport": {"width": 1000, "height": 1000},
                "camera": {
                    "sceneAvailable": True,
                    "originX": 0.0,
                    "originY": 0.0,
                    "scale": 1.0,
                },
                "player": {
                    "valid": True,
                    "x": 500.0,
                    "y": 500.0,
                    "hp": 50.0,
                },
                "replicatedEnemies": [
                    {
                        "network_id": 101,
                        "dead": False,
                        "hp": hp,
                        "x": 300.0,
                        "y": 400.0,
                        "screen_valid": False,
                        "screen_x": 0.0,
                        "screen_y": 0.0,
                    },
                    {
                        "network_id": 102,
                        "dead": False,
                        "hp": 2.5,
                        "x": 700.0,
                        "y": 600.0,
                        "screen_valid": False,
                        "screen_x": 0.0,
                        "screen_y": 0.0,
                    }
                ],
            }

        class FakePipe:
            def __init__(self) -> None:
                self.states = iter([state(2.5), state(1.5)])

            def state(self) -> dict[str, object]:
                return next(self.states)

        class BurstPeer:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def click_sequence(
                self,
                targets: list[tuple[float, float]],
                hold_ms: int,
                interval_ms: int,
            ) -> str:
                self.calls.append(
                    {
                        "targets": targets,
                        "holdMs": hold_ms,
                        "intervalMs": interval_ms,
                    }
                )
                return "ok"

        peer = BurstPeer()
        with mock.patch(
            "tools._real_flow_e2e.runtime.time.sleep",
            return_value=None,
        ):
            result = damage_enemy_with_real_input(
                ROOT,
                peer,  # type: ignore[arg-type]
                FakePipe(),  # type: ignore[arg-type]
                timeout=5.0,
            )

        self.assertEqual(
            peer.calls,
            [
                {
                    "targets": [
                        (0.3, 0.4),
                        (0.3, 0.4),
                        (0.3, 0.4),
                        (0.3, 0.4),
                        (0.3, 0.4),
                    ],
                    "holdMs": 90,
                    "intervalMs": 450,
                }
            ],
        )
        self.assertEqual(result["hpAfter"], 1.5)
        self.assertEqual(result["actions"][0]["physicalInputCount"], 5)

    def test_ws20_worker_bounds_remote_click_bursts(
        self,
    ) -> None:
        worker = (
            ROOT / "scripts/Run-RealFlowWindowsSessionWorker.ps1"
        ).read_text(encoding="utf-8")
        real_input = worker.split(
            "function Invoke-RealInput {", 1
        )[1].split("function Close-RunProcesses {", 1)[0]

        self.assertIn(
            '$Request.Action -eq "click-sequence"',
            real_input,
        )
        self.assertIn("$targets.Count -gt 8", real_input)
        self.assertIn("$targets.Count -lt 2", real_input)
        self.assertIn(
            "Start-Sleep -Milliseconds $intervalMilliseconds",
            real_input,
        )
        self.assertIn(
            '[string]$Request.GameExecutable',
            real_input,
        )

    def test_ws20_action_uses_one_remote_powershell_round_trip(
        self,
    ) -> None:
        class FakeConnection:
            stage_root = r"C:\Users\test\sd-netrepro-stage"

            def __init__(self) -> None:
                self.scripts: list[str] = []

            def run_ps(
                self,
                script: str,
                *,
                timeout: float,
            ) -> str:
                self.scripts.append(script)
                return json.dumps(
                    {"ok": True, "detail": {"processId": 42}}
                )

            def write_json(
                self,
                _path: str,
                _value: dict[str, object],
            ) -> None:
                raise AssertionError("second SSH request was used")

        peer = object.__new__(Ws20Peer)
        peer.harness = SimpleNamespace(run_name="one-round-trip")
        peer.connection = FakeConnection()
        peer._action_counter = 0

        detail = peer._invoke(
            "click",
            {"ProcessId": 42, "X": "0.5", "Y": "0.5"},
            timeout=30,
        )

        self.assertEqual(detail, {"processId": 42})
        self.assertEqual(len(peer.connection.scripts), 1)
        self.assertIn(
            "[System.Convert]::FromBase64String",
            peer.connection.scripts[0],
        )

    def test_client_attack_precedes_paired_capture(self) -> None:
        source = (
            ROOT / "tools/verify_real_flow_e2e.py"
        ).read_text(encoding="utf-8")
        materialized = source.index(
            'result["clientEnemyMaterialization"] = materialization'
        )
        damage = source.index(
            'sampler.set_phase("client-real-damage")',
            materialized,
        )
        capture = source.index(
            'sampler.set_phase("paired-render-capture")',
            materialized,
        )

        self.assertLess(damage, capture)

    def test_ws20_capture_uses_remote_execution_wall_clock(
        self,
    ) -> None:
        adapter = (
            ROOT / "tools/_real_flow_e2e/ws20.py"
        ).read_text(encoding="utf-8")
        bridge = (
            ROOT / "scripts/Invoke-RemoteLuaExecBridge.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("-IncludeExecutionUtcNanoseconds", adapter)
        self.assertIn('struct.unpack(\n                    "<IQ"', adapter)
        self.assertIn(
            '"captureUtcNanoseconds": remote_capture_ns',
            adapter,
        )
        self.assertIn(
            "[DateTime]::UtcNow.Ticks - 621355968000000000",
            bridge,
        )
        self.assertIn(
            "-ExecutionUtcNanoseconds $executionUtcNanoseconds",
            bridge,
        )

    def test_evidence_manifest_hashes_every_artifact_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nested").mkdir()
            (root / "one.txt").write_text("one\n", encoding="utf-8")
            (root / "nested/two.txt").write_text(
                "two\n",
                encoding="utf-8",
            )

            manifest = write_manifest(root)
            rows = manifest.read_text(encoding="utf-8").splitlines()

            self.assertEqual(len(rows), 2)
            self.assertTrue(any(row.endswith("  one.txt") for row in rows))
            self.assertTrue(
                any(row.endswith("  nested/two.txt") for row in rows)
            )
            self.assertFalse(
                any("evidence-sha256.txt" in row for row in rows)
            )


if __name__ == "__main__":
    unittest.main()
