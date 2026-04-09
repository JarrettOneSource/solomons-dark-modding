# Debug UI Overlay

The debug UI overlay is a launcher-owned, opt-in runtime diagnostic for Solomon Dark.

## Ownership

- The launcher owns staging `config/debug-ui.ini` into `runtime/stage/.sdmod/config/`.
- The loader owns parsing the staged config, installing the runtime hooks, observing UI draw activity, and rendering the overlay in-process.

## Config-driven seams

`config/debug-ui.ini` keeps Solomon Dark-specific debug overlay seams out of C++ source:

- `enabled`
- `text_draw_helper`
- `device_pointer_global`
- `title_main_menu_vftable`
- `title_main_menu_button_array_offset`
- `title_main_menu_button_stride`
- `title_main_menu_button_count`
- `title_main_menu_button_left_offset`
- `title_main_menu_button_top_offset`
- `title_main_menu_button_width_offset`
- `title_main_menu_button_height_offset`
- `title_main_menu_mode_offset`
- `msgbox_vftable`
- `msgbox_panel_left_offset`
- `msgbox_panel_top_offset`
- `msgbox_panel_width_offset`
- `msgbox_panel_height_offset`
- `msgbox_primary_button_left_offset`
- `msgbox_primary_button_top_offset`
- `msgbox_primary_button_width_offset`
- `msgbox_primary_button_height_offset`
- `msgbox_secondary_button_left_offset`
- `msgbox_secondary_button_top_offset`
- `msgbox_secondary_button_half_width_offset`
- `msgbox_secondary_button_half_height_offset`
- `msgbox_primary_label_offset`
- `msgbox_secondary_label_offset`
- `dark_cloud_browser_vftable`
- `surface_range_slop`
- `max_tracked_elements_per_frame`

The text helper address, `MainMenu` button offsets, `MsgBox` offsets, and D3D9 device global are treated as binary seams. They should be updated from reverse engineering artifacts, not hardcoded in the loader.

## Runtime architecture

The overlay is intentionally structured to keep the hot path light when enabled:

1. The x86 text helper hook resolves the active UI surface from the live call stack and records per-element observations.
2. Element observations are aggregated by stable widget identity when available, then filtered to the dominant active surface before a frame is rendered.
3. The dialog hooks track `MsgBox` line and button construction into a durable modal snapshot, while the tracked dialog renderer rereads the live root `MsgBox` object for exact panel and primary-button rectangles.
4. The D3D9 `EndScene` hook prewarms the font atlas once and renders overlay primitives once per frame.
5. The overlay is disabled by default so the normal launcher and loader path pay no render cost.

This keeps resource setup and draw submission out of the text helper path and leaves the loader with one render pass per frame instead of many immediate draws.

## Verification

Default-off workspace verification:

```powershell
pwsh ./scripts/Verify-Workspace.ps1 -Configuration Debug -LaunchAndVerifyLoader
```

When `config/debug-ui.ini` is temporarily set to `enabled=true`, a live launch should produce loader log markers showing:

- debug UI config load
- D3D9 hook installation
- first frame callback
- font atlas prewarm
- first helper interception
- first observed frame summary
- first tracked dialog render when the beta modal is active

Recommended capture commands:

```powershell
py -3 .\scripts\capture_window.py --title SolomonDark --output .\runtime\debug-ui-current.png --method window
py -3 .\scripts\capture_window.py --title SolomonDark --output .\runtime\debug-ui-screen.png --method screen --activate
```

## Current limits

- The overlay is now the live `sd.ui` snapshot/action backbone for `dialog`, `main_menu`, `dark_cloud_browser`, `dark_cloud_search`, `settings`, and the current `simple_menu` / `pause_menu` bridge. `sd.ui.activate_action(action_id, surface_id)` resolves the live widget from the current snapshot and dispatches the game's own owner/control handler instead of simulating a mouse click.
- The centered title-menu buttons come from exact embedded `Button` objects inside `MainMenu::vftable` `0x007980CC`: array at `MainMenu + 0x78`, stride `0xB4`, rect fields at `Button + 0x14/+0x18/+0x1C/+0x20`, state selection at `MainMenu + 0x3FC`, and activation through the owner vtable slot at `+0x10`.
- The beta `MsgBox` panel and primary `OK` button come from exact live root-object fields on `MsgBox::vftable` `0x00788E04`: panel at `+0x78/+0x7C/+0x80/+0x84`, primary button at `+0xD8/+0xDC/+0xE0/+0xE4`, and activation through the owner vtable slot at `+0x10`.
- The Dark Cloud browser actions come from exact browser child controls and dispatch through `DarkCloud::vftable` `0x00797C44`, slot `+0x10` (`0x005A5530`).
- The Dark Cloud search panel is now promoted from the live `MyQuickCPanel` modal snapshot into stable `NAME`, `AUTHOR`, and `SEARCH NOW` semantic actions instead of piggybacking on browser-owned text tags.
- The settings surface now resolves actionable rows such as `DONE`, `CUSTOMIZE KEYBOARD`, `LOGIN INFO`, and `TWEAK GAME` from exact control/text capture and dispatches them through the live settings owner.
- The overlay still draws most modal body lines from observed text positions rather than from the internal `MsgBox` line container, so dialog text rows are improved but not yet a full child-list enumeration.
- The remaining incomplete areas are the title/profile/boneyard follow-through surfaces, the true in-game pause owner/dispatch path, first-class gameplay surface promotion for `inventory`, `skills`, `spell_picker`, and `book_picker`, and stable row semantics for browser/picker lists.
- The authoritative surface-by-surface implementation status and cutover order now lives in `docs/ui-automation-inventory.md`.
- The higher-level hook targets for extending coverage are documented in `docs/ui-engine-system-map.md`.
- Secondary-button dialogs still need the exact secondary-child layout validated under a live two-button modal before the remaining modal path can be called complete.
