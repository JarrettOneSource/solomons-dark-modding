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

## Membership sweep

The complete `0x005CBD40` xref sweep found sixteen call sites in twelve
functions. They divide into these owner families:

| Family | Native entries | Relationship to ESC pause |
| --- | --- | --- |
| `SimpleMenu` | `0x005ABF10` | exact pause-menu owner and nested settings/menu owner |
| generic quick-canceller modals | `0x004C2AA0`, `0x004C2E30` | sibling modal framework; shares nesting helper, not the pause-menu input or rows |
| Inventory | open `0x00555810`, close/destruction `0x005684C0` | independently triggered gameplay surface using the same region suspension depth |
| quick panel/settings | `0x005D8DC0`, `0x005D8F30` | independently triggered nested settings surface |
| skill/spell/book selection | `0x006588C0`, `0x0066B200`, `0x0066F0B0`, `0x0066F920`, `0x0067CAC0` | independently triggered mandatory or settings pickers using the same suspension depth |

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
