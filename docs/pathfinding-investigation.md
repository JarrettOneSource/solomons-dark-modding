# Pathfinding Investigation

Date: 2026-04-13

## Project State Today

- Workspace currently splits into three useful surfaces:
  - `Mod Loader/` for launcher, injected loader, Lua runtime, gameplay seams, and loader-owned bot movement/pathing.
  - `Decompiled Game/reverse-engineering/` for curated maps, pseudo-source, and manual RE artifacts.
  - `Decompiled Game/ghidra_project*` plus `Mod Loader/tools/ghidra-scripts/` for repeatable headless Ghidra passes.
- Current loader bot movement/pathing is now split cleanly:
  - `sd.bots.move_to(id, x, y)` stores destination intent plus a revision counter.
  - runtime keeps the destination current, but no longer owns straight-line steering.
  - gameplay-side bot bindings build and follow a loader-owned A* route over the
    native scene grid.
  - each waypoint is executed through stock `PlayerActor_MoveStep (0x00525800)`,
    now from the standalone bot actor's own `PlayerActorTick` cadence rather than
    the older 50 ms scene-binding mover.
  - the per-step movement budget is read from the bot actor's native
    `+0x218 move_step_scale` field before calling `PlayerActor_MoveStep`, which
    matches the stock player-side pattern recovered from `PlayerActorTick`.
  - collision, sliding, animation advance ownership, and world motion remain
    game-native.
  - April 15 scene-membership cutover:
    - hub bots now materialize as `scene.kind = SharedHub` participants instead
      of relying on the older `home_region_*` heuristic
    - the same movement stack is still used there; the live log shows the bot
      receiving A* waypoints and entering the gameplay-thread path-follow loop
      in the hub
    - current residual:
      - the tested hub waypoint still ended in repeated `zero-displacement move
        step` logs, so the scene-membership cutover is proven but hub movement
        needs its own follow-up pass

## Verified Stock Pathfinding Anchors

### 1. Monster setup data contains explicit pathfinding and flanking bytes

- `0x004AFBC0` now documented as `MonsterSetup_Parse`
  - parses `MONSTER SETUP` records into a monster definition blob
  - verified fields:
    - `+0x6C` chase speed
    - `+0x70` attack speed
    - `+0xB8` flanking mode byte
    - `+0xB9` pathfinding mode byte
- `0x0063E890` now documented as `MonsterSetup_Reset`
  - clears the same layout
  - explicitly resets `+0xB8` and `+0xB9`
- `0x004CAB70` remains under its old filename, but notes now mark it as a **misnamed Monster Setup builder**
  - it displays `PATHFINDING:` from `setup + 0xB9`
  - it displays `FLANKING` from `setup + 0xB8`

### 2. `0x00483480` is a live gameplay consumer of `pathfinding_mode`

- `0x00483480` now documented as `MonsterPathfinding_RefreshTarget`
- verified behavior:
  - reads the dual-use `actor + 0x1D0` slot as a monster-definition pointer for native enemies
  - branches on `*(monster_definition + 0xB9)`
  - observed value handling:
    - `0` -> `actor + 0x1E0 *= 10`
    - `1` -> `actor + 0x1E0 *= 3`
    - `3` -> `actor + 0x1E0 = 10`
  - `actor + 0x1E0` is a retarget-cadence divisor, not a movement-speed scaler
  - refreshes `actor + 0x168` from region/world bucket table:
    - `world + 0x500 + (actor_group * 0x800 + actor_slotish_index) * 4`
  - updates heading accumulator at `actor + 0x6C`
  - recomputes cadence modulo at `actor + 0x1DC`
- current interpretation:
  - this is not full route solving by itself
  - it is a strong stock AI/path-target refresh helper driven by monster-definition pathfinding mode
  - `world + 0x500` bucket lookup suggests target acquisition / chase lane selection is mixed into path refresh

### 3. Immediate caller family around `0x00483480`

- callers recovered through xrefs:
  - `0x00484AA0`
  - `0x00486380`
  - `0x00486BB0`
  - `0x004871F0`
  - `0x00487230`
  - `0x00487F30`
  - `0x00487F60`
  - `0x00488E90`
