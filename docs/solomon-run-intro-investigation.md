# Solomon Run Intro Investigation

Date: 2026-04-21

## Scope

This note focuses on the stock pre-wave intro sequence in `testrun`:

- what happens when the player gets close enough to the Solomon intro owner
- what happens when Solomon finishes talking and the scene hands off into the
  retreat/combat phase

The goal is to pin the actual owner, recover the state machine that runs the
sequence, and record the current live pre-trigger state in a durable form.

## Live Pre-Trigger State

Current live sample from the open game session:

- `scene.kind = arena`
- `scene.name = testrun`
- `world.wave = 0`
- `world.enemy_count = 0`

Current live actor sample:

- `0x1` slot `0` -> local player
- `0x1392` -> lantern-like static scene object
- `0x1391` -> live intro owner candidate at `0x14080130`
- `0x1` slot `1` -> nearby ally/follower rail

Important live proof:

- tracing `0x0048A8B0` hit continuously with `ecx = 0x14080130`
- that means the recovered Solomon intro state machine is executing on the
  current live `0x1391` object
- the same trace captured `eax = 0x866984`, which matches the live
  `0x1391` vtable pointer already sampled through Lua

Current live `0x1391` field snapshot:

- `+0x220 state = 0`
- `+0x2A0 player_acquired = 0`
- `+0x2A4 target_slot = 0`
- `+0x2C0/+0x2C4/+0x2C8/+0x2CC/+0x2D4 = 0`

Current interpretation:

- the open scene is still in the real pre-trigger idle state
- the owner is ticking, but it has not yet acquired a valid player target or
  entered the dialogue branch

## Owner And Type Mapping

Static type anchors:

- `0x1391` -> `Solomon_Dig` ctor at `0x00481C20`
- `0x3EB` -> `SkeletonMage` ctor at `0x0048ABB0`

Current conservative class reading:

- the live pre-wave intro owner is definitely the `0x1391` object
- the recovered state machine helpers around `0x0048A8B0` still look
  SkeletonMage-family in their original construction/field layout
- the cleanest current wording is:
  - the `0x1391 Solomon_Dig` actor owns or reuses a SkeletonMage-derived
    Solomon intro state machine in the live pre-wave run

## Recovered State Machine

`0x0048A8B0` is the main dispatcher for the intro rail.

Recovered state table at `owner + 0x220`:

- `0` -> `0x00481FC0`
- `1` -> `0x0047D0F0`
- `2` -> `0x0047D450`
- `3` -> `0x0047D570`
- `4` -> `0x004857B0`

Additional high-value fields:

- `+0x2A0` -> player-acquired flag
- `+0x2A4` -> chosen gameplay-slot target
- `+0x2A8` -> intro-facing helper / desired heading input
- `+0x2B8` -> retreat/combat-prelude countdown
- `+0x2C0/+0x2C4` -> retreat target position
- `+0x2C8/+0x2CC` -> retreat direction helper
- `+0x2D4` -> retreat move-step scalar

## When Player Gets Close

This is the recovered "walk near Solomon" leg.

`0x0048A8B0` keeps scanning active gameplay-slot actors in the same owner/world
while `state < 3`.

Recovered behavior:

- it tests each gameplay slot actor against an ellipse-style proximity check
- on the first valid candidate it sets `+0x2A0 = 1`
- it stores the nearest valid slot index into `+0x2A4`

State `0` (`0x00481FC0`) is the idle pre-trigger owner:

- maintains an internal timer at `+0x218`
- gates various intro-side presentation timers around `+0x23C/+0x240` and
  `+0x244/+0x248`
- once the timer window and `+0x2A0` acquisition flag line up, it promotes the
  intro into state `1`

State `1` (`0x0047D0F0`) is the actual proximity dialogue gate:

- resolves the selected player slot through `+0x2A4`
- steers the owner's facing (`+0x6C`) toward the cached intro-facing target
- when the facing/proximity gate passes, it flips `+0x220` from `1` to `2`
- on that transition it queues the Solomon intro narration through
  `0x004FCEC0`

Recovered narration branches:

- single-line branch:
  - queues `SAY_SOLOMON_HELLO%d`
- explicit conversation branch:
  - queues `SAY_OHBOYANOTHERWIZARD`
  - queues `SAY_IHAVEBEENDISPATCHED`
  - queues `SAY_ILLDOTHEDISPATCHING`
  - queues `SAY_YOURPERVERSIONS`
  - queues `SAY_TODEATHEXACTLY`

This is the strongest current answer to the first scope item:

- getting close does **not** directly start waves
- it first acquires the nearest player slot, lines Solomon up to face that
  target, and only then promotes into the narrated intro exchange

## When Talk Finishes

This is the recovered post-dialog handoff.

State `2` (`0x0047D450`) is the dialogue-completion gate:

- it still re-enters the state-1 handler each tick while the narration/UI
  globals are busy
- once those globals clear, it snapshots current position into `+0x210/+0x214`
- it promotes the rail into state `3`

State `3` (`0x0047D570`) is the retreat/combat-prelude handler:

- decrements the countdown at `+0x2B8`
- on the first one-shot branch it queues:
  - `SAY_SOLOMON_LAUGH1`
  - optional `SAY_COWARDCOMEBACK`
  - `SAY_GETHIMBOYS`
- it advances the retreat-prelude motion/facing fields
- when that prelude finishes, it:
  - sets `+0x220 = 4`
  - switches the scene into `combat` / `combatprelude`
  - seeds `+0x2C0/+0x2C4/+0x2C8/+0x2CC/+0x2D4` for the run-away path

State `4` (`0x004857B0`) consumes those fields:

- drives the actual run-away motion through the existing movement wrapper
- reuses the same stock move-step path already documented elsewhere

Current conservative conclusion for the second scope item:

- finishing the talk does **not** jump straight into visible enemy waves
- the stock sequence first enters a retreat/combat-prelude phase
- Solomon laughs, switches the scene into combat-prelude state, seeds a retreat
  destination, and then runs away under state `4`

## Notes On `start_waves`

This pass also armed the stock `ArenaStartWaves (0x00465C00)` seam.

Observed result:

- no live `0x00465C00` hit was captured during the current pre-trigger idle
  session

Current interpretation:

- the pre-wave Solomon intro is upstream of the stock `start_waves` seam
- the visible handoff after dialogue is currently better described as
  `dialogue -> retreat/combatprelude -> downstream combat activation`
- the exact downstream point where combat-prelude becomes active wave spawning
  still needs one more live trigger pass

## Next Targets

- trigger the live `0x1391` rail from the current idle state and capture the
  first `0x0047D0F0` hit plus the first `state_220` transition
- follow the first `state 4` completion branch to the exact downstream combat
  activation point
- map the owner-side globals toggled by the `combat` / `combatprelude` setup so
  the wave-start boundary is fully explicit
