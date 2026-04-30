# Registered GameNpc Transform Update Instability

Date: 2026-04-18

## Summary

The current loader does not have a stock-valid teleport or relocation path for a
materialized registered `GameNpc` participant in hub scenes.

April 18 scope correction:

- the earlier "generic `ActorWorld_Register(..., slot=-1)` is probably too weak
  for any long-lived hub actor" framing is too broad
- stock named hub NPCs (`PerkWitch`, `PotionGuy`, `Annalist`, `ItemsGuy`,
  `Tyrannia`, `Teacher`) are long-lived and stable on the generic register lane
- the sharper loader-side mismatch is that the registered bot rail keeps a
  create-wizard preview/source `GameNpc (0x1397)` alive after
  `0x00466FA0`, instead of following the stock handoff into
  `WizardCloneFromSourceActor (0x0061AA00)`
- because of that, the default hub selector now stays on the standalone clone
  rail until a real long-lived `GameNpc` contract is recovered

April 20 crash correction:

- the fresh shared-hub crash did follow the stock clone handoff, but the
  loader then misclassified the clone as `RegisteredGameNpc`
- `WizardCloneFromSourceActor (0x0061AA00)` allocates a fresh player actor
  through `PlayerActorCtor (0x0052B4C0)`, not a `GameNpc (0x1397)`
- the crashing runtime log showed that exact mismatch:
  - the post-handoff actor was remembered as `RegisteredGameNpc`
  - but its live `object_type` was `0x1`, not `0x1397`
- the first follow retarget then called the native `GameNpc` movement helper
  (`GameNpc_SetMoveGoal` / `0x005E9D50`) on that player-family clone
- stock `PlayerActorTick` later faulted in
  `FUN_00533520 -> FUN_004022A0 -> FUN_004024C0`, where
  `FUN_004024C0` expects `count > 0` arrays to have a non-null backing pointer
  and crashed on `mov eax, [eax]`

Current implication:

- `WizardCloneFromSourceActor` output belongs to the standalone/player rail
- it must never be remembered or driven as `RegisteredGameNpc`
- the registered rail remains blocked until the loader can materialize a true
  long-lived `0x1397` actor without mixing in the clone/player family

Two things were proven:

1. `sd.bots.update({ position = ... })` is accepted and reaches the gameplay
   sync path, but that path only writes actor `x/y/heading`.
2. A later direct actor-memory teleport can move the live actor, but it is not
   a legal relocation for this actor family and can crash stock code afterward.

So the current implementation is not "a teleport that sometimes fails." It is a
partial transform patch being applied to an actor class whose world/movement
state has stricter stock invariants than the loader is currently honoring.

The April 20 crash adds a second, separate invariant:

- the loader must not classify a player-family clone as `RegisteredGameNpc`
- once that classification is wrong, the registered-NPC follow helpers write
  the wrong state model onto the clone before stock player tick code runs

## Verified Evidence

### 1. Runtime update accepts the request

`UpdateBot(...)` in
`SolomonDarkModLoader/src/bot_runtime/public_api/update_api.inl`:

- updates runtime transform state
- dispatches an entity sync when `has_transform`

Relevant code:

- [`update_api.inl:1`](../../SolomonDarkModLoader/src/bot_runtime/public_api/update_api.inl)

### 2. Gameplay sync reports success

`ExecuteParticipantEntitySyncNow(...)` routes the transform update into
`TryUpdateParticipantEntity(...)`, which logged:

- `queued sync ... has_transform=1 x=569.354919 y=476.598267 heading=92.000000`
- `sync updated existing entity. bot_id=...`

Relevant code:

- [`participant_entity_sync.inl:1`](../../SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/participant_entity_sync.inl)
- [`entity_update_and_rail_selection.inl:34`](../../SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/entity_update_and_rail_selection.inl)

### 3. The gameplay update path only writes transform fields

`TryUpdateParticipantEntity(...)` currently:

- resolves a sanitized transform
- writes `actor + x`
- writes `actor + y`
- writes `actor + heading`
- publishes a gameplay snapshot

It does **not**:

- stop native `GameNpc` movement state first
- clear loader path state / current waypoint state
- invalidate pending movement intent
- rebind the actor in the world-cell grid
- run a stock relocation helper

Relevant code:

- [`entity_update_and_rail_selection.inl:34`](../../SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/entity_update_and_rail_selection.inl)

### 4. Bot snapshot composition can expose stale position

`sd.bots.get_state()` is built by:

1. `FillBotSnapshot(...)` from runtime participant state
2. `ApplyGameplayStateToSnapshot(...)` from gameplay snapshot
3. `ApplyControllerStateToSnapshot(...)` from pending controller intent

`ApplyGameplayStateToSnapshot(...)` overwrites snapshot `position_x/y/heading`
from the cached gameplay snapshot whenever the bot is materialized.

Relevant code:

- [`snapshot_builders.inl:1`](../../SolomonDarkModLoader/src/bot_runtime/helpers/snapshot_builders.inl)
- [`snapshot_builders.inl:28`](../../SolomonDarkModLoader/src/bot_runtime/helpers/snapshot_builders.inl)
- [`snapshot_builders.inl:55`](../../SolomonDarkModLoader/src/bot_runtime/helpers/snapshot_builders.inl)
- [`lua_engine_parsers.cpp:804`](../../SolomonDarkModLoader/src/lua_engine_parsers.cpp)

This means a transform update can be accepted at runtime while `get_state()`
still reports the old gameplay snapshot until that snapshot is refreshed.

### 5. Stock movement/reposition paths maintain cell membership

Recovered stock helpers show that legal movement/repositioning keeps
`actor +0x54` world-cell membership coherent:

- `PlayerActor_MoveStep (0x00525800)` removes the actor from the old cell,
  computes the new cell, inserts it, and writes the new cell pointer back.
- `WorldCellGrid_RebindActor (0x005217B0)` performs the same membership repair
  when publication or other systems need to recompute the actor's cell.
- `ActorWorld_RegisterGameplaySlotActor (0x00641090)` explicitly finishes by
  calling `WorldCellGrid_RebindActor(region + 0x378, actor)`.

Pseudo-source references:

- `Decompiled Game/reverse-engineering/pseudo-source/gameplay/00525800__ActorMoveWithCollisionAndGrid.c`
- `Decompiled Game/reverse-engineering/pseudo-source/gameplay/005217B0__WorldCellGrid_RebindActor.c`
- `Decompiled Game/reverse-engineering/pseudo-source/gameplay/00641090__ActorWorld_RegisterGameplaySlotActor.c`

Current implication:

- a transform-only update for a live registered `GameNpc` is incomplete
- the actor can be left at a new world position with stale spatial membership

### 6. Direct actor-memory teleport produced a stock crash

After a direct memory teleport, the crash log captured:

- actor position in crash summary at the forced coordinates
- a later stock AV at `SolomonDark.exe + 0x00123E33`

Crash context snapshot:

- materialized registered `GameNpc`
- `pos=(569.355,476.598)`

That confirms the direct write moved the actor, but it did not satisfy stock
post-move invariants well enough for the game to remain stable.

April 18, 2026 crash-chain refinement:

- `0x00123E33` sits inside
  `MovementCollision_TestCirclePlacement (0x00523C90)`
- the nearby frame `0x00126AC6` sits inside
  `MovementCollision_ResolveDynamicObjects (0x00526520)`

Current interpretation:

- the forced teleport is not just upsetting generic actor readers
- it is also leaving the collision / dynamic-overlap side of the movement
  context in a state that later stock movement code cannot safely consume

More precise stock chain mapping:

- `SolomonDark.exe + 0x001225E0` -> `MovementCollision_QueryType2Hazards (0x00522500)`
- `SolomonDark.exe + 0x001228CC` -> `FUN_005226F0`
  - path-step helper that walks movement-context hazard/object lists