- useful observed caller behaviors:
  - `0x00484AA0` now documented as `Badguy_RefreshTargetThenDispatch`
    - calls `MonsterPathfinding_RefreshTarget`
    - resolves target state from `+0x236/+0x238`
    - dispatches through target actor vtable slot `+0x10`
  - `0x004871F0` now documented as `Badguy_LoadChaseSpeed`
    - calls `MonsterPathfinding_RefreshTarget`
    - loads chase speed from native monster definition `+0x6C` into actor field `+0x238`
  - `0x00487F60` now documented as `Badguy_RefreshTargetLongCadence`
    - calls `MonsterPathfinding_RefreshTarget`
    - multiplies cadence field `+0x1E0` by `100`
    - rescales movement values at `+0x220/+0x224`
    - recomputes cadence quotient

### 3b. Class ownership of the pathfinding slot

- vtable refs to `MonsterPathfinding_RefreshTarget` show it is a base `Badguy` virtual inherited by multiple native enemies
- constructors / destructors tied to those vtables include:
  - `Badguy`
  - `Imp`
  - `GreenImp`
  - `Zombie`
  - `Skeleton`
  - `Demon`
  - `DemonSkull`
  - `DireFaculty`
  - `Coffin`
  - `Maggot`
- current conclusion:
  - this is broad monster chase logic, not a single-enemy special case

### 4. Residual sweep: pre/post helpers around `0x00483480`

- `0x00481A60` now documented as `MonsterPathfinding_SelectNearestTarget`
  - scans a global actor list
  - filters inactive entries and region mismatches
  - picks nearest candidate
  - stores selected target into `actor + 0x168`
  - stores selected target world-bucket delta into `actor + 0x164`
    - in stock same-group targeting this collapses to `target + 0x5E`
  - if no target survives, clears `actor + 0x1D8`
- `0x00525800` is the already-mapped `PlayerActor_MoveStep`
  - fast path directly adds movement deltas into actor position
  - slow path routes through a cluster of collision/grid helpers:
    - `0x00521B80`
    - `0x005218C0`
    - `0x00522CE0`
    - `0x00522500`
    - `0x00522C00`
    - `0x00522B20`
    - `0x00526520`
  - rebinds `actor + 0x54` against the scene grid at `scene + 0xB4`
- deeper movement/collision helpers now partially classified:
  - `0x00521B80` gathers occupied neighboring cells into the primary collision candidate list
  - `0x005218C0` probes directional adjacent cells into a secondary candidate list
  - `0x00522500` scans type-2 collider owners and dispatches overlapping subitems/hazards
  - `0x00522C00` and `0x00522B20` both react to collisions against the `context + 0x70/+0x7C` list and can force actor position rewrite while setting collision flag `context + 0x80`
  - `0x00522B20` is the stronger branch because it also calls `0x00522A30`
  - `0x00526520` is a broader object-response pass over `context + 0x58/+0x64`; it can push/slide actors, accumulate response state, and recurse back into `PlayerActor_MoveStep`
  - geometry helpers are now identified too:
    - `0x00521090` clamps a scalar into `[min,max]`
    - `0x005210D0` is a circle-vs-cell-rectangle overlap/closest-point test
    - `0x00521E00` computes a simple linear push vector for overlapping circles
    - `0x00521EF0` computes a weighted push vector with a 4th-power falloff term
    - `0x00522A30` finalizes the stronger branch by querying contacts through `0x005226F0`, nudging forward on no-contact, or snapping to resolved position on contact
- updated interpretation:
  - `0x00483480` is a sound anchor
  - it sits between monster-definition mode selection and lower movement/collision/grid resolution
  - stock “pathfinding” currently looks more like target selection + heading + shared collision-aware chase than a separate route planner
  - obstacle-aware behavior, if present, is more likely inside the `0x00525800` helper family than inside `0x00483480` itself
  - the chase-to-movement bridge is now explicit:
    - `MonsterPathfinding_RefreshTarget`
    - `Badguy_CommonChaseTick`
    - `Badguy_MoveStep`
    - `PlayerActor_MoveStep`

### 5. Badguy-specific follow-up

