# Solomon Dark UI Binary Map

This note captures the first-pass Solomon Dark UI recovery work for `SolomonDark.exe` `0.72.5`.

## Scope and method

- Target binary: `SolomonDark.exe`
- Image base: `0x00400000`
- Ghidra project: `Decompiled Game/ghidra_project/SolomonDark.gpr`
- Broad term/xref sweeps:
  - `ui_search_main_menu.log`
  - `ui_search_runtime_ui.log`
  - `ui_search_surfaces.log`
  - `ui_search_account_ui.log`
- Narrowed decompilation:
  - `ui_decomp_menu_logic.log`
  - `ui_decomp_surfaces_a.log`
  - `ui_decomp_surfaces_b.log`

The staged source of truth for recovered addresses now lives in `config/binary-layout.ini`.

## Verified surface anchors

- `title`: `0x004F3210` loads `Title` / `Title@2X`
- `main_menu`: `0x00598780` renders the main menu options and `0x005A0960` renders the `MAIN MENU` / `HALL OF FAME` header layer
- `dark_cloud_browser`: `0x00594FC0` renders the post-beta browser screen with `THE DARK CLOUD`, `RECENT`, `ONLINE LEVELS`, `my levels`, `BONEYARD NAME`, `AUTHOR`, `RATING`, `PLAY`, and `OPTIONS`
- `pause_menu`: `0x0058EA50` renders `RESUME GAME[1]|GAME SETTINGS[0]|LEAVE GAME[2]`
- `settings`: `0x005D9A50` builds `Sound and Music`, `Video Settings`, `Dark Cloud Settings`, `CONTROLS`, and `Performance`
- `controls`: `0x005DAEF0` builds the concrete control-binding UI and `0x005D8120` handles multiple settings/control actions
- `control_scheme_picker`: `0x005B9A30` owns `SELECT A CONTROL SCHEME`
- `inventory`: `0x004EB0F0` loads `Inventory` / `Inventory@2X`; `0x005D08C0` renders the `ACCESS YOUR INVENTORY` HUD prompt
- `skills`: `0x004ED280` loads `Skills` / `Skills@2X`
- `spell_picker`: `0x004FA460` owns `Select a Spell`
- `book_picker`: `0x004F80B0` owns `Select a Book`
- `game_over`: `0x004EA650` loads `GameOver`
- Asset-backed screen builders:
  - `bonedit`: `0x004E41C0`
  - `college`: `0x004E6450`
  - `control_panel`: `0x004E7EF0`
  - `create`: `0x004E8680`
  - `faculty`: `0x004E9EA0`
  - `heartmonger`: `0x004EADD0`
  - `level_picker`: `0x004EBA90`
  - `library`: `0x004EBCC0`
  - `memoratorium`: `0x004EC3B0`
  - `storage`: `0x004F2EB0`

## Verified menu and dialog actions

- Main menu at `0x00598780`:
  - `LAST GAME`
  - `NEW GAME`
  - `SETTINGS`
  - `HALL OF FAME`
  - `BACK`
  - `quit`
- Dark Cloud browser at `0x00594FC0`:
  - `THE DARK CLOUD`
  - `You are signed in as a GUEST.`
  - `To change this, touch here.`
  - `RECENT`
  - `ONLINE LEVELS`
  - `my levels`
  - `BONEYARD NAME`
  - `AUTHOR`
  - `RATING`
  - `PLAY`
  - `OPTIONS`
- Dark Cloud search via the live `MyQuickCPanel` modal (`vftable 0x0079C014`):
  - `NAME`
  - `AUTHOR`
  - `SEARCH NOW`
- Profile/title flow at `0x005A5530` and nearby helpers:
  - `SELECT A BONEYARD[0]`
  - `RESUME[0]|GAME SETTINGS[1]|SIGN OUT[2]|MAIN MENU[3]`
  - `CREATE NEW BONEYARD...`
  - `RESUME PREVIOUS GAME?` via `0x0058F500`
  - `CREATE DARK ACCOUNT` / `Create New Dark Account` via `0x005913A0`
  - `0x005A5530` is also the `DarkCloud::vftable` `0x00797C44` owner/control action dispatcher at slot `+0x10`
- SimpleMenu bridge:
  - title/profile follow-through menus currently resolve through the live `SimpleMenu` owner path
  - gameplay pause also aliases through that bridge today, even though the true in-game pause owner is still a separate remaining gap
- Pause menu:
  - `RESUME GAME[1]|GAME SETTINGS[0]|LEAVE GAME[2]`
- Settings menu at `0x005D9A50`:
  - `DONE`
  - `LOGIN INFO`
  - `Sound and Music`
  - `Video Settings`
  - `Dark Cloud Settings`
  - `CONTROLS`
  - `CUSTOMIZE KEYBOARD`
  - `TWEAK GAME`
  - `Performance`
  - `SELECT A CONTROL SCHEME` via `0x005B9A30`
- Title-settings `CUSTOMIZE KEYBOARD` is an inline rollout built by `0x005DAEF0`
  and toggled through `CPanelRollout::slot+0x10` at `0x00437630`, not a direct
  transition into the `controls` surface.
- Skills/settings actions handled from `0x005D8120`:
  - `Select Primary Attack`
  - `Select Concentration`
- Runtime pickers:
  - `Select a Spell`
  - `Select a Book`

## Verified control-binding globals

Recovered from `0x005DAEF0`:

- `MOVE UP`: `0x00B3BCBC`
- `MOVE DOWN`: `0x00B3BCC0`
- `MOVE LEFT`: `0x00B3BCB4`
- `MOVE RIGHT`: `0x00B3BCB8`
- `OPEN MENU`: `0x00B3BCCC`
- `OPEN INVENTORY`: `0x00B3BCC4`
- `OPEN SKILLS`: `0x00B3BCC8`
- `BELT SLOT 1-8`: `0x00B3BCD0` through `0x00B3BCEC`
- `COMPLEX LIGHTING`: `0x00B3BCA8`
- `COMPLEX SHADOWS`: `0x00B3BCA9`
- `MULTIPLE SHADOWS`: `0x00B3BCAA`
- `LIGHT QUALITY`: `0x00B3BCA4`
- `ZOOM EFFECTS`: `0x00B3BCAC`
- `ENHANCED EFFECTS`: `0x00B3BCAD`
- `CAST SECONDARY SPELLS AT MOUSE`: `0x00B3BCF4`
- `KID MODE (STORY GAMES ONLY)`: `0x00B3BCF5`

`SAVE MEMORY (REQUIRES RESTART)` is present in the controls builder, but the live storage address is not yet pinned to a simple static global in the same way as the other toggles.

## What this gives the SD mod stack

- A config-backed image base for address resolution
- A first-pass catalog of screen identities, action labels, vtables, and control-slot globals
- A semantic `sd.ui` backbone for mapped `dialog`, `main_menu`, `dark_cloud_browser`, `dark_cloud_search`, `settings`, and the current `simple_menu` / `pause_menu` bridge without re-hardcoding coordinates in Lua

## Remaining unknowns

- First-class gameplay surface promotion is still incomplete for `pause_menu`, `inventory`, `skills`, `spell_picker`, and `book_picker`.
- The true in-game pause owner still needs to be separated from the current `SimpleMenu` bridge.
- Browser rows and picker rows still need stable row-level semantics instead of box-only capture.
- Title/profile/boneyard follow-through surfaces are still only partially mapped as first-class semantic owners.
