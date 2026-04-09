# UI Overlay — Remaining Work

## High Priority

### Hall of Fame Surface Support — IMPLEMENTED
The HoF surface is now detected and rendered via:
- Ghidra RE identified `HallOfFameBox` vtable at `0x00799264` and renderer at `0x005A2C80` (vtable slot 3)
- Surface defined in `binary-layout.ini` as `[surface.hall_of_fame]`
- Render hook captures the HoF object each frame when the screen is active
- Text capture tags all rendered text as `surface_id="hall_of_fame"` during the HoF render call
- Overlay builder creates bbox elements from captured text (character names, awesomeness scores, boast status, etc.)

**Remaining gaps:**
- Card bounding boxes are text-capture-based, not struct-derived — individual stat lines get their own bboxes rather than grouped card regions
- No interactive actions defined yet (HoF is read-only display)
- WizardData struct offsets (0x114-byte entries with fields at +0x88..+0x110) are mapped but not used for direct memory reading

### Grid Item Row Geometry — IMPLEMENTED (text-capture approach)
Replaced hardcoded pixel constants (`kListContentTop=255`, `kListRowHeight=26`, etc.) with text-capture-based positioning. Entry names from the browser's data array are matched against exact text capture elements. The captured coordinates provide actual rendered positions, which:
- Automatically handles scroll (only visible entries have captured text)
- Uses real pixel coordinates from the renderer (no resolution assumptions)
- Scans up to 256 entries to find matches (vs. the old limit of 16)

### Owner Resolution for Main Menu Button Dispatch — IMPLEMENTED
Added a dedicated render hook for the main menu renderer at `0x00598780` (vtable slot 3). Previously the main menu relied on fragile stack scanning during text draw hooks to discover the live object pointer. The render hook now captures the main menu object reliably each frame with vftable validation (`0x007980CC`), making `TryResolveLiveUiSurfaceOwner` consistently succeed for dispatch.

## Medium Priority

### Surface Registry Refactor — IMPLEMENTED
Introduced `SurfaceRegistryEntry` table and consolidated the major dispatch boilerplate:

**Consolidated:**
- 9-branch if-else cascade in `RenderOverlayFrame` → single loop over `s_surface_registry[]` with per-entry metadata (priority, state-clearing flags, log names)
- 7 per-surface `first_*_frame_logged` booleans → `first_frame_logged` field on each registry entry
- 5-call `Observe*ControlRender` fan-out at 3 call sites → single `ObserveControlRenderForAllSurfaces()` dispatch
- 2 identical simple-render detection blocks (DCB, HoF) → `kSimpleRenderSurfaces[]` table in `BeginExactTextRenderCapture`

**Kept as-is (genuinely different logic):**
- 8 `TryBuild*OverlayRenderElements` functions — each has unique filtering, geometry, and struct-reading logic
- 5 complex detection blocks in `BeginExactTextRenderCapture` (settings, quick_panel, simple_menu, dialog, main_menu) — each has different ownership resolution and caller validation
- Hook installation cascade — mandatory/optional distinction + error cleanup ordering makes table-driving complex for low payoff

Adding a new surface with simple render-hook detection now requires: 1 config entry, 1 binary-layout entry, 1 render hook, 1 builder function, 1 `s_surface_registry` row, and 1 `kSimpleRenderSurfaces` row.

### Spell Picker Surface — IMPLEMENTED
Ghidra RE found the spell picker's vtable at `0x00790B04` with renderer at `0x004FA460` (vtable slot 3, same pattern as all other surfaces). Added render hook, text capture detection (via `kSimpleRenderSurfaces[]`), builder (`TryBuildSpellPickerOverlayRenderElements`), and registry entry. The surface was NOT a "custom modal loop at 0x0066f0b0" — that address was a settings-context function. The spell picker is a standard vtable-dispatched renderer.

## Low Priority

### Quit Button Action
The `quit` label on the main menu renders as `kind=label, interactive=false` because there's no quit action configured in `binary-layout.ini`. Add a config entry if programmatic quit is desired.

### Dark Cloud Browser Row Semantics
The top-level browser tabs are already verified, including `Recent` and `Online Levels`. The remaining browser work is row-level semantics: promote list entries and secondary popups to first-class semantic elements instead of treating them as text-capture boxes.

### Gameplay Surface Promotion
Lua sandbox gameplay probes now cover pause, inventory, skills, and hub/testrun entry. The remaining work is turning those verified probes into first-class `sd.ui` surfaces with direct owner/control recovery, especially the true in-game pause owner rather than the current `simple_menu` bridge.
