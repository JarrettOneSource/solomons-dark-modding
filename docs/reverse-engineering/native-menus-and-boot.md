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
header names every native instance, process, machine-derived capture commit and
tree, executable/DLL SHA, profile-state identity, capture method, capture time,
and the SHA-256 of the raw live navigation recording. It embeds 27 ordinary
standalone layouts, three path-qualified Hub layouts, one non-semantic overlay,
one semantic-dialog composite, and 40 observed edges. Layout records also exist as smaller JSON files
under `tests/fixtures/webgame/menu-layouts/` or
`tests/fixtures/webgame/menu-transition-layouts/`, with matching native frames
under `tests/fixtures/webgame/menu-reference-captures/`. The overlay pins its
own paired player-visible frames and explicitly has no semantic members. The
composite pins its semantic underlay, complete dialog contribution, measured
dismissal control, and zero-residual decomposition. The
settle and classification rules are normative in the
[`native menu settlement specification v2.19`](native-menu-settlement.md).

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
The paired fixture headers record their current machine-derived commit/tree,
binary hashes, pristine profile identity, and live D3D9 Sprite-render geometry
seam.

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
and its reference PNG. Its paired special-capture headers carry the same
machine-derived provenance and settle receipts as the ordinary menu corpus.

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

### Canonical 30-layout, one-overlay, and one-composite census

Each row below names the exact JSON/PNG basename. The layout file is the
lossless layout specification: it contains every element id, clipped and
unclipped rectangle, text, art id, font wrapper, text style, visibility,
interaction flag, action id, and draw order.

| Layout fixture | Screen / state | Controls and result |
| --- | --- | --- |
| `native-loader` | Raptisoft boot loader | No controls; exits only when real startup work completes. |
| `loading-screen` | Match/Boneyard loading | No controls; exits only when the lifecycle barrier completes. |
| `beta-notice` | Qualified pause-entry `BETA VERSION V.0.72` screen | `OK` / `dialog.primary` dismisses the modal. |
| `control-scheme-picker` | First-run control scheme | Arrow Keys + Mouse and `WASD + MOUSE`; choosing a scheme persists bindings and advances to Create/main flow. The live semantic hit tag covers WASD; both illustrations are exact in the fixture. |
| `main-menu-root` | Main menu | Play, Explore the Dark Cloud, Settings, Hall of Fame, and the visible lower-right Quit affordance. |
| `profile-save-select` | Play/profile/save branch | Last Game resumes the saved session; New Game starts onboarding; Hall of Fame opens scores; Back returns to main. |
| `create-element` | Class/loadout element step | Ether, Earth, Fire, Water, Air; commits one element and exposes the discipline step. |
| `create-discipline` | Class/loadout discipline step | Mind, Body, Arcane; commits the loadout and enters the hub/session. Element hit regions remain attached but are not the active step. |
| `hub_pristine_second_new_game` | Hub reached by first-run Hub -> Main Menu -> New Game -> Create -> Hub in one pristine process | Exact 15-member settled state before projection; includes the five full-presence LevelPicker members and motion-capable `UI.28`. |
| `hub_new_game` | Hub reached by direct New Game under the pristine-derived Annalist/Fomentius baseline | Exact 14-member minimum settled state; `UI.27`/`UI.88` ambient draws may raise the raw sample census without changing the path core. |
| `hub_resumed` | Hub reached from durable resumed-run state | Exact 10-member settled state before projection; contains motion-capable `UI.28`. |
| `game-settings-title` | Settings over title | Sound/music, fullscreen, selectable resolution, login info, controls, performance, Done. |
| `game-settings-gameplay` | Settings over gameplay | Same, but resolution is the noninteractive message `RESOLUTION AVAILABLE FROM MAIN MENU ONLY`. It has three exact history-bound cores because visited child headings remain visible. |
| `game-settings-dark-cloud` | Settings over Dark Cloud | Same gameplay-context restriction; Done restores the Dark Cloud browser. |
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