- `0x004835F0` is now identified as `Badguy_CommonChaseTick`
  - shared chase/steering helper used by multiple monster slot-2 methods
  - manages cadence and refresh timers around `+0x61/+0x83/+0x156/+0x1DA`
  - resolves `actor + 0x5A` from the world target bucket
  - calls `MonsterPathfinding_SelectNearestTarget` when retarget conditions hit
  - accumulates motion through subclass virtuals plus
    `Badguy_AccumulateSeparationVector (0x0047CB20)`
  - hands the final move into `Badguy_MoveStep (0x00475FE0)`, which is only a
    thin wrapper around `PlayerActor_MoveStep (0x00525800)`
  - base `Badguy::vftable` callbacks are now partly classified too:
    - `+0x6C` -> `Badguy_BuildChaseVector`
    - `+0x70` -> `Badguy_BuildChaseVectorSigned`
    - `+0x78` -> `Badguy_EmitPeriodicTargetEffect`
    - `+0x84` -> `Badguy_TriggerState0D`
    - `+0x8C` -> `Badguy_IsTargetVisibleWithinRange`
    - `+0x90` -> `Badguy_IsTargetVisibleWithinScaledRange`
    - `+0x94` -> `Badguy_TriggerState0E`
  - that split makes the route-vs-attack line clearer:
    - `+0x6C/+0x70` are steering providers
    - `+0x8C/+0x90` are target-range/visibility predicates
    - `+0x84/+0x94` are state/event triggers, not movement
    - `+0x78` is a periodic visual/effect helper, not routing
- `0x00484B30` now documented as `Badguy_ClearTargetAndNotifySlots`
  - clears target selectors at `+0x236/+0x238`
  - calls `0x00482E90`
  - notifies each gameplay slot actor through vtable slot `+0x1C`
- nearby slot-2 class brains are now resolved by vtable ownership:
  - `0x00485DC0` -> `Imp_Tick`
  - `0x004863A0` -> `Zombie_Tick`
  - `0x00486C30` -> `Wraith_Tick`
  - `0x00484B90` -> `Skeleton_Tick`
  - `0x00485200` -> `SkeletonArcher_Tick`
  - `0x00487300` -> `Demon_Tick`
  - `0x00489000` -> `Heartmonger_Tick`
  - `0x004963C0` -> `DemonSkull_Tick`
  - `0x0049D0D0` -> `DireFaculty_Tick`
  - `0x004A2760` -> `Coffin_Tick`
  - `0x0052C1A0` -> `GoodImp_Tick`
- current takeaway:
  - `0x00484B30` is target/reset plumbing, not a deeper subclass path solver
  - the surrounding anonymous cluster is not NPC ally logic
  - it is concrete monster-family runtime behavior layered on top of the shared
    badguy/path-target helpers
  - current evidence still points toward target maintenance, attack timers,
    helper spawning, and effect logic rather than alternate route planning
  - the newly mapped slot-2 methods reinforce that split:
    - `Imp`, `Zombie`, and `Wraith` add class-specific locomotion, attack
      windows, and helper/effect spawning on top of the same shared chase flow
    - `DemonSkull`, `DireFaculty`, and `Coffin` are more state-machine-heavy,
      but still express their movement through shared helpers rather than a
      separate route planner
  - nearby spawn ids in this cluster are now less ambiguous:
    - `0x7E2` is `Meteor`
    - `0x7E3` is `Fire`
    - those actors show up in spell/special-attack paths, which helps keep them
      on the attack/effect side of the line rather than the routing side

### 6. Early Field Trace Notes

- `actor + 0x168` is still the strongest current-target pointer anchor
  - written by `MonsterPathfinding_SelectNearestTarget`
  - read directly by `Badguy_CommonChaseTick` and several subclass slot-2
    methods including `Wraith_Tick`, `DemonSkull_Tick`, and `Skeleton_Tick`
- `actor + 0x164` is not a second pointer
  - stock refresh consumes it as a world-bucket delta:
    - `target = world + 0x500[(actor_slot << 11) + *(int *)(actor + 0x164)]`
  - stock selector writes only `target + 0x5E` because shipped hostile
    selection commits only group/slot `0` targets
  - cross-group hostile overrides therefore must write a packed bucket delta,
    not just a raw target world-slot id
