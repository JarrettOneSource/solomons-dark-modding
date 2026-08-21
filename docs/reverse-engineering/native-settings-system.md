# Native Settings system

## Scope and provenance

This report closes the retail Settings owner, all of its root and child
controls, persistence, context branches, and lifetime. Addresses refer to the
retail `SolomonDark.exe` 0.72.5 image based at `0x00400000`, size `4,723,200`
bytes, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.

The static pass used program `SolomonDark.exe` in
`Decompiled Game/ghidra_project/SolomonDark.gpr` through the read-only replica
pool and Ghidra 12.0.3. Fresh 2026-08-21 headless queries covered
`0x005A81A0`, `0x005D8DC0`, `0x005D8F30`, `0x005D8120`, `0x005D8FC0`,
`0x005D9A50`, `0x005DAEF0`, `0x00407190`, `0x004072B0`, `0x0041CE20`, and
`0x005BAB60`, plus every settings label and persistence-key xref.

Live presentation evidence is the settled `game-settings-title`,
`game-settings-gameplay`, `game-settings-dark-cloud`, `controls`, and
`performance` fixture family under `tests/fixtures/webgame/`. Each fixture is
bound to the same executable hash and has an independent confirmation run.
For example, title Settings was captured as process `13876` at
`2026-08-09T16:21:55.2124704Z`, settled for 40 structurally constant samples,
and confirmed by process `17980`. The corresponding reference PNGs are the
visual oracle; injected menu hooks supplied structure and are not treated as
clean-stock behavior evidence on their own.

## Owner, entry, suspension, and teardown

`MyCPanel` owns Settings. Its vtable is `0x0079BEDC`; the relevant adjacent
slots are:

| Vtable slot | Function | Responsibility |
| ---: | ---: | --- |
| `+0xB4` | `Settings_Render 0x005D9A50` | Builds the root Settings rollouts and the embedded Controls/Performance definitions. |
| `+0xB8` | `0x005D8FC0` | Reads the two live audio sliders and applies their values to the Audio manager. |
| `+0xBC` | `Controls_Render 0x005DAEF0` | Reads the complete root/control/performance state and writes it to display, input, lighting, and gameplay globals. |

`0x005A81A0` allocates exactly `0x204` bytes, constructs the panel through
`0x005D8DC0`, and installs it through the application owner at vslot `+0xA8`.
The constructor installs `MyCPanel::vftable`, initializes the panel children,
and, when Gameplay exists, calls the shared suspension owner with `1`.
Destructor `0x005D8F30` calls the same owner with `0`, releases the panel
children, and destroys the base. Thus title Settings is a modal title child;
gameplay Settings retains the already-paused world until the panel dies.

The in-session SimpleMenu returns `0` for `GAME SETTINGS` and dispatches
`0x005A81A0`; title and Dark Cloud edges reach the same panel owner through
their own callers. `SettingsControl_HandleAction 0x005D8120` routes Login,
Performance, Customize Keyboard, Select Primary Attack, Select Concentration,
and the in-game pause handoff. Child panels return to the still-live Settings
owner. Done destroys that owner and returns to its invoker; it does not create
a second independent settings store.

## Complete semantic membership

### Root Settings rows

