# Solomon Dark UI Automation Inventory

This is the authoritative implementation inventory for the `sd.ui` menu automation system.

It exists to answer three questions:

1. What is already on the preferred semantic automation path?
2. What is still transitional or incomplete?
3. What is the ordered cutover list to reach reliable programmatic navigation for every menu, including in-game menus?

## Target architecture

The preferred system is:

- C++ owns surface detection.
- C++ owns element extraction.
- C++ owns live owner/control resolution.
- C++ owns semantic action dispatch.
- Lua consumes `sd.ui` snapshots and action activation only.
- The debug overlay only renders the current semantic snapshot and must not contain unique automation logic.

That means mouse injection, coordinate playback, and Lua-side UI heuristics are not the end state. They are only acceptable as temporary probes while a surface is being moved onto the semantic path.

## Current public seam

The current Lua bridge already exposes the right top-level API in [`src/lua_engine_bindings.cpp`](../SolomonDarkModLoader/src/lua_engine_bindings.cpp):

- `sd.ui.get_surface_id()`
- `sd.ui.get_snapshot()`
- `sd.ui.find_element()`
- `sd.ui.find_action()`
- `sd.ui.get_action_dispatch()`
- `sd.ui.activate_action()`

The underlying loader-owned API lives in [`src/debug_ui_overlay/public_api.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/public_api.inl):

- `TryGetLatestDebugUiSurfaceSnapshot`
- `TryFindDebugUiActionElement`
- `TryGetDebugUiActionDispatchSnapshot`
- `TryActivateDebugUiAction`

Semantic dispatch currently resolves live owners in [`src/debug_ui_overlay/state_and_actions.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/state_and_actions.inl) for:

- `dialog`
- `main_menu`
- `dark_cloud_browser`
- `settings`
- `simple_menu` / `pause_menu`
- `create`

### `sd.ui` contract

The live Lua contract today is:

- `sd.ui.get_surface_id() -> string | nil`
  - returns the dominant root surface id from the latest usable snapshot
- `sd.ui.get_snapshot() -> snapshot | nil`
  - returns `{ generation, captured_at_milliseconds, surface_id, surface_title, elements = [...] }`
- `sd.ui.find_element(label, surface_id?) -> element | nil`
  - best-match lookup by visible label
- `sd.ui.find_action(action_id, surface_id?) -> element | nil`
  - best-match lookup by semantic action id
- `sd.ui.get_action_dispatch(request_id?) -> dispatch | nil`
  - returns the current or last request lifecycle record
- `sd.ui.activate_action(action_id, surface_id?) -> success, request_id_or_error`
  - queues a single-flight semantic activation request

Snapshot elements currently expose:

- `surface_id`
- `surface_root_id`
- `surface_title`
- `label`
- `action_id`
- `source_object_ptr`
- `surface_object_ptr`
- `show_label`
- `left`
- `top`
- `right`
- `bottom`
- `width`
- `height`
- `center_x`
- `center_y`

Dispatch snapshots currently expose:

- `request_id`
- `queued_at_milliseconds`
- `started_at_milliseconds`
- `completed_at_milliseconds`
- `snapshot_generation`
- `action_id`
- `surface_id`
- `status`
- `error_message`

### What belongs in C++ vs Lua

These responsibilities belong in C++ and should stay there:

- surface identification
- widget ownership recovery
- label extraction from live controls/text
- stale-surface eviction
- semantic action id resolution
- owner/control dispatch into the game
- per-surface geometry and layout knowledge

These responsibilities belong in Lua:

- sequencing
- waiting and retry policy at the script level
- assertions about expected surface transitions
- reusable navigation flows composed from semantic actions
- scenario-specific test harnesses

These responsibilities do **not** belong in Lua long-term:

- hardcoded coordinates
- screen-specific geometry inference
- label scraping heuristics
- menu-specific direct memory knowledge
- fallback mouse simulation

## Status key

- `proven`: live snapshot + semantic action dispatch verified in replay or direct use
- `partial`: some exact capture, owner recovery, or dispatch exists, but coverage is incomplete or transitional
- `declared-only`: address/action metadata exists in `binary-layout.ini`, but the surface is not yet a first-class semantic automation surface

## Declared surface matrix

This matrix is the current truth for every surface declared in [`config/binary-layout.ini`](../config/binary-layout.ini).