- `+0x238/+0x23C` are overloaded and cannot yet be treated as one universal
  chase-field pair
  - `Badguy_LoadChaseSpeed` writes chase speed into `+0x238`
  - render/effect helpers such as `0x0048DEE0` also reuse `+0x236/+0x238`
    for display-state routing
  - field meaning is therefore class- and routine-specific until narrowed
- `+0x236/+0x238` now look like a real linked-actor handle in the skeleton
  family rather than random effect bytes
  - `Skeleton_Ctor` seeds them to `0xFF/0xFFFF`
  - `Badguy_ClearTargetAndNotifySlots` clears them back to that sentinel state
  - `Badguy_RefreshTargetThenDispatch` interprets them as:
    - `+0x236` = signed group selector
    - `+0x238` = signed 16-bit slot id
  - special group value `0x64` (`'d'`) routes through the alternate table at
    `world + 0x87D8`, otherwise resolution uses the normal bucket table at
    `world + 0x500`
  - `0x0048DEE0` consumes the same pair in render/effect logic, which explains
    why raw scalar scans mix genuine chase-state users with visual helpers
- `+0x23C` is currently best read as a skeleton-family leash/range field, not a
  universal badguy chase scalar
  - `Skeleton_HandleLinkEvent` writes it during event ids `0x0E/0x0F/0x10`
  - `Skeleton_Tick` compares current linked-target distance against `+0x23C`
    and either clears the link or repositions the linked actor along that leash
  - other `+0x23C` hits outside this branch still look like unrelated struct
    layouts or render payloads, so the field remains overloaded globally
- `GoodImp` uses a separate linked-actor mirror pair at `+0x240/+0x242`
  - `GoodImp_Ctor` seeds them to `0xFF/0xFFFF`
  - `GoodImp_RefreshLinkedTargetId` fills them from a nearby actor's
    `+0x5C/+0x5E`
  - `GoodImp_Tick` only lightly touches `+0x242`, so this pair is not a
    generic monster target slot field

### 7. Hostile Target Selection Versus Multiplayer Bots

- current stock hostile selection path is now concrete enough to explain the
  multiplayer-bot targeting problem
  - `MonsterPathfinding_SelectNearestTarget` scans the live global actor list
    at `g_pGameplayScene + 0x1390/+0x139C`
  - it rejects candidates whose `candidate + 0x160 != 0`
  - it also rejects candidates whose mapped region from
    `DAT_00819E84[candidate + 0x5C]` does not match `world + 0x78`
  - it chooses the nearest surviving candidate
  - but it only commits that candidate when the chosen `candidate + 0x5C`
    value is `0`
- loader/runtime evidence lines up with that gate
  - seam config exposes:
    - `actor_slot = 0x5C`
    - `actor_world_slot = 0x5E`
    - `actor_registered_slot_mirror = 0x164`
  - multiplayer bot runtime logs already showed:
    - gameplay-slot bots materialize with `actor_slot = 1`
    - second bot materializes with `actor_slot = 2`
- current conclusion:
  - stock hostile selection is effectively biased toward slot-0 participants
    in this build
  - custom multiplayer bots published into gameplay slots `1..3` can be fully
    registered and visible, yet still be ignored by enemies because they never
    satisfy the stock final commit gate

### 8. Runtime Cutover

- the loader now hooks `MonsterPathfinding_RefreshTarget (0x00483480)`
  through the gameplay hook set
- implementation strategy:
  - let stock refresh run first
  - keep the stock slot-0 result as the baseline
  - scan live gameplay-slot participants in slots `1..3`
  - if a valid slot `1..3` participant is closer than the stock slot-0 target,
    overwrite hostile target state with that actor and a cross-group bucket
    delta that survives later stock refreshes
- the runtime patch intentionally uses the stock gameplay-slot path rather than
  spoofing bot identity
  - bots still materialize through `Gameplay_CreatePlayerSlot`
  - bots still register through `ActorWorld_RegisterGameplaySlotActor`
  - the hostile refresh path is what widens, not the bot actor contract
- current implementation writes:
  - `hostile + 0x168` = replacement target actor pointer
  - `hostile + 0x164` = replacement bucket delta
    - `best_actor_slot * 0x800 + best_world_slot - hostile_actor_slot * 0x800`
    - for the validated slot-0 hostile -> slot-1 bot case this is `2048`
