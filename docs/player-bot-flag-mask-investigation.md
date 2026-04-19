# Player vs Bot Flag Mask Investigation

Date: 2026-04-15

## Scope

This note investigates the stable mismatch between player and gameplay-slot bot
actor fields at:

- `actor + 0x38`
- `actor + 0x3C`

The goal is to answer three questions:

- what these fields currently hold for player and bot actors
- how stock code writes them
- what behavior the mismatch can change, especially for navigation and
  placement queries

## Live Baseline

Settled shared-hub baseline:

- player
  - type `0x1`
  - slot `0`
  - radius `25.0`
  - `+0x38 = 0x1`
  - `+0x3C = 0x1`
- gameplay-slot bot
  - type `0x1`
  - slot `1`
  - radius `25.0`
  - `+0x38 = 0x0`
  - `+0x3C = 0x0`
- roaming Student
  - type `0x138A`
  - slot `0`
  - radius about `13.4..16.2`
  - `+0x38 = 0x0`
  - `+0x3C = 0x0`

The player and bot matched on:

- actor family (`0x1`)
- owner/world pointer
- radius (`+0x30 = 25.0`)

The mismatch at `+0x38/+0x3C` therefore is not caused by actor size or a
different collision radius.

The mismatch was stable across:

- fresh settled hub
- after bot movement through the normal bot path-follow flow

Raw memory windows also matched the semantic readers exactly:

- player
  - `+0x38 = 0x00000001`
  - `+0x3C = 0x00000001`
- bot
  - `+0x38 = 0x00000000`
  - `+0x3C = 0x00000000`

## Stock Writer: `0x0052B900`

`0x0052B900` (`PlayerActor_EnsureProgressionHandleFromGameplaySlot`) is the
main recovered stock writer for these fields.

Recovered behavior:

- it only writes `+0x38` and `+0x3C` when:
  - `actor == gameplay + 0x1358`
  - i.e. when `ECX` is the slot-0 actor pointer
- it then writes slot-bit masks derived from `actor + 0x5C`:
  - slot `0` -> `1`
  - slot `1` -> `2`
  - slot `2` -> `4`
  - slot `3` -> `8`

Critical consequence:

- even when the loader calls `0x0052B900` on the gameplay-slot bot, stock code
  will **not** rewrite the bot masks unless that bot is literally the slot-0
  actor pointer
- in the current loader model, the local player lives at `gameplay + 0x1358`
  and the bot lives at `gameplay + 0x135C`
- so the observed bot zeros are not evidence that the call failed
- they are the direct result of the current stock guard in `0x0052B900`

## Additional Stock Clue

The recovered wizard-clone path (`0x0061AA00`) explicitly clears:

- `clone->primary_flag_mask = 0` at `+0x38`

This strengthens the interpretation that these fields are not generic movement
or collision radius fields. They are actor-role or slot-identity-style masks
that stock code is willing to zero on synthetic or non-primary actors.

## What The Mismatch Does For Navigation

The loader-owned bot planner uses the bot actor's `+0x38` as the `mask`
parameter when calling stock:

- `MovementCollision_TestCirclePlacement (0x00523C90)`

The native query behavior matters:

- for occupied cells:
  - if `((mask & cell_mask) == 0)`, the cell is treated as blocking
- for type-2 object or hazard entries:
  - if `((object_mask & mask) == 0)`, the overlap is treated as blocking

That means:

- mask `0`
  - has **no** intersections with any cell/object mask
  - therefore the query treats **every** active cell/object candidate as
    blocking
- mask `1`
  - ignores candidates whose collision/object mask includes bit `1`
- mask `2`
  - ignores candidates whose collision/object mask includes bit `2`
- etc.

Current direct implication:

- the bot's zero mask makes the loader-owned placement oracle more restrictive
  than the player's
- this is a concrete native reason the old bot nav substrate could reject
  placements or cells that the player could still use

## What The Mismatch Does Not Yet Prove

This mismatch does **not** prove that the stock low-level mover itself is more
restrictive for bots, because:

- `PlayerActor_MoveStep` is the shared runtime executor
- the currently recovered body does not directly read actor `+0x38/+0x3C`
- the restriction is definitely present in the loader's path-planning oracle,
  because that code passes the bot field directly into `0x00523C90`

So the most defensible current statement is:

- the mismatch definitely changes the loader-owned placement/pathfinding layer
- it may or may not also affect other stock systems
- current evidence does not show that it changes the direct reactive move step
  in ordinary stock locomotion

## Current Interpretation

Best current model:

- `+0x38/+0x3C` are stock slot-bit or actor-role masks, not generic radius-like
  navigation fields
- stock only rewrites them for the slot-0 actor in `0x0052B900`
- synthetic or non-primary actors can legitimately carry zeros there
- the loader bot planner currently uses `+0x38` as a placement-query mask, so
  the zero value matters there and makes the bot probe stricter than the player

## Open Questions

- which additional stock helpers besides `0x0052B900` and the clone path write
  or clear `+0x38/+0x3C`
- which stock systems besides the loader bot planner consult these masks in
  practice
- whether gameplay-slot bots should inherit a nonzero slot-bit mask for parity
  with player-style path probes, or whether the loader should instead stop using
  `+0x38` as the placement mask for bot planning