`dark_cloud_settings_credentials` is the separate overlay record. Activating
the measured Login Info / Modify row displays the credentials panel, but the
menu-member hook continues to expose the underlying surface and cannot observe
the panel's widgets. The record therefore pins its frames, route, settled
underlay agreement, and zero semantic members; it is not counted as a layout.

`beta_notice_first_boot` is the semantic-dialog composite. On pristine first
boot the same 28-member dialog is drawn over the five-member
`control_scheme_picker` underlay. Both fresh instances reproduce the exact
33-member decomposition, dialog frame, post-dismissal picker frame, and
measured `dialog.primary` control. It is a typed state and is not another
layout fixture.

The populated Hall row contract was closed separately on 2026-08-20. Rows are
sorted by descending `AWESOMENESS`, with a later-loaded equal score inserted
before equal rows already traversed, capped at 100, and toggle between a
collapsed rank/wizard/name/level/discipline/Awesomeness summary and expanded
survival details: time, wave, three highest skills, monsters killed, awesomest
kill, and the 3-by-3 perks-used grid. The retail distribution's populated
sample rendered `VOLUSIUS`, level 1 Seer, 91 Awesomeness, time `0:05:39`, wave
1, 17 kills, and Skeleton as the awesomest kill. See
[`native-hall-of-fame-and-memoratorium.md`](native-hall-of-fame-and-memoratorium.md)
for addresses, collection behavior, and the separate dormant Social
leaderboard loader.

The rendered class title is the complete lookup at `0x00658B40`, not the raw
discipline label: Ether is Sage/Seer/Occultist, Fire is
Warlock/Pyromancer/Fire Mage, Air is Stormcaller/Astrologer/Storm Mage, Water
is Icebinder/Thaumaturge/Frost Mage, and Earth is
Ritualist/Channeler/Earth Mage for Body/Mind/Arcane respectively.

Awesomeness is its own `Game+0x1C38` counter, not an experience delta. Enemy
retirement awards a pulse-gated base point plus a new-maximum-health bonus,
then applies the exact low-health and level-scaled kill-streak multipliers.
Potion use resets the streak. The full writer, Region-pulse membership, enemy
name formatter, and story-only 1.1 archive adjustment are recorded in the
same report. Time starts with the Game-wide Hub clock and serializes on Player
death tick 300. That writer also consumes the exact signed heading and scale
draws used by the archived wizard composite.

The following bounds are the larger measured settle latency from each
layout's primary/confirmation pair. They are evidence-derived recorder times,
not animation durations or fixed waits:

| Layout | Paired settle-latency bound (ms) | Layout | Paired settle-latency bound (ms) |
| --- | ---: | --- | ---: |
| `beta-notice` | 16114 | `control-scheme-picker` | 17033 |
| `controls` | 16355 | `create-discipline` | 15950 |
| `create-element` | 16022 | `dark-cloud-browser` | 16327 |
| `dark-cloud-login-settings` | 16105 | `dark-cloud-menu` | 16091 |
| `dark-cloud-my-levels` | 16524 | `dark-cloud-online-levels` | 16309 |
| `dark-cloud-options` | 16129 | `dark-cloud-recent` | 16406 |
| `dark-cloud-search` | 16167 | `dark-cloud-sort` | 16242 |
| `game-over` | 16042 | `game-settings-dark-cloud` | 16124 |
| `game-settings-gameplay` | 16035 | `game-settings-title` | 16172 |
| `hall-of-fame` | 16241 | `loading-screen` | 2469 |
| `main-menu-root` | 16162 | `map-picker` | 16165 |
| `native-loader` | 2407 | `pause-menu` | 16513 |
| `performance` | 15869 | `profile-save-select` | 16188 |
| `skill-picker` | 17181 | `hub_new_game` | 16095 |
| `hub_pristine_second_new_game` | 15889 | `hub_resumed` | 15910 |