| Surface | Declared actions | Runtime status | Replay coverage |
| --- | ---: | --- | --- |
| `title` | 8 | partial | title-entry flow is replayed by the title presets, but dedicated end-to-end coverage for the declared `title.*` / `profile.*` follow-through actions is still incomplete |
| `main_menu` | 7 | proven | `title_menu_checkpoint`, `title_menu_to_play`, `title_menu_to_explore_dark_cloud`, `title_menu_to_settings`, `title_menu_to_hall_of_fame` |
| `dialog` | 2 | proven | covered implicitly by all title-entry presets |
| `dark_cloud_browser` | 9 | proven | `title_menu_to_explore_dark_cloud`, `..._search`, `..._sort`, `..._recent`, `..._online_levels`, `..._my_levels`, `..._menu`, `dark_cloud_browser_play`. All 9 actions verified interactive including PLAY (control_offset=0x3D4) and login link (control_offset=0x488). |
| `hall_of_fame` | 0 | partial | `title_menu_to_hall_of_fame` |
| `dark_cloud_search` | 3 | proven | `title_menu_to_explore_dark_cloud_search` |
| `pause_menu` | 3 | partial | `enter_gameplay_pause_menu` screenshot-verifies live gameplay pause entry. Remaining work is recovering the true pause owner/dispatch path instead of aliasing through `simple_menu`. |
| `settings` | 6 | partial | `title_menu_to_settings`, `title_menu_settings_done`, `title_menu_explore_leave_settings_done`, `title_menu_to_settings_customize_keyboard`, `title_menu_to_settings_tweak_game`, `title_menu_to_settings_login_info`. Working actions: `settings.done`, `settings.controls`, `settings.login_info`, `settings.tweak_game`. |
| `controls` | 24 | partial | `title_menu_to_settings_customize_keyboard` proves entry into the controls surface and `MOVE UP` discovery. First-class row semantics and action-by-action replay coverage are still incomplete. |
| `control_scheme_picker` | 1 | partial | reached transitively from `settings.controls`; still shown through the current `controls` / `simple_menu` bridge rather than a clean dedicated surface. |
| `inventory` | 1 | declared-only | `enter_gameplay_inventory` screenshot-verifies gameplay entry. First-class `sd.ui` surface promotion is still incomplete. |
| `skills` | 2 | declared-only | `enter_gameplay_skills` screenshot-verifies gameplay entry. First-class `sd.ui` surface promotion is still incomplete. |
| `spell_picker` | 1 | declared-only | none |
| `book_picker` | 1 | declared-only | none |
| `bonedit` | 0 | declared-only | none |
| `college` | 0 | declared-only | none |
| `control_panel` | 0 | declared-only | none |
| `create` | 8 | partial | `enter_gameplay`, `enter_gameplay_wait`, and the downstream gameplay presets verify character-creation dispatch. Snapshot/surface promotion is still incomplete. |
| `faculty` | 0 | declared-only | none |
| `heartmonger` | 0 | declared-only | none |
| `level_picker` | 0 | declared-only | none |
| `library` | 0 | declared-only | none |
| `memoratorium` | 0 | declared-only | none |
| `storage` | 0 | declared-only | none |
| `game_over` | 0 | declared-only | none |

Additional runtime-only transitional surfaces currently observed by the overlay but not yet formalized in `binary-layout.ini`:

| Surface | Runtime status | Notes |
| --- | --- | --- |
| `simple_menu` | partial | generic modal currently bridging title/profile menus and the live gameplay pause path |
| `quick_panel` | partial | exact control/text capture exists and currently backs `dark_cloud_search`, but it is not yet promoted as its own declared public surface |

## Proven surfaces

### `dialog`

- Status: `proven`
- Why:
  - tracked modal snapshot and exact button geometry are implemented
  - semantic action dispatch exists for `dialog.primary` and `dialog.secondary`
