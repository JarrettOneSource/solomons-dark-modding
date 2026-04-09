# Solomon Dark UI Engine System Map

This note captures the higher-level UI engine structure recovered so far from `SolomonDark.exe` `0.72.5`.

It exists to answer one practical question for the SD mod stack:

- what engine systems should we hook above the current helper-level overlay so UI snapshots and bounding boxes become reliable

## Scope

- target binary: `SolomonDark.exe`
- image base: `0x00400000`
- primary workspace: `Solomon Dark/Decompiled Game/ghidra_project/SolomonDark.gpr`
- supporting artifacts:
  - `docs/ui-binary-map.md`
  - `ui_decomp_menu_logic.log`
  - `ui_overlay_helpers.log`
  - `ghidra_decomp_darkcloud_owner_funcs.log`
  - `ghidra_decomp_hub_backend_targets.log`

## High-level model

The current evidence points to a layered UI stack:

1. A top-level `Bundle_*` screen or flow object owns the active menu state.
2. A shared global UI and render context owns screen dimensions, layout cursor state, graphics config, and render services.
3. Reusable control-builder helpers construct rows, toggles, selectors, text fields, and section entries inside a screen.
4. Screen-specific bundle methods populate or render concrete menus such as title, pause, settings, controls, inventory, and modal dialogs.
5. Very low-level text and sprite helpers draw the final presentation.

The current overlay is attached at layer `5`. Reliable UI extraction needs to move up to layers `1` through `4`.

## Layer 1: active bundle and screen flow

### Current bundle global

- `DAT_008199E0` is the strongest current-screen anchor recovered so far.
- `FUN_005AF5D0` is a constructor that installs `Bundle_Title::vftable` and then sets `DAT_008199E0 = param_1`.
- `FUN_005B6B00` calls through `*DAT_008199E0`, which strongly suggests bundle lifecycle dispatch through the active bundle object.

### Verified bundle-related functions

- `0x005AF5D0` `FUN_005AF5D0`
  - constructs `Bundle_Title`
  - initializes bundle-owned arrays and sprite containers
  - publishes the live title bundle to `DAT_008199E0`
- `0x005A51B0` `FUN_005A51B0`
  - title-flow update or tick function
  - advances timers and state
  - triggers `FUN_0058DB90()` when the startup sequence reaches the beta dialog stage
  - later calls a bundle virtual at slot `0x18` and then `FUN_0058E8C0()`
- `0x0058E8C0` `FUN_0058E8C0`
  - title-flow state transition dispatcher keyed by `*(param_1 + 0x46c)`
  - branches into at least:
    - `case 1`: title-side transition helper
    - `case 3`: loads `data\\levels\\survival.boneyard`
    - `case 4`: calls `FUN_005AAA30()`
    - `case 5`: exit or return path through `FUN_005A7E30()`
- `0x005B6B00` `FUN_005B6B00`
  - tears down or transitions through the active bundle
  - loads `data\\levels\\Tutorial.boneyard`
  - toggles flags on the created gameplay object

### Implication

The menu system is not just a pile of unrelated text draws. It is driven by active `Bundle_*` objects, and `DAT_008199E0` is the first global we should treat as the current-screen seam.

## Layer 2: shared UI and render context

### Global context

- `DAT_00B401A8` behaves like the engine-wide UI and render context.
- It is referenced by low-level rendering helpers, settings/config functions, and many menu render paths.

### Recovered field roles

These names are descriptive, not final type names:

- `+0x1dc`, `+0x1e0`
  - current backbuffer or viewport width and height
  - repeatedly used when title and settings code prepare fullscreen quads and screen-relative layout
- `+0x238`, `+0x23c`
  - current UI layout cursor or pen position
  - title and menu code moves these fields during row placement
- `+0x184`
  - render-service object used by graphics or settings code through virtual calls
- `+0x3f1`
  - temporary render-state toggle used around text-heavy drawing
- `+0xc7c`
  - graphics settings store or settings branch used for `Graphics.Resolution`
- `+0xd10`
  - dirty or initialized flag used around `Graphics.SaveVideoMemory`

### Verified supporting functions

- `0x0041CE20` `FUN_0041CE20`
  - reads and writes `Graphics.Resolution`
  - consults `Graphics.SaveVideoMemory`
  - directly uses `DAT_00B401A8 + 0xc7c`
