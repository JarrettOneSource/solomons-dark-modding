"""Contracts for the opt-in, live native-menu layout recorder."""

from __future__ import annotations

import re
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

    def test_settings_family_replays_only_machine_measured_cached_panel_art(self) -> None:
        builders = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "overlay_surface_builders_settings_surfaces.inl"
        )
        helpers = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "overlay_surface_builders_settings_helpers.inl"
        )
        frame = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "label_resolution_surface_registry_and_frame_render.inl"
        )
        binary_layout = read("config/binary-layout.ini")
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
            r"(?s)HasCurrentSettingsPanelArt.*?"
            r'"ControlPanel\.0".*?"ControlPanel\.8".*?"ControlPanel\.18".*?'
            r"TryExtractSettingsFamilyOverlayArt.*?"
            r"if \(overlay_elements == nullptr \|\|\s*"
            r"!HasCurrentSettingsPanelArt\(current_elements\)\) \{\s*"
            r"return false;\s*\}.*?"
            r"overlay_first_draw_order.*?"
            r"element\.art_id\.rfind\(\"Title\.\", 0\)",
            "Settings cached art must originate in one complete live panel "
            "suffix and must exclude title-backdrop draws",
        )
        self.assertRegex(
            builders,
            r"(?s)SettingsFamilyOverlayArtCacheState.*?"
            r"settings_underlay.*?"
            r"GetCapturedMenuArtSemanticKey.*?"
            r"TryExtractControlsPageArtDifference.*?"
            r"underlay_counts.*?"
            r"element\.art_id\.rfind\(\"Title\.\", 0\) == 0\).*?"
            r"continue;.*?"
            r"element\.art_id\.rfind\(\"ControlPanel\.\", 0\).*?"
            r"controls_elements->clear\(\);.*?return false;",
            "Controls cached art must be the semantic multiset difference from "
            "the measured Settings underlay and exclude title/Settings draws",
        )
        semantic_key = re.search(
            r"(?s)std::string GetCapturedMenuArtSemanticKey\(.*?"
            r"return key\.str\(\);\s*\}",
            builders,
        )
        self.assertIsNotNone(
            semantic_key,
            "the Controls underlay subtraction must define one semantic key",
        )
        self.assertNotIn(
            "draw_order",
            semantic_key.group(0),
            "absolute draw order must not prevent stable underlay subtraction",
        )
        self.assertRegex(
            builders,
            r"(?s)ResolveSettingsFamilyMenuArtElements.*?"
            r"cache\.settings_address != settings_address.*?"
            r"element\.draw_order = next_draw_order\+\+.*?"
            r"TryResolveSettingsRolloutPageState.*?"
            r"TryExtractControlsPageArtDifference.*?"
            r"replay_cached_overlay\(\*last_cache, settings_address\).*?"
            r"cache_state\.last_page != page_observation\.page.*?"
            r"active_cache->settings_address = settings_address;.*?"
            r"replay_cached_overlay\(\*active_cache, settings_address\)",
            "Settings-family caches must remain owner/page scoped, replay the "
            "known source through a native page transition, and adopt only the "
            "measured destination page",
        )
        self.assertRegex(
            builders,
            r"(?s)if \(cache_state\.last_page != page_observation\.page &&\s*"
            r"cache_state\.transition\.settings_address == settings_address &&\s*"
            r"!cache_state\.transition\.elements\.empty\(\)\) \{\s*"
            r"active_cache->settings_address = settings_address;\s*"
            r"active_cache->elements =\s*"
            r"std::move\(cache_state\.transition\.elements\);",
            "Settings-family cached page art must be adopted only when the "
            "machine-measured destination differs from the known source page",
        )
        self.assertRegex(
            builders,
            r"(?s)auto\* active_cache =.*?"
            r"if \(page_observation\.page == "
            r"SettingsRolloutPageState::Settings &&\s*"
            r"TryExtractSettingsFamilyOverlayArt\(",
            "an outgoing Settings ControlPanel draw must never populate the "
            "Controls destination cache",
        )
        self.assertRegex(
            builders,
            r"(?s)if \(!TryResolveSettingsRolloutPageState\(.*?"
            r"TryExtractSettingsFamilyOverlayArt\(\s*"
            r"current_elements,\s*&transition_overlay\)\) \{\s*"
            r"cache_state\.settings\.settings_address = settings_address;\s*"
            r"cache_state\.settings\.elements =\s*"
            r"std::move\(transition_overlay\);\s*"
            r"cache_state\.settings_underlay = current_elements;\s*"
            r"cache_state\.transition = CachedSettingsFamilyOverlayArt\{\};\s*"
            r"\} else if \(TryExtractControlsPageArtDifference",
            "an unresolved outgoing Settings panel must remain quarantined in "
            "the Settings cache instead of becoming Controls transition art",
        )
        self.assertRegex(
            builders,
            r"(?s)if \(!TryResolveSettingsRolloutPageState\(.*?"
            r"MarkSettingsFamilyPageTransitionPending\(&cache_state\);.*?"
            r"if \(cache_state\.transition_started_at != 0 &&\s*"
            r"now - cache_state\.transition_started_at >\s*"
            r"kTrackedSettingsMaximumIdleMs\) \{\s*"
            r"Log\(\s*\"Debug UI settings-family cached page retired "
            r"after bounded unresolved transition\.\"\);\s*"
            r"clear_caches\(\);\s*"
            r"return current_elements;\s*\}.*?"
            r"replay_cached_overlay\(\*last_cache, settings_address\)",
            "an unresolved Settings-family source must expire before its cached "
            "panel can mask a settled main-menu destination indefinitely",
        )
        self.assertRegex(
            builders + frame,
            r"(?s)SettingsFamilyOverlayArtCacheState.*?"
            r"transition_started_at.*?"
            r"MarkSettingsFamilyPageTransitionPending.*?"
            r"ShouldRetainSettingsTrackingAcrossMainMenuFallback.*?"
            r"now - state\.transition_started_at <= "
            r"kTrackedSettingsMaximumIdleMs.*?"
            r"page_observation\.page == SettingsRolloutPageState::Controls &&\s*"
            r"\(active_cache->settings_address != settings_address \|\|\s*"
            r"active_cache->elements\.empty\(\)\).*?"
            r"cache_state\.last_page = page_observation\.page;.*?"
            r"cache_state\.transition_started_at = 0;.*?"
            r"retain_settings_tracking =.*?"
            r"std::strcmp\(entry\.surface_id, \"main_menu\"\) == 0 &&\s*"
            r"ShouldRetainSettingsTrackingAcrossMainMenuFallback\(\).*?"
            r"if \(entry\.clear_settings_tracking &&\s*"
            r"!retain_settings_tracking\)",
            "the main-menu underlay must not retire the Settings owner during "
            "the bounded handoff to a uniquely resolved native Controls page",
        )
        self.assertRegex(
            helpers,
            r"(?s)TryResolveSettingsRolloutPageState.*?"
            r"duplicate GAME SETTINGS roots.*?"
            r"duplicate CUSTOMIZE KEYBOARD roots.*?"
            r"IsSettingsRolloutPageAtLocalOrigin.*?"
            r"if \(settings_at_origin == controls_at_origin\).*?return false;.*?"
            r"SettingsRolloutPageState::Controls.*?"
            r"SettingsRolloutPageState::Settings",
            "Settings and Controls must be selected from one unique native rollout "
            "page at the live local origin, never from a stale render timestamp",
        )
        self.assertRegex(
            frame,
            r"ResolveSettingsFamilyMenuArtElements\(\s*"
            r"TakeCapturedMenuArtFrame\(\)\)",
            "the frame classifier must consume the owner/page-scoped Settings-family "
            "art resolver rather than raw one-shot draws",
        )
        controls_builder = re.search(
            r"(?s)TryBuildControlsOverlayRenderElements\(.*?"
            r"TryReadTrackedSettingsRender\(&settings_address\).*?"
            r"TryResolveSettingsRolloutPageState\(\s*"
            r"\*config,\s*settings_address,\s*&page_observation\).*?"
            r"controls_at_origin =\s*page_resolved &&\s*"
            r"page_observation\.page == SettingsRolloutPageState::Controls.*?;.*?"
            r"controls_transition_source =\s*!page_resolved &&\s*"
            r"cache_state\.settings_address == settings_address &&\s*"
            r"cache_state\.last_page == SettingsRolloutPageState::Controls &&\s*"
            r"ShouldRetainSettingsTrackingAcrossMainMenuFallback\(\) &&\s*"
            r"page_observation\.settings_page_control != 0 &&\s*"
            r"page_observation\.customize_page_control != 0 &&\s*"
            r"page_observation\.customize_rollout_child_control != 0;.*?"
            r"if \(!controls_at_origin && !controls_transition_source\) \{\s*"
            r"return \{\};\s*\}.*?"
            r"customize_owner_control =\s*"
            r"page_observation\.customize_page_control;.*?"
            r"TryReadSettingsDoneButtonRect.*?"
            r"back_button\.surface_id = \"controls\";.*?"
            r"back_button\.label = \"BACK\";.*?"
            r"ResolveConfiguredUiActionId\(\s*\"controls\".*?"
            r"return render_elements;\s*\}",
            builders,
        )
        self.assertIsNotNone(
            controls_builder,
            "Controls classification must require either the unique live native "
            "rollout page or its bounded machine-proven transition source, plus "
            "the machine-measured Back control",
        )
        self.assertNotIn(
            "controls.elements",
            controls_builder.group(0),
            "Controls classification must not wait for a one-shot art cache after "
            "the native Controls rollout is uniquely at the local origin",
        )
        self.assertRegex(
            binary_layout,
            r"(?s)\[surface\.controls\].*?actions=.*?controls\.back.*?"
            r"\[action\.controls\.back\]\s*"
            r"surface=controls\s*label=BACK\s*owner=0x005D9A50\s*"
            r"handler=0x005D8120\s*control_offset=0x00B8",
            "the measured native Controls Back widget must remain a configured "
            "interactive action instead of a fixture-only label",
        )

    def test_settings_modal_retains_one_shot_rows_only_for_its_live_owner(self) -> None:
        state = read("SolomonDarkModLoader/src/debug_ui_overlay.cpp")
        frame = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "overlay_surface_builders_misc_surfaces.inl"
        )
        reset = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "state_actions_activation/resolved_action_activation.inl"
        )
        snapshot = read(
            "SolomonDarkModLoader/src/debug_ui_overlay/"
            "menu_layout_capture_snapshot_and_hooks.inl"
        )
        self.assertIn("retained_settings_elements_owner", state)
        self.assertIn("retained_settings_exact_text_elements", state)
        self.assertIn("retained_settings_exact_control_elements", state)
        self.assertRegex(
            frame,
            r"(?s)MergeRetainedSettingsFrameElementsUnlocked.*?"
            r"settings_render\.tracked_object_ptr.*?"
            r"retained_settings_elements_owner != settings_owner.*?"
            r"retained_settings_exact_text_elements\.clear\(\).*?"
            r"retained_settings_exact_control_elements\.clear\(\).*?"
            r"source\.surface_id != \"settings\".*?continue;.*?"
            r"TakeExactTextFrameElements.*?"
            r"MergeRetainedSettingsFrameElementsUnlocked\(.*?"
            r"retained_settings_exact_text_elements",
            "one-shot settings rows must be replayed only while the same live "
            "settings owner remains selected",
        )
        self.assertRegex(
            reset,
            r"(?s)RetireUiCaptureBeforeActionDispatch.*?"
            r"retained_settings_elements_owner = 0.*?"
            r"retained_settings_exact_text_elements\.clear\(\).*?"
            r"retained_settings_exact_control_elements\.clear\(\)",
            "semantic action retirement must invalidate retained settings rows",
        )
        self.assertRegex(
            snapshot,
            r"(?s)semantic_root.*?GetOverlaySurfaceRootId.*?"
            r"exact_text_elements.*?source_root.*?"
            r"source_root != semantic_root.*?continue;",
            "a selected surface must not inherit hidden exact text from a foreign surface",
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
        self.assertIn('has_action_prefix("pause_menu.")', source)
        self.assertIn('return "pause_menu"', source)
        self.assertIn('has_action_prefix("profile.")', source)
        self.assertIn('return "dark_cloud_menu"', source)
        self.assertIn("ContainsObservedText(exact_text_elements, expected)", source)
        self.assertIn("LowerAsciiCopy(element.label).find(", source)
        self.assertIn('contains_text("beta version v.0.72")', source)
        self.assertIn('has_action("main_menu.resume_last_game")', source)
        self.assertIn('return "profile_save_select"', source)
        for art_id, screen_id in (
            ("GameOver.0", "game_over"),
            ("ControlPanel.9", "performance"),
            ("ControlPanel.0", "settings"),
            ("UI.51", "skill_picker"),
            ("LevelPicker.3", "map_picker"),
            ("Skills.43", "hub"),
        ):
            self.assertIn(f'has_art("{art_id}")', source)
            self.assertIn(f'return "{screen_id}"', source)
        self.assertIn('visible_art_count("UI.17") >= 4', source)
        self.assertIn('return "dark_cloud_settings"', source)
        self.assertIn("ContainsObservedTextAbove", source)
        self.assertIn('"hall of fame",', source)
        self.assertIn("100.0f", source)

    def test_settings_rows_are_captured_from_live_immediate_mode_draws(self) -> None:
        source = read_menu_layout_capture()
        for token in (
            "kSettingsScalarRowAddress",
            "kSettingsToggleRowAddress",
            "kSettingsActionRowAddress",
            "BeginSettingsRowCapture",
            "ObserveActiveSettingsRowBounds",
            "HookSettingsScalarRow",
            "HookSettingsToggleRow",
            "HookSettingsActionRow",
            "settings_action_row_hook",
        ):
            self.assertIn(token, source)

        state = read("SolomonDarkModLoader/src/debug_ui_overlay.cpp")
        self.assertIn("SettingsActionRowFn", state)
        self.assertIn("settings_action_row_hook", state)
        self.assertRegex(
            source,
            r"(?s)HookSettingsActionRow\(.*?"
            r"BeginSettingsRowCapture\(.*?primary_label.*?"
            r"GetX86HookTrampoline<SettingsActionRowFn>.*?"
            r"original\(\s*self,\s*primary_label,\s*secondary_label,\s*"
            r"action_context\).*?"
            r"CacheObservedObjectLabel\(\s*"
            r"reinterpret_cast<uintptr_t>\(result\),\s*primary_label_text\).*?"
            r"EndSettingsRowCapture\(\).*?return result;",
            "two-label settings action rows must retain their machine-read label on "
            "the durable native control returned by the exact helper",
        )

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
            r"\$captureDestinationScreen.*?"
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
            r'(?s)if \(\$probe\.Status -in '
            r'@\("wrong_surface", "wrong_tab"\)\) \{.*?'
            r'Test-NativeMenuScreenTagsEquivalent.*?'
            r'-Left \$measuredSurface.*?'
            r'-Right \$TransitionalSourceScreen.*?'
            r'\$probeKey = \(.*?\$probe\.Status.*?\$measuredSurface.*?'
            r'\$probe\.NativeGeneration.*?'
            r'\$probeKey -cne \$foreignSurfaceProbeKey.*?'
            r'if \(\s*\$consecutiveForeignSurfaceProbes -ge\s*'
            r'\$script:NativeMenuSettleConsecutiveSamples.*?'
            r'\$script:NativeMenuSettleMinimumSpanMilliseconds.*?'
            r'throw \[string\]\$probe\.Detail',
            "a transient population classifier may be retried, but any one "
            "foreign surface that itself meets the 40-sample/two-second "
            "settlement floor must abort with the measured mismatch",
        )
        self.assertRegex(
            support,
            r'(?s)function Resolve-NativeMenuBrowserTabState.*?'
            r'dark_cloud_browser\.recent.*?'
            r'dark_cloud_browser\.online_levels.*?'
            r'dark_cloud_browser\.my_levels.*?'
            r'UI\.13.*?'
            r'\$memberIds\.Count -ne 6.*?'
            r'\$distinctTops\.Count -ne 2.*?'
            r'function Assert-NativeMenuBrowserTabAgreement.*?'
            r'native-menu browser tab agreement rejected',
            "browser layouts must be selected by the six measured bracket "
            "members and reject a wrong operator tab",
        )
        self.assertRegex(
            support,
            r'(?s)function Resolve-NativeMenuHubPathLayoutId.*?'
            r'LevelPicker\.0.*?LevelPicker\.2.*?LevelPicker\.4.*?'
            r'LevelPicker\.5.*?LevelPicker\.6.*?UI\.28.*?'
            r'hub_pristine_second_new_game.*?15.*?'
            r'hub_new_game.*?14.*?hub_resumed.*?10.*?'
            r'Hub path classifier measured no exact authorized v2\.13.*?'
            r'if \(\$elements\.Count -ne \$requiredElementCount\).*?'
            r'Hub path classifier measured.*?exact authorized.*?census',
            "path-qualified Hub capture must machine-classify the exact "
            "authorized member signature and census before retagging",
        )
        self.assertRegex(
            support,
            r'(?s)\$captureSurfaceId -ceq "hub".*?'
            r'Resolve-NativeMenuHubPathLayoutId.*?'
            r'\$measuredHubLayout -cne \$ScreenId.*?'
            r'Hub path selector expected.*?machine-classified.*?'
            r'\$semanticPayload\.screen_id = \$ScreenId',
            "the Hub parent screen must be retagged only after its measured "
            "path layout equals the requested qualifier",
        )
        self.assertIn(
            "-TransitionalSourceScreen $SourceScreen",
            transition,
            "destination settlement must distinguish its known source surface "
            "from an unrelated classifier/tag substitution",
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
        self.assertRegex(
            helper,
            r"(?s)keybd_event\(.*?0x12,.*?0,.*?0,.*?"
            r"keybd_event\(.*?0x12,.*?0,.*?0x0002,.*?"
            r"SetForegroundWindow\(\$window\).*?"
            r"\$foregroundProcessId -ne \$ProcessId.*?throw",
            "the exact-process click helper must release the Windows "
            "foreground lock and still prove target ownership before input",
        )


if __name__ == "__main__":
    unittest.main()
