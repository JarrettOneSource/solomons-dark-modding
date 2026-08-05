"""Contracts for the opt-in, live native-menu layout recorder."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class NativeMenuLayoutCaptureContractTests(unittest.TestCase):
    def test_sprite_capture_is_explicitly_opt_in(self) -> None:
        source = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "menu_layout_capture.inl"
        )
        self.assertIn("SDMOD_NATIVE_MENU_LAYOUT_CAPTURE", source)
        self.assertIn("SDMOD_NATIVE_BOOT_CAPTURE_DIRECTORY", source)
        self.assertIn("if (!requested)", source)
        self.assertIn("menu_layout_capture_enabled = requested", source)

    def test_loader_probe_uses_live_progress_and_native_draws(self) -> None:
        source = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "menu_layout_capture.inl"
        )
        for token in (
            "kNativeLoaderProgressNumerator",
            "kNativeLoaderProgressDenominator",
            "kNativeLoaderCompleteFlag",
            "HookNativeLoaderRender",
            "Loader.",
            "CaptureD3d9BackBufferBmp",
            "native-loader-layout.json",
        ):
            self.assertIn(token, source)

    def test_layout_api_retains_transient_screens(self) -> None:
        header = read("SolomonDarkModLoader/include/debug_ui_overlay.h")
        implementation = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "public_api_surface_dispatch.inl"
        )
        state = read("SolomonDarkModLoader/src/debug_ui_overlay.cpp")
        bindings = read(
            "SolomonDarkModLoader/src/lua_engine_bindings_ui.cpp"
        )
        self.assertIn("TryGetDebugUiLayoutSnapshot", header)
        self.assertIn("layout_snapshots_by_screen", state)
        self.assertIn("layout_snapshots_by_screen.find", implementation)
        self.assertIn("luaL_checkstring(state, 1)", bindings)
        self.assertIn('"get_layout_snapshot"', bindings)

        frame = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "label_resolution_surface_registry_and_frame_render.inl"
        )
        self.assertIn("kMenuLayoutCaptureTrackedDialogPriorityMs", frame)
        self.assertIn("menu_layout_capture_enabled", frame)

    def test_position_draw_capture_survives_the_gameplay_hook_chain(self) -> None:
        header = read("SolomonDarkModLoader/include/debug_ui_overlay.h")
        public_api = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/public_api.inl"
        )
        gameplay_hook = read(
            "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
            "gameplay_hud_hooks.inl"
        )
        observer = "ObserveDebugUiMenuSpritePositionDraw"
        self.assertIn(observer, header)
        self.assertIn(observer, public_api)
        self.assertIn("ObserveMenuSpritePositionDraw(sprite, x, y, false)", public_api)
        self.assertIn(f"{observer}(self, x, y)", gameplay_hook)

    def test_layout_capture_deduplicates_hook_chain_draws_and_names_create_phases(self) -> None:
        source = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "menu_layout_capture.inl"
        )
        self.assertIn("same_layout_element", source)
        self.assertIn('has_art("Create.9")', source)
        self.assertIn('return "create_element"', source)
        self.assertIn('has_art("Create.16")', source)
        self.assertIn('return "create_discipline"', source)
        self.assertIn('element.action_id.rfind("pause_menu.", 0)', source)
        self.assertIn('return "pause_menu"', source)

    def test_settings_rows_are_captured_from_live_immediate_mode_draws(self) -> None:
        source = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "menu_layout_capture.inl"
        )
        for token in (
            "kSettingsScalarRowAddress",
            "kSettingsToggleRowAddress",
            "BeginSettingsRowCapture",
            "ObserveActiveSettingsRowBounds",
            "HookSettingsScalarRow",
            "HookSettingsToggleRow",
        ):
            self.assertIn(token, source)

        text_hooks = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "exact_text_capture/render_hooks.inl"
        )
        self.assertIn("ObserveActiveSettingsRowTextQuad(arg2)", text_hooks)

    def test_recorder_never_measures_layout_from_the_reference_image(self) -> None:
        recorder = read("scripts/Record-NativeMenuLayout.ps1")
        self.assertIn("sd.ui.get_layout_snapshot", recorder)
        self.assertIn("sd.debug.capture_backbuffer", recorder)
        self.assertIn("Get-FileHash", recorder)
        self.assertNotIn("GetPixel", recorder)
        self.assertNotIn("image recognition", recorder.lower())

    def test_native_click_helper_is_pinned_to_the_exact_owned_stage(self) -> None:
        helper = read("scripts/Invoke-ExactProcessClientClick.ps1")
        for token in (
            "Get-CimInstance Win32_Process",
            "ExecutablePath",
            "StringComparison]::OrdinalIgnoreCase",
            "ClientToScreen",
            "SetForegroundWindow",
            "mouse_event",
        ):
            self.assertIn(token, helper)


if __name__ == "__main__":
    unittest.main()