- `SolomonDark.exe + 0x00122D10` -> `MovementCollision_ResolveType2Hazards (0x00522CE0)`
- `SolomonDark.exe + 0x00123E33` -> `MovementCollision_TestCirclePlacement (0x00523C90)`

At `0x00123E33`, the helper executes:

- `TEST dword ptr [EAX + 0x14], ECX`

At that point:

- `EAX` comes from the secondary overlap/object list rooted at
  `movement_context + 0x7C`
- the list was expected to contain a live type-2 hazard / dynamic owner record
- the crash record showed `EAX = 0`

Current interpretation:

- the teleport path is leaving the movement/collision context with a stale or
  null entry in the dynamic/hazard overlap branch
- this is stronger than the earlier "world-cell membership might be stale"
  statement: the dynamic overlap/object side of the movement context is also
  implicated directly by the crash-site dereference

April 18, 2026 follow-up blocker during ordinary movement:

- `SolomonDark.exe + 0x00122D10` is the instruction:
  - `MOV ECX, dword ptr [EAX + 0x10]`
- at that point:
  - `EAX` is sourced from the primary overlap list rooted at
    `movement_context + 0x4C`
  - the crash record showed `EAX = 0`

Current interpretation:

- this is a separate null-entry failure from the `0x00123E33` branch
- the broader movement/collision context can contain null or stale entries in
  both:
  - the primary overlap list (`+0x4C`)
  - the secondary hazard/object list (`+0x7C`)
- the relocation/update contract must therefore preserve more than just actor
  position and world-cell membership; it must leave the movement context's
  overlap/object lists in a stock-valid shape before later movement code runs

## Disproven Assumptions

These assumptions are now wrong and should not be reused:

1. "If `sd.bots.update({ position = ... })` returns true, the bot has been
   stock-safely teleported."

False. It means the loader accepted the request and wrote a transform through
its current sync path.

2. "If the gameplay log says `sync updated existing entity`, the public bot
   snapshot must already match the new transform."

False. Snapshot composition mixes runtime, gameplay snapshot, and controller
state, and gameplay state currently overwrites runtime transform fields.

3. "A raw actor `x/y/heading` write is close enough to a legal relocation for a
   hub `GameNpc`."

False. That bypasses world-cell membership, native movement bookkeeping, and
any other stock relocation-side effects.

## Current Best Interpretation

The loader currently has three distinct things:

- runtime transform intent
- gameplay snapshot observation
- stock actor state

For materialized registered `GameNpc` participants, those three are not tied
together by a stock-valid relocation contract.

The missing RE target is not "which three floats should we write." It is:

- what stock function or function sequence performs a legal relocation/update of
  a live `GameNpc`
- what additional fields or owner/grid structures are repaired by that path
- whether the correct path is:
  - a generic world/grid rebind after transform
  - a `GameNpc`-specific reposition helper
  - a destroy/rematerialize cutover that is already stock-safe

## Loader Contract Matrix

### Runtime-side update contract

`UpdateBot(...)` currently means:

- update runtime participant metadata
- update runtime transform cache if `has_transform`
- dispatch an entity sync request into gameplay

It does **not** mean:

- "stock-safe relocate the live materialized actor"

Relevant code:

- `SolomonDarkModLoader/src/bot_runtime/public_api/update_api.inl`

### Gameplay-side existing-entity sync contract

`TryUpdateParticipantEntity(...)` currently means:

- resolve a sanitized transform
- write actor `x`
- write actor `y`
- write actor `heading`
- publish a gameplay snapshot

It does **not**:

- stop native movement state
- clear loader path state
- clear runtime movement intent
- rebind the actor in the world-cell grid
- repair any movement-context overlap/object lists
- call a stock relocation helper

Relevant code:

- `SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/entity_update_and_rail_selection.inl`

### Snapshot composition contract

`sd.bots.get_state()` currently composes:

1. runtime participant cache
2. gameplay snapshot
3. controller intent

That means:

- gameplay snapshot can overwrite freshly written runtime transform
- controller state can still advertise stale `moving/has_target`
- runtime can then be rewritten again from gameplay snapshot publication

Relevant code:

- `SolomonDarkModLoader/src/bot_runtime/helpers/snapshot_builders.inl`
- `SolomonDarkModLoader/src/mod_loader_gameplay/bot_registry_and_movement_participant_snapshot.inl`

Current interpretation:

- the loader does not yet have a single authoritative relocation owner for a
  materialized registered `GameNpc`
- `sd.bots.update({ position = ... })` is therefore a partial sync request, not
  a complete live relocation contract

## Publication Scope Correction

### Generic register is valid for other long-lived hub actors

Fresh stock decompilation of the named hub-character builder `FUN_0050B720`
shows that the visible hub NPCs are published by:

- factory-create the actor (`0x1389`, `0x138B`, `0x138C`, `0x138D`, `0x138F`,
  `0x1390`)
- seed position
- call `ActorWorld_Register(world, actor_group=0, actor, slot_index=-1, use_alt_list=0)`

No `ActorWorld_RegisterGameplaySlotActor(...)` call appears in that hub builder.

Current implication:

- generic `ActorWorld_Register(..., slot=-1)` is not inherently invalid for
  long-lived hub publication
- the earlier "persistent slot side effects are required for any long-lived
  actor" hypothesis is too broad

### The sharper mismatch is preview-source lifetime, not just register flavor

Fresh decompilation of the stock create-wizard preview/source bridge
`0x00466FA0` confirms that it:

- allocates `GameNpc (0x1397)` through `GameObjectFactory_Create(0x1397)`
- seeds source/profile fields at `+0x174/+0x178/+0x17C`
- resolves preview position
- publishes the actor through generic `ActorWorld_Register(..., slot=-1)`
- immediately runs `ActorBuildRenderDescriptorFromSource (0x005E3080)`

That stock function stops at the preview/source contract.

Fresh decompilation of `WizardCloneFromSourceActor (0x0061AA00)` confirms that
stock then performs a separate handoff into a live actor contract:

- allocates a new `PlayerActor` (`0x398`)
- allocates progression and equip runtimes
- allocates the `+0x21C` selection/control state object
- transfers source visual helper state
- refreshes progression
- attaches the actor to gameplay

Current loader-side mismatch:

- `TrySpawnRegisteredGameNpcParticipantEntity(...)` currently uses
  `CreateWizardCloneSourceActor(...)`
- that helper reproduces the `0x00466FA0` preview/source contract:
  - factory-create `0x1397`
  - generic `ActorWorld_Register(..., slot=-1)`
  - `ActorBuildRenderDescriptorFromSource`
- the loader then keeps that preview/source actor alive as a hub participant,
  adds equip/runtime state, and drives movement on it
- it does **not** complete the stock handoff through `0x0061AA00`

April 18, 2026 correction:

- the helper already does call the two key stock entrypoints behind those seam
  names:
  - `ActorWorld_Register` is `0x0063F6D0`
  - `ActorBuildRenderDescriptorFromSource` is `0x005E3080`
- so the remaining gap is not "we forgot to call `0x0063F6D0` /
  `0x005E3080` entirely"
- the sharper open question is whether:
  - another create-wizard-side step around `0x00466FA0` is still missing
  - or the preview/source `0x1397` actor is simply not a stock-valid long-lived
    follower rail even when those helpers have run

Current interpretation:

- the registered rail is not just "a long-lived generic-register actor"
- it is a create-wizard preview/source actor being prolonged past the stock
  handoff boundary
- that is a stronger root-cause candidate than the earlier generalized
  publication theory

### April 18, 2026 live comparison corrections

Fresh shared-hub live probes against a registered bot, a roaming `Student`
(`0x138A`), and a named hub NPC show:

- `mask=0 mask2=0` on the registered bot is **not** unique
- stock hub NPC families also carry zero masks while remaining stable
- on clean runs, the registered bot stays:
  - listed in `sd.world.list_actors()`
  - owned by the live world
  - attached to a stable cell pointer
  - materialized with stable `source_kind=3` / source-profile state

So the stronger remaining issue is no longer "zero masks" or obvious silent
de-publication.

### April 18, 2026 crash-frame refinement

Fresh decompilation and crash-frame logging now make the `0x001225E0` fault
more precise:

- raw instructions at `0x005225E0` show:
  - `ESI` is the current top-level primary-overlap entry pointer
  - `EBX` is the movement context
  - the faulting instruction is `cmpb $0x2, 0xc(%esi)`
- on the real crash frame:
  - `ESI = 0`
  - `EBX = movement_context`
- so the immediate crash is consistent with a null **top-level primary overlap
  entry pointer**

But the same exception-handler dump also shows:

- `EBX + 0x4C` still points to a readable primary list
- the first few entries re-read as non-null by the time the handler inspects
  them

Current interpretation:

- the actor itself can still look fully coherent immediately before the crash
- the null primary entry appears transient or rebuilt before the handler's
  re-read
- that shifts the remaining focus toward the primary-overlap builder / caller
  path, not just actor owner/cell corruption

### Loader hardening from this correction

The hub rail selector now prefers the standalone clone path and no longer
defaults to the registered preview-source path in non-arena scenes.

Reason:

- the clone path follows a stock long-lived actor handoff (`0x0061AA00`)
- the registered rail currently extends the preview/source contract beyond the
  point stock stops using it

## Next RE Targets

1. Recover the stock call chain around:
   - `SolomonDark.exe + 0x00123E33`
   - `SolomonDark.exe + 0x001225E0`
   - `SolomonDark.exe + 0x001228CC`
   - `SolomonDark.exe + 0x00122D10`

2. Identify every stock caller that updates a live `GameNpc` position outside
   normal movement.

3. Verify whether a legal relocation requires:
   - `StopRegisteredGameNpcMotion(...)`
   - world-cell rebind
   - native goal/waypoint reset
   - loader path reset
   - controller intent invalidation

4. Decide whether materialized registered `GameNpc` teleport should be:
   - a stock relocation helper call
   - or explicitly unsupported, with rematerialize-at-position used instead

## Candidate Relocation Contracts

### Candidate A — raw transform write

Shape:

- write actor `x/y/heading`

Status:

- rejected

Reason:

- disproven by crash logs and by stock movement/collision contracts

### Candidate B — raw transform write + world-cell rebind

Shape:

- write actor `x/y/heading`
- call `WorldCellGrid_RebindActor`

Status:

- plausible but incomplete

Reason:

- stock crash chain implicates not just stale cell membership but also stale
  dynamic overlap/object state and native `GameNpc` movement bookkeeping

### Candidate C — stock helper `Actor_SetPositionAndRebindIfActive (0x00622D90)`

Shape:

- call stock helper to write actor `x/y`
- let it perform the immediate world-cell rebind when the actor is active/owned

Status:

- current leading stock seam

Reason:

- it is the strongest recovered stock helper that already encodes the "write
  position + keep cell membership coherent" contract
- still unresolved whether it must be wrapped with native movement/path resets
  for live registered `GameNpc`s

### Candidate D — stock helper + native movement/path reset

Shape:

- stop native `GameNpc` movement
- clear loader path / waypoint state
- clear or revise runtime movement intent
- call `0x00622D90`

Status:

- most plausible full contract today

Reason:

- matches the current evidence that relocation is failing on both spatial and
  movement/collision bookkeeping

### Candidate E — destroy/rematerialize

Shape:

- dematerialize current actor
- respawn/rematerialize at the requested position through the already-proven
  stock-safe publication path

Status:

- fallback design candidate, not yet preferred

Reason:

- likely safest if no complete live relocation contract exists
- more invasive than a true stock relocation helper path

## Current Comparison: Stock Motion vs Loader Transform Sync

### What stock movement/repositioning does

From the recovered stock helpers:

- `PlayerActor_MoveStep (0x00525800)`
  - rebuilds the primary overlap list at `movement_context + 0x4C`
  - rebuilds the adjacent-cell list at `movement_context + 0x64`
  - rebuilds the secondary hazard/object list at `movement_context + 0x7C`
  - resolves branch-A / branch-B collision responses
  - resolves dynamic-object responses when enabled
  - removes the actor from the previous world cell at `actor + 0x54`
  - inserts the actor into the new world cell and writes the new cell pointer
    back to `actor + 0x54`

- `Actor_SetPositionAndRebindIfActive (0x00622D90)`
  - writes actor `x/y`
  - if active and owned, immediately calls `WorldCellGrid_RebindActor`

### What the current loader transform sync does

`TryUpdateParticipantEntity(...)` currently:

- resolves a sanitized target transform
- writes actor `x`
- writes actor `y`
- writes actor `heading`
- republishes a gameplay snapshot

It does **not**:

- call `0x00622D90`
- call `WorldCellGrid_RebindActor`
- rebuild any overlap lists at `+0x4C/+0x64/+0x7C`
- clear native `GameNpc` movement state
- clear loader waypoint/path state
- invalidate or revise pending movement intent

### Minimal missing stock-side updates

Based on the current evidence, a stock-valid live relocation almost certainly
requires at least:

1. stop or invalidate the actor's current native movement/follow state
2. clear or supersede the loader-owned waypoint/path state
3. move the actor through a stock seam that also repairs world-cell membership
   (`0x00622D90` is the current strongest candidate)
4. ensure later movement/collision code sees rebuilt, non-null overlap/object
   lists before it re-enters `0x00522CE0` / `0x00523C90`
5. keep runtime/controller state from reasserting stale pre-relocation targets

Current interpretation:

- `x/y/heading` writes alone are not even close to a complete relocation
  contract for a materialized registered `GameNpc`
- `0x00622D90` is likely necessary, but not yet proven sufficient by itself

## Scope Correction: Publication Is Also Broken

The April 18 `0x00122D10` crash widened the scope of the bug:

- that crash occurred on an idle, never-teleported registered `GameNpc`
- so the null-entry failures in the movement/collision context are not caused
  only by the relocation path

Current interpretation:

- the loader's **publication** contract for registered `GameNpc` actors is also
  incomplete
- but the sharper mismatch is no longer "generic register versus persistent
  slot" in the abstract
- stock named hub actors prove generic
  `ActorWorld_Register(world, actor_group=0, actor, slot_index=-1, use_alt_list=0)`
  can support long-lived non-slot hub actors
- the current loader bug is specifically that it prolongs the
  `0x00466FA0` create-wizard preview/source `GameNpc` contract past the point
  where stock stops using it

Important differences that still matter when comparing the generic preview path
against the persistent-slot path:

- persistent-slot publication sets `region + 0x7C + slot`
- persistent-slot publication writes a different slot-indexed mirror cell at
  `region + 0x500 + slot * 0x2000`
- persistent-slot publication rewrites actor identity to `+0x5C = slot`,
  `+0x5E = 0`
- persistent-slot publication finishes with
  `WorldCellGrid_RebindActor(region + 0x378, actor)`

Current implication:

- those persistent-slot side effects are real, but they are not required for
  every long-lived hub actor
- the evidence now points at a source-versus-live-handoff problem first:
  `TrySpawnRegisteredGameNpcParticipantEntity(...)` keeps a preview/source
  `GameNpc` alive instead of following the stock handoff into
  `WizardCloneFromSourceActor (0x0061AA00)`

### Leading publication hypothesis

Current best fit for the April 18 evidence is:

- the generic register path is sufficient for:
  - stock preview/helper actors
  - stock named non-slot hub actors