- `0x0041D4A0` `FUN_0041D4A0`
  - resolves resolution state and stores it into a settings object
  - uses `DAT_00B401A8 + 0xc7c`
- `0x0041D6A0` `FUN_0041D6A0`
  - validates screen metrics against requested dimensions
  - falls back to graphics config lookups when current settings are unavailable

### Implication

This is the system that answers the earlier camera question.

- For menu UI, the first blocker is not a world camera.
- The first blocker is this screen-space UI context plus the active bundle and widget layer above it.

We may still need extra camera or projection work later for in-run HUD or world-space labels, but menu UI looks primarily screen-space and context-driven.

## Layer 3: shared control-builder layer

The engine has a reusable set of helper functions that appear to build or bind concrete UI controls. These are much better hook candidates than raw text draws.

### Confirmed helper family

- `0x004A58B0` `FUN_004A58B0`
  - lightweight wrapper used immediately after `FUN_00402AE0("...")`
  - likely adds static text or a simple row to the current container
- `0x00437D90` `FUN_00437D90`
  - allocates or attaches a control object through `FUN_004376C0`
  - sets per-control bytes at `+0x34` and `+0x35`
  - likely a generic selectable control or header-style row builder
- `0x00435DE0` `FUN_00435DE0`
  - converts a byte value into `TRUE` or `FALSE` on initial construction
  - later reads updated state back into the same backing byte
  - likely boolean toggle or checkbox binding
- `0x00436160` `FUN_00436160`
  - initial path uses `FUN_00428D70`
  - later reads from `FUN_00435CA0()`
  - likely numeric slider or bounded numeric option binding
- `0x00436310` `FUN_00436310`
  - initial path uses `FUN_00428C30`
  - later reads from `FUN_00435CA0()`
  - likely enum, choice list, or discrete selector binding
- `0x004364C0` `FUN_004364C0`
  - initial path uses `FUN_0042D420`
  - update path uses `FUN_0042D4E0`
  - likely text input or editable string field binding
- `0x004A62A0` `FUN_004A62A0`
  - wraps `FUN_00437D30` and `FUN_004380D0`
  - likely standard option-row builder
- `0x004A5B60` `FUN_004A5B60`
  - wraps `FUN_004366E0` and `FUN_00438410`
  - likely section, category, or grouped entry builder

### Implication

If the goal is a reliable `sd.ui` surface, one productive path is to hook or observe these builders and recover:

- the created control instance pointer
- its label string
- its backing state pointer
- its final computed rect
- its visibility and enabled flags

That is a much cleaner seam than trying to infer controls from text draws after layout has already happened.

## Layer 4: screen-specific menu builders and renderers

### Title and main menu

- `0x00598780` `FUN_00598780`
  - renders the main title menu
  - places visible entries such as:
    - `LAST GAME`
    - `NEW GAME`
    - `SETTINGS`
    - `HALL OF FAME`
    - `BACK`
    - `quit`
  - uses `DAT_008199E0` fields directly, which ties menu rendering to the active title bundle object
  - uses `DAT_00B401A8 + 0x238/+0x23c` style layout state while drawing
- `0x00598470` `FUN_00598470`
  - helper used by the title flow to create and animate menu-side transient entries or particles
  - reads active title-bundle arrays through `DAT_008199E0 + 0x8b8/+0x8bc`

### Beta dialog and modal path

- `0x0058DB90` `FUN_0058DB90`
  - builds the startup beta dialog
  - repeatedly feeds strings into a dialog or row-building path
- `0x004A98E0` `FUN_004A98E0`
  - constructor for `MsgBox`
  - installs `MsgBox::vftable`
  - initializes embedded `String` instances and modal flags
- `MsgBox::vftable` root object
  - verified live root vtable is `0x00788E04`
  - exact panel rect lives at `+0x78/+0x7C/+0x80/+0x84`
  - exact primary button rect lives at `+0xD8/+0xDC/+0xE0/+0xE4`
  - inline button labels live at `+0x22C` and `+0x248`
- embedded child layout
  - `FUN_005AB2C0` computes the root dialog rect and then drives an embedded child widget rooted at `MsgBox + 0xC4`
  - `FUN_005AB5C0` drives another embedded child rooted at `MsgBox + 0x178`
  - earlier reverse engineering confusion around `0x00784544` came from one of these embedded child widgets, not from the live root `MsgBox` object handed to the hooks

