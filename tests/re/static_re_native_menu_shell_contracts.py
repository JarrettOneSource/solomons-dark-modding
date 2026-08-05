"""Static contracts for the G11 native boot/menu shell reconstruction."""

from __future__ import annotations

import json
import re
from pathlib import Path

from static_re_contract_support import (
    ROOT,
    StaticReTestFailure,
    assert_recorded_hash_matches_file,
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


def _require(source: str, tokens: tuple[str, ...], contract: str) -> None:
    missing = [token for token in tokens if token not in source]
    if missing:
        raise StaticReTestFailure(
            f"{contract} is incomplete: " + ", ".join(missing)
        )


def test_native_menu_screen_census_and_live_layouts_are_pinned() -> str:
    findings = _read("docs/reverse-engineering/native-menus-and-boot.md")
    golden = _json("tests/fixtures/webgame/menu-goldens.json")
    if golden["schema"] != "solomon-dark-menu-goldens-v1":
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
        if not re.fullmatch(r"[0-9a-f]{40}", header["capture_commit"]):
            raise StaticReTestFailure(
                f"{layout_id} capture commit is not an exact SHA"
            )
        if header["native_exe_sha256"] != (
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
            if not element["id"] or len(element["rect"]) != 4:
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
        "all 28 live screen layouts, references, capture headers, and exact "
        "Raptisoft/loading geometry are pinned"
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
