# Native boot, loading, and menu shell (G11)

This is the implementation contract for the retail Solomon's Dark shell from
process start through the last pre-gameplay picker. It closes browser-rebuild
gap G11 against the retail executable with SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
An implementing agent should use this document together with the checked-in
goldens; opening the binary is not required.

The G11 scope and the Raptisoft-logo shipping decision are in
[`browser-rebuild-roadmap.md`](../browser-rebuild-roadmap.md#6-gap-register-re-campaigns-each-lands-docs--goldens--contracts-on-main).
The owner confirmed on 2026-08-04 that the developers' blessing covers the
logo. The logo is therefore part of the shipped screen, not a placeholder or
an optional legal-safe variant. Website footer wording remains the separate
launch task identified by the roadmap; this campaign does not publish the
website.

## Evidence and coordinate contract

The canonical live artifact is
[`menu-goldens.json`](../../tests/fixtures/webgame/menu-goldens.json). Its
header names every native instance, process, capture commit, executable/DLL
SHA, capture method, capture time, and the SHA-256 of the raw live navigation
recording. It embeds 28 layouts and 39 observed edges. Each layout also exists
as a smaller JSON file under `tests/fixtures/webgame/menu-layouts/`, and each
has a matching PNG under `tests/fixtures/webgame/menu-reference-captures/`.

Unless a section explicitly says otherwise:

- rectangles are live-query results, never screenshot measurements;
- a rectangle is `[left, top, right, bottom]` in the captured `1600 x 900`
  backbuffer; width is `right-left` and height is `bottom-top`;
- `rect` is clipped to the viewport and `unclipped_rect` retains the complete
  transformed draw geometry;
- `art_id` is `<bundle>.<record>` as seen by the native Sprite draw hook;
- `Fonts.93-184`, `Fonts.216-307`, and `Fonts.308-349` identify the native
  bitmap-font wrappers, not inferred operating-system typefaces;
- the complete ordered draw list, visibility, text, text style, font, action
  id, and exact rectangle is the named layout JSON. The PNG is a reference,
  not a source of coordinates.

The live capture methods were: native UI-tree queries; exact native Sprite and
bitmap-text draw hooks; exact-process semantic input; before/after backbuffer
hashes; and, for the two loaders, the actual D3D9 render geometry. Capture-only
seams are opt-in and do not change gameplay or menu behavior.

## Boot sequence

The retail ordering is:

| Order | Native owner | Work and residency | Exit condition / time source |
| ---: | --- | --- | --- |
| 1 | application startup at `0x005BAB60` | Creates the `0x484`-byte `MyLoader`, builds the five-record `Loader` bundle at object `+0x78`, publishes it at singleton `0x008199BC`, stores the loader at `MyApp+0xDA4`, and registers the object with the application lifecycle. `Loader` must therefore be resident before the general asset workload can be shown. | Process initialization; no user gate. |
| 2 | `MyLoader::Render` `0x005BCA40`, vtable `0x00799BDC` | Draws the deep-blue clear, Raptisoft logo, URL, frame, and real progress fill from `Loader.0..3`. Work numerator `0x0081F6A8` and denominator `0x0081F6AC` advance while the remaining native bundles/configuration are built. | Load-bound ratio, not an elapsed-time animation. Completion flag is `0x0081F6B0`. |
| 3 | front-end installer `0x005A7F60` | Once loading completes, installs the front-end. It calls the MainMenu installer `0x005A7D90`, whose constructor is `0x0058D940`; the MainMenu pointer is stored at application `+0xDAC` and registered through `0x004277E0`. The `Title`, `UI`, and font assets used by the first stable frame are resident before it becomes interactive. | Application/controller delta time. Wall-clock sampling in this shell ultimately uses WinMM `timeGetTime`; individual controllers integrate their own `dt` fields. |
| 4 | first-run gate `0x005A84C0` | Chooses whether the control-scheme picker is required. A persisted profile proceeds to the main menu; a fresh profile leaves the control-scheme picker underneath the first modal. | Persisted first-run state. |
| 5 | beta notice modal | Installs the `BETA VERSION V.0.72` dialog above either the main menu or the first-run picker. This modal is the first active click target in the observed build. Dismissing `dialog.primary` reveals the underlying screen. | User input; exact live rect `[702,643.5,898,712.5]`. |

No separate video, publisher carousel, or time-fixed attract slide runs before
the title. A transient white/black frame may appear before D3D9 has presented
the first authored frame; it is swap-chain initialization, not a screen to
reproduce. A hot-cache observation reached title art in well under one second,
but that sample is not a normative duration because the loader is work-bound.

The exact per-file order inside the general asset workload is not needed by
the shell contract and was not reversed. The browser implementation must make
the loader atlas available first, update the progress ratio from actual
completed startup work, and install the first interactive surface only after
its own Title/UI/font dependencies are ready.

## Splash / attract

There is one authored pre-title presentation: the Raptisoft loader. It is both
the splash and the boot progress screen.

| Element | Exact live art / geometry at 1600 x 900 | Meaning |
| --- | --- | --- |
| Background | primitive clear, deep blue (approximately RGB `0,0,0.33`) | Full backbuffer. |
| Logo | `Loader.2`, `[601,302.5,989,529.5]` (`388 x 227`) | Raptisoft logo; centered. |
| URL | `Loader.3`, `[679,541,923,559]` (`244 x 18`) | Centered publisher URL art. |
| Progress frame | `Loader.1`, `[685,553,915,607]` (`230 x 54`) | Decorative frame. |
| Progress fill at the captured 100% state | `Loader.0`, `[704,572,896,590]` (`192 x 18`) | Width is driven by the real numerator/denominator ratio. |
| Unused record | `Loader.4` | Constructed and released, but no live/compiled renderer selection was found. |

The exact layout and reference frame are
[`menu-layouts/native-loader.json`](../../tests/fixtures/webgame/menu-layouts/native-loader.json)
and
[`menu-reference-captures/native-loader.png`](../../tests/fixtures/webgame/menu-reference-captures/native-loader.png).
That fixture was recorded from instance `men-boot1` at capture commit
`d28f98a190d69662c8e6e691484b4d4e0dc939b9` by the live D3D9 Sprite-render
geometry seam.

Duration is load-bound. There is no minimum splash time, no independent
splash timer, and no input branch in `MyLoader::Render` that skips the screen.
Input cannot accelerate or dismiss it. The renderer does not apply a fade-in,
fade-out, wipe, or easing curve to `Loader.0..3`; the first complete authored
frame appears when D3D can render it, and the screen ends when loading
completes.

This live result supersedes the older static-only conclusion in
[`native-presentation-ui-fonts-and-loader.md`](native-presentation-ui-fonts-and-loader.md):
the retail renderer does select records 0 through 3.

## Loading screens

The shell has two distinct loading presentations.

### Stock process-start loader

The stock Raptisoft loader above is real progress. Its fill is
`numerator / denominator` from `0x0081F6A8 / 0x0081F6AC`, clamped by the
renderer. It is neither a time ramp nor synthetic interpolation. It has no
minimum display time and is not skippable.

### Match / Boneyard loading overlay

The loader-owned match overlay records completion of concrete lifecycle
stages. It does not interpolate between them. The 20 monotonic stage values
are:

`connecting_transport .44`, `creating_lobby .48`, `joining_lobby .48`,
`authenticating_session .52`, `establishing_route .56`,
`synchronizing_host_settings .60`, `receiving_host_checkpoint .66`,
`preparing_host .66`, `receiving_run_plan .70`, `preparing_boneyard .73`,
`generating_boneyard .77`, `serializing_boneyard .80`,
`reading_boneyard .83`, `materializing_world .87`,
`receiving_world_checkpoint .90`, `receiving_wave_checkpoint .91`,
`materializing_participants .92`, `waiting_for_participants .95`,
`confirming_participants .98`, and `gameplay_ready 1.00`.

The equal `.48` and `.66` values are intentional alternative paths. The bar
advances only when the corresponding operation reports completion and never
regresses. `GetTickCount64` timestamps evidence; it does not drive the fill.
There is a `150 ms` presentation delay to avoid flashing an overlay for a
trivial operation. That delay is not a minimum time once the overlay is
visible, and there is no artificial hold after `gameplay_ready`.

The exact live `materializing_participants` frame is:

| Element | Exact live geometry / style |
| --- | --- |
| Background | `Wizards_dire_BG`, source `1920 x 1080`, rect `[-0.5,-0.5,1599.5,899.5]` |
| Bottom gradient scrim | `[-0.5,737.5,1599.5,899.5]` |
| Progress border | `[318.5,831,1280.5,841]` |
| Progress track | `[319.5,832,1279.5,840]` |
| `.92` fill | `[319.5,832,1202.7001,840]` |
| Label | `Gathering the coven...`, `[693.25,793.3333,905.75,820]`; Segoe UI, native height `-24`, weight `600`, draw scale `0.833333` |

See
[`menu-layouts/loading-screen.json`](../../tests/fixtures/webgame/menu-layouts/loading-screen.json)
and its reference PNG. The source was live instance `men-load2`, PID `34424`,
at capture commit `933fdd99f0bf85ef06b9ef04c25990bff79966f4`.

Loading owns input. The already-landed uigate contract is authoritative:
[`beta32-ungated-client-interactions-2026-08-04.md`](../bugs/beta32-ungated-client-interactions-2026-08-04.md)
and
[`static_re_ui_interaction_gate_contracts.py`](../../tests/re/static_re_ui_interaction_gate_contracts.py).
`BlockingOverlayOwnsGameplayInput()` seals movement, key edges, both mouse
buttons, casting, and the stock-player bridge. Input received during the
barrier is dropped, never deferred. This document does not re-derive or weaken
that contract.

## Screen census and layout

### Widget and font vocabulary

The live layout schema uses `art`, `text`, and semantic `control`. The loading
fixture additionally uses `gradient_scrim`, `progress_border`,
`progress_track`, and `progress_fill`. Native semantic widgets are:

- rectangular action buttons (`UI.101` body with `UI.54` ends in the common
  panel family);
- continuous sliders (`ControlPanel.18` and the skull thumb);
- two-state toggles (`ControlPanel.8` off, `ControlPanel.9` on);
- action rows with a right arrow;
- key-binding rows that enter a key/mouse-listen mode;
- text-entry rows with a clear `x` affordance;
- tab strips, scrolling list rows, and footer actions;
- modal panels that dim and block the underlying surface;
- dynamic Sprite hit controls for Create, skill, and map choices; and
- whole-screen/one-action continuation on Game Over and Hall of Fame.

Native bitmap-font wrapper `Fonts.93-184` is the medium panel-text group
(`16/4/28` wrapper metrics), `Fonts.216-307` is the menu/dialog group
(`24/6/28`), and `Fonts.308-349` is the large heading group (`40/10/28`).
Older settings/Create/picker labels also use the embedded ControlPanel or
sprite-baked glyphs; no OS font substitution is implied. The exact font ABI is
in
[`native-presentation-ui-fonts-and-loader.md`](native-presentation-ui-fonts-and-loader.md).

### Canonical 28-layout census

Each row below names the exact JSON/PNG basename. The layout file is the
lossless layout specification: it contains every element id, clipped and
unclipped rectangle, text, art id, font wrapper, text style, visibility,
interaction flag, action id, and draw order.

| Layout fixture | Screen / state | Controls and result |
| --- | --- | --- |
| `native-loader` | Raptisoft boot loader | No controls; exits only when real startup work completes. |
| `loading-screen` | Match/Boneyard loading | No controls; exits only when the lifecycle barrier completes. |
| `beta-notice` | `BETA VERSION V.0.72` modal | `OK` / `dialog.primary` dismisses the modal. |
| `control-scheme-picker` | First-run control scheme | Arrow Keys + Mouse and `WASD + MOUSE`; choosing a scheme persists bindings and advances to Create/main flow. The live semantic hit tag covers WASD; both illustrations are exact in the fixture. |
| `main-menu-root` | Main menu | Play, Explore the Dark Cloud, Settings, Hall of Fame, and the visible lower-right Quit affordance. |
| `profile-save-select` | Play/profile/save branch | Last Game resumes the saved session; New Game starts onboarding; Hall of Fame opens scores; Back returns to main. |
| `create-element` | Class/loadout element step | Ether, Earth, Fire, Water, Air; commits one element and exposes the discipline step. |
| `create-discipline` | Class/loadout discipline step | Mind, Body, Arcane; commits the loadout and enters the hub/session. Element hit regions remain attached but are not the active step. |
| `game-settings-title` | Settings over title | Sound/music, fullscreen, selectable resolution, login info, controls, performance, Done. |
| `game-settings-gameplay` | Settings over gameplay | Same, but resolution is the noninteractive message `RESOLUTION AVAILABLE FROM MAIN MENU ONLY`. |
| `game-settings-dark-cloud` | Settings over Dark Cloud | Same gameplay-context restriction; Done restores the Dark Cloud browser. |
| `dark-cloud-settings` | Gameplay Login Info child | Dark Name, Password, Back. |
| `controls` | Customize Keyboard | Movement, menu/inventory/skills, belt slots 1-8, Back. |
| `performance` | Tweak Performance | Lighting/shadow/play-style/effect toggles, optional Light Quality, Back. |
| `dark-cloud-browser` | Initial Dark Cloud list | Menu, login identity link, tabs, level list, Play, Search, Sort, Options. The browser opens **on the Online Levels tab**, so this capture and `dark-cloud-online-levels` are the same rendered state and their reference captures are byte-identical. Do not go looking for a difference. |
| `dark-cloud-recent` | Recent tab | Same shell; Recent selected. |
| `dark-cloud-online-levels` | Online Levels tab | Same shell; Online Levels selected — which is also the browser's entry state, see `dark-cloud-browser`. |
| `dark-cloud-my-levels` | My Levels tab | Same shell; My Levels selected; center action is Edit for a selected/user row. |
| `dark-cloud-search` | Search modal | Name text field and Search Now. |
| `dark-cloud-sort` | Sort modal | Newest, Oldest, Updated Recently, Best Rating. |
| `dark-cloud-options` | Level Options modal | Select a Boneyard; disabled until a compatible row exists. |
| `dark-cloud-login-settings` | Dark Account modal | Dark Name, Password, Sign In, Create New Account, Done. |
| `dark-cloud-menu` | Dark Cloud pause/menu modal | Resume, Game Settings, Sign Out, Main Menu. |
| `pause-menu` | In-session pause | Resume Game, Game Settings, Leave Game. |
| `skill-picker` | Level-up option picker | Three choices normally, four on the bonus path; clicking an offer applies that exact native option and consumes one pending pick. |
| `map-picker` | Stock story/Boneyard picker | One control per unlocked story index; clicking resolves `data\\levels\\story<index>.boneyard`; the start control cancels/toggles the picker. |
| `game-over` | Full story Game Over | Armed input continues the native post-death flow. Boneyard mode intentionally uses the fade-only branch. |
| `hall-of-fame` | Hall of Fame | Main Menu/continue action closes the score screen and reinstalls the title front end. |

**How the Dark Cloud shell marks its selected tab (observed).** Selection is
carried by **two signals that move together**, not one:

1. **The label rises 8 px.** Resting tops are `recent` 166, `online levels` 163,
   `my levels` 166, `multiplayer` 165; selected, the first three read 158, 155,
   and 158.
2. **The tab's `UI.13` bracket pair grows.** Resting brackets span y 136–187
   (51 px tall); the selected tab's pair spans y 128–193 (65 px) — 8 px taller at
   the top, matching the label's rise, and 6 px lower at the bottom.

The brackets' **x never changes**: the eight sprites hold x 460/596, 630/936,
970/1106, 1140/1308 in every tab state, one pair per tab. Only instance ids and
draw orders permute, which is an allocation artifact with no visual consequence.
So a reimplementation moves the label and reshapes the bracket pair vertically,
and never slides a bracket sideways.

**Multiplayer is not a tab.** It was never captured "selected" because it cannot
be: on all four captured browser states it carries **no control element** — the
other three each have a `control.dark_cloud_browser_*` spanning the band, while
Multiplayer has only a band-sized `text` element standing in that slot — and its
brackets are drawn in the **selected (65 px) form in every state** while its
label never leaves its resting baseline. It reads as a permanently-lit,
non-interactive entry in this build. Treat its "raised" baseline as undefined
rather than inferred; there is no observation of it.

Switching between Recent and Online Levels changes no element count. My Levels
does: it drops the `author` and `rating` column headers and swaps the centre
`PLAY` control for `EDIT`, 94 elements against 98.

### Exact art families

These are the visible art-id sets recovered for reconstruction. Repeated
instances and exact rectangles remain ordered in the corresponding fixture.

| Screens | Visible art records |
| --- | --- |
| Main/title | `Title.0,1,2,3,4,5,6,8,9,12,13,16,17,18,19,20,21,22,23,24` plus common `UI.8,17,18,53,54,101,103,107,108,109,110`; main text uses `Fonts.216-307` and `Fonts.308-349`. |
| Beta notice | Title family with `Title.13,14` and the modal art; exact modal label is sprite/text-captured, and button chrome is `UI.101/54`. |
| Profile/save | Title family with state records `Title.11,15`; menu text uses `Fonts.216-307`. |
| Control scheme | `Controls.0` at `[477.5,290,722.5,610]`, `Controls.2` at `[850.5,324,1149.5,576]`, heading `SELECT A CONTROL SCHEME` in `Fonts.308-349` at `[751,21,1127,52]`. `Controls.1` is the alternate compiled record but was not visible in this branch; `Controls.3` is dormant. |
| Create | `Create.0,1,2,5,6,7,16,17,18,20,21,22,23` for discipline state and `Create.3,6,7,9,10,11,12,13,15,20,21,22,23` for element state, plus common panel UI. |
| Common settings/pause panel | `UI.8,17,18,28,42,47,48,54,80/82,100,101,107,108,109,110`, with `Skills.43/48`; values add `ControlPanel.0,8,9,18` as applicable. |
| Dark Cloud shell and overlays | `UI.8,13,17,18,20,29,31,32,42,53,54,58,66,101,103,107,108,109,110` and `ControlPanel.0,8,18`; headings use `Fonts.308-349`, normal labels `Fonts.216-307`, form labels `Fonts.93-184`. |
| Skill picker | `UI.3,28,37,42,47,48,51,59,62,82,100,107,108,109,110`; `Skills.5,13,43,48,83,84,164`; `LevelPicker.0,2,4,5,6`. |
| Map picker | `LevelPicker.1,3`, `UI.28,42,47,48,82,100`, `Skills.43,48`. |
| Game Over | `GameOver.0` and `GameOver.1`; `GameOver.2` is dormant. |
| Hall of Fame | `UI.8,17,18,24,31,32,54,101,107,108,109,110` and `ControlPanel.0,8,18`. |

### Exact primary control geometry

| Screen | Element / action | Live rectangle |
| --- | --- | --- |
| Main | Play / `main_menu.play` | `[673.5,421,1026.5,490]` |
| Main | Explore Dark Cloud / `main_menu.explore_dark_cloud` | `[673.5,497,1026.5,566]` |
| Main | Settings / `main_menu.settings` | `[673.5,573,1026.5,642]` |
| Main | Hall of Fame / `main_menu.hall_of_fame` | `[673.5,649,1026.5,718]` |
| Main | Quit visual | `[1480,834,1580,886]`; glyph `[1503,853,1558,871]` |
| Profile | Last Game / `main_menu.resume_last_game` | `[673.5,421,1026.5,490]` |
| Profile | New Game / `main_menu.new_game` | `[673.5,497,1026.5,566]` |
| Profile | Hall of Fame / `main_menu.hall_of_fame` | `[673.5,573,1026.5,642]` |
| Profile | Back / `main_menu.back` | `[673.5,649,1026.5,718]` |
| Pause | Resume / `pause_menu.resume_game` | `[623.5,339.5,976.5,408.5]` |
| Pause | Game Settings / `pause_menu.game_settings` | `[623.5,415.5,976.5,484.5]` |
| Pause | Leave Game / `pause_menu.leave_game` | `[623.5,491.5,976.5,560.5]` |
| Create element | Ether / Earth / Fire / Water / Air | `[738.303,313.046,914.303,425.046]`; `[568.798,361.651,744.798,473.651]`; `[836.909,459.235,1012.909,571.235]`; `[562.644,537.879,738.644,649.879]`; `[728.346,598.189,904.346,710.189]` |
| Create discipline | Mind / Body / Arcane | `[653,412,797,508]`; `[803,412,947,508]`; `[953,412,1097,508]` |
| Dark Cloud | Menu / login link | `[5,5,55,55]`; `[586,58,1014,108]` |
| Dark Cloud | Recent / Online / My Levels tabs | `[460,128,630,197]`; `[630,128,970,197]`; `[970,128,1140,197]` |
| Dark Cloud | Play/Edit / Search / Sort / Options | `[623.5,809.5,976.5,878.5]`; `[390,818,480,870]`; `[495,818,585,870]`; `[1017.5,818,1202.5,870]` |
| Dark Cloud menu | Resume / Settings / Sign Out / Main | `[623.5,301.5,976.5,370.5]`; `[623.5,377.5,976.5,446.5]`; `[623.5,453.5,976.5,522.5]`; `[623.5,529.5,976.5,598.5]` |
| Skill picker | Three visible offer tiles | `Skills.5` at `[556.5,338.5,643.5,426.5]`, `[756.5,338.5,843.5,426.5]`, `[956.5,338.5,1043.5,426.5]`; the complete 47-element composition is in the fixture. |
| Map picker | Parchment / captured unlocked marker | `LevelPicker.3` `[324,85.5,1276,799.5]`; `UI.28` `[720.317,426.921,795.683,504.079]`; map-specific marker `LevelPicker.1` `[817,457.5,890,511.5]`. |
| Game Over | title art / continue art | `GameOver.0` `[646.5,215.5,953.5,334.5]`; `GameOver.1` `[647,515,953,635]`. |
| Hall of Fame | Main Menu button body | `UI.101` `[623.5,815.5,976.5,884.5]`. |

### Settings domains, actions, and persistence

`Settings` is built at `0x005D9A50`; controls/options are built at
`0x005DAEF0`; audio apply is `0x005D8FC0`. All settings apply on change or on
Done/Back according to the stock control. The browser must preserve these
domains:

| Control | Widget / domain | Action and persistence |
| --- | --- | --- |
| Sound Vol | continuous slider, clamped `0..1` | Sets live sound gain; persists `Audio.SoundVolume`. |
| Music Vol | continuous slider, clamped `0..1` | Sets live music gain; persists `Audio.MusicVolume`. |
| Fullscreen | Boolean toggle | Changes display mode; persists `Graphics.Fullscreen`. |
| Resolution | enumerated supported display modes | Selectable only from title settings; persists `Graphics.Resolution`. Gameplay/Dark Cloud show a disabled explanatory row. |
| Login Info | child action | Opens Dark Name/Password settings; those text values persist in the native profile/config store. Exact native key spellings are not claimed here. |
| Customize Keyboard | child action / title inline rollout | Opens the binding editor; title builds the rollout inline through `0x005DAEF0` and `CPanelRollout` action `0x00437630`. |
| Tweak Game | child action | Opens performance controls. |
| Done / Back | action button | Commits/closes and returns to the invoking surface. |
| Complex Lighting | Boolean | global `0x00B3BCA8`; persists `Game.ComplexLighting`. |
| Complex Shadows | Boolean | global `0x00B3BCA9`; persists `Game.ComplexShadows`. |
| Multiple Shadows | Boolean | global `0x00B3BCAA`; persists `Game.MultipleShadows`. |
| Light Quality | capability-gated numeric/quality value | global float `0x00B3BCA4`; row exists only when capability flag `0x00B3BCAE` permits it; persists `Game.LightQuality`. |
| Cast Secondary Spells at Mouse | Boolean | global `0x00B3BCF4`; changes secondary-placement policy. |
| Kid Mode (Story Games Only) | Boolean | global `0x00B3BCF5`; persists `Game.KidMode`. |
| Enhanced Effects | Boolean | global `0x00B3BCAD`. |
| Save Memory (Requires Restart) | Boolean, restart-required | persists `Graphics.SaveVideoMemory`. |
| Zoom Effects | Boolean | global `0x00B3BCAC`. |

The live performance capture shows: Complex Lighting On, Complex Shadows On,
Multiple Shadows Off, Secondary at Mouse On, Kid Mode Off, Enhanced Effects
Off, Save Memory Off, Zoom Effects On. Those are observed sample values, not
defaults to hard-code.

Binding rows accept one native key/mouse code each and persist through the
native configuration writer. Their storage globals are: left/right/up/down
`0x00B3BCB4/B8/BC/C0`; inventory `0x00B3BCC4`; skills `0x00B3BCC8`; menu
`0x00B3BCCC`; belt 1-8 `0x00B3BCD0..0x00B3BCEC`. The live sample displays
W/S/A/D, Escape, I, T, Right Mouse for slot 1, then numeric keys for the
remaining belt slots. A browser implementation must persist user choices,
not hard-code the sample.

### Picker and end-of-session semantics

The skill picker is the level-up option picker, not the separate Select a
Spell acquisition dialog. Its offer construction, three/four-option rule, and
exact apply sequence are in
[`skill-picker-re.md`](../skill-picker-re.md). Confirming an offered option
decrements the pending count and applies that exact native choice; it does not
bind a belt slot.

The map picker scans exactly 50 unlock bytes, creates one control per unlocked
story index, and resolves a click to
`data\\levels\\story<index>.boneyard`. It does not enumerate arbitrary files.
The full value boundary and cancel path are in
[`map-picker.md`](../re/map-picker.md).

Game Over uses vtable `0x0079B0CC`, renderer `0x005C9030`, and tick
`0x005CF4F0`. Story mode renders the full `GameOver.0/.1` screen; Boneyard mode
may intentionally render only the fade. Boneyard input does not arm until tick
1000. Subsequent Mortuary/Memoratorium, Hall of Fame, and main-menu ownership
is specified in
[`native-game-over-session-semantics.md`](native-game-over-session-semantics.md).
Game Over completion must not be simplified into a direct hub transition.

## Transitions

The table below is the complete **live-recorded navigation graph in this
campaign**. Every row exists in `menu-goldens.json` with the exact action,
dispatch result, observation time, and distinct before/after backbuffer hashes.
Names that describe `beta_notice` are deliberate: two operator labels were
corrected from the actual captured frame rather than preserving a false
destination.

| Edge id | Source | Trigger | Destination |
| --- | --- | --- | --- |
| `control_scheme_picker_to_create` | control scheme | `control_scheme_picker.select_wasd` | create element |
| `create_element_to_discipline` | create element | `create.select_element_fire` | create discipline |
| `create_discipline_to_hub` | create discipline | `create.select_discipline_mind` | hub |
| `hub_to_pause` | hub | Menu key | pause |
| `pause_to_hub_resume` | pause | `pause_menu.resume_game` | hub |
| `pause_to_game_settings` | pause | `pause_menu.game_settings` | settings |
| `settings_to_controls` | settings | Customize Keyboard | controls |
| `controls_to_settings` | controls | Back | settings |
| `settings_to_performance` | settings | Tweak Game | performance |
| `performance_to_settings` | performance | Back | settings |
| `settings_to_dark_cloud_settings` | settings | Login Info / Modify | Dark Cloud settings |
| `dark_cloud_settings_to_settings` | Dark Cloud settings | Back | settings |
| `settings_to_hub` | settings | Done | hub |
| `pause_to_beta_notice` | pause | `pause_menu.leave_game` | beta notice |
| `beta_notice_to_main` | beta notice | `dialog.primary` | main menu |
| `main_to_profile_select` | main | `main_menu.play` | profile/save select |
| `profile_select_to_main` | profile/save | `main_menu.back` | main menu |
| `main_to_settings` | main | `main_menu.settings` | settings |
| `settings_to_main` | settings | Done | main menu |
| `main_to_hall_of_fame` | main | `main_menu.hall_of_fame` | Hall of Fame |
| `hall_of_fame_to_beta_notice` | Hall of Fame | Main Menu | beta notice |
| `main_to_dark_cloud` | main | `main_menu.explore_dark_cloud` | Dark Cloud browser |
| `dark_cloud_to_recent` | Dark Cloud | Recent | recent tab |
| `dark_cloud_recent_to_online` | recent | Online Levels | online tab |
| `dark_cloud_online_to_my_levels` | online | My Levels | My Levels tab |
| `dark_cloud_to_search` | My Levels | Search | search modal |
| `dark_cloud_search_to_browser` | search modal | Menu/back key | My Levels |
| `dark_cloud_to_sort` | My Levels | Sort | sort modal |
| `dark_cloud_sort_to_browser` | sort modal | Menu/back key | My Levels |
| `dark_cloud_to_options` | My Levels | Options | options modal |
| `dark_cloud_options_to_browser` | options modal | Menu/back key | My Levels |
| `dark_cloud_to_login_settings` | My Levels | login identity link | Dark Account modal |
| `dark_cloud_login_to_browser` | Dark Account | Done | My Levels |
| `dark_cloud_to_menu` | My Levels | Menu | Dark Cloud menu |
| `dark_cloud_menu_resume` | Dark Cloud menu | Resume | My Levels |
| `dark_cloud_menu_to_settings` | Dark Cloud menu | Game Settings | settings |
| `dark_cloud_settings_done` | settings | Done | My Levels |
| `dark_cloud_menu_to_beta_notice` | Dark Cloud menu | Main Menu | beta notice |
| `profile_select_resume_to_hub` | profile/save | Last Game | hub |

### Provenance of the recorded screen tags

Each endpoint in the graph carries a `tagged_screen`, and it **is not an
observation** — it is the string the operator passed to
`sd.ui.capture_current_layout`, handed straight back. The binding ends with
`captured.screen_id = std::string(screen_id)`, so the field can never disagree
with whoever ran the recorder. Read it as a label, never as evidence of which
screen the game thought it was on.

The game's own classification is not lost entirely, but it survives in only one
bit. Before stamping the label, `TryCaptureCurrentDebugUiLayoutSnapshot`
compares it against the classifier's `screen_id` through a small alias table
(`profile_save_select`→`main_menu`, `beta_notice` and
`leave_game_confirmation`→`dialog`, the eight Dark Cloud sub-screens→
`dark_cloud_browser`). When they disagree it does two things: it appends
`+ exact live-navigation screen tag (stale controls omitted)` to
`capture_method`, and it **deletes every element that is not `art` or `text`**.

That suffix therefore reads like a stronger provenance claim while actually
marking a weaker capture, and it is the one field that tells you so. **34 of the
78 recorded endpoints carry it.** For those, only `art` and `text` elements
survive, so `element_count` is a stripped remnant of the screen and must not be
read as a census of it. The clearest case is `hall_of_fame_to_beta_notice`,
whose after-state was captured under the label `main_menu` on a state the game
classified `dialog`: its 124 elements are an art/text remnant of a dialog, not a
main-menu layout.

Two further consequences worth stating plainly. `semantic_generation` is `0` on
19 endpoints — there `sd.ui.get_snapshot()` returned nothing, so
`semantic_surface` is empty and only the tagged layout is available. And
`element_count`/`layout_generation` come from the loader's most recently cached
layout snapshot, while `frame_sha256` hashes the backbuffer at the moment of the
call; the two are not sampled atomically. Identical frames can therefore pair
with different counts, and do — `dark_cloud_search` shares one frame hash across
generations 147 and 3345 at 95 and 96 elements, and `dark_cloud_menu` across
generations 3387/3389/3393 at 101 and 100.

Presentation rules recovered to a trustworthy level are:

- the Raptisoft loader has no fade or wipe and is replaced when loading is
  complete;
- the first Title/MainMenu controller uses a native `1.1` entry-fade constant
  and keeps title input gated through its `2.0` controller threshold. These
  values belong to title entry and must not be generalized to every edge;
- common child panels and Dark Cloud dialogs are modal overlays: they dim the
  retained underlay and restore it on dismissal. No wipe was observed;
- ordinary title/profile/simple-menu changes use the native controller fade
  state. The golden graph records the stable state on both sides, not a made-up
  duration or easing curve;
- stock MapPicker cancel calls `0x00500B40` to begin its close fade, then its
  tick/destructor `0x0050E980` restores the Courtyard;
- Hall of Fame input sets its close rate to `1.0`; `HallOfFame::Tick`
  `0x00589CD0` integrates `progress += rate * dt` and installs MainMenu after
  progress exceeds `1.0`, giving a linear one-second close from accepted
  input; and
- Game Over owns its own title/click alpha, input-arm threshold, fade, and
  close dispatch. The browser must preserve the state sequence from the Game
  Over semantics document rather than replacing it with a generic menu fade.

## Focus — designed controller navigation

The retail game is mouse-driven and has no native focus order. **Every rule in
this section is DESIGN — NOT OBSERVED.** The machine-readable mirror is
[`menu-focus-model.json`](../../webgame-contracts/menu-focus-model.json), and
every screen entry in that contract is individually marked
`DESIGN_NOT_OBSERVED`.

This design consumes, and does not redefine, G14's
[`menuNavIntent`](../../webgame-contracts/intent-schema.json): `kind` is
`menu_nav`; commands are `up`, `down`, `left`, `right`, `confirm`, `back`,
`next`, and `previous`, with `press`/`release` phases. Producers may map D-pad,
stick, keyboard, or accessibility input to those verbs. The menu never consumes
raw device events.

| Screen | Provenance | Focus order / default | Wrap | Back / cancel |
| --- | --- | --- | --- | --- |
| Native loader | **DESIGN — NOT OBSERVED** | none / none | none | ignored |
| Match loading | **DESIGN — NOT OBSERVED** | none / none | none | dropped by uigate |
| Beta notice | **DESIGN — NOT OBSERVED** | OK / OK | none | dismisses through the safe primary action |
| Control scheme | **DESIGN — NOT OBSERVED** | Arrow+Mouse, WASD+Mouse / WASD | horizontal wrap | ignored while the first-run prerequisite is active |
| Main | **DESIGN — NOT OBSERVED** | Play, Dark Cloud, Settings, Hall of Fame, Quit / Play | vertical wrap over enabled controls | no-op at root; Quit is explicit |
| Profile/save | **DESIGN — NOT OBSERVED** | Last Game, New Game, Hall of Fame, Back / Last Game if enabled, otherwise New Game | vertical wrap; skip disabled Last Game | activates Back |
| Create element | **DESIGN — NOT OBSERVED** | Ether, Earth, Fire, Water, Air / restored value, otherwise Fire | spatial; `next/previous` use the stable listed order and wrap | returns to profile/save |
| Create discipline | **DESIGN — NOT OBSERVED** | Mind, Body, Arcane / restored value, otherwise Mind | horizontal wrap | returns to element without committing discipline |
| Settings, title | **DESIGN — NOT OBSERVED** | Sound, Music, Fullscreen, Resolution, Login, Controls, Performance, Done / Sound | vertical wrap; left/right adjusts | Done |
| Settings, gameplay | **DESIGN — NOT OBSERVED** | Sound, Music, Fullscreen, Login, Controls, Performance, Done / Sound; disabled Resolution is omitted | vertical wrap; skip unavailable rows | Done to the hub/pause invoker |
| Settings, Dark Cloud | **DESIGN — NOT OBSERVED** | Sound, Music, Fullscreen, Login, Controls, Performance, Done / Sound; disabled Resolution is omitted | vertical wrap; skip unavailable rows | Done to the Dark Cloud invoker |
| Login Info child | **DESIGN — NOT OBSERVED** | Dark Name, Password, Back / Dark Name | vertical wrap | Back |
| Controls | **DESIGN — NOT OBSERVED** | Move Up/Down/Left/Right, Menu, Inventory, Skills, Belt 1-8, Back / Move Up | vertical wrap | cancels key-listen first; otherwise Back |
| Performance | **DESIGN — NOT OBSERVED** | visible rows in screen order, then Back / Complex Lighting | vertical wrap; skip gated Light Quality; left/right or confirm changes values | Back |
| Dark Cloud initial browser | **DESIGN — NOT OBSERVED** | login, enabled tabs, selected list row, Play, Search, Sort, Options, Menu / active tab | left/right wraps within tab/footer regions; up/down crosses regions; next/previous cycles tabs | opens the Dark Cloud menu |
| Dark Cloud Recent | **DESIGN — NOT OBSERVED** | Recent, list rows, Play, Search, Sort, Options, Menu, login / Recent | use the browser regional wrap rules | opens the Dark Cloud menu |
| Dark Cloud Online Levels | **DESIGN — NOT OBSERVED** | Online Levels, list rows, Play, Search, Sort, Options, Menu, login / Online Levels | use the browser regional wrap rules | opens the Dark Cloud menu |
| Dark Cloud My Levels | **DESIGN — NOT OBSERVED** | My Levels, list rows, Edit, Search, Sort, Options, Menu, login / My Levels | use the browser regional wrap rules | opens the Dark Cloud menu |
| Dark Cloud Search | **DESIGN — NOT OBSERVED** | Name, Search Now / Name | vertical wrap | closes without applying and restores Search focus |
| Dark Cloud Sort | **DESIGN — NOT OBSERVED** | Newest, Oldest, Updated Recently, Best Rating / current sort or Newest | vertical wrap | closes without changing sort |
| Dark Cloud Options | **DESIGN — NOT OBSERVED** | Select a Boneyard when eligible / same | none | closes without changing selection |
| Dark Account | **DESIGN — NOT OBSERVED** | Dark Name, Password, Sign In, Create, Done / Dark Name | vertical wrap | Done |
| Dark Cloud menu | **DESIGN — NOT OBSERVED** | Resume, Settings, Sign Out, Main Menu / Resume | vertical wrap over enabled controls | Resume |
| Pause | **DESIGN — NOT OBSERVED** | Resume, Settings, Leave / Resume | vertical wrap | Resume |
| Skill picker | **DESIGN — NOT OBSERVED** | dynamic offered choices left-to-right / first offer | left/right and next/previous wrap across 3 or 4 offers | ignored; the pending choice is mandatory |
| Map picker | **DESIGN — NOT OBSERVED** | unlocked story entries by increasing index / prior valid choice, otherwise first unlocked | nearest spatial neighbor; edge wrap; next/previous wrap by index | stock close/cancel to Courtyard |
| Game Over | **DESIGN — NOT OBSERVED** | Continue only when armed / Continue when armed | none | ignored; confirm is the sole continuation |
| Hall of Fame | **DESIGN — NOT OBSERVED** | Continue / Continue | none | Continue after entry fade is idle |

**DESIGN — NOT OBSERVED modal rule:** a modal traps focus, blocks its underlay,
remembers the invoking control, and restores that focus when it closes.
`back` invokes the modal's cancel action when one exists. It does not leak to
the underlay. A one-action informational dialog may bind `back` to its safe
primary dismissal; destructive confirmations must expose distinct Confirm and
Cancel controls and default to Cancel.

**DESIGN — NOT OBSERVED dynamic-control rule:** disabled, hidden, capability-
gated, or absent controls are omitted from focus traversal. When the current
control disappears, move to the nearest following eligible control, then the
preceding one, then no focus. Text-entry nodes must be real focusable HTML
inputs so the Steam Deck keyboard can open, as required by roadmap section 4.

## Not Yet Reversed

These boundaries are explicit so an implementation does not fill them with
guesses:

- The exact glyph rectangles and semantic hit rectangles for the old
  Settings, Controls, Performance, Create-label, Hall-of-Fame-label, and
  Game-Over prompt paths were not exposed by the stable text/action hook. Their
  exact Sprite geometry and live reference frames are recorded; labels,
  domains, and actions are statically recovered. Do not measure missing
  rectangles from the PNG.
- The Arrow Keys + Mouse control-scheme action did not receive a live semantic
  action tag in the captured branch. Its `Controls.0` layout is exact; the
  static flow proves it is the alternative scheme. The corresponding focus id
  is design, not a claim about a native action string.
- Main-menu Quit and any confirmation screen were not activated in the live
  solo campaign, so no quit edge or confirmation layout is in the golden
  graph. Do not invent one; the designed root Back action is intentionally a
  no-op.
- Profile New Game, first-run control-scheme alternatives, Create choices
  other than the recorded Fire/Mind path, skill-picker close, map-picker
  selection/cancel, and Game-Over continuation were not added to the live
  navigation graph. Their native semantics are cited above, but exact stable
  before/after G11 graph frames remain unrecorded.
- Dark Cloud Multiplayer did not activate in the observed guest build. Sign
  Out was ineligible as Guest, Play/Edit had no selected compatible row, and
  Create New Dark Account was not followed. These controls are visible but
  their downstream layouts/edges are not claimed.
- Exact fade duration/easing for ordinary Main/Profile/Settings/Dark Cloud
  edges was not captured. The stable edge, overlay-vs-replacement behavior,
  and known special timers are pinned; do not apply the title `1.1/2.0`
  constants globally.
- The exact order of every asset file loaded between the loader numerator
  increments was not reversed. Progress is conclusively real and load-bound;
  a browser implementation should report its own equivalent real startup work
  rather than copying native increment granularity.
