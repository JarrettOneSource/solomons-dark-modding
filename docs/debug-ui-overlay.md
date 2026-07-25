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
5. The native UI bridge may stay active for semantic `sd.ui` snapshots and
   functional multiplayer HUDs, but diagnostic surface registration is a
   separate capability. The `full` runtime profile sets
   `loader.debug_ui=false`; only an explicit runtime-flag override can register
   and draw observed diagnostic surfaces or loader status text.

This separation is structural: normal gameplay can observe a stock surface for
automation without turning that surface into a loader-owned quad. In
particular, level-up barrier text is constructed inside the same diagnostic
registration function as observed stock-surface overlays. When
`loader.debug_ui=false`, that function returns before either surface is
constructed. Death-spectator status is deliberately not part of this registry:
it is player-facing product UI rendered through the retail panel and exact-text
functions only while the local owner is in the `Spectating` phase.

The complete native D3D9 surface audit is:

| Surface class | Normal-session policy | Reason |
| --- | --- | --- |
| Observed stock UI labels and panels | Diagnostic gate | Automation and acceptance observability |
| Level-up barrier wait text | Diagnostic gate | Loader status text; stock picker remains authoritative |
| Death-spectator target/click hint | Product, spectator-only | Required target and input affordance; uses retail panel/text rendering |
| Participant health bars | Functional | Multiplayer combat information |
| Dampen rings | Functional | Replicated gameplay effect |
| Join consent and loading covers | Functional | Required launcher join-flow interaction |

The product spectator renderer first proves render target 0 is the swap-chain
backbuffer. It skips offscreen `EndScene` passes, so a summon or spell render
target cannot inherit or duplicate the HUD. Resource setup and draw submission
stay out of the text helper path, and the loader retains one shared callback
pass rather than many immediate draws.

## Diagnostic logging policy

Runtime automation logs should stay quiet enough for live play and frame-rate
testing. High-frequency bot movement, path-follow, HUD callback, and local
player cast-probe diagnostics are compiled out by default through the gameplay
diagnostic constants in `src/mod_loader_gameplay/core/gameplay_constants.inl`.
Enable those constants only for a focused investigation, then rebuild and
restore them before normal verification.

## Verification

Default-off workspace verification:

```powershell
pwsh ./scripts/Verify-Workspace.ps1 -Configuration Debug -LaunchAndVerifyLoader
```

Normal live acceptance also checks each staged loader log with
`tools/normal_gameplay_debug_surface_guard.py`. Every normal process must
report:

```text
Debug UI diagnostic surface set. enabled=0 registered=0 rendered=0
```

The gate fails if the marker is missing or if any diagnostic surface is enabled,
registered, or rendered. It also rejects any successful level-up-wait or
legacy diagnostic death-spectator draw even if the diagnostic-set counters
claim zero.
The guard exposes the complete normal-session context matrix—menu, join/lobby,
alive, dead, and spectating—so live gates can record the same invariant for
every peer.

The separate product-surface marker is:

```text
Product spectator HUD surface. active=1 phase=Spectating registered=1 rendered=1 target_participant_id=2305843009213698050
```

`tools/spectator_product_hud_guard.py` requires
`registered=rendered=1` only for the local dead owner's `Spectating` phase.
Menu, join/lobby, alive, five-second `DeathPresentation`, and respawned states
must remain `registered=rendered=0`; living observer peers must never report a
visible product spectator surface. Live gates also inspect the normalized
backbuffer HUD region for the native gold text pixels. This makes a successful
state marker insufficient by itself: clipped, invisible, or actor-migrated
output fails the acceptance run.

When `config/debug-ui.ini` is enabled and the staged runtime explicitly sets
`loader.debug_ui=true`, a live launch should produce loader log markers showing:

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