- this keeps the downstream chain aligned with stock refresh logic:
  - `MonsterPathfinding_RefreshTarget`
  - `Badguy_CommonChaseTick`
  - `Badguy_MoveStep`
  - `PlayerActor_MoveStep`

## Live Runtime Validation

- stable validation surface is stock `sd.gameplay.start_waves()`, not manual
  `sd.world.spawn_enemy(...)`
  - manual spawn still proved unreliable during earlier freeze isolation
  - stock-wave validation stayed responsive through the current fix
- validated live run on 2026-04-14:
  - settled scene: `testrun`
  - live slot-backed bot:
    - actor `0x02D4D7A8`
    - `actor_slot = 1`
    - `world_slot = 0`
  - stock-wave hostile promotion log:
    - hostile `0x14A3D638`
    - stock target `0x1407EA90` (slot `0`, world-slot `0`)
    - promoted target `0x02D4D7A8` (slot `1`, world-slot `0`)
    - promoted bucket delta `2048`
  - retention proof five seconds later:
    - hostile `0x14A3D638`
    - `target = 0x02D4D7A8`
    - `mirror = 2048`
  - attack proof:
    - bot HP dropped from `50.0` to `18.5`, then to `-293.5`
  - hostile AI is now acquiring, retaining, and attacking gameplay-slot bots

## Current A-to-B Conclusion

- Current recovered native "pathfinding" is still a chase stack, not a reusable
  arbitrary destination solver.
- What is proven today:
  - `MonsterPathfinding_SelectNearestTarget` picks the nearest live target from
    a flat actor list.
  - `MonsterPathfinding_RefreshTarget` scales retarget cadence from monster
    definition byte `+0xB9`, refreshes the current target, computes a heading,
    and then falls straight into shared movement.
  - `Badguy_CommonChaseTick` is the shared steering layer above
    `Badguy_MoveStep`, and `Badguy_MoveStep` is only a wrapper over
    `PlayerActor_MoveStep`.
  - `PlayerActor_MoveStep` owns collision-aware movement and grid rebinding, so
    it is the reusable obstacle/collision executor in the stock stack.
- What is not proven:
  - any navmesh, waypoint graph, flood fill, A*, or other point-to-point route
    generator for arbitrary actor destinations
  - any native helper that takes "point A -> point B" and returns a path for a
    bot to follow
- Current loader bot movement therefore remains:
  - target point intent in bot runtime
  - normalized straight-line direction vector
  - gameplay-thread `ActorMoveByDelta` / `PlayerActor_MoveStep`
- New April 14 control-brain finding:
  - `PlayerActorTick (0x00548B00)` calls
    `PlayerActor_UpdateControlBrainTargeting (0x0052C910)`
  - that helper mutates the `actor + 0x21C` selection/control brain directly:
    - decrements retarget ticks at `+0x08`
    - clears or refreshes target slot/handle at `+0x04/+0x06`
    - writes steering/control floats at `+0x20/+0x28/+0x2C`
  - helper `0x00641160` used inside that path is now identified as
    `FindNearestFlaggedActorAroundPoint`
    - scans `world + 0x324` for the nearest flagged actor around a supplied
      `(x,y)` position
    - excludes the calling actor
  - helper `0x00476010` used there is now identified as
    `ActorTargetHandle_WriteFromActor`
    - copies `target + 0x5C/+0x5E` into the packed target-handle pair
  - current implication:
    - this native control-brain branch is still actor-target-driven follow/chase
      logic
    - it does not yet show a world-coordinate destination writer or waypoint
      planner for arbitrary point A -> point B travel
- Current implementation consequence:
  - directly reusing the hostile helpers for arbitrary bot A->B travel would be
    the wrong cutover because those helpers are tightly coupled to monster
    definitions, hostile target buckets, and chase-state timers
  - the cleaner native-facing next seam, if it exists, is a stock
    control-brain / point-click destination path rather than the hostile chase
    path
  - if no such destination seam is recovered, the only honest route to bot
    A->B pathing is more RE or a loader-owned waypoint/path solver feeding the
    stock movement executor

