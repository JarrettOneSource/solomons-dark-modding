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
    SettlementV2Error,
    canonical_bytes,
    structural_layout_bytes,
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
        r"primaryIdsJson\s+-cne\s+\$confirmationIdsJson.*?"
        r"settlement\s*=\s*\$observation\.settlement",
        "animation confirmation no longer proves a fresh instance/process, "
        "identical machine provenance, and animated ID set",
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
        r"consecutive_structural_samples.*?structural_sha256",
        "native-loader/loading import no longer reclassifies the complete raw "
        "sample stream under Settlement v2",
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
        "apply Settlement v2, confirm animation from a fresh exact process, and "
        "derive commit/tree/exact-binary provenance without operator overrides"
    )


def test_native_menu_settlement_v2_classifier_is_strict_and_ci_wired() -> str:
    assert_module_runs_in_ci("test_native_menu_settlement_v2")
    classifier = _read("tools/native_menu_settlement_v2.py")
    _require_regex(
        classifier,
        r"MINIMUM_SAMPLES\s*=\s*40\b.*?"
        r"MINIMUM_SPAN_MILLISECONDS\s*=\s*2_000\b.*?"
        r"MAXIMUM_ANIMATED_FRACTION\s*=\s*0\.30\b",
        "Settlement v2 sample/span/animated-cap constants drifted from the "
        "amended menu capture definition",
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
        r"def assert_confirmation_matches\(.*?"
        r"if primary_ids != confirmation_ids:.*?"
        r"animated ID confirmation mismatch",
        "fresh-instance confirmation no longer requires exactly equal measured "
        "animated ID sets",
    )
    confirmation_body = classifier.partition(
        "def assert_confirmation_matches("
    )[2].partition("\ndef _read_json(")[0]
    if not confirmation_body or "structural_layout_bytes" in confirmation_body:
        raise StaticReTestFailure(
            "fresh-instance confirmation widened ATC's animated-ID-set rule "
            "into an undeclared cross-instance structural-equality rule"
        )
    return (
        "Settlement v2 classification, guardrails, fixture shaping, and fresh-"
        "instance animated-ID confirmation are behavior-tested by the CI unit module"
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


def _assert_settlement_v2_layout(
    layout: dict[str, Any], settlement: dict[str, Any], witness: str
) -> list[str]:
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
            if envelope["sample_count"] != settlement.get(
                "consecutive_structural_samples"
            ):
                raise StaticReTestFailure(
                    f"{witness}.{element_id} envelope does not cover the settled window"
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
    header: dict[str, Any], animated_ids: list[str], witness: str
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
    if not re.fullmatch(
        r"[0-9a-f]{64}",
        str(confirmation.get("confirmation_structural_sha256")),
    ):
        raise StaticReTestFailure(
            f"{witness} animation confirmation lost its independently measured "
            "second-capture structural hash"
        )
    if confirmation.get("animated_element_ids_sha256") != hashlib.sha256(
        canonical_bytes(animated_ids)
    ).hexdigest():
        raise StaticReTestFailure(
            f"{witness} animation confirmation records a false animated-ID hash"
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


def test_native_menu_settled_destinations_equal_standalones() -> str:
    golden = _json("tests/fixtures/webgame/menu-goldens.json")
    if golden.get("schema") != "solomon-dark-menu-goldens-v2":
        raise StaticReTestFailure(
            "settled destination contract did not reach a Settlement v2 aggregate"
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
        animated_ids = _assert_settlement_v2_layout(
            entry["layout"], header["settlement"], f"standalone {fixture}"
        )
        _assert_animation_confirmation(header, animated_ids, fixture)
        provenance_sources.append(header["source"])

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
        )
        after_ids = _assert_settlement_v2_layout(
            edge["after"]["layout"],
            edge["after"]["settlement"],
            f"{edge_id}.destination",
        )
        if edge["before"].get("animated_element_ids") != before_ids:
            raise StaticReTestFailure(
                f"{edge_id}.source endpoint summary changed its animated ID set"
            )
        if edge["after"].get("animated_element_ids") != after_ids:
            raise StaticReTestFailure(
                f"{edge_id}.destination endpoint summary changed its animated ID set"
            )
        standalone_layout = by_fixture[destination_fixture]["layout"]
        standalone_ids = _animated_ids_for_layout(
            standalone_layout, f"standalone {destination_fixture}"
        )
        if after_ids != standalone_ids:
            raise StaticReTestFailure(
                f"{edge_id} settled destination animated ID set does not equal "
                f"{destination_fixture}"
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
        "reference hashes, fresh-instance confirmation, and resolvable provenance"
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
