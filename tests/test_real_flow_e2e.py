from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from PIL import Image

from tools._real_flow_e2e.config import ConfigError, HarnessConfig
from tools._real_flow_e2e.evidence import (
    EvidenceError,
    paired_windows_capture,
    packet_accounting,
    rendered_enemy_assertion,
    steam_transport_assertion,
    write_manifest,
)
from tools._real_flow_e2e.endurance import (
    EnduranceAnomalyMonitor,
    FighterStatsTracker,
    effective_wave,
    is_capture_milestone,
    terminal_game_over,
)
from tools._real_flow_e2e.runtime import (
    LuaPipe,
    RuntimeProbeError,
    _merge_solomon_authority_state,
    approach_solomon_and_complete_dialogue,
    cover_participant_with_real_input_once,
    damage_click_targets,
    damage_enemy_with_real_input,
    normalize_state,
    shared_hub_views_converged,
)
from tools.verify_real_flow_e2e import (
    EnduranceProbeOutage,
    RealFlowFailure,
    _assert_clean_release,
    _drain_authority_damage_log,
    _native_enemy_render_assertion,
    _real_primary_damage_metrics,
    _replicated_damage_participant_ids,
    _try_endurance_probe_bundle,
    validate_living_wave_boundary,
    validate_stock_water_cast,
    validate_wave_convergence,
)
from tools._real_flow_e2e.wan import _damage_remote_enemy
from tools._real_flow_e2e.windows import (
    ProcessRecord,
    UiElement,
    WindowsHarnessError,
    _launcher_ui_diagnostics,
    close_exact_owned_processes,
    launch_environment,
    prepare_windows_peer,
)
from tools._real_flow_e2e.ws20 import (
    RemoteWindowsConnection,
    Ws20HarnessError,
    Ws20Peer,
    _longest_staged_runtime_path,
)


ROOT = Path(__file__).resolve().parents[1]