- but the specific create-wizard preview/source `GameNpc (0x1397)` published by
  `0x00466FA0` is not obviously a stock-valid long-lived follower contract on
  its own

Why this is the current leading hypothesis:

- idle registered-`GameNpc` actors can still crash in the movement/collision
  family without any teleport attempt
- the current registered loader rail reproduces the preview/source half of the
  stock create-wizard path, then stops
- stock immediately follows that preview step with a different live-actor
  handoff (`WizardCloneFromSourceActor (0x0061AA00)`) instead of driving the
  preview actor as a participant

This is not yet proven, but it is currently the strongest explanation for why a
materialized registered `GameNpc` can remain visible and appear superficially
valid while still tripping later stock readers in the movement/collision domain.

## New Stock Seam Recovered

April 18, 2026 follow-up RE recovered a strong relocation helper candidate:

- `0x00622D90` -> `Actor_SetPositionAndRebindIfActive`

Verified instruction shape:

- write `actor + 0x18 = x`
- write `actor + 0x1C = y`
- if `actor + 0x36 != 0` and `actor + 0x58 != 0`
  - call `WorldCellGrid_RebindActor(owner + 0x378, actor)`

This is now the strongest known stock seam for:

- setting a live actor position
- immediately keeping `actor + 0x54` world-cell membership coherent

Open question:

- whether this helper alone is sufficient for a live registered `GameNpc`
  relocation, or whether the actor family still requires additional native
  goal/path/behavior resets before or after the call

### Current caller classification for `0x00622D90`

Current xrefs recovered from the analyzed binary:

- `0x00473190`
  - trivial wrapper around `0x00622D90`
- `0x004804D0`
- `0x00498180`
- `0x0053CFE0`
- `0x0053DC60`
- `0x0053E6A0`
- `0x0053EDB0`
- `0x0053F3C0`

What those callers appear to do:

- multiple callers allocate objects through `GameObjectFactory_Create`
  (`0x005B7080`)
- they then set initial world-space placement through `0x00622D90`
- they register those objects through `ActorWorld_Register (0x0063F6D0)`
- several of the recovered paths look like helper/effect/preview actor setup,
  not durable participant publication

Current interpretation:

- `0x00622D90` is clearly a stock-safe "set position and keep cell membership
  coherent" seam
- but current evidence points to helper/spawned actor placement, not yet to a
  proven persistent remote-participant relocation path
- that makes it a strong candidate building block, not yet a complete proof
  that a live registered `GameNpc` can be teleported by calling it in isolation

### Current non-`MoveStep` callers of `WorldCellGrid_RebindActor`

Recovered explicit xrefs to `0x005217B0` so far:

- `PlayerActor_MoveStep (0x00525800)` through its normal collision/movement flow
- `Actor_SetPositionAndRebindIfActive (0x00622D90)`
- `FUN_0052A0B0`
  - helper path that advances a spawned/helper actor forward until placement is
    clear, then rebinding through `0x005217B0`
- `ActorWorld_RegisterGameplaySlotActor (0x00641090)`

Current interpretation:

- stock absolutely does use explicit world-cell rebinding outside normal
  movement
- but the known non-`MoveStep` callers are still setup/registration/helper
  paths, not yet a verified "teleport a live `GameNpc` participant here"
  contract

## Practical Rule For Now

Do not treat `sd.bots.update({ position = ... })` as a correct teleport for a
materialized registered `GameNpc` until the stock-safe relocation contract is
recovered and implemented.

Current loader behavior (April 18, 2026):

- transform-only `sd.bots.update({ position = ... })` requests for a live
  materialized registered `GameNpc` are now rejected at the public API boundary
  instead of being silently half-applied
- this is an explicit unsupported-state guard, not a completed relocation fix
- live validation:
  - with a fresh staged run and a materialized registered `GameNpc`, calling
    `sd.bots.update({ id=bot.id, position={ x=player.x, y=player.y } })`
    now returns `false`