## Current Loader Pathing Implementation

- April 14 cutover: the loader now uses a gameplay-thread A* solver for
  `sd.bots.move_to(...)`.
- Current ownership split:
  - runtime intent:
    - final destination
    - movement revision
    - high-level moving/idle state
  - gameplay-thread bot binding:
    - grid snapshot
    - path build / retry state
    - waypoint list
    - current waypoint steering
  - stock game:
    - final movement execution through `PlayerActor_MoveStep`
    - native per-actor movement budget from `actor + 0x218`
    - standalone bot movement cadence from the bot actor's own `PlayerActorTick`
    - collision resolution / sliding / grid rebinding
- Traversability substrate:
  - neighbor generation comes from the recovered native scene grid
  - traversability uses the recovered native placement query wrapper
    `MovementCollision_TestCirclePlacement (0x00523C90)` for cell, shape, and
    type-2 object/hazard overlap checks
  - April 25 update:
    - live `testrun` movement geometry exposed hundreds of small circular
      scenery blockers with mask `0x4`
    - these are the right bucket for run props such as trees, gravestones, and
      pit-like blockers that are too small to be represented by whole grid-cell
      occupancy alone
    - the loader-owned bot planner now snapshots the movement-controller circle
      list (`controller+0xA0/+0xAC`) and rejects A* samples that overlap mask
      `0x4` static circles
    - movable/push-through circle blockers are intentionally excluded so bots
      try to walk through and push them instead of routing around them:
      - the original broad live sample found `0x2004` circles, interpreted as
        static collision plus a movable/physics bit
      - the tested boneyard gate with a live bot present instead resolves as a
        line of plain `0x4` circle blockers with object type `0xBBE`, radius
        `10`, and vtable `0x0118CB44`; this gate family is skipped by object
        type/radius rather than by mask alone
    - A* cell sampling and `sd.debug.get_nav_grid` both use the same static
      circle rejection path, so visual clutter/props affect routing instead of
      only debug overlays
    - the existing player-equivalent collision-mask fallback is still used for
      cell and type-2 object/hazard overlap checks, so gameplay-slot bots do not
      inherit the overly strict zero-mask behavior
    - `MovementCollision_TestCirclePlacementExtended (0x005238C0)` has two
      different mask meanings:
      - the first mask is a raw movement-circle block mask; intersecting entries
        block placement
      - the second mask is an overlap allow mask for the primary/type-2 lists;
        entries block placement when they do **not** intersect it
      - the planner therefore passes a filtered circle mask that excludes
        `0x4/0x2000`, while its native overlap allow mask includes those bits;
        trees, gravestones, and holes stay blocked by the loader's explicit
        kept-circle overlap list
      - live gate-center samples still reported blocked through native overlap
        state even when the only nearby circle was the skipped `0xBBE` gate, so
        the planner now allows a native-blocked sample only when it overlaps an
        ignored push-through circle after the kept-static-circle test has
        already passed
- Live validation status:
  - clean `testrun` launch with only `sample.lua.ui_sandbox_lab` enabled works
    when the bootstrap settles before `sd.hub.start_testrun()`
  - open-space route test:
    - built path from `(31,3)` to `(31,7)`
    - emitted 3 waypoints
    - bot walked the route and stopped cleanly
  - previously failing target test:
    - destination `(1000, 3222)` used to fail with
      `A* search found no path. start=(38, 8) goal=(32, 10)`
    - after the start-cell relocation/follow fixes, the same style of target now
      builds a 3-waypoint route
    - live path example:
      - `(850,3150) -> (950,3150) -> (1050,3250)`
    - bot walks that route and settles with movement cleared
- Root-cause fixes that moved the branch from failing to working:
  - corrected grid-axis mapping for world `(x,y)` -> grid `(row,column)`
  - cleared stale failed-path cooldown behavior across new move revisions
  - kept the final waypoint on a valid cell-center route unless the exact
    destination is already safely inside that final waypoint
  - fixed the relocated-start bug:
    - if the solver relocates the start cell, it now expands neighbors from the
      relocated cell center rather than the actor's raw blocked position
    - it also keeps the relocated start waypoint in the final route instead of
      discarding it as though the actor had started there already
  - removed the old global movement scalar:
    - bot movement no longer multiplies direction by a loader-owned guessed
      constant
    - the bot tick now reads `actor + 0x218` and applies movement once per
      native bot actor tick instead of once per 50 ms scene-binding heartbeat

