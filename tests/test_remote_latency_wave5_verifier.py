from __future__ import annotations

import importlib.util
import inspect
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/verify_remote_latency_wave5.py"
SPEC = importlib.util.spec_from_file_location(
    "verify_remote_latency_wave5",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def event(name: str, mono_us: int, **fields: object) -> dict[str, object]:
    return {
        "schema": 1,
        "event": name,
        "mono_us": mono_us,
        **fields,
    }


class RemoteLatencyWaveFiveVerifierTests(unittest.TestCase):
    def test_wave_scenario_uses_two_offensive_element_profiles(self) -> None:
        self.assertEqual(
            [
                (row["element"], row["behavior"])
                for row in verifier.BOT_ROSTER
            ],
            [
                ("fire", "skirmisher"),
                ("water", "striker"),
            ],
        )

    def test_distribution_interpolates_p99(self) -> None:
        result = verifier.distribution([1, 2, 3, 4])

        self.assertEqual(result["count"], 4)
        self.assertEqual(result["maximum"], 4.0)
        self.assertAlmostEqual(result["p99"], 3.97)

    def test_integer_preserves_adjacent_participant_ids_above_2_to_53(
        self,
    ) -> None:
        first = 1_152_921_504_606_851_072
        second = first + 1

        self.assertEqual(
            verifier.integer({"id": str(first)}, "id"),
            first,
        )
        self.assertEqual(
            verifier.integer({"id": str(second)}, "id"),
            second,
        )

    def test_remote_lua_response_is_unwrapped_like_local_client(self) -> None:
        response = json.dumps(
            {
                "ok": True,
                "print_output": "scene=hub\nwave.number=0",
                "results": [],
                "error": "",
            }
        )

        output = verifier.unwrap_lua_exec_response(response)

        self.assertEqual(output, "scene=hub\nwave.number=0\n")

    def test_pair_probe_explicitly_targets_bot_brain(self) -> None:
        config = self._config()
        _, peer = verifier.direction_peers(
            config,
            "b",
            "netlag-post-b01",
        )
        response = json.dumps(
            {
                "ok": True,
                "print_output": "scene=hub",
                "results": [],
                "error": "",
            }
        )

        with mock.patch.object(
            verifier,
            "local_lua",
            return_value=response,
        ) as invoke:
            values = verifier.peer_values(config, peer)

        self.assertEqual(values["scene"], "hub")
        sent_code = invoke.call_args.args[2]
        self.assertTrue(
            sent_code.startswith(
                "-- sdmod-exec-target: bot.brain\n"
            )
        )
        self.assertIn(
            'return table.concat(output, "\\n")',
            verifier.PAIR_PROBE,
        )
        self.assertNotIn("print(", verifier.PAIR_PROBE)

    def test_read_only_ssh_retries_a_transient_timeout(self) -> None:
        config = self._config()
        with (
            mock.patch.object(
                verifier,
                "ssh",
                side_effect=(
                    subprocess.TimeoutExpired(["ssh"], 20),
                    "ready\n",
                ),
            ) as invoke,
            mock.patch.object(verifier.time, "sleep"),
        ):
            output = verifier.ssh_read_only(
                config,
                "ss -H -lunp",
            )

        self.assertEqual(output, "ready\n")
        self.assertEqual(invoke.call_count, 2)

    def test_direction_b_places_real_windows_client_locally(self) -> None:
        config = self._config()

        host, client = verifier.direction_peers(
            config,
            "b",
            "netlag-post-b01",
        )

        self.assertEqual(host.location, "remote")
        self.assertEqual(host.local_port, 51511)
        self.assertEqual(client.location, "local")
        self.assertEqual(client.local_port, 50312)
        self.assertEqual(client.player_name, "client B")

    def test_testrun_waits_for_public_and_native_wave_start(
        self,
    ) -> None:
        config = self._config()
        host, _ = verifier.direction_peers(
            config,
            "b",
            "netlag-pre-b01",
        )
        testrun_output = "ok=true\nresult="
        wave_state_output = "\n".join(
            (
                "wave.number=1",
                "wave.phase=active",
                "combat.available=true",
                "combat.wave_index=1",
                "combat.active=true",
            )
        )

        with mock.patch.object(
            verifier,
            "lua",
            side_effect=(
                testrun_output,
                wave_state_output,
            ),
        ) as invoke:
            testrun = verifier.start_testrun(config, host)
            waves = verifier.wait_retail_wave_start(config, host)

        self.assertEqual(testrun["ok"], "true")
        self.assertEqual(waves["wave.number"], "1")
        self.assertEqual(invoke.call_count, 2)
        self.assertIs(
            invoke.call_args_list[1].args[2],
            verifier.WAVE_START_PROBE,
        )

    def test_wave_start_rejects_native_only_progress(self) -> None:
        config = self._config()
        host, _ = verifier.direction_peers(
            config,
            "b",
            "netlag-pre-b01",
        )
        state_output = "\n".join(
            (
                "wave.number=0",
                "wave.phase=idle",
                "combat.available=true",
                "combat.wave_index=1",
                "combat.active=true",
            )
        )

        with mock.patch.object(
            verifier,
            "lua",
            return_value=state_output,
        ):
            with self.assertRaises(verifier.VerificationFailure):
                verifier.wait_retail_wave_start(
                    config,
                    host,
                    timeout=0.001,
                )

    def test_solomon_dig_probe_uses_local_native_actor_list(self) -> None:
        self.assertIn(
            "sd.world.list_actors()",
            verifier.SOLOMON_DIG_PROBE,
        )
        self.assertNotIn(
            "sd.world.get_replicated_actors()",
            verifier.SOLOMON_DIG_PROBE,
        )

    def test_solomon_dig_placement_uses_real_actor_after_observer_arm(self) -> None:
        config = self._config()
        host, client = verifier.direction_peers(
            config,
            "b",
            "netlag-pre-b01",
        )

        with mock.patch.object(
            verifier,
            "lua",
            side_effect=(
                "armed=true\nsamples=1",
                "armed=true\nsamples=1",
                "\n".join(
                    (
                        "solomon_actor=123",
                        "solomon_state=0",
                        "solomon_acquired=0",
                        "write_x=true",
                        "write_y=true",
                        "rebind=true",
                        "placed=true",
                        "error=",
                    )
                ),
            ),
        ) as invoke:
            host_result = verifier.arm_solomon_dig_flow(config, host)
            client_result = verifier.arm_solomon_dig_flow(
                config, client
            )
            placement = verifier.place_client_at_solomon(
                config, client
            )

        self.assertEqual(host_result["armed"], "true")
        self.assertEqual(client_result["armed"], "true")
        self.assertEqual(placement["placed"], "true")
        placement_code = invoke.call_args_list[2].args[2]
        self.assertIn("sd.world.list_actors()", placement_code)
        self.assertIn("sd.world.rebind_actor", placement_code)
        self.assertIn(
            "solomon_dig_interaction_state", placement_code
        )
        self.assertNotIn("start_waves", placement_code)

    def test_stock_ui_action_waits_for_completed_dispatch(self) -> None:
        config = self._config()
        host, _ = verifier.direction_peers(
            config,
            "b",
            "netlag-pre-b01",
        )

        with mock.patch.object(
            verifier,
            "lua",
            side_effect=(
                "ok=true\nrequest=42",
                "status=queued\nerror=",
                "status=dispatched\nerror=",
            ),
        ) as invoke:
            result = verifier.activate_ui_action(
                config,
                host,
                "main_menu.play",
                "main_menu",
            )

        self.assertEqual(result["request"], "42")
        self.assertEqual(result["status"], "dispatched")
        self.assertEqual(invoke.call_count, 3)

    def test_stock_ui_navigation_waits_for_loaded_lua_mod_state(
        self,
    ) -> None:
        config = self._config()
        _, client = verifier.direction_peers(
            config,
            "b",
            "netlag-pre-b01",
        )

        with (
            mock.patch.object(
                verifier,
                "peer_values",
                side_effect=(
                    verifier.VerificationFailure(
                        "No loaded Lua mod state is available."
                    ),
                    {"scene": "hub"},
                ),
            ) as probe,
            mock.patch.object(verifier.time, "sleep"),
        ):
            result = verifier.enter_hub_through_stock_ui(
                config,
                client,
            )

        self.assertEqual(result["selection"], "already-in-hub")
        self.assertEqual(probe.call_count, 2)

    def test_stock_ui_navigation_does_not_repeat_action_on_same_surface(
        self,
    ) -> None:
        config = self._config()
        host, _ = verifier.direction_peers(
            config,
            "b",
            "netlag-pre-b01",
        )
        picker = {
            "scene": "transition",
            "surface": "control_scheme_picker",
            "actions": "control_scheme_picker.select_wasd",
        }

        with (
            mock.patch.object(
                verifier,
                "peer_values",
                side_effect=(picker, picker, {"scene": "hub"}),
            ),
            mock.patch.object(
                verifier,
                "activate_ui_action",
                return_value={
                    "ok": "true",
                    "request": "1",
                    "status": "dispatched",
                },
            ) as activate,
            mock.patch.object(verifier.time, "sleep"),
        ):
            result = verifier.enter_hub_through_stock_ui(
                config,
                host,
            )

        self.assertEqual(result["selection"], "already-in-hub")
        activate.assert_called_once_with(
            config,
            host,
            "control_scheme_picker.select_wasd",
            "control_scheme_picker",
        )

    def test_run_roster_recovers_only_stalled_unmaterialized_bots(
        self,
    ) -> None:
        config = self._config()
        host, client = verifier.direction_peers(
            config,
            "b",
            "netlag-pre-b01",
        )
        peer_view = {
            "scene": "testrun",
            "brain.desired": "2",
            "brain.active": "2",
            "bot.count": "2",
            "bot.1.id": "1152921504606851072",
            "bot.1.name": "Ember",
            "bot.1.materialized": "false",
            "bot.2.id": "1152921504606851073",
            "bot.2.name": "Brook",
            "bot.2.materialized": "false",
        }
        stalled = {
            "host": dict(peer_view),
            "client": dict(peer_view),
        }
        ready = {"host": {"ready": "true"}, "client": {"ready": "true"}}

        with (
            mock.patch.object(
                verifier,
                "wait_pair_roster",
                side_effect=(
                    verifier.VerificationFailure("stalled"),
                    ready,
                ),
            ) as wait_roster,
            mock.patch.object(
                verifier,
                "pair_views",
                return_value=stalled,
            ),
            mock.patch.object(
                verifier,
                "request_bot_respawn",
                return_value={"ok": "true", "error": ""},
            ) as respawn,
        ):
            result = verifier.wait_run_roster(
                config,
                host,
                client,
            )

        self.assertEqual(result["views"], ready)
        self.assertEqual(
            result["recovery"]["reason"],
            "post-switch bot sync was not requeued",
        )
        respawn.assert_called_once_with(config, host)
        self.assertEqual(
            [call.kwargs["timeout"] for call in wait_roster.call_args_list],
            [15, 105],
        )

    def test_run_roster_does_not_recover_a_non_bot_failure(self) -> None:
        config = self._config()
        host, client = verifier.direction_peers(
            config,
            "b",
            "netlag-pre-b01",
        )
        with (
            mock.patch.object(
                verifier,
                "wait_pair_roster",
                side_effect=verifier.VerificationFailure("disconnected"),
            ),
            mock.patch.object(
                verifier,
                "pair_views",
                return_value={
                    "host": {"scene": "hub"},
                    "client": {"scene": "testrun"},
                },
            ),
            mock.patch.object(
                verifier,
                "request_bot_respawn",
            ) as respawn,
        ):
            with self.assertRaisesRegex(
                verifier.VerificationFailure,
                "disconnected",
            ):
                verifier.wait_run_roster(config, host, client)

        respawn.assert_not_called()

    def test_remote_and_local_launchers_disable_native_quick_start(
        self,
    ) -> None:
        remote = (
            ROOT / "scripts/Run-RemoteLatencyPeer.sh"
        ).read_text(encoding="utf-8")
        local = (
            ROOT / "scripts/Launch-RemoteLatencyPeer.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("SDMOD_MULTIPLAYER_QUICK_START= \\", remote)
        self.assertNotIn(
            "SDMOD_MULTIPLAYER_QUICK_START=1",
            remote,
        )
        self.assertIn(
            'SDMOD_MULTIPLAYER_QUICK_START = ""',
            local,
        )
        self.assertIn(
            "control_scheme_picker.select_wasd",
            MODULE_PATH.read_text(encoding="utf-8"),
        )
        for source in (remote, local):
            self.assertIn(
                "harness.remote_latency_controller",
                source,
            )
            self.assertIn("SDMOD_UI_SANDBOX_PRESET", source)
            self.assertIn("idle", source)
            self.assertIn(
                "SDMOD_LUA_EXEC_TARGET_MOD_ID",
                source,
            )
            self.assertIn(
                "harness.remote_latency_controller",
                source,
            )
        self.assertIn("netlag-wave-*.bmp", remote)
        for startup_field in (
            "multiplayerFoundationReady",
            "botRuntimeInitialized",
            "luaLoadedModCount",
            "runtimeTickServiceRunning",
        ):
            self.assertIn(startup_field, remote)
        self.assertIn("record_game_identity", remote)
        self.assertIn("pid_matches_start_time", remote)
        self.assertIn("wineserver\" -k", remote)

        controller_manifest = json.loads(
            (
                ROOT
                / "tools/remote_latency_controller_mod/manifest.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            controller_manifest["id"],
            "harness.remote_latency_controller",
        )
        self.assertLess(controller_manifest["priority"], 0)

        engine = (
            ROOT
            / "SolomonDarkModLoader/src/lua_engine/"
            "lua_exec_target.inl"
        ).read_text(encoding="utf-8")
        pump = (
            ROOT
            / "SolomonDarkModLoader/src/lua_engine_main_thread_pump.inl"
        ).read_text(encoding="utf-8")
        pipe = (
            ROOT
            / "SolomonDarkModLoader/src/lua_exec_pipe.cpp"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"SDMOD_LUA_EXEC_TARGET_MOD_ID"',
            engine,
        )
        self.assertIn(
            "return configured == mods.end()",
            engine,
        )
        self.assertIn(
            "ResolveLuaExecTargetState(request->target_mod_id)",
            pump,
        )
        self.assertIn("-- sdmod-exec-target: ", pipe)

    def test_client_solomon_dig_requires_local_and_remote_acquisition(
        self,
    ) -> None:
        config = self._config()
        host, client = verifier.direction_peers(
            config,
            "b",
            "netlag-pre-b01",
        )

        with mock.patch.object(
            verifier,
            "peer_values",
            side_effect=(
                {
                    "acquired": "true",
                    "target_slot": "3",
                    "error": "",
                },
                {
                    "placed": "true",
                    "acquired": "true",
                    "target_slot": "0",
                    "error": "",
                },
            ),
        ) as probe:
            result = verifier.wait_client_solomon_dig(
                config,
                host,
                client,
            )

        self.assertEqual(
            result["clientB"]["target_slot"],
            "0",
        )
        self.assertIs(
            probe.call_args_list[0].args[2],
            verifier.SOLOMON_DIG_FLOW_PROBE,
        )

    def test_solomon_dig_is_armed_before_run_transition(
        self,
    ) -> None:
        source = inspect.getsource(verifier.run_session)

        self.assertLess(
            source.index(
                'result["solomonDigArm"] = {'
            ),
            source.index('result["runStart"] = start_testrun'),
        )
        self.assertLess(
            source.index(
                "run_roster = wait_run_roster"
            ),
            source.index(
                'result["solomonDigPlacement"] = '
                "place_client_at_solomon"
            ),
        )
        self.assertLess(
            source.index(
                'result["solomonDigPlacement"] = '
                "place_client_at_solomon"
            ),
            source.index(
                'result["solomonDig"] = wait_client_solomon_dig'
            ),
        )

    def test_bounded_line_reader_rejects_partial_response(self) -> None:
        read_descriptor, write_descriptor = verifier.os.pipe()
        try:
            with verifier.os.fdopen(
                read_descriptor, "rb", closefd=False
            ) as stream:
                verifier.os.write(write_descriptor, b"partial")
                with self.assertRaises(verifier.VerificationFailure):
                    verifier.read_bounded_line(
                        stream,
                        bytearray(),
                        timeout=0.001,
                        label="test response",
                    )
        finally:
            verifier.os.close(read_descriptor)
            verifier.os.close(write_descriptor)

    def test_time_index_returns_only_inclusive_window(self) -> None:
        rows = [
            event("present", 30),
            event("present", 10),
            event("present", 20),
            event("present", 40),
        ]

        selected = verifier._rows_between(
            verifier._time_index(rows),
            20,
            30,
        )

        self.assertEqual(
            [int(row["mono_us"]) for row in selected],
            [20, 30],
        )

    def test_enemy_motion_flags_only_unexpected_large_steps(self) -> None:
        metrics = {
            "observedSteps": 0,
            "movingSteps": 0,
            "totalDistance": 0.0,
            "maximumStep": 0.0,
            "unexpectedLargeStepCount": 0,
        }
        previous = {11: (0.0, 0.0)}
        values = {
            "enemy.count": "1",
            "enemy.1.id": "11",
            "enemy.1.dead": "false",
            "enemy.1.hp": "2.5",
            "enemy.1.x": "400",
            "enemy.1.y": "0",
        }

        verifier.update_enemy_motion(values, previous, metrics)

        self.assertEqual(metrics["observedSteps"], 1)
        self.assertEqual(metrics["movingSteps"], 1)
        self.assertEqual(metrics["maximumStep"], 400.0)
        self.assertEqual(metrics["unexpectedLargeStepCount"], 1)

    def test_progress_assist_uses_host_native_enemy_death_path(
        self,
    ) -> None:
        config = self._config()
        host, _ = verifier.direction_peers(
            config,
            "b",
            "netlag-pre-b01",
        )

        with mock.patch.object(
            verifier,
            "lua",
            return_value=(
                "ok=true\nhealth=true\ndeath=true\nseh=0\n"
                "actor=123\nnetwork_id=456\nold_hp=2.5\nmax_hp=2.5"
            ),
        ) as invoke:
            result = verifier.retire_one_host_enemy(config, host)

        self.assertEqual(result["ok"], "true")
        code = invoke.call_args.args[2]
        self.assertIn("sd.gameplay.set_run_enemy_health", code)
        self.assertIn("sd.world.trigger_enemy_death", code)

    def test_survival_guard_is_disabled_before_vital_acceptance(
        self,
    ) -> None:
        config = self._config()
        _, client = verifier.direction_peers(
            config,
            "b",
            "netlag-pre-b01",
        )
        with mock.patch.object(
            verifier,
            "lua",
            return_value="disabled=true",
        ) as invoke:
            result = verifier.disarm_human_survival_guard(
                config, client
            )

        self.assertEqual(result["disabled"], "true")
        self.assertIn(
            "_G.__netlag_human_survival = false",
            invoke.call_args.args[2],
        )

    def test_remote_capture_defers_transfer_until_peer_stop(self) -> None:
        config = self._config()
        host, _ = verifier.direction_peers(
            config,
            "b",
            "netlag-pre-b01",
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(
                verifier,
                "lua",
                return_value="ok=true\nerror=",
            ) as invoke,
            mock.patch.object(verifier, "ssh") as ssh_call,
            mock.patch.object(verifier, "scp_from") as scp_call,
        ):
            result = verifier.capture_peer(
                config,
                host,
                Path(directory),
                "wave-01",
            )

        self.assertEqual(
            result["pendingRemoteArtifact"],
            "netlag-wave-01-host.bmp",
        )
        self.assertIn(
            "netlag-wave-01-host.bmp",
            invoke.call_args.args[2],
        )
        ssh_call.assert_not_called()
        scp_call.assert_not_called()

    def test_wave_screenshots_are_armed_on_wave_started(self) -> None:
        config = self._config()
        host, _ = verifier.direction_peers(
            config,
            "b",
            "netlag-pre-b01",
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(
                verifier,
                "lua",
                return_value="registered=true",
            ) as invoke,
        ):
            result = verifier.arm_wave_screenshot_capture(
                config,
                host,
                Path(directory),
            )

        self.assertEqual(result["registered"], "true")
        code = invoke.call_args.args[2]
        self.assertIn('sd.events.on("wave.started"', code)
        self.assertIn("netlag-wave-01-host.bmp", code)
        self.assertIn("netlag-wave-05-host.bmp", code)

    def test_event_screenshot_records_require_both_peers(self) -> None:
        config = self._config()
        host, client = verifier.direction_peers(
            config,
            "b",
            "netlag-pre-b01",
        )
        status = {
            f"wave.{wave}.{field}": value
            for wave in range(1, 6)
            for field, value in (
                ("seen", "true"),
                ("ok", "true"),
                ("error", ""),
            )
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(
                verifier,
                "query_wave_screenshot_capture",
                return_value=status,
            ),
        ):
            records, observed, error = (
                verifier.collect_wave_screenshot_records(
                    config,
                    host,
                    client,
                    Path(directory),
                )
            )

        self.assertEqual(set(records), {"1", "2", "3", "4", "5"})
        self.assertEqual(error, "")
        self.assertEqual(observed["host"]["wave.5.ok"], "true")
        self.assertEqual(
            records["5"]["captureTrigger"],
            "wave.started",
        )

    def test_progression_assist_does_not_wait_for_deferred_screenshots(
        self,
    ) -> None:
        source = inspect.getsource(verifier.monitor_wave_five)

        self.assertNotIn("str(host_wave) in screenshots", source)

    def test_local_capture_defers_png_conversion_until_stop(self) -> None:
        config = self._config()
        _, client = verifier.direction_peers(
            config,
            "b",
            "netlag-pre-b01",
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(
                verifier,
                "lua",
                return_value="ok=true\nerror=",
            ),
        ):
            result = verifier.capture_peer(
                config,
                client,
                Path(directory),
                "wave-01",
            )

        self.assertTrue(
            result["pendingLocalArtifact"].endswith(
                "wave-01-client.bmp"
            )
        )
        self.assertNotIn("quality", result)

    def test_deferred_local_capture_is_validated_after_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            raw = session / "screenshots/wave-01-client.bmp"
            output = session / "screenshots/wave-01-client.png"
            raw.parent.mkdir(parents=True)
            image = verifier.Image.new("RGB", (128, 128))
            image.putdata(
                [
                    (
                        index % 256,
                        (index // 256) % 256,
                        (index * 17) % 256,
                    )
                    for index in range(128 * 128)
                ]
            )
            image.save(raw)
            result = {
                "waveFive": {
                    "screenshots": {
                        "1": {
                            "peers": {
                                "client": {
                                    "role": "client",
                                    "location": "local",
                                    "path": str(output),
                                    "pendingLocalArtifact": str(raw),
                                }
                            }
                        }
                    }
                }
            }

            verifier.finalize_deferred_screenshots(
                result, session
            )

            peer = result["waveFive"]["screenshots"]["1"][
                "peers"
            ]["client"]
            self.assertTrue(output.is_file())
            self.assertFalse(raw.exists())
            self.assertGreater(peer["quality"]["uniqueColors"], 500)

    def test_receive_gap_with_continuous_host_send_is_transport_stall(
        self,
    ) -> None:
        host = [
            event(
                "packet_send",
                100_000 + index * 50_000,
                sequence=10 + index,
                kind=7,
                bytes=1800 if index == 2 else 200,
            )
            for index in range(5)
        ]
        client = [
            event(
                "packet_receive",
                1_000_000,
                sequence=10,
                sequence_delta=0,
                arrival_gap_us=0,
            ),
            event(
                "packet_receive",
                1_400_000,
                sequence=14,
                sequence_delta=4,
                arrival_gap_us=400_000,
                missing_before=3,
            ),
            event(
                "receive_batch",
                1_400_010,
                packet_count=4,
                duration_us=400,
            ),
            event(
                "present",
                1_400_020,
                gap_us=16_000,
                duration_us=500,
            ),
        ]

        stalls = verifier.classify_client_transport_stalls(
            client,
            host,
        )

        self.assertEqual(len(stalls), 1)
        self.assertEqual(stalls[0]["stage"], "network_receive_gap")
        self.assertTrue(stalls[0]["senderContinuous"])
        self.assertEqual(stalls[0]["missingSenderSequencesInGap"], 3)
        self.assertEqual(stalls[0]["missingLikelyFragmentedInGap"], 1)
        self.assertEqual(stalls[0]["recoveryBatchPackets"], 4)

    def test_large_apply_after_gap_is_classified_as_catch_up(
        self,
    ) -> None:
        host = [
            event(
                "packet_send",
                100_000 + index * 50_000,
                sequence=20 + index,
                kind=7,
                bytes=200,
            )
            for index in range(5)
        ]
        client = [
            event(
                "packet_receive",
                2_000_000,
                sequence=20,
                sequence_delta=0,
                arrival_gap_us=0,
            ),
            event(
                "packet_receive",
                2_400_000,
                sequence=24,
                sequence_delta=4,
                arrival_gap_us=400_000,
                missing_before=3,
            ),
            event(
                "packet_apply",
                2_400_020,
                sequence=24,
                duration_us=90_000,
            ),
        ]

        stalls = verifier.classify_client_transport_stalls(
            client,
            host,
        )

        self.assertEqual(stalls[0]["stage"], "catch_up_apply")
        self.assertEqual(stalls[0]["maxPacketApplyUs"], 90_000)

    def test_sender_idle_render_and_tick_gap_is_not_transport_stall(
        self,
    ) -> None:
        host = [
            event(
                "packet_send",
                1_000_000,
                sequence=30,
                kind=7,
                bytes=200,
            ),
            event(
                "packet_send",
                1_400_000,
                sequence=31,
                kind=7,
                bytes=200,
            ),
        ]
        client = [
            event(
                "packet_receive",
                2_000_000,
                sequence=30,
                sequence_delta=0,
                arrival_gap_us=0,
            ),
            event(
                "packet_receive",
                2_400_000,
                sequence=31,
                sequence_delta=1,
                arrival_gap_us=400_000,
            ),
            event(
                "transport_tick",
                2_400_010,
                gap_us=400_000,
                duration_us=500,
            ),
            event(
                "present",
                2_400_020,
                gap_us=400_000,
                duration_us=500,
            ),
        ]

        stalls = verifier.classify_client_transport_stalls(
            client,
            host,
        )

        self.assertEqual(stalls, [])

    def test_blocking_logger_caller_takes_priority_over_apply_time(
        self,
    ) -> None:
        host = [
            event(
                "packet_send",
                100_000 + index * 50_000,
                sequence=40 + index,
                kind=16,
                bytes=200,
            )
            for index in range(5)
        ]
        client = [
            event(
                "packet_receive",
                3_000_000,
                sequence=40,
                sequence_delta=0,
                arrival_gap_us=0,
            ),
            event(
                "packet_receive",
                3_400_000,
                sequence=44,
                sequence_delta=4,
                arrival_gap_us=400_000,
            ),
            event(
                "packet_apply",
                3_400_010,
                sequence=44,
                duration_us=181_408,
            ),
            event(
                "logger_write",
                3_400_020,
                total_us=181_074,
                flush_us=180_820,
            ),
        ]

        stalls = verifier.classify_client_transport_stalls(
            client,
            host,
        )

        self.assertEqual(stalls[0]["stage"], "blocking_log_write")
        self.assertEqual(stalls[0]["maxLoggerWriteUs"], 181_074)

    def test_summary_separates_async_logger_caller_and_writer_cost(
        self,
    ) -> None:
        rows = [
            event(
                "logger_enqueue",
                10,
                mutex_wait_us=3,
                queue_depth=2,
                queued=True,
                dropped_line_count=0,
                total_us=17,
            ),
            event(
                "logger_flush",
                20,
                line_count=1,
                bytes=80,
                dropped_line_count=0,
                duration_us=180_000,
            ),
        ]

        summary = verifier.summarize_telemetry(rows)

        self.assertEqual(summary["loggerTotalUs"]["maximum"], 17.0)
        self.assertEqual(
            summary["loggerAsyncFlushUs"]["maximum"],
            180_000.0,
        )
        self.assertEqual(summary["loggerQueueDepth"]["maximum"], 2.0)
        self.assertEqual(summary["loggerDroppedLineCount"], 0)

    def test_summary_reports_fragmentation_and_recovery(self) -> None:
        rows = [
            event(
                "packet_send",
                10,
                backend="local_udp",
                kind=42,
                sequence=1,
                bytes=1800,
                result=1800,
            ),
            event(
                "recovery_send",
                20,
                retransmit=True,
                pending_count=2,
                previous_send_age_ms=101,
            ),
            event(
                "recovery_ack",
                30,
                retired_count=1,
            ),
        ]

        summary = verifier.summarize_telemetry(rows)

        self.assertEqual(summary["oversizedDatagramCount"], 1)
        self.assertEqual(summary["largestDatagramBytes"], 1800)
        self.assertEqual(summary["retransmitCount"], 1)
        self.assertEqual(summary["recoveryAckCount"], 1)
        self.assertEqual(summary["recoveryRetiredCount"], 1)

    def test_summary_uses_physical_datagram_size_after_transport_fragmenting(
        self,
    ) -> None:
        rows = [
            event(
                "packet_send",
                10,
                backend="local_udp",
                kind=31,
                sequence=1,
                bytes=1704,
                wire_bytes=1752,
                datagram_count=2,
                largest_datagram_bytes=1200,
                transport_fragmented=True,
                result=1704,
            ),
            event(
                "fragment_receive",
                20,
                kind=31,
                sequence=1,
                wire_arrival_gap_us=40_000,
                assembly_complete=False,
            ),
            event(
                "fragment_receive",
                21,
                kind=31,
                sequence=1,
                wire_arrival_gap_us=100,
                assembly_complete=True,
            ),
        ]

        summary = verifier.summarize_telemetry(rows)

        self.assertEqual(summary["oversizedDatagramCount"], 0)
        self.assertEqual(summary["largestDatagramBytes"], 1200)
        self.assertEqual(summary["transportFragmentedPacketCount"], 1)
        self.assertEqual(summary["fragmentAssemblyCompleteCount"], 1)
        self.assertEqual(
            summary["receiveArrivalGapUs"]["maximum"],
            40_000,
        )

    def test_receiver_thread_keeps_transport_live_during_present_gap(
        self,
    ) -> None:
        host = [
            event(
                "packet_send",
                1_000_000 + index * 50_000,
                sequence=100 + index,
                kind=20,
                bytes=382,
            )
            for index in range(8)
        ]
        client = [
            event(
                "packet_receive",
                1_000_000 + index * 50_000,
                sequence=100 + index,
                sequence_delta=1,
                arrival_gap_us=50_000,
                wire_arrival_gap_us=50_000,
                physical_datagram=True,
                ingress_queue_depth=index + 1,
            )
            for index in range(8)
        ]
        client.extend(
            [
                event(
                    "transport_tick",
                    1_360_000,
                    gap_us=360_000,
                    duration_us=1500,
                ),
                event(
                    "packet_apply",
                    1_360_010,
                    sequence=100,
                    queue_age_us=360_000,
                    duration_us=50,
                ),
                event(
                    "receive_batch",
                    1_360_020,
                    packet_count=8,
                    duration_us=500,
                ),
                event(
                    "present",
                    1_360_030,
                    gap_us=360_000,
                    duration_us=400,
                ),
            ]
        )

        spikes = verifier.classify_client_spikes(client, host)
        stalls = verifier.classify_client_transport_stalls(
            client,
            host,
        )

        self.assertEqual(len(spikes), 1)
        self.assertEqual(spikes[0]["stage"], "render_present_stall")
        self.assertEqual(spikes[0]["maxIngressQueueDepth"], 8)
        self.assertEqual(spikes[0]["maxPacketQueueAgeUs"], 360_000)
        self.assertEqual(stalls, [])

    def test_slow_named_transport_stage_is_reported(self) -> None:
        client = [
            event(
                "transport_stage",
                1_300_000,
                stage="native_reconciliation",
                duration_us=300_000,
            ),
            event(
                "transport_tick",
                1_300_010,
                gap_us=31_000,
                duration_us=301_000,
            ),
            event(
                "present",
                1_300_020,
                gap_us=300_000,
                duration_us=400,
            ),
        ]

        spikes = verifier.classify_client_spikes(client, [])

        self.assertEqual(len(spikes), 1)
        self.assertEqual(
            spikes[0]["stage"],
            "transport_stage_stall:native_reconciliation",
        )
        self.assertEqual(
            spikes[0]["slowestTransportStage"],
            "native_reconciliation",
        )
        self.assertEqual(spikes[0]["maxTransportStageUs"], 300_000)

    def test_jsonl_analysis_correlates_missing_sequences(self) -> None:
        host_rows = [
            event(
                "packet_send",
                index * 10,
                sequence=index,
                kind=1,
                bytes=100,
            )
            for index in range(1, 6)
        ]
        client_rows = [
            event(
                "packet_receive",
                index * 12,
                sequence=index,
                sequence_delta=1,
                arrival_gap_us=12,
            )
            for index in (1, 2, 4, 5)
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            host_path = root / "host.jsonl"
            client_path = root / "client.jsonl"
            host_path.write_text(
                "".join(json.dumps(row) + "\n" for row in host_rows),
                encoding="utf-8",
            )
            client_path.write_text(
                "".join(json.dumps(row) + "\n" for row in client_rows),
                encoding="utf-8",
            )

            analysis = verifier.analyze_pair(
                host_path,
                client_path,
            )

        self.assertEqual(analysis["hostToClient"]["missingCount"], 1)
        self.assertEqual(
            analysis["hostToClient"]["missingSequences"][0]["sequence"],
            3,
        )

    @staticmethod
    def _config() -> object:
        return verifier.HarnessConfig(
            path=Path("/tmp/config.json"),
            ssh_executable=Path(
                "/mnt/c/Windows/System32/OpenSSH/ssh.exe"
            ),
            scp_executable=Path(
                "/mnt/c/Windows/System32/OpenSSH/scp.exe"
            ),
            ssh_alias="nfoservers-root",
            remote_root="/root/sd-netlag-20260728",
            remote_public_host="203.0.113.1",
            local_public_host="198.51.100.1",
            evidence_root=Path(
                "/mnt/d/codex-evidence/netlag-20260728"
            ),
            local_package_root=Path("/tmp/package"),
            local_game_root=Path("/tmp/game"),
            local_runtime_root=Path("/tmp/runtime"),
            local_lua_client=Path("/tmp/lua.exe"),
            local_host_port=50311,
            local_client_port=50312,
            remote_host_port=51511,
            remote_client_port=51512,
            timeout_seconds=900,
        )


if __name__ == "__main__":
    unittest.main()
