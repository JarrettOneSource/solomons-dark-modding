from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

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
    normalize_state,
)


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
            Image.new("RGB", (100, 100), (90, 100, 110)).save(capture)

            with self.assertRaisesRegex(EvidenceError, "visually uniform"):
                rendered_enemy_assertion(self._render_state(), capture)

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

    def test_damage_targets_try_actor_sprite_neighborhood_first(
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
        )

        self.assertEqual(
            targets[:2],
            [
                (0.2925, 22.0 / 900.0),
                (0.3625, 22.0 / 900.0 + 0.06),
            ],
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
