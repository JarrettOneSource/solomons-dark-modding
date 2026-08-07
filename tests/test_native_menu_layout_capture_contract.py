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
        self.assertIn(
            "g_native_boot_capture_samples.back().progress >= 1.0",
            source,
            "native-loader capture must settle-gate the real full-progress frame",
        )
        self.assertIn(
            "while (!g_native_boot_capture_settled",
            source,
            "native-loader capture must not fall back to one fixed-delay frame",
        )

    def test_loading_capture_rejects_offscreen_render_targets(self) -> None:
        source = read(
            "SolomonDarkModLoader/src/loading_screen_native_present.cpp"
        )
        self.assertIn(
            "IsProcessClientPresentationViewport(*layout)",
            source,
            "loading settlement must exclude offscreen viewport samples",
        )
        self.assertRegex(
            source,
            r"if \(!IsProcessClientPresentationViewport\(\*layout\)\) \{\s*"
            r"return;\s*\}\s*CaptureLoadingScreenEvidenceFrameInternal",
            "offscreen loading frames must be rejected before settlement state changes",
        )
        self.assertRegex(
            source,
            r"(?s)snapshot\.stage\s*==\s*"
            r"LoadingScreenStage::WaitingForParticipants.*?"
            r"while \(!g_loading_capture_settled.*?"
            r"CaptureLoadingScreenEvidenceFrameInternal\(\s*"
            r"snapshot,\s*\*layout\)",
            "the real final loading barrier must remain presented until settled",
        )

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

    def test_current_frame_capture_refuses_classifier_tag_disagreement(self) -> None:
        api = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "public_api_surface_dispatch.inl"
        )
        bindings = read("SolomonDarkModLoader/src/lua_engine_bindings_ui.cpp")
        recorder = read_native_menu_recorder()
        self.assertIn("TryCaptureCurrentDebugUiLayoutSnapshot", api)
        self.assertRegex(
            api,
            r"captured\.screen_id != screen_id\) \{\s*return false;\s*\}",
            "a classifier/tag mismatch must be refused before any snapshot is stored",
        )
        self.assertNotIn("classification_agrees", api)
        self.assertNotIn("stale controls omitted", api)
        self.assertNotIn("captured.screen_id = std::string(screen_id)", api)
        self.assertIn("TryGetLatestDebugUiLayoutSnapshot", bindings)
        self.assertIn('lua_setfield(state, -2, "classified_screen_id")', bindings)
        self.assertIn("capture_current_layout", bindings)
        self.assertIn("sd.ui.capture_current_layout", recorder)

    def test_settings_modal_uses_current_frame_evidence_to_retain_its_owner(self) -> None:
        builders = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "overlay_surface_builders_settings_surfaces.inl"
        )
        tracking = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "tracked_surfaces_and_main_menu.inl"
        )
        self.assertIn("bool TryReadTrackedSettingsRender(", tracking)
        self.assertNotRegex(
            tracking,
            r"(?s)now - g_debug_ui_overlay_state\.settings_render\.captured_at > "
            r"kTrackedSettingsMaximumIdleMs\) \{\s*"
            r"g_debug_ui_overlay_state\.settings_render\.tracked_object_ptr = 0",
            "the idle probe must not erase the owner before current-frame settings "
            "evidence can validate it later in the same frame",
        )
        self.assertRegex(
            builders,
            r"(?s)has_settings_exact_evidence.*?"
            r"if \(has_settings_exact_evidence\).*?"
            r"TryReadTrackedSettingsRender\(&settings_address\).*?"
            r"else if \(!TryGetActiveSettingsRender\(&settings_address\)\)",
            "current-frame settings text must bridge the stock modal's one-shot "
            "render helper without turning the retained owner into timeless evidence",
        )
        self.assertRegex(
            builders,
            r"(?s)has_customize_keyboard_exact_evidence.*?"
            r"TryReadTrackedSettingsRender\(&settings_address\).*?"
            r"TryIsCustomizeKeyboardRolloutExpanded",
            "controls classification must require current-frame Customize Keyboard "
            "evidence and the live expanded rollout on the retained settings owner",
        )

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
            r"\$dispatch\.classified_surface -ceq.*?"
            r"\$ExpectedDestinationScreen.*?"
            r"\$dispatch\.layout_generation -ne.*?"
            r"\$SourceLayoutGeneration",
            "a blocking native modal may proceed only after its exact caller-pinned "
            "destination classification and a layout-generation advance are measured live",
        )
        self.assertIn(
            "-SourceLayoutGeneration $before.layout_generation",
            transition,
            "the modal proof must compare against the exact settled source "
            "layout generation",
        )
        self.assertIn(
            "-ExpectedDestinationScreen $DestinationScreen",
            transition,
            "the transition recorder must bind modal dispatch to the intended "
            "machine classification",
        )
        self.assertNotIn(
            "ExpectedSourceSurface",
            transition,
            "source agreement must be mandatory rather than operator-optional",
        )
        self.assertNotIn(
            "ExpectedDestinationSurface",
            transition,
            "destination agreement must be mandatory rather than operator-optional",
        )
        for script, consequence in (
            (standalone, "standalone"),
            (transition, "transition"),
            (confirmation, "confirmation"),
            (motion, "extended observation"),
        ):
            self.assertIn(
                "Assert-NativeMenuCaptureSurfaceAgreement",
                script,
                f"{consequence} capture must refuse a classifier/tag mismatch",
            )
        self.assertIn(
            'ParameterSetName = "MeasuredClick"',
            transition,
            "the corrected navigation path must derive its click from a live control",
        )
        self.assertRegex(
            support,
            r'if \(\$probe\.Status -eq "wrong_surface"\) \{\s*'
            r'throw \[string\]\$probe\.Detail',
            "a post-transition classifier mismatch must abort on its first probe "
            "instead of aging into the settlement timeout",
        )
        self.assertIn(
            "dispatch_measurement = $dispatchMeasurement",
            transition,
            "a live-derived click must carry its measured rectangle receipt",
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
            "NativeMenuExtendedPerSampleBudgetMilliseconds = 1000",
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
            "$observedSpanMilliseconds -lt $requiredSpanMilliseconds",
            motion,
            "extended observation duration must be measured between actual "
            "samples rather than from wall-clock startup",
        )
        self.assertIn(
            "$sampleCensusDeadlineMilliseconds",
            motion,
            "the extended timeout must budget for the independent 200-sample "
            "census as well as the elapsed-span floor",
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