| Member | Native construction/application | State and behavior |
| --- | --- | --- |
| Sound Vol | `0x005D9A50`; apply `0x005D8FC0 -> 0x004073A0` | Continuous `0..1` user gain. It multiplies the independent effective sound lane and applies to one-shots, loops, streams, and active channels. Persisted as `Audio.SoundVolume`. |
| Music Vol | `0x005D9A50`; apply `0x005D8FC0 -> 0x00407340` | Continuous `0..1` user gain. It multiplies the independent effective music lane. Persisted as `Audio.MusicVolume`. |
| Fullscreen | `0x005D9A50`; display apply `0x005DAEF0 -> 0x0041D4A0` | Boolean display mode, persisted as `Graphics.Fullscreen`. |
| Resolution | `0x005D9A50`; display apply `0x005DAEF0 -> 0x0041D4A0` | Enumerated supported modes. Selectable only when title, Gameplay/Dark Cloud instead show `RESOLUTION AVAILABLE FROM MAIN MENU ONLY`. Persisted as `Graphics.Resolution`. |
| Login Info | control `MyCPanel+0x22C`; `0x005D8120 -> 0x005C6F10` | Opens Dark Name/password settings when its optional enabled pointer permits it. |
| Customize Keyboard | control `MyCPanel/Game owner +0xD4C`; `0x005D8120` | Title builds the rollout inline through `0x005DAEF0` and `CPanelRollout 0x00437630`; gameplay uses the same binding family under the held pause owner. |
| Tweak Game | control `+0x2EC`; `0x005D8120 -> 0x005CA640` | Opens the Performance child when its optional enabled pointer permits it. |
| Select Primary Attack | control `+0x3AC`; `0x005D8120` | Gameplay-only picker using the live learned-primary set. The selected primary is committed through the player/progression owner. |
| Select Concentration | controls `+0x46C` and sibling `+0x52C`; `0x005D8120` | Gameplay-only concentration picker with the native eligibility and active-concentration paths. |
| Done | `0x005D9A50` | Closes the root, returning to title, Dark Cloud, or the held gameplay invoker. |

### Customize Keyboard rows

Every row below is built and applied by `0x005DAEF0`. The settings writer
persists one native key/mouse code per row.

| Row | Global | Persisted key / shipped fresh value |
| --- | ---: | --- |
| Move Up | `0x00B3BCBC` | `Game.Controls.KeyboardUp=17` (`W`) |
| Move Down | `0x00B3BCC0` | `Game.Controls.KeyboardDown=31` (`S`) |
| Move Left | `0x00B3BCB4` | `Game.Controls.KeyboardLeft=30` (`A`) |
| Move Right | `0x00B3BCB8` | `Game.Controls.KeyboardRight=32` (`D`) |
| Open Menu | `0x00B3BCCC` | `Game.Controls.Menu=1` (`Escape`) |
| Open Inventory | `0x00B3BCC4` | `Game.Controls.Inventory=23` (`I`) |
| Open Skills | `0x00B3BCC8` | `Game.Controls.Skills=20` (`T`) |
| Belt slots 1..8 | `0x00B3BCD0..0x00B3BCEC`, stride four | `513,2,3,4,5,6,7,8`: Right Mouse, then keys `1..7` |

The bindings are user state, not a hard-coded sample. The live `controls`
fixture's retained Performance labels are a measured history-bound panel
artifact; they do not add Performance rows to the Customize Keyboard domain.

### Tweak Performance rows

| Row | Global/store | Missing-key default on shipped Windows | Native consequence |
| --- | --- | --- | --- |
| Complex Lighting | `0x00B3BCA8`, `Game.ComplexLighting` | on | Enables analytic object tint, directional-record construction, and the early light composite. Off forces common world tint to white and moves the still-present raster composite after the shared queue. |
| Complex Shadows | `0x00B3BCA9`, `Game.ComplexShadows` | on | Gates class painters' consumption of directional records. |
| Multiple Shadows | `0x00B3BCAA`, `Game.MultipleShadows` | platform capability, on | Supplies the directional/containment-bypass flag for every provider marked `MS`; it does not affect providers with literal true/false flags. |
| Light Quality | float `0x00B3BCA4`, `Game.LightQuality` | `0.25f` on the capable path, otherwise `0.05999999865889549f` | Controls light-target resolution and the manager query/raster transform. The row exists only when capability byte `0x00B3BCAE` permits it. |
| Cast Secondary Spells at Mouse | `0x00B3BCF4`, `Game.CastSecondariesOnMouse` | on | Selects cursor/world-point secondary placement instead of the non-pointer policy. |
| Kid Mode (Story Games Only) | `0x00B3BCF5`, `Game.KidMode` | off | Story-only gameplay policy; the live Gameplay owner mirrors it into its active story state. |
| Enhanced Effects | `0x00B3BCAD`, persisted under `Game.FastCPU` | platform capability, on | Controls effect density and the specific provider/shadow branches catalogued by the lighting, projectile, weather, and spell reports. |
| Save Memory (Requires Restart) | application `+0x49C`, `Graphics.SaveVideoMemory` | off | Changes native texture/video-memory retention and is applied on process restart. |
| Zoom Effects | `0x00B3BCAC`, `Game.ZoomFX` | on | Gates native world/camera pulse effects; it is not a camera field-of-view setting. |
| Back | Settings child action | Applies the child values and restores the still-live root Settings panel. |

