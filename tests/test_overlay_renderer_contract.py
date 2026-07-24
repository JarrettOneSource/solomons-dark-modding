#!/usr/bin/env python3
"""Regression tests for the shared D3D9 overlay rendering contract."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOADER_SOURCE = ROOT / "SolomonDarkModLoader" / "src"


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class OverlayRendererContractTests(unittest.TestCase):
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
