"""Static contracts for the G11 native boot/menu shell reconstruction."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
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
    importer_launcher = recorders[
        "scripts/Import-NativeMenuSpecialCaptures.ps1"
    ]
    importer = _read("tools/import_native_menu_special_captures_v25.py")
    support = _read("scripts/NativeMenuCaptureSupport.ps1")
    dark_cloud_rows = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "label_resolution_and_frame_render.inl"
    )
    debug_ui_ini = _read("config/debug-ui.ini")
    debug_ui_header = _read("SolomonDarkModLoader/include/debug_ui_config.h")
    debug_ui_parser = _read("SolomonDarkModLoader/src/debug_ui_config.cpp")
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

    legacy_dark_cloud_capacity_probe = "\n".join(
        (dark_cloud_rows, debug_ui_ini, debug_ui_header, debug_ui_parser)
    )
    for forbidden in (
        "dark_cloud_browser_list_widget_entry_count_offset",
        "dark_cloud_browser_list_widget_row_data_base_offset",
        "probed_content_count",
    ):
        if forbidden in legacy_dark_cloud_capacity_probe:
            raise StaticReTestFailure(
                "Dark Cloud row census again trusts pointer-probed widget "
                "capacity instead of the browser's native +0x1E0 entry count"
            )
    _require_regex(
        debug_ui_ini,
        r"^dark_cloud_browser_entry_count_offset=0x1E0$",
        "Dark Cloud row census again trusts pointer-probed widget capacity "
        "instead of the browser's native +0x1E0 entry count",
    )
    _require_regex(
        debug_ui_header,
        r"size_t dark_cloud_browser_entry_count_offset = 0;",
        "Dark Cloud row census again trusts pointer-probed widget capacity "
        "instead of the browser's native +0x1E0 entry count",
    )
    _require_regex(
        debug_ui_parser,
        r'\{"dark_cloud_browser_entry_count_offset",\s*'
        r"&DebugUiOverlayConfig::dark_cloud_browser_entry_count_offset\}",
        "Dark Cloud row census again trusts pointer-probed widget capacity "
        "instead of the browser's native +0x1E0 entry count",
    )
    _require_regex(
        dark_cloud_rows,
        r"TryReadPlainField\(\s*"
        r"reinterpret_cast<const void\*>\(browser_address\),\s*"
        r"g_debug_ui_overlay_state\.config\."
        r"dark_cloud_browser_entry_count_offset,\s*&entry_count\);.*?"
        r"const int draw_count\s*=\s*"
        r"\(std::min\)\(\(std::max\)\(entry_count, 0\), "
        r"clamped_max_visible\);",
        "Dark Cloud row census again trusts pointer-probed widget capacity "
        "instead of the browser's native +0x1E0 entry count",
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
        r"\$candidateSamples\.Count\s+-ge\s+"
        r"\$script:NativeMenuSettleConsecutiveSamples\s+-and\s+"
        r"\$candidateSpan\s+-ge\s+"
        r"\$script:NativeMenuSettleMinimumSpanMilliseconds",
        "native-menu Settlement v2.5 constants are declared but no longer "
        "gate the rolling candidate stream",
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
        r"\s*-Context \$Context\s+`\s*-Samples @\(\$candidateSamples\).*?"
        r"\$stableStartIndex\s*=\s*\[int\]"
        r"\$classification\.stable_start_index.*?"
        r"\$stableEndIndex\s*=\s*\[int\]"
        r"\$classification\.stable_end_index.*?"
        r"animated_element_ids\s*=\s*@\(\s*"
        r"\$classification\.animated_element_ids\s*\)",
        "native-menu settlement no longer selects and carries the exact "
        "v2.5-classified rolling window into the accepted result",
    )
    _require_regex(
        support,
        r"catch \{\s*"
        r"\$classificationError\s*=\s*\[string\]\$_\.Exception\.Message.*?"
        r"if \(\$classificationError -match '\^BROKEN:'\).*?throw.*?"
        r"\$lastRejectedCandidate\s*=\s*\$classificationError.*?"
        r"last_rejected_candidate='\$lastRejectedCandidate'",
        "a rejected v2.5 lifecycle candidate no longer keeps measuring until "
        "a compliant window or the bounded STOP names the exact rejection",
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
        r"\$script:NativeMenuActionDispatchTimeoutMilliseconds\s*=\s*15000.*?"
        r"function Wait-NativeMenuActionDispatch.*?"
        r"sd\.ui\.get_action_dispatch\(\$RequestId\).*?"
        r"sd\.ui\.capture_current_layout\("
        r"\[=\[\$captureDestinationScreen\]=\]\).*?"
        r"\$lastStatus -ceq \"dispatched\".*?"
        r"\$lastStatus -ceq \"dispatching\".*?"
        r"\$dispatch\.classified_surface -ceq.*?"
        r"\$captureDestinationScreen.*?"
        r"\$dispatch\.layout_generation -ne.*?"
        r"\$SourceLayoutGeneration.*?"
        r"\$lastStatus -ceq \"failed\".*?"
        r"never became.*?runnable",
        "native-menu semantic actions no longer distinguish queued or busy "
        "requests, exact-surface blocking modals, completed dispatch, and "
        "terminal dispatch failure",
    )
    _require_regex(
        transition_recorder,
        r"sd\.ui\.activate_action.*?"
        r"Wait-NativeMenuActionDispatch\s*`\s*"
        r"-Context \$context\s*`\s*"
        r"-RequestId \$requestId\s*`\s*"
        r"-ActionId \$ActionId\s*`\s*"
        r"-SourceLayoutGeneration \$before\.layout_generation\s*`\s*"
        r"-ExpectedDestinationScreen \$DestinationScreen.*?"
        r"\$after\s*=\s*Get-SettledNativeMenuObservation",
        "native-menu transition endpoints can settle before their queued "
        "semantic action dispatches or reaches its exact blocking-modal surface",
    )
    _require_regex(
        support,
        r"function Test-NativeMenuFrameMatchesSettlement.*?"
        r"\$FrameProbe\.SemanticSurface -cne.*?"
        r"\$Settlement\.AnchorProbe\.SemanticSurface.*?"
        r"\$FrameProbe\.SemanticGeneration -ne.*?"
        r"\$Settlement\.AnchorProbe\.SemanticGeneration.*?"
        r"FrameProbe\.SemanticPayload\.generation -ne.*?"
        r"Settlement\.Layout\.generation",
        "post-window frame capture is no longer bound to the same semantic "
        "surface and both measured generations",
    )
    _require_regex(
        support,
        r"throw \(\s*\"STOP: '\$ScreenId' never satisfied Settlement v2\.9 "
        r"across at least \".*?\"40 samples spanning two seconds within 60 "
        r"seconds\. \"",
        "a native-menu surface that never satisfies Settlement v2.9 is no "
        "longer a bounded STOP finding",
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
        r'foreach \(\$field in @\(\s*"base_commit_sha",\s*'
        r'"source_tree_sha",\s*"game_executable_sha256",\s*'
        r'"loader_dll_sha256"\s*\)\).*?'
        r"primary\.header\.source\.\$field\s+-cne\s+"
        r"\[string\]\$context\.Source\.\$field.*?"
        r"Get-SettledNativeMenuObservation.*?"
        r"\$rawSetsMatchNoncontractual\s*=\s*\$primaryIdsJson\s+-ceq\s+"
        r"\$confirmationIdsJson.*?"
        r"settlement\s*=\s*\$observation\.settlement.*?"
        r"raw_sets_match_noncontractual\s*=\s*"
        r"\$rawSetsMatchNoncontractual.*?"
        r"requires_campaign_resolution\s*=\s*\$true",
        "animation confirmation no longer proves a fresh instance/process, "
        "identical machine provenance, or labels raw-set equality noncontractual",
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
        r"\$observedSpanMilliseconds\s*=\s*0L.*?"
        r"while \(\s*\$observedSpanMilliseconds\s+-lt\s*"
        r"\$requiredSpanMilliseconds\s+-or\s*\$samples\.Count\s+-lt\s*"
        r"\$script:NativeMenuExtendedMinimumSamples\s*\).*?"
        r"\$observedSpanMilliseconds\s*=\s*\[long\]\(\s*"
        r"\$samples\[\$samples\.Count - 1\]\.elapsed_milliseconds\s*-\s*"
        r"\$samples\[0\]\.elapsed_milliseconds\s*\).*?"
        r"Invoke-NativeMenuExtendedObservationClassifier",
        "the v2.3 corroboration recorder no longer derives 60-second/10x "
        "duration from the stationary window, measures that span between "
        "actual samples, and requires at least 200 samples",
    )
    _require_regex(
        support,
        r"NativeMenuExtendedPerSampleBudgetMilliseconds\s*=\s*1000",
        "extended observation timeout again budgets only elapsed span and can "
        "STOP before the independent 200-sample census",
    )
    _require_regex(
        motion_recorder,
        r"sampleCensusDeadlineMilliseconds\s*=\s*\(\s*"
        r"\[long\]\$script:NativeMenuExtendedMinimumSamples\s*\*\s*"
        r"\[long\]\$script:NativeMenuExtendedPerSampleBudgetMilliseconds\s*"
        r"\).*?deadlineMilliseconds\s*=\s*\[Math\]::Max\(\s*"
        r"\$requiredSpanMilliseconds\s*\+\s*"
        r"\[long\]\$script:NativeMenuSettleTimeoutMilliseconds,\s*"
        r"\$sampleCensusDeadlineMilliseconds\s*\).*?"
        r'"samples=\$\(\$samples\.Count\) "',
        "extended observation timeout again budgets only elapsed span and can "
        "STOP before the independent 200-sample census",
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
        r"def derive_git_provenance\(.*?"
        r"git_text\(repo_root, \"rev-parse\", \"HEAD\"\).*?"
        r"git_text\(repo_root, \"rev-parse\", \"HEAD\^\{tree\}\"\).*?"
        r"git_text\(repo_root, \"status\", \"--porcelain\", "
        r"\"--untracked-files=no\"\).*?"
        r"def derive_binary_source\(.*?"
        r"\"SolomonDark\.exe\".*?\"SolomonDarkModLoader\.dll\".*?"
        r"game_hash = sha256_file\(executable\).*?"
        r"loader_hash = sha256_file\(loader\).*?"
        r"game_entry\.get\(\"sha256\"\) != game_hash.*?"
        r"loader_entry\.get\(\"sha256\"\) != loader_hash",
        "special menu capture import no longer derives its own Git and binary "
        "provenance",
    )
    _require_regex(
        importer,
        r"primary_classification = find_ambient_settled_window\(primary_samples\).*?"
        r"confirmation_classification = "
        r"find_ambient_settled_window\(confirmation_samples\).*?"
        r"validate_recorded_settlement\(.*?primary.*?"
        r"validate_recorded_settlement\(.*?confirmation",
        "native-loader/loading import no longer reclassifies and revalidates "
        "both complete fresh-instance sample streams",
    )
    _require_regex(
        importer,
        r"def settlement_summary\(.*?"
        r"\"settlement_spec\".*?\"structural_element_order\".*?"
        r"\"consecutive_structural_samples\".*?\"structural_sha256\"",
        "native-loader/loading import carries no v2.5 canonical-order receipt "
        "from its reclassified sample streams into fixture headers",
    )
    _require_regex(
        importer,
        r"def settled_samples\(.*?len\(result\) < 40.*?"
        r"def write_trace\(.*?"
        r"solomon-dark-native-menu-settlement-trace-v3.*?"
        r"\"settled_window_samples\": copy\.deepcopy\(window\).*?"
        r"def confirmation_value\(.*?"
        r"solomon-dark-native-menu-animation-confirmation-v4.*?"
        r"\"settled_window_samples\": copy\.deepcopy\(window\).*?"
        r"def import_surface\(.*?"
        r"primary_header\[\"settlement_trace\"\] = write_trace\(.*?"
        r"confirmation = confirmation_value\(.*?"
        r"primary_header\[\"animation_confirmation\"\]",
        "native loader/loading import no longer emits real standardized raw "
        "windows and paired confirmations for campaign-wide v2.5 resolution",
    )
    _require_regex(
        importer,
        r"def assert_independent_pair\(.*?"
        r"primary\[\"instance\"\] == confirmation\[\"instance\"\].*?"
        r"primary\[\"process_id\"\] == confirmation\[\"process_id\"\].*?"
        r"canonical_bytes\(primary\[\"source\"\]\) != "
        r"canonical_bytes\(confirmation\[\"source\"\]\).*?"
        r"assert_independent_pair\(primary_header, confirmation_header, label\).*?"
        r"label=\"native_loader\".*?label=\"loading_screen\"",
        "native loader/loading import no longer requires two independent "
        "fresh instances with identical machine-derived provenance per surface",
    )
    _require_regex(
        importer_launcher,
        r"\$LoaderPrimaryCapturePath.*?\$LoaderConfirmationCapturePath.*?"
        r"\$LoadingPrimaryCapturePath.*?\$LoadingConfirmationCapturePath.*?"
        r"import PIL; print\('native-menu-special-import-ready'\).*?"
        r"& py\.exe -3 \$importer.*?"
        r"--loader-primary \$LoaderPrimaryCapturePath.*?"
        r"--loader-confirmation \$LoaderConfirmationCapturePath.*?"
        r"--loading-primary \$LoadingPrimaryCapturePath.*?"
        r"--loading-confirmation \$LoadingConfirmationCapturePath",
        "the special-capture launcher no longer proves its real importer runs "
        "or supplies both required fresh-instance pairs",
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
        r"g_native_boot_capture_samples\.back\(\)\.progress\s*>=\s*1\.0.*?"
        r"deadline\s*=\s*GetTickCount64\(\)\s*\+\s*60000.*?"
        r"while \(!g_native_boot_capture_settled.*?"
        r"Sleep\(50\).*?CaptureNativeLoaderSample\(\).*?"
        r"STOP: native loader never satisfied",
        "native-loader capture no longer holds and settle-samples the real "
        "full-progress render or bounds failure as STOP",
    )
    _require_regex(
        loading_capture,
        r"if \(!IsProcessClientPresentationViewport\(\*layout\)\) \{\s*"
        r"return;\s*\}\s*CaptureLoadingScreenEvidenceFrameInternal",
        "loading-screen capture no longer rejects offscreen render targets "
        "before they can reset settlement",
    )
    _require_regex(
        loading_capture,
        r"IsProcessClientPresentationViewport\(\*layout\).*?"
        r"CaptureLoadingScreenEvidenceFrameInternal\(\s*"
        r"snapshot,\s*\*layout\).*?"
        r"while \(!g_loading_capture_settled.*?"
        r"CaptureLoadingScreenEvidenceFrameInternal\(\s*"
        r"snapshot,\s*\*layout\)",
        "loading-screen settlement hold no longer pins the accepted client "
        "layout against concurrent offscreen last-layout replacement",
    )
    _require_regex(
        loading_capture,
        r"snapshot\.stage\s*==\s*"
        r"LoadingScreenStage::WaitingForParticipants.*?"
        r"deadline\s*=\s*GetTickCount64\(\)\s*\+\s*60000.*?"
        r"while \(!g_loading_capture_settled.*?"
        r"Sleep\(50\).*?CaptureLoadingScreenEvidenceFrameInternal\(\s*"
        r"snapshot,\s*\*layout\).*?"
        r"STOP: loading screen never satisfied",
        "loading-screen capture no longer holds and settle-samples the real "
        "final barrier or bounds failure as STOP",
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
        "apply Settlement v2.9, preserve fresh-instance raw measurements, "
        "derive long corroboration from the stationary window, read Dark "
        "Cloud row census from the native browser owner, and "
        "derive commit/tree/exact-binary provenance without operator overrides"
    )


def test_native_menu_profile_state_and_browser_tab_are_pinned() -> str:
    assert_module_runs_in_ci("test_native_menu_profile_state_and_browser_tab")
    launcher_provenance = _read(
        "SolomonDarkModLauncher/src/Launch/"
        "NativeMenuProfileStateProvenance.cs"
    )
    staged_launcher = _read(
        "SolomonDarkModLauncher/src/Launch/StagedGameLauncher.cs"
    )
    profile_python = _read("tools/native_menu_profile_state.py")
    hub_binding_generator = _read(
        "tools/derive_native_menu_hub_bindings_v213.py"
    )
    browser_python = _read("tools/native_menu_browser_tab.py")
    attributes = _read(".gitattributes")
    support = _read("scripts/NativeMenuCaptureSupport.ps1")
    baseline_writer = _read("scripts/Write-NativeMenuProfileStateBaseline.ps1")
    resolver = _read("tools/resolve_native_menu_ambient_campaign.py")
    promoter = _read("tools/promote_native_menu_recapture.py")
    aggregate_builder = _read("tools/build_native_menu_goldens_v25.py")
    special_importer = _read("tools/import_native_menu_special_captures_v25.py")

    recorder_paths = (
        "scripts/Record-NativeMenuLayout.ps1",
        "scripts/Record-NativeMenuTransition.ps1",
        "scripts/Confirm-NativeMenuLayoutAnimation.ps1",
        "scripts/Observe-NativeMenuMotionCapability.ps1",
        "scripts/Import-NativeMenuSpecialCaptures.ps1",
        "scripts/Write-NativeMenuProfileStateBaseline.ps1",
    )
    recorders = {path: _read(path) for path in recorder_paths}
    if "scripts/Record-NativeMenuLayout.ps1" not in recorders:
        raise StaticReTestFailure(
            "profile-state override census did not reach the standalone recorder"
        )
    forbidden_parameters = {
        "basecommitsha",
        "sourcetreesha",
        "gameexecutablesha256",
        "loaderdllsha256",
        "profilestate",
        "profilestateidentity",
        "profilestateidentitysha256",
        "profilestatereceipt",
        "profilestatereceiptpath",
        "profilebaseline",
        "profilebaselinemode",
    }
    for path, source in recorders.items():
        overrides = sorted(
            _powershell_parameter_names(source) & forbidden_parameters
        )
        if overrides:
            raise StaticReTestFailure(
                "native-menu profile-state provenance accepts an operator "
                f"override in {path}: {overrides}"
            )

    _require_regex(
        staged_launcher,
        r"IsolatedProfileBootstrapper\.CreateLaunchOptions\(.*?"
        r"freshInstall\);.*?"
        r"NativeMenuProfileStateProvenance\.Materialize\(\s*"
        r"stage\.StageRootPath,\s*options,\s*freshInstall,.*?\);.*?"
        r"options\s*=\s*ApplySandboxEnvironment",
        "the launcher no longer derives durable-state provenance from the "
        "fresh isolated inputs before the game process environment is built",
    )
    _require_regex(
        launcher_provenance,
        r"IdentitySchema\s*=.*?native-menu-profile-state-input-v1.*?"
        r"new StateRoot\(\s*\"stage_sandbox\".*?"
        r"new StateRoot\(\"isolated_profile\".*?"
        r"SelectMany\(ReadFiles\).*?"
        r"OrderBy\(file => file\.Root, StringComparer\.Ordinal\).*?"
        r"ThenBy\(file => file\.RelativePath, StringComparer\.Ordinal\).*?"
        r"SHA256\.HashData\(Encoding\.UTF8\.GetBytes"
        r"\(canonicalIdentityJson\)\).*?"
        r"WriteAtomic\(receiptPath, receipt\)",
        "the launcher profile identity is no longer a canonical machine hash "
        "of both durable-state roots written atomically before launch",
    )
    _require_regex(
        support,
        r"function Get-NativeMenuProfileStateProvenance.*?"
        r"native-menu-profile-state\.json.*?"
        r"native-menu-profile-state-baseline\.json.*?"
        r"native-menu-hub-bindings-v213\.json.*?"
        r"hub_new_game_two_action_v213.*?"
        r"native-menu derivation receipt mismatch.*?"
        r"function Get-NativeMenuProfileStateBinding.*?"
        r"native-menu per-binding profile-state baseline.*?"
        r"function Copy-NativeMenuProfileStateEvidence.*?"
        r"Get-FileHash.*?launch_receipt\.sha256.*?"
        r"New-NativeMenuCaptureContext.*?"
        r"Get-NativeMenuProfileStateProvenance.*?"
        r"profile_state_identity_sha256",
        "the live recorder no longer admits only the exact pristine/derived "
        "baselines, copies its launch receipt, or enforces per-binding scope",
    )
    for path in (
        "scripts/Record-NativeMenuLayout.ps1",
        "scripts/Record-NativeMenuTransition.ps1",
        "scripts/Confirm-NativeMenuLayoutAnimation.ps1",
        "scripts/Observe-NativeMenuMotionCapability.ps1",
    ):
        _require_regex(
            recorders[path],
            r"Copy-NativeMenuProfileStateEvidence.*?"
            r"profile_state\s*=\s*\$profileState",
            f"{path} no longer copies and records the machine-derived durable-state receipt",
        )
    _require_regex(
        recorders["scripts/Confirm-NativeMenuLayoutAnimation.ps1"],
        r"Get-NativeMenuProfileStateBinding.*?"
        r"profile_state_binding.*?"
        r"base_commit_sha.*?source_tree_sha.*?game_executable_sha256.*?"
        r"loader_dll_sha256.*?"
        r"hub_new_game_two_action_v213.*?"
        r"primaryRole -cne \"primary\".*?"
        r"confirmationRole -cne \"confirmation\".*?"
        r"profile_state_identity_sha256 -ceq",
        "animation confirmation no longer keeps commit/tree/binaries exact "
        "while requiring distinct pinned v2.13 derivation witness roles",
    )
    _require_regex(
        support + "\n" + recorders["scripts/Record-NativeMenuLayout.ps1"],
        r"pathDependentCore = \[ordered\]@\{.*?"
        r"parent_screen_id.*?path_qualifier.*?selector.*?"
        r"required_baseline_id.*?measured_settled_element_count.*?"
        r"fork_decision.*?"
        r"profileStateBinding\.Contains\(\"path_dependent_core\"\).*?"
        r"fixture\.header\[\"path_dependent_core\"\]",
        "the standalone recorder no longer emits exact Hub fork provenance "
        "from the machine-derived v2.13 binding contract",
    )

    _require_regex(
        baseline_writer,
        r"status\", \"--porcelain\", \"--untracked-files=no\".*?"
        r"native-menu-profile-state\.json.*?"
        r"baseline_mode.*?fresh_install.*?"
        r"source_sandbox_excluded.*?\$true.*?"
        r"retail_appdata_seeded.*?\$false.*?"
        r"@\(\$receipt\.files\)\.Count -ne 0.*?"
        r"SolomonDarkModLoader\.dll.*?Get-FileHash.*?"
        r"solomon-dark-native-menu-profile-state-baseline-v1",
        "the committed pristine baseline can be authored without a live, clean, "
        "exact-binary fresh instance",
    )
    _require_regex(
        attributes + "\n" + baseline_writer,
        r"^tests/fixtures/webgame/native-menu-profile-state-baseline\.json "
        r"text eol=lf$.*?"
        r"\(\$value \| ConvertTo-Json -Depth 20\)\.Replace\("
        r"\"`r`n\", \"`n\"\).*?\$serialized \+ \"`n\"",
        "the committed profile-state baseline no longer has identical LF bytes "
        "on Windows capture hosts and CI checkouts",
    )
    _require_regex(
        profile_python,
        r"def validate_capture_profile_state\(.*?"
        r"identity != source_identity.*?"
        r"PROFILE_MISMATCH_REASON.*?"
        r"derivation_witness_instance.*?derivation_evidence.*?"
        r"_derivation_evidence\(resolved\[\"witness\"\]\).*?"
        r"DERIVATION_MISMATCH_REASON.*?"
        r"required_baseline_id.*?PER_BINDING_MISMATCH_REASON.*?"
        r"_resolve_unique_receipt\(.*?"
        r"receipt_path\.stat\(\)\.st_size != expected_bytes.*?"
        r"sha256_file\(receipt_path\) != expected_sha256",
        "the offline durable-state verifier can accept a foreign identity, "
        "wrong binding, false derivation receipt, ambiguity, or false receipt hash",
    )
    _require_regex(
        hub_binding_generator,
        r"def derive\(.*?"
        r"decision\"\) != \"CASE_A\".*?"
        r"historical_hub_new_game_equal.*?"
        r"isolated_two_field_replay_equal.*?"
        r"any\(value != pristine_values\[0\].*?"
        r"any\(.*?value != derived_values\[0\].*?"
        r"v212_exact.*?v213_exact.*?"
        r"historical_exact != v213_exact.*?"
        r"content-vindication consequence.*?"
        r"witness_specs.*?primary.*?confirmation.*?"
        r"evidence_receipt\(.*?"
        r"copied_profile_state_forbidden.*?"
        r"hub_pristine_second_new_game.*?"
        r"hub_new_game_two_action_v213",
        "the v2.12/v2.13 Hub contract is no longer derived from both exact "
        "fresh/derived instance pairs and the accepted content-vindication audit",
    )
    _require_regex(
        resolver,
        r"def _validate_profile_state\(.*?"
        r"return validate_capture_profile_state\(.*?"
        r"def collect_standalones\(.*?"
        r"profile_state\s*=\s*_validate_profile_state\(",
        "the resolver no longer calls its profile-state verifier at the "
        "standalone fixture boundary",
    )
    _require_regex(
        promoter,
        r"def _validate_profile_state_v25\(.*?"
        r"return validate_capture_profile_state\(.*?"
        r"def validate_settlement_fixture_v25\(.*?"
        r"profile_state\s*=\s*_validate_profile_state_v25\(",
        "the promoter no longer calls its profile-state verifier at the "
        "settled fixture boundary",
    )
    _require_regex(
        aggregate_builder,
        r"def validate_fixture\(.*?validate_capture_profile_state\(",
        "the aggregate builder no longer validates profile-state provenance "
        "at its fixture boundary",
    )
    _require_regex(
        special_importer,
        r"def derive_binary_source\(.*?"
        r"materialize_capture_profile_state\(.*?"
        r"profile_state_identity_sha256.*?"
        r"return source, profile_state",
        "native-loader/loading imports no longer derive pristine durable-state "
        "provenance from each exact fresh stage",
    )

    _require_regex(
        support,
        r"function Get-NativeMenuCaptureSurfaceId.*?"
        r"dark_cloud_browser.*?dark_cloud_recent.*?"
        r"dark_cloud_online_levels.*?dark_cloud_my_levels.*?"
        r"return \"dark_cloud_browser\".*?"
        r"hub_new_game.*?hub_pristine_second_new_game.*?hub_resumed.*?"
        r"return \"hub\".*?return \$ScreenTag.*?"
        r"function Get-NativeMenuMachineSurfaceId.*?"
        r"create_element.*?create_discipline.*?return \"create\".*?"
        r"beta_notice.*?return \"dialog\".*?"
        r"pause_menu.*?dark_cloud_menu.*?return \"simple_menu\".*?"
        r"profile_save_select.*?return \"main_menu\".*?"
        r"dark_cloud_search.*?return \"quick_panel\".*?"
        r"dark_cloud_sort.*?dark_cloud_options.*?"
        r"dark_cloud_login_settings.*?return \"dark_cloud_browser\".*?"
        r"skill_picker.*?return \"spell_picker\".*?"
        r"hub_new_game.*?hub_pristine_second_new_game.*?hub_resumed.*?"
        r"return \"hub\".*?"
        r"function Get-NativeMenuExpectedBrowserTab.*?"
        r"\"dark_cloud_browser\" \{ return \"online_levels\" \}.*?"
        r"function Resolve-NativeMenuBrowserTabState.*?"
        r"dark_cloud_browser\.recent.*?"
        r"dark_cloud_browser\.online_levels.*?"
        r"dark_cloud_browser\.my_levels.*?"
        r"art_id -ceq \"UI\.13\".*?"
        r"\$memberIds\.Count -ne 6.*?"
        r"\$distinctTops\.Count -ne 2.*?"
        r"function Assert-NativeMenuBrowserTabAgreement.*?"
        r"STOP: native-menu browser tab agreement rejected.*?"
        r"Status = \"wrong_tab\".*?"
        r"if \(\$probe\.Status -in "
        r"@\(\"wrong_surface\", \"wrong_tab\"\)\)",
        "the recorder no longer maps logical layouts to their exact machine "
        "surface, classifies browser tabs from all six measured brackets, or "
        "fails at capture time on a wrong tab",
    )
    _require_regex(
        browser_python,
        r"ENTRY_STATE_STOP\s*=.*?pristine.*?online_levels.*?"
        r"def resolve_browser_tab\(.*?"
        r"len\(geometry_ids\) != 6.*?"
        r"len\(set\(tops\)\) != 2.*?"
        r"def validate_browser_tab\(.*?"
        r"measured\[\"measured_tab\"\] != expected.*?"
        r"receipt\.get\(\"geometry_sha256\"\) != "
        r"measured\[\"geometry_sha256\"\]",
        "offline promotion no longer remeasures the Case A browser tab or "
        "verifies the exact capture-time geometry receipt",
    )

    baseline_path = (
        ROOT / "tests/fixtures/webgame/native-menu-profile-state-baseline.json"
    )
    if not baseline_path.is_file():
        raise StaticReTestFailure(
            "the committed pristine native-menu profile-state baseline is absent"
        )
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_profile = baseline.get("profile_state")
    if not isinstance(baseline_profile, dict):
        raise StaticReTestFailure(
            "the committed pristine native-menu profile-state baseline has no payload"
        )
    baseline_identity = baseline_profile.get("profile_state_identity_sha256")
    if (
        baseline.get("schema")
        != "solomon-dark-native-menu-profile-state-baseline-v1"
        or not isinstance(baseline_identity, str)
        or re.fullmatch(r"[0-9a-f]{64}", baseline_identity) is None
        or baseline_profile.get("baseline_mode") != "fresh_install"
        or baseline_profile.get("source_sandbox_excluded") is not True
        or baseline_profile.get("retail_appdata_seeded") is not False
        or baseline_profile.get("files") != []
    ):
        raise StaticReTestFailure(
            "the committed native-menu profile-state baseline is not the "
            "machine-derived pristine Case A state"
        )

    binding_path = (
        ROOT / "tests/fixtures/webgame/native-menu-hub-bindings-v213.json"
    )
    if not binding_path.is_file():
        raise StaticReTestFailure(
            "the committed v2.12/v2.13 Hub baseline/binding contract is absent"
        )
    bindings = json.loads(binding_path.read_text(encoding="utf-8"))
    baseline_registry = bindings.get("baselines")
    hub_layouts = bindings.get("layouts")
    endpoint_bindings = bindings.get("bindings")
    if (
        bindings.get("schema")
        != "solomon-dark-native-menu-hub-bindings-v213"
        or bindings.get("settlement_spec") != "2.13"
        or bindings.get("baseline_legitimacy", {}).get(
            "copied_profile_state_forbidden"
        )
        is not True
        or not isinstance(baseline_registry, dict)
        or set(baseline_registry)
        != {"pristine_fresh_install", "hub_new_game_two_action_v213"}
        or not isinstance(hub_layouts, dict)
        or set(hub_layouts)
        != {
            "hub_resumed",
            "hub_pristine_second_new_game",
            "hub_new_game",
        }
        or not isinstance(endpoint_bindings, list)
        or len(endpoint_bindings) != 6
    ):
        raise StaticReTestFailure(
            "the committed v2.12/v2.13 contract is not the exact two-baseline, "
            "three-layout, six-binding boundary"
        )
    fresh_contract = baseline_registry["pristine_fresh_install"]
    fresh_fixture_receipt = fresh_contract.get("fixture")
    if not isinstance(fresh_fixture_receipt, dict):
        raise StaticReTestFailure(
            "the v2.13 registry lost its committed pristine baseline receipt"
        )
    assert_recorded_hash_matches_file(
        str(fresh_fixture_receipt.get("sha256", "")),
        baseline_path,
        "v2.13 pristine baseline registry",
    )
    if (
        fresh_contract.get("profile_state_identity_sha256") != baseline_identity
        or fresh_fixture_receipt.get("bytes") != baseline_path.stat().st_size
        or fresh_fixture_receipt.get("repo_relative_path")
        != "tests/fixtures/webgame/native-menu-profile-state-baseline.json"
    ):
        raise StaticReTestFailure(
            "the v2.13 registry records false pristine baseline identity or bytes"
        )
    derived_witnesses = baseline_registry["hub_new_game_two_action_v213"].get(
        "witnesses"
    )
    if (
        not isinstance(derived_witnesses, list)
        or len(derived_witnesses) != 2
        or {witness.get("role") for witness in derived_witnesses}
        != {"primary", "confirmation"}
        or len(
            {
                witness.get("profile_state_identity_sha256")
                for witness in derived_witnesses
            }
        )
        != 2
    ):
        raise StaticReTestFailure(
            "the v2.13 derived baseline does not pin two independent witness identities"
        )
    for layout_id in (
        "hub_pristine_second_new_game",
        "hub_new_game",
    ):
        layout_contract = hub_layouts[layout_id]
        digest = layout_contract.get("resolved_semantic_multiset_sha256")
        members = layout_contract.get("resolved_semantic_multiset")
        measured_count = layout_contract.get("measured_settled_element_count")
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(members, list)
            or len(members) != measured_count
        ):
            raise StaticReTestFailure(
                f"the exact {layout_id} complete semantic multiset is not pinned"
            )
        measured_digest = hashlib.sha256(
            json.dumps(
                members, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        if measured_digest != digest:
            raise StaticReTestFailure(
                f"the exact {layout_id} semantic multiset digest is false"
            )

    fixture_paths = sorted(
        (ROOT / "tests/fixtures/webgame/menu-layouts").glob("*.json")
    ) + sorted(
        (ROOT / "tests/fixtures/webgame/menu-transition-layouts").glob("*.json")
    )
    expected_paths = {
        f"menu-layouts/{layout_id}.json" for layout_id in LAYOUT_IDS
    } | {
        "menu-transition-layouts/hub_new_game.json",
        "menu-transition-layouts/hub_pristine_second_new_game.json",
        "menu-transition-layouts/hub_resumed.json",
    }
    actual_paths = {
        f"{path.parent.name}/{path.name}" for path in fixture_paths
    }
    if actual_paths != expected_paths:
        raise StaticReTestFailure(
            "profile-state fixture sweep did not reach the exact 31-layout corpus: "
            f"missing={sorted(expected_paths - actual_paths)} "
            f"extra={sorted(actual_paths - expected_paths)}"
        )
    if "menu-layouts/dark-cloud-browser.json" not in actual_paths:
        raise StaticReTestFailure(
            "profile-state fixture sweep did not reach the Case A browser witness"
        )
    reached_layouts: set[str] = set()
    for path in fixture_paths:
        layout_id = path.stem
        reached_layouts.add(layout_id)
        fixture = json.loads(path.read_text(encoding="utf-8"))
        header = fixture.get("header")
        profile_state = (
            header.get("profile_state") if isinstance(header, dict) else None
        )
        source = header.get("source") if isinstance(header, dict) else None
        if not isinstance(profile_state, dict) or not isinstance(source, dict):
            raise StaticReTestFailure(
                f"{path.name} does not carry machine-derived durable-state provenance"
            )
        required_baseline_id = (
            hub_layouts.get(layout_id, {}).get(
                "required_baseline_id", "pristine_fresh_install"
            )
        )
        allowed_identities = (
            {baseline_identity}
            if required_baseline_id == "pristine_fresh_install"
            else {
                witness["profile_state_identity_sha256"]
                for witness in derived_witnesses
            }
        )
        if (
            profile_state.get("baseline_id") != required_baseline_id
            or profile_state.get("profile_state_identity_sha256")
            not in allowed_identities
            or source.get("profile_state_identity_sha256")
            != profile_state.get("profile_state_identity_sha256")
        ):
            raise StaticReTestFailure(
                f"{path.name} does not bind its exact qualified profile-state identity"
            )
        recorded_baseline = profile_state.get("baseline_fixture")
        if not isinstance(recorded_baseline, dict):
            raise StaticReTestFailure(
                f"{path.name} does not name the committed profile-state baseline"
            )
        expected_baseline_path = (
            baseline_path
            if required_baseline_id == "pristine_fresh_install"
            else binding_path
        )
        assert_recorded_hash_matches_file(
            str(recorded_baseline.get("sha256", "")),
            expected_baseline_path,
            f"{path.name} profile-state baseline",
        )
        if recorded_baseline.get("bytes") != expected_baseline_path.stat().st_size:
            raise StaticReTestFailure(
                f"{path.name} records a false profile-state baseline byte count"
            )
        recorded_binding = profile_state.get("binding_contract")
        if not isinstance(recorded_binding, dict):
            raise StaticReTestFailure(
                f"{path.name} does not name the committed per-binding contract"
            )
        assert_recorded_hash_matches_file(
            str(recorded_binding.get("sha256", "")),
            binding_path,
            f"{path.name} per-binding baseline contract",
        )
        if recorded_binding.get("bytes") != binding_path.stat().st_size:
            raise StaticReTestFailure(
                f"{path.name} records a false per-binding contract byte count"
            )
        profile_binding = header.get("profile_state_binding")
        if (
            not isinstance(profile_binding, dict)
            or profile_binding.get("baseline_id") != required_baseline_id
            or profile_binding.get("layout_id") != layout_id
        ):
            raise StaticReTestFailure(
                f"{path.name} does not explicitly record its per-layout baseline binding"
            )
    if "hub_pristine_second_new_game" not in reached_layouts:
        raise StaticReTestFailure(
            "profile-state fixture sweep did not reach the v2.12 Hub witness"
        )

    menu_goldens_path = ROOT / "tests/fixtures/webgame/menu-goldens.json"
    menu_goldens = json.loads(menu_goldens_path.read_text(encoding="utf-8"))
    aggregate_baseline = menu_goldens.get("header", {}).get(
        "profile_state_baseline"
    )
    if not isinstance(aggregate_baseline, dict):
        raise StaticReTestFailure(
            "menu-goldens does not bind the committed pristine profile-state baseline"
        )
    assert_recorded_hash_matches_file(
        str(aggregate_baseline.get("sha256", "")),
        baseline_path,
        "menu-goldens profile-state baseline",
    )
    if (
        aggregate_baseline.get("bytes") != baseline_path.stat().st_size
        or aggregate_baseline.get("profile_state_identity_sha256")
        != baseline_identity
    ):
        raise StaticReTestFailure(
            "menu-goldens records false pristine profile-state baseline provenance"
        )
    aggregate_bindings = menu_goldens.get("header", {}).get(
        "profile_state_bindings"
    )
    if not isinstance(aggregate_bindings, dict):
        raise StaticReTestFailure(
            "menu-goldens does not bind the committed v2.13 baseline registry"
        )
    assert_recorded_hash_matches_file(
        str(aggregate_bindings.get("sha256", "")),
        binding_path,
        "menu-goldens v2.13 baseline registry",
    )
    if (
        aggregate_bindings.get("bytes") != binding_path.stat().st_size
        or aggregate_bindings.get("baseline_ids")
        != sorted(baseline_registry)
    ):
        raise StaticReTestFailure(
            "menu-goldens records false v2.13 baseline registry bytes or census"
        )

    return (
        "launcher and recorders derive only exact legitimate durable-state "
        "identities with no override path; all 31 layouts and menu-goldens "
        "hash-check their per-binding baseline; Dark Cloud tabs remain measured"
    )


def test_native_menu_browser_tab_measurement_records_are_aggregable() -> str:
    assert_module_runs_in_ci("test_native_menu_layout_capture_contract")
    support = _read("scripts/NativeMenuCaptureSupport.ps1")
    layout_capture = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "menu_layout_capture_snapshot_and_hooks.inl"
    )
    search_builder = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "label_resolution_and_frame_render.inl"
    )
    exact_text_capture = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/exact_text_capture/"
        "capture_session.inl"
    )
    panel_controls = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "control_observers_menu_and_panel_capture.inl"
    )
    _require_regex(
        support,
        r"function Resolve-NativeMenuBrowserTabState.*?"
        r"\$measurements\.Add\(\[pscustomobject\]\[ordered\]@\{.*?"
        r"bracket_top\s*=\s*\[double\]\$leftRect\[1\].*?"
        r"\$measurements \| Measure-Object -Property bracket_top -Minimum",
        "browser-tab geometry measurements are no longer typed records that "
        "Windows PowerShell can aggregate before enforcing the selected tab",
    )
    _require_regex(
        layout_capture,
        r'contains_text\("item 1"\)\s*&&\s*'
        r'has_art\("ControlPanel\.0"\).*?'
        r'return "dark_cloud_login_settings";',
        "My Levels can no longer keep its browser identity when roster text "
        "shares Item 1 with the ControlPanel-backed login modal",
    )
    if '{"item 1", "dark_cloud_login_settings"}' in layout_capture:
        raise StaticReTestFailure(
            "My Levels is again misclassified as login settings from shared "
            "roster text without the measured modal-art witness"
        )
    _require_regex(
        exact_text_capture,
        r"TryGetActiveMyQuickPanel\(&quick_panel_address\).*?"
        r"!capture\.label\.empty\(\).*?"
        r"capture\.surface_id\s*=\s*\"quick_panel\".*?"
        r"owned_object_address != 0.*?widget_object != 0",
        "active QuickPanel text can no longer reach the semantic search "
        "builder when the optional widget-owner lookup misses live controls",
    )
    _require_regex(
        search_builder,
        r"if \(name_field == nullptr \|\| search_now_button == nullptr\).*?"
        r"build_element\(\*name_field.*?"
        r"if \(author_field != nullptr\).*?"
        r"build_element\(\*search_now_button",
        "the guest Dark Cloud search panel is no longer classified from its "
        "measured NAME and SEARCH NOW witnesses with AUTHOR remaining optional",
    )
    _require_regex(
        panel_controls,
        r"void ObserveQuickPanelRectDispatch\(.*?"
        r"TryGetActiveMyQuickPanel\(&quick_panel_address\).*?"
        r"TryReadQuickPanelPanelRect\(.*?"
        r"PointInsideRect\(center_x, center_y, panel_left, panel_top, "
        r"panel_right, panel_bottom\)",
        "QuickPanel controls no longer classify from measured in-panel draw "
        "geometry when synthetic widget ownership is unavailable",
    )
    rect_dispatch = re.search(
        r"void ObserveQuickPanelRectDispatch\((.*?)\n\}",
        panel_controls,
        re.DOTALL,
    )
    if rect_dispatch is None:
        raise StaticReTestFailure(
            "QuickPanel rect-dispatch classifier body went unchecked"
        )
    if "IsQuickPanelOwnedObject" in rect_dispatch.group(1):
        raise StaticReTestFailure(
            "QuickPanel in-panel draw classification again depends on the "
            "invalid synthetic widget-owner relation"
        )
    _require_regex(
        layout_capture,
        r"ResolveCapturedLayoutScreenId\(.*?"
        r"std::string_view active_action_id.*?"
        r'visible_art_count\("UI\.18"\) == 2\s*&&\s*'
        r'visible_art_count\("UI\.17"\) == 12.*?'
        r'active_action_id == "dark_cloud_browser\.sort".*?'
        r'return "dark_cloud_sort".*?'
        r'active_action_id == "dark_cloud_browser\.options".*?'
        r'return "dark_cloud_options".*?'
        r"state->active_semantic_ui_action_dispatch\.active\s*&&\s*"
        r'state->active_semantic_ui_action_dispatch\.status == "dispatching".*?'
        r"active_semantic_ui_action_dispatch\.action_id.*?"
        r"ResolveCapturedLayoutScreenId\(.*?active_action_id",
        "blocking Dark Cloud Sort and Options panels can no longer require "
        "both their active native action identity and exact measured modal "
        "chrome before replacing the unobscured browser classification",
    )
    _require_regex(
        support,
        r"function Get-NativeMenuMachineSurfaceId.*?"
        r'"dark_cloud_sort"\s*\{\s*return "dark_cloud_sort"\s*\}.*?'
        r'"dark_cloud_options"\s*\{\s*return "dark_cloud_options"\s*\}',
        "blocking Dark Cloud Sort and Options classifications can no longer "
        "be collapsed back to the unobscured browser while their native "
        "action dispatch remains inside the modal loop",
    )
    return (
        "browser-tab geometry is aggregated from typed measured records and "
        "shared roster text cannot masquerade as the login modal; the guest "
        "search panel resolves from live in-panel text and draw witnesses; "
        "blocking Sort and Options require active native actions plus exact "
        "modal chrome and retain their classified identities through dispatch"
    )


def test_native_menu_hall_layout_retention_is_native_owner_bounded() -> str:
    assert_module_runs_in_ci("test_native_menu_layout_capture_contract")
    layout_snapshot = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "menu_layout_capture_snapshot_and_hooks.inl"
    )
    tracked_surfaces = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "tracked_surfaces_and_main_menu.inl"
    )
    capture_session = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/exact_text_capture/"
        "capture_session.inl"
    )
    _require_regex(
        layout_snapshot,
        r"bool TryReadCurrentHallOfFameController\(.*?"
        r'"application_global".*?'
        r'"application_hall_of_fame_offset".*?'
        r'"hall_of_fame_vftable".*?'
        r"TryReadResolvedGamePointer\(application_global, &application\).*?"
        r"TryReadPointerValueDirect\(\s*application \+ hall_of_fame_offset,.*?"
        r"TryReadPointerField\(.*?hall_of_fame.*?&object_vftable\).*?"
        r"object_vftable != expected_vftable.*?"
        r"snapshot\.elements\.empty\(\) &&\s*"
        r'state->latest_layout_snapshot\.screen_id == "hall_of_fame" &&\s*'
        r"TryReadCurrentHallOfFameController\(&hall_of_fame\)\) \{\s*"
        r"return;\s*\}\s*"
        r"state->latest_layout_snapshot = std::move\(snapshot\);",
        "the one-shot Hall renderer can no longer retain its last measured "
        "layout only while the exact native controller and vtable remain active",
    )
    _require_regex(
        tracked_surfaces,
        r"bool TryGetCurrentHallOfFame\(.*?"
        r"TryReadCurrentHallOfFameController\(hof_address\).*?return true;.*?"
        r"kTrackedHallOfFameMaximumIdleMs.*?return false;",
        "Hall surface ownership no longer prefers the durable validated "
        "controller before its bounded render-transition fallback",
    )
    _require_regex(
        capture_session,
        r'\{"hall_of_fame",\s*"Hall of Fame",\s*'
        r"&TryGetCurrentHallOfFame\}",
        "Hall exact-text capture no longer uses the durable native owner, so "
        "the one-shot title frame cannot become a retained semantic layout",
    )
    return "Hall layout retention is bounded by the exact live native owner"


def test_native_menu_capture_surface_agreement_is_fail_closed() -> str:
    assert_module_runs_in_ci("test_native_menu_layout_capture_contract")
    api = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "public_api_surface_dispatch.inl"
    )
    bindings = _read("SolomonDarkModLoader/src/lua_engine_bindings_ui.cpp")
    settings_builder = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "overlay_surface_builders_settings_surfaces.inl"
    )
    settings_helpers = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "overlay_surface_builders_settings_helpers.inl"
    )
    frame_registry = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "label_resolution_surface_registry_and_frame_render.inl"
    )
    binary_layout = _read("config/binary-layout.ini")
    settings_tracking = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "tracked_surfaces_and_main_menu.inl"
    )
    overlay_state = _read("SolomonDarkModLoader/src/debug_ui_overlay.cpp")
    frame_capture = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "overlay_surface_builders_misc_surfaces.inl"
    )
    action_retirement = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "state_actions_activation/resolved_action_activation.inl"
    )
    layout_snapshot = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "menu_layout_capture_snapshot_and_hooks.inl"
    )
    menu_capture_state = _read("SolomonDarkModLoader/src/debug_ui_overlay.cpp")
    menu_capture_resolvers = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "menu_layout_capture_resolvers.inl"
    )
    menu_capture_observers = _read(
        "SolomonDarkModLoader/src/debug_ui_overlay/"
        "menu_layout_capture_art_observation.inl"
    )
    support = _read("scripts/NativeMenuCaptureSupport.ps1")
    sandbox_setup = _read("mods/lua_ui_sandbox_lab/scripts/lib/setup.lua")
    click_helper = _read("scripts/Invoke-ExactProcessClientClick.ps1")
    standalone = _read("scripts/Record-NativeMenuLayout.ps1")
    transition = _read("scripts/Record-NativeMenuTransition.ps1")
    confirmation = _read("scripts/Confirm-NativeMenuLayoutAnimation.ps1")
    motion = _read("scripts/Observe-NativeMenuMotionCapability.ps1")

    _require_regex(
        support,
        r"function Assert-NativeMenuCaptureDriverQuiescent.*?"
        r"get_environment_variable\('SDMOD_UI_SANDBOX_PRESET'\).*?"
        r'if \(\$preset -cne "idle"\).*?'
        r"STOP: native-menu capture driver quiescence rejected.*?"
        r"\$captureDriverPreset\s*=\s*"
        r"Assert-NativeMenuCaptureDriverQuiescent\s+`\s*"
        r"-Context \$context.*?"
        r'\$source\["capture_driver_preset"\]\s*=\s*'
        r"\$captureDriverPreset.*?return \$context",
        "native-menu capture can run beside an autonomous UI driver instead "
        "of proving and recording the exact passive preset",
    )
    _require_regex(
        sandbox_setup,
        r'if active_preset == "native_menu_capture_idle" then\s*'
        r"return native_menu_capture_idle_steps\s*end.*?"
        r"return \{\}\s*end",
        "native-menu capture can run beside an autonomous UI driver instead "
        "of proving and recording the exact passive preset",
    )

    _require_regex(
        api,
        r"auto captured\s*=\s*"
        r"g_debug_ui_overlay_state\.latest_layout_snapshot;\s*"
        r"if \(captured\.screen_id != screen_id\) \{\s*"
        r"return false;\s*\}\s*"
        r"g_debug_ui_overlay_state\.layout_snapshots_by_screen"
        r"\[captured\.screen_id\]\s*=\s*captured;",
        "a classifier/tag mismatch can reach the accepted native layout cache",
    )
    for forbidden in (
        "classification_agrees",
        "stale controls omitted",
        "captured.screen_id = std::string(screen_id)",
    ):
        if forbidden in api:
            raise StaticReTestFailure(
                "the native layout API regained mismatch relabeling or "
                f"control stripping through {forbidden!r}"
            )
    _require_regex(
        layout_snapshot,
        r"const auto contains_text =.*?"
        r"ContainsObservedText\(exact_text_elements, expected\).*?"
        r"LowerAsciiCopy\(element\.label\)\.find\(\s*"
        r"normalized_expected\).*?"
        r"semantic_root == \"dialog\" && "
        r"contains_text\(\"beta version v\.0\.72\"\).*?"
        r"return \"beta_notice\";",
        "the capture-time classifier can no longer identify the stock beta "
        "dialog when its measured title arrives through semantic text",
    )
    _require_regex(
        layout_snapshot,
        r"ResolveCapturedLayoutScreenId\(.*?"
        r"has_action_prefix\(\"pause_menu\.\"\).*?return \"pause_menu\";.*?"
        r"has_action_prefix\(\"profile\.\"\).*?return \"dark_cloud_menu\";.*?"
        r"has_action\(\"main_menu\.resume_last_game\"\).*?"
        r"has_action\(\"main_menu\.new_game\"\).*?"
        r"has_action\(\"main_menu\.back\"\).*?"
        r"return \"profile_save_select\";",
        "the capture-time classifier can no longer distinguish pause, Dark "
        "Cloud menu, and profile-select surfaces by their measured actions",
    )
    _require_regex(
        layout_snapshot,
        r"has_art\(\"GameOver\.0\"\) && has_art\(\"GameOver\.1\"\).*?"
        r"return \"game_over\";.*?"
        r"has_art\(\"ControlPanel\.9\"\).*?return \"performance\";.*?"
        r"has_art\(\"ControlPanel\.0\"\) && "
        r"has_art\(\"ControlPanel\.18\"\).*?return \"settings\";.*?"
        r"has_art\(\"UI\.51\"\) && has_art\(\"Skills\.13\"\).*?"
        r"return \"skill_picker\";.*?"
        r"has_art\(\"LevelPicker\.3\"\).*?return \"map_picker\";",
        "art-only game-over, performance, settings, skill-picker, and "
        "map-picker layouts can no longer acquire a measured screen identity",
    )
    _require_regex(
        layout_snapshot,
        r"visible_art_count\(\"UI\.17\"\) >= 4 &&\s*"
        r"visible_art_count\(\"UI\.18\"\) >= 2 && "
        r"has_art\(\"UI\.28\"\).*?return \"dark_cloud_settings\";.*?"
        r"has_art\(\"Skills\.43\"\) && has_art\(\"UI\.42\"\) &&\s*"
        r"\(has_art\(\"LevelPicker\.0\"\) \|\| "
        r"has_art\(\"UI\.28\"\)\).*?return \"hub\";",
        "the art-only Dark Cloud settings and both Hub path states can no "
        "longer be separated by their measured native art signatures",
    )
    _require_regex(
        bindings,
        r"if \(!sdmod::TryCaptureCurrentDebugUiLayoutSnapshot\(.*?"
        r"lua_pushnil\(state\);.*?"
        r"TryGetLatestDebugUiLayoutSnapshot\(&classified\).*?"
        r"lua_setfield\(state, -2, \"classified_screen_id\"\);\s*"
        r"return 2;",
        "capture_current_layout no longer returns the measured classifier on "
        "a refused operator tag",
    )
    _require_regex(
        support,
        r"function Assert-NativeMenuCaptureSurfaceAgreement\s*\{.*?"
        r"\$captureSurface\s*=\s*Get-NativeMenuMachineSurfaceId.*?"
        r"if \(\s*\$MachineClassifiedSurface -cne \$captureSurface -and\s*"
        r"\$MachineClassifiedSurface -cne \$OperatorScreenTag\s*\) \{\s*"
        r"throw \(.*?"
        r"STOP: native-menu capture surface agreement rejected:.*?"
        r"operator tag '\$OperatorScreenTag' does not equal.*?"
        r"machine-classified surface '\$MachineClassifiedSurface'.*?"
        r"capture surface '\$captureSurface'\."
        r".*?\}\s*\}",
        "the recorder agreement gate no longer names and rejects unequal "
        "machine surface and operator tag",
    )
    _require_regex(
        support,
        r"function Resolve-NativeMenuHubPathLayoutId.*?"
        r"LevelPicker\.0.*?LevelPicker\.2.*?LevelPicker\.4.*?"
        r"LevelPicker\.5.*?LevelPicker\.6.*?UI\.28.*?"
        r"hub_pristine_second_new_game.*?"
        r"\$requiredElementCount\s*=\s*15.*?"
        r"hub_new_game.*?\$requiredElementCount\s*=\s*14.*?"
        r"hub_resumed.*?\$requiredElementCount\s*=\s*10.*?"
        r"Hub path classifier measured no exact authorized v2\.13.*?"
        r"\$elements\.Count -ne \$requiredElementCount.*?"
        r"exact authorized.*?census.*?"
        r"\$measuredHubLayout -cne \$ScreenId.*?"
        r"Hub path selector expected.*?machine-classified.*?"
        r"\$semanticPayload\.screen_id\s*=\s*\$ScreenId",
        "path-qualified Hub capture no longer proves its exact authorized "
        "member signature and census before logical retagging",
    )
    _require_regex(
        click_helper,
        r"keybd_event\(\s*0x12,\s*0,\s*0,.*?"
        r"keybd_event\(\s*0x12,\s*0,\s*0x0002,.*?"
        r"SetForegroundWindow\(\$window\).*?"
        r"\$foregroundProcessId -ne \$ProcessId.*?throw",
        "the exact-process click helper no longer releases the Windows "
        "foreground lock and proves target ownership before input",
    )
    _require_regex(
        support,
        r"type\(sd\) ~= 'table'.*?"
        r"type\(sd\.ui\) ~= 'table'.*?"
        r"type\(sd\.ui\.get_snapshot\) ~= 'function'.*?"
        r"type\(sd\.ui\.capture_current_layout\) ~= 'function'.*?"
        r"return '__NATIVE_MENU_LAYOUT_NOT_READY__'.*?"
        r"local snapshot, capture_diagnostic\s*=\s*"
        r"sd\.ui\.capture_current_layout\(\[=\[\$captureSurfaceId\]=\]\).*?"
        r"__NATIVE_MENU_LAYOUT_SURFACE_MISMATCH__=.*?"
        r"Assert-NativeMenuCaptureSurfaceAgreement.*?"
        r"catch\s*\{.*?Status = \"wrong_surface\".*?"
        r"Status = \"not_ready\".*?"
        r"exact capture snapshot.*?still populating.*?"
        r"Status = \"ready\".*?"
        r"if \(\$probe\.Status -in "
        r"@\(\"wrong_surface\", \"wrong_tab\"\)\) \{\s*"
        r"\$measuredSurface.*?"
        r"Test-NativeMenuScreenTagsEquivalent.*?"
        r"-Left \$measuredSurface.*?"
        r"-Right \$TransitionalSourceScreen.*?"
        r"\$probeKey = \(.*?\$probe\.Status.*?\$measuredSurface.*?"
        r"\$probe\.NativeGeneration.*?"
        r"\$probeKey -cne \$foreignSurfaceProbeKey.*?"
        r"if \(\s*\$consecutiveForeignSurfaceProbes -ge\s*"
        r"\$script:NativeMenuSettleConsecutiveSamples.*?"
        r"\$script:NativeMenuSettleMinimumSpanMilliseconds.*?"
        r"throw \[string\]\$probe\.Detail",
        "the live probe can treat an initializing API as broken, accept a "
        "retagged layout, lose the measured surface, or let a settled foreign "
        "surface age into the general timeout",
    )
    _require_regex(
        settings_builder,
        r"bool HasCurrentSettingsPanelArt\(.*?"
        r'"ControlPanel\.0".*?"ControlPanel\.8".*?"ControlPanel\.18".*?'
        r"element\.visible.*?element\.art_id == required_art_id.*?"
        r"TryExtractSettingsFamilyOverlayArt.*?"
        r"if \(overlay_elements == nullptr \|\|\s*"
        r"!HasCurrentSettingsPanelArt\(current_elements\)\) \{\s*"
        r"return false;\s*\}.*?"
        r"overlay_first_draw_order.*?"
        r"element\.art_id\.rfind\(\"Title\.\", 0\)",
        "Settings cached art is no longer extracted from one complete live "
        "panel suffix or can include title-backdrop draws",
    )
    _require_regex(
        settings_builder,
        r"SettingsFamilyOverlayArtCacheState.*?"
        r"settings_underlay.*?"
        r"GetCapturedMenuArtSemanticKey.*?"
        r"TryExtractControlsPageArtDifference.*?"
        r"underlay_counts.*?"
        r"element\.art_id\.rfind\(\"Title\.\", 0\) == 0\).*?continue;.*?"
        r"element\.art_id\.rfind\(\"ControlPanel\.\", 0\).*?"
        r"controls_elements->clear\(\);.*?return false;",
        "Controls cached art is no longer the non-ID/non-draw-order semantic "
        "multiset difference against its measured Settings underlay, or can "
        "include title/partial Settings draws",
    )
    semantic_key = re.search(
        r"std::string GetCapturedMenuArtSemanticKey\(.*?"
        r"return key\.str\(\);\s*\}",
        settings_builder,
        flags=re.DOTALL,
    )
    if semantic_key is None or "draw_order" in semantic_key.group(0):
        raise StaticReTestFailure(
            "Controls cached art no longer uses one draw-order-independent "
            "semantic key for measured multiset subtraction"
        )
    _require_regex(
        settings_builder,
        r"ResolveSettingsFamilyMenuArtElements.*?"
        r"cache\.settings_address != settings_address.*?"
        r"element\.draw_order = next_draw_order\+\+.*?"
        r"TryResolveSettingsRolloutPageState.*?"
        r"TryExtractControlsPageArtDifference.*?"
        r"replay_cached_overlay\(\*last_cache, settings_address\).*?"
        r"cache_state\.last_page != page_observation\.page.*?"
        r"active_cache->settings_address = settings_address;.*?"
        r"replay_cached_overlay\(\*active_cache, settings_address\)",
        "Settings-family cached page art can leak across an owner or "
        "transition, or the known source is not replayed while neither native "
        "page owns the origin",
    )
    _require_regex(
        settings_builder,
        r"if \(cache_state\.last_page != page_observation\.page &&\s*"
        r"cache_state\.transition\.settings_address == settings_address &&\s*"
        r"!cache_state\.transition\.elements\.empty\(\)\) \{\s*"
        r"active_cache->settings_address = settings_address;\s*"
        r"active_cache->elements =\s*"
        r"std::move\(cache_state\.transition\.elements\);",
        "Settings-family cached page art can leak across an owner or "
        "transition, or the known source is not replayed while neither native "
        "page owns the origin",
    )
    _require_regex(
        settings_builder,
        r"auto\* active_cache =.*?"
        r"if \(page_observation\.page == "
        r"SettingsRolloutPageState::Settings &&\s*"
        r"TryExtractSettingsFamilyOverlayArt\(",
        "an outgoing Settings ControlPanel draw can populate the Controls "
        "destination cache instead of the measured Controls page difference",
    )
    _require_regex(
        settings_builder,
        r"if \(!TryResolveSettingsRolloutPageState\(.*?"
        r"TryExtractSettingsFamilyOverlayArt\(\s*"
        r"current_elements,\s*&transition_overlay\)\) \{\s*"
        r"cache_state\.settings\.settings_address = settings_address;\s*"
        r"cache_state\.settings\.elements =\s*"
        r"std::move\(transition_overlay\);\s*"
        r"cache_state\.settings_underlay = current_elements;\s*"
        r"cache_state\.transition = CachedSettingsFamilyOverlayArt\{\};\s*"
        r"\} else if \(TryExtractControlsPageArtDifference",
        "an unresolved outgoing Settings panel can enter the destination "
        "transition cache and be adopted as Controls art",
    )
    _require_regex(
        settings_builder,
        r"if \(!TryResolveSettingsRolloutPageState\(.*?"
        r"MarkSettingsFamilyPageTransitionPending\(&cache_state\);.*?"
        r"if \(cache_state\.transition_started_at != 0 &&\s*"
        r"now - cache_state\.transition_started_at >\s*"
        r"kTrackedSettingsMaximumIdleMs\) \{\s*"
        r"Log\(\s*\"Debug UI settings-family cached page retired "
        r"after bounded unresolved transition\.\"\);\s*"
        r"clear_caches\(\);\s*"
        r"return current_elements;\s*\}.*?"
        r"replay_cached_overlay\(\*last_cache, settings_address\)",
        "an unresolved Settings-family source can mask a settled main-menu "
        "destination beyond the bounded transition window",
    )
    _require_regex(
        settings_builder + frame_registry,
        r"SettingsFamilyOverlayArtCacheState.*?"
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
        "the main-menu underlay can retire the Settings owner before a visible "
        "Controls page reaches its unique native local origin",
    )
    _require_regex(
        settings_tracking,
        r"if \(now - g_debug_ui_overlay_state\.settings_render\.captured_at > "
        r"kTrackedSettingsMaximumIdleMs\) \{\s*return false;\s*\}.*?"
        r"bool TryReadTrackedSettingsRender\(uintptr_t\* settings_address\)",
        "the idle settings probe can again erase the retained modal owner "
        "before current-frame evidence validates it",
    )
    _require_regex(
        settings_helpers,
        r"TryResolveSettingsRolloutPageState.*?"
        r"duplicate GAME SETTINGS roots.*?"
        r"duplicate CUSTOMIZE KEYBOARD roots.*?"
        r"IsSettingsRolloutPageAtLocalOrigin.*?"
        r"if \(settings_at_origin == controls_at_origin\).*?return false;.*?"
        r"SettingsRolloutPageState::Controls.*?"
        r"SettingsRolloutPageState::Settings",
        "Settings and Controls can again be selected without one unique native "
        "rollout page occupying the live local origin",
    )
    _require_regex(
        frame_registry,
        r"ResolveSettingsFamilyMenuArtElements\(\s*"
        r"TakeCapturedMenuArtFrame\(\)\)",
        "the frame classifier bypasses the owner/page-scoped Settings-family "
        "cached-art resolver",
    )
    controls_builder_match = re.search(
        r"TryBuildControlsOverlayRenderElements\(.*?"
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
        settings_builder,
        flags=re.DOTALL,
    )
    if controls_builder_match is None:
        raise StaticReTestFailure(
            "Controls classification no longer requires either the unique live "
            "native rollout page or its bounded machine-proven transition source, "
            "plus the machine-measured Back control"
        )
    if "controls.elements" in controls_builder_match.group(0):
        raise StaticReTestFailure(
            "Controls classification can again wait for unrelated one-shot art "
            "after the native Controls page is uniquely at the local origin"
        )
    _require_regex(
        binary_layout,
        r"\[surface\.controls\].*?actions=.*?controls\.back.*?"
        r"\[action\.controls\.back\]\s*"
        r"surface=controls\s*label=BACK\s*owner=0x005D9A50\s*"
        r"handler=0x005D8120\s*control_offset=0x00B8",
        "the live Controls Back widget is no longer a configured interactive "
        "action backed by the native Settings done control",
    )
    _require_regex(
        settings_builder,
        r"bool TryBuildSettingsRolloutMarkerElements\(.*?"
        r"TryReadSettingsControlPointers\(\s*config,\s*settings_address,"
        r"\s*&root_controls\).*?"
        r"IsSettingsRolloutControl\(config, root_control\).*?"
        r"if \(!TryReadCachedObjectLabel\(root_control, &label\)\) \{\s*"
        r"label = ResolveSettingsControlLabel\(config, root_control\);\s*"
        r"\}.*?"
        r"art_element\.art_id != \"ControlPanel\.0\".*?"
        r"PointInsideRect\(\s*center_x,\s*center_y,\s*panel_left,\s*"
        r"panel_top,\s*panel_right,\s*panel_bottom\).*?"
        r"rollout_rows\.size\(\) != marker_draws\.size\(\).*?"
        r"return false;.*?"
        r"element\.action_id = ResolveConfiguredUiActionId\(\s*"
        r"\"settings\",\s*row\.label\);.*?"
        r"element\.source_object_ptr = row\.control_address;.*?"
        r"element\.left = marker->left;\s*"
        r"element\.top = marker->top;\s*"
        r"element\.right = marker->right;\s*"
        r"element\.bottom = marker->bottom;.*?"
        r"TryBuildSettingsRolloutMarkerElements\(\s*\*config,\s*"
        r"settings_address,\s*surface_title,\s*panel_left,\s*panel_top,\s*"
        r"panel_right,\s*panel_bottom,\s*art_elements,\s*&render_elements\)",
        "Settings navigation can lose its unambiguous machine-measured "
        "rollout affordance and fall back to stale coordinates",
    )
    _require_regex(
        overlay_state + frame_capture,
        r"retained_settings_elements_owner.*?"
        r"retained_settings_exact_text_elements.*?"
        r"retained_settings_exact_control_elements.*?"
        r"MergeRetainedSettingsFrameElementsUnlocked.*?"
        r"settings_render\.tracked_object_ptr.*?"
        r"retained_settings_elements_owner != settings_owner.*?"
        r"source\.surface_id != \"settings\".*?continue;.*?"
        r"TakeExactTextFrameElements.*?"
        r"MergeRetainedSettingsFrameElementsUnlocked\(.*?"
        r"retained_settings_exact_text_elements",
        "one-shot settings rows can disappear before settlement or leak from "
        "a different retained settings owner",
    )
    _require_regex(
        action_retirement,
        r"RetireUiCaptureBeforeActionDispatch.*?"
        r"retained_settings_elements_owner = 0.*?"
        r"retained_settings_exact_text_elements\.clear\(\).*?"
        r"retained_settings_exact_control_elements\.clear\(\)",
        "semantic action retirement can leave one-shot settings rows attached "
        "to a retired owner",
    )
    _require_regex(
        layout_snapshot,
        r"for \(const auto& source : exact_text_elements\).*?"
        r"semantic_root.*?GetOverlaySurfaceRootId.*?"
        r"source_root.*?GetOverlaySurfaceRootId\(source\.surface_id\).*?"
        r"source_root != semantic_root.*?continue;",
        "a selected native menu layout can inherit hidden exact text from a "
        "foreign semantic surface",
    )
    _require_regex(
        menu_capture_state + menu_capture_resolvers + menu_capture_observers + layout_snapshot,
        r"SettingsActionRowFn.*?settings_action_row_hook.*?"
        r"kSettingsActionRowAddress\s*=\s*0x004A5B60.*?"
        r"HookSettingsActionRow\(.*?"
        r"BeginSettingsRowCapture\(\s*primary_label.*?"
        r"GetX86HookTrampoline<SettingsActionRowFn>.*?"
        r"original\(\s*self,\s*primary_label,\s*secondary_label,\s*"
        r"action_context\).*?"
        r"CacheObservedObjectLabel\(\s*"
        r"reinterpret_cast<uintptr_t>\(result\),\s*primary_label_text\).*?"
        r"EndSettingsRowCapture\(\).*?return result;.*?"
        r"InstallSafeX86Hook\(\s*"
        r"reinterpret_cast<void\*>\(settings_action\).*?"
        r"HookSettingsActionRow.*?settings_action_row_hook",
        "the native two-label settings action-row constructor can lose the "
        "machine-read label-to-control binding, making Customize Keyboard "
        "unavailable or geometry-free",
    )
    _require_regex(
        standalone,
        r"Get-SettledNativeMenuObservation.*?"
        r"Assert-NativeMenuCaptureSurfaceAgreement\s*`\s*"
        r"-OperatorScreenTag \$ScreenId\s*`\s*"
        r"-MachineClassifiedSurface \$observation\.semantic_surface",
        "standalone capture can persist a surface that disagrees with its tag",
    )
    _require_regex(
        confirmation,
        r"Get-SettledNativeMenuObservation.*?"
        r"Assert-NativeMenuCaptureSurfaceAgreement\s*`\s*"
        r"-OperatorScreenTag \$ScreenId\s*`\s*"
        r"-MachineClassifiedSurface \$observation\.semantic_surface",
        "fresh-instance confirmation can accept a surface/tag disagreement",
    )
    _require_regex(
        motion,
        r"Get-NativeMenuLayoutProbe.*?"
        r"Assert-NativeMenuCaptureSurfaceAgreement\s*`\s*"
        r"-OperatorScreenTag \$ScreenId\s*`\s*"
        r"-MachineClassifiedSurface \$probe\.SemanticSurface",
        "extended motion observation can accept a surface/tag disagreement",
    )
    _require_regex(
        transition,
        r"\$before\s*=\s*Get-SettledNativeMenuObservation.*?"
        r"-OperatorScreenTag \$SourceScreen.*?"
        r"-MachineClassifiedSurface \$before\.semantic_surface.*?"
        r"\$after\s*=\s*Get-SettledNativeMenuObservation.*?"
        r"-TransitionalSourceScreen \$SourceScreen.*?"
        r"-OperatorScreenTag \$DestinationScreen.*?"
        r"-MachineClassifiedSurface \$after\.semantic_surface",
        "a navigation edge can proceed without classifier agreement at both "
        "source and destination, or cannot distinguish a transient known "
        "source from wholesale surface substitution",
    )
    supplied = _powershell_parameter_names(transition)
    forbidden_overrides = {
        "expectedsourcesurface",
        "expecteddestinationsurface",
    }
    if supplied & forbidden_overrides:
        raise StaticReTestFailure(
            "navigation surface agreement again depends on an optional "
            "operator-supplied expectation"
        )
    _require_regex(
        transition,
        r"ParameterSetName = \"MeasuredClick\".*?"
        r"\$before\.layout\.elements \| Where-Object.*?"
        r"\$measuredCandidates\.Count -ne 1.*?refusing ambiguity.*?"
        r"\$measuredX\s*=.*?\$measuredRect\[0\].*?"
        r"\$measuredRect\[2\].*?/ 2\.0.*?"
        r"\$measuredY\s*=.*?\$measuredRect\[1\].*?"
        r"\$measuredRect\[3\].*?/ 2\.0.*?"
        r"dispatch_measurement = \$dispatchMeasurement",
        "the corrected click driver no longer derives and receipts one live "
        "interactive control rectangle",
    )
    _require_regex(
        transition,
        r"function Get-NativeMenuProbeProperty.*?"
        r"\$Probe\.PSObject\.Properties\[\$Name\].*?"
        r"if \(\$null -eq \$property -or \$null -eq "
        r"\$property\.Value\).*?return \$Default.*?"
        r"catch \{\s*\$failureMessage.*?"
        r"Get-NativeMenuLayoutProbe.*?-FramePath \$failureFrame.*?"
        r"\$failureReason = if.*?"
        r"native-menu capture surface agreement rejected.*?"
        r"capture_surface_did_not_match_operator_tag.*?"
        r"navigation_transition_failed_before_destination_settlement.*?"
        r"named_reason = \$failureReason.*?"
        r"click_point = \$resolvedClickPoint.*?"
        r"machine_classified_surface = Get-NativeMenuProbeProperty.*?"
        r"probe_detail = Get-NativeMenuProbeProperty.*?"
        r"frame = \$frameReceipt.*?"
        r"Navigation aborted before proceeding",
        "a navigation failure can again mask its original error by reading "
        "probe-shape-specific properties or omit its click, measured surface, "
        "frame receipt, and exact failure class",
    )
    return (
        "native layout capture refuses relabeling; standalone, confirmation, "
        "motion, and both navigation endpoints require exact classifier/tag "
        "agreement, with live-click receipts and abort diagnostics"
    )


def test_native_menu_settlement_v2_classifier_is_strict_and_ci_wired() -> str:
    assert_module_runs_in_ci("test_native_menu_settlement_v2")
    assert_module_runs_in_ci("test_native_menu_ambient_lifecycle")
    classifier = _read("tools/native_menu_ambient_lifecycle.py")
    unit_tests = _read("tests/test_native_menu_ambient_lifecycle.py")
    _require_regex(
        classifier,
        r"SETTLEMENT_SPEC\s*=\s*\"2\.9\".*?"
        r"MINIMUM_SAMPLES\s*=\s*40\b.*?"
        r"MINIMUM_SPAN_MILLISECONDS\s*=\s*2_000\b.*?"
        r"MAXIMUM_AMBIENT_FRACTION\s*=\s*0\.40\b.*?"
        r"MAXIMUM_ANIMATED_FRACTION\s*=\s*0\.30\b.*?"
        r"EXTENDED_OBSERVATION_MINIMUM_SAMPLES\s*=\s*200\b.*?"
        r"EXTENDED_OBSERVATION_MINIMUM_MILLISECONDS\s*=\s*60_000\b",
        "Settlement v2.9 sample, span, lifecycle-cap, and corroboration "
        "constants drifted from the authorized definition",
    )
    _require_regex(
        classifier,
        r"semantic_surface\s*=\s*sample\.get\("
        r"\"semantic_surface\", screen_id\).*?"
        r"if not isinstance\(semantic_surface, str\):.*?"
        r"sample has no semantic surface",
        "Settlement v2.5 no longer treats gameplay's empty semantic-surface "
        "identifier as a constant while rejecting non-string missing state",
    )
    _require_regex(
        classifier,
        r"def _measure_window\(.*?"
        r"member_class\s*=\s*\"full_presence\".*?"
        r"member_class\s*=\s*\(\s*"
        r"\"one_way_spawn_candidate\" if one_way_spawn else \"ephemeral\".*?"
        r"member_class\s*=\s*\"visibility_cycling\".*?"
        r"member_class\s*=\s*\"animated\"",
        "Settlement v2.5 no longer machine-measures full, one-way, ephemeral, "
        "visibility-cycling, and rect-animation classes",
    )
    _require_regex(
        classifier,
        r"if not _pure_art\(anchor\):.*?"
        r"membership churn on.*?text/control member.*?not classifiable.*?"
        r"if not _pure_art\(anchor\):.*?"
        r"visible variance on.*?text/control member.*?not classifiable",
        "Settlement v2.5 art-only guard no longer stops membership churn and "
        "visibility variance on text or controls",
    )
    _require_regex(
        classifier,
        r"def _core_counter_for_measurements\(.*?"
        r"common &= counter.*?"
        r"cross-instance structural core inequality.*?"
        r"def _project_core_sequence\(.*?"
        r"structural core member disappeared.*?"
        r"structural core relative-order.*?flip",
        "Settlement v2.5 no longer intersects cross-instance semantic cores "
        "and rejects a missing member or relative-order flip",
    )
    _require_regex(
        classifier,
        r"varying_member_keys,\s*cross_window_rect_events\s*=\s*"
        r"_resolve_varying_member_keys\(\s*"
        r"measurements, ambient_family, animated_family_keys\s*\).*?"
        r"motion capability resolution requires extended-observation.*?evidence.*?"
        r"classification == \"full_presence\".*?varying_key is None.*?"
        r"phantom animated.*?zero events",
        "Settlement v2.5 no longer applies asymmetric motion capability, "
        "requires stationary-side corroboration, and rejects phantom classes",
    )
    _require_regex(
        classifier,
        r"def _core_bands\(.*?"
        r"lower_id\s*=.*?\"bottom\".*?"
        r"upper_id\s*=\s*\"top\".*?"
        r"ambient draw-band cross-instance contract.*?"
        r"lacks two independent.*?instance witnesses.*?"
        r'"draw_bands": bands\[.*?'
        r"draw_order_semantics\": \"structural_core_relative_sequence\"",
        "Settlement v2.5 no longer excludes absolute draw ordinals while "
        "pinning core-relative sequence and ambient draw bands",
    )
    _require_regex(
        classifier,
        r"ephemeral family lacks.*?bidirectional spawn and despawn.*?"
        r"ambient_fraction\s*=\s*ambient_units / peak_census.*?"
        r"if ambient_fraction > maximum_ambient_fraction:.*?"
        r"ambient lifecycle cap exceeded.*?exceeds 40%",
        "Settlement v2.5 no longer enforces the semantic 40-percent cap and "
        "family-wide bidirectional ephemeral witness",
    )
    _require_regex(
        classifier,
        r"\"anchor_semantics\": "
        r"\"first_observation_first_present_sample\".*?"
        r"\"anchor_payload\": _semantic_payload\(class_elements\[0\]\).*?"
        r"\"union_spatial_envelope\": _union_envelope\(class_elements\).*?"
        r"\"dominant_phase_payload\": _semantic_payload\(dominant\)",
        "Settlement v2.5 fixture shaping no longer retains honest anchors, "
        "union envelopes, and dominant lifecycle phases",
    )
    _require_regex(
        unit_tests,
        r"def test_extended_baseline_receipt_resolves_exact_recording_bytes\(.*?"
        r"def test_extended_baseline_receipt_rejects_absent_or_duplicate_bytes\(.*?"
        r"def test_ambiguous_settings_screen_requires_exact_edge_route\(.*?"
        r"def test_churn_on_control_member_is_not_classifiable\(.*?"
        r"def test_visible_variance_on_control_member_is_not_classifiable\(.*?"
        r"def test_core_relative_order_flip_trips\(.*?"
        r"def test_cross_instance_core_byte_inequality_trips\(.*?"
        r"def test_ambient_fraction_above_forty_percent_stops\(.*?"
        r"def test_declared_phantom_ambient_class_is_a_recorder_defect\(.*?"
        r"def test_empty_semantic_surface_is_a_constant_gameplay_surface\(.*?"
        r"def test_non_string_semantic_surface_is_a_recorder_defect\(",
        "Settlement v2.5 named guardrails lost their direct behavior tests",
    )
    return (
        "Settlement v2.9 ambient classification, reproduced core, relative "
        "draw order, anchors/envelopes, asymmetry, caps, and guardrails are "
        "behavior-tested by the CI unit module"
    )


def test_native_menu_motion_capability_campaign_resolution_is_fail_closed() -> str:
    assert_module_runs_in_ci("test_native_menu_settlement_v2")
    assert_module_runs_in_ci("test_native_menu_ambient_lifecycle")
    resolver = _read("tools/resolve_native_menu_ambient_campaign.py")
    classifier = _read("tools/native_menu_ambient_lifecycle.py")
    ambient_tests = _read("tests/test_native_menu_ambient_lifecycle.py")
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
        r"if not paths:.*?standalone fixture sweep reached no candidate content.*?"
        r"if layout_id in fixtures:.*?standalone fixture id.*?ambiguous.*?"
        r"def collect_navigation\(.*?"
        r"set\(by_label\[\"primary\"\]\) != "
        r"set\(by_label\[\"confirmation\"\]\).*?"
        r"navigation edge censuses differ",
        "ambient-lifecycle resolution no longer proves it reached real "
        "standalones or refuses duplicate/missing screen and edge candidates",
    )
    _require_regex(
        resolver,
        r"NAVIGATION_ENDPOINT_LAYOUT_IDS\s*=\s*\{.*?"
        r"\(\"main_to_settings\", \"after\"\): \"game-settings-title\".*?"
        r"\(\"settings_to_main\", \"before\"\): \"game-settings-title\".*?"
        r"\(\"dark_cloud_menu_to_settings\", \"after\"\): "
        r"\"game-settings-dark-cloud\".*?"
        r"\(\"dark_cloud_settings_done\", \"before\"\): "
        r"\"game-settings-dark-cloud\".*?"
        r"\(\"settings_to_hub\", \"before\"\): \"game-settings-gameplay\".*?"
        r"\(\"pause_to_game_settings\", \"after\"\): "
        r"\"game-settings-gameplay\".*?"
        r"\(\"settings_to_controls\", \"before\"\): "
        r"\"game-settings-title\".*?"
        r"\(\"controls_to_settings\", \"after\"\): "
        r"\"game-settings-title\".*?"
        r"\(\"settings_to_performance\", \"before\"\): "
        r"\"game-settings-gameplay\".*?"
        r"\(\"performance_to_settings\", \"after\"\): "
        r"\"game-settings-gameplay\".*?"
        r"\(\"settings_to_dark_cloud_settings\", \"before\"\): "
        r"\"game-settings-gameplay\".*?"
        r"\(\"dark_cloud_settings_to_settings\", \"after\"\): "
        r"\"game-settings-gameplay\".*?"
        r"applicable_explicit_layout_ids\s*=\s*\{.*?"
        r"if key\[0\] in by_label\[\"primary\"\].*?"
        r"if explicit_layout_ids != applicable_explicit_layout_ids:.*?"
        r"explicit navigation layout mapping census changed",
        "ambient-lifecycle resolver no longer refuses the three-way settings "
        "screen ambiguity with an every-edge explicit route map",
    )
    _require_regex(
        resolver,
        r"def resolve_baseline_evidence\(.*?"
        r"if path\.stat\(\)\.st_size != recorded_bytes:.*?"
        r"if file_sha256\(path\) == recorded_sha256:.*?matches\.append\(.*?"
        r"if examined == 0:.*?baseline evidence sweep reached no JSON content.*?"
        r"if len\(matches\) != 1:.*?"
        r"baseline receipt does not resolve exactly.*?one byte-identical.*?"
        r"validate_receipt\(baseline_path, receipt, label \+ \" baseline\"\).*?"
        r"baseline_path, baseline_recording = resolve_baseline_evidence\(.*?"
        r"if canonical_bytes\(baseline_source\) != "
        r"canonical_bytes\(motion_source\):.*?"
        r"baseline provenance does not.*?match the motion observation.*?"
        r"_assert_runtime_provenance_matches\(\s*motion_source,\s*"
        r"fixture_source,\s*f\"extended observation \{path\} baseline\"",
        "historical motion observations are no longer byte-bound to one copied "
        "baseline with matching capture and runtime provenance",
    )
    _require_regex(
        resolver,
        r"def build_extended_baseline_filename_map\(.*?"
        r'f"\{layout_id\}-primary\.baseline\.json".*?'
        r'f"\{layout_id\}-confirmation\.baseline\.json".*?'
        r'filename_layout_candidates\.setdefault\(filename, set\(\)\)\.add\(layout_id\).*?'
        r"if ambiguous_filenames:.*?"
        r"extended baseline filename map is ambiguous.*?"
        r"layout_by_filename\s*=\s*build_extended_baseline_filename_map\(fixtures\).*?"
        r"layout_id\s*=\s*layout_by_filename\.get\(filename\)",
        "historical motion observations are no longer byte-bound to one copied "
        "baseline with matching capture and runtime provenance",
    )
    _require_regex(
        resolver,
        r"primary_identity\s*=\s*_identity\(.*?"
        r"confirmation_identity\s*=\s*_identity\(.*?"
        r"if primary_identity == confirmation_identity:.*?"
        r"did not use an independent fresh instance",
        "screen lifecycle resolution no longer requires independent standalone "
        "instances",
    )
    _require_regex(
        resolver,
        r"for layout_id in sorted\(fixtures\):\s*"
        r"reached\s*=\s*observations\.get\(layout_id\).*?"
        r"if not reached:.*?was never reached.*?"
        r"resolution\s*=\s*resolve_ambient_lifecycle\(\s*"
        r"reached, asset_manifest=asset_manifest\s*\)",
        "screen lifecycle resolution no longer resolves every reached window "
        "for each named standalone layout",
    )
    _require_regex(
        classifier,
        r"screen_ids\s*=\s*\{.*?"
        r'measurement\["identity"\]\["screen_id"\].*?'
        r"probed_semantic_surfaces\s*=\s*\{.*?"
        r'identity_source"\]\s*==\s*"semantic_probe".*?'
        r"invalid_fallback_identities\s*=\s*\[.*?"
        r"sealed-v6 fallback.*?exact screen/layout payload fallback.*?"
        r"len\(screen_ids\) != 1 or len\(probed_semantic_surfaces\) > 1.*?"
        r"semantic_generation_measurements\s*=\s*\[.*?"
        r'identity_source"\]\s*==\s*"semantic_probe".*?or measurements.*?'
        r'identity\["observed_layout_generations"\]\s*=\s*sorted\(.*?'
        r'measurement\["identity"\]\["layout_generation"\].*?'
        r'identity\["layout_generation_semantics"\]',
        "Settlement v2.5 no longer keeps path-local generation counters and "
        "sealed-v6 placeholder surfaces out of live-probed screen identity",
    )
    _require_regex(
        resolver,
        r"def _observation\(.*?corroboration_anchor: bool = True.*?"
        r'"corroboration_anchor": bool\(.*?'
        r"_observation\(\s*header,\s*samples,\s*"
        r"evidence_receipt\(paths\[label\], evidence_root\),\s*"
        r'f"edge:\{edge_id\}:\{side\}:\{label\}",\s*'
        r"corroboration_anchor=False",
        "navigation replay windows again multiply the v2.3 extended-observation "
        "duty after screen classification was anchored to two fresh standalones",
    )
    _require_regex(
        classifier,
        r"corroboration_anchors\s*=\s*\[.*?"
        r'measurement\["corroboration_anchor"\].*?'
        r"requires two fresh standalone.*?corroboration anchors.*?"
        r'if not quiet_measurement\["corroboration_anchor"\]:\s*continue',
        "motion-capability resolution no longer requires two fresh standalone "
        "anchors and their same-instance extended corroboration",
    )
    _require_regex(
        classifier,
        r"def _motion_geometry_compatible\(.*?"
        r"if max\(left_min, right_min\) > min\(left_max, right_max\):\s*"
        r"return False.*?"
        r"def _resolve_varying_member_keys\(\s*measurements:.*?"
        r"varying-member identity ambiguity.*?"
        r"_core_counter_for_measurements\(\s*"
        r"measurements,\s*ambient_family,\s*varying_member_keys,\s*"
        r"animated_family_keys,\s*asset_manifest,?\s*\).*?"
        r"_core_bands\(\s*measurements,\s*core_counter,\s*core_ids,\s*"
        r"\{\*\*resolved_ambient_keys, \*\*choice_slot_keys\}",
        "same-art rect animation again collapses distinct screen members and "
        "demotes a reproduced stable sibling from the structural core",
    )
    _require_regex(
        classifier,
        r"def _resolve_varying_member_keys\(\s*measurements:.*?"
        r"ambient_family: set\[str\].*?"
        r"witnesses\s*=\s*\[.*?"
        r'record\[1\]\["classification"\] == "animated".*?'
        r'record\[1\]\["art_id"\] not in ambient_family',
        "title-backdrop ambient art is again forced through screen-member "
        "motion slots instead of retaining authorized art-family identity",
    )
    _require_regex(
        classifier,
        r"def _varying_member_geometry_ranks\(.*?"
        r'if len\(by_measurement\) < 2 or len\(counts\) != 1:\s*return \{\}.*?'
        r"geometry-rank collision.*?"
        r"geometry_ranks\s*=\s*_varying_member_geometry_ranks\(records\).*?"
        r"in geometry_ranks.*?and geometry_ranks\[.*?== geometry_ranks\[.*?"
        r"motion envelopes crossed.*?measured geometry ranks",
        "same-art movers observed at disjoint phases again fragment into "
        "instance-local slots instead of measured geometry-ranked members",
    )
    _require_regex(
        classifier,
        r"if not witnesses:.*?"
        r"geometry_samples\s*=\s*\{.*?"
        r"if len\(geometry_samples\) < 2:\s*continue.*?"
        r"fixed_payloads\s*=\s*\{.*?"
        r"field not in GEOMETRY_FIELDS.*?"
        r"motion capability guardrail: cross-window member.*?"
        r"cross_window_rect_events\[key\]\s*=\s*"
        r"len\(geometry_samples\) - 1.*?"
        r'"motion_witness":\s*\(.*?"cross_window_rect_variance".*?'
        r'events\["rect_change"\]\s*\+\s*'
        r'events\["cross_window_rect_change"\]',
        "Settlement v2.3 no longer treats rect-only differences across valid "
        "quiet windows as measured screen-member motion while retaining the "
        "non-rect and phantom-classification guardrails",
    )
    _require_regex(
        ambient_tests,
        r"def test_cross_window_rect_variance_proves_motion_capability\(.*?"
        r"cross_window_rect_change.*?"
        r"def test_cross_window_motion_requires_each_stationary_anchor_extension\(.*?"
        r"def test_cross_window_motion_rejects_nonrect_variance\(",
        "the CI behavior suite no longer proves cross-window motion, both "
        "stationary-anchor corroborations, and non-rect rejection",
    )
    _require_regex(
        classifier,
        r"def find_ambient_settled_window\(.*?"
        r"window_ephemeral_art_ids\s*=\s*sorted\(.*?"
        r"membership_events\s*=\s*\[.*?"
        r"if window_ephemeral_art_ids and \(\s*"
        r'not any\(event\["event"\] == "spawn".*?or not any\(\s*'
        r'event\["event"\] == "despawn".*?'
        r"population-versus-ephemeral settlement guardrail.*?continue.*?"
        r'result\["stable_start_index"\]\s*=\s*start',
        "Settlement v2.5 again accepts one-way membership decay as settled "
        "ephemeral churn before bidirectional family evidence",
    )
    _require_regex(
        classifier,
        r"ambient_family\s*=\s*\{.*?"
        r"_resolve_varying_member_keys\(\s*"
        r"measurements, ambient_family, animated_family_keys\s*\)",
        "title-backdrop ambient art is again forced through screen-member "
        "motion slots instead of retaining authorized art-family identity",
    )
    _require_regex(
        ambient_tests,
        r"class NativeMenuAmbientLifecycleTests\(unittest\.TestCase\):.*?"
        r"def test_same_art_motion_slot_does_not_demote_stable_sibling\(.*?"
        r"self\.assertEqual\(len\(resolved\[\"animated_element_ids\"\]\), 1\).*?"
        r"element\[\"art_id\"\] == \"UI\.shared\"",
        "the CI behavior suite no longer proves same-art motion capability is "
        "member-scoped rather than atlas-family scoped",
    )
    _require_regex(
        resolver,
        r"RUNTIME_PROVENANCE_FIELDS\s*=\s*\(\s*"
        r'"game_executable_sha256",\s*"loader_dll_sha256",\s*\).*?'
        r"def _assert_runtime_provenance_matches\(.*?"
        r"for field in RUNTIME_PROVENANCE_FIELDS:.*?"
        r"changed runtime provenance field.*?"
        r"_assert_game_executable_matches\(\s*"
        r"_source\(header, str\(paths\[label\]\)\),\s*"
        r'fixtures\[layout_id\]\["source"\]',
        "independent navigation recordings no longer retain their own "
        "machine-derived commit and loader provenance while requiring the "
        "exact game executable",
    )
    _require_regex(
        resolver,
        r'NAVIGATION_GAME_PROVENANCE_FIELD\s*=\s*"game_executable_sha256".*?'
        r"def _assert_game_executable_matches\(.*?"
        r"field = NAVIGATION_GAME_PROVENANCE_FIELD.*?"
        r"changed game executable provenance field",
        "navigation-to-standalone comparison no longer rejects a changed game "
        "binary while allowing independently recorded loader evolution",
    )
    _require_regex(
        resolver,
        r"def resolve_exact_evidence_receipt\(.*?"
        r"not path\.is_relative_to\(root\) or not path\.is_file\(\).*?"
        r"validate_receipt\(path, receipt, label\).*?"
        r"def collect_supplemental_standalones\(.*?"
        r"if not isinstance\(pairs, list\) or not pairs:.*?"
        r"sweep reached no historical pair witness.*?"
        r"resolve_exact_evidence_receipt\(.*?primary_fixture.*?"
        r"resolve_exact_evidence_receipt\(.*?primary_trace.*?"
        r"resolve_exact_evidence_receipt\(.*?confirmation.*?"
        r"_assert_game_executable_matches\(\s*historical_source,\s*"
        r'fixtures\[layout_id\]\["source"\].*?'
        r"candidate_identities & \(existing \| historical_identities\).*?"
        r"repeats an existing capture identity.*?"
        r"collect_supplemental_standalones\(.*?"
        r'"supplemental_settled_pair_manifest": evidence_receipt',
        "cross-window motion history is no longer bound to an exact nonempty "
        "hashed pair manifest with unambiguous independent identities and an "
        "unchanged retail game binary",
    )
    _require_regex(
        resolver,
        r"fixture\[\"layout\"\]\s*=\s*copy\.deepcopy\(layouts\[layout_id\]\).*?"
        r"endpoint\[\"layout\"\]\s*=\s*copy\.deepcopy\(layouts\[layout_id\]\).*?"
        r"if verify:.*?"
        r"resolved candidate .*? is not the machine-derived v2\.9 result.*?"
        r"resolved navigation is not the machine-derived v2\.9 result",
        "the v2.9 resolver no longer applies one screen classification to every "
        "fixture/endpoint or verifies the derived artifacts byte-for-byte",
    )
    _require_regex(
        promoter,
        r"ambient_lifecycle_resolution.*?settlement_spec.*?2\.9.*?"
        r"resolve_campaign\(.*?False,\s*True,",
        "menu promotion can bypass re-derivation of the complete v2.9 campaign",
    )
    _require_regex(
        confirmation,
        r"\$rawSetsMatchNoncontractual\s*=.*?"
        r"raw_sets_match_noncontractual\s*=\s*\$rawSetsMatchNoncontractual.*?"
        r"requires_campaign_resolution\s*=\s*\$true",
        "fresh confirmation again treats window-local raw IDs as contractual "
        "instead of deferring to campaign-wide v2.9 resolution",
    )
    return (
        "Settlement v2.9 resolves one structural core and lifecycle map across "
        "every standalone/edge observation, refuses ambiguity and provenance overrides, "
        "and promotion re-derives the complete campaign"
    )


def test_native_menu_v210_controls_title_correction_is_exact() -> str:
    assert_module_runs_in_ci("test_native_menu_ambient_lifecycle")
    contract_path = (
        ROOT
        / "tests/fixtures/webgame/native-menu-controls-title-v210.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    expected_fields = {
        "schema": "solomon-dark-native-menu-controls-title-v210",
        "settlement_spec": "2.10",
        "layout_id": "controls",
        "screen_id": "controls",
        "field": "screen_title",
        "landed_value": "",
        "settled_value": "Wizard Controls",
    }
    if {field: contract.get(field) for field in expected_fields} != expected_fields:
        raise StaticReTestFailure(
            "Settlement v2.10 no longer authorizes exactly the empty-to-Wizard "
            "Controls title correction"
        )
    if set(contract) != {*expected_fields, "source_stop_audit", "derivation"}:
        raise StaticReTestFailure(
            "Settlement v2.10 Controls title contract gained an unreviewed scope"
        )
    source_stop_audit = contract.get("source_stop_audit")
    if source_stop_audit != {
        "evidence_filename": "controls-screen-title-stop-audit.json",
        "sha256": (
            "0377809414de5a1e5d0b8af01baaf1ee8221c5e586e81d7dfda95f18d1da703f"
        ),
        "bytes": 5456,
    }:
        raise StaticReTestFailure(
            "Settlement v2.10 Controls title correction lost its accepted STOP audit receipt"
        )

    diagnosis = _read("tools/native_menu_landed_diagnosis_v25.py")
    promoter = _read("tools/promote_native_menu_recapture.py")
    mutation_runner = _read("tools/run_native_menu_v210_title_mutations.py")
    unit_tests = _read("tests/test_native_menu_ambient_lifecycle.py")
    specification = _read("docs/reverse-engineering/native-menu-settlement.md")
    _require_regex(
        diagnosis,
        r"def _diagnose_layout_identity_v210\(.*?"
        r"landed_layout\.get\(\"screen_id\"\) != "
        r"settled_layout\.get\(\"screen_id\"\).*?"
        r"field 'screen_id' differs.*?"
        r"if landed_title == settled_title:\s*return None.*?"
        r"layout_id != controls_title_contract\[\"layout_id\"\].*?"
        r"landed_layout\.get\(\"screen_id\"\) != "
        r"controls_title_contract\[\"screen_id\"\].*?"
        r"landed_title != controls_title_contract\[\"landed_value\"\].*?"
        r"settled_title != controls_title_contract\[\"settled_value\"\].*?"
        r"field 'screen_title' differs.*?"
        r"solomon-dark-native-menu-screen-title-correction-v210",
        "Settlement v2.10 can authorize a title change outside the exact "
        "Controls layout, native screen, old value, and new value",
    )
    _require_regex(
        promoter,
        r"native-menu-controls-title-v210\.json.*?"
        r"diagnose_landed_layout\(\s*layout_id,.*?"
        r"order_override_contract,\s*controls_title_contract,.*?"
        r"diagnose_landed_layout\(\s*source_layout_id,.*?"
        r"order_override_contract,\s*controls_title_contract,",
        "standalone or transition-source promotion can bypass the exact "
        "v2.10 Controls title contract or lose layout identity",
    )
    _require_regex(
        unit_tests,
        r"def test_v210_controls_title_exact_correction_is_bounded\(.*?"
        r"def test_v210_controls_title_case_variant_remains_a_stop\(.*?"
        r"def test_v210_controls_title_rule_does_not_apply_to_another_layout\(",
        "the CI behavior suite no longer proves v2.10 positive, wrong-value, "
        "and wrong-layout behavior",
    )
    _require_regex(
        mutation_runner,
        r'layout\["screen_title"\] = "WIZARD CONTROLS".*?'
        r'layout\["screen_title"\] = "Changed title outside Controls".*?'
        r'"exact_controls_title_positive".*?'
        r'"controls_title_case_variant".*?'
        r'"other_layout_title_change".*?'
        r"cleared_before_baseline = clear_contract_bytecode.*?"
        r"cleared_before_mutation = clear_contract_bytecode.*?"
        r"cleared_before_restore = clear_contract_bytecode",
        "the real-candidate v2.10 mutation runner no longer proves exact value "
        "and exact layout scope with cleared-bytecode green baselines",
    )
    _require_regex(
        specification,
        r"# Native menu settlement specification v2\.11.*?"
        r"## Controls title capture defect.*?"
        r"0377809414de5a1e5d0b8af01baaf1ee8221c5e586e81d7dfda95f18d1da703f.*?"
        r"no general title tolerance was added",
        "the versioned settlement specification no longer records the exact "
        "Controls title STOP and bounded v2.10 correction",
    )
    return (
        "Settlement v2.10 corrects only Controls layout.screen_title from the "
        "landed empty value to the two-instance Wizard Controls value"
    )


def test_native_menu_v211_controls_core_supersession_is_exact() -> str:
    assert_module_runs_in_ci("test_native_menu_ambient_lifecycle")
    contract_path = (
        ROOT
        / "tests/fixtures/webgame/native-menu-controls-core-v211.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    expected_top_level = {
        "schema",
        "settlement_spec",
        "layout_id",
        "screen_id",
        "superseded_landed_fixture",
        "superseding_candidate_fixture",
        "source_audits",
        "paired_settlement",
        "navigation_endpoints",
        "justification",
        "forbidden",
        "derivation",
    }
    if set(contract) != expected_top_level:
        raise StaticReTestFailure(
            "Settlement v2.11 Controls structural supersession gained an "
            "unreviewed acceptance surface"
        )
    if {
        field: contract.get(field)
        for field in ("schema", "settlement_spec", "layout_id", "screen_id")
    } != {
        "schema": "solomon-dark-native-menu-controls-core-supersession-v211",
        "settlement_spec": "2.11",
        "layout_id": "controls",
        "screen_id": "controls",
    }:
        raise StaticReTestFailure(
            "Settlement v2.11 no longer authorizes exactly one Controls-only "
            "structural supersession"
        )
    if contract.get("forbidden") != [
        "general_settled_only_member_tolerance",
        "count_or_class_based_acceptance",
        "another_layout",
        "another_candidate_content",
    ]:
        raise StaticReTestFailure(
            "Settlement v2.11 no longer explicitly forbids generalized "
            "structural mismatch acceptance"
        )

    landed = contract.get("superseded_landed_fixture")
    settled = contract.get("superseding_candidate_fixture")
    if not isinstance(landed, dict) or not isinstance(settled, dict):
        raise StaticReTestFailure(
            "Settlement v2.11 lost one of its exact old/new fixture receipts"
        )
    if landed.get("path") != (
        "webgame-contracts/baseline-snapshots/menu-layouts/controls.json"
    ) or settled.get("path") != (
        "candidates/candidate-v29/menu-layouts/controls.json"
    ):
        raise StaticReTestFailure(
            "Settlement v2.11 old/new fixture receipts no longer name the "
            "reviewed Controls artifacts"
        )
    assert_recorded_hash_matches_file(
        landed.get("sha256"),
        ROOT / landed["path"],
        "Settlement v2.11 superseded Controls baseline snapshot",
    )
    settled_fixture_path = (
        ROOT / "tests/fixtures/webgame/menu-layouts/controls.json"
    )
    assert_recorded_hash_matches_file(
        settled.get("sha256"),
        settled_fixture_path,
        "Settlement v2.11 superseding settled Controls fixture",
    )
    if landed.get("bytes") != (ROOT / landed["path"]).stat().st_size:
        raise StaticReTestFailure(
            "Settlement v2.11 superseded Controls byte receipt no longer "
            "matches the committed baseline"
        )
    if settled.get("bytes") != settled_fixture_path.stat().st_size:
        raise StaticReTestFailure(
            "Settlement v2.11 superseding Controls byte receipt no longer "
            "matches the committed settled fixture"
        )

    def semantic_counter(path: Path) -> Counter[str]:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        elements = fixture.get("layout", {}).get("elements")
        if not isinstance(elements, list) or not elements:
            raise StaticReTestFailure(
                "Settlement v2.11 semantic comparison reached no Controls members"
            )
        counter: Counter[str] = Counter()
        for element in elements:
            if not isinstance(element, dict):
                raise StaticReTestFailure(
                    "Settlement v2.11 semantic comparison reached a malformed member"
                )
            semantic = {
                key: value
                for key, value in element.items()
                if key not in {"id", "draw_order", "draw_order_semantics"}
            }
            encoded = json.dumps(
                semantic,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            counter[hashlib.sha256(encoded).hexdigest()] += 1
        return counter

    def recorded_counter(value: dict[str, Any], label: str) -> Counter[str]:
        entries = value.get("semantic_multiset")
        if not isinstance(entries, list) or not entries:
            raise StaticReTestFailure(
                f"Settlement v2.11 {label} semantic multiset is absent"
            )
        counter: Counter[str] = Counter()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {
                "semantic_sha256",
                "count",
            }:
                raise StaticReTestFailure(
                    f"Settlement v2.11 {label} semantic multiset is ambiguous"
                )
            digest = entry.get("semantic_sha256")
            count = entry.get("count")
            if (
                not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count <= 0
                or digest in counter
            ):
                raise StaticReTestFailure(
                    f"Settlement v2.11 {label} semantic multiset is not canonical"
                )
            counter[digest] = count
        return counter

    landed_counter = recorded_counter(landed, "superseded")
    settled_counter = recorded_counter(settled, "superseding")
    if landed_counter != semantic_counter(ROOT / landed["path"]):
        raise StaticReTestFailure(
            "Settlement v2.11 superseded Controls semantic multiset no longer "
            "matches its committed baseline"
        )
    if settled_counter != semantic_counter(settled_fixture_path):
        raise StaticReTestFailure(
            "Settlement v2.11 superseding Controls semantic multiset no longer "
            "matches its committed fixture"
        )
    if (
        landed.get("semantic_member_count") != sum(landed_counter.values())
        or settled.get("semantic_member_count") != sum(settled_counter.values())
    ):
        raise StaticReTestFailure(
            "Settlement v2.11 Controls semantic member census no longer closes"
        )

    audits = contract.get("source_audits")
    if audits != {
        "title": {
            "path": "diagnostics/controls-screen-title-stop-audit.json",
            "sha256": (
                "0377809414de5a1e5d0b8af01baaf1ee8221c5e586e81d7dfda95f18d1da703f"
            ),
            "bytes": 5456,
        },
        "structural_core": {
            "path": "diagnostics/controls-post-v210-structural-stop-audit.json",
            "sha256": (
                "22fc8f3061a0f0577bf805ab1ddf750416744bc0097405187321b9feeae148f1"
            ),
            "bytes": 63660,
        },
    }:
        raise StaticReTestFailure(
            "Settlement v2.11 Controls supersession lost its exact title and "
            "structural STOP audit receipts"
        )
    paired = contract.get("paired_settlement")
    if (
        not isinstance(paired, dict)
        or paired.get("two_independent_instances") is not True
        or paired.get("classifier_and_tag_agree") is not True
        or not isinstance(paired.get("primary"), dict)
        or not isinstance(paired.get("confirmation"), dict)
        or (
            paired["primary"].get("instance"),
            paired["primary"].get("process_id"),
        )
        == (
            paired["confirmation"].get("instance"),
            paired["confirmation"].get("process_id"),
        )
    ):
        raise StaticReTestFailure(
            "Settlement v2.11 no longer requires two independent "
            "classifier-agreed Controls settlements"
        )
    endpoints = contract.get("navigation_endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != 2:
        raise StaticReTestFailure(
            "Settlement v2.11 no longer pins exactly both regenerated Controls endpoints"
        )
    endpoint_identities = {
        (entry.get("edge_id"), entry.get("side"), entry.get("trigger"))
        for entry in endpoints
        if isinstance(entry, dict)
    }
    if endpoint_identities != {
        ("settings_to_controls", "after", "customize_keyboard_click"),
        ("controls_to_settings", "before", "back_button_click"),
    } or any(
        entry.get("semantic_surface") != "controls"
        or entry.get("tagged_screen") != "controls"
        for entry in endpoints
    ):
        raise StaticReTestFailure(
            "Settlement v2.11 Controls endpoints no longer bind both exact "
            "classifier-agreed standalone endpoints"
        )

    diagnosis = _read("tools/native_menu_landed_diagnosis_v25.py")
    promoter = _read("tools/promote_native_menu_recapture.py")
    generator = _read("tools/derive_native_menu_controls_supersession_v211.py")
    mutation_runner = _read(
        "tools/run_native_menu_v211_controls_core_mutations.py"
    )
    unit_tests = _read("tests/test_native_menu_ambient_lifecycle.py")
    specification = _read("docs/reverse-engineering/native-menu-settlement.md")
    _require_regex(
        diagnosis,
        r"def _diagnose_structural_core_v211\(.*?"
        r"_v211_receipt_matches\(recorded_landed, landed_fixture_receipt\).*?"
        r"_v211_receipt_matches\(recorded_candidate, candidate_fixture_receipt\).*?"
        r"layout_id != contract\[\"layout_id\"\].*?"
        r"_v211_semantic_counter\(landed_layout.*?!= landed_counter.*?"
        r"_v211_semantic_counter\(settled_layout.*?!= settled_counter.*?"
        r"V211_STRUCTURAL_MISMATCH",
        "Settlement v2.11 runtime can accept a non-exact receipt, layout, or "
        "semantic multiset",
    )
    _require_regex(
        promoter,
        r"native-menu-controls-core-v211\.json.*?"
        r"diagnose_landed_layout\(\s*layout_id,.*?"
        r"controls_core_contract,.*?file_receipt\(landed_path_by_layout_id\[layout_id\]\).*?"
        r"_validate_controls_context_v211\(.*?"
        r"controls_core_contract,.*?records\[\"controls\"\].*?"
        r"diagnose_landed_layout\(\s*source_layout_id,.*?"
        r"controls_core_contract,.*?"
        r"promotion_pairs",
        "standalone, transition-source, or final promotion can bypass the "
        "exact v2.11 Controls contract and context gate",
    )
    _require_regex(
        generator,
        r"committed_receipt\(repo_root, landed_snapshot_relative\).*?"
        r"structural_audit does not reproduce both multisets.*?"
        r"Controls confirmation reused the primary identity.*?"
        r"controls_endpoints\(navigation, settled_layout\)",
        "Settlement v2.11 generator can accept an uncommitted old snapshot, "
        "unclosed audit arithmetic, reused instance, or missing endpoint",
    )
    _require_regex(
        mutation_runner,
        r'"exact_55_member_core_positive".*?'
        r'"drop_one_core_member".*?'
        r'"mutate_one_core_rect".*?'
        r'"add_one_core_member".*?'
        r'"wrong_layout_claim".*?'
        r"cleared_before_baseline = clear_contract_bytecode.*?"
        r"cleared_before_mutation = clear_contract_bytecode.*?"
        r"cleared_before_restore = clear_contract_bytecode",
        "the real v2.11 mutation table no longer proves exact positive, drop, "
        "mutate, add, and wrong-layout behavior with green baselines",
    )
    _require_regex(
        unit_tests,
        r"test_v211_controls_structural_core_exact_supersession_is_bounded.*?"
        r"test_v211_controls_structural_core_drop_one_stops.*?"
        r"test_v211_controls_structural_core_mutate_one_stops.*?"
        r"test_v211_controls_structural_core_add_one_stops.*?"
        r"test_v211_controls_structural_core_rule_does_not_apply_elsewhere",
        "the CI behavior suite no longer proves the bounded v2.11 Controls "
        "supersession in both directions",
    )
    _require_regex(
        specification,
        r"# Native menu settlement specification v2\.11.*?"
        r"## Controls structural-core capture defect.*?"
        r"22fc8f3061a0f0577bf805ab1ddf750416744bc0097405187321b9feeae148f1.*?"
        r"no general settled-only-member tolerance",
        "the versioned settlement specification no longer records the exact "
        "Controls structural STOP and bounded v2.11 supersession",
    )
    return (
        "Settlement v2.11 supersedes exactly the audited Controls core while "
        "preserving classifier agreement, paired settlement, and both endpoints"
    )


def test_native_menu_path_dependent_core_fork_is_exact() -> str:
    assert_module_runs_in_ci("test_native_menu_ambient_lifecycle")
    resolver = _read("tools/resolve_native_menu_ambient_campaign.py")
    materializer = _read("tools/materialize_native_menu_path_forks_v26.py")
    builder = _read("tools/build_native_menu_goldens_v25.py")
    promoter = _read("tools/promote_native_menu_recapture.py")
    tests = _read("tests/test_native_menu_ambient_lifecycle.py")
    specification = _read(
        "docs/reverse-engineering/native-menu-settlement.md"
    )
    profile = _read("tools/native_menu_profile_state.py")

    forbidden_provenance_options = (
        "--base-commit-sha",
        "--source-tree-sha",
        "--game-executable-sha256",
        "--loader-dll-sha256",
        "--fork-decision-sha256",
        "--measured-structural-element-count",
    )
    smuggled = [
        option for option in forbidden_provenance_options if option in materializer
    ]
    if smuggled:
        raise StaticReTestFailure(
            "path-dependent core materializer accepts operator-supplied "
            f"provenance or golden values: {smuggled}"
        )
    _require_regex(
        resolver,
        r'NAVIGATION_ENDPOINT_LAYOUT_IDS\s*=\s*\{.*?'
        r'\("hub_to_pause", "before"\): "hub_resumed".*?'
        r'\("pause_to_hub_resume", "after"\): "hub_resumed".*?'
        r'\("profile_select_resume_to_hub", "after"\): "hub_resumed".*?'
        r'\("settings_to_hub", "after"\): "hub_resumed"',
        "Settlement v2.13 no longer retains every non-conditional Hub route mapping",
    )
    _require_regex(
        resolver,
        r'PATH_DEPENDENT_CORE_LAYOUTS\s*=\s*\{.*?'
        r'"hub_pristine_second_new_game"\s*:\s*\{.*?'
        r'"path_qualifier"\s*:\s*"pristine_second_new_game".*?'
        r'"required_baseline_id"\s*:\s*"pristine_fresh_install".*?'
        r'"hub_new_game"\s*:\s*\{.*?'
        r'"parent_screen_id"\s*:\s*"hub".*?'
        r'"path_qualifier"\s*:\s*"new_game_derived_two_action".*?'
        r'"required_baseline_id"\s*:\s*"hub_new_game_two_action_v213".*?'
        r'"hub_resumed"\s*:\s*\{.*?'
        r'"parent_screen_id"\s*:\s*"hub".*?'
        r'"path_qualifier"\s*:\s*"resumed".*?'
        r'PATH_DEPENDENT_CORE_ENDPOINTS\s*=\s*\{.*?'
        r'\("create_discipline_to_hub", "after"\): '
        r'"hub_pristine_second_new_game".*?'
        r'\("hub_to_pause", "before"\).*?'
        r'\("pause_to_hub_resume", "after"\).*?'
        r'\("profile_select_resume_to_hub", "after"\).*?'
        r'\("settings_to_hub", "after"\)',
        "Settlement v2.13 no longer names exactly three Hub layouts or binds "
        "the fresh navigation graph to its deterministic path/session state",
    )
    _require_regex(
        resolver,
        r"def validate_path_dependent_core_forks\(.*?"
        r"load_hub_binding_contract.*?"
        r"if reached_layouts != expected_layouts:.*?"
        r"path-dependent core contract: Hub variant census changed.*?"
        r"if observed_bindings != PATH_DEPENDENT_CORE_ENDPOINTS:.*?"
        r"one or more Hub navigation endpoints.*?remain ambiguous.*?"
        r"if unexpected_hub_endpoints:.*?"
        r"Hub navigation endpoint lacks a.*?declared selector.*?"
        r"if len\(set\(counts\.values\(\)\)\) != len\(counts\):.*?"
        r"Hub variants do not differ in element census",
        "Settlement v2.13 no longer rejects an equal-census, unbound, or "
        "extra-layout Hub fork",
    )
    _require_regex(
        profile,
        r"def resolve_navigation_profile_binding\(.*?"
        r"edge_id.*?endpoint.*?baseline_id.*?"
        r"if len\(matches\) != 1:.*?"
        r"PER_BINDING_MISMATCH_REASON.*?"
        r"def assert_navigation_baseline_allowed\(.*?"
        r"if baseline_id not in allowed:.*?"
        r"PER_BINDING_MISMATCH_REASON",
        "the v2.13 edge resolver no longer refuses an absent or ambiguous "
        "baseline-qualified Hub binding",
    )
    _require_regex(
        materializer,
        r"def validate_audit\(.*?"
        r"sample_count.*?< 40.*?"
        r"stable_span_milliseconds.*?< 2_000.*?"
        r"non_full_presence_members.*?!= \[\].*?"
        r"if len\(identities\) != 4:.*?"
        r"fork lacks four fresh instance witnesses.*?"
        r"def fork_metadata\(.*?fork_decision.*?audit_receipt",
        "Hub path-fork fixtures are no longer derived from four settled fresh "
        "instance witnesses with one exact hashed fork-decision receipt",
    )
    _require_regex(
        materializer,
        r"def evidence_receipt\(.*?"
        r"if not resolved\.is_relative_to\(root\):.*?"
        r'"sha256": sha256_file\(resolved\).*?'
        r'"bytes": resolved\.stat\(\)\.st_size',
        "Hub path-fork fixtures no longer hash their exact fork-decision "
        "artifact inside the campaign evidence root",
    )
    _require_regex(
        builder,
        r'menu-transition-layouts", 3, "hub_new_game".*?'
        r'"hub_pristine_second_new_game".*?'
        r'"hub_resumed".*?'
        r"three authorized Hub layouts.*?"
        r"if len\(fixtures\) != 31.*?"
        r"28 menus plus three Hub layouts",
        "menu-goldens aggregation no longer embeds all three authorized Hub "
        "standalones while preserving the 28 shell-facing layout census",
    )
    _require_regex(
        promoter,
        r'"hub_new_game\.json".*?'
        r'"hub_pristine_second_new_game\.json".*?'
        r'"hub_resumed\.json".*?'
        r"if len\(records\) != 31.*?"
        r"28 menus plus three Hub layouts.*?"
        r'"status": "new_path_dependent_layout".*?'
        r'"fork_decision": copy\.deepcopy',
        "promotion no longer carries both new Hub path layouts and their fork "
        "decision without inventing a pre-v2.6 standalone payload",
    )
    _require_regex(
        tests,
        r"def test_hub_path_dependent_core_routes_are_exact_and_complete\(.*?"
        r"def test_hub_path_dependent_core_requires_distinct_reproduced_censuses\(.*?"
        r"def test_hub_path_dependent_core_rejects_an_unbound_endpoint\(",
        "Settlement v2.6 lost direct behavior tests for exact Hub routing, "
        "different censuses, and complete endpoint binding",
    )
    _require_regex(
        specification,
        r"# Native menu settlement specification v2\.13.*?"
        r"## Path-dependent core.*?Settlement v2\.6.*?"
        r"two.*?fresh instances.*?"
        r"deterministic entry path.*?durable session state.*?"
        r"differ in element census.*?"
        r"## Hub baseline legitimacy and exact path bindings.*?"
        r"Settlement v2\.12.*?hub_pristine_second_new_game.*?"
        r"Settlement v2\.13.*?hub_new_game.*?"
        r"Annalist.*?PotionGuy.*?"
        r"## Changelog.*?v2\.13.*?v2\.12",
        "the versioned settlement specification no longer records the exact "
        "v2.12/v2.13 Hub baselines, paths, and accepted STOP mechanism",
    )
    return (
        "Settlement v2.12/v2.13 permits exactly three paired-evidence Hub "
        "layouts, binds every graph endpoint by legitimate baseline, and "
        "derives all provenance and measured censuses"
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
    importer = _read("tools/import_native_menu_special_captures_v25.py")
    aggregate_builder = _read("tools/build_native_menu_goldens_v25.py")
    aggregate_launcher = _read("scripts/Build-NativeMenuGoldens.ps1")
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
        r"_noncanonical.*?deterministic reordinalization produced.*?"
        r"noncanonical survivor ordinal",
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
        r"def _navigation_population_trace_pairs_v25\(.*?"
        r"primary_identity == confirmation_identity.*?"
        r"if layout_id not in required_layouts:\s*continue.*?"
        r"canonical_bytes\(primary_endpoint\.get\(\"layout\"\)\).*?"
        r"required_layouts\[layout_id\].*?"
        r"def _select_population_trace_pair_v25\(.*?"
        r"landed_generation in primary\[\"generation_trace\"\].*?"
        r"landed_generation in confirmation\[\"generation_trace\"\].*?"
        r"if len\(qualifying_navigation\) > 1:.*?"
        r"population-witness routing is ambiguous.*?"
        r'"source": "paired_navigation_endpoint"',
        "overlay generation proof can select an unpaired, wrong-layout, or "
        "ambiguous navigation witness",
    )
    _require_regex(
        _read("tests/test_native_menu_ambient_lifecycle.py"),
        r"test_population_witness_routing_uses_unique_paired_navigation_trace.*?"
        r"test_population_witness_routing_refuses_ambiguous_paired_edges",
        "the CI behavior suite no longer proves unique paired-navigation "
        "population-witness routing and ambiguity refusal",
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
        r"def assert_overlay_sample_hygiene\(.*?"
        r"schema == OVERLAY_REFERENCE_SCHEMA_V24.*?"
        r"assert_overlay_sample_hygiene_v24\(samples, reference\).*?"
        r"schema == OVERLAY_REFERENCE_SCHEMA_V25.*?"
        r"for index, sample in enumerate\(samples\).*?"
        r"assert_overlay_hygiene_v25\(payload, reference\).*?"
        r"assert_overlay_sample_hygiene\(primary_samples, overlay_reference.*?"
        r"assert_overlay_sample_hygiene\(\s*confirmation_samples, "
        r"overlay_reference",
        "native-loader/loading import no longer overlay-gates every raw sample",
    )
    _require_regex(
        support,
        r"tests[\\/]fixtures[\\/]webgame[\\/]menu-overlay-reference\.json.*?"
        r"check-overlay.*?--reference",
        "NativeMenuCaptureSupport.ps1 no longer binds overlay hygiene to the "
        "machine-derived committed reference",
    )
    _require_regex(
        importer,
        r"repo_root / \"tests\" / \"fixtures\" / \"webgame\" / "
        r"\"menu-overlay-reference\.json\".*?"
        r"overlay_reference=overlay_reference.*?label=\"native_loader\".*?"
        r"overlay_reference=overlay_reference.*?label=\"loading_screen\"",
        "the paired special importer no longer binds both surfaces to the "
        "machine-derived committed overlay reference",
    )
    _require_regex(
        aggregate_builder,
        r"menu-overlay-reference\.json.*?"
        r"overlay\.get\(\"schema\"\) != OVERLAY_REFERENCE_SCHEMA.*?"
        r"assert_overlay_hygiene\(fixture\[\"layout\"\], overlay\).*?"
        r"for side, observed in.*?source.*?destination.*?"
        r"assert_overlay_hygiene\(observed\[\"layout\"\], overlay\)",
        "the Settlement v2.5 aggregate can accept derived beta-dialog "
        "contamination in a standalone, transition source, or transition "
        "destination",
    )
    _require_regex(
        aggregate_launcher,
        r"tools[\\/]build_native_menu_goldens_v25\.py.*?"
        r"Test-Path -LiteralPath \$builder -PathType Leaf.*?"
        r"& py\.exe -3 \$builder.*?"
        r"--fixture-root \$fixtureRoot.*?"
        r"--navigation-recording \$navigationPath.*?"
        r"--output \$outputPath",
        "Build-NativeMenuGoldens.ps1 no longer launches the fixed Settlement "
        "v2.5 aggregate implementation over the resolved fixture corpus",
    )
    return (
        "Settlement v2.4 derives one hashed beta-overlay semantic multiset, "
        "accepts only exact zero-residual subtraction with deterministic "
        "reordinalization, and hygiene-gates every capture surface"
    )


def test_native_menu_ambient_overlay_derivation_is_fail_closed() -> str:
    assert_module_runs_in_ci("test_native_menu_ambient_lifecycle")
    derivation = _read("tools/native_menu_overlay_v25.py")
    regression = _read("tools/verify_native_menu_ambient_v6_regression.py")
    unit_tests = _read("tests/test_native_menu_ambient_lifecycle.py")

    _require_regex(
        derivation,
        r"def derive_overlay_reference\(.*?"
        r"missing_title\s*=\s*main_title - beta_title.*?"
        r"extra_title\s*=\s*beta_title - main_title.*?"
        r"title-core member is missing from.*?beta_notice.*?"
        r"beta_notice leaves a title-side residual",
        "Settlement v2.5 overlay derivation no longer proves the complete "
        "main-menu title core embeds without a title-side residual",
    )
    _require_regex(
        derivation,
        r"main_residual\s*=\s*main_draws - beta_draws.*?"
        r"main_menu_root art core does not embed.*?"
        r"derived\s*=\s*beta_draws - main_draws.*?"
        r"derived != create_counter or derived != pause_counter.*?"
        r"does .*?not equal the proven Create and pause correction multisets",
        "Settlement v2.5 overlay reference no longer derives an exact semantic "
        "difference and corroborates it against both accepted corrections",
    )
    _require_regex(
        derivation,
        r"def overlay_semantic_multiset_is_present\(.*?"
        r"return not bool\(required - observed\).*?"
        r"def assert_overlay_hygiene\(.*?"
        r"contains the complete.*?derived beta-dialog semantic multiset",
        "Settlement v2.5 overlay hygiene regressed from complete sub-multiset "
        "matching to unsafe suffix intersection",
    )
    _require_regex(
        regression,
        r"def _stable_ui_counter\(.*?"
        r"dialog UI block is not sample-stable.*?"
        r"if primary_ui != confirmation_ui:.*?"
        r"independent dialog UI blocks differ.*?"
        r"if core_ui != primary_ui:.*?"
        r"complete dialog UI block did not enter",
        "the mandatory sealed-v6 regression no longer proves both traces settle "
        "with the complete dialog UI block in their reproduced core",
    )
    _require_regex(
        unit_tests,
        r"def test_overlay_derivation_trips_when_title_core_member_is_missing\(.*?"
        r"def test_overlay_corroboration_trips_on_one_perturbed_draw\(.*?"
        r"def test_derived_overlay_hygiene_refuses_complete_multiset\(.*?"
        r"def test_derived_overlay_hygiene_accepts_partial_suffix_sharing\(",
        "Settlement v2.5 overlay derivation and hygiene lost their named "
        "missing-title, perturbed-corroboration, complete, or partial tests",
    )
    return (
        "Settlement v2.5 derives the beta-dialog semantic multiset from settled "
        "cores, corroborates Create and pause, and keeps complete-sub-multiset "
        "hygiene without the pause suffix false positive"
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
