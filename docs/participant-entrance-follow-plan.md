# Participant Entrance-Driven Follow Plan

Date: 2026-04-15

## Goal

Make bot following in hub/private interiors behave like a real participant instead
of a teleported scene mirror.

Desired behavior:

- If the player is in the shared hub, the bot is also in the shared hub.
- If the player enters a private hub area such as `memorator`, `librarian`,
  `dowser`, or `polisher_arch`, the bot should:
  - pathfind to the correct hub entrance anchor
  - trigger the same region entry the player would
  - appear in the destination interior as if it had entered normally
- If the player returns to the hub, the bot should:
  - exit the interior through the matching return path
  - rematerialize in the shared hub at the correct return location
- Coordinated run starts remain party-wide and can keep using direct run scene
  promotion.

## Current State

What is already solid:

- authoritative participant scene intent exists:
  - `shared_hub`
  - `private_region`
  - `run`
- shared/private split is proven for `memorator`
  - shared-hub bot hides in `memorator`
  - private-region bot materializes there
  - return-to-hub rematerialization no longer crashes on the latest churn-gated
    build
- pathfinding-backed bot movement works in both:
  - shared hub
  - `memorator`
- memorator entrance-driven private travel is now stable on the latest build:
  - staged bot survives the player's `hub -> memorator` switch
  - bot rematerializes inside `memorator` on the private-region lane
- the Lua follow mod now uses the profile-centric bot API and scene intent model
  instead of the old run-only `wizard_id` logic

Known rough edges discovered during validation:

- raw or synthetic hub/private stress paths can still choose bad nav targets if a
  test teleports the bot onto awkward cells instead of letting it walk naturally
- raw `hub -> librarian` switching still raises first-chance exceptions even
  with the bot mod disabled
- that keeps `librarian` in the "stock instability" bucket until the base
  switch path is reversed further

## Policy Decision

For hub/private interiors, **policy belongs in Lua** and should be modeled as a
small travel state machine, not instant scene mirroring.

Use the current participant scene model like this:

- `scene_intent` remains the authoritative runtime truth for where a participant
  belongs
- for hub/private travel, Lua changes `scene_intent` only when the bot is
  actually entering or exiting through the correct entrance flow
- for runs, the existing coordinated scene promotion can stay direct

## Why This Model Is Better

- It matches the player’s travel ritual instead of faking area changes.
- It avoids unnecessary same-tick scene churn while the player is still in the
  shared hub.
- It gives modders a real AI policy seam:
  - decide when to follow
  - decide which entrance to use
  - decide whether to wait, regroup, or enter
- It keeps the DLL primitive-only:
  - scene query
  - pathfinding move
  - region entry trigger
  - scene snapshot/state query

## Implementation Tracks

### Track 1: Entrance Data Model

Define a table of hub/private entrance anchors for:

- `memorator`
- `librarian`
- `dowser`
- `polisher_arch`

Each entry needs:

- target private region index
- target private region type id
- hub-side entrance anchor
- private-side arrival/return anchor if needed
- distance threshold for “bot reached the entrance”

Preferred source:

- recover/measure stock player entry and return positions live

If the game already exposes a discoverable entrance/trigger object, expose that
through a typed DLL primitive instead of hardcoding coordinates.

### Track 2: Minimal DLL Primitives

The DLL should only expose what Lua cannot already infer.

Candidate primitives, in order of preference:

1. `sd.world.get_private_region_entrances()`
   - returns typed entrance anchors for the active hub
2. `sd.world.find_private_region_entrance(region_index or region_type_id)`
   - targeted lookup for one area
3. `sd.hub.enter_private_region(region_index)`
   - only if there is no safe way for Lua to trigger the stock transition once
     the bot reaches the anchor

Do **not** put travel policy in the DLL.

The DLL should not decide:

- when the bot should enter
- whether the bot should wait for the player
- which area should be followed

### Track 3: Lua Travel State Machine

Replace the current immediate hub/private scene update with a state machine:

States:

- `idle`
- `follow_in_scene`
- `travel_to_entrance`
- `waiting_for_transition`
- `rematerialize_in_destination`

Behavior:

1. If player and bot are in the same scene, use normal follow band logic.
2. If player enters a private hub area:
   - bot switches to `travel_to_entrance`
   - bot pathfinds to the matching hub entrance anchor
   - once inside threshold, Lua triggers the area entry
   - bot scene intent becomes `private_region`
3. If player returns to the shared hub:
   - bot exits the interior using the reverse rule
   - bot scene intent becomes `shared_hub`
4. For `run`:
   - keep existing party-wide promotion semantics

### Track 4: Follow Robustness

Keep the current stuck-detection idea for same-scene follow, but treat it as
movement robustness, not scene-travel logic.

Use it only for:

- repathing when `move_to` stays active without displacement
- refreshing stand-off targets

Do not use it to fake scene changes.

### Track 5: Validation

Required proofs before calling this slice done:

1. Shared hub -> `memorator`
   - bot walks to entrance
   - bot enters
   - bot appears in `memorator`
2. `memorator` -> shared hub
   - bot exits
   - bot appears in hub at the correct return location
3. Same for:
   - `librarian`
   - `dowser`
   - `polisher_arch`
4. Same-scene follow still works in:
   - shared hub
   - at least one private interior
5. Coordinated hub -> run still works

## Near-Term Coding Order

1. Measure or recover entrance anchors for all four private hub interiors.
2. Decide whether a new DLL primitive is needed for entrance discovery or entry
   triggering.
3. Remove teleport-style hub/private scene updates from `mods/lua_bots`.
4. Implement the entrance-driven Lua travel state machine.
5. Rework the proof harness to validate entrance travel instead of raw
   `switch_region` mirroring.

## Measured Anchor Data

Current measured stock player positions from the live harness:

- `memorator`
  - interior arrival: `(512.0, 798.25897216797)`
  - hub return: `(87.480285644531, 443.60046386719)`
  - current bot staging point: `(75.0, 375.0)`
- `dowser`
  - interior arrival: `(537.5, 647.73309326172)`
  - hub return: `(627.5, 137.6875)`
  - provisional bot staging point: `(675.0, 75.0)`
- `polisher_arch`
  - interior arrival: `(512.0, 867.88549804688)`
  - hub return: `(952.5, 106.6875)`
  - current bot staging point: `(825.0, 75.0)`
- `librarian`
  - interior arrival: `(512.0, 924.0)`
  - provisional hub-side anchor observed before entry: `(124.76531219482, 496.97552490234)`
  - current bot staging point: `(75.0, 525.0)`

Important current caveat:

- raw `hub -> librarian` region switching still raises first-chance exceptions in
  the current client even without the Lua bot mod active
- the scene still loads, but the path is not yet clean enough to treat as fully
  stable
- `memorator`, `dowser`, and `polisher_arch` are the stronger initial targets
  for entrance-driven follow validation

## Current Status

Implemented:

- participant scene intent model (`shared_hub`, `private_region`, `run`)
- shared/private split and hub return rematerialization
- pathfinding-backed same-scene movement in hub and private interiors
- entrance-driven Lua bot travel state machine skeleton
- measured entrance table for the stable hub interiors
- hub doorway travel now uses an outside→inside arm latch instead of naive
  spawn/proximity triggering, so a fresh hub spawn no longer auto-targets a
  nearby entrance
- `run.started` now latches a pending promotion and completes it from the next
  stable `testrun` tick, so the managed bot follows into runs again
- bot spawn/materialization transforms are sanitized against the live gameplay
  path/collision grid and snap to the nearest traversable cell instead of
  publishing directly into blocked geometry

Still being tightened:

- `librarian` is still not clean enough to treat as a stable stock transition
- `dowser` and `polisher_arch` still need a clean entrance-driven validation pass
  on top of the same framework, but no new code path is expected there
- multi-participant region churn still has a separate crash edge when more than
  one participant bot is materialized during a region switch; that is tracked in
  [multi-participant-region-switch-instability.md](/mnt/c/Users/User/Documents/GitHub/SB%20Modding/Solomon%20Dark/Mod%20Loader/docs/bugs/multi-participant-region-switch-instability.md)

## Explicit Non-Goals For This Slice

- Dedicated server authority
- Remote-player networking
- Inventory replication
- Combat sync

Those sit on top of this once participant travel semantics are stable.
