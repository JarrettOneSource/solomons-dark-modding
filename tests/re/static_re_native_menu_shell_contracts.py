"""Static contracts for the G11 native boot/menu shell reconstruction."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    assert_module_runs_in_ci,
    assert_recorded_hash_matches_file,
)
from native_menu_settlement_v2 import (
    MAXIMUM_ANIMATED_FRACTION,
    MINIMUM_SAMPLES,
    MINIMUM_SPAN_MILLISECONDS,
    OVERLAY_REFERENCE_SCHEMA,
    SettlementV2Error,
    assert_overlay_hygiene,
    build_overlay_contamination_override,
    canonical_bytes,
    deterministic_reordinalized_layout,
    structural_layout_bytes,
    validate_overlay_reference,
)


LAYOUT_IDS = (
    "beta-notice",
    "controls",
    "control-scheme-picker",
    "create-discipline",
    "create-element",
    "dark-cloud-browser",
    "dark-cloud-login-settings",
    "dark-cloud-menu",
    "dark-cloud-my-levels",
    "dark-cloud-online-levels",
    "dark-cloud-options",
    "dark-cloud-recent",
    "dark-cloud-search",
    "dark-cloud-settings",
    "dark-cloud-sort",
    "game-over",
    "game-settings-dark-cloud",
    "game-settings-gameplay",
    "game-settings-title",
    "hall-of-fame",
    "loading-screen",
    "main-menu-root",
    "map-picker",
    "native-loader",
    "pause-menu",
    "performance",
    "profile-save-select",
    "skill-picker",
)

EDGE_CONTRACT = {
    "control_scheme_picker_to_create": (
        "control_scheme_picker",
        "control_scheme_picker.select_wasd",
        "create_element",
    ),
    "create_element_to_discipline": (
        "create_element",
        "create.select_element_fire",
        "create_discipline",
    ),
    "create_discipline_to_hub": (
        "create_discipline",
        "create.select_discipline_mind",
        "hub",
    ),
    "hub_to_pause": ("hub", "menu_key", "pause_menu"),
    "pause_to_hub_resume": (
        "pause_menu",
        "pause_menu.resume_game",
        "hub",
    ),
    "pause_to_game_settings": (
        "pause_menu",
        "pause_menu.game_settings",
        "settings",
    ),
    "settings_to_controls": (
        "settings",
        "customize_keyboard_click",
        "controls",
    ),
    "controls_to_settings": (
        "controls",
        "back_button_click",
        "settings",
    ),
    "settings_to_performance": (
        "settings",
        "tweak_game_click",
        "performance",
    ),
    "performance_to_settings": (
        "performance",
        "back_button_click",
        "settings",
    ),
    "settings_to_dark_cloud_settings": (
        "settings",
        "login_info_modify_click",
        "dark_cloud_settings",
    ),
    "dark_cloud_settings_to_settings": (
        "dark_cloud_settings",
        "back_button_click",
        "settings",
    ),
    "settings_to_hub": ("settings", "done_button_click", "hub"),
    "pause_to_beta_notice": (
        "pause_menu",
        "pause_menu.leave_game",
        "beta_notice",
    ),
    "beta_notice_to_main": (
        "beta_notice",
        "dialog.primary",
        "main_menu",
    ),
    "main_to_profile_select": (
        "main_menu",
        "main_menu.play",
        "profile_save_select",
    ),
    "profile_select_to_main": (
        "profile_save_select",
        "main_menu.back",
        "main_menu",
    ),
    "main_to_settings": (
        "main_menu",
        "main_menu.settings",
        "settings",
    ),
    "settings_to_main": ("settings", "done_button_click", "main_menu"),
    "main_to_hall_of_fame": (
        "main_menu",
        "main_menu.hall_of_fame",
        "hall_of_fame",
    ),
    "hall_of_fame_to_beta_notice": (
        "hall_of_fame",
        "main_menu_button_click",
        "beta_notice",
    ),
    "main_to_dark_cloud": (
        "main_menu",
        "main_menu.explore_dark_cloud",
        "dark_cloud_browser",
    ),
    "dark_cloud_to_recent": (
        "dark_cloud_browser",
        "dark_cloud_browser.recent",
        "dark_cloud_recent",
    ),
    "dark_cloud_recent_to_online": (
        "dark_cloud_recent",
        "dark_cloud_browser.online_levels",
        "dark_cloud_online_levels",
    ),
    "dark_cloud_online_to_my_levels": (
        "dark_cloud_online_levels",
        "dark_cloud_browser.my_levels",
        "dark_cloud_my_levels",
    ),
    "dark_cloud_to_search": (
        "dark_cloud_my_levels",
        "dark_cloud_browser.search",
        "dark_cloud_search",
    ),
    "dark_cloud_search_to_browser": (
        "dark_cloud_search",
        "menu_key",
        "dark_cloud_my_levels",
    ),
    "dark_cloud_to_sort": (
        "dark_cloud_my_levels",
        "dark_cloud_browser.sort",
        "dark_cloud_sort",
    ),
    "dark_cloud_sort_to_browser": (
        "dark_cloud_sort",
        "menu_key",
        "dark_cloud_my_levels",
    ),
    "dark_cloud_to_options": (
        "dark_cloud_my_levels",
        "dark_cloud_browser.options",
        "dark_cloud_options",
    ),
    "dark_cloud_options_to_browser": (
        "dark_cloud_options",
        "menu_key",
        "dark_cloud_my_levels",
    ),
    "dark_cloud_to_login_settings": (
        "dark_cloud_my_levels",
        "dark_cloud_browser.login",
        "dark_cloud_settings",
    ),
    "dark_cloud_login_to_browser": (
        "dark_cloud_login_settings",
        "done_button_click",
        "dark_cloud_my_levels",
    ),
    "dark_cloud_to_menu": (
        "dark_cloud_my_levels",
        "dark_cloud_browser.menu",
        "dark_cloud_menu",
    ),
    "dark_cloud_menu_resume": (
        "dark_cloud_menu",
        "profile.resume",
        "dark_cloud_my_levels",
    ),
    "dark_cloud_menu_to_settings": (
        "dark_cloud_menu",
        "profile.game_settings",
        "settings",
    ),
    "dark_cloud_settings_done": (
        "settings",
        "done_button_click",
        "dark_cloud_my_levels",
    ),
    "dark_cloud_menu_to_beta_notice": (
        "dark_cloud_menu",
        "profile.main_menu",
        "beta_notice",
    ),
    "profile_select_resume_to_hub": (
        "profile_save_select",
        "main_menu.resume_last_game",
        "hub",
    ),
}

# The capture_method the loader writes when its own screen classifier AGREED with
# the label the operator passed to `sd.ui.capture_current_layout`, and the one it
# writes when it did NOT.
ENDPOINT_CAPTURE_AGREED = (
    "live native UI tree + exact text/font hooks + native Sprite draw hooks"
)
ENDPOINT_CAPTURE_DISAGREED = (
    ENDPOINT_CAPTURE_AGREED
    + " + exact live-navigation screen tag (stale controls omitted)"
)

# Every field the navigation recorder writes on each edge endpoint, pinned:
# (semantic_surface, semantic_generation, layout_generation, element_count,
#  game_disagreed).  Before this table only `screen`/`trigger`/`destination` and
# the two frame hashes were gated, so a re-recording could have scrambled all
# five of these on all 78 endpoints without tripping anything.
#
# `game_disagreed` is the load-bearing one.  It is NOT decoration: when the
# loader's classifier disagrees with the operator's label it DELETES every
# element that is not `art` or `text` before returning the snapshot (see
# TryCaptureCurrentDebugUiLayoutSnapshot in
# SolomonDarkModLoader/src/debug_ui_overlay/public_api_surface_dispatch.inl).
# So a disagreeing endpoint's `element_count` is a stripped remnant, not a
# census of that screen, and must never be read as one.
ENDPOINT_CONTRACT = {
    "beta_notice_to_main": (
        ("dialog", 13, 13, 112, False),
        ("main_menu", 14, 14, 115, False),
    ),
    "control_scheme_picker_to_create": (
        ("control_scheme_picker", 2, 2, 5, False),
        ("create", 4, 4, 34, False),
    ),
    "controls_to_settings": (
        ("", 0, 8, 31, True),
        ("", 0, 8, 37, True),
    ),
    "create_discipline_to_hub": (
        ("create", 4, 4, 45, False),
        ("", 0, 5, 25, True),
    ),
    "create_element_to_discipline": (
        ("create", 3, 3, 45, False),
        ("create", 4, 4, 98, False),
    ),
    "dark_cloud_login_to_browser": (
        ("dark_cloud_browser", 3386, 3386, 95, True),
        ("dark_cloud_browser", 3386, 3386, 94, False),
    ),
    "dark_cloud_menu_resume": (
        ("simple_menu", 3387, 3387, 101, True),
        ("dark_cloud_browser", 3388, 3388, 94, False),
    ),
    "dark_cloud_menu_to_beta_notice": (
        ("simple_menu", 3393, 3393, 100, True),
        ("dialog", 3396, 3396, 123, False),
    ),
    "dark_cloud_menu_to_settings": (
        ("simple_menu", 3389, 3389, 100, True),
        ("dark_cloud_browser", 3392, 3392, 86, True),
    ),
    "dark_cloud_online_to_my_levels": (
        ("dark_cloud_browser", 36, 36, 98, False),
        ("dark_cloud_browser", 37, 37, 94, False),
    ),
    "dark_cloud_options_to_browser": (
        ("dark_cloud_browser", 3385, 3385, 104, False),
        ("dark_cloud_browser", 3385, 3385, 94, False),
    ),
    "dark_cloud_recent_to_online": (
        ("dark_cloud_browser", 35, 35, 98, False),
        ("dark_cloud_browser", 36, 36, 98, False),
    ),
    "dark_cloud_search_to_browser": (
        ("quick_panel", 3345, 3345, 96, True),
        ("dark_cloud_browser", 3383, 3383, 94, False),
    ),
    "dark_cloud_settings_done": (
        ("dark_cloud_browser", 3392, 3392, 86, True),
        ("dark_cloud_browser", 3392, 3392, 94, False),
    ),
    "dark_cloud_settings_to_settings": (
        ("", 0, 8, 31, True),
        ("", 0, 8, 37, True),
    ),
    "dark_cloud_sort_to_browser": (
        ("dark_cloud_browser", 3384, 3384, 104, False),
        ("dark_cloud_browser", 3384, 3384, 94, False),
    ),
    "dark_cloud_to_login_settings": (
        ("dark_cloud_browser", 3385, 3385, 94, False),
        ("dark_cloud_browser", 3386, 3386, 95, True),
    ),
    "dark_cloud_to_menu": (
        ("dark_cloud_browser", 3386, 3386, 94, False),
        ("simple_menu", 3387, 3387, 101, True),
    ),
    "dark_cloud_to_options": (
        ("dark_cloud_browser", 3384, 3384, 94, False),
        ("dark_cloud_browser", 3385, 3385, 104, False),
    ),
    "dark_cloud_to_recent": (
        ("dark_cloud_browser", 34, 34, 98, False),
        ("dark_cloud_browser", 35, 35, 98, False),
    ),
    "dark_cloud_to_search": (
        ("dark_cloud_browser", 37, 37, 94, False),
        ("quick_panel", 147, 147, 95, True),
    ),
    "dark_cloud_to_sort": (
        ("dark_cloud_browser", 3383, 3383, 94, False),
        ("dark_cloud_browser", 3384, 3384, 104, False),
    ),
    "hall_of_fame_to_beta_notice": (
        ("", 0, 24, 51, True),
        ("dialog", 26, 26, 124, True),
    ),
    "hub_to_pause": (
        ("", 0, 6, 25, True),
        ("simple_menu", 7, 7, 46, False),
    ),
    "main_to_dark_cloud": (
        ("main_menu", 32, 32, 126, False),
        ("dark_cloud_browser", 34, 34, 99, False),
    ),
    "main_to_hall_of_fame": (
        ("main_menu", 27, 27, 128, False),
        ("main_menu", 29, 29, 51, True),
    ),
    "main_to_profile_select": (
        ("main_menu", 14, 14, 115, False),
        ("main_menu", 15, 15, 113, False),
    ),
    "main_to_settings": (
        ("main_menu", 20, 20, 128, False),
        ("main_menu", 22, 22, 123, True),
    ),
    "pause_to_beta_notice": (
        ("simple_menu", 11, 11, 46, False),
        ("dialog", 13, 13, 115, False),
    ),
    "pause_to_game_settings": (
        ("simple_menu", 7, 7, 46, False),
        ("settings", 8, 8, 37, True),
    ),
    "pause_to_hub_resume": (
        ("simple_menu", 6, 6, 46, False),
        ("", 0, 6, 25, True),
    ),
    "performance_to_settings": (
        ("", 0, 8, 39, True),
        ("", 0, 8, 37, True),
    ),
    "profile_select_resume_to_hub": (
        ("main_menu", 3398, 3398, 123, False),
        ("", 0, 3400, 38, True),
    ),
    "profile_select_to_main": (
        ("main_menu", 15, 15, 114, False),
        ("main_menu", 16, 16, 115, False),
    ),
    "settings_to_controls": (
        ("", 0, 8, 22, True),
        ("", 0, 8, 16, True),
    ),
    "settings_to_dark_cloud_settings": (
        ("", 0, 8, 37, True),
        ("", 0, 8, 31, True),
    ),
    "settings_to_hub": (
        ("", 0, 10, 37, True),
        ("", 0, 10, 25, True),
    ),
    "settings_to_main": (
        ("main_menu", 20, 20, 124, True),
        ("main_menu", 20, 20, 124, False),
    ),
    "settings_to_performance": (
        ("", 0, 8, 37, True),
        ("", 0, 8, 39, True),
    ),
}

# `tagged_screen` is NOT an observation.  `capture_current_layout(screen_id)`
# ends with `captured.screen_id = std::string(screen_id)`, so the field always
# echoes the string the operator typed; the game's own classification survives
# only as the agreed/disagreed distinction above.  It is therefore pinned
# against the edge's own `screen`/`destination` rather than trusted -- with the
# two endpoints where the recorded label and the documented destination
# genuinely differ declared here, so neither can drift silently and neither can
# be "tidied" away.  Both are already called out in the G11 document.
ENDPOINT_TAG_EXCEPTIONS = {
    # The game classified this landing `dialog`, which both `beta_notice` and
    # `leave_game_confirmation` alias to, so the classifier cannot tell the two
    # dialogs apart; the destination name comes from reading the frame.
    ("pause_to_beta_notice", "after"): "leave_game_confirmation",
    # Captured under the label `main_menu` on a state the game classified
    # `dialog`.  The labels disagree, so this endpoint lost its controls -- its
    # 124 elements are an art/text remnant of a dialog, NOT a main-menu census.
    ("hall_of_fame_to_beta_notice", "after"): "main_menu",
}


TAB_LABELS = frozenset({"recent", "online levels", "my levels", "multiplayer"})

# The Dark Cloud tab strip's hit band, and each tab's horizontal span within it.
TAB_BAND = (128.0, 197.0)
TAB_SPAN = {
    "recent": (460.0, 630.0),
    "online levels": (630.0, 970.0),
    "my levels": (970.0, 1140.0),
    "multiplayer": (1140.0, 1342.0),
}

# Where each tab label sits when its tab is not selected.  Selected, it sits
# TAB_RAISE px higher -- see the selection block in the census test.
TAB_RESTING_TOP = {
    "recent": 166.0,
    "online levels": 163.0,
    "my levels": 166.0,
    "multiplayer": 165.0,
}
TAB_RAISE = 8.0

# The `UI.13` bracket pair framing each tab.  x never changes; the vertical
# extent is the second half of the selection signal.
BRACKET_X = frozenset({460.0, 596.0, 630.0, 936.0, 970.0, 1106.0, 1140.0, 1308.0})
BRACKET_RESTING = (136.0, 187.0)
BRACKET_SELECTED = (128.0, 193.0)

# Which tab each captured browser state has selected.  The entry browser is the
# Online Levels tab.  Multiplayer is not in this table because it is not a tab:
# it carries no control element on any screen and its brackets are drawn in the
# selected form in every state (see MULTIPLAYER_IS_INERT below).
TAB_SELECTION = {
    "dark-cloud-browser": "online levels",
    "dark-cloud-online-levels": "online levels",
    "dark-cloud-recent": "recent",
    "dark-cloud-my-levels": "my levels",
}
MULTIPLAYER_IS_INERT = "multiplayer"


def _strip_screen_prefix(
    elements: list[dict[str, object]], layout_id: str
) -> list[dict[str, object]]:
    """Elements with their screen-id prefix removed, for cross-screen equality."""
    prefix = layout_id.replace("-", "_") + "."
    stripped = []
    for element in elements:
        copy = dict(element)
        copy["id"] = str(copy["id"]).removeprefix(prefix)
        stripped.append(copy)
    return stripped


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _json(relative_path: str) -> object:
    return json.loads(_read(relative_path))


def _require_regex(source: str, pattern: str, consequence: str) -> None:
    if re.search(pattern, source, flags=re.MULTILINE | re.DOTALL) is None:
        raise StaticReTestFailure(consequence)


def _powershell_parameter_names(source: str) -> set[str]:
    preamble, separator, _ = source.partition("Set-StrictMode")
    if not separator or not preamble.lstrip().startswith("[CmdletBinding"):
        raise StaticReTestFailure(
            "native-menu recorder parameter census could not reach its "
            "CmdletBinding preamble"
        )
    return {
        match.group(1).lower()
        for match in re.finditer(
            r"^\s*\[(?:string|int|float|switch)\]\$(\w+)",
            preamble,
            flags=re.MULTILINE | re.IGNORECASE,
        )
    }


def _require(source: str, tokens: tuple[str, ...], contract: str) -> None:
    """Require each prose token, independent of how the markdown is wrapped.

    Every caller passes a documentation file. A raw substring test makes the
    contract depend on where the author's editor happened to break the line, so
    reflowing a paragraph silently breaks a passing gate and, worse, quietly
    biases authors toward short tokens that never wrap. Collapse runs of
    whitespace on both sides so the claim is about the prose, not its layout.
    """
    flattened = " ".join(source.split())
    missing = [
        token for token in tokens if " ".join(token.split()) not in flattened
    ]
    if missing:
        raise StaticReTestFailure(
            f"{contract} is incomplete: " + ", ".join(missing)
        )


def test_native_menu_recorders_settle_and_derive_provenance() -> str:
    recorder_paths = (
        "scripts/Record-NativeMenuLayout.ps1",
        "scripts/Record-NativeMenuTransition.ps1",
        "scripts/Confirm-NativeMenuLayoutAnimation.ps1",
        "scripts/Observe-NativeMenuMotionCapability.ps1",
        "scripts/Import-NativeMenuSpecialCaptures.ps1",
    )
    recorders = {path: _read(path) for path in recorder_paths}
    forbidden_parameters = {
        "capturecommit",
        "basecommitsha",
        "sourcetreesha",
        "nativeexesha256",
        "gameexecutablesha256",
        "loaderdllsha256",
        "loadercapturecommit",
        "loadingcapturecommit",
    }
    for path in recorder_paths:
        supplied = _powershell_parameter_names(recorders[path])
        overrides = sorted(supplied & forbidden_parameters)
        if overrides:
            raise StaticReTestFailure(
                "native-menu recorder accepts operator-supplied provenance "
                f"parameters in {path}: {overrides}"
            )

    layout_recorder = recorders["scripts/Record-NativeMenuLayout.ps1"]
    transition_recorder = recorders[
        "scripts/Record-NativeMenuTransition.ps1"
    ]
    confirmation_recorder = recorders[
        "scripts/Confirm-NativeMenuLayoutAnimation.ps1"
    ]
    motion_recorder = recorders[
        "scripts/Observe-NativeMenuMotionCapability.ps1"
    ]
    importer = recorders["scripts/Import-NativeMenuSpecialCaptures.ps1"]
    support = _read("scripts/NativeMenuCaptureSupport.ps1")
    loader_capture = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "menu_layout_capture_snapshot_and_hooks.inl"
    )
    loading_capture = _read(
        "SolomonDarkModLoader/src/loading_screen_native_present.cpp"
    )

    for path, recorder in (
        ("Record-NativeMenuLayout.ps1", layout_recorder),
        ("Record-NativeMenuTransition.ps1", transition_recorder),
        ("Confirm-NativeMenuLayoutAnimation.ps1", confirmation_recorder),
    ):
        if "Start-Sleep" in recorder or "WaitMilliseconds" in recorder:
            raise StaticReTestFailure(
                f"{path} regained a fixed-delay capture path"
            )

    _require_regex(
        support,
        r"NativeMenuSettleConsecutiveSamples\s*=\s*40\b.*?"
        r"NativeMenuSettleMinimumSpanMilliseconds\s*=\s*2000\b",
        "native-menu Settlement v2 no longer requires 40 samples over at "
        "least two seconds",
    )
    _require_regex(
        support,
        r"\$stableWindow\.Count\s+-ge\s+"
        r"\$script:NativeMenuSettleConsecutiveSamples\s+-and\s+"
        r"\$stableSpan\s+-ge\s+"
        r"\$script:NativeMenuSettleMinimumSpanMilliseconds",
        "native-menu Settlement v2 constants are declared but no longer gate "
        "the same candidate window",
    )
    _require_regex(
        support,
        r"if \(\$probe\.Status -ne \"ready\"\).*?"
        r"Start-Sleep -Milliseconds "
        r"\$script:NativeMenuSettlePollMilliseconds\s+continue",
        "native-menu unavailable probes no longer retry only through the "
        "bounded settlement loop",
    )
    _require_regex(
        support,
        r"\$classification\s*=\s*Invoke-NativeMenuSettlementClassifier\s+`"
        r"\s*-Context \$Context\s+`\s*-Samples @\(\$stableWindow\).*?"
        r"animated_element_ids\s*=\s*@\(\s*"
        r"\$classification\.animated_element_ids\s*\)",
        "native-menu settlement reaches its measured animation classifier but "
        "no longer carries that exact classification into the accepted result",
    )
    _require_regex(
        support,
        r"catch \{\s*"
        r"\$classificationError\s*=\s*\[string\]\$_\.Exception\.Message.*?"
        r"animated geometry cap exceeded:.*?"
        r"\$stableWindow\.Clear\(\).*?"
        r"\$stableWindow\.Add\(\[ordered\]@\{.*?"
        r"last_rejected_candidate='\$lastRejectedCandidate'",
        "a population-positioning window above the animation cap no longer "
        "gets rejected and remeasured until a compliant window or the bounded "
        "STOP names the last rejected candidate",
    )
    _require_regex(
        support,
        r"local structural_elements\s*=\s*\{\}.*?"
        r"table\.sort\(structural_elements, function\(left, right\).*?"
        r"left_order < right_order.*?"
        r"tostring\(left\.id or ''\) < tostring\(right\.id or ''\).*?"
        r"structure\[#structure \+ 1\]\s*=\s*core\(element\)",
        "the live Settlement v2.2 probe no longer canonicalizes only its "
        "structural hash by draw_order then element id",
    )
    _require_regex(
        support,
        r"\$script:NativeMenuPopulationPhaseLimit\s*=\s*4096.*?"
        r"function Initialize-NativeMenuPopulationSampler.*?"
        r"sd\.events\.on\('runtime\.tick', function\(event\).*?"
        r"table\.sort\(structural_elements, function\(left, right\).*?"
        r"left_order < right_order.*?"
        r"tostring\(left\.id or ''\) < tostring\(right\.id or ''\).*?"
        r"if #state\.phases >= "
        r"\$script:NativeMenuPopulationPhaseLimit then.*?"
        r"function Stop-NativeMenuPopulationSampler.*?"
        r"phase_count.*?"
        r"observed no destination phase.*?"
        r"for \(\$phaseIndex = 1; "
        r"\$phaseIndex -le \$phaseCount; \$phaseIndex\+\+\).*?"
        r"Invoke-NativeMenuLua -Context \$Context.*?"
        r"payload_encoding.*?structural-element-arrays-v1",
        "the transition recorder no longer captures bounded, canonical "
        "runtime-tick population phases, retrieves each phase below the Lua "
        "pipe payload ceiling, or fails closed when none are runnable",
    )
    _require_regex(
        transition_recorder,
        r"Initialize-NativeMenuPopulationSampler -Context \$context\s*"
        r"Start-NativeMenuPopulationSampler.*?"
        r"\$dispatchResult\s*=.*?"
        r"\$after\s*=\s*Get-SettledNativeMenuObservation.*?"
        r"\$populationTrace\s*=\s*Stop-NativeMenuPopulationSampler.*?"
        r"high_cadence_structural_phases",
        "navigation dispatch no longer arms its high-cadence sampler before "
        "the action and binds the stopped trace to the settled destination",
    )
    _require_regex(
        support,
        r"function Test-NativeMenuFrameMatchesSettlement.*?"
        r"foreach \(\$geometryName in @\(\"rect\", \"unclipped_rect\"\)\).*?"
        r"\$expectedGeometry\.Count -ne 4.*?"
        r"for \(\$coordinate = 0; \$coordinate -lt 4;.*?"
        r"\[double\]\$frameGeometry\[\$coordinate\] -ne\s*"
        r"\[double\]\$expectedGeometry\[\$coordinate\]",
        "same-call frame validation again compares JSON number formatting "
        "instead of exact numeric non-animated geometry",
    )
    _require_regex(
        support,
        r"throw \(\s*\"STOP: '\$ScreenId' never settled to 40 consecutive "
        r"structurally \".*?\"byte-identical payloads with one measured "
        r"animated ID set spanning \"",
        "a native-menu surface that never satisfies Settlement v2 is no longer "
        "a STOP finding",
    )
    _require_regex(
        layout_recorder,
        r"\$observation\s*=\s*Get-SettledNativeMenuObservation\s+`\s*"
        r"-Context \$context\s+`\s*-ScreenId \$ScreenId",
        "the standalone menu recorder no longer obtains its fixture from the "
        "settlement gate",
    )
    _require_regex(
        transition_recorder,
        r"\$before\s*=\s*Get-SettledNativeMenuObservation.*?"
        r"\$after\s*=\s*Get-SettledNativeMenuObservation",
        "the transition recorder no longer settlement-gates both source and "
        "destination",
    )
    for recorder_name, recorder in (
        ("standalone", layout_recorder),
        ("transition", transition_recorder),
    ):
        if "settle_latency_milliseconds" not in recorder:
            raise StaticReTestFailure(
                f"{recorder_name} menu fixture no longer emits measured settle latency"
            )

    _require_regex(
        confirmation_recorder,
        r"primary\.header\.instance\s+-eq\s+\$Instance.*?"
        r"primary\.header\.process_id\s+-eq\s+\$ProcessId.*?"
        r"primarySourceJson\s+-cne\s+\$confirmationSourceJson.*?"
        r"Get-SettledNativeMenuObservation.*?"
        r"\$rawSetsMatch\s*=\s*\$primaryIdsJson\s+-ceq\s+"
        r"\$confirmationIdsJson.*?"
        r"settlement\s*=\s*\$observation\.settlement.*?"
        r"requires_extended_observation\s*=\s*\(-not \$rawSetsMatch\)",
        "animation confirmation no longer proves a fresh instance/process, "
        "identical machine provenance, or preserves raw-set disagreement for v2.3",
    )
    if "animated ID confirmation mismatch" in confirmation_recorder:
        raise StaticReTestFailure(
            "raw window animation disagreement again vetoes the v2.3 "
            "motion-capability resolution path"
        )
    _require_regex(
        motion_recorder,
        r"stableSpanMilliseconds\s*=\s*\[long\]"
        r"\$baselineSettlement\.stable_span_milliseconds.*?"
        r"requiredSpanMilliseconds\s*=\s*\[Math\]::Max\(\s*"
        r"\[long\]\$script:NativeMenuExtendedMinimumMilliseconds,\s*"
        r"\[long\]\$script:NativeMenuExtendedSpanMultiplier\s*\*\s*"
        r"\$stableSpanMilliseconds\s*\).*?"
        r"while \(\s*\$clock\.ElapsedMilliseconds\s+-lt\s*"
        r"\$requiredSpanMilliseconds\s+-or\s*\$samples\.Count\s+-lt\s*"
        r"\$script:NativeMenuExtendedMinimumSamples\s*\).*?"
        r"Invoke-NativeMenuExtendedObservationClassifier",
        "the v2.3 corroboration recorder no longer derives 60-second/10x "
        "duration from the stationary window and requires at least 200 samples",
    )
    _require_regex(
        motion_recorder,
        r"baselineHeader\.instance\s+-cne\s+\$Instance.*?"
        r"baselineHeader\.process_id\s+-ne\s+\$ProcessId.*?"
        r"baselineSourceJson\s+-cne\s+\$currentSourceJson.*?"
        r"Assert-NativeMenuOverlayHygiene.*?"
        r"motion_events\s*=\s*@\(\$classification\.motion_events\)",
        "the v2.3 corroboration recorder no longer binds the exact stationary "
        "process/provenance, overlay-gates samples, and records every motion delta",
    )

    _require_regex(
        support,
        r"\$baseCommitSha\s*=\s*Invoke-NativeMenuGit.*?"
        r"-Arguments @\(\"rev-parse\", \"HEAD\"\).*?"
        r"\$sourceTreeSha\s*=\s*Invoke-NativeMenuGit.*?"
        r"-Arguments @\(\"rev-parse\", \"HEAD\^\{tree\}\"\)",
        "native-menu provenance no longer derives commit and tree from the "
        "recorder checkout",
    )
    _require_regex(
        support,
        r"expectedExecutable\s*=.*?stage\\SolomonDark\.exe.*?"
        r"injectedLoader\s*=.*?dist\\launcher\\SolomonDarkModLoader\.dll.*?"
        r"\$gameExecutableSha256\s*=\s*\(\s*Get-FileHash "
        r"-LiteralPath \$expectedExecutable.*?"
        r"\$loaderDllSha256\s*=\s*\(\s*Get-FileHash "
        r"-LiteralPath \$injectedLoader.*?"
        r"multiplayer-compatibility\.json.*?"
        r"compatibility\.compatibility\.loader\.sha256\s+-ne\s*"
        r"\$loaderDllSha256",
        "native-menu provenance no longer hashes the exact staged game and "
        "launcher-injected loader or ties them to the stage receipt",
    )
    _require_regex(
        support,
        r"status\", \"--porcelain\", \"--untracked-files=no\".*?"
        r"requires a clean tracked tree",
        "native-menu capture no longer proves HEAD describes its tracked recorder",
    )
    _require_regex(
        support,
        r"Get-Command py\.exe.*?py\.exe -3 -c "
        r"\"print\('native-menu-python-ready'\)\".*?"
        r"exists but cannot run",
        "native-menu capture checks Python presence but no longer proves it runs",
    )
    _require_regex(
        support,
        r"solomondarkmodloader\.log.*?Select-String\s+`.*?"
        r"Debug UI native menu-layout capture hooks installed\..*?"
        r"launch it with SDMOD_NATIVE_MENU_LAYOUT_CAPTURE=1",
        "native-menu recorder can again mistake a permanently disabled capture "
        "hook for a screen that is merely not ready yet",
    )
    _require_regex(
        support,
        r"\$previousErrorActionPreference\s*=\s*\$ErrorActionPreference.*?"
        r"\$ErrorActionPreference\s*=\s*\"Continue\".*?"
        r"\$result\s*=\s*@\(\$LuaCode \| & py\.exe -3 "
        r"\$Context\.LuaExecClient 2>&1\).*?"
        r"\$exitCode\s*=\s*\$LASTEXITCODE.*?finally \{.*?"
        r"\$ErrorActionPreference\s*=\s*\$previousErrorActionPreference",
        "native-menu Lua probing again lets Windows PowerShell terminate on a "
        "busy pipe before the exit-code discriminator can classify it",
    )
    _require_regex(
        support,
        r"if \(-not \(Test-NativeMenuOwnedProcess.*?throw \(\s*"
        r"\"BROKEN: the exact staged process exited.*?"
        r"if \(\$AllowBusy -and \$pipeUnavailable\).*?Status = \"busy\"",
        "native-menu Lua probing no longer distinguishes a broken owned process "
        "from a busy pipe",
    )
    _require_regex(
        importer,
        r"\$baseCommitSha\s*=\s*Invoke-CaptureGit "
        r"@\(\"rev-parse\", \"HEAD\"\).*?"
        r"\$gameExecutableSha256\s*=\s*\(\s*Get-FileHash "
        r"-LiteralPath \$nativeExecutable.*?"
        r"\$loaderDllSha256\s*=\s*\(\s*Get-FileHash "
        r"-LiteralPath \$injectedLoader.*?"
        r"compatibility\.compatibility\.loader\.sha256\s+-ne\s*"
        r"\$loaderDllSha256",
        "special menu capture import no longer derives its own Git and binary "
        "provenance",
    )
    _require_regex(
        importer,
        r"py\.exe -3 \$classifierPath find\s+`\s*"
        r"--input \$inputPath\s+`\s*--output \$outputPath.*?"
        r"settlement_spec\s*=\s*"
        r"\[string\]\$Classification\.settlement_spec.*?"
        r"structural_element_order\s*=\s*\(.*?"
        r"\[string\]\$Classification\.structural_element_order.*?"
        r"consecutive_structural_samples.*?structural_sha256",
        "native-loader/loading import no longer reclassifies the complete raw "
        "sample stream or carry Settlement v2.2 canonical ordering into its "
        "fixture header",
    )
    _require_regex(
        importer,
        r"function Write-SpecialSettlementTrace.*?"
        r"if \(\$settledWindow\.Count -lt 40\).*?"
        r"schema\s*=\s*\"solomon-dark-native-menu-settlement-trace-v2\".*?"
        r"settled_window_samples\s*=\s*\$settledWindow.*?"
        r"loaderFixture\.header\.settlement_trace\s*=\s*"
        r"Write-SpecialSettlementTrace.*?"
        r"loadingFixture\.header\.settlement_trace\s*=\s*"
        r"Write-SpecialSettlementTrace",
        "native loader/loading import no longer emits real standardized raw "
        "windows for v2.3 campaign-wide motion resolution",
    )
    for surface, source in (
        ("native_loader", loader_capture),
        ("loading_screen", loading_capture),
    ):
        _require_regex(
            source,
            r"stable_sample_count\s*>=\s*40\s*&&\s*stable_span\s*>=\s*2000",
            f"{surface} capture no longer applies the 40-sample/two-second gate",
        )
        if "settle_latency_milliseconds" not in source:
            raise StaticReTestFailure(
                f"{surface} raw recording no longer emits measured settle latency"
            )
    _require_regex(
        loader_capture,
        r"SerializeNativeBootStructure\(.*?"
        r"const auto semantic = SerializeNativeBootStructure\(sample\).*?"
        r"semantic != g_native_boot_stable_semantic",
        "native-loader capture no longer gates population on structure before "
        "the importer measures animated geometry",
    )
    _require_regex(
        loading_capture,
        r"SerializeLoadingStructure\(.*?"
        r"const auto structure_json = SerializeLoadingStructure\(.*?"
        r"structure_json != g_loading_stable_semantic",
        "loading-screen capture no longer gates population on structure before "
        "the importer measures animated geometry",
    )

    return (
        "standalone, transition, native-loader, and loading-screen capture paths "
        "apply Settlement v2.3, preserve fresh-instance raw measurements, "
        "derive long corroboration from the stationary window, and "
        "derive commit/tree/exact-binary provenance without operator overrides"
    )


def test_native_menu_settlement_v2_classifier_is_strict_and_ci_wired() -> str:
    assert_module_runs_in_ci("test_native_menu_settlement_v2")
    classifier = _read("tools/native_menu_settlement_v2.py")
    _require_regex(
        classifier,
        r"MINIMUM_SAMPLES\s*=\s*40\b.*?"
        r"MINIMUM_SPAN_MILLISECONDS\s*=\s*2_000\b.*?"
        r"MAXIMUM_ANIMATED_FRACTION\s*=\s*0\.30\b.*?"
        r"EXTENDED_OBSERVATION_MINIMUM_MILLISECONDS\s*=\s*60_000\b.*?"
        r"EXTENDED_OBSERVATION_SETTLE_SPAN_MULTIPLIER\s*=\s*10\b.*?"
        r"EXTENDED_OBSERVATION_MINIMUM_SAMPLES\s*=\s*200\b.*?"
        r"SETTLEMENT_SPEC\s*=\s*\"2\.4\"",
        "Settlement v2 sample/span/animated-cap constants drifted from the "
        "amended menu capture and corroboration definition",
    )
    _require_regex(
        classifier,
        r"for payload in typed_payloads\[1:\]:\s*"
        r"_assert_non_geometry_stable\(anchor_payload, payload\).*?"
        r"animated_ids\s*=\s*\[.*?"
        r"len\(set\(geometries\[element_id\]\)\)\s*>\s*1",
        "Settlement v2 no longer derives animation only after every "
        "non-geometry field and element membership stay fixed",
    )
    _require_regex(
        classifier,
        r"if animated_fraction > maximum_animated_fraction:.*?"
        r"raise SettlementV2Error\(\s*\"animated geometry cap exceeded:",
        "Settlement v2 no longer stops when measured animation exceeds 30 "
        "percent of a screen",
    )
    _require_regex(
        classifier,
        r"element\[\"animated_geometry\"\]\s*=\s*True.*?"
        r"element\[\"anchor_rect\"\].*?"
        r"element\[\"anchor_unclipped_rect\"\].*?"
        r"element\[\"envelope\"\]\s*=\s*\{.*?"
        r"\"sample_count\": len\(rects\)",
        "Settlement v2 fixtures no longer preserve an honest first-sample "
        "anchor and measured motion envelope",
    )
    _require_regex(
        classifier,
        r"def resolve_motion_capability\(.*?"
        r"all_measured_sets\s*=\s*\[\*raw_id_sets\].*?"
        r"resolved_ids\s*=\s*sorted\(set\(\)\.union\(\*all_measured_sets\)\).*?"
        r"pair_disputed\s*=\s*members\[0\]\[1\]\.symmetric_difference"
        r"\(members\[1\]\[1\]\).*?"
        r"motion capability resolution requires extended observation.*?"
        r"phantom animated classification.*?"
        r"resolved animated geometry cap exceeded",
        "Settlement v2.3 no longer resolves screen-member motion by asymmetric "
        "union, corroborates a stationary side, rejects phantoms, and reapplies the cap",
    )
    _require_regex(
        classifier,
        r"def classify_extended_observation\(.*?"
        r"max\(\s*EXTENDED_OBSERVATION_MINIMUM_MILLISECONDS,.*?"
        r"if len\(samples\) < minimum_samples:.*?"
        r"events\s*=\s*_motion_events\(samples\).*?"
        r"motion_events\": events",
        "Settlement v2.3 extended observations no longer prove duration/sample "
        "floors and retain the exact timestamped change census",
    )
    _require_regex(
        classifier,
        r"def validate_resolved_motion_capability\(.*?"
        r"phantom\s*=\s*sorted\(set\(declared_ids\) - set\(expected_ids\)\).*?"
        r"future\s*=\s*sorted\(set\(expected_ids\) - set\(declared_ids\)\).*?"
        r"future motion drift: member",
        "Settlement v2.3 can no longer distinguish neither phantom flags nor "
        "later motion by a member pinned stationary",
    )
    _require_regex(
        classifier,
        r"def _canonical_element_key\(.*?"
        r"return float\(draw_order\), element_id.*?"
        r"def canonical_structural_layout\(.*?"
        r"result\[\"elements\"\]\s*=\s*_canonical_elements\(elements\).*?"
        r"def structural_layout_bytes\(.*?canonical_structural_layout\(",
        "Settlement v2.2 cross-instance comparison no longer sorts elements "
        "by draw_order then native element id",
    )
    _require_regex(
        classifier,
        r"def _assert_non_geometry_stable\(.*?"
        r"if set\(order\) != set\(anchor_order\):.*?"
        r"element membership varied .*?within the settled window",
        "Settlement v2.2 again treats instance-arbitrary raw list position as "
        "structural state",
    )
    return (
        "Settlement v2.3 classification, guardrails, canonical structural "
        "ordering, fixture shaping, motion asymmetry, corroboration, and drift "
        "are behavior-tested by the CI unit module"
    )


def test_native_menu_motion_capability_campaign_resolution_is_fail_closed() -> str:
    assert_module_runs_in_ci("test_native_menu_settlement_v2")
    resolver = _read("tools/resolve_native_menu_motion_campaign.py")
    promoter = _read("tools/promote_native_menu_recapture.py")
    confirmation = _read("scripts/Confirm-NativeMenuLayoutAnimation.ps1")

    forbidden_provenance_options = (
        "--base-commit-sha",
        "--source-tree-sha",
        "--game-executable-sha256",
        "--loader-dll-sha256",
        "--resolved-animated-element-id",
    )
    smuggled = [
        option for option in forbidden_provenance_options if option in resolver
    ]
    if smuggled:
        raise StaticReTestFailure(
            "motion-capability resolver accepts operator-supplied provenance "
            f"or classification values: {smuggled}"
        )
    _require_regex(
        resolver,
        r"def collect_standalones\(.*?"
        r"if not fixture_paths:.*?standalone sweep reached no candidate fixtures.*?"
        r"if layout_id in fixtures:.*?ambiguous.*?"
        r"def collect_navigation\(.*?"
        r"set\(primary_by_id\) != set\(confirmation_by_id\).*?"
        r"edge census is absent or ambiguous",
        "motion-capability resolution no longer proves it reached real "
        "standalones or refuses duplicate/missing screen and edge candidates",
    )
    _require_regex(
        resolver,
        r"pair_id\s*=\s*f\"standalone:\{layout_id\}\".*?"
        r"pair_id\s*=\s*f\"edge:\{edge_id\}:\{side\}\".*?"
        r"resolve_motion_capability\(.*?"
        r"if len\(resolved_by_index\) != len\(observations\):.*?"
        r"did not reach every campaign observation",
        "screen motion resolution no longer pairs every standalone and every "
        "edge endpoint across two fresh recordings before normalization",
    )
    _require_regex(
        resolver,
        r"endpoint\[\"layout\"\]\s*=\s*normalized\[\"layout\"\].*?"
        r"endpoint\[\"motion_capability\"\]\s*=\s*proofs\[layout_id\].*?"
        r"if verify:.*?"
        r"resolved candidate .*? is not the machine-derived v2\.4 result.*?"
        r"resolved navigation is not the machine-derived v2\.4 result",
        "the v2.3 resolver no longer applies one screen classification to every "
        "fixture/endpoint or verifies the derived artifacts byte-for-byte",
    )
    _require_regex(
        promoter,
        r"motion_capability_resolution.*?settlement_spec.*?2\.4.*?"
        r"resolve_campaign\(.*?False,\s*True,",
        "menu promotion can bypass re-derivation of the complete v2.3 campaign",
    )
    _require_regex(
        confirmation,
        r"\$rawSetsMatch\s*=.*?"
        r"requires_extended_observation\s*=\s*\(-not \$rawSetsMatch\)",
        "fresh confirmation no longer preserves a raw-set mismatch for the "
        "mandatory stationary-side observation",
    )
    return (
        "Settlement v2.3 resolves one motion-capability set across every paired "
        "standalone/edge observation, refuses ambiguity and operator provenance, "
        "and promotion re-derives the complete campaign"
    )


def test_native_menu_landed_population_override_is_fail_closed() -> str:
    assert_module_runs_in_ci("test_native_menu_settlement_v2")
    classifier = _read("tools/native_menu_settlement_v2.py")
    attacher = _read("tools/attach_native_menu_landed_override.py")
    promoter = _read("tools/promote_native_menu_recapture.py")

    _require_regex(
        classifier,
        r"def build_population_phase_override\(.*?"
        r"assert_canonical_structure_matches\(primary_layout, confirmation_layout\).*?"
        r"differences\s*=\s*structural_differences\(.*?"
        r"if landed_generation == settled_generation:.*?"
        r"landed and settled generations do not differ",
        "Settlement v2.1 landed override no longer requires a generation change "
        "and canonical second-instance structural agreement",
    )
    _require_regex(
        classifier,
        r"if difference\[\"kind\"\] == \"settled_only_element\":.*?"
        r"is not a vanishing population member.*?"
        r"_landed_difference_in_settled_payload.*?"
        r"landed population override rejected:.*?is present.*?settled window.*?"
        r"if not primary_witnesses or not confirmation_witnesses:.*?"
        r"lacks two-instance population",
        "Settlement v2.1 landed override no longer rejects settled members or "
        "requires every old value in both population traces and neither settled window",
    )
    _require_regex(
        classifier,
        r"high_cadence_phases\s*=\s*trace\.get\("
        r"\"high_cadence_structural_phases\", \[\]\).*?"
        r"phases\s*=\s*\[\*high_cadence_phases, \*polled_phases\].*?"
        r"encoding == \"structural-element-arrays-v1\".*?"
        r"dict\(zip\(_COMPACT_POPULATION_ELEMENT_FIELDS, compact\)\)",
        "Settlement v2.1 override proof no longer consumes the high-cadence "
        "dispatch phases that can witness pre-poll population members",
    )
    _require_regex(
        attacher,
        r"landed_path\s*=\s*\(.*?primary_path\.name.*?"
        r"successful\.append\(\s*\(\s*\"landed_population_override\".*?"
        r"build_population_phase_override\(.*?"
        r"if len\(successful\) != 1:.*?"
        r"field, override\s*=\s*successful\[0\].*?"
        r"header\[field\]\s*=\s*override",
        "the landed override attacher no longer derives its old/new proof from "
        "the uniquely named landed fixture and two raw traces or refuses "
        "ambiguous override resolution",
    )
    forbidden_override_options = (
        "--landed-generation",
        "--settled-generation",
        "--landed-element-count",
        "--settled-element-count",
        "--structural-differences",
        "--base-commit-sha",
        "--game-executable-sha256",
        "--loader-dll-sha256",
    )
    smuggled = [value for value in forbidden_override_options if value in attacher]
    if smuggled:
        raise StaticReTestFailure(
            "the landed override attacher accepts operator-supplied proof or "
            f"provenance values: {smuggled}"
        )
    _require_regex(
        promoter,
        r"def validate_population_override\(.*?"
        r"build_population_phase_override\(",
        "menu promotion no longer re-derives a declared Settlement v2.1 "
        "override from its raw evidence",
    )
    _require_regex(
        promoter,
        r"if structural_bit_match:.*?"
        r"if declared_override_fields:.*?matching landed structure.*?"
        r"else:.*?if len\(declared_override_fields\) != 1:.*?"
        r"override_kind == \"landed_population_override\":.*?"
        r"validate_population_override\(",
        "menu promotion can bypass or falsely declare the Settlement v2.1 "
        "landed population override",
    )
    return (
        "Settlement v2.1 landed overrides are machine-derived from two exact "
        "population traces, require canonical structural agreement and a "
        "generation change, and reject any difference surviving settlement"
    )


def test_native_menu_overlay_contamination_override_is_fail_closed() -> str:
    assert_module_runs_in_ci("test_native_menu_settlement_v2")
    classifier = _read("tools/native_menu_settlement_v2.py")
    reference_builder = _read("tools/build_native_menu_overlay_reference.py")
    attacher = _read("tools/attach_native_menu_landed_override.py")
    promoter = _read("tools/promote_native_menu_recapture.py")
    support = _read("scripts/NativeMenuCaptureSupport.ps1")
    importer = _read("scripts/Import-NativeMenuSpecialCaptures.ps1")
    aggregate_builder = _read("scripts/Build-NativeMenuGoldens.ps1")
    unit_tests = _read("tests/test_native_menu_settlement_v2.py")

    _require_regex(
        classifier,
        r"def build_overlay_contamination_override\(.*?"
        r"assert_canonical_structure_matches\(primary_layout, confirmation_layout\).*?"
        r"reference_counter = validate_overlay_reference\(overlay_reference\).*?"
        r"_subtract_overlay_semantic_multiset\(.*?"
        r"if corrected_bytes != primary_bytes:.*?"
        r"semantic-multiset difference leaves.*?residual draws or fields",
        "Settlement v2.4 overlay correction no longer requires canonical "
        "second-instance agreement and zero-residual semantic subtraction",
    )
    _require_regex(
        classifier,
        r"absence_payloads = \(.*?primary_phases.*?confirmation_phases.*?"
        r"primary_settled.*?confirmation_settled.*?\).*?"
        r"overlay_semantic_multiset_is_present\(payload, overlay_reference\).*?"
        r"appears in a fresh population phase or settled window.*?"
        r"generation difference lacks.*?two-instance population witnesses",
        "Settlement v2.4 overlay correction no longer proves the complete "
        "semantic multiset absent and its generation change in both traces",
    )
    _require_regex(
        classifier,
        r"def deterministic_reordinalized_layout\(.*?"
        r"elements.sort\(key=_reordinalization_key\).*?"
        r"counts\[base\] \+= 1.*?"
        r"element\[\"id\"\] = new_id.*?element\[\"draw_order\"\] = art_order.*?"
        r"normalized_corrected.*?normalized_primary.*?normalized_confirmation",
        "Settlement v2.4 overlay correction no longer deterministically "
        "reassigns positional draw orders and per-art ordinals on all views",
    )
    _require_regex(
        classifier,
        r"def overlay_semantic_multiset_is_present\(.*?"
        r"all\(observed\[signature\] >= count.*?required.items\(\)\).*?"
        r"def assert_overlay_hygiene\(.*?"
        r"contains the complete beta-dialog semantic multiset",
        "overlay hygiene no longer rejects only a complete semantic "
        "sub-multiset and may regress to suffix-intersection false positives",
    )
    _require_regex(
        unit_tests,
        r"def test_overlay_override_rejects_residual_draw_beyond_reference\(.*?"
        r"semantic-multiset difference leaves.*?residual draws or fields.*?"
        r"def test_overlay_override_rejects_noncanonical_reordinalization\(.*?"
        r"_noncanonical.*?residual draws or fields",
        "the v2.4 unit mutations no longer trip residual semantic draws and "
        "non-canonical survivor ordinals by their named claims",
    )
    _require_regex(
        unit_tests,
        r"def test_overlay_hygiene_rejects_complete_semantic_multiset\(.*?"
        r"assertRaisesRegex\(.*?complete beta-dialog semantic multiset.*?"
        r"def test_overlay_hygiene_accepts_pause_style_partial_shared_suffix_subset\(.*?"
        r"elements.*?append\(.*?assert_overlay_hygiene\(",
        "the overlay hygiene regression no longer rejects a complete dialog "
        "while accepting pause-style partial atlas sharing",
    )
    _require_regex(
        reference_builder,
        r"def build_reference\(.*?"
        r"derive_overlay_reference\(overlay_layout, clean_layout\).*?"
        r"\"overlay_capture\": evidence_receipt\(.*?"
        r"\"clean_capture\": evidence_receipt\(.*?"
        r"validate_overlay_reference\(reference\)",
        "the beta-dialog reference is no longer derived from two hashed live "
        "captures",
    )
    forbidden_reference_options = (
        "--art-element-id-suffix",
        "--overlay-only-element",
        "--game-executable-sha256",
        "--loader-dll-sha256",
        "--base-commit-sha",
    )
    smuggled = [
        option for option in forbidden_reference_options if option in reference_builder
    ]
    if smuggled:
        raise StaticReTestFailure(
            "the overlay reference builder accepts operator-supplied set or "
            f"provenance values: {smuggled}"
        )
    _require_regex(
        attacher,
        r"menu-overlay-reference\.json.*?"
        r"validate_evidence_receipt\(.*?overlay_capture.*?"
        r"validate_evidence_receipt\(.*?clean_capture.*?"
        r"build_overlay_contamination_override\(.*?"
        r"if len\(successful\) != 1:.*?absent or ambiguous",
        "the landed override attacher no longer hashes the fixed reference "
        "evidence, derives v2.4, and refuses ambiguous override paths",
    )
    _require_regex(
        promoter,
        r"def validate_overlay_override\(.*?"
        r"build_overlay_contamination_override\(.*?"
        r"canonical_bytes\(declared\) != canonical_bytes\(expected\).*?"
        r"derived exactly from the reference and both fresh traces",
        "menu promotion no longer re-derives the exact declared Settlement "
        "v2.4 overlay proof from the committed reference and both traces",
    )
    _require_regex(
        promoter,
        r"assert_overlay_hygiene\(layout, overlay_reference\).*?"
        r"assert_overlay_hygiene\(confirmation_layout, overlay_reference\).*?"
        r"assert_overlay_hygiene\(before_layout, overlay_reference\).*?"
        r"assert_overlay_hygiene\(destination_layout, overlay_reference\)",
        "menu promotion no longer rejects beta-dialog contamination in every "
        "standalone, confirmation, source, and destination surface",
    )
    _require_regex(
        promoter,
        r"source_structural_match\s*=\s*structurally_matches\(.*?"
        r"landed\[\"before\"\]\[\"layout\"\].*?"
        r"source_frame_match\s*=.*?frame_sha256.*?"
        r"source_bit_match\s*=.*?source_signature_match.*?"
        r"source_structural_match.*?source_frame_match.*?"
        r"if not source_bit_match:.*?if len\(override_matches\) != 1:",
        "menu promotion no longer requires every transition source to bit-match "
        "its landed semantic/frame truth or one unique approved correction",
    )
    _require_regex(
        support,
        r"foreach \(\$phase in \$structuralPhases\) \{\s*"
        r"Assert-NativeMenuOverlayHygiene.*?-Layout \$phase\.payload",
        "the live recorder checks only the final layout and can silently accept "
        "overlay contamination from an earlier sampled population phase",
    )
    _require_regex(
        support,
        r"local function compact\(element\).*?"
        r"element\.left.*?element\.top.*?element\.right.*?element\.bottom.*?"
        r"element\.unclipped_left.*?element\.unclipped_top.*?"
        r"element\.unclipped_right.*?element\.unclipped_bottom.*?"
        r"payload_encoding\":\"structural-element-arrays-v1",
        "high-cadence population evidence no longer carries the full geometry "
        "needed to prove semantic overlay absence",
    )
    _require_regex(
        importer,
        r"function Assert-SpecialCaptureSampleOverlayHygiene.*?"
        r"check-overlay-samples.*?"
        r"Assert-SpecialCaptureSampleOverlayHygiene.*?"
        r"-Samples @\(\$loaderClassifierSamples\).*?"
        r"Assert-SpecialCaptureSampleOverlayHygiene.*?"
        r"-Samples @\(\$loadingClassifierSamples\)",
        "native-loader/loading import no longer overlay-gates every raw sample",
    )
    for path, source in (
        ("NativeMenuCaptureSupport.ps1", support),
        ("Import-NativeMenuSpecialCaptures.ps1", importer),
        ("Build-NativeMenuGoldens.ps1", aggregate_builder),
    ):
        _require_regex(
            source,
            r"tests[\\/]fixtures[\\/]webgame[\\/]menu-overlay-reference\.json.*?"
            r"check-overlay.*?--reference",
            f"{path} no longer binds overlay hygiene to the fixed, "
            "machine-derived committed reference",
        )
    return (
        "Settlement v2.4 derives one hashed beta-overlay semantic multiset, "
        "accepts only exact zero-residual subtraction with deterministic "
        "reordinalization, and hygiene-gates every capture surface"
    )


def _animated_ids_for_layout(
    layout: dict[str, Any], witness: str
) -> list[str]:
    animated_ids = layout.get("animated_element_ids")
    if not isinstance(animated_ids, list) or not all(
        isinstance(value, str) and value for value in animated_ids
    ):
        raise StaticReTestFailure(
            f"{witness} lost its measured animated_element_ids list"
        )
    if len(animated_ids) != len(set(animated_ids)):
        raise StaticReTestFailure(
            f"{witness} contains ambiguous duplicate animated element IDs"
        )
    return animated_ids


def _assert_external_evidence_receipt(receipt: object, witness: str) -> None:
    if not isinstance(receipt, dict):
        raise StaticReTestFailure(f"{witness} lost its external evidence receipt")
    if (
        not isinstance(receipt.get("evidence_path"), str)
        or not receipt["evidence_path"]
        or not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("sha256")))
        or isinstance(receipt.get("bytes"), bool)
        or not isinstance(receipt.get("bytes"), int)
        or receipt["bytes"] <= 0
    ):
        raise StaticReTestFailure(
            f"{witness} external evidence provenance is incomplete"
        )


def _assert_motion_capability(
    proof: object,
    layout: dict[str, Any],
    animated_ids: list[str],
    witness: str,
    pair_id: str,
    instance: str,
    process_id: object,
) -> tuple[int, list[str]]:
    if not isinstance(proof, dict) or proof.get("rule") != (
        "Settlement v2.3 screen-member motion capability"
    ):
        raise StaticReTestFailure(
            f"{witness} lost its Settlement v2.3 motion-capability proof"
        )
    if proof.get("screen_id") != layout.get("screen_id"):
        raise StaticReTestFailure(
            f"{witness} motion-capability proof names a different screen"
        )
    if not isinstance(proof.get("layout_id"), str) or not proof["layout_id"]:
        raise StaticReTestFailure(
            f"{witness} motion-capability proof lost its logical layout identity"
        )
    if (
        not instance
        or isinstance(process_id, bool)
        or not isinstance(process_id, int)
        or process_id <= 0
    ):
        raise StaticReTestFailure(
            f"{witness} lost its exact capture process identity"
        )
    if proof.get("resolved_animated_element_ids") != animated_ids:
        raise StaticReTestFailure(
            f"{witness} fixture animated IDs disagree with screen capability"
        )
    raw = proof.get("raw_observations")
    if not isinstance(raw, list) or len(raw) < 2:
        raise StaticReTestFailure(
            f"{witness} motion-capability sweep reached fewer than two raw observations"
        )
    pairs: dict[str, list[dict[str, Any]]] = {}
    raw_union: set[str] = set()
    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            raise StaticReTestFailure(
                f"{witness} raw motion observation {index} is not an object"
            )
        row_pair = row.get("pair_id")
        row_ids = row.get("animated_element_ids")
        if (
            not isinstance(row_pair, str)
            or not row_pair
            or not isinstance(row_ids, list)
            or not all(isinstance(value, str) and value for value in row_ids)
            or len(row_ids) != len(set(row_ids))
            or row.get("sample_count", 0) < MINIMUM_SAMPLES
            or row.get("stable_span_milliseconds", 0)
            < MINIMUM_SPAN_MILLISECONDS
            or isinstance(row.get("motion_event_count"), bool)
            or not isinstance(row.get("motion_event_count"), int)
            or row["motion_event_count"] < 0
        ):
            raise StaticReTestFailure(
                f"{witness} raw motion observation {index} is incomplete"
            )
        _assert_external_evidence_receipt(
            row.get("evidence"), f"{witness} raw motion observation {index}"
        )
        raw_union.update(row_ids)
        pairs.setdefault(row_pair, []).append(row)
    if not pairs:
        raise StaticReTestFailure(
            f"{witness} motion-capability proof resolved no independent pair"
        )
    for row_pair, members in pairs.items():
        identities = {
            (member.get("instance"), member.get("process_id"))
            for member in members
        }
        if len(members) != 2 or len(identities) != 2:
            raise StaticReTestFailure(
                f"{witness} pair {row_pair!r} does not contain two fresh processes"
            )
    endpoint_rows = [
        row
        for row in raw
        if row.get("pair_id") == pair_id
        and row.get("instance") == instance
        and row.get("process_id") == process_id
    ]
    if len(endpoint_rows) != 1:
        raise StaticReTestFailure(
            f"{witness} does not resolve one raw observation for its exact process/pair"
        )

    extended = proof.get("extended_observations")
    if not isinstance(extended, list):
        raise StaticReTestFailure(
            f"{witness} motion-capability proof lost its extended-observation list"
        )
    extended_by_identity: dict[tuple[object, object], list[dict[str, Any]]] = {}
    extended_union: set[str] = set()
    for index, row in enumerate(extended):
        if not isinstance(row, dict):
            raise StaticReTestFailure(
                f"{witness} extended motion observation {index} is not an object"
            )
        moving_ids = row.get("moving_element_ids")
        if (
            not isinstance(moving_ids, list)
            or not all(isinstance(value, str) and value for value in moving_ids)
            or len(moving_ids) != len(set(moving_ids))
            or row.get("required_span_milliseconds", 0) < 60_000
            or row.get("observed_span_milliseconds", 0)
            < row.get("required_span_milliseconds", 0)
            or row.get("sample_count", 0) < 200
            or isinstance(row.get("motion_event_count"), bool)
            or not isinstance(row.get("motion_event_count"), int)
            or row["motion_event_count"] < 0
        ):
            raise StaticReTestFailure(
                f"{witness} extended motion observation {index} violates its floor"
            )
        _assert_external_evidence_receipt(
            row.get("evidence"), f"{witness} extended motion observation {index}"
        )
        extended_union.update(moving_ids)
        extended_by_identity.setdefault(
            (row.get("instance"), row.get("process_id")), []
        ).append(row)

    disputed: set[str] = set()
    for row_pair, members in pairs.items():
        first_ids = set(members[0]["animated_element_ids"])
        second_ids = set(members[1]["animated_element_ids"])
        for element_id in first_ids.symmetric_difference(second_ids):
            disputed.add(element_id)
            stationary = members[0] if element_id not in first_ids else members[1]
            corroborations = extended_by_identity.get(
                (stationary.get("instance"), stationary.get("process_id")), []
            )
            if len(corroborations) != 1:
                raise StaticReTestFailure(
                    f"{witness} disputed member {element_id!r} in pair "
                    f"{row_pair!r} lacks one stationary-side extended observation"
                )
            required = max(
                60_000,
                10 * int(stationary["stable_span_milliseconds"]),
            )
            if corroborations[0]["required_span_milliseconds"] != required:
                raise StaticReTestFailure(
                    f"{witness} disputed member {element_id!r} records a false "
                    "60-second/10x corroboration bound"
                )
    if proof.get("disputed_element_ids") != sorted(disputed):
        raise StaticReTestFailure(
            f"{witness} records a false disputed-member census"
        )
    if set(animated_ids) != raw_union | extended_union:
        raise StaticReTestFailure(
            f"{witness} resolved set is not the asymmetric union of measured motion"
        )

    motion_evidence = proof.get("motion_evidence")
    if not isinstance(motion_evidence, list):
        raise StaticReTestFailure(
            f"{witness} lost its per-member motion-event evidence"
        )
    evidence_by_id = {
        row.get("element_id"): row
        for row in motion_evidence
        if isinstance(row, dict)
    }
    if set(evidence_by_id) != set(animated_ids) or len(evidence_by_id) != len(
        motion_evidence
    ):
        raise StaticReTestFailure(
            f"{witness} contains a phantom or ambiguous animated classification"
        )
    for element_id, row in evidence_by_id.items():
        witnesses = row.get("witnesses")
        if not isinstance(witnesses, list) or not witnesses:
            raise StaticReTestFailure(
                f"{witness} animated member {element_id!r} has no measured motion event"
            )
        for event_witness in witnesses:
            if (
                not isinstance(event_witness, dict)
                or event_witness.get("motion_event_count", 0) <= 0
                or not isinstance(event_witness.get("first_event"), dict)
                or event_witness["first_event"].get("element_id") != element_id
            ):
                raise StaticReTestFailure(
                    f"{witness} animated member {element_id!r} has phantom event evidence"
                )
            _assert_external_evidence_receipt(
                event_witness.get("evidence"),
                f"{witness} animated member {element_id} event",
            )
    expected_sample_count = sum(row["sample_count"] for row in raw) + sum(
        row["sample_count"] for row in extended
    )
    if proof.get("envelope_sample_count") != expected_sample_count:
        raise StaticReTestFailure(
            f"{witness} motion envelope does not cover every campaign sample"
        )
    return expected_sample_count, endpoint_rows[0]["animated_element_ids"]


def _assert_settlement_v2_layout(
    layout: dict[str, Any],
    settlement: dict[str, Any],
    witness: str,
    motion_capability: object,
    pair_id: str,
    instance: str,
    process_id: object,
) -> list[str]:
    if settlement.get("settlement_spec") != "2.4":
        raise StaticReTestFailure(
            f"{witness} does not identify the Settlement v2.4 discipline"
        )
    if settlement.get("structural_element_order") != (
        "draw_order_then_element_id"
    ):
        raise StaticReTestFailure(
            f"{witness} makes raw element-list position structural"
        )
    elements = layout.get("elements")
    if not isinstance(elements, list) or not elements:
        raise StaticReTestFailure(
            f"{witness} did not reach any real menu elements"
        )
    element_ids = [element.get("id") for element in elements]
    if not all(isinstance(value, str) and value for value in element_ids):
        raise StaticReTestFailure(
            f"{witness} contains an element without a stable native ID"
        )
    if len(element_ids) != len(set(element_ids)):
        raise StaticReTestFailure(
            f"{witness} contains ambiguous duplicate native element IDs"
        )

    animated_ids = _animated_ids_for_layout(layout, witness)
    motion_sample_count, expected_raw_ids = _assert_motion_capability(
        motion_capability,
        layout,
        animated_ids,
        witness,
        pair_id,
        instance,
        process_id,
    )
    animated_set = set(animated_ids)
    shaped_ids: list[str] = []
    required_static_fields = {
        "id",
        "kind",
        "text",
        "action_id",
        "art_id",
        "font_id",
        "text_style",
        "visible",
        "interactive",
        "draw_order",
    }
    envelope_fields = {
        "min_x",
        "max_x",
        "min_y",
        "max_y",
        "min_width",
        "max_width",
        "min_height",
        "max_height",
    }
    for element in elements:
        element_id = element["id"]
        if not required_static_fields.issubset(element):
            raise StaticReTestFailure(
                f"{witness}.{element_id} lost part of its exact static remainder"
            )
        if element_id in animated_set:
            shaped_ids.append(element_id)
            if element.get("animated_geometry") is not True:
                raise StaticReTestFailure(
                    f"{witness}.{element_id} is measured animated but lacks its marker"
                )
            if "rect" in element or "unclipped_rect" in element:
                raise StaticReTestFailure(
                    f"{witness}.{element_id} smuggles a frozen moving rect into "
                    "the structural payload"
                )
            for anchor_name in ("anchor_rect", "anchor_unclipped_rect"):
                anchor = element.get(anchor_name)
                if not isinstance(anchor, list) or len(anchor) != 4:
                    raise StaticReTestFailure(
                        f"{witness}.{element_id} lost its four-coordinate {anchor_name}"
                    )
            envelope = element.get("envelope")
            if not isinstance(envelope, dict) or set(envelope) != {
                "sample_count",
                "rect",
                "unclipped_rect",
            }:
                raise StaticReTestFailure(
                    f"{witness}.{element_id} lost its exact motion-envelope shape"
                )
            if envelope["sample_count"] != motion_sample_count:
                raise StaticReTestFailure(
                    f"{witness}.{element_id} envelope does not cover every campaign observation"
                )
            for geometry_name in ("rect", "unclipped_rect"):
                geometry = envelope.get(geometry_name)
                if not isinstance(geometry, dict) or set(geometry) != envelope_fields:
                    raise StaticReTestFailure(
                        f"{witness}.{element_id}.{geometry_name} lost a measured "
                        "min/max envelope coordinate"
                    )
                for minimum, maximum in (
                    ("min_x", "max_x"),
                    ("min_y", "max_y"),
                    ("min_width", "max_width"),
                    ("min_height", "max_height"),
                ):
                    if geometry[minimum] > geometry[maximum]:
                        raise StaticReTestFailure(
                            f"{witness}.{element_id}.{geometry_name} records an "
                            f"impossible {minimum}/{maximum} envelope"
                        )
        else:
            if any(
                field in element
                for field in (
                    "animated_geometry",
                    "anchor_rect",
                    "anchor_unclipped_rect",
                    "envelope",
                )
            ):
                raise StaticReTestFailure(
                    f"{witness}.{element_id} carries animation data without "
                    "measured classification"
                )
            for geometry_name in ("rect", "unclipped_rect"):
                geometry = element.get(geometry_name)
                if not isinstance(geometry, list) or len(geometry) != 4:
                    raise StaticReTestFailure(
                        f"{witness}.{element_id} lost exact non-animated geometry"
                    )
    if shaped_ids != animated_ids:
        raise StaticReTestFailure(
            f"{witness} animated ID list does not equal its marked element set"
        )

    if settlement.get("consecutive_structural_samples", 0) < MINIMUM_SAMPLES:
        raise StaticReTestFailure(
            f"{witness} no longer proves 40 consecutive structural samples"
        )
    if settlement.get("animated_id_set_sample_count", 0) < MINIMUM_SAMPLES:
        raise StaticReTestFailure(
            f"{witness} no longer proves one animated ID set across all 40 samples"
        )
    if settlement.get("stable_span_milliseconds", 0) < (
        MINIMUM_SPAN_MILLISECONDS
    ):
        raise StaticReTestFailure(
            f"{witness} no longer proves a two-second settled window"
        )
    if settlement.get("settle_latency_milliseconds", 0) < (
        MINIMUM_SPAN_MILLISECONDS
    ):
        raise StaticReTestFailure(
            f"{witness} lost its measured end-to-end settle latency"
        )
    if settlement.get("animated_element_ids") != animated_ids:
        raise StaticReTestFailure(
            f"{witness} settlement header disagrees with its animated ID list"
        )
    raw_ids = settlement.get("raw_window_animated_element_ids")
    if (
        not isinstance(raw_ids, list)
        or not all(isinstance(value, str) and value for value in raw_ids)
        or len(raw_ids) != len(set(raw_ids))
    ):
        raise StaticReTestFailure(
            f"{witness} lost its raw per-window animated ID measurement"
        )
    if raw_ids != expected_raw_ids:
        raise StaticReTestFailure(
            f"{witness} settlement disagrees with its exact raw-window observation"
        )
    if settlement.get("motion_envelope_sample_count") != motion_sample_count:
        raise StaticReTestFailure(
            f"{witness} settlement records a false campaign envelope sample count"
        )
    if settlement.get("element_count") != len(elements):
        raise StaticReTestFailure(
            f"{witness} settlement header disagrees with its element census"
        )
    if settlement.get("animated_element_count") != len(animated_ids):
        raise StaticReTestFailure(
            f"{witness} settlement header disagrees with its animated census"
        )
    animated_fraction = len(animated_ids) / len(elements)
    if animated_fraction > MAXIMUM_ANIMATED_FRACTION:
        raise StaticReTestFailure(
            f"{witness} exceeds the 30 percent animated-screen STOP cap"
        )
    if settlement.get("animated_fraction") != animated_fraction:
        raise StaticReTestFailure(
            f"{witness} records a false animated element fraction"
        )
    structural_sha = hashlib.sha256(
        structural_layout_bytes(layout, animated_ids)
    ).hexdigest()
    if settlement.get("structural_sha256") != structural_sha:
        raise StaticReTestFailure(
            f"{witness} records a false structural payload hash"
        )
    return animated_ids


def _assert_animation_confirmation(
    header: dict[str, Any],
    animated_ids: list[str],
    structural_sha256: str,
    witness: str,
) -> None:
    confirmation = header.get("animation_confirmation")
    if not isinstance(confirmation, dict):
        raise StaticReTestFailure(
            f"{witness} lost its independent animated-ID confirmation"
        )
    if confirmation.get("instance") == header.get("instance"):
        raise StaticReTestFailure(
            f"{witness} animation confirmation reused the primary instance"
        )
    if confirmation.get("process_id") == header.get("process_id"):
        raise StaticReTestFailure(
            f"{witness} animation confirmation reused the primary process"
        )
    if confirmation.get("source") != header.get("source"):
        raise StaticReTestFailure(
            f"{witness} animation confirmation changed machine provenance"
        )
    if confirmation.get("confirmation_structural_sha256") != structural_sha256:
        raise StaticReTestFailure(
            f"{witness} resolved confirmation structure disagrees with its screen"
        )
    if confirmation.get("animated_element_ids_sha256") != hashlib.sha256(
        canonical_bytes(sorted(animated_ids))
    ).hexdigest():
        raise StaticReTestFailure(
            f"{witness} animation confirmation records a false animated-ID hash"
        )
    for field in (
        "raw_confirmation_structural_sha256",
        "raw_confirmation_animated_element_ids_sha256",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(confirmation.get(field))):
            raise StaticReTestFailure(
                f"{witness} animation confirmation lost {field}"
            )
    if confirmation.get("motion_capability_resolved") is not True:
        raise StaticReTestFailure(
            f"{witness} animation confirmation bypassed screen-level resolution"
        )
    if (
        not isinstance(confirmation.get("evidence_filename"), str)
        or not confirmation["evidence_filename"]
        or not re.fullmatch(r"[0-9a-f]{64}", str(confirmation.get("sha256")))
        or confirmation.get("bytes", 0) <= 0
    ):
        raise StaticReTestFailure(
            f"{witness} lost its evidence-bundle confirmation provenance"
        )


def _assert_landed_population_override(
    header: dict[str, Any], layout: dict[str, Any], witness: str
) -> bool:
    override = header.get("landed_population_override")
    if override is None:
        return False
    if not isinstance(override, dict):
        raise StaticReTestFailure(
            f"{witness} landed population override is not an object"
        )
    if override.get("rule") != (
        "Settlement v2.1 landed population-phase override"
    ):
        raise StaticReTestFailure(
            f"{witness} does not name the narrow Settlement v2.1 override rule"
        )
    if override.get("canonical_order") != "draw_order_then_element_id":
        raise StaticReTestFailure(
            f"{witness} override makes raw element-list position contractual"
        )
    elements = layout.get("elements")
    if not isinstance(elements, list) or not elements:
        raise StaticReTestFailure(
            f"{witness} override did not reach a settled element census"
        )
    settled_generation = layout.get("generation")
    if override.get("settled_generation") != settled_generation:
        raise StaticReTestFailure(
            f"{witness} override records a false settled generation"
        )
    if override.get("landed_generation") == settled_generation:
        raise StaticReTestFailure(
            f"{witness} override did not supersede a different landed generation"
        )
    if override.get("settled_element_count") != len(elements):
        raise StaticReTestFailure(
            f"{witness} override records a false settled element census"
        )
    animated_ids = _animated_ids_for_layout(layout, witness)
    structural_sha = hashlib.sha256(
        structural_layout_bytes(layout, animated_ids)
    ).hexdigest()
    if override.get("canonical_structural_sha256") != structural_sha:
        raise StaticReTestFailure(
            f"{witness} override records a false canonical settled structure"
        )
    if override.get("confirmation_canonical_structural_sha256") != structural_sha:
        raise StaticReTestFailure(
            f"{witness} override lacks second-instance canonical structural agreement"
        )

    differences = override.get("structural_differences")
    if not isinstance(differences, list) or not differences:
        raise StaticReTestFailure(
            f"{witness} override enumerates no landed structural difference"
        )
    identities = [
        (
            difference.get("kind"),
            difference.get("element_id"),
            difference.get("field"),
        )
        for difference in differences
        if isinstance(difference, dict)
    ]
    if len(identities) != len(differences):
        raise StaticReTestFailure(
            f"{witness} override contains a non-object structural difference"
        )
    if len(identities) != len(set(identities)):
        raise StaticReTestFailure(
            f"{witness} override ambiguously repeats a structural difference"
        )
    generation_differences = [
        difference
        for difference in differences
        if difference.get("kind") == "layout_field"
        and difference.get("field") == "generation"
    ]
    if len(generation_differences) != 1:
        raise StaticReTestFailure(
            f"{witness} override does not enumerate exactly one generation change"
        )
    current_by_id = {element.get("id"): element for element in elements}
    landed_only_count = 0
    for difference in differences:
        kind = difference.get("kind")
        if kind == "settled_only_element":
            raise StaticReTestFailure(
                f"{witness} override admits a settled-only member instead of a "
                "vanishing population member"
            )
        if difference.get("landed_value") == difference.get("settled_value"):
            raise StaticReTestFailure(
                f"{witness} override records a structural difference with equal values"
            )
        for instance_label in ("primary", "confirmation"):
            indexes = difference.get(
                f"{instance_label}_population_phase_indexes"
            )
            if not isinstance(indexes, list) or not indexes or not all(
                isinstance(index, int) and index >= 0 for index in indexes
            ):
                raise StaticReTestFailure(
                    f"{witness} difference {identities[differences.index(difference)]} "
                    f"has no {instance_label} population witness"
                )
            if difference.get(
                f"{instance_label}_settled_absence_samples", 0
            ) < MINIMUM_SAMPLES:
                raise StaticReTestFailure(
                    f"{witness} difference {identities[differences.index(difference)]} "
                    f"was not absent from the {instance_label} settled window"
                )
        if kind == "landed_only_element":
            landed_only_count += 1
            element_id = difference.get("element_id")
            landed_value = difference.get("landed_value")
            if (
                element_id in current_by_id
                or not isinstance(landed_value, dict)
                or landed_value.get("id") != element_id
                or difference.get("settled_value") is not None
            ):
                raise StaticReTestFailure(
                    f"{witness} falsely identifies vanished member {element_id!r}"
                )
        elif kind == "element_field":
            element_id = difference.get("element_id")
            field = difference.get("field")
            element = current_by_id.get(element_id)
            if not isinstance(element, dict) or element.get(field) != difference.get(
                "settled_value"
            ):
                raise StaticReTestFailure(
                    f"{witness} records a false settled value for {element_id}.{field}"
                )
        elif kind == "layout_field":
            field = difference.get("field")
            if layout.get(field) != difference.get("settled_value"):
                raise StaticReTestFailure(
                    f"{witness} records a false settled layout field {field}"
                )
        else:
            raise StaticReTestFailure(
                f"{witness} override contains unknown difference kind {kind!r}"
            )
    if override.get("landed_element_count") != len(elements) + landed_only_count:
        raise StaticReTestFailure(
            f"{witness} override census does not equal settled plus vanished members"
        )

    for trace_label in ("primary_population_trace", "confirmation_population_trace"):
        trace = override.get(trace_label)
        if not isinstance(trace, dict):
            raise StaticReTestFailure(
                f"{witness} override has no {trace_label} provenance"
            )
        if (
            not isinstance(trace.get("evidence_path"), str)
            or not trace["evidence_path"]
            or not re.fullmatch(r"[0-9a-f]{64}", str(trace.get("sha256")))
            or trace.get("bytes", 0) <= 0
            or not isinstance(trace.get("edge_id"), str)
            or not trace["edge_id"]
            or trace.get("side") != "destination"
        ):
            raise StaticReTestFailure(
                f"{witness} override lost exact {trace_label} evidence provenance"
            )
        counts = trace.get("element_count_trace")
        generations = trace.get("generation_trace")
        observations = trace.get("phase_observations")
        if (
            not isinstance(counts, list)
            or not counts
            or not isinstance(generations, list)
            or len(generations) != len(counts)
            or not isinstance(observations, list)
            or len(observations) != len(counts)
            or trace.get("settled_sample_count", 0) < MINIMUM_SAMPLES
        ):
            raise StaticReTestFailure(
                f"{witness} override lost its measured {trace_label} phase trace"
            )
    return True


def _assert_landed_overlay_override(
    header: dict[str, Any],
    layout: dict[str, Any],
    witness: str,
    overlay_reference: dict[str, Any],
    overlay_reference_path: Path,
) -> bool:
    override = header.get("landed_overlay_override")
    if override is None:
        return False
    if not isinstance(override, dict):
        raise StaticReTestFailure(
            f"{witness} landed overlay override is not an object"
        )
    if override.get("rule") != (
        "Settlement v2.4 landed beta-overlay semantic-multiset override"
    ):
        raise StaticReTestFailure(
            f"{witness} does not name the narrow Settlement v2.4 overlay rule"
        )
    if (
        override.get("canonical_order") != "draw_order_then_remaining_fields"
        or override.get("ordinal_identity")
        != "screen_local_positional_bookkeeping"
    ):
        raise StaticReTestFailure(
            f"{witness} overlay override makes raw list position or ordinal identity contractual"
        )

    receipt = override.get("overlay_reference")
    if not isinstance(receipt, dict):
        raise StaticReTestFailure(
            f"{witness} overlay override lost its committed reference receipt"
        )
    if receipt.get("fixture") != (
        "tests/fixtures/webgame/menu-overlay-reference.json"
    ):
        raise StaticReTestFailure(
            f"{witness} overlay override names a different reference fixture"
        )
    assert_recorded_hash_matches_file(
        receipt.get("sha256"),
        overlay_reference_path,
        f"{witness} overlay reference",
    )
    if receipt.get("bytes") != overlay_reference_path.stat().st_size:
        raise StaticReTestFailure(
            f"{witness} overlay override records a false reference byte count"
        )
    for capture_label in ("overlay_capture", "clean_capture"):
        if receipt.get(capture_label) != overlay_reference["header"].get(
            capture_label
        ):
            raise StaticReTestFailure(
                f"{witness} overlay override changed its {capture_label} evidence receipt"
            )

    elements = layout.get("elements")
    if not isinstance(elements, list) or not elements:
        raise StaticReTestFailure(
            f"{witness} overlay override did not reach settled menu elements"
        )
    current_by_id = {element.get("id"): element for element in elements}
    if len(current_by_id) != len(elements) or None in current_by_id:
        raise StaticReTestFailure(
            f"{witness} overlay override cannot resolve unique surviving element IDs"
        )
    settled_generation = layout.get("generation")
    if override.get("settled_generation") != settled_generation:
        raise StaticReTestFailure(
            f"{witness} overlay override records a false settled generation"
        )
    if override.get("landed_generation") == settled_generation:
        raise StaticReTestFailure(
            f"{witness} overlay override has no witnessed generation change"
        )
    if override.get("settled_element_count") != len(elements):
        raise StaticReTestFailure(
            f"{witness} overlay override records a false settled element census"
        )
    animated_ids = _animated_ids_for_layout(layout, witness)
    structural_sha = hashlib.sha256(
        structural_layout_bytes(layout, animated_ids)
    ).hexdigest()
    for field in (
        "canonical_structural_sha256",
        "confirmation_canonical_structural_sha256",
    ):
        if override.get(field) != structural_sha:
            raise StaticReTestFailure(
                f"{witness} overlay override records a false {field}"
            )

    differences = override.get("structural_differences")
    if not isinstance(differences, list) or not differences:
        raise StaticReTestFailure(
            f"{witness} overlay override enumerates no structural differences"
        )
    identities = [
        (
            difference.get("kind"),
            difference.get("element_id"),
            difference.get("field"),
        )
        for difference in differences
        if isinstance(difference, dict)
    ]
    if len(identities) != len(differences) or len(identities) != len(
        set(identities)
    ):
        raise StaticReTestFailure(
            f"{witness} overlay override has ambiguous structural differences"
        )
    generation_differences = [
        difference
        for difference in differences
        if difference.get("kind") == "layout_field"
        and difference.get("field") == "generation"
    ]
    if len(generation_differences) != 1 or generation_differences[0].get(
        "settled_value"
    ) != settled_generation:
        raise StaticReTestFailure(
            f"{witness} overlay override does not enumerate its exact generation change"
        )
    reference_entries = overlay_reference.get("overlay_semantic_draw_multiset")
    if not isinstance(reference_entries, list) or not reference_entries:
        raise StaticReTestFailure(
            f"{witness} overlay reference has no semantic draw multiset"
        )
    reference_hash_counts: dict[str, int] = {}
    for entry in reference_entries:
        if not isinstance(entry, dict):
            raise StaticReTestFailure(
                f"{witness} overlay semantic multiset contains a non-object entry"
            )
        payload = entry.get("payload")
        count = entry.get("count")
        if not isinstance(payload, dict) or not isinstance(count, int) or count <= 0:
            raise StaticReTestFailure(
                f"{witness} overlay semantic multiset contains an invalid count or payload"
            )
        semantic_hash = hashlib.sha256(canonical_bytes(payload)).hexdigest()
        reference_hash_counts[semantic_hash] = count
    reference_draw_count = sum(reference_hash_counts.values())
    if (
        override.get("overlay_semantic_draw_count") != reference_draw_count
        or override.get("overlay_semantic_multiset_sha256")
        != hashlib.sha256(canonical_bytes(reference_entries)).hexdigest()
    ):
        raise StaticReTestFailure(
            f"{witness} overlay proof records a different semantic multiset"
        )
    removed = override.get("removed_overlay_draws")
    if not isinstance(removed, list) or len(removed) != reference_draw_count:
        raise StaticReTestFailure(
            f"{witness} overlay proof removed the wrong semantic draw census"
        )
    removed_hash_counts: dict[str, int] = {}
    removed_ids: set[str] = set()
    for row in removed:
        if not isinstance(row, dict):
            raise StaticReTestFailure(
                f"{witness} overlay removal proof contains a non-object row"
            )
        element_id = row.get("landed_element_id")
        draw_order = row.get("landed_draw_order")
        semantic_hash = row.get("semantic_draw_sha256")
        if (
            not isinstance(element_id, str)
            or not element_id
            or element_id in removed_ids
            or isinstance(draw_order, bool)
            or not isinstance(draw_order, (int, float))
            or not re.fullmatch(r"[0-9a-f]{64}", str(semantic_hash))
        ):
            raise StaticReTestFailure(
                f"{witness} overlay removal proof has ambiguous positional bookkeeping"
            )
        removed_ids.add(element_id)
        removed_hash_counts[str(semantic_hash)] = (
            removed_hash_counts.get(str(semantic_hash), 0) + 1
        )
    if removed_hash_counts != reference_hash_counts:
        raise StaticReTestFailure(
            f"{witness} landed-minus-settled semantic difference is not exactly the overlay multiset"
        )
    if override.get("landed_element_count") != len(elements) + len(removed):
        raise StaticReTestFailure(
            f"{witness} overlay census is not settled plus the exact semantic multiset"
        )

    for difference in differences:
        if difference.get("landed_value") == difference.get("settled_value"):
            raise StaticReTestFailure(
                f"{witness} overlay proof records an equal-valued difference"
            )
        if difference.get("kind") not in {
            "layout_field",
            "landed_only_element",
            "settled_only_element",
            "element_field",
        }:
            raise StaticReTestFailure(
                f"{witness} overlay proof contains an unsupported structural difference"
            )

    absence = override.get("overlay_absence")
    if not isinstance(absence, dict):
        raise StaticReTestFailure(
            f"{witness} overlay proof has no semantic-multiset absence census"
        )
    for field, minimum in (
        ("primary_population_phases", 1),
        ("confirmation_population_phases", 1),
        ("primary_settled_samples", MINIMUM_SAMPLES),
        ("confirmation_settled_samples", MINIMUM_SAMPLES),
    ):
        if absence.get(field, 0) < minimum:
            raise StaticReTestFailure(
                f"{witness} overlay semantic multiset lacks {field} absence proof"
            )

    witnesses = override.get("generation_population_witnesses")
    if not isinstance(witnesses, dict):
        raise StaticReTestFailure(
            f"{witness} overlay generation change has no two-instance witnesses"
        )
    for field in ("primary_phase_indexes", "confirmation_phase_indexes"):
        indexes = witnesses.get(field)
        if not isinstance(indexes, list) or not indexes or not all(
            isinstance(index, int) and index >= 0 for index in indexes
        ):
            raise StaticReTestFailure(
                f"{witness} overlay generation change lacks {field}"
            )

    reordinalization = override.get("deterministic_reordinalization")
    if (
        not isinstance(reordinalization, dict)
        or reordinalization.get("algorithm")
        != "art_draw_order_then_remaining_fields_per_art_id"
    ):
        raise StaticReTestFailure(
            f"{witness} overlay proof lost its deterministic ordinal algorithm"
        )
    try:
        normalized_layout, normalized_ids, expected_primary_proof = (
            deterministic_reordinalized_layout(layout, animated_ids)
        )
    except SettlementV2Error as error:
        raise StaticReTestFailure(
            f"{witness} settled layout cannot be deterministically reordinalized: {error}"
        ) from error
    if reordinalization.get("settled_primary") != expected_primary_proof:
        raise StaticReTestFailure(
            f"{witness} overlay proof records a non-canonical settled survivor ordinal"
        )
    expected_projection = [
        (row["normalized_element_id"], row["normalized_draw_order"])
        for row in expected_primary_proof
    ]
    for label in ("corrected_landed", "settled_confirmation"):
        proof = reordinalization.get(label)
        if not isinstance(proof, list) or not all(
            isinstance(row, dict) for row in proof
        ):
            raise StaticReTestFailure(
                f"{witness} overlay proof has no {label} reordinalization witness"
            )
        projection = [
            (row.get("normalized_element_id"), row.get("normalized_draw_order"))
            for row in proof
        ]
        if projection != expected_projection:
            raise StaticReTestFailure(
                f"{witness} overlay proof has a non-canonical {label} survivor ordinal"
            )
    normalized_hash = hashlib.sha256(
        structural_layout_bytes(normalized_layout, normalized_ids)
    ).hexdigest()
    if override.get("reordinalized_structural_sha256") != normalized_hash:
        raise StaticReTestFailure(
            f"{witness} overlay proof records a false reordinalized structural hash"
        )

    for trace_label in ("primary_population_trace", "confirmation_population_trace"):
        trace = override.get(trace_label)
        if not isinstance(trace, dict):
            raise StaticReTestFailure(
                f"{witness} overlay override has no {trace_label} provenance"
            )
        if (
            not isinstance(trace.get("evidence_path"), str)
            or not trace["evidence_path"]
            or not re.fullmatch(r"[0-9a-f]{64}", str(trace.get("sha256")))
            or trace.get("bytes", 0) <= 0
            or not isinstance(trace.get("edge_id"), str)
            or not trace["edge_id"]
            or trace.get("side") != "destination"
            or not isinstance(trace.get("element_count_trace"), list)
            or not trace["element_count_trace"]
            or len(trace.get("generation_trace", []))
            != len(trace["element_count_trace"])
            or len(trace.get("phase_observations", []))
            != len(trace["element_count_trace"])
            or trace.get("settled_sample_count", 0) < MINIMUM_SAMPLES
        ):
            raise StaticReTestFailure(
                f"{witness} overlay override lost exact {trace_label} evidence"
            )
    return True


def test_native_menu_settled_destinations_equal_standalones() -> str:
    golden = _json("tests/fixtures/webgame/menu-goldens.json")
    if golden.get("schema") != "solomon-dark-menu-goldens-v2":
        raise StaticReTestFailure(
            "settled destination contract did not reach a Settlement v2 aggregate"
        )
    resolution_header = golden.get("header", {}).get(
        "motion_capability_resolution"
    )
    if (
        not isinstance(resolution_header, dict)
        or resolution_header.get("settlement_spec") != "2.4"
        or resolution_header.get("screen_count", 0) < len(LAYOUT_IDS) + 1
        or not isinstance(
            resolution_header.get("motion_observation_directory"), str
        )
    ):
        raise StaticReTestFailure(
            "settled destination contract did not reach the complete v2.4 "
            "campaign-resolution receipt"
        )
    for field in ("primary_raw_recording", "confirmation_raw_recording"):
        _assert_external_evidence_receipt(
            resolution_header.get(field),
            f"settled menu {field}",
        )
    overlay_reference_path = (
        ROOT / "tests/fixtures/webgame/menu-overlay-reference.json"
    )
    overlay_reference = _json(
        "tests/fixtures/webgame/menu-overlay-reference.json"
    )
    if not isinstance(overlay_reference, dict) or overlay_reference.get(
        "schema"
    ) != OVERLAY_REFERENCE_SCHEMA:
        raise StaticReTestFailure(
            "settled menu contract did not reach the machine-derived overlay reference"
        )
    try:
        validate_overlay_reference(overlay_reference)
    except SettlementV2Error as error:
        raise StaticReTestFailure(
            f"settled menu overlay reference is invalid: {error}"
        ) from error
    overlay_receipt = golden.get("header", {}).get("overlay_reference")
    if not isinstance(overlay_receipt, dict) or overlay_receipt.get(
        "fixture"
    ) != "menu-overlay-reference.json":
        raise StaticReTestFailure(
            "settled menu aggregate lost its committed overlay-reference receipt"
        )
    assert_recorded_hash_matches_file(
        overlay_receipt.get("sha256"),
        overlay_reference_path,
        "settled menu aggregate overlay reference",
    )
    if overlay_receipt.get("bytes") != overlay_reference_path.stat().st_size:
        raise StaticReTestFailure(
            "settled menu aggregate records a false overlay-reference byte count"
        )
    edges = golden["navigation_graph"]["edges"]
    edge_ids = [edge["id"] for edge in edges]
    if len(edge_ids) != len(EDGE_CONTRACT):
        raise StaticReTestFailure(
            "settled destination contract did not examine all 39 navigation edges"
        )
    if len(edge_ids) != len(set(edge_ids)):
        raise StaticReTestFailure(
            "settled destination contract found ambiguous duplicate edge IDs"
        )
    if set(edge_ids) != set(EDGE_CONTRACT):
        raise StaticReTestFailure(
            "settled destination contract did not reach every pinned navigation edge"
        )

    layout_entries = [
        *golden["layouts"],
        *golden["transition_endpoint_layouts"],
    ]
    if len(layout_entries) != len(LAYOUT_IDS) + 1:
        raise StaticReTestFailure(
            "settled destination contract did not examine all 28 census layouts "
            "and the standalone hub witness"
        )
    fixture_names = [entry["fixture"] for entry in layout_entries]
    if len(fixture_names) != len(set(fixture_names)):
        raise StaticReTestFailure(
            "settled destination contract found ambiguous duplicate standalone fixtures"
        )
    if "menu-transition-layouts/hub.json" not in fixture_names:
        raise StaticReTestFailure(
            "settled destination contract did not reach the standalone hub witness"
        )
    by_fixture = {entry["fixture"]: entry for entry in layout_entries}
    fixture_root = ROOT / "tests/fixtures/webgame"

    provenance_sources: list[dict[str, Any]] = []
    population_override_fixtures: list[str] = []
    overlay_override_fixtures: list[str] = []
    for entry in layout_entries:
        fixture = entry["fixture"]
        standalone = _json(f"tests/fixtures/webgame/{fixture}")
        if standalone.get("schema") != "solomon-dark-native-menu-layout-v2":
            raise StaticReTestFailure(
                f"settled standalone {fixture} does not use Settlement v2"
            )
        if standalone["header"] != entry["header"] or (
            standalone["layout"] != entry["layout"]
        ):
            raise StaticReTestFailure(
                f"settled standalone {fixture} disagrees with its embedded golden"
            )
        reference = fixture_root / entry["reference_capture"]
        standalone_reference = (
            (fixture_root / fixture).parent / standalone["header"]["reference_capture"]
        ).resolve()
        if standalone_reference != reference.resolve():
            raise StaticReTestFailure(
                f"settled standalone {fixture} and its aggregate name different "
                "reference captures"
            )
        assert_recorded_hash_matches_file(
            entry["reference_sha256"],
            reference,
            f"{fixture} settled reference capture",
        )
        header = entry["header"]
        if header.get("recorded_live") is not True:
            raise StaticReTestFailure(
                f"settled standalone {fixture} lost recorded-live provenance"
            )
        standalone_motion = header.get("motion_capability")
        standalone_layout_id = (
            standalone_motion.get("layout_id", "")
            if isinstance(standalone_motion, dict)
            else ""
        )
        animated_ids = _assert_settlement_v2_layout(
            entry["layout"],
            header["settlement"],
            f"standalone {fixture}",
            standalone_motion,
            "standalone:" + str(standalone_layout_id),
            str(header.get("instance", "")),
            header.get("process_id"),
        )
        try:
            assert_overlay_hygiene(entry["layout"], overlay_reference)
        except SettlementV2Error as error:
            raise StaticReTestFailure(
                f"standalone {fixture} failed overlay hygiene: {error}"
            ) from error
        _assert_animation_confirmation(
            header,
            animated_ids,
            header["settlement"]["structural_sha256"],
            fixture,
        )
        population_override = _assert_landed_population_override(
            header, entry["layout"], fixture
        )
        overlay_override = _assert_landed_overlay_override(
            header,
            entry["layout"],
            fixture,
            overlay_reference,
            overlay_reference_path,
        )
        if population_override and overlay_override:
            raise StaticReTestFailure(
                f"{fixture} ambiguously declares both landed override paths"
            )
        if population_override:
            population_override_fixtures.append(fixture)
        if overlay_override:
            overlay_override_fixtures.append(fixture)
        provenance_sources.append(header["source"])

    if "menu-layouts/create-element.json" not in overlay_override_fixtures:
        raise StaticReTestFailure(
            "settled menu override sweep did not reach the accepted beta-overlay "
            "create-element standalone witness"
        )

    for edge in edges:
        edge_id = edge["id"]
        destination_fixture = edge.get("destination_layout_fixture")
        if destination_fixture not in by_fixture:
            raise StaticReTestFailure(
                f"{edge_id} has no unique standalone destination fixture"
            )
        before_ids = _assert_settlement_v2_layout(
            edge["before"]["layout"],
            edge["before"]["settlement"],
            f"{edge_id}.source",
            edge["before"].get("motion_capability"),
            f"edge:{edge_id}:source",
            str(edge.get("header", {}).get("instance", "")),
            edge.get("header", {}).get("process_id"),
        )
        after_ids = _assert_settlement_v2_layout(
            edge["after"]["layout"],
            edge["after"]["settlement"],
            f"{edge_id}.destination",
            edge["after"].get("motion_capability"),
            f"edge:{edge_id}:destination",
            str(edge.get("header", {}).get("instance", "")),
            edge.get("header", {}).get("process_id"),
        )
        try:
            assert_overlay_hygiene(edge["before"]["layout"], overlay_reference)
            assert_overlay_hygiene(edge["after"]["layout"], overlay_reference)
        except SettlementV2Error as error:
            raise StaticReTestFailure(
                f"{edge_id} failed transition overlay hygiene: {error}"
            ) from error
        if edge["before"].get("animated_element_ids") != before_ids:
            raise StaticReTestFailure(
                f"{edge_id}.source endpoint summary changed its animated ID set"
            )
        if edge["after"].get("animated_element_ids") != after_ids:
            raise StaticReTestFailure(
                f"{edge_id}.destination endpoint summary changed its animated ID set"
            )
        standalone_layout = by_fixture[destination_fixture]["layout"]
        standalone_motion = by_fixture[destination_fixture]["header"].get(
            "motion_capability"
        )
        standalone_ids = _animated_ids_for_layout(
            standalone_layout, f"standalone {destination_fixture}"
        )
        if set(after_ids) != set(standalone_ids):
            raise StaticReTestFailure(
                f"{edge_id} settled destination animated ID set does not equal "
                f"{destination_fixture}"
            )
        if edge["after"].get("motion_capability") != standalone_motion:
            raise StaticReTestFailure(
                f"{edge_id} destination does not carry the same resolved "
                f"screen-member motion proof as {destination_fixture}"
            )
        try:
            destination_bytes = structural_layout_bytes(
                edge["after"]["layout"], after_ids
            )
            standalone_bytes = structural_layout_bytes(
                standalone_layout, standalone_ids
            )
        except SettlementV2Error as error:
            raise StaticReTestFailure(
                f"{edge_id} structural destination comparison was ambiguous: {error}"
            ) from error
        if destination_bytes != standalone_bytes:
            raise StaticReTestFailure(
                f"{edge_id} settled destination structural payload does not "
                f"byte-match {destination_fixture}"
            )
        header = edge["header"]
        if header["settlement"]["source"] != edge["before"]["settlement"]:
            raise StaticReTestFailure(
                f"{edge_id} carries two disagreeing source settlement records"
            )
        if header["settlement"]["destination"] != edge["after"]["settlement"]:
            raise StaticReTestFailure(
                f"{edge_id} carries two disagreeing destination settlement records"
            )
        if header.get("recorded_live") is not True:
            raise StaticReTestFailure(
                f"{edge_id} lost recorded-live transition provenance"
            )
        provenance_sources.append(header["source"])

    if len(provenance_sources) != len(layout_entries) + len(EDGE_CONTRACT):
        raise StaticReTestFailure(
            "settled menu provenance sweep did not reach all 68 fixture/edge headers"
        )
    resolved_pairs: set[tuple[str, str]] = set()
    for source in provenance_sources:
        commit = source.get("base_commit_sha")
        tree = source.get("source_tree_sha")
        game_hash = source.get("game_executable_sha256")
        loader_hash = source.get("loader_dll_sha256")
        if not isinstance(commit, str) or not re.fullmatch(
            r"[0-9a-f]{40}", commit
        ):
            raise StaticReTestFailure(
                "settled menu fixture lost machine-derived base commit provenance"
            )
        if not isinstance(tree, str) or not re.fullmatch(r"[0-9a-f]{40}", tree):
            raise StaticReTestFailure(
                "settled menu fixture lost machine-derived source tree provenance"
            )
        if not isinstance(game_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", game_hash
        ):
            raise StaticReTestFailure(
                "settled menu fixture lost exact game-executable provenance"
            )
        if not isinstance(loader_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", loader_hash
        ):
            raise StaticReTestFailure(
                "settled menu fixture lost exact staged-loader provenance"
            )
        resolved_pairs.add((commit, tree))

    if not resolved_pairs:
        raise StaticReTestFailure(
            "settled menu provenance sweep resolved no commit/tree witness"
        )
    for commit, tree in sorted(resolved_pairs):
        result = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", f"{commit}^{{tree}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or result.stdout.strip() != tree:
            raise StaticReTestFailure(
                f"settled menu provenance tree {tree} is not the tree of {commit}"
            )
        reachable = subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", commit, "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if reachable.returncode != 0:
            raise StaticReTestFailure(
                f"settled menu base commit {commit} is not an ancestor of HEAD"
            )

    raw = golden["header"]["raw_recording"]
    if (
        not raw["evidence_filename"]
        or not re.fullmatch(r"[0-9a-f]{64}", raw["sha256"])
        or raw["bytes"] <= 0
    ):
        raise StaticReTestFailure(
            "settled menu golden lost its raw evidence-bundle provenance"
        )
    return (
        "all 39 transition destinations structurally byte-match their explicit "
        "settled standalone fixtures with equal animated ID sets, committed "
        "reference hashes, beta-overlay hygiene, fresh-instance confirmation, "
        "and resolvable provenance"
    )


def test_native_menu_screen_census_and_live_layouts_are_pinned() -> str:
    findings = _read("docs/reverse-engineering/native-menus-and-boot.md")
    golden = _json("tests/fixtures/webgame/menu-goldens.json")
    if golden["schema"] != "solomon-dark-menu-goldens-v2":
        raise StaticReTestFailure("the G11 golden schema drifted")
    if golden["screen_census"] != list(LAYOUT_IDS):
        raise StaticReTestFailure(
            f"the G11 screen census drifted: {golden['screen_census']}"
        )
    if golden["header"]["screen_count"] != len(LAYOUT_IDS):
        raise StaticReTestFailure("the G11 screen count header drifted")
    if len(golden["layouts"]) != len(LAYOUT_IDS):
        raise StaticReTestFailure("a G11 layout was added or removed")

    fixture_root = ROOT / "tests/fixtures/webgame"
    observed_ids: list[str] = []
    by_id: dict[str, dict[str, object]] = {}
    claimed_captures: set[Path] = set()
    for entry in golden["layouts"]:
        fixture = entry["fixture"]
        layout_id = fixture.removeprefix("menu-layouts/").removesuffix(
            ".json"
        )
        observed_ids.append(layout_id)
        by_id[layout_id] = entry
        header = entry["header"]
        if not header["instance"] or not header["capture_method"]:
            raise StaticReTestFailure(
                f"{layout_id} lost live capture provenance"
            )
        source = header["source"]
        if not re.fullmatch(r"[0-9a-f]{40}", source["base_commit_sha"]):
            raise StaticReTestFailure(
                f"{layout_id} machine-derived base commit is not an exact SHA"
            )
        if source["game_executable_sha256"] != (
            "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3"
        ):
            raise StaticReTestFailure(
                f"{layout_id} was not captured from the pinned retail EXE"
            )
        reference = fixture_root / entry["reference_capture"]
        if not reference.is_file():
            raise StaticReTestFailure(
                f"{layout_id} lost its reference capture"
            )
        assert_recorded_hash_matches_file(
            entry["reference_sha256"],
            reference,
            f"{layout_id} reference capture",
        )
        claimed_captures.add(reference.resolve())

        # The golden embeds each layout and the standalone fixture is committed
        # beside it.  Two copies of the same recording are two chances to
        # disagree, so tie them together rather than trusting whichever one a
        # reader happens to open.
        on_disk = _json(f"tests/fixtures/webgame/{fixture}")
        if on_disk["layout"] != entry["layout"]:
            raise StaticReTestFailure(
                f"{layout_id}: the embedded golden and {fixture} disagree"
            )
        standalone_reference = (
            fixture_root / "menu-layouts" / on_disk["header"]["reference_capture"]
        ).resolve()
        if standalone_reference != reference.resolve():
            raise StaticReTestFailure(
                f"{layout_id}: {fixture} names a different reference capture "
                f"than the golden"
            )

        elements = entry["layout"]["elements"]
        if not elements:
            raise StaticReTestFailure(f"{layout_id} has no live elements")
        for element in elements:
            geometry = (
                element.get("anchor_rect")
                if element.get("animated_geometry") is True
                else element.get("rect")
            )
            if not element["id"] or not isinstance(geometry, list) or (
                len(geometry) != 4
            ):
                raise StaticReTestFailure(
                    f"{layout_id} contains an incomplete live element"
                )
    if observed_ids != list(LAYOUT_IDS):
        raise StaticReTestFailure(
            f"the ordered embedded layout set drifted: {observed_ids}"
        )

    committed_captures = {
        path.resolve()
        for path in (fixture_root / "menu-reference-captures").glob("*.png")
    }
    orphans = sorted(
        path.name for path in committed_captures - claimed_captures
    )
    if orphans:
        raise StaticReTestFailure(
            "reference captures are committed but claimed by no screen: "
            + ", ".join(orphans)
        )

    # Dark Cloud tab selection is carried by two signals that move together: the
    # selected tab's label rises TAB_RAISE px, and its `UI.13` bracket pair grows
    # from BRACKET_RESTING to BRACKET_SELECTED.  The brackets' x never changes.
    # Pin both -- an earlier draft of this block claimed the label raise was the
    # whole mechanism, and a mutation that slid a bracket sideways went
    # undetected, which is how the second signal was found in the first place.
    def _tab_label_tops(layout_id: str) -> dict[str, float]:
        """Each tab label's baseline, refusing to guess when a label is ambiguous.

        `multiplayer` appears twice per screen: once as the band-sized element
        standing in for the control the other three tabs have, and once as the
        drawn label.  Keying a dict by label text silently kept whichever came
        last in element order -- and element order is exactly what permutes
        between tab states, so that reading was riding on an accident.  Discard
        the band-sized elements explicitly and refuse anything still ambiguous.
        """
        prefix = layout_id.replace("-", "_")
        tops: dict[str, float] = {}
        for label in TAB_LABELS:
            candidates = [
                element
                for element in by_id[layout_id]["layout"]["elements"]
                if str(element.get("text", "")).lower() == label
                and str(element["id"]).startswith(f"{prefix}.text")
                and (element["rect"][1], element["rect"][3]) != TAB_BAND
            ]
            if len(candidates) != 1:
                raise StaticReTestFailure(
                    f"{layout_id}: expected exactly one drawn '{label}' label, "
                    f"found {len(candidates)}"
                )
            tops[label] = candidates[0]["rect"][1]
        return tops

    for layout_id, active in TAB_SELECTION.items():
        tops = _tab_label_tops(layout_id)
        expected = {
            label: TAB_RESTING_TOP[label] - (TAB_RAISE if label == active else 0.0)
            for label in TAB_LABELS
        }
        if tops != expected:
            raise StaticReTestFailure(
                f"{layout_id} tab-selection baselines drifted: {tops} "
                f"(expected {expected})"
            )

        brackets = [
            element
            for element in by_id[layout_id]["layout"]["elements"]
            if element.get("art_id") == "UI.13"
        ]
        if {element["rect"][0] for element in brackets} != BRACKET_X:
            raise StaticReTestFailure(
                f"{layout_id}: the UI.13 tab brackets moved horizontally; they "
                f"hold the same x in every tab state"
            )
        for label, (left, right) in TAB_SPAN.items():
            extents = {
                (element["rect"][1], element["rect"][3])
                for element in brackets
                if left <= element["rect"][0] < right
            }
            # Multiplayer is inert: always drawn in the selected form.
            lit = label in (active, MULTIPLAYER_IS_INERT)
            want = BRACKET_SELECTED if lit else BRACKET_RESTING
            if extents != {want}:
                raise StaticReTestFailure(
                    f"{layout_id}: the '{label}' brackets read {sorted(extents)}, "
                    f"expected {want} ({'selected' if lit else 'resting'} form)"
                )

        # Multiplayer is not a tab.  The other three each carry a control element
        # spanning the band; Multiplayer never does, on any screen.  A capture
        # that gave it one would mean the build changed, not that the tab strip
        # was recaptured.
        controls = {
            str(element["id"]).split(".control.")[1]
            for element in by_id[layout_id]["layout"]["elements"]
            if ".control." in str(element["id"])
        }
        if any(MULTIPLAYER_IS_INERT in control for control in controls):
            raise StaticReTestFailure(
                f"{layout_id}: Multiplayer gained a control element; the census "
                f"documents it as an inert label, not a selectable tab"
            )

    browser = by_id["dark-cloud-browser"]["layout"]["elements"]
    online = by_id["dark-cloud-online-levels"]["layout"]["elements"]
    if _strip_screen_prefix(browser, "dark-cloud-browser") != _strip_screen_prefix(
        online, "dark-cloud-online-levels"
    ):
        raise StaticReTestFailure(
            "the entry browser and the Online Levels tab no longer render "
            "identically; the census documents them as the same state"
        )

    loader = by_id["native-loader"]["layout"]["elements"]
    loader_geometry = {
        element["art_id"]: element["rect"] for element in loader
    }
    if loader_geometry != {
        "Loader.2": [601.0, 302.5, 989.0, 529.5],
        "Loader.1": [685.0, 553.0, 915.0, 607.0],
        "Loader.0": [704.0, 572.0, 896.0, 590.0],
        "Loader.3": [679.0, 541.0, 923.0, 559.0],
    }:
        raise StaticReTestFailure(
            f"the live Raptisoft loader geometry drifted: {loader_geometry}"
        )
    loading = by_id["loading-screen"]["layout"]
    if loading["stage_id"] != "materializing_participants":
        raise StaticReTestFailure("the match-loading golden stage drifted")
    if loading["progress"] != 0.92:
        raise StaticReTestFailure("the match-loading progress drifted")

    _require(
        findings,
        (
            "`MyLoader::Render` `0x005BCA40`",
            "`Loader.2`, `[601,302.5,989,529.5]`",
            "Duration is load-bound",
            "There is no minimum splash time",
            "Input cannot accelerate or dismiss it",
            "`BlockingOverlayOwnsGameplayInput()`",
            "## Screen census and layout",
            "## Not Yet Reversed",
        ),
        "native boot, splash, loading, and screen-census documentation",
    )
    return (
        "all 28 live Settlement v2 screen layouts, references, capture headers, "
        "and exact Raptisoft/loading geometry are pinned"
    )


def test_native_menu_live_transition_graph_is_pinned() -> str:
    findings = _read("docs/reverse-engineering/native-menus-and-boot.md")
    golden = _json("tests/fixtures/webgame/menu-goldens.json")
    edges = golden["navigation_graph"]["edges"]
    if golden["header"]["edge_count"] != len(EDGE_CONTRACT):
        raise StaticReTestFailure("the G11 edge-count header drifted")
    if len(edges) != len(EDGE_CONTRACT):
        raise StaticReTestFailure("a live G11 navigation edge was added or lost")

    actual: dict[str, tuple[str, str, str]] = {}
    for edge in edges:
        edge_id = edge["id"]
        actual[edge_id] = (
            edge["screen"],
            edge["trigger"],
            edge["destination"],
        )
        before_hash = edge["before"]["frame_sha256"]
        after_hash = edge["after"]["frame_sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", before_hash):
            raise StaticReTestFailure(f"{edge_id} lost its before-frame hash")
        if not re.fullmatch(r"[0-9a-f]{64}", after_hash):
            raise StaticReTestFailure(f"{edge_id} lost its after-frame hash")
        if before_hash == after_hash:
            raise StaticReTestFailure(
                f"{edge_id} does not prove a distinct destination frame"
            )
        if edge_id not in findings:
            raise StaticReTestFailure(
                f"{edge_id} is live-recorded but absent from the G11 document"
            )
    if actual != EDGE_CONTRACT:
        raise StaticReTestFailure(f"the live navigation graph drifted: {actual}")
    if not re.fullmatch(
        r"[0-9a-f]{64}", golden["header"]["navigation_recording_sha256"]
    ):
        raise StaticReTestFailure("the raw navigation recording hash is absent")
    return "all 39 live source/trigger/destination edges and frame hashes are pinned"


def test_native_menu_transition_endpoint_provenance_is_pinned() -> str:
    findings = _read("docs/reverse-engineering/native-menus-and-boot.md")
    golden = _json("tests/fixtures/webgame/menu-goldens.json")
    edges = golden["navigation_graph"]["edges"]

    observed: dict[str, tuple] = {}
    disagreed = 0
    for edge in edges:
        edge_id = edge["id"]
        sides = []
        for side, pinned_name in (("before", "screen"), ("after", "destination")):
            endpoint = edge[side]
            method = endpoint["capture_method"]
            if method == ENDPOINT_CAPTURE_AGREED:
                game_disagreed = False
            elif method == ENDPOINT_CAPTURE_DISAGREED:
                game_disagreed = True
                disagreed += 1
            else:
                raise StaticReTestFailure(
                    f"{edge_id}.{side} carries an unknown capture_method "
                    f"{method!r}; the recorder emits exactly two"
                )

            # `tagged_screen` echoes the operator's argument, so it is checked
            # against the edge's own pinned name rather than believed.
            expected_tag = ENDPOINT_TAG_EXCEPTIONS.get(
                (edge_id, side), edge[pinned_name]
            )
            if endpoint["tagged_screen"] != expected_tag:
                raise StaticReTestFailure(
                    f"{edge_id}.{side} is tagged {endpoint['tagged_screen']!r} "
                    f"but the edge's {pinned_name} is {expected_tag!r}; an "
                    f"undeclared label disagreement means the recording and the "
                    f"document no longer describe the same screen"
                )

            sides.append(
                (
                    endpoint["semantic_surface"],
                    endpoint["semantic_generation"],
                    endpoint["layout_generation"],
                    endpoint["element_count"],
                    game_disagreed,
                )
            )
        observed[edge_id] = tuple(sides)

    if observed != ENDPOINT_CONTRACT:
        drifted = sorted(
            key
            for key in set(observed) | set(ENDPOINT_CONTRACT)
            if observed.get(key) != ENDPOINT_CONTRACT.get(key)
        )
        raise StaticReTestFailure(
            f"live navigation endpoints drifted: {drifted}"
        )

    # A disagreeing endpoint had every non-art/text element deleted before the
    # snapshot was returned, so its element_count is a remnant.  Pin how many
    # endpoints are in that state: silently growing the degraded set is exactly
    # the drift this contract exists to catch.
    if disagreed != 34:
        raise StaticReTestFailure(
            f"{disagreed} endpoints were captured under a label the game "
            f"disagreed with; the recording documents 34"
        )

    _require(
        findings,
        (
            "### Provenance of the recorded screen tags",
            "`captured.screen_id = std::string(screen_id)`",
            "is not an observation",
            "only `art` and `text` elements survive",
            "34 of the 78",
        ),
        "navigation-endpoint provenance documentation",
    )
    return (
        "all 78 live endpoint surfaces/generations/counts are pinned, every "
        "operator label is reconciled against its edge, and the 34 "
        "control-stripped captures are declared"
    )


def test_designed_menu_focus_model_consumes_g14_intents() -> str:
    findings = _read("docs/reverse-engineering/native-menus-and-boot.md")
    focus = _json("webgame-contracts/menu-focus-model.json")
    intent = _json("webgame-contracts/intent-schema.json")
    golden = _json("tests/fixtures/webgame/menu-goldens.json")

    if focus["provenance"] != "DESIGN_NOT_OBSERVED":
        raise StaticReTestFailure("the focus model lost its design provenance")
    if focus["intent_ref"] != (
        "webgame-contracts/intent-schema.json#/$defs/menuNavIntent"
    ):
        raise StaticReTestFailure("the focus model no longer consumes G14")
    nav = intent["$defs"]["menuNavIntent"]
    if nav["properties"]["kind"]["const"] != "menu_nav":
        raise StaticReTestFailure("G14 menu intent kind drifted")
    if nav["properties"]["command"]["enum"] != [
        "up",
        "down",
        "left",
        "right",
        "confirm",
        "back",
        "next",
        "previous",
    ]:
        raise StaticReTestFailure("G14 menu-nav verbs drifted")
    if nav["properties"]["phase"]["enum"] != ["press", "release"]:
        raise StaticReTestFailure("G14 menu-nav phases drifted")

    screens = focus["screens"]
    focus_ids = [screen["layout_id"] for screen in screens]
    if len(focus_ids) != len(set(focus_ids)) or set(focus_ids) != set(
        LAYOUT_IDS
    ):
        raise StaticReTestFailure(f"the focus-screen census drifted: {focus_ids}")
    if set(focus_ids) != set(golden["screen_census"]):
        raise StaticReTestFailure("focus and live layout censuses disagree")
    for screen in screens:
        if screen["provenance"] != "DESIGN_NOT_OBSERVED":
            raise StaticReTestFailure(
                f"{screen['layout_id']} is not explicitly marked as design"
            )
        for field in (
            "strategy",
            "focus_order",
            "default_focus",
            "wrap",
            "back",
        ):
            if field not in screen:
                raise StaticReTestFailure(
                    f"{screen['layout_id']} is missing focus field {field}"
                )
    modal = focus["modal_policy"]
    if modal != {
        "provenance": "DESIGN_NOT_OBSERVED",
        "trap_focus": True,
        "restore_invoker_focus_on_close": True,
        "block_underlay_navigation": True,
        "back": (
            "Invoke the modal cancel action when one exists; otherwise ignore "
            "back unless the modal explicitly declares a safe primary dismissal."
        ),
    }:
        raise StaticReTestFailure("the designed modal focus contract drifted")

    if findings.count("**DESIGN — NOT OBSERVED**") < len(LAYOUT_IDS):
        raise StaticReTestFailure(
            "the Markdown focus rows are not individually marked as design"
        )
    _require(
        findings,
        (
            "## Focus — designed controller navigation",
            "[`menuNavIntent`]",
            "`up`, `down`, `left`, `right`, `confirm`, `back`",
            "`next`, and `previous`",
            "a modal traps focus",
            "It does not leak to",
        ),
        "designed focus documentation",
    )
    return (
        "all 28 designed-not-observed focus orders/defaults/wrap/back rules "
        "consume G14 menu_nav without a competing intent schema"
    )