- Primary implementation:
  - [`src/debug_ui_overlay/dialog_tracking_and_snapshots.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/dialog_tracking_and_snapshots.inl)
  - [`src/debug_ui_overlay/public_api.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/public_api.inl)
  - [`src/debug_ui_overlay/state_and_actions.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/state_and_actions.inl)
- Remaining cleanup:
  - validate exact secondary-button layout under a real two-button modal

### `main_menu`

- Status: `proven`
- Why:
  - exact main-menu control observation exists
  - live owner resolution exists
  - semantic activation for title actions is working
  - `quit` is back on the exact overlay path
- Primary implementation:
  - [`src/debug_ui_overlay/control_observers.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/control_observers.inl)
  - [`src/debug_ui_overlay/surface_render_hooks.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/surface_render_hooks.inl)
  - [`src/debug_ui_overlay/tracked_surfaces_and_main_menu.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/tracked_surfaces_and_main_menu.inl)
  - [`src/debug_ui_overlay/label_resolution_and_frame_render.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/label_resolution_and_frame_render.inl)
- Verified actions:
  - `main_menu.play`
  - `main_menu.explore_dark_cloud`
  - `main_menu.settings`
  - `main_menu.hall_of_fame`
  - `main_menu.back`
  - `main_menu.new_game`
  - `main_menu.resume_last_game`
- Remaining cleanup:
  - none at the extraction level
  - title-side follow-through actions still need broader flow verification

### `dark_cloud_browser`

- Status: `proven` for top-level navigation, `partial` for full browser semantics
- Why:
  - exact browser owner/control capture exists
  - semantic dispatch exists and is verified for the core top bar / footer controls
  - sandbox presets are stable for entering the browser and activating `Sort`, `Recent`, `Online Levels`, `My Levels`, and `Menu`
- Primary implementation:
  - [`src/debug_ui_overlay/exact_widget_resolution.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/exact_widget_resolution.inl)
  - [`src/debug_ui_overlay/exact_text_capture_and_hooks.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/exact_text_capture_and_hooks.inl)
  - [`src/debug_ui_overlay/tracked_surfaces_and_main_menu.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/tracked_surfaces_and_main_menu.inl)
  - [`src/debug_ui_overlay/state_and_actions.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/state_and_actions.inl)
- Verified actions:
  - `dark_cloud_browser.search`
  - `dark_cloud_browser.sort`
  - `dark_cloud_browser.recent`
  - `dark_cloud_browser.online_levels`
  - `dark_cloud_browser.my_levels`
  - `dark_cloud_browser.menu`
- Remaining cleanup:
  - promote browser rows and secondary popups to first-class semantic elements
  - make browser list rows actionable by stable semantic ids instead of visual-only boxes

### `dark_cloud_search`

- Status: `proven`
- Why:
  - the browser search modal is now derived from the live `MyQuickCPanel` snapshot instead of opportunistic browser-owned control tagging
  - the semantic surface exposes stable actions for `NAME`, `AUTHOR`, and `SEARCH NOW`
  - replay proof exists for opening the panel and resolving the `SEARCH NOW` action
- Primary implementation:
  - [`src/debug_ui_overlay/modal_surface_render_builders.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/modal_surface_render_builders.inl)
  - [`src/debug_ui_overlay/label_resolution_and_frame_render.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/label_resolution_and_frame_render.inl)
  - [`src/debug_ui_overlay/state_and_actions.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/state_and_actions.inl)
- Verified actions:
  - `dark_cloud_search.name`
  - `dark_cloud_search.author`
  - `dark_cloud_search.search_now`
- Remaining cleanup:
  - add text-entry semantics on top of the focused `NAME` and `AUTHOR` controls if automated search queries become a priority

## Partial surfaces on the preferred path

### `settings`

- Status: `partial`
- Why:
  - exact settings render tracking exists
  - exact section/control geometry exists
  - semantic dispatch is verified for `settings.done`, `settings.controls`, `settings.login_info`, and `settings.tweak_game`
  - settings overlay can render and recover after navigation churn
- Primary implementation:
  - [`src/debug_ui_overlay/overlay_surface_builders.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/overlay_surface_builders.inl)
  - [`src/debug_ui_overlay/exact_widget_resolution.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/exact_widget_resolution.inl)
  - [`src/debug_ui_overlay/string_and_memory_readers.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/string_and_memory_readers.inl)
  - [`src/debug_ui_overlay/tracked_surfaces_and_main_menu.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/tracked_surfaces_and_main_menu.inl)
- Working actions:
  - `settings.done`
  - `settings.controls`
  - `settings.login_info`
  - `settings.tweak_game`
- Verified non-action semantic labels:
  - `Sound and Music`
  - `Video Settings`
  - `Dark Cloud Settings`
  - `CONTROLS`
  - `Performance`
