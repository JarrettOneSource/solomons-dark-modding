"""Contracts for the opt-in, live native-menu layout recorder."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def read_menu_layout_capture() -> str:
    root = "SolomonDarkModLoader/src/debug_ui_overlay/"
    return "".join(
        read(root + filename)
        for filename in (
            "menu_layout_capture.inl",
            "menu_layout_capture_resolvers.inl",
            "menu_layout_capture_art_observation.inl",
            "menu_layout_capture_snapshot_and_hooks.inl",
        )
    )


def read_native_menu_recorder() -> str:
    return read("scripts/Record-NativeMenuLayout.ps1") + read(
        "scripts/NativeMenuCaptureSupport.ps1"
    )


class NativeMenuLayoutCaptureContractTests(unittest.TestCase):
    def test_sprite_capture_is_explicitly_opt_in(self) -> None:
        source = read_menu_layout_capture()
        self.assertIn("SDMOD_NATIVE_MENU_LAYOUT_CAPTURE", source)
        self.assertIn("SDMOD_NATIVE_BOOT_CAPTURE_DIRECTORY", source)
        self.assertIn("if (!requested)", source)
        self.assertIn("menu_layout_capture_enabled = requested", source)

    def test_loader_probe_uses_live_progress_and_native_draws(self) -> None:
        source = read_menu_layout_capture()
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

    def test_current_frame_tag_keeps_live_text_but_drops_stale_controls(self) -> None:
        api = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "public_api_surface_dispatch.inl"
        )
        bindings = read("SolomonDarkModLoader/src/lua_engine_bindings_ui.cpp")
        recorder = read_native_menu_recorder()
        self.assertIn("TryCaptureCurrentDebugUiLayoutSnapshot", api)
        self.assertIn('element.kind != "art"', api)
        self.assertIn('element.kind != "text"', api)
        self.assertIn("std::remove_if", api)
        self.assertIn("stale controls omitted", api)
        self.assertIn('screen_id == "profile_save_select"', api)
        self.assertIn('screen_id == "beta_notice"', api)
        self.assertIn('screen_id == "dark_cloud_search"', api)
        self.assertIn("capture_current_layout", bindings)
        self.assertIn("sd.ui.capture_current_layout", recorder)

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
        source = read_menu_layout_capture()
        self.assertIn("same_layout_element", source)
        self.assertIn('has_art("Create.9")', source)
        self.assertIn('return "create_element"', source)
        self.assertIn('has_art("Create.16")', source)
        self.assertIn('return "create_discipline"', source)
        self.assertIn('element.action_id.rfind("pause_menu.", 0)', source)
        self.assertIn('return "pause_menu"', source)
        self.assertIn("ContainsObservedTextAbove", source)
        self.assertIn('"hall of fame",', source)
        self.assertIn("100.0f", source)

    def test_settings_rows_are_captured_from_live_immediate_mode_draws(self) -> None:
        source = read_menu_layout_capture()
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
        recorder = read_native_menu_recorder()
        self.assertIn("sd.ui.capture_current_layout", recorder)
        self.assertIn("sd.debug.capture_backbuffer", recorder)
        self.assertIn("Get-FileHash", recorder)
        self.assertNotIn("GetPixel", recorder)
        self.assertNotIn("image recognition", recorder.lower())

    def test_recorders_settle_semantics_without_provenance_overrides(self) -> None:
        support = read("scripts/NativeMenuCaptureSupport.ps1")
        standalone = read("scripts/Record-NativeMenuLayout.ps1")
        transition = read("scripts/Record-NativeMenuTransition.ps1")
        confirmation = read("scripts/Confirm-NativeMenuLayoutAnimation.ps1")
        motion = read("scripts/Observe-NativeMenuMotionCapability.ps1")
        resolver = read("tools/resolve_native_menu_ambient_campaign.py")
        importer_launcher = read("scripts/Import-NativeMenuSpecialCaptures.ps1")
        importer = read("tools/import_native_menu_special_captures_v25.py")
        classifier = read("tools/native_menu_ambient_lifecycle.py")
        self.assertIn(
            "NativeMenuSettleConsecutiveSamples = 40",
            support,
            "standalone settlement must require forty identical samples",
        )
        self.assertIn(
            "NativeMenuSettleMinimumSpanMilliseconds = 2000",
            support,
            "standalone settlement must span at least two seconds",
        )
        self.assertIn(
            "Invoke-NativeMenuSettlementClassifier",
            support,
            "settlement must classify animated geometry from the measured window",
        )
        self.assertIn(
            "Debug UI native menu-layout capture hooks installed.",
            support,
            "the recorder must reject a process whose capture hook cannot run",
        )
        self.assertIn(
            '$ErrorActionPreference = "Continue"',
            support,
            "native stderr must reach the busy/dead exit-code discriminator",
        )
        self.assertIn(
            "animated_element_ids = @(",
            support,
            "settlement must carry the measured animated ID set",
        )
        self.assertRegex(
            classifier,
            r"(?s)animated geometry cap exceeded:.*?exceeds 30%",
            "a transition-positioning window above the animation cap must be "
            "rejected by the measured classifier",
        )
        self.assertRegex(
            support,
            r"(?s)catch \{.*?\$lastRejectedCandidate = "
            r"\$classificationError.*?continue.*?last_rejected_candidate",
            "a rejected candidate must be remeasured until a compliant window "
            "or the bounded STOP reports the classifier finding",
        )
        self.assertIn(
            "table.sort(structural_elements",
            support,
            "settlement structure must canonicalize instance-arbitrary list order",
        )
        self.assertIn(
            "return tostring(left.id or '') < tostring(right.id or '')",
            support,
            "canonical structure must break equal draw-order ties by native id",
        )
        self.assertRegex(
            support,
            r"(?s)function Test-NativeMenuFrameMatchesSettlement.*?"
            r"SemanticSurface.*?SemanticGeneration.*?"
            r"SemanticPayload\.generation.*?Settlement\.Layout\.generation",
            "post-window frames must remain on the exact measured semantic "
            "surface and both generations while ambient geometry keeps moving",
        )
        self.assertIn(
            "Get-SettledNativeMenuObservation",
            standalone,
            "standalone fixtures must be produced by the settlement gate",
        )
        self.assertIn(
            '"$fixtureBasename.settlement.json"',
            standalone,
            "same-screen settings variants must not overwrite raw traces",
        )
        self.assertRegex(
            transition,
            r"(?s)\$before\s*=\s*Get-SettledNativeMenuObservation.*"
            r"\$after\s*=\s*Get-SettledNativeMenuObservation",
            "transition source and destination must both use the settlement gate",
        )
        self.assertRegex(
            support,
            r"(?s)\$lastStatus -ceq \"dispatching\".*?"
            r"\$ExpectedDestinationSurface.*?"
            r"\$dispatch\.semantic_surface -ceq.*?"
            r"\$ExpectedDestinationSurface",
            "a blocking native modal may proceed only after its exact caller-pinned "
            "destination surface is measured live",
        )
        self.assertIn(
            "-ExpectedDestinationSurface $ExpectedDestinationSurface",
            transition,
            "the transition recorder must bind modal dispatch to the pinned "
            "destination surface",
        )
        self.assertNotIn(
            "WaitMilliseconds",
            transition,
            "transition capture must not expose a fixed-delay parameter",
        )
        self.assertNotIn(
            "Start-Sleep",
            transition,
            "transition capture must not sleep before sampling a destination",
        )
        self.assertIn(
            "Get-SettledNativeMenuObservation",
            confirmation,
            "fresh-instance animation confirmation must use Settlement v2",
        )
        self.assertIn(
            '"$confirmationBasename.bmp"',
            confirmation,
            "same-screen settings confirmations must not overwrite frames",
        )
        self.assertIn(
            "primary.header.process_id -eq $ProcessId",
            confirmation,
            "animation confirmation must reject process reuse",
        )
        self.assertIn(
            "$rawSetsMatchNoncontractual = $primaryIdsJson -ceq $confirmationIdsJson",
            confirmation,
            "raw-set disagreement must reach screen-level motion resolution",
        )
        self.assertNotIn(
            "animated ID confirmation mismatch",
            confirmation,
            "a stationary window must not veto a measured moving window",
        )
        for token in (
            "NativeMenuExtendedMinimumMilliseconds = 60000",
            "NativeMenuExtendedSpanMultiplier = 10",
            "NativeMenuExtendedMinimumSamples = 200",
        ):
            self.assertIn(token, support)
        self.assertIn(
            "$stableSpanMilliseconds = [long]$baselineSettlement.stable_span_milliseconds",
            motion,
            "extended duration must be derived from the exact stationary window",
        )
        self.assertIn(
            "$samples.Count -lt $script:NativeMenuExtendedMinimumSamples",
            motion,
            "extended observation must reach at least 200 runnable samples",
        )
        self.assertIn(
            "motion_events = @($classification.motion_events)",
            motion,
            "the recorder must retain the exact motion-event census",
        )
        self.assertIn(
            "resolve_ambient_lifecycle(",
            resolver,
            "campaign promotion must resolve one classification per screen member",
        )
        for recorder in (
            standalone,
            transition,
            confirmation,
            motion,
            importer_launcher,
            importer,
        ):
            self.assertNotIn(
                "CaptureCommit",
                recorder,
                "operators must not be able to supply capture commit provenance",
            )
        self.assertIn(
            'git_text(repo_root, "rev-parse", "HEAD")',
            importer,
            "special capture provenance must derive HEAD from its own repo",
        )
        self.assertIn(
            "loader_hash = sha256_file(loader)",
            importer,
            "special capture provenance must hash the launcher-side loader",
        )
        self.assertIn(
            "base_commit_sha = $baseCommitSha",
            support,
            "fixture provenance must carry the recorder-derived base commit",
        )
        self.assertIn(
            "Get-FileHash -LiteralPath $injectedLoader",
            support,
            "fixture provenance must hash the exact launcher-injected loader DLL",
        )

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