The credentials-overlay underlay held its equal text/action payload across
15,883 ms and 15,835 ms paired 40-sample spans. Its player-visible truth is
the paired frame record, not a synthetic member-layout latency.

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
| Skill picker | Three visible offer tiles | `Skills.5` at `[556.5,338.5,643.5,426.5]`, `[756.5,338.5,843.5,426.5]`, `[956.5,338.5,1043.5,426.5]`; the complete fresh-baseline composition, animated family, and choice slots are in the fixture. |
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
may intentionally render only the fade. In Boneyard mode the tick method
synthesizes acceptance internally when its counter becomes exactly 1000 and
begins the 400-tick exit fade on that same tick; it does not arm or await user
input. Subsequent Mortuary/Memoratorium, Hall of Fame, and main-menu ownership
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
| `beta_notice_first_boot_to_control_scheme_picker` | first-boot beta dialog composite | measured `dialog.primary` | control scheme picker |
| `control_scheme_picker_to_create` | control scheme | `control_scheme_picker.select_wasd` | create element |
| `create_element_to_discipline` | create element | `create.select_element_fire` | create discipline |
| `create_discipline_to_hub` | create discipline | `select_discipline_mind` | baseline-qualified `hub_new_game` or `hub_pristine_second_new_game` |
| `hub_to_pause` | hub | Menu key | pause |
| `pause_to_hub_resume` | pause | `pause_menu.resume_game` | hub |
| `pause_to_game_settings` | pause | `pause_menu.game_settings` | gameplay settings `base` |
| `settings_to_controls` | settings | Customize Keyboard | controls |
| `controls_to_settings` | controls | Back | settings |
| `settings_to_performance` | gameplay settings `base` | Tweak Game | performance |
| `performance_to_settings` | performance | Back | gameplay settings `performance_retained` |
| `settings_to_dark_cloud_settings` | gameplay settings `performance_retained` | Login Info / Modify | typed credentials overlay |
| `dark_cloud_settings_to_settings` | typed credentials overlay | Back | gameplay settings `performance_dark_cloud_retained` |
| `settings_to_hub` | gameplay settings `performance_dark_cloud_retained` | Done | `hub_resumed` |
| `pause_to_beta_notice` | pause | `pause_menu.leave_game` | beta notice |
| `beta_notice_to_main` | beta notice | `dialog.primary` | main menu |
| `main_to_profile_select` | main | `main_menu.play` | profile/save select |
| `profile_select_to_main` | profile/save | `main_menu.back` | main menu |
| `profile_select_new_game_to_create` | profile/save | `main_menu.new_game` | create element |
| `main_to_settings` | main | `settings_click` | settings |
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

### Capture-time identity and route guardrails

The recorder now treats an operator screen tag only as an expectation. It
accepts a standalone or edge endpoint only after the machine classifier reports
the same semantic surface (through the bounded native alias table), and every
navigation step verifies its intended destination before the next action can
run. A mismatch aborts immediately with the measured point, machine surface,
operator tag, and frame. The recorder never strips controls, retags a foreign
surface, or continues a route after an unverified dispatch.

This closes the failure that produced the rejected Controls candidate. The old
driver queued `main_menu.settings` but retained only a request id; its source
capture already classified as `main_menu` even though a Settings panel was
visible. It then reused the operator-supplied point `(1015,586)`. On the
machine-classified payload that point intersected only the main menu's third
button plate and ornament, with no interactive control. The native modal owner
still displayed Customize Keyboard, while the old capture API rewrote a stable
`main_menu` remnant to the operator tags `settings` and then `controls`. The new
destination check and classifier/tag agreement gate reject that sequence before
any fixture exists. The clean rerun instead binds both Controls edges and the
standalone to the same reproduced 55-member core and exact `Wizard Controls`
title.