- Remaining cleanup:
  - promote `controls` and `control_scheme_picker` into cleaner first-class surfaces instead of the current transitional follow-through
  - add first-class gameplay follow-through for `settings.select_primary_attack` and `settings.select_concentration`
  - keep extending replay coverage for non-action rows such as `FULLSCREEN` and `RESOLUTION`

### `simple_menu`

- Status: `partial`
- Why:
  - exact control capture and panel geometry exist
  - menu labels now come from parsed definition strings captured before the modal loop, not from fragile draw-time text ownership
  - the browser menu is now confirmed to be a `profile` / title-style simple menu, not a pause menu
  - this is still a transitional modal surface, not a declared surface in `binary-layout.ini`
- Primary implementation:
  - [`src/debug_ui_overlay/modal_surface_render_builders.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/modal_surface_render_builders.inl)
  - [`src/debug_ui_overlay/exact_text_capture_and_hooks.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/exact_text_capture_and_hooks.inl)
  - [`src/debug_ui_overlay/control_observers.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/control_observers.inl)
  - [`src/debug_ui_overlay/dialog_tracking_and_snapshots.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/dialog_tracking_and_snapshots.inl)
  - [`src/debug_ui_overlay/surface_render_hooks.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/surface_render_hooks.inl)
- Current use:
  - browser menu / title-profile modal routing
  - current gameplay pause routing while the real pause owner remains unrecovered
  - title/profile modal routing through the generic `FUN_005ABF10` SimpleMenu runner
- Remaining cleanup:
  - decide whether `simple_menu` remains a runtime-only surface or is normalized into declared surfaces such as `pause_menu` / `profile`
  - recover and track the real semantic owner for title/profile-style simple menus so actions like `profile.main_menu` can dispatch, not just label correctly
  - recover the real in-game pause owner so actual pause actions do not alias through `simple_menu`

### `pause_menu`

- Status: `partial`
- Why:
  - live gameplay pause entry is now screenshot-verified through the Lua sandbox
  - action ids exist in `binary-layout.ini`
  - pause-style semantic expectations still piggyback on `simple_menu`
- Current implementation detail:
  - the browser menu that looked pause-like is now proven to be the title/profile simple menu instead
  - true in-game pause ownership/dispatch is still not recovered as a dedicated first-class surface
- Declared actions:
  - `pause_menu.resume_game`
  - `pause_menu.game_settings`
  - `pause_menu.leave_game`
- Remaining cleanup:
  - recover the real in-game pause surface owner/builder instead of aliasing through `simple_menu`
  - promote gameplay pause snapshots/action dispatch onto a dedicated `pause_menu` surface

### `title`

- Status: `partial`
- Why:
  - title/main-menu flow is mapped
  - profile simple-menu entries now label and identify correctly through parsed menu definitions
  - title-root account/profile/boneyard flows still do not have a verified live owner/dispatch path
- Declared actions:
  - `title.create_dark_account`
  - `title.resume_previous_game`
  - `title.select_boneyard`
  - `profile.resume`
  - `profile.game_settings`
  - `profile.sign_out`
  - `profile.main_menu`
  - `profile.create_new_boneyard`
- Remaining cleanup:
  - prove the non-main-menu title flows end-to-end
  - recover the live owner for `FUN_005A5530`-driven profile menus so `profile.*` actions can dispatch semantically
  - formalize `profile` / account submenus as semantic surfaces instead of one-off labels from nearby screens

## Transitional runtime surfaces not yet formalized in `binary-layout.ini`

### `quick_panel`

- Status: `partial`
- Why:
  - exact control and text capture exist
  - owner and builder traversal exist
  - it is not yet part of the declared public automation inventory
- Primary implementation:
  - [`src/debug_ui_overlay/modal_surface_render_builders.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/modal_surface_render_builders.inl)
  - [`src/debug_ui_overlay/string_and_memory_readers.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/string_and_memory_readers.inl)
  - [`src/debug_ui_overlay/control_observers.inl`](../SolomonDarkModLoader/src/debug_ui_overlay/control_observers.inl)
- Remaining cleanup:
  - identify which gameplay/menu flows own it
  - either promote it to a declared surface or collapse it under a more specific semantic owner

## Additional declared partial surfaces

These surfaces are declared in `binary-layout.ini` and already have some live coverage, but they are not complete first-class automation surfaces yet:

- `controls`
  - entry is verified via `title_menu_to_settings_customize_keyboard`, but per-row semantics and action replay are still incomplete
- `control_scheme_picker`
  - reached transitively from `settings.controls`, but still bridged by the current `controls` / `simple_menu` follow-through
- `create`
  - character-creation dispatch is working through the gameplay-entry presets, but snapshot/surface promotion is still incomplete

## Declared-only surfaces from `binary-layout.ini`

These surfaces have address/action metadata, but they are not yet complete semantic automation surfaces:

### High-priority declared surfaces

- `inventory`
  - gameplay probe exists via `enter_gameplay_inventory`, but the surface is not yet first-class
- `skills`
  - gameplay probe exists via `enter_gameplay_skills`, but the surface is not yet first-class
- `spell_picker`
  - declared action exists for `spell_picker.select_spell`
- `book_picker`
  - declared action exists for `book_picker.select_book`

### Asset-backed or broader screen declarations

- `bonedit`
- `college`
- `control_panel`
- `faculty`
- `heartmonger`
- `level_picker`
- `library`
- `memoratorium`
- `storage`
- `game_over`

These are currently binary anchors, not reliable automation surfaces.

## Lua sandbox coverage today

The sandbox harness in [`mods/lua_ui_sandbox_lab/scripts/main.lua`](../mods/lua_ui_sandbox_lab/scripts/main.lua) is useful, but it is a consumer of `sd.ui`, not the system itself.

Treat [`mods/lua_ui_sandbox_lab/scripts/main.lua`](../mods/lua_ui_sandbox_lab/scripts/main.lua) as the authoritative preset inventory. The preset set changes faster than this note and now spans:

- title/browser semantic flows
- settings semantic flows, including `done`, `controls`, `login_info`, and `tweak_game`
- character-creation and gameplay-entry flows
- gameplay probes for pause, inventory, skills, and hub/testrun entry
- diagnostic snapshot probes

What this means:

- `main_menu`, `dark_cloud_browser`, `dark_cloud_search`, `settings`, and `create` already have replayable coverage
- gameplay menus now have screenshot-verified probe coverage for pause, inventory, skills, and hub/testrun entry, even though those surfaces are not yet first-class `sd.ui` surfaces
- `simple_menu` coverage exists, but is still transitional because its semantic ownership is incomplete

## Ordered full-send execution list

This is the recommended implementation order from here.

1. Recover the real owner/dispatch path for `FUN_005ABF10` simple menus, starting with `FUN_005A5530` profile/title menus and the actual in-game pause owner.
2. Decide whether `simple_menu` remains runtime-only or gets normalized into declared semantic surfaces after owner recovery.
3. Finish `settings` submenu dispatch and replay all declared settings actions.
4. Cut over `controls` as a first-class surface using the shared control-builder layer.
5. Cut over `control_scheme_picker` as a first-class surface.
6. Add semantic browser-row modeling for Dark Cloud browser entries.
7. Formalize title/profile/account/boneyard follow-through surfaces.
8. Promote first-class gameplay surfaces: `pause_menu`, `inventory`, `skills`, `spell_picker`, `book_picker`.
9. Cut over the remaining asset-backed screens only after shared control-builder seams are stable.
10. Expand the Lua-side navigation library so scripts compose waits, surface assertions, and action dispatch without menu-specific logic.
11. Keep [`scripts/main.lua`](../mods/lua_ui_sandbox_lab/scripts/main.lua) authoritative and add replay presets for every promoted surface and every declared action.

## Acceptance bar for “all menus”

A surface is only complete when all of these are true:

- it appears in `binary-layout.ini`
- it can become the dominant `sd.ui` snapshot surface
- all supported visible elements get stable labels and bounding boxes while visible
- stale boxes disappear when the surface is gone
- semantic action ids resolve without Lua-side label guessing
- `sd.ui.activate_action` dispatches the game’s own handler without OS mouse input
- the surface has at least one replay preset that proves entry, interaction, and exit

## Immediate next cutover

The highest-leverage next target is:

- `settings` -> `CUSTOMIZE KEYBOARD` -> `controls` -> `control_scheme_picker`

That path removes the biggest remaining transitional seam in menu automation and unlocks the first real in-game menu family.