## Scene Grid Semantics For Loader-Owned Pathing

- The stock scene grid is now specific enough to reuse for a loader-owned path
  solver.
- `ResolveSceneGridCellFromScaledCoords (0x00521260)`:
  - floors scaled coordinates into integer cell indices
  - bounds-checks against:
    - `scene + 0xD8` = grid height
    - `scene + 0xDC` = grid width
  - resolves the cell address as:
    - `scene + 0xB4 + (grid_height * grid_x + grid_y) * 0x18`
- `PlayerActor_MoveStep (0x00525800)` uses the same formula directly:
  - `grid_x = floor(actor_x / *(float *)(scene + 0xE0))`
  - `grid_y = floor(actor_y / *(float *)(scene + 0xE4))`
  - so:
    - `scene + 0xE0` = cell width / x scale
    - `scene + 0xE4` = cell height / y scale
    - each grid cell record is `0x18` bytes
- `WorldCellGrid_RebindActor (0x005217B0)` and `SceneGrid_AttachActorIfActive`
  helper `0x005212F0` both route through `0x00521260`, confirming that the
  same cell-address function is used for stable actor-to-cell membership.
- Collision gather helpers also now confirm the grid is the native movement
  substrate:
  - `MovementCollision_BuildCellOverlapList (0x00521B80)`
    - computes the actor's current cell from position/radius
    - sweeps neighboring cells
    - dispatches occupied cells through the callback vtable at `context + 0x38`
    - rebuild lifecycle:
      - if `context + 0x49 != 0`, frees the old primary list at `context + 0x4C`
      - then zeroes `context + 0x40/+0x44/+0x4C`
      - rebuilds the primary overlap list from the actor's current position,
        radius, and the scene-grid scales at `context + 0xC8/+0xCC`
  - `MovementCollision_ProbeAdjacentCells (0x005218C0)`
    - probes direction-adjacent cells based on movement vector
    - dispatches candidate cells through the callback vtable at `context + 0x50`
    - rebuild lifecycle:
      - if `param_3 == 0` and `context + 0x61 != 0`, frees the old adjacent
        list at `context + 0x64`
      - then zeroes `context + 0x58/+0x5C/+0x64`
  - New cell/query details from deeper decompilation plus live runtime checks:
  - live `testrun` grid sample now confirms:
    - `grid + 0xE0/+0xE4 = 100.0 / 100.0`
    - `grid + 0xDC/+0xD8 = 34 / 25`
  - the cell records at `scene + 0xB4` are live `0x18`-byte objects
  - the primary overlap builder `0x00521B80` treats:
    - `cell + 0x0C` as the active/occupied discriminator
    - `cell + 0x10` as a collision mask/classification consulted by the
      higher-level collision queries
  - crash-site refinement on the higher-level wrappers now shows:
    - `MovementCollision_TestCirclePlacement (0x00523C90)` walks the primary
      overlap list rooted at `movement_context + 0x4C`
      - each primary entry is expected to expose:
        - `+0x0C` active/type discriminator
        - `+0x10` collision mask/classification
        - `+0x04/+0x08` payload used by the circle-vs-cell rect test path
      - the `SolomonDark.exe + 0x00123D70` and `+0x00122D10` crash sites both
        confirm that null entries in those lists are fatal
    - the same helper also walks the secondary overlap/object list rooted at
      `movement_context + 0x7C`
      - each secondary entry is expected to expose:
        - `+0x00/+0x04/+0x08/+0x0C` axis-aligned bounds payload
        - `+0x14` collision mask/classification
      - the `SolomonDark.exe + 0x00123E33` teleport crash dereferenced
        `TEST [entry + 0x14], mask` with `entry == 0`
    - the higher-level query wrappers are now partially identified:
      - `MovementCollision_BuildCellOverlapList (0x00521B80)` is the stock
        builder for the primary overlap list rooted at `movement_context + 0x4C`
      - `MovementCollision_QueryType2Hazards (0x00522500)` is the stock
        builder for the secondary hazard/object list rooted at
        `movement_context + 0x7C`
        - if `context + 0x79 != 0`, frees the old secondary list and zeroes
          `context + 0x70/+0x74/+0x7C` before rebuilding
      - `MovementCollision_TestCirclePlacementExtended (0x005238C0)`
        - rebuilds overlap lists from the same movement context
        - first checks the raw movement-circle list at `context + 0xA0/+0xAC`
          and rejects circles whose mask intersects the first query mask
        - then checks occupied cells and type-2 hazard/object overlap using the
          inverted second-mask rule: candidates block when their mask does not
          intersect the query mask
      - is used by several placement/search helpers to find nearby valid points
    - `MovementCollision_TestCirclePlacement (0x00523C90)`
      - smaller placement query used by dynamic-object response
      - returns nonzero when a proposed circle placement is blocked
  - current implementation consequence:
    - these placement-query helpers are a better substrate for a loader-owned
      path solver than guessing raw cell semantics from each `0x18` record
    - the solver can use the native grid for neighbor generation and the native
      collision query wrappers as a traversability oracle
    - null entries in either overlap list are not benign:
      - the `+0x4C` primary list is dereferenced by
        `MovementCollision_ResolveType2Hazards (0x00522CE0)` at
        `SolomonDark.exe + 0x00122D10`
      - the `+0x7C` secondary list is dereferenced by
        `MovementCollision_TestCirclePlacement (0x00523C90)` at
        `SolomonDark.exe + 0x00123E33`
      - that means any relocation path that bypasses the stock builders or
        leaves their preconditions stale can crash later movement/collision
        code even if the immediate transform write "worked"