This gives us a concrete modal subsystem, not just a title-screen special case.

### Settings and controls

- `0x005D9A50` `FUN_005D9A50`
  - settings menu owner or renderer
  - ties together major categories such as:
    - `Sound and Music`
    - `Video Settings`
    - `Dark Cloud Settings`
    - `CONTROLS`
    - `Performance`
- `0x005DAEF0` `FUN_005DAEF0`
  - concrete controls and options builder
  - uses the control-builder family extensively
  - covers labels such as:
    - `SOUND VOL:`
    - `MUSIC VOL:`
    - `FULLSCREEN`
    - `RESOLUTION`
    - `Dark Name:`
    - `Password:`
    - `MOVE UP`
    - `MOVE DOWN`
    - `MOVE LEFT`
    - `MOVE RIGHT`
    - `OPEN MENU`
    - `OPEN INVENTORY`
    - `OPEN SKILLS`
    - `COMPLEX LIGHTING`
    - `COMPLEX SHADOWS`
    - `MULTIPLE SHADOWS`
    - `LIGHT QUALITY`
    - `ENHANCED EFFECTS`
    - `SAVE MEMORY (REQUIRES RESTART)`
    - `ZOOM EFFECTS`
    - `CAST SECONDARY SPELLS AT MOUSE`
    - `KID MODE (STORY GAMES ONLY)`
- `0x005D8FC0` `FUN_005D8FC0`
  - applies or synchronizes live settings values for at least:
    - `SOUND VOL:`
    - `MUSIC VOL:`

### Implication

The screen-specific functions are good places to understand menu composition, but they are still screen-by-screen logic. The reusable control-builder layer is the better long-term hook boundary.

## Layer 5: low-level draw helpers

- `0x00415130` is the low-level text draw path that the current debug overlay has been using.
- It is useful for discovery, because it proves that a UI element was rendered.
- It is not a stable ownership seam for UI extraction.

This explains the current overlay problems:

- invisible or stale controls can still be inferred from historical helper traffic
- dialog text can be over-grouped into synthetic boxes
- navigation changes can lag because the hook is below semantic menu ownership

The overlay is useful as a seam-discovery tool. It is not the correct foundation for `sd.ui`.

## What this means for hooking

The clean stack for reliable UI extraction now looks like this:

1. Recover and monitor the active bundle object through `DAT_008199E0`.
2. Map the bundle lifecycle slots used for build, tick, render, and transition.
3. Hook or observe shared control builders so newly-created rows and widgets become visible to the loader as semantic controls.
4. Recover final widget rects from the control instances or from the screen-space layout state inside `DAT_00B401A8`.
5. Build a typed `sd.ui` snapshot with:
   - current surface id
   - stable element id
   - label
   - rect
   - visibility
   - enabled state
   - action handle

## Why full camera reverse engineering is not first

For main menus, pause menus, settings, and dialogs:

- the recovered code already shows a dedicated screen-space layout context
- the recovered bundles already own current menu state
- the helper family already looks like a real widget-construction layer

That means reliable menu bounding boxes should come from widget and layout recovery first.

Camera work becomes more important later for:

- world-space HUD markers
- hybrid in-run overlays that mix UI and scene transforms
- any UI surfaces that intentionally live in gameplay camera space

## Highest-value next RE targets

1. Map the `Bundle_Title` and `Bundle_Loader` vtable slots used for build, tick, render, and transition.
2. Recover the base control or widget struct created by `FUN_00437D90` and related helpers.
3. Find where final rects are stored on controls after layout.
4. Map the `MsgBox` internal line container and the secondary-button child path so modal dialogs can be enumerated directly without using observed text rows.
5. Find the bundle switch points for pause, settings, inventory, spell picker, and book picker so the active surface can be identified without relying on text strings.

## Immediate guidance for the SD mod stack

For the next implementation pass, the best architecture is:

- keep `binary-layout.ini` as the seam registry
- add bundle-global and builder-function seams there rather than hardcoding them
- stop improving the helper-only overlay as if it can become exact
- rebuild the overlay and future Lua API on top of the bundle and control layers described above

That is the shortest path to a hygienic `sd.ui` foundation that can support:

- accurate debug bounding boxes
- stable menu snapshots
- Lua-driven UI navigation
- future in-process automation without string-guess heuristics
