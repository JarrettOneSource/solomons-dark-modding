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
    _merge_solomon_authority_state,
    cover_participant_with_real_input_once,
    damage_click_targets,
    damage_enemy_with_real_input,
    normalize_state,
    shared_hub_views_converged,
)
from tools.verify_real_flow_e2e import (
    validate_living_wave_boundary,
    validate_stock_water_cast,
    validate_wave_convergence,
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
            "solomonInteractor": "client",
            "verifyThroughWave": 2,
            "requireWaterContactObservation": True,
            "expectedWaterContactDamage": 0.025,
            "waveBoundaryMaxDisplacement": 64,
            "host": {
                "platform": "windows_local",
                "launcherScope": "real-host",
                "instance": "real-host",
                "playerName": "Host",
                "pipeName": "RealFlowHost",
                "participantId": "0x1001",
                "loadoutElement": "air",
                "localPort": 50911,
                "remoteHost": "127.0.0.1",
                "remotePort": 50912,
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
                "loadoutElement": "water",
                "localPort": 50912,
                "remoteHost": "127.0.0.1",
                "remotePort": 50911,
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

            self.assertEqual(config.host.local_port, 50911)
            self.assertEqual(config.client.local_port, 50912)
            self.assertEqual(config.solomon_interactor, "client")
            self.assertEqual(config.verify_through_wave, 2)
            self.assertTrue(config.require_water_contact_observation)
            self.assertEqual(config.host.loadout_element, "air")
            self.assertEqual(config.client.loadout_element, "water")

            document["host"]["localPort"] = 50913  # type: ignore[index]
            with self.assertRaisesRegex(ConfigError, "50911/50912"):
                self._load_document(root, document)

    def test_fieldbreak_example_drives_fresh_profile_to_dead_hawg(
        self,
    ) -> None:
        document = json.loads(
            (
                ROOT / "tools/real_flow_e2e_fieldbreak25.example.json"
            ).read_text(encoding="utf-8")
        )
        actions = document["host"]["matchStartActions"]

        self.assertEqual(
            [
                (
                    action["kind"],
                    action.get("key"),
                    action.get("holdMilliseconds"),
                )
                for action in actions[:5]
            ],
            [
                ("key", "d", 4000),
                ("key", "s", 3000),
                ("key", "a", 2750),
                ("key", "w", 1100),
                ("key", "a", 800),
            ],
        )
        self.assertEqual(
            [
                (action["x"], action["y"])
                for action in actions[5:9]
            ],
            [
                (0.5, 0.43),
                (0.5, 0.43),
                (0.956, 0.944),
                (0.534, 0.539),
            ],
        )
        self.assertEqual(actions[-1]["scene"], "testrun")

    def test_client_solomon_flow_uses_host_authority_state(self) -> None:
        local = {
            "player": {"x": 900.0, "y": 2000.0},
            "solomon": {"valid": False},
            "combat": {"waveIndex": 0},
            "wave": {"index": 0},
            "world": {"waveIndex": 0},
        }
        authority = {
            "solomon": {
                "valid": True,
                "x": 850.5,
                "y": 974.9,
            },
            "combat": {"waveIndex": 1},
            "wave": {"index": 1},
            "world": {"waveIndex": 1},
        }

        merged = _merge_solomon_authority_state(local, authority)

        self.assertIs(merged["player"], local["player"])
        self.assertIs(merged["solomon"], authority["solomon"])
        self.assertIs(merged["combat"], authority["combat"])
        self.assertIs(merged["wave"], authority["wave"])
        self.assertIs(merged["world"], authority["world"])
        controller = (
            ROOT / "tools/verify_real_flow_e2e.py"
        ).read_text(encoding="utf-8")
        runtime = (
            ROOT / "tools/_real_flow_e2e/runtime.py"
        ).read_text(encoding="utf-8")
        self.assertIn("authority_pipe=host_pipe", controller)
        self.assertIn('"kind": "direct-authority-target"', runtime)
        self.assertIn(
            "1800 if remote_authority else 1200",
            runtime,
        )
        self.assertIn("cover_action=(", controller)
        self.assertGreaterEqual(
            controller.count("cover_client_dig()"),
            3,
        )

    @mock.patch("tools._real_flow_e2e.runtime._click")
    def test_client_dig_cover_casts_host_air_at_a_live_enemy(
        self,
        click: mock.Mock,
    ) -> None:
        click.return_value = "clicked"
        pipe = mock.Mock()
        pipe.state.return_value = {
            "scene": {"name": "testrun"},
            "player": {
                "valid": True,
                "hp": 42.0,
                "x": 100.0,
                "y": 100.0,
            },
            "nativeEnemies": [
                {
                    "dead": False,
                    "hp": 2.5,
                    "x": 120.0,
                    "y": 100.0,
                }
            ],
            "viewport": {"width": 1600, "height": 900},
            "camera": {
                "sceneAvailable": True,
                "originX": 0.0,
                "originY": 0.0,
                "scale": 1.0,
            },
        }

        action = cover_participant_with_real_input_once(
            ROOT,
            mock.Mock(),
            pipe,
            movement_index=2,
        )

        self.assertEqual(action["kind"], "air-cast")
        self.assertEqual(action["liveEnemyCount"], 1)
        self.assertEqual(action["hp"], 42.0)
        click.assert_called_once()
        self.assertEqual(click.call_args.args[-1], 1500)

    def test_shared_hub_wait_requires_converged_participant_views(
        self,
    ) -> None:
        def state(
            local_id: int,
            other_y: float,
        ) -> dict[str, object]:
            return {
                "scene": {"kind": "hub"},
                "loadingScreen": {"active": False},
                "multiplayer": {
                    "sessionState": "in-hub",
                    "sessionStatus": "Ready",
                    "participantCount": 2,
                    "participants": [
                        {
                            "id": local_id,
                            "name": (
                                "Host" if local_id == 1 else "client B"
                            ),
                            "connected": True,
                            "ready": True,
                            "in_run": False,
                            "scene_kind": "SharedHub",
                            "x": 952.5,
                            "y": 163.25,
                        },
                        {
                            "id": 3 - local_id,
                            "name": (
                                "client B" if local_id == 1 else "Host"
                            ),
                            "connected": True,
                            "ready": True,
                            "in_run": False,
                            "scene_kind": "SharedHub",
                            "x": 952.5,
                            "y": other_y,
                        },
                    ],
                },
            }

        host = state(1, 60.0)
        client = state(2, 90.0)
        self.assertFalse(shared_hub_views_converged(host, client))

        host["multiplayer"]["participants"][1]["y"] = 163.2  # type: ignore[index]
        client["multiplayer"]["participants"][1]["y"] = 163.3  # type: ignore[index]
        self.assertTrue(shared_hub_views_converged(host, client))

        client["loadingScreen"]["active"] = True  # type: ignore[index]
        self.assertFalse(shared_hub_views_converged(host, client))

    def test_shared_hub_wait_matches_large_ids_by_participant_name(
        self,
    ) -> None:
        host = {
            "scene": {"kind": "hub"},
            "loadingScreen": {"active": False},
            "multiplayer": {
                "sessionState": "in-hub",
                "sessionStatus": "Ready",
                "participantCount": 2,
                "participants": [
                    {
                        "id": 1,
                        "name": "Host",
                        "connected": True,
                        "ready": True,
                        "in_run": False,
                        "scene_kind": "SharedHub",
                        "x": 918.3,
                        "y": 222.8,
                    },
                    {
                        "id": 2666130979403333632,
                        "name": "client B",
                        "connected": True,
                        "ready": True,
                        "in_run": False,
                        "scene_kind": "SharedHub",
                        "x": 952.6,
                        "y": 162.9,
                    },
                ],
            },
        }
        client = {
            "scene": {"kind": "hub"},
            "loadingScreen": {"active": False},
            "multiplayer": {
                "sessionState": "in-hub",
                "sessionStatus": "Ready",
                "participantCount": 2,
                "participants": [
                    {
                        "id": 1,
                        "name": "client B",
                        "connected": True,
                        "ready": True,
                        "in_run": False,
                        "scene_kind": "SharedHub",
                        "x": 952.6,
                        "y": 162.9,
                    },
                    {
                        "id": 2666130979403333632,
                        "name": "Host",
                        "connected": True,
                        "ready": True,
                        "in_run": False,
                        "scene_kind": "SharedHub",
                        "x": 918.3,
                        "y": 222.8,
                    },
                ],
            },
        }

        self.assertTrue(shared_hub_views_converged(host, client))

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
            host["localPort"] = 50911
            host["remotePort"] = 50912
            host["remoteHost"] = "203.0.113.10"
            client["platform"] = "linux_ssh_proton"
            client["localPort"] = 50912
            client["remotePort"] = 50911
            client["remoteHost"] = "198.51.100.20"
            client["ssh"] = {
                "target": "nfo-test",
                "stageRoot": "/root/sd-fieldbreak25-20260730",
            }

            config = self._load_document(root, document)

            self.assertEqual(
                config.client.ssh.stage_root,  # type: ignore[union-attr]
                "/root/sd-fieldbreak25-20260730",
            )
            document["client"]["ssh"]["stageRoot"] = "/root/other"  # type: ignore[index]
            with self.assertRaisesRegex(
                ConfigError,
                "/root/sd-fieldbreak25-20260730",
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
        self.assertIn("config.solomon_interactor == \"host\"", combined)
        self.assertIn("approach_solomon_and_complete_dialogue(", combined)
        self.assertIn("verify_through_wave", combined)

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
            'sampler.set_phase("client-real-water-damage")',
            materialized,
        )
        capture = source.index(
            'sampler.set_phase("paired-render-capture")',
            materialized,
        )

        self.assertLess(damage, capture)

    def test_stock_water_cast_requires_exact_contacts_and_peer_hp(
        self,
    ) -> None:
        cast = {
            "networkActorId": 77,
            "hostDamage": 0.05,
            "hostHpAfter": 1.95,
            "clientAfter": {
                "replicatedEnemies": [
                    {
                        "network_id": 77,
                        "dead": False,
                        "hp": 1.95,
                    }
                ],
            },
            "observation": {
                "damageClaimValid": True,
                "nativeContactCount": 2,
                "nativeContactSkillId": 32,
                "nativeContactSkillConsistent": True,
                "nativeContactSamples": [0.025, 0.025],
                "nativeContactTotal": 0.05,
                "claimedTotal": 0.05,
                "associatedSkillId": 32,
                "associatedSkillConsistent": True,
                "unassociatedClaimCount": 0,
            },
        }

        result = validate_stock_water_cast(
            cast,
            expected_contact_damage=0.025,
        )

        self.assertEqual(result["contactCount"], 2)
        self.assertEqual(result["hostAuthoritativeDamage"], 0.05)
        cast["observation"]["nativeContactSamples"] = [0.05, 0.05]
        with self.assertRaisesRegex(
            RuntimeError,
            "non-stock native contacts",
        ):
            validate_stock_water_cast(
                cast,
                expected_contact_damage=0.025,
            )

    def test_wave_boundary_rejects_living_position_teleport(
        self,
    ) -> None:
        def state(
            wave: int,
            x: float,
            y: float,
        ) -> dict[str, object]:
            participants = [
                {
                    "connected": True,
                    "in_run": True,
                    "wave": wave,
                },
                {
                    "connected": True,
                    "in_run": True,
                    "wave": wave,
                },
            ]
            return {
                "scene": {"name": "testrun"},
                "player": {"hp": 1.0, "x": x, "y": y},
                "wave": {"index": wave},
                "combat": {"waveIndex": wave},
                "world": {"waveIndex": wave},
                "multiplayer": {
                    "participantCount": 2,
                    "participants": participants,
                },
            }

        stable_rows = [
            {
                "utcNanoseconds": 1,
                "host": state(1, 500.0, 600.0),
                "clientB": state(1, 800.0, 900.0),
            },
            {
                "utcNanoseconds": 2,
                "host": state(2, 501.0, 600.0),
                "clientB": state(2, 801.0, 900.0),
            },
        ]
        result = validate_living_wave_boundary(
            stable_rows,
            target_wave=2,
            maximum_displacement=64.0,
        )
        self.assertLess(
            result["participants"]["host"]["boundaryDisplacement"],
            2.0,
        )
        validate_wave_convergence(
            stable_rows[-1]["host"],
            stable_rows[-1]["clientB"],
            target_wave=2,
        )

        teleported = [dict(row) for row in stable_rows]
        teleported[1] = {
            "utcNanoseconds": 2,
            "host": state(2, 1276.0, 2238.0),
            "clientB": state(2, 1276.0, 2238.0),
        }
        with self.assertRaisesRegex(
            RuntimeError,
            "living host position was moved",
        ):
            validate_living_wave_boundary(
                teleported,
                target_wave=2,
                maximum_displacement=64.0,
            )

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
