# Native gameplay pause and modal suspension

This report closes the stock gameplay-pause owner for retail 32-bit
`SolomonDark.exe` 0.72.5, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`,
preferred image base `0x00400000`.

## Scope and evidence

The recovered system starts at the configurable `OPEN MENU` input, follows the
in-game pause surface through its modal lifetime, and ends when the same
gameplay region resumes. Evidence is:

- fresh read-only headless Ghidra decompilation and instruction dumps from
  `Decompiled Game/ghidra_project/SolomonDark.gpr`;
- the live native pause layout and frame at
  `tests/fixtures/webgame/menu-layouts/pause-menu.json` and
  `tests/fixtures/webgame/menu-reference-captures/pause-menu.png`;
- the existing fixed-tick graph in
  `docs/reverse-engineering/native-movement-and-tick.md` and input census in
  `docs/reverse-engineering/native-input-model.md`.

The live layout was captured through behavior-neutral UI, Sprite, and bitmap
font observation hooks. Its header records the same retail executable hash,
the exact loader/capture tree, a pristine fresh-install profile, four
independent observed instances, and a settled 1600 by 900 frame. Loader hooks
are capture provenance, not a source for the pause behavior below.

## Causal trace

1. `Gameplay::Tick` `0x005D7EF0` runs the game-state input pass
   `0x005CB360` before the gameplay ActorWorld.
2. `0x005CB3D4..0x005CB42A` reads configurable binding global
   `0x00B3BCCC` and calls the rising-edge sampler
   `GameplayKeyboardEdge_Check` at `0x00429950`. Both shipped keyboard presets
   initialize this binding to DirectInput scan code `0x01` (Escape).
3. The branch is admitted only when the global modal/input exclusion at
   `0x008203F0` is clear, `Gameplay+0x88` is zero, and the gameplay menu-control
   gate at `Gameplay+0xD60` is positive. It dispatches the same UI action as
   the in-world menu control; it does not mutate an actor or synthesize a world
   input.
4. The pause action handler at `0x0058EA50` allocates a `SimpleMenu` through
   constructor `0x005BA4B0` and supplies the complete authored row string:

   ```text
   RESUME GAME[1]|GAME SETTINGS[0]|LEAVE GAME[2]
   ```

5. `SimpleMenu_ModalLoop` at `0x005ABF10` registers the surface through the
   application surface virtual `+0xA8 -> 0x004280E0`, calls gameplay suspension
   helper `0x005CBD40` with `true`, and enters modal runner `0x004281F0`.
6. `0x005CBD40(true)` increments the nesting depth at `Gameplay+0x80` and
   writes `-1` to the active region object's scene-delay field `+0x68`.
   Generic scene dispatcher `0x00427800` ticks only when `scene+0x68 == 0`,
   decrements positive delays, and returns without ticking for a negative
   value. The active region, its ActorWorld, actors, AI, collisions, waves,
   effects, and region-owned clocks therefore retain one exact state.
7. Modal runner `0x004281F0` continues calling MyApp virtual `+0xD0`,
   `0x0040D130`. That path still invokes MyApp scheduler virtual `+0xD4`,
   `0x0040D3C0`, so window messages, UI input, modal animation, rendering, and
   the application loop remain serviced. Pause is a world/region suspension,
   not a stopped process or a blocked networking/audio thread.
8. Selecting `RESUME GAME` returns result `1` and performs no downstream
   transition. `GAME SETTINGS` returns `0` and calls `0x005A81A0`; `LEAVE GAME`
   returns `2` and calls front-end installer `0x005A7F60`.
9. On every modal return, `0x005ABF10` calls `0x005CBD40(false)`. That helper
   decrements `Gameplay+0x80` without underflow and restores active-region
   `+0x68` to zero only when the nesting depth reaches zero. The next ordinary
   fixed tick resumes the retained world. No elapsed pause duration is added,
   and there is no catch-up or pause timeout.

Because the active-modal exclusion at `0x008203F0` is nonzero while the
`SimpleMenu` owns input, another `OPEN MENU` edge does not recursively open or
close the pause menu. Stock resume is the `RESUME GAME` action, not a second
Escape toggle.

## State and timing contract

| State | Native storage/owner | Transition |
| --- | --- | --- |
| menu edge | binding `0x00B3BCCC`, sampler `0x00429950` | one rising edge while the gameplay gates above are open |
| suspension depth | `Gameplay+0x80` | increment on modal entry; decrement without underflow on exit |
| active world hold | active region object `+0x68` | `-1` while depth is nonzero; zero after final release |
| modal result | `SimpleMenu+0x60` through `0x004281F0` | `1` resume, `0` settings, `2` leave |
| reveal alpha | `SimpleMenu+0x78` in `0x005A8950` | add `0.035` per fixed tick, clamp to one; 29 ticks |
| close alpha | same field after close byte `+0x7C` | subtract `0.05` per fixed tick, clamp to zero; 20 ticks |
| underlay dim | `SimpleMenu::Render` `0x005C5A00` | fullscreen black at `reveal * 0.85` |

The native visual is the retained world frame under the dim layer, centered
gold frame, and three rows. At 1600 by 900, the exact action rectangles are:

| Action | Rectangle `[left, top, right, bottom]` |
| --- | --- |
| Resume Game | `[623.5, 339.5, 976.5, 408.5]` |
| Game Settings | `[623.5, 415.5, 976.5, 484.5]` |
| Leave Game | `[623.5, 491.5, 976.5, 560.5]` |

## Reopened SimpleMenu presentation trace

The first Website pause pass stopped after recovering the settled rectangles
and visible art ids. That was not a complete renderer trace. It permitted a
CSS border and translucent panel that stock never submits, an operating-system
font in place of the native font wrapper, a focus/hover highlight stock does
not render, a disabled Settings row, and no pressed or chrome-motion branch.
The reported bad-looking ESC menu reopened this entry. The complete shared
`SimpleMenu` presentation path is now instruction-derived from the same retail
binary and reconciled with the checked-in pause frame.

`SimpleMenu::Render` at `0x005C5A00` has this exact painter sequence:

1. Multiply `SimpleMenu+0x78` by `0.85` and draw the fullscreen black dim;
   restore white, then set the menu draw alpha to `SimpleMenu+0x78`.
2. For every parsed row, draw common-button array entry
   `Button+0x78`. The array at `UI owner +0x40D8/+0x40DC` has exactly two
   entries, loaded consecutively by `0x004F3590`: settled `UI.101` and pressed
   `UI.102`. Both are `353 x 69`.
3. Draw the row surround with `UI.54` through the horizontal strip compositor
   `0x00417E30`: full left and mirrored-right `70 x 85` ends plus a stretched
   quad sampling the record's rightmost five percent. This is not a CSS line
   or an omitted gap.
4. Set RGBA to `(0.85, 0.73, 0.44, 1)` and draw the label through Fonts group
   3 at `Fonts owner +0x0E7D98` (bundle records `216..307`, wrapper header
   `[24,6,28]`, 210 kerning pairs). The normal label origin is the button
   center plus `(0,9)`. While pressed, both label coordinates add exactly
   `6`; hover/focus does not change art or text.
5. Compute `spread = (1 - reveal) * 25 + 40`. Starting from the union of the
   three button rectangles (`x=623.5`, `y=339.5`, `w=353`, `h=221`), build
   the chrome rectangle `x-spread, y-spread, w+2*spread, h+2*spread`.
   Settled chrome is `[583.5,299.5,1016.5,600.5]`; closed chrome is
   `[558.5,274.5,1041.5,625.5]`.
6. Draw the chrome with `UI.17` through four-corner/edge compositor
   `0x00417760`, with its center-fill flag false. The helper draws four full
   `80 x 83` corners, stretches the rightmost five-percent strip across the
   top/bottom gaps, and stretches the bottom five-percent strip across the
   left/right gaps. No separate rectangle, fill, border, or shadow exists.
7. Draw `UI.18` at horizontal center and `chromeTop - 42`, rotated 90 degrees;
   draw `UI.8` at `(centerX, chromeBottom + 55)` and at
   `(centerX +/- 75, chromeBottom + 42)` with the side pair scaled to `0.75`.
   These eight outer members move 25 pixels outward as reveal approaches zero;
   the three button rows stay fixed.
8. Restore white alpha. `SimpleMenu::Tick` `0x005A8950` advances the reveal in
   fixed `0.035` steps and the close in fixed `0.05` steps.

The pressed-state evidence is independent of visual guesswork. Button
constructor `0x00430430` initializes bytes `+0x78/+0x79` to zero; Button input
methods `0x00430890`, `0x00430A40`, `0x00430AC0`, and `0x00430AE0` distinguish
pressed from hover. `0x005C5A00` reads only `+0x78`, uses it as the two-entry
common-button index, and multiplies it by the exact six-pixel label offset.
The full extracted `UI.bundle` catalog independently identifies the adjacent
records as `UI.101` and `UI.102`; the settled live capture identifies index
zero as `UI.101`.

The settled pause-specific art membership is therefore exactly
`UI.101 x3`, `UI.54 x6`, `UI.17 x4`, `UI.18 x1`, and `UI.8 x3`, plus the three
Fonts-group-3 strings. Each of the three mutually exclusive pressed variants
replaces only its row's `UI.101` with `UI.102` and offsets that label. The
captured Hub HUD members below the modal are retained-world presentation, not
pause-menu members.

## Membership sweep

The complete `0x005CBD40` xref sweep found sixteen call sites in twelve
functions. They divide into these owner families:

| Family | Native entries | Relationship to ESC pause |
| --- | --- | --- |
| `SimpleMenu` | `0x005ABF10` | exact pause-menu owner and nested settings/menu owner |
| generic quick-canceller modals | `0x004C2AA0`, `0x004C2E30` | sibling modal framework; shares nesting helper, not the pause-menu input or rows |
| Inventory | open `0x00555810`, close/destruction `0x005684C0` | independently triggered gameplay surface using the same region suspension depth |
| quick panel/settings | `0x005D8DC0`, `0x005D8F30` | independently triggered nested settings surface |
| skill/spell/book selection | `0x006588C0`, `0x0066B200`, `0x0066F0B0`, `0x0066F920`, `0x0067CAC0` | independently triggered mandatory, HUD, or book pickers using the same suspension depth |

The constructor/modal xref sweep also found every consumer of the shared
`SimpleMenu` renderer. Their disposition relative to the ESC system is:

| Consumer | Native entry | ESC-system disposition |
| --- | --- | --- |
| gameplay Pause Menu | `0x0058EA50` | in-system; exact authored three-row instance above |
| Hub-owner menu action | `0x004BB3F0` | out-of-system; independently triggered Hub/profile action |
| title/profile UI owner | `0x005A5530` | out-of-system; separate front-end/profile flow |
| selected-skill Game HUD handler | `0x005D8120` | out-of-system; separate HUD owner which opens `Skills_Quickbar`, not `SimpleMenu` |

They share the renderer facts above. None provides a second pause-menu style,
font, hover rule, or fallback path.

The xref sweep establishes that `Gameplay+0x80` is deliberately nestable. A
pause-menu implementation must not let a child settings surface release the
world before the outer pause owner exits. Inventory and picker presentation
remain separate UI systems; this report does not redefine their rows or
selection logic.

Current Website gameplay has two applicable world members: every Hub region
under the `hub` world and the active Boneyard/Arena under the `boneyard` world.
Title, Create, loading, post-run loadout, and Game Over are separate application
or session surfaces, not consumers of the ESC pause-menu edge. A mandatory
level-up picker owns its own barrier and consumes Escape; the pause menu must
not stack above it.

## Multiplayer extension boundary

Retail 0.72.5 is single-player and supplies no player identity or replication
policy for this menu. The Website multiplayer rule is therefore an explicit
product extension layered over the recovered suspension contract:

- the authoritative game host accepts the first connected gameplay
  participant's pause request and records that participant as the sole owner;
- the host holds the same simulation state and tick with no timeout while
  transport heartbeat, joins, departures, and pause presentation messages stay
  live;
- every peer receives the owner's participant id and display name; the owner
  receives the stock pause actions, while other peers receive a noninteractive
  waiting message naming that owner;
- only the owner can resume; another participant cannot replace or release the
  owner;
- owner disconnect or session teardown releases the barrier, clears every
  queued/held gameplay input, resets the next fixed-tick wall-clock deadline,
  and resumes without catch-up;
- a late joiner receives the current pause owner in its authenticated welcome;
- pause requests are rejected while loading, Game Over, post-run loadout, or a
  mandatory level-up barrier owns the session.

This differs from the loader's older `shared_gameplay_pause_sync.inl` policy,
which aggregates several independent menu surfaces and forces a 60-second
timeout. That loader policy is not evidence for the Website contract and must
not be copied into the browser host.

## Confidence and remaining boundary

Input, owner, state writers/readers, nesting, timing, visual geometry, action
results, and teardown are instruction- or live-fixture-confirmed with high
confidence. The retail binary has no multiplayer branch to extract. The host
ownership and disconnect rules above are designed extension behavior required
by the web multiplayer product, not claims about stock code.

## 2026-08-23 audio-lane reopening

The Website request to mute every non-music sound while the Pause Menu,
mandatory LevelupScreen, or compact selected-skill picker is present reopens
the modal/audio boundary without changing the suspension findings above. A
fresh instruction pass against the same read-only retail project establishes
that this is an explicit Website policy, not an omitted stock call:

- `SimpleMenu_ModalLoop 0x005ABF10` registers the modal, calls
  `0x005CBD40(true)`, runs `0x004281F0`, requests registry stream 131
  `sounds\\MessageDone__Stream` at `0x005AC0B6..0x005AC0C4`, and only then
  calls `0x005CBD40(false)` at `0x005AC0C9..0x005AC0D4`. It never calls either
  audio-volume setter or the audio manager's pause virtual.
- Mandatory LevelupScreen open `0x0067CAC0..0x0067CAED` increments the same
  gameplay suspension depth and requests registry 64 `sounds\\openpanel` at
  gain one. Destructor `0x006588C0` balances the gameplay suspension. Neither
  path changes sound gain, music gain, or global BASS pause state.
- The selected-primary and concentration HUD handler `0x005D8120` builds the
  compact `Skills_Quickbar` through constructor/builder
  `0x00657A70/0x0066F0B0`, runs it through modal owner `0x004281F0`, and tears
  it down at `0x00658DC0`. Its acceptance path owns the recovered `click` and
  `concentrate` requests, but the complete owner/callee trace has no sound-gain
  setter or `Audio::Pause` call.
- `Audio::Pause 0x00407400` is a separate reference-counted device-wide owner
  at `Audio+0x88`. Its zero/nonzero transitions call `BASS_Start` and
  `BASS_Pause`, so using it would pause music together with `Sound`,
  `SoundStream`, and `SoundLoop`. It cannot implement the requested
  "everything but music" behavior.
- The independent persisted/effective lanes remain `Audio+0x7C/+0x84` for
  sound through BASS configs 4/5 and `Audio+0x78/+0x80` for music through
  config 6. A temporary Website modal multiplier must preserve both persisted
  user settings and restore the current sound scalar when the final modal
  owner leaves.

The complete affected Website membership is the local Hub Pause Menu, the
authoritative Boneyard Pause Menu as seen by its owner and waiting peers, the
Dark Cloud Explore Pause Menu that shares the SimpleMenu surface, and the
mandatory level-up barrier from picker opening through its closing/waiting
tail. The compact primary/A/B `Skills_Quickbar` member is covered for its local
owner and for every Website peer waiting on the replicated `skill-selector`
pause source. One-shots, streams, gameplay loops, ambience, voices, and UI
requests all belong to the non-music lane and are silent while that owner is
active; scene music and its crossfade envelope remain live. Inventory, the full
SkillScreen, trader dialogs, ordinary title/create surfaces, and application
focus loss are independent modal or application owners and are not silently
added to this policy.

There is no browser constraint here. The Website already routes resident
buffer playback through one Web Audio master while music uses independent
`HTMLAudioElement` channels. Muting that master is the direct product-policy
implementation. It must mute rather than destroy channels so loop/stream
lifecycle and owner teardown continue normally behind the temporary zero gain.