Platform capability byte `0x00B3BCAE` is set for the recognized `WIN`, `MAC`,
and `LINUX` paths. The preserved retail sandbox settings are a user override,
not the fresh-profile oracle: they explicitly store Multiple Shadows off,
FastCPU/Enhanced Effects off, and Light Quality `0.060000`.

## Persistence and live application

Audio load/save is separate from the 37-line process `settings.txt` writer:
`0x00407190` reads `Audio.SoundVolume` and `Audio.MusicVolume` into Audio
manager `+0x7C/+0x78`; `0x004072B0` writes them. Settings apply calls
`0x004073A0/0x00407340`, so changing a slider affects the live channel system,
not only future sounds.

Display initialization `0x0041CE20` reads Resolution, Fullscreen, and
SaveVideoMemory. Configuration initialization `0x005BAB60` owns the remaining
presentation, gameplay, and keybinding defaults and settings registration.
The fully decoded 37-row `settings.txt` order and values live in
`tests/fixtures/webgame/save-format-goldens.json`; credentials, process/network
identity, resume state, and UID rows are persistence siblings but are not
Settings-menu presentation members.

## Context and presentation membership

The semantic settings system has three root layouts and two child families:

| Layout | Context branch |
| --- | --- |
| `game-settings-title` | Title backdrop retained; Resolution selectable. |
| `game-settings-gameplay` | Gameplay retained and suspended; Resolution replaced by the main-menu-only message; gameplay skill-selection actions may be present. The settled core is history-bound after visiting children. |
| `game-settings-dark-cloud` | Dark Cloud shell retained; Resolution restricted; Done returns to Dark Cloud. |
| `controls` | Customize Keyboard rows and Back. |
| `performance` | Lighting, play-style, special-effects rows and Back. |

The exact root visual family consumes `ControlPanel.0,8,9,18`, common
`UI.8,17,18,28,42,47,48,54,80/82,100,101,107,108,109,110`, and context
underlay records from Title, Skills/LevelPicker, or Dark Cloud. The settled
title fixture specifically contains `ControlPanel.0 x4`, `ControlPanel.18 x2`,
`ControlPanel.8 x1`, `UI.17 x4`, `UI.18 x4`, `UI.101 x4`, `UI.54 x8`, and its
Title underlay. The Performance reference contains four `ControlPanel.8` and
four `ControlPanel.9` toggles for the captured on/off state. Exact per-instance
rectangles and draw order remain owned by the fixture JSON, not duplicated
here.

The stable hook did not expose exact glyph or semantic hit rectangles for
every old ControlPanel label. Reference frames, label/domain strings, builder
calls, and atlas records are exact; inferring missing rectangles from pixels
would not be. This is the only remaining presentation unknown and does not
leave a semantic setting, state branch, asset family, or persistence row
unclassified.

## Native-system boundary

Settings owns local process preferences and their menu/controller lifecycle.
It does not own simulation save identity, online account authority, the Audio
registry, renderer implementations, individual shadow/light providers, spell
mechanics, or the learned-skill picker internals. Those systems consume
settings values through the globals and callbacks above. Closing or replacing
Settings must preserve those consumer boundaries rather than moving their
state into the panel.