Click coordinates are now derived from the unique visible live member or
control being activated and are stored with the route. Semantic actions are
accepted only with their completed app-tick dispatch receipt. Browser endpoints
add the measured six-member tab-state check because the broad surface
classifier cannot distinguish Recent from Online Levels. Every header also
pins the machine-derived profile-state identity. The pristine baseline contains
no copied durable files; another baseline is legal only when deterministic,
receipted in-game actions derive it from pristine state and its resulting file
identity is registered for that exact layout or edge binding.

### Why the old snapshots were wrong

The earlier four-second capture raced two different mechanisms on Create. A
fresh `control_scheme_picker_to_create` trace first populated the destination:
at its earliest measured phase, the settled layout was still missing the exact
art members `Create.21/.9/.23/.13/.10/.12/.20/.11/.15/.3/.22/.14` and all eight
Create element/discipline controls. That one-way ramp is late population. Once
the 30-member destination existed, the native transition spawned 66 temporary
`Create.4` draws, captured as
`create_element.art.create_4.1` through `.66`, then destroyed them one by one;
the final transient phase contained only `.1` before the stable 30-member
window. Both fresh instances reproduced that sequence. The landed 34-member
edge destination was therefore the settled destination plus four of these
transition-overlay draws—not outgoing control-scheme members and not late rows.

The old 45-member Create standalone had a separate defect. Its 15 extra
`UI.107/.108/.109/.110`, four `UI.17`, `UI.18`, three `UI.8`, `UI.101`, and two
`UI.54` draws never appeared in any Create population or settled window. Their
complete non-id semantic multiset equals the independently captured beta-dialog
chrome, and removing that multiset deterministically recompacts the surviving
draw sequence to the settled layout. Thus the standalone was captured with the
stock beta dialog undismissed; it was overlay contamination, not transition
population. Overlay matching is semantic because screen-local ordinal ids are
positional bookkeeping. Pause legitimately shares 11 of the same atlas
suffixes, so suffix intersection is not identity; only the complete overlay
semantic multiset triggers hygiene rejection.

The beta notice itself has two qualified forms, not one path-tolerant screen.
On pristine first boot, the member system reports `control_scheme_picker` and
the dialog contributes an exact 28-member semantic multiset above its
five-member underlay; dismissing the measured `dialog.primary` control reveals
the picker. That 33-member state is therefore a v2.17 semantic-dialog
composite. The pause-menu Leave Game route instead produces the qualified
28-member `beta_notice` screen. The old 34-member fixture was a main-menu
underlay capture from the contaminated era and is retired, not generalized.

Create's stable census still moves. In both instances the seven full-presence
members `create_element.art.create_7.1`, `.14.1`, `.15.1`, `.20.1`, `.21.1`,
`.22.1`, and `.23.1` varied only in `rect`/`unclipped_rect`; every other field
and the member set remained fixed. The fixture pins their identities, static
payloads, first-window anchors, and union motion envelopes. It does not freeze
one arbitrary frame. Animation waveform and period remain the G4/animre seam.

Title surfaces need the wider ambient-lifecycle model. `Title.11`-`.15`
sparkle/ember draws spawn and despawn; higher `Title.17`-`.24` ordinals are
instance-local particles; scroll-wrap members can toggle visibility; and those
changes uniformly displace absolute draw-order numbers beneath stable dialog
chrome. Contracts therefore assert the reproduced structural core and its
relative paint sequence, while ambient members carry draw bands, anchors,
events, and union envelopes. Absolute draw order and raw element-list position
are excluded. The five-minute paired Settings-title extension additionally
observed `Title.5` disappear and reappear in both instances, proving a real
scroll-wrap lifecycle rather than a quiet-window constant.