- Current implication for implementation:
  - if bots need true point A -> point B routing, the clean next substrate is
    this native scene grid plus the existing stock movement executor
    `PlayerActor_MoveStep`
  - remaining unknown is no longer the cell addressing formula; it is whether
    the loader should rely directly on the newly identified placement-query
    wrappers or continue deeper until every cell mask/value is fully named

## Exact Next Runtime Probes

Do these once a native enemy exists in scene, either by entering an active wave or by explicitly spawning one:

```lua
local enemy_actor = 0x???????? -- native enemy actor, not loader bot
local def = sd.debug.read_ptr(enemy_actor + 0x1D0)
print(string.format("enemy=0x%X def=0x%X", enemy_actor, def))
print("pathfinding", sd.debug.read_u8(def + 0xB9))
print("flanking", sd.debug.read_u8(def + 0xB8))
print("interval_1e0", sd.debug.read_i32(enemy_actor + 0x1E0))
print("cadence_1dc", sd.debug.read_i32(enemy_actor + 0x1DC))
print(string.format("target_168=0x%X", sd.debug.read_ptr(enemy_actor + 0x168)))
print("heading_6c", sd.debug.read_float(enemy_actor + 0x6C))
```

Optional watch pair for next session:

```lua
sd.debug.watch("enemy_interval", enemy_actor + 0x1E0, 4)
sd.debug.watch("enemy_target", enemy_actor + 0x168, 4)
```

## Open Questions

- what exact semantic enum does `pathfinding_mode` use beyond observed values `0`, `1`, and `3`?
- which class/vtable family owns `0x00483480`, and can RTTI or constructor recovery turn the current anonymous caller cluster into concrete enemy AI type names?
- which of the `0x00525800` descendants (`0x00521B80`, `0x005218C0`, `0x00522C00`, `0x00522B20`, `0x00526520`) performs actual wall/obstacle resolution?

## Claude Cross-Check

- second-pass review agreed `0x00483480` is a strong anchor for stock chase/pathfinding work
- strongest corrections from that review:
  - `actor + 0x1D0` is a dual-use slot; native enemies use it as a monster-definition pointer, while player/wizard-style actors can reuse it for other runtime state
  - `actor + 0x1E0` is retarget cadence, not speed
  - `0x00525800` should stay aligned with the existing `PlayerActor_MoveStep` naming
- recommended next static targets from that review:
  - `0x00484AA0`
  - `0x004871F0`
  - `0x00489600` thunk / owning vtable
  - `0x00487F60`