class RealFlowE2ETests(unittest.TestCase):
    def test_paired_capture_uses_controller_clock_bounds(self) -> None:
        def peer_capture(
            capture_ns: int,
            start_ns: int,
            end_ns: int,
        ) -> SimpleNamespace:
            def capture(output: Path) -> dict[str, object]:
                output.write_bytes(b"capture")
                return {
                    "path": str(output),
                    "captureUtcNanoseconds": capture_ns,
                    "captureWindowStartUtcNanoseconds": start_ns,
                    "captureWindowEndUtcNanoseconds": end_ns,
                }

            return SimpleNamespace(capture_window=capture)

        with tempfile.TemporaryDirectory() as temporary:
            result = paired_windows_capture(
                ROOT,
                peer_capture(150_000_000, 100_000_000, 200_000_000),
                peer_capture(250_000_000, 150_000_000, 300_000_000),
                Path(temporary),
                label="bounded",
            )

        self.assertEqual(result["attempt"], 1)
        self.assertEqual(result["captureBoundSpanNanoseconds"], 200_000_000)
        self.assertEqual(result["rejectedAttempts"], [])

    def test_paired_capture_retries_without_relaxing_bound(self) -> None:
        class SequencedCapture:
            def __init__(self, windows: list[tuple[int, int]]) -> None:
                self.windows = iter(windows)

            def capture_window(self, output: Path) -> dict[str, object]:
                start_ns, end_ns = next(self.windows)
                output.write_bytes(b"capture")
                return {
                    "path": str(output),
                    "captureUtcNanoseconds": (start_ns + end_ns) // 2,
                    "captureWindowStartUtcNanoseconds": start_ns,
                    "captureWindowEndUtcNanoseconds": end_ns,
                }

        host = SequencedCapture(
            [(0, 100_000_000), (2_000_000_000, 2_100_000_000)]
        )
        client = SequencedCapture(
            [(1_200_000_000, 1_300_000_000), (2_050_000_000, 2_200_000_000)]
        )
        with tempfile.TemporaryDirectory() as temporary:
            result = paired_windows_capture(
                ROOT,
                host,
                client,
                Path(temporary),
                label="retry",
            )

        self.assertEqual(result["attempt"], 2)
        self.assertEqual(len(result["rejectedAttempts"]), 1)
        self.assertEqual(result["captureBoundSpanNanoseconds"], 200_000_000)

    def test_endurance_probe_bundle_recovers_from_bounded_remote_outage(
        self,
    ) -> None:
        sample = {"elapsedSeconds": 12.0, "host": {}, "clientB": {}}
        sampler = SimpleNamespace(
            sample_now=mock.Mock(
                side_effect=[
                    RuntimeProbeError(
                        "remote Lua bridge failed: remote Windows Lua "
                        "bridge timed out"
                    ),
                    Ws20HarnessError(
                        "remote bridge startup failed: SSH timed out"
                    ),
                    sample,
                ]
            )
        )
        outage = EnduranceProbeOutage(budget_seconds=180.0)

        with mock.patch(
            "tools.verify_real_flow_e2e.time.monotonic",
            side_effect=[100.0, 110.0, 125.0],
        ), mock.patch(
            "tools.verify_real_flow_e2e._bot_probe",
            side_effect=[{"active": True}, {"active": True}],
        ):
            unavailable, started = _try_endurance_probe_bundle(
                sampler,
                SimpleNamespace(),
                SimpleNamespace(),
                outage,
                elapsed_seconds=12.0,
                sanitize_error=lambda value: value,
            )
            recovered, ended = _try_endurance_probe_bundle(
                sampler,
                SimpleNamespace(),
                SimpleNamespace(),
                outage,
                elapsed_seconds=22.0,
                sanitize_error=lambda value: value,
            )
            self.assertIsNone(recovered)
            self.assertEqual(ended["event"], "probe-outage-retry")
            recovered, ended = _try_endurance_probe_bundle(
                sampler,
                SimpleNamespace(),
                SimpleNamespace(),
                outage,
                elapsed_seconds=37.0,
                sanitize_error=lambda value: value,
            )

        self.assertIsNone(unavailable)
        self.assertEqual(started["event"], "probe-outage-start")
        self.assertEqual(recovered["sample"], sample)
        self.assertEqual(recovered["bots"]["host"], {"active": True})
        self.assertEqual(ended["event"], "probe-outage-recovered")
        self.assertEqual(ended["durationSeconds"], 25.0)
        self.assertEqual(ended["failureCount"], 2)
        self.assertEqual(len(outage.completed), 1)

    def test_endurance_probe_bundle_aborts_persistent_remote_outage(
        self,
    ) -> None:
        error = RuntimeProbeError(
            "remote Lua bridge failed: remote Windows Lua bridge timed out"
        )
        sampler = SimpleNamespace(
            sample_now=mock.Mock(side_effect=[error, error])
        )
        outage = EnduranceProbeOutage(budget_seconds=180.0)

        with mock.patch(
            "tools.verify_real_flow_e2e.time.monotonic",
            side_effect=[100.0, 281.0],
        ):
            bundle, _ = _try_endurance_probe_bundle(
                sampler,
                SimpleNamespace(),
                SimpleNamespace(),
                outage,
                elapsed_seconds=12.0,
                sanitize_error=lambda value: value,
            )
            self.assertIsNone(bundle)
            with self.assertRaisesRegex(
                RealFlowFailure,
                "remote endurance probe outage exceeded 180.0 seconds",
            ):
                _try_endurance_probe_bundle(
                    sampler,
                    SimpleNamespace(),
                    SimpleNamespace(),
                    outage,
                    elapsed_seconds=193.0,
                    sanitize_error=lambda value: value,
                )

    def test_endurance_probe_bundle_does_not_hide_game_lua_errors(
        self,
    ) -> None:
        sampler = SimpleNamespace(
            sample_now=mock.Mock(
                side_effect=RuntimeProbeError("Lua execution failed")
            )
        )

        with self.assertRaisesRegex(
            RuntimeProbeError,
            "Lua execution failed",
        ):
            _try_endurance_probe_bundle(
                sampler,
                SimpleNamespace(),
                SimpleNamespace(),
                EnduranceProbeOutage(budget_seconds=180.0),
                elapsed_seconds=12.0,
                sanitize_error=lambda value: value,
            )

    def test_launcher_failure_diagnostics_preserve_visible_status(self) -> None:
        peer = SimpleNamespace(ui_pid=41)
        status = UiElement(
            name="Steam could not create the lobby.",
            control_type="ControlType.Text",
            automation_id="",
            enabled=True,
            offscreen=False,
            value="",
        )
        with mock.patch(
            "tools._real_flow_e2e.windows.ui_elements",
            return_value=[status],
        ):
            rows = _launcher_ui_diagnostics(
                SimpleNamespace(),  # type: ignore[arg-type]
                peer,  # type: ignore[arg-type]
            )

        self.assertEqual(rows[0]["name"], status.name)
        self.assertFalse(rows[0]["offscreen"])

    def test_local_lua_pipe_serializes_concurrent_requests(self) -> None:
        active = 0
        maximum_active = 0
        active_lock = threading.Lock()

        def run_bridge(*args: object, **kwargs: object) -> str:
            nonlocal active, maximum_active
            with active_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.03)
            with active_lock:
                active -= 1
            return "ok"

        pipe = LuaPipe(ROOT, "test-pipe")
        with mock.patch.object(
            pipe,
            "_execute_daemon",
            side_effect=run_bridge,
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(pipe.execute, ("one", "two")))

        self.assertEqual(results, ["ok", "ok"])
        self.assertEqual(maximum_active, 1)

    def test_local_lua_pipe_reuses_and_closes_one_daemon(self) -> None:
        raw = json.dumps(
            {
                "ok": True,
                "print_output": "",
                "results": ["answer=42"],
                "error": None,
            }
        ).encode("utf-8")
        responses = base64.b64encode(raw) + b"\n"

        class InputSink:
            def __init__(self) -> None:
                self.writes: list[bytes] = []

            def write(self, value: bytes) -> None:
                self.writes.append(value)

            def flush(self) -> None:
                pass

            def close(self) -> None:
                pass

        class Process:
            def __init__(self) -> None:
                self.stdin = InputSink()
                self.stdout = io.BytesIO(responses * 2)
                self.stderr = io.BytesIO()
                self.exited = False

            def poll(self) -> int | None:
                return 0 if self.exited else None

            def wait(self, *, timeout: float) -> int:
                self.exited = True
                return 0

            def terminate(self) -> None:
                self.exited = True

            def kill(self) -> None:
                self.exited = True

        process = Process()
        pipe = LuaPipe(ROOT, "test-pipe")
        with mock.patch(
            "tools._real_flow_e2e.runtime.subprocess.Popen",
            return_value=process,
        ) as popen:
            self.assertEqual(pipe.execute("return 42"), "answer=42")
            self.assertEqual(pipe.execute("return 42"), "answer=42")
            pipe.close()

        popen.assert_called_once()
        self.assertTrue(process.exited)
        self.assertEqual(process.stdin.writes[-1], b"__SDLUA_EXIT__\n")

    def test_solomon_waypoint_stall_uses_real_input_detour(self) -> None:
        def state(*, acquired: bool = False) -> dict[str, object]:
            return {
                "scene": {"name": "testrun"},
                "player": {"valid": True, "x": 0.0, "y": 0.0},
                "solomon": {
                    "valid": True,
                    "acquired": acquired,
                    "state": 1 if acquired else 0,
                    "x": 1000.0,
                    "y": 0.0,
                },
                "wave": {"index": 0},
                "combat": {"waveIndex": 0},
                "world": {},
            }

        initial = state()
        complete = state(acquired=True)
        complete["wave"]["index"] = 1  # type: ignore[index]
        samples = [
            *[state() for _ in range(5)],
            state(acquired=True),
            complete,
        ]

        class Pipe:
            def openable_path_obstacles(self) -> list[object]:
                return []

            def navigation_grid(self, *, timeout: float) -> dict[str, object]:
                return {
                    "cellWidth": 100.0,
                    "cellHeight": 100.0,
                    "nodes": {},
                }

            def state(self) -> dict[str, object]:
                return samples.pop(0)

        pipe = Pipe()
        peer = SimpleNamespace()
        with (
            mock.patch(
                "tools._real_flow_e2e.runtime.wait_for_state",
                return_value=initial,
            ),
            mock.patch(
                "tools._real_flow_e2e.runtime.plan_navigation_path",
                return_value={
                    "kind": "test-grid",
                    "waypoints": [{"x": 100.0, "y": 0.0}],
                },
            ),
            mock.patch(
                "tools._real_flow_e2e.runtime._send_key"
            ) as send_key,
        ):
            result = approach_solomon_and_complete_dialogue(
                ROOT,
                peer,  # type: ignore[arg-type]
                pipe,  # type: ignore[arg-type]
                timeout=1.0,
            )

        self.assertEqual(result["navigation"]["detourCount"], 1)
        self.assertIn(mock.call(ROOT, peer, "s", 1200), send_key.mock_calls)

    def test_human_control_does_not_reopen_takeover_state(self) -> None:
        state = {
            "active": False,
            "desired": False,
            "focus_active": False,
            "takeover.active": False,
            "takeover.clean": True,
            "takeover.target_valid": False,
            "takeover.actor_address": 0,
            "takeover.target_actor_address": 0,
            "takeover.pending_movement_frames": 0,
            "takeover.pending_mouse_left_frames": 0,
            "takeover.pending_mouse_right_frames": 0,
            "takeover.pending_scancode_count": 0,
            "takeover.pending_native_control_frames": 0,
            "takeover.pending_movement_x": 0.0,
            "takeover.pending_movement_y": 0.0,
            "takeover.cast_intent": 0,
            "takeover.primary_skill_id": 0,
            "takeover.previous_skill_id": 0,
            "takeover.current_target_actor_address": 0,
            "takeover.movement_input_x": 0.0,
            "takeover.movement_input_y": 0.0,
            "takeover.control_brain_move_x": 0.66,
            "takeover.control_brain_move_y": -0.75,
        }

        with self.assertRaisesRegex(
            RuntimeError,
            "release retained control state",
        ):
            _assert_clean_release(state)
        assertion = _assert_clean_release(
            state,
            after_human_input=True,
        )
        self.assertTrue(assertion["clean"])
        self.assertTrue(assertion["afterHumanInput"])
        self.assertNotIn(
            "takeover.control_brain_move_x",
            assertion["explicitZeroFields"],
        )

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

    def test_botplay_loopback_uses_owner_ports_and_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = self._config_document(root)
            (root / "source/mods/bot-brain").mkdir(parents=True)
            (root / "source/mods/bot-brain/manifest.json").touch()
            document.update(
                {
                    "runName": "bply-contract",
                    "topology": "loopback_windows_botplay",
                    "botPlayForMe": True,
                    "localStagingRoot": str(
                        root / "bply-contract-stage"
                    ),
                    "verifyThroughWave": 4,
                }
            )
            host = document["host"]
            client = document["client"]
            assert isinstance(host, dict)
            assert isinstance(client, dict)
            host.update(
                {
                    "launcherScope": "bply-host",
                    "instance": "bply-host",
                    "pipeName":
                        "SolomonDarkModLoader_LuaExec_bply-host",
                    "localPort": 51411,
                    "remotePort": 51412,
                }
            )
            client.update(
                {
                    "launcherScope": "bply-client",
                    "instance": "bply-client",
                    "pipeName":
                        "SolomonDarkModLoader_LuaExec_bply-client",
                    "localPort": 51412,
                    "remotePort": 51411,
                }
            )
            config = self._load_document(root, document)
            self.assertTrue(config.bot_play_for_me)
            self.assertEqual(
                config.windows_staging_root,
                root / "bply-contract-stage",
            )
            self.assertEqual(config.host.local_port, 51411)
            self.assertEqual(config.client.local_port, 51412)
            self.assertEqual(
                config.host.pipe_name,
                "SolomonDarkModLoader_LuaExec_bply-host",
            )
            environment = launch_environment(
                config,
                SimpleNamespace(config=config.host),
            )
            self.assertEqual(
                environment["SDMOD_MULTIPLAYER_MAX_PARTICIPANTS"],
                "4",
            )

            host["localPort"] = 51080
            client["remotePort"] = 51080
            with self.assertRaisesRegex(ConfigError, "at or above 51400"):
                self._load_document(root, document)

    def test_ws20_endurance_accepts_bot_takeover_and_ninety_minute_cap(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = self._config_document(root)
            (root / "source/mods/bot-brain").mkdir(parents=True)
            (root / "source/mods/bot-brain/manifest.json").touch()
            observer = root / "source/tools/_real_flow_e2e/observer_mod"
            observer.mkdir(parents=True)
            (observer / "manifest.json").touch()
            document.update(
                {
                    "runName": "bply-botendure",
                    "topology": "steam_windows_ws20",
                    "botPlayForMe": True,
                    "botPlayBehavior": "striker",
                    "enduranceMode": True,
                    "enduranceMaxSeconds": 5400,
                    "reuseWs20Prestage": True,
                    "localStagingRoot": str(
                        root / "bply-botendure-stage"
                    ),
                    "verifyThroughWave": 1,
                }
            )
            host = document["host"]
            client = document["client"]
            assert isinstance(host, dict)
            assert isinstance(client, dict)
            host.update(
                {
                    "launcherScope": "bply-endure-host",
                    "instance": "bply-endure-host",
                    "pipeName": (
                        "SolomonDarkModLoader_LuaExec_bply-endure-host"
                    ),
                    "localPort": 0,
                    "remotePort": 0,
                    "remoteHost": "",
                }
            )
            client.update(
                {
                    "platform": "windows_ssh",
                    "launcherScope": "bply-endure-client",
                    "instance": "bply-endure-client",
                    "pipeName": (
                        "SolomonDarkModLoader_LuaExec_bply-endure-client"
                    ),
                    "localPort": 0,
                    "remotePort": 0,
                    "remoteHost": "",
                    "ssh": {
                        "target": "workstation20.example",
                        "username": "client-b",
                        "keyPath": "/run/user/1000/ws20-key",
                        "stageRoot": (
                            r"%USERPROFILE%\sd-botendure-stage"
                        ),
                    },
                }
            )

            config = self._load_document(root, document)

            self.assertTrue(config.bot_play_for_me)
            self.assertEqual(config.bot_play_behavior, "striker")
            self.assertTrue(config.endurance_mode)
            self.assertEqual(config.endurance_max_seconds, 5400)
            self.assertTrue(config.reuse_ws20_prestage)
            self.assertEqual(
                config.directory_url,
                "https://solomondarker.com",
            )
            with mock.patch(
                "tools._real_flow_e2e.windows.windows_path",
                side_effect=lambda path: rf"C:\stage\{path.name}",
            ):
                peers = (
                    prepare_windows_peer(config, config.host),
                    prepare_windows_peer(config, config.client),
                )
            for peer in peers:
                settings = json.loads(
                    (peer.settings_root / "settings.json").read_text()
                )
                self.assertEqual(
                    settings["directoryUrl"],
                    "https://solomondarker.com",
                )
            self.assertEqual(
                config.redacted()["client"]["sshStageRoot"],
                r"%USERPROFILE%\sd-botendure-stage",
            )

            document["botPlayForMe"] = False
            with self.assertRaisesRegex(
                ConfigError,
                "enduranceMode requires botPlayForMe",
            ):
                self._load_document(root, document)
            document["botPlayForMe"] = True
            document["botPlayBehavior"] = "berserker"
            with self.assertRaisesRegex(
                ConfigError,
                "botPlayBehavior must be",
            ):
                self._load_document(root, document)
            document["botPlayBehavior"] = "striker"
            document["enduranceMaxSeconds"] = 5401
            with self.assertRaisesRegex(
                ConfigError,
                "enduranceMaxSeconds must be between 60 and 5400",
            ):
                self._load_document(root, document)

            document["enduranceMaxSeconds"] = 5400
            document["topology"] = "loopback_windows_botplay"
            with self.assertRaisesRegex(
                ConfigError,
                "reuseWs20Prestage requires steam_windows_ws20",
            ):
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
                "hp": 46.0,
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
        self.assertEqual(action["hp"], 46.0)
        click.assert_called_once()
        self.assertEqual(click.call_args.args[-1], 600)

    @mock.patch("tools._real_flow_e2e.runtime._click")
    def test_client_dig_cover_keeps_casting_host_air_when_low(
        self,
        click: mock.Mock,
    ) -> None:
        click.return_value = "clicked"
        pipe = mock.Mock()
        pipe.state.return_value = {
            "scene": {"name": "testrun"},
            "player": {
                "valid": True,
                "hp": 20.0,
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
            movement_index=0,
        )

        self.assertEqual(action["kind"], "air-cast")
        click.assert_called_once_with(
            ROOT,
            mock.ANY,
            0.075,
            100.0 / 900.0,
            600,
        )

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

    def test_shared_hub_wait_matches_native_local_slots_by_owner(
        self,
    ) -> None:
        def participant(
            *,
            participant_id: int,
            name: str,
            owner: bool,
            x: float,
            y: float,
        ) -> dict[str, object]:
            return {
                "id": participant_id,
                "name": name,
                "owner": owner,
                "connected": True,
                "ready": True,
                "in_run": False,
                "scene_kind": "SharedHub",
                "x": x,
                "y": y,
            }

        common = {
            "scene": {"kind": "hub"},
            "loadingScreen": {"active": False},
            "multiplayer": {
                "sessionState": "in-hub",
                "sessionStatus": "Ready",
                "participantCount": 2,
            },
        }
        host = json.loads(json.dumps(common))
        client = json.loads(json.dumps(common))
        host["multiplayer"]["participants"] = [  # type: ignore[index]
            participant(
                participant_id=1,
                name="FUN DENIER",
                owner=True,
                x=952.5,
                y=163.6,
            ),
            participant(
                participant_id=0x2B00000000000002,
                name="Bply Client",
                owner=False,
                x=951.1,
                y=164.5,
            ),
        ]
        client["multiplayer"]["participants"] = [  # type: ignore[index]
            participant(
                participant_id=1,
                name="FUN DENIER",
                owner=True,
                x=951.1,
                y=164.5,
            ),
            participant(
                participant_id=0x2B00000000000001,
                name="Bply Host",
                owner=False,
                x=952.5,
                y=163.6,
            ),
        ]

        self.assertTrue(shared_hub_views_converged(host, client))

    def test_shared_hub_wait_matches_native_peers_with_lua_bots(
        self,
    ) -> None:
        def row(
            participant_id: int,
            name: str,
            *,
            owner: bool,
            controller_kind: str,
            x: float,
            y: float,
        ) -> dict[str, object]:
            return {
                "id": participant_id,
                "name": name,
                "owner": owner,
                "controller_kind": controller_kind,
                "connected": True,
                "ready": True,
                "in_run": False,
                "scene_kind": "SharedHub",
                "x": x,
                "y": y,
            }

        def state(
            participants: list[dict[str, object]],
        ) -> dict[str, object]:
            return {
                "scene": {"kind": "hub"},
                "loadingScreen": {"active": False},
                "multiplayer": {
                    "sessionState": "in-hub",
                    "sessionStatus": "Ready",
                    "participantCount": len(participants),
                    "participants": participants,
                },
            }

        ember_id = 0x1000000000000000
        brook_id = ember_id + 1
        host = state(
            [
                row(
                    1,
                    "FUN DENIER",
                    owner=True,
                    controller_kind="Native",
                    x=952.5,
                    y=163.6,
                ),
                row(
                    ember_id,
                    "Ember",
                    owner=False,
                    controller_kind="LuaBrain",
                    x=1027.5,
                    y=79.9,
                ),
                row(
                    brook_id,
                    "Brook",
                    owner=False,
                    controller_kind="LuaBrain",
                    x=983.9,
                    y=203.2,
                ),
                row(
                    0x2B00000000000002,
                    "Bply Client",
                    owner=False,
                    controller_kind="Native",
                    x=951.1,
                    y=164.5,
                ),
            ]
        )
        client = state(
            [
                row(
                    1,
                    "FUN DENIER",
                    owner=True,
                    controller_kind="Native",
                    x=951.1,
                    y=164.5,
                ),
                row(
                    ember_id,
                    "Ember",
                    owner=False,
                    controller_kind="LuaBrain",
                    x=1027.5,
                    y=79.9,
                ),
                row(
                    brook_id,
                    "Brook",
                    owner=False,
                    controller_kind="LuaBrain",
                    x=983.9,
                    y=203.2,
                ),
                row(
                    0x2B00000000000001,
                    "Bply Host",
                    owner=False,
                    controller_kind="Native",
                    x=952.5,
                    y=163.6,
                ),
            ]
        )

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
                "target": "workstation20.example",
                "username": "client-b",
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
            document["client"]["ssh"]["target"] = (  # type: ignore[index]
                "client-b@workstation20.example"
            )
            with self.assertRaisesRegex(ConfigError, "host-only target"):
                self._load_document(root, document)
            document["client"]["ssh"]["target"] = (  # type: ignore[index]
                "workstation20.example"
            )
            document["client"]["ssh"]["stageRoot"] = (  # type: ignore[index]
                r"C:\Users\client-b\other"
            )
            with self.assertRaisesRegex(ConfigError, "sd-<token>-stage"):
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

    def test_native_enemy_render_assertion_uses_local_screen_projection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "native-enemy.png"
            image = Image.new("RGB", (100, 100), (20, 20, 20))
            for y in range(45, 56):
                for x in range(45, 56):
                    image.putpixel(
                        (x, y),
                        (220, 180, 40) if (x + y) % 2 else (40, 80, 220),
                    )
            image.save(capture)
            state = {
                "viewport": {"width": 100, "height": 100},
                "nativeEnemies": [
                    {
                        "address": 0x1234,
                        "dead": False,
                        "hp": 2.5,
                        "screen_valid": True,
                        "screen_x": 50.0,
                        "screen_y": 50.0,
                    }
                ],
            }

            result = _native_enemy_render_assertion(state, capture)

            self.assertEqual(
                result["accepted"][0]["localActorAddress"],
                0x1234,
            )

    def test_authority_damage_log_records_accepted_remote_claims(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "loader.log"
            log_path.write_text(
                "[2026-07-31 04:46:17.004] Multiplayer enemy damage "
                "claim accepted. participant_id=3098476543630901250 "
                "target_network_actor_id=281543696187396 "
                "damage=1.000000 before_hp=2.500000 "
                "after_hp=1.500000 position_applied=1\n",
                encoding="utf-8",
            )
            rows = []

            offset, partial = _drain_authority_damage_log(
                log_path,
                0,
                "",
                rows,
            )

            self.assertEqual(offset, log_path.stat().st_size)
            self.assertEqual(partial, "")
            self.assertEqual(
                rows,
                [
                    {
                        "sequence": 0,
                        "monotonicMs": 0,
                        "sourceParticipantId": 3098476543630901250,
                        "targetNetworkActorId": 281543696187396,
                        "targetHpBefore": 2.5,
                        "targetHpAfter": 1.5,
                        "damage": 1.0,
                        "claimedDamage": 1.0,
                        "sourceNativeTypeId": 0,
                        "sourceOwnerNativeTypeId": 0,
                        "sourceGameplaySlot": -1,
                        "evidenceSource": "host-authority-log",
                        "evidencePeer": "host",
                        "authoritative": True,
                    }
                ],
            )

    def test_real_primary_damage_rejects_contact_only_edges(self) -> None:
        config = SimpleNamespace(
            host=SimpleNamespace(loadout_element="fire"),
            client=SimpleNamespace(loadout_element="fire"),
        )
        participant_ids = {"host": 11, "clientB": 22}
        contact_rows = {
            role: [
                {
                    "sourceParticipantId": participant_ids[role],
                    "sourceNativeTypeId": 1,
                    "damage": 1.0,
                }
            ]
            for role in participant_ids
        }

        with self.assertRaisesRegex(
            RealFlowFailure,
            "real projectile-sourced",
        ):
            _real_primary_damage_metrics(
                config,
                [
                    {
                        "sourceParticipantId": participant_id,
                        "damage": 1.0,
                        "authoritative": True,
                    }
                    for participant_id in participant_ids.values()
                ],
                contact_rows,
                participant_ids,
            )

    def test_real_primary_damage_requires_origin_and_authority(self) -> None:
        config = SimpleNamespace(
            host=SimpleNamespace(loadout_element="fire"),
            client=SimpleNamespace(loadout_element="fire"),
        )
        participant_ids = {"host": 11, "clientB": 22}
        origins = {
            role: [
                {
                    "sourceParticipantId": participant_ids[role],
                    "sourceNativeTypeId": 0x7D4,
                    "damage": 4.0,
                }
            ]
            for role in participant_ids
        }
        metrics = _real_primary_damage_metrics(
            config,
            [
                {
                    "sourceParticipantId": participant_id,
                    "damage": 4.0,
                    "authoritative": True,
                }
                for participant_id in participant_ids.values()
            ],
            origins,
            participant_ids,
        )

        self.assertEqual(metrics["missing"], [])
        self.assertEqual(
            metrics["fighters"]["clientB"]["expectedSourceNativeTypeId"],
            0x7D4,
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

    def test_runtime_state_includes_endurance_terminal_and_death_fields(
        self,
    ) -> None:
        state = normalize_state(
            {
                "ui.surface_id": "game_over",
                "game_over.command_epoch": "7",
                "game_over.accepted_epoch": "7",
                "game_over.run_nonce": "91",
                "game_over.authority_participant_id": "1001",
                "game_over.pending_dispatch": "false",
                "game_over.dispatch_count": "1",
                "spectator.active": "true",
                "spectator.phase": "spectating",
                "spectator.target_participant_id": "1002",
                "barrier.active": "true",
                "barrier.released": "true",
                "barrier.timed_out": "false",
                "barrier.run_nonce": "91",
                "barrier.release_reason": "mutual-visibility",
                "mp.participant_count": "1",
                "participant.1.owner": "true",
                "participant.1.hp": "0",
                "participant.1.life_max": "2.5",
                "participant.1.death_presentation_tick": "42",
                "participant.1.presentation_flags": "59",
            }
        )

        self.assertEqual(state["ui"]["surfaceId"], "game_over")
        self.assertTrue(terminal_game_over(state))
        state["gameOver"]["dispatchCount"] = 2
        self.assertFalse(terminal_game_over(state))
        self.assertEqual(state["deathSpectator"]["phase"], "spectating")
        self.assertTrue(state["runLoadingBarrier"]["released"])
        participant = state["multiplayer"]["participants"][0]
        self.assertEqual(participant["life_max"], 2.5)
        self.assertEqual(participant["death_presentation_tick"], 42)

    def test_replicated_damage_ids_map_each_fighter_from_other_peer_view(
        self,
    ) -> None:
        sample = {
            "host": {
                "multiplayer": {
                    "participants": [
                        {
                            "id": 1,
                            "kind": "LocalHuman",
                            "owner": True,
                        },
                        {
                            "id": 0x2B00000000000002,
                            "kind": "RemoteParticipant",
                            "owner": False,
                        },
                    ]
                }
            },
            "clientB": {
                "multiplayer": {
                    "participants": [
                        {
                            "id": 1,
                            "kind": "LocalHuman",
                            "owner": True,
                        },
                        {
                            "id": 0x2B00000000000001,
                            "kind": "RemoteParticipant",
                            "owner": False,
                        },
                    ]
                }
            },
        }

        self.assertEqual(
            _replicated_damage_participant_ids(sample),
            {
                "host": 0x2B00000000000001,
                "clientB": 0x2B00000000000002,
            },
        )

    def test_endurance_stats_count_death_respawn_and_damage_by_participant(
        self,
    ) -> None:
        def sample(
            *,
            elapsed: float,
            host_hp: float,
            client_hp: float,
            host_tick: int = 0,
            client_tick: int = 0,
        ) -> dict[str, object]:
            def state(hp: float, tick: int, owner_id: int) -> dict[str, object]:
                return {
                    "wave": {"index": 3},
                    "combat": {"waveIndex": 3},
                    "world": {"waveIndex": 3},
                    "player": {
                        "valid": True,
                        "x": elapsed,
                        "y": 0.0,
                        "hp": hp,
                        "maxHp": 2.0,
                    },
                    "multiplayer": {
                        "participants": [
                            {
                                "owner": True,
                                "id": owner_id,
                                "hp": hp,
                                "life_max": 2.0,
                                "death_presentation_tick": tick,
                            }
                        ]
                    },
                }

            return {
                "elapsedSeconds": elapsed,
                "utcNanoseconds": round(elapsed * 1_000_000_000),
                "host": state(host_hp, host_tick, 101),
                "clientB": state(client_hp, client_tick, 202),
            }

        tracker = FighterStatsTracker({"host": 101, "clientB": 202})
        tracker.observe(sample(elapsed=1.0, host_hp=2.0, client_hp=2.0))
        deaths = tracker.observe(
            sample(
                elapsed=2.0,
                host_hp=0.0,
                client_hp=2.0,
                host_tick=1,
            )
        )
        respawns = tracker.observe(
            sample(elapsed=4.0, host_hp=2.0, client_hp=2.0)
        )
        stats = tracker.result(
            [
                {
                    "sourceParticipantId": 101,
                    "damage": 0.75,
                },
                {
                    "sourceParticipantId": 202,
                    "damage": 0.5,
                },
            ],
            [
                {
                    "targetParticipantId": 101,
                    "damage": 1.0,
                }
            ],
        )

        self.assertEqual([row["event"] for row in deaths], ["death"])
        self.assertEqual([row["event"] for row in respawns], ["respawn"])
        self.assertEqual(stats["host"]["deaths"], 1)
        self.assertEqual(stats["host"]["respawns"], 1)
        self.assertEqual(stats["host"]["damageDealt"], 0.75)
        self.assertEqual(stats["clientB"]["damageDealt"], 0.5)

    def test_endurance_monitor_reports_transport_failure_immediately(
        self,
    ) -> None:
        def state(*, failures: int) -> dict[str, object]:
            return {
                "wave": {"index": 1},
                "combat": {"waveIndex": 1},
                "world": {"waveIndex": 1},
                "scene": {"name": "testrun"},
                "player": {
                    "valid": True,
                    "x": 1.0,
                    "y": 2.0,
                    "hp": 2.0,
                    "maxHp": 2.0,
                },
                "nativeEnemies": [],
                "replicatedEnemies": [],
                "gameOver": {
                    "commandEpoch": 0,
                    "acceptedEpoch": 0,
                    "runNonce": 0,
                    "authorityParticipantId": 0,
                    "pendingDispatch": False,
                    "dispatchCount": 0,
                },
                "multiplayer": {
                    "participants": [],
                    "transportReady": True,
                    "sessionStatus": "ready",
                    "packetsSent": 10,
                    "packetsReceived": 10,
                    "steamSendFailures": failures,
                    "steamReliableSendFailures": 0,
                    "lastSteamSendFailureResult": 25 if failures else 0,
                },
            }

        monitor = EnduranceAnomalyMonitor()
        findings = monitor.observe(
            {
                "elapsedSeconds": 1.0,
                "host": state(failures=1),
                "clientB": state(failures=0),
            },
            {
                "host": {"brain.think_count": 1},
                "clientB": {"brain.think_count": 1},
            },
            {"host": True, "clientB": True},
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["kind"], "steam-send-failure")
        self.assertTrue(is_capture_milestone(5))
        self.assertFalse(is_capture_milestone(4))

    def test_endurance_wave_uses_replicated_authority_summary(self) -> None:
        state = {
            "wave": {"index": 2},
            "combat": {"waveIndex": 9},
            "world": {"waveIndex": 7},
        }

        self.assertEqual(effective_wave(state), 2)

    def test_endurance_monitor_detects_one_way_receive_stall(self) -> None:
        def state(*, sent: int, received: int) -> dict[str, object]:
            return {
                "wave": {"index": 1},
                "combat": {"waveIndex": 1},
                "world": {"waveIndex": 1},
                "scene": {"name": "testrun"},
                "player": {
                    "valid": True,
                    "x": float(sent),
                    "y": 2.0,
                    "hp": 2.0,
                    "maxHp": 2.0,
                },
                "nativeEnemies": [],
                "replicatedEnemies": [],
                "gameOver": {
                    "commandEpoch": 0,
                    "acceptedEpoch": 0,
                    "runNonce": 0,
                    "authorityParticipantId": 0,
                    "pendingDispatch": False,
                    "dispatchCount": 0,
                },
                "multiplayer": {
                    "participants": [],
                    "transportReady": True,
                    "sessionStatus": "Ready",
                    "packetsSent": sent,
                    "packetsReceived": received,
                    "steamSendFailures": 0,
                    "steamReliableSendFailures": 0,
                    "lastSteamSendFailureResult": 0,
                },
            }

        monitor = EnduranceAnomalyMonitor()
        bots = {
            "host": {"brain.think_count": 1},
            "clientB": {"brain.think_count": 1},
        }
        monitor.observe(
            {
                "elapsedSeconds": 1.0,
                "host": state(sent=10, received=10),
                "clientB": state(sent=10, received=10),
            },
            bots,
            {"host": True, "clientB": True},
        )
        findings = monitor.observe(
            {
                "elapsedSeconds": 32.0,
                "host": state(sent=50, received=40),
                "clientB": state(sent=40, received=10),
            },
            bots,
            {"host": True, "clientB": True},
        )

        self.assertEqual([row["kind"] for row in findings], ["packet-stall"])
        self.assertEqual(
            findings[0]["evidence"]["secondsWithoutReceiveProgress"][
                "clientB"
            ],
            31.0,
        )

    def test_endurance_monitor_detects_casting_without_enemy_damage(
        self,
    ) -> None:
        def state(*, enemy_hp: float, packets: int) -> dict[str, object]:
            enemies = (
                [
                    {
                        "dead": False,
                        "hp": enemy_hp,
                    }
                ]
                if enemy_hp > 0.0
                else []
            )
            return {
                "wave": {"index": 2},
                "combat": {"waveIndex": 1},
                "world": {"waveIndex": 0},
                "scene": {"name": "testrun"},
                "player": {
                    "valid": True,
                    "x": float(packets),
                    "y": 2.0,
                    "hp": 50.0,
                    "maxHp": 50.0,
                },
                "nativeEnemies": enemies,
                "replicatedEnemies": [],
                "gameOver": {
                    "commandEpoch": 0,
                    "acceptedEpoch": 0,
                    "runNonce": 0,
                    "authorityParticipantId": 0,
                    "pendingDispatch": False,
                    "dispatchCount": 0,
                },
                "multiplayer": {
                    "participants": [],
                    "transportReady": True,
                    "sessionStatus": "Ready",
                    "packetsSent": packets,
                    "packetsReceived": packets,
                    "steamSendFailures": 0,
                    "steamReliableSendFailures": 0,
                    "lastSteamSendFailureResult": 0,
                },
            }

        monitor = EnduranceAnomalyMonitor()
        client_state = state(enemy_hp=0.0, packets=1)
        monitor.observe(
            {
                "elapsedSeconds": 1.0,
                "host": state(enemy_hp=10.0, packets=1),
                "clientB": client_state,
            },
            {
                "host": {
                    "brain.think_count": 1,
                    "brain.cast_accepted": 1,
                    "brain.target_distance": 100.0,
                    "brain.target_network_actor_id": 9001,
                    "brain.mode": "kite",
                },
                "clientB": {"brain.think_count": 1},
            },
            {"host": True, "clientB": False},
        )
        findings = monitor.observe(
            {
                "elapsedSeconds": 62.0,
                "host": state(enemy_hp=10.0, packets=62),
                "clientB": state(enemy_hp=0.0, packets=62),
            },
            {
                "host": {
                    "brain.think_count": 62,
                    "brain.cast_accepted": 20,
                    "brain.target_distance": 100.0,
                    "brain.target_network_actor_id": 9001,
                    "brain.mode": "kite",
                },
                "clientB": {"brain.think_count": 62},
            },
            {"host": True, "clientB": False},
        )

        no_damage = next(
            row
            for row in findings
            if row["kind"] == "host-bot-no-damage-progress"
        )
        self.assertEqual(
            no_damage["evidence"]["castsWithoutEnemyHpProgress"],
            19,
        )

    def test_runtime_state_preserves_large_participant_ids(self) -> None:
        participant_id = 0x2B00000000000002
        state = normalize_state(
            {
                "mp.participant_count": "1",
                "participant.1.id": str(participant_id),
            }
        )

        self.assertEqual(
            state["multiplayer"]["participants"][0]["id"],
            participant_id,
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

    def test_ws20_client_waits_for_ready_game_before_setting_lobby_id(
        self,
    ) -> None:
        worker = (
            ROOT / "scripts/Run-RealFlowWindowsSessionWorker.ps1"
        ).read_text(encoding="utf-8")
        start_client = worker.split(
            "function Start-Client {", 1
        )[1].split("function Invoke-RealInput {", 1)[0]

        self.assertNotIn('-Name "Ready"', start_client)
        self.assertEqual(start_client.count('-Name "Host Game"'), 2)
        self.assertEqual(start_client.count('-Name "Join Game"'), 2)
        self.assertLess(
            start_client.index("Set-LauncherLobbyId"),
            start_client.index('-Name "Join Game"'),
        )
        self.assertIn('-Name "Launch Game"', start_client)

    def test_ws20_safe_path_guard_covers_every_bot_runtime_file(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary)
            bot_root = source_root / "mods" / "bot-brain"
            nested = bot_root / "scripts" / "policy"
            nested.mkdir(parents=True)
            (bot_root / "manifest.json").write_text("{}\n")
            longest = nested / "long-policy-descriptor.lua"
            longest.write_text("return {}\n")
            harness = SimpleNamespace(
                source_root=source_root,
                bot_play_for_me=True,
            )

            path = _longest_staged_runtime_path(
                harness,
                r"C:\Users\client-b\sd-botendure-stage\r\l\data"
                r"\runtime\instances\bplyc\stage\SolomonDark.exe",
            )

        self.assertTrue(path.endswith(r"long-policy-descriptor.lua"))
        self.assertIn("\\.sdmod\\runtime\\mods\\", path)

    def test_ws20_uses_the_compact_owned_stage_layout(self) -> None:
        source = (
            ROOT / "tools" / "_real_flow_e2e" / "ws20.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'run_root = ntpath.join(connection.stage_root, "r")',
            source,
        )
        self.assertIn('bundle_root = ntpath.join(run_root, "l")', source)
        self.assertIn("Move-Item -LiteralPath $source", source)

    def test_ws20_verified_prestage_uploads_only_dynamic_run_state(
        self,
    ) -> None:
        source = (
            ROOT / "tools" / "_real_flow_e2e" / "ws20.py"
        ).read_text(encoding="utf-8")

        branch = source.split(
            "if harness.reuse_ws20_prestage:", 1
        )[1].split("else:", 1)[0]
        self.assertIn(
            'prestage_bundle = ntpath.join(prestage_root, "launcher")',
            branch,
        )
        self.assertIn(
            'prestage_game = ntpath.join(prestage_root, "game")',
            branch,
        )
        self.assertIn("Copy-Item -LiteralPath $bundleSource", branch)
        self.assertIn('client.bundle_root / "mods"', branch)
        self.assertIn('client.bundle_root / ".sdmod-test-data"', branch)
        self.assertNotIn("harness.game_directory, run_root", branch)

    def test_ws20_worker_has_bounded_interactive_steam_attach_probe(
        self,
    ) -> None:
        worker = (
            ROOT / "scripts/Run-RealFlowWindowsSessionWorker.ps1"
        ).read_text(encoding="utf-8")
        probe = worker.split(
            "function Test-SteamAttach {", 1
        )[1].split("function Close-RunProcesses {", 1)[0]

        self.assertIn("__join-steam-lobby", probe)
        self.assertIn(
            "$process.WaitForExit([int]$Request.TimeoutSeconds",
            probe,
        )
        self.assertIn('$process.StandardInput.WriteLine("leave")', probe)
        self.assertIn("$current.ProcessId -eq $process.Id", probe)
        self.assertIn("escapes the owned stage", probe)
        self.assertIn('"probe-steam" { Test-SteamAttach', worker)

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

    def test_ws20_bot_settings_are_written_inside_the_owned_stage(
        self,
    ) -> None:
        class FakeConnection:
            stage_root = r"C:\Users\client-b\sd-botendure-stage"
            stage_leaf = "sd-botendure-stage"

            def __init__(self) -> None:
                self.confined: list[str] = []
                self.scripts: list[str] = []

            def _require_confined(self, path: str) -> None:
                self.confined.append(path)

            def run_ps(self, script: str) -> str:
                self.scripts.append(script)
                return ""

        peer = object.__new__(Ws20Peer)
        peer.connection = FakeConnection()
        peer.config = SimpleNamespace(instance="bply-endure-client")
        peer.runtime_root = (
            r"C:\Users\client-b\sd-botendure-stage\r\bply-run\runtime"
        )

        output = peer.write_bot_settings(
            mod_id="bot.brain",
            values={
                "play_for_me": True,
                "play_for_me_behavior": "skirmisher",
                "roster": [],
            },
        )

        self.assertEqual(len(peer.connection.confined), 1)
        self.assertEqual(len(peer.connection.scripts), 1)
        self.assertTrue(
            output.startswith(
                "%USERPROFILE%\\sd-botendure-stage\\"
            )
        )
        self.assertIn("bot.brain.json", output)
        self.assertIn("[System.IO.File]::Replace", peer.connection.scripts[0])
        self.assertIn(".bply-tmp", peer.connection.scripts[0])
        self.assertIn(".bply-backup", peer.connection.scripts[0])
        self.assertIn(
            "Replace($temporary,$path,$backup)",
            peer.connection.scripts[0],
        )
        self.assertNotIn(
            "Replace($temporary,$path,$null)",
            peer.connection.scripts[0],
        )

    def test_ws20_stage_is_claimed_before_preparation_and_deleted_if_owned(
        self,
    ) -> None:
        connection = object.__new__(RemoteWindowsConnection)
        connection.stage_root = (
            r"C:\Users\client-b\sd-botendure-stage"
        )
        connection.profile_root = r"C:\Users\client-b"
        connection.stage_leaf = "sd-botendure-stage"
        scripts: list[str] = []
        connection.run_ps = scripts.append  # type: ignore[method-assign]

        connection.create_stage_root()

        self.assertEqual(len(scripts), 1)
        self.assertIn("staging root must be new", scripts[0])
        self.assertIn(
            "New-Item -ItemType Directory -Path $target",
            scripts[0],
        )
        self.assertIn(r"C:\Users\client-b", scripts[0])
        self.assertNotIn("$env:USERPROFILE", scripts[0])
        source = (
            ROOT / "tools/verify_real_flow_e2e.py"
        ).read_text(encoding="utf-8")
        claim = source.index("connection.create_stage_root()")
        prepare = source.index("Ws20Peer.prepare(config, connection)")
        self.assertLess(claim, prepare)
        self.assertIn(
            "if remote_stage_claimed:\n"
            "                    connection.remove_stage_root()",
            source,
        )

    def test_ws20_windows_openssh_uses_separate_login_and_windows_paths(
        self,
    ) -> None:
        connection = object.__new__(RemoteWindowsConnection)
        connection.ssh = SimpleNamespace(
            executable=(
                "/mnt/c/Windows/System32/OpenSSH/ssh.exe"
            ),
            username="client-b",
        )
        connection.key_argument = r"C:\Users\User\.ssh\ws20-key"

        ssh = connection._ssh_base()

        self.assertEqual(
            ssh[0],
            "/mnt/c/Windows/System32/OpenSSH/ssh.exe",
        )
        self.assertEqual(ssh[ssh.index("-l") + 1], "client-b")
        self.assertEqual(
            connection._scp_executable(),
            "/mnt/c/Windows/System32/OpenSSH/scp.exe",
        )
        with mock.patch(
            "tools._real_flow_e2e.ws20.windows_path",
            return_value=r"D:\evidence\capture.png",
        ) as convert:
            local = connection._local_scp_path(
                Path("/mnt/d/evidence/capture.png")
            )
        self.assertEqual(local, r"D:\evidence\capture.png")
        convert.assert_called_once()

    def test_ws20_remote_errors_redact_accounts_paths_and_steam_ids(
        self,
    ) -> None:
        connection = object.__new__(RemoteWindowsConnection)
        connection.ssh = SimpleNamespace(
            target="workstation20.tail.example",
            username="ssh-login",
        )
        connection.stage_root = (
            r"C:\Users\interactive-owner\sd-botendure-stage"
        )
        connection.stage_leaf = "sd-botendure-stage"

        output = connection.sanitize_text(
            "ssh-login at workstation20.tail.example: "
            r"C:\Users\interactive-owner\sd-botendure-stage\control "
            r"C:\Users\another-account\file "
            "76561198000000000"
        )

        self.assertEqual(
            output,
            "client B at workstation20: "
            r"%USERPROFILE%\sd-botendure-stage\control "
            r"%USERPROFILE%\file <steam-id>",
        )

    def test_ws20_controller_accepts_only_a_safe_profile_stage_leaf(
        self,
    ) -> None:
        controller = (
            ROOT / "scripts/Invoke-RealFlowWindowsSession.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "^sd-[a-z0-9][a-z0-9-]{0,31}-stage$",
            controller,
        )
        self.assertIn("GetOwnerSid", controller)
        self.assertIn("Win32_UserProfile", controller)
        self.assertIn("GetDirectoryName($resolvedStageRoot)", controller)
        self.assertIn("$info.LastRunTime.ToUniversalTime()", controller)
        self.assertNotIn(
            'Join-Path $env:USERPROFILE "sd-netrepro-stage"',
            controller,
        )

    def test_ws20_connection_resolves_stage_from_interactive_steam_profile(
        self,
    ) -> None:
        source = (
            ROOT / "tools/_real_flow_e2e/ws20.py"
        ).read_text(encoding="utf-8")

        self.assertIn("GetOwnerSid", source)
        self.assertIn("Win32_UserProfile", source)
        self.assertIn("$expected=Join-Path $profile", source)
        self.assertNotIn(
            "$expected=Join-Path $env:USERPROFILE",
            source,
        )

    def test_client_attack_precedes_paired_capture(self) -> None:
        source = (
            ROOT / "tools/verify_real_flow_e2e.py"
        ).read_text(encoding="utf-8")
        run_body = source.split(
            "def run(config: HarnessConfig", 1
        )[1]
        materialized = run_body.index(
            'result["clientEnemyMaterialization"] = ('
        )
        damage = run_body.index(
            'sampler.set_phase("client-real-water-damage")',
            materialized,
        )
        capture = run_body.index(
            'sampler.set_phase("paired-render-capture")',
            materialized,
        )

        self.assertLess(damage, capture)

    def test_endurance_prearms_client_before_match_and_host_before_enemy_wait(
        self,
    ) -> None:
        source = (
            ROOT / "tools" / "verify_real_flow_e2e.py"
        ).read_text(encoding="utf-8")
        run_body = source.split(
            "def run(config: HarnessConfig", 1
        )[1]

        client_prearm = run_body.index(
            'sampler.set_phase("bot-play-client-prearm")'
        )
        match_start = run_body.index(
            'sampler.set_phase("match-start")'
        )
        endurance_start = run_body.index(
            'result["botPlayForMe"] = _run_bot_play_endurance('
        )
        ordinary_enemy_wait = run_body.index(
            'result["clientEnemyMaterialization"] = (',
            endurance_start,
        )

        self.assertLess(client_prearm, match_start)
        self.assertLess(endurance_start, ordinary_enemy_wait)
        self.assertIn(
            '"clientB": client_prearm_request',
            source,
        )
        endurance_body = source.split(
            "def _run_bot_play_endurance(", 1
        )[1].split("\ndef ", 1)[0]
        monitor_phase = endurance_body.index(
            'sampler.set_phase("bot-play-endurance")'
        )
        materialization = endurance_body.index(
            "_assert_client_enemy_materialization(sample)"
        )
        self.assertLess(monitor_phase, materialization)
        self.assertNotIn(
            "_wait_for_client_enemy_materialization(config, sampler)",
            endurance_body,
        )

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

    def test_ws20_capture_preserves_remote_clock_and_uses_controller_bound(
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
            '"remoteCaptureUtcNanoseconds": remote_capture_ns',
            adapter,
        )
        self.assertIn(
            '"captureWindowStartUtcNanoseconds": started_ns',
            adapter,
        )
        self.assertIn(
            '"captureWindowEndUtcNanoseconds": capture_completed_ns',
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
