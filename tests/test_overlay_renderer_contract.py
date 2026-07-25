#!/usr/bin/env python3
"""Regression tests for the shared D3D9 overlay rendering contract."""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOADER_SOURCE = ROOT / "SolomonDarkModLoader" / "src"
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from normal_gameplay_debug_surface_guard import (  # noqa: E402
    NORMAL_PLAYER_SESSION_CONTEXTS,
    assert_debug_surfaces_empty,
)


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class OverlayRendererContractTests(unittest.TestCase):
    def test_live_log_guard_rejects_any_diagnostic_surface_leak(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "solomondarkmodloader.log"
            log_path.write_text(
                "Debug UI diagnostic surface set. "
                "enabled=0 registered=0 rendered=0\n",
                encoding="utf-8",
            )
            result = assert_debug_surfaces_empty([log_path])
            self.assertTrue(result["all_states_empty"])

            log_path.write_text(
                "Debug UI diagnostic surface set. "
                "enabled=1 registered=5 rendered=5\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                AssertionError,
                "registered or rendered",
            ):
                assert_debug_surfaces_empty([log_path])

    def test_live_log_guard_requires_runtime_state_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "solomondarkmodloader.log"
            log_path.write_text("ordinary loader log\n", encoding="utf-8")
            with self.assertRaisesRegex(
                AssertionError,
                "did not report",
            ):
                assert_debug_surfaces_empty([log_path])

    def test_live_log_guard_rejects_independent_status_surface_draws(
        self,
    ) -> None:
        leaked_draws = (
            "Multiplayer spectator HUD draw. ok=1 "
            'text="Spectating Client Player  |  '
            'Left / Right click: next player"',
            "Multiplayer level-up wait HUD draw. "
            "source=dx9_level_up_barrier ok=1 "
            'text="Waiting for Client Player"',
        )
        for leaked_draw in leaked_draws:
            with self.subTest(leaked_draw=leaked_draw):
                with tempfile.TemporaryDirectory() as directory:
                    log_path = (
                        Path(directory) / "solomondarkmodloader.log"
                    )
                    log_path.write_text(
                        "Debug UI diagnostic surface set. "
                        "enabled=0 registered=0 rendered=0\n"
                        f"{leaked_draw}\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        AssertionError,
                        "status surface",
                    ):
                        assert_debug_surfaces_empty([log_path])

    def test_guard_enforces_every_normal_player_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "solomondarkmodloader.log"
            log_path.write_text(
                "Debug UI diagnostic surface set. "
                "enabled=0 registered=0 rendered=0\n",
                encoding="utf-8",
            )
            for context in NORMAL_PLAYER_SESSION_CONTEXTS:
                with self.subTest(context=context):
                    result = assert_debug_surfaces_empty(
                        [log_path],
                        context=context,
                    )
                    self.assertEqual(context, result["context"])
                    self.assertTrue(result["all_states_empty"])
                    self.assertEqual(
                        [],
                        result["logs_checked"][0][
                            "status_surface_draws"
                        ],
                    )

    def test_normal_runtime_cannot_register_diagnostic_surfaces(self) -> None:
        runtime_flags = read(
            "SolomonDarkModLauncher/src/Staging/RuntimeStageFlags.cs"
        )
        loader = read("SolomonDarkModLoader/src/mod_loader.cpp")
        overlay_header = read(
            "SolomonDarkModLoader/include/debug_ui_overlay.h"
        )
        frame_renderer = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "label_resolution_surface_registry_and_frame_render.inl"
        )

        full_defaults = runtime_flags[
            runtime_flags.index(
                "private static RuntimeStageFlags CreateFullDefaults()"
            ) :
            runtime_flags.index(
                "private static RuntimeStageFlags "
                "CreateBootstrapOnlyDefaults()"
            )
        ]
        self.assertIn("LoaderDebugUi = false", full_defaults)
        self.assertIn(
            "const bool native_ui_bridge_required",
            loader,
        )
        self.assertIn(
            "native_ui_bridge_required || diagnostic_ui_enabled",
            loader,
        )
        self.assertIn(
            "InitializeDebugUiOverlay(diagnostic_ui_enabled)",
            loader,
        )
        self.assertNotIn(
            "diagnostic_visuals_enabled = true",
            overlay_header,
        )

        gate_start = frame_renderer.index(
            "DiagnosticSurfaceFrame RegisterDiagnosticSurfaceFrame("
        )
        gate_end = frame_renderer.index(
            "\n}", gate_start
        )
        gate = frame_renderer[gate_start:gate_end]
        self.assertIn(
            "if (!diagnostic_visuals_enabled)",
            gate,
        )
        self.assertIn("return {};", gate)
        self.assertIn(
            "Debug UI diagnostic surface set. enabled=",
            frame_renderer,
        )
        self.assertIn(
            "diagnostic_surface_frame.registered_surface_count",
            frame_renderer,
        )
        self.assertIn(
            "diagnostic_surface_frame.render_elements",
            frame_renderer,
        )
        self.assertNotIn(
            "render_elements.clear();",
            frame_renderer,
        )

        draw_start = frame_renderer.index(
            "for (const auto& element :\n"
            "         diagnostic_surface_frame.render_elements)"
        )
        draw_end = frame_renderer.index(
            "for (const auto& health_bar", draw_start
        )
        self.assertIn(
            "DrawObservedOverlayElement(",
            frame_renderer[draw_start:draw_end],
        )
        native_overlay_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (LOADER_SOURCE / "debug_ui_overlay").glob("*.inl")
        )
        self.assertEqual(
            native_overlay_source.count("DrawObservedOverlayElement("),
            2,
            "diagnostic elements gained a draw path outside the gated "
            "definition and single registered-surface loop",
        )

    def test_loader_status_surfaces_share_the_diagnostic_registration_gate(
        self,
    ) -> None:
        frame_renderer = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "label_resolution_surface_registry_and_frame_render.inl"
        )
        gate_start = frame_renderer.index(
            "DiagnosticSurfaceFrame RegisterDiagnosticSurfaceFrame("
        )
        gate_end = frame_renderer.index("\n}", gate_start)
        gate = frame_renderer[gate_start:gate_end]

        for token in (
            "multiplayer::TryBuildLevelUpWaitStatusText(",
            "multiplayer::TryBuildDeathSpectatorStatusText(",
            "frame.level_up_wait_text",
            "frame.death_spectator_text",
        ):
            self.assertIn(token, gate)
        self.assertLess(
            gate.index("if (!diagnostic_visuals_enabled)"),
            gate.index(
                "multiplayer::TryBuildLevelUpWaitStatusText("
            ),
        )
        self.assertLess(
            gate.index("if (!diagnostic_visuals_enabled)"),
            gate.index(
                "multiplayer::TryBuildDeathSpectatorStatusText("
            ),
        )

        self.assertIn(
            "gameplay_level_up_wait_text =\n"
            "        diagnostic_surface_frame.level_up_wait_text",
            frame_renderer,
        )
        self.assertIn(
            "gameplay_death_spectator_text =\n"
            "        diagnostic_surface_frame.death_spectator_text",
            frame_renderer,
        )
        self.assertEqual(
            1,
            frame_renderer.count(
                "multiplayer::TryBuildLevelUpWaitStatusText("
            ),
        )
        self.assertEqual(
            1,
            frame_renderer.count(
                "multiplayer::TryBuildDeathSpectatorStatusText("
            ),
        )

    def test_native_picker_owner_never_gets_a_loader_choice_surface(self) -> None:
        transport = read(
            "SolomonDarkModLoader/src/multiplayer_local_transport/"
            "public_cast_loot_api.inl"
        )
        function_start = transport.index(
            "bool TryBuildLevelUpWaitStatusText("
        )
        function_end = transport.index("\n}", function_start)
        function = transport[function_start:function_end]

        self.assertNotIn("Choose your skill upgrade", function)
        self.assertIn(
            "g_local_transport.local_peer_id",
            function,
        )
        self.assertIn(
            "waiting_participant_ids.erase(",
            function,
        )
        self.assertIn(
            "BuildLevelUpWaitStatusTextFromIds(",
            function,
        )

    def test_one_reset_aware_state_block_owns_all_overlay_callbacks(self) -> None:
        hook = read("SolomonDarkModLoader/src/d3d9_end_scene_hook.cpp")
        all_native_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in LOADER_SOURCE.rglob("*")
            if path.suffix in {".cpp", ".inl"}
        )

        state_block_creations = re.findall(
            r"CreateStateBlock\s*\(\s*D3DSBT_ALL",
            all_native_source,
        )
        self.assertEqual(len(state_block_creations), 1)
        for relative_path in (
            "SolomonDarkModLoader/src/lua_draw_renderer.cpp",
            "SolomonDarkModLoader/src/lua_ui_renderer.cpp",
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "label_resolution_surface_registry_and_frame_render.inl",
        ):
            self.assertNotIn("CreateStateBlock", read(relative_path))

        end_scene = hook[
            hook.index("HRESULT STDMETHODCALLTYPE HookEndScene(") :
            hook.index("HRESULT STDMETHODCALLTYPE HookReset(")
        ]
        self.assertLess(
            end_scene.index("callbacks[index](device);"),
            end_scene.index("original_end_scene(device)"),
        )
        reset = hook[
            hook.index("HRESULT STDMETHODCALLTYPE HookReset(") :
            hook.index("bool PatchHookSlot(")
        ]
        self.assertLess(
            reset.index("ReleaseFrameStateBlockUnlocked();"),
            reset.index("original_reset(device, presentation_parameters)"),
        )
        self.assertIn("kResetVtableIndex = 16", hook)
        self.assertIn("g_frame_state_block->Capture()", hook)
        self.assertIn("state_block->AddRef()", end_scene)
        self.assertIn("state_block->Release()", end_scene)
        self.assertGreaterEqual(hook.count("state_block->Apply()"), 2)

    def test_frame_hook_has_a_bounded_late_device_startup_window(self) -> None:
        hook = read("SolomonDarkModLoader/src/d3d9_end_scene_hook.cpp")

        self.assertIn(
            "kDeviceAcquireTimeoutMilliseconds = 10000",
            hook,
        )
        self.assertIn("kDeviceAcquirePollMilliseconds = 50", hook)
        self.assertIn(
            "GetTickCount64() + kDeviceAcquireTimeoutMilliseconds",
            hook,
        )

    def test_frame_hook_preserves_an_early_subscriber_for_device_retry(
        self,
    ) -> None:
        hook = read("SolomonDarkModLoader/src/d3d9_end_scene_hook.cpp")
        install = hook[
            hook.index("bool InstallD3d9FrameHook(") :
            hook.index("void RemoveD3d9FrameCallback(")
        ]

        self.assertIn("bool callback_registered = false;", install)
        self.assertIn(
            "if (callback_registered && g_hook_installed)",
            install,
        )
        acquire_failure = install[
            install.index("if (!TryAcquireDevicePointer(") :
            install.index("auto** vtable")
        ]
        self.assertIn(
            "g_callbacks[g_callback_count++] = callback;",
            acquire_failure,
        )
        self.assertIn("deferred callback until the next subscriber", install)
        self.assertIn("return true;", acquire_failure)

    def test_lua_draw_batches_runs_and_filters_sprites_linearly(self) -> None:
        renderer = read(
            "SolomonDarkModLoader/src/lua_draw_renderer/"
            "rendering_helpers.inl"
        )

        self.assertIn("class LuaDrawBatcher", renderer)
        self.assertIn("LuaDrawBatchMode::PointText", renderer)
        self.assertIn("LuaDrawBatchMode::LinearSprite", renderer)
        self.assertIn(
            "point_text ? D3DTEXF_POINT : D3DTEXF_LINEAR",
            renderer,
        )
        self.assertEqual(renderer.count("DrawPrimitiveUP("), 2)
        self.assertNotIn("D3DPT_TRIANGLESTRIP", renderer)
        self.assertIn("D3DPT_TRIANGLELIST", renderer)

    def test_generation_cache_reuses_unchanged_display_lists(self) -> None:
        runtime = read("SolomonDarkModLoader/src/lua_draw_runtime.cpp")
        renderer = read("SolomonDarkModLoader/src/lua_draw_renderer.cpp")

        self.assertIn("RefreshLuaDrawFrameSnapshots(", runtime)
        self.assertIn(
            "snapshot.generation == frame->second.generation",
            runtime,
        )
        self.assertIn(
            "snapshots->push_back(std::move(*cached));",
            runtime,
        )
        self.assertIn(
            "RefreshLuaDrawFrameSnapshots(&g_lua_draw_renderer.frame_snapshots)",
            renderer,
        )

    def test_gdi_font_atlas_has_one_shared_implementation(self) -> None:
        font_source = read(
            "SolomonDarkModLoader/src/d3d9_font_atlas.cpp"
        )
        lua_renderer = read(
            "SolomonDarkModLoader/src/lua_draw_renderer/"
            "rendering_helpers.inl"
        )
        debug_renderer = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "font_atlas_rendering.inl"
        )
        all_native_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in LOADER_SOURCE.rglob("*")
            if path.suffix in {".cpp", ".inl"}
        )

        self.assertEqual(all_native_source.count("CreateFontW("), 1)
        self.assertIn("D3DPOOL_MANAGED", font_source)
        self.assertIn("InitializeD3d9FontAtlas(", lua_renderer)
        self.assertIn("InitializeD3d9FontAtlas(", debug_renderer)

    def test_workspace_and_pair_launchers_never_kill_other_groups(self) -> None:
        reset = read("scripts/Reset-LocalRuntimeState.ps1")
        verify = read("scripts/Verify-Workspace.ps1")
        pair = read("scripts/Launch-LocalMultiplayerPair.ps1")
        pair_driver = read("tools/verify_local_multiplayer_sync.py")

        for script in (reset, verify, pair):
            self.assertNotRegex(
                script,
                r"Get-Process\s+SolomonDark\*?",
            )
        self.assertIn("[int[]]$OwnedProcessIds = @()", reset)
        self.assertNotIn("$env:APPDATA", reset)
        self.assertIn("Stop-OwnedSolomonDarkProcess", verify)
        self.assertIn(
            '$launcherContextArguments = @("--instance", $InstanceName)',
            verify,
        )
        self.assertIn(
            '$launcherContextArguments += @("--game-dir", $GameDirectory)',
            verify,
        )
        self.assertIn(". $launcherProcessHelpers", verify)
        self.assertIn("Invoke-LauncherWithEnvironment `", verify)
        self.assertNotIn("$output = & $launcher", verify)
        self.assertIn('"Lua engine initialized\\."', verify)
        self.assertNotIn("Lua engine stub initialized", verify)
        self.assertIn("kill_existing: bool = False", pair_driver)
        self.assertIn("if kill_existing:", pair_driver)
        self.assertIn('"-ProcessIdOutputPath"', pair_driver)
        self.assertNotIn('args.append("-NoKill")', pair_driver)


if __name__ == "__main__":
    unittest.main()