Motion capability is asymmetric. Hub's `UI.28` stayed stationary in one short
window but moved in another; an 85.8-second, 200-sample corroboration then
recorded two motion events. One real event proves capability, while a quiet
window cannot prove immobility. The resolved animated classification is shared
by every fixture of that screen. Skill Picker adds the one authorized animated
family: eight byte-identical `UI.3` draws exchange synthetic ordinals and cross
geometry ranks in both instances, so the fixture pins their collective count,
slot set, payload, and union envelope. Its two roster-dependent offer positions
are separate v2.8 choice slots whose anchors, offsets, atlas namespace, and
asset-manifest centering reproduce even when skill art differs.

Finally, gameplay Settings has deterministic structural history rather than
animation. Returning from Performance retains the exact `TWEAK PERFORMANCE`
heading; opening and returning from Login Info then also retains `DARK CLOUD
SETTINGS`. Each 28/29/30-member state settles in both instances and each graph
endpoint binds to one exact state. No filter removes these player-visible
members, and no state binding is inferred from time.

The absolute `generation` counter is different: it does not render and is not
screen identity. The first picker pair both measured 1, but deeper equal-route
pairs showed session-cumulative, instance-timing-sensitive drift from -2
through +2 in both directions. Ten of 30 standalone pairs and 24 of 76 layout
edge endpoints differed while each individual 40-sample window held its own
value constant. Settlement v2.19 therefore records the primary fixture value
and both observation values as provenance, but excludes only `generation` and
its semantic mirror from cross-instance identity after projecting both sealed
windows to an exact-equal core multiset and relative sequence with zero
residual. All 34 disagreeing pairs pass that machine proof, including the
fresh Skill Picker pair at 18 and 20. A mid-window change, a hand-edited
fixture value, or any non-generation core difference still stops; recapturing
until counters happen to agree is forbidden counter-shopping.

All current provenance is recorder-derived. Each fixture carries the actual
repository commit and tree plus hashes computed from the staged game executable
and loader DLL. Operators cannot supply or override those values. Each header
also cites the exact profile-state receipt, traces, confirmation, reference
frame, and measured settle latency; contracts re-hash every committed file and
refuse duplicate or ambiguous evidence lookup.

The capture commits came from several isolated, qualified campaign worktrees,
so their exact objects are preserved rather than replaced with the eventual
landing commit. Evidence artifact `menufix-capture-source.bundle`, Windows
SHA-256
`c9d521db6917d1ff997604aaf7038537a510673548a5bd091ad315e7ac78fb50`,
is a thin Git bundle over prerequisite `c24fc3cc`. A prerequisite-only replica
was proven not to contain the capture objects; importing the eight exact bundle
heads then recovered all 15 recorded commit/tree objects with their declared
Git types. This makes the machine-derived revisions re-inspectable without
pretending the final landing commit existed at capture time.

The web shell is intentionally not rewritten by this campaign. During the
shellfix task #101 interregnum, the exact pre-menufix bytes of all 28 historical
menu fixtures, their 28 reference captures, and the embedded shell aggregate
live under `webgame-contracts/baseline-snapshots/`. Each committed file is
hash-pinned by `webgame-contracts/menu-baseline.json`. Existing shell replay
and human visual attestations remain bound to those exact snapshot hashes.
Settled truth is separately enumerated as exactly 29 `pending_shellfix` states:
27 screen fixtures, the Dark Cloud Settings non-semantic overlay, and the
first-boot beta-notice composite. That is the exact old-28-minus-retired-screen-
plus-overlay-plus-composite delta. A changed snapshot, a missing or wrong
pending hash, or any census other than 28 historical snapshots and 29 settled
states fails. The old ten-screen stale-control waiver no longer exists; task
#101 must consume the settled fixtures and then remove this explicit
compatibility boundary.

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
- Game Over owns its own title/click alpha, mode-specific acceptance, fade, and
  close dispatch. Normal story mode has armed input; Boneyard mode has the
  internal tick-1000 edge. The browser must preserve the state sequence from
  the Game Over semantics document rather than replacing it with a generic
  menu fade.

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
