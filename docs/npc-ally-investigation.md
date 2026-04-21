# NPC And Ally Investigation

Date: 2026-04-15

## Latest Pass

- the repo now has a cleaner split between three rails that were easy to
  conflate:
  - ally/NPC **command authoring** under `ScriptingCommand_DispatchBuilder`
  - editor-side `NPC_SETUP` **setup-data** objects
  - native `GameNpc` **gameplay actor** objects
- `FUN_005B7080` is now the verified factory bridge for `GameNpc`
  - case `0x1397`
  - allocates `0x268` bytes
  - calls `GameNpc_Ctor (0x005E9A90)`
- the live `0x42D` runtime carrier is narrower but stronger than before:
  - `FUN_0062C6E0` and `FUN_0062C790` both build live `CodeLine` objects whose
    command id is `0x42D`
  - that means ally-duration semantics are not just editor text; they have a
    concrete runtime payload shape
- fresh loader crash evidence from 2026-04-20 sharpened the `0x447` output
  question:
  - the shared-hub clone handoff returned an actor with live `object_type=0x1`
  - it did **not** return a live `GameNpc (0x1397)`
  - treating that clone as `RegisteredGameNpc` and calling
    `GameNpc_SetMoveGoal` on it crashed stock `PlayerActorTick`
- `UNTIL LULL` is no longer an open ownership question
  - the recovered `ScriptCmd_TripOrTry (0x004E0640)` mode-`6` branch shows it
    belongs to a generic pause/trip command family
  - current evidence does **not** support treating it as part of the direct
    NPC-to-ally builder at `0x447`
- live Lua exec is available in the current workspace session
  - current semantic surfaces expose `scene`, `player`, selection state, and
    `sd.world.list_actors()`
  - typed actor enumeration now exists, although cross-scene validation is
    still limited by scene-switch instability

## Strongest Current Ally Anchor

- `0x004D33B0` now confirmed as a direct ally-control option builder
- verified emitted options:
  - `SPECIFIC HP[0]|INFINITE HP[1]`
  - `STAY CLOSE[0]|GO OFF ON THEIR OWN[1]`
- this is concrete shipped ally-behavior UI / scripting support
- it matches the earlier report strings around:
  - `CHANGE NPCS TO ALLIES`
  - ally HP mode
  - ally follow behavior

Current interpretation:

- Solomon Dark ships real NPC-to-ally control logic
- the ally system is not just summon flavor text
- this is separate evidence from the golem / puppet path

## Higher-Level Command Flow

- `0x004DEDA0` is now the verified high-level scripting command builder
- ally/NPC-relevant verified cases:
  - `0x411` -> `NpcCommands_BuildReferenceNpcsOptions`
  - `0x412` -> `ScriptCmd_BuildDespawnTriggerOptions`
  - `0x417` -> `NPCs NEED HELP` with `WHEN CONVENIENT|URGENTLY`
  - `0x41D` -> `MonsterCommands_BuildReferenceMonstersOptions`
  - `0x42D` -> `NpcCommands_BuildAllyDurationOptions`
  - `0x445` -> label `CHANGE NPCS TO TARGETS`
  - `0x447` -> `NpcCommands_BuildChangeNpcsToAlliesOptions`
  - `0x448` is not ally apply logic; it builds `REDUCE REF'D MONSTER HP BY ...`

### `0x004D0750` -> `ScriptCmd_BuildDespawnTriggerOptions`

Verified option string:

- `WHEN IN DARK[1]|WHEN OFFSCREEN[2]|VIA UNSUMMON[3]|VIA INSTANT REMOVE[4]`

Important correction:

- this row is now recovered
- but it is reached as `ScriptingCommand_DispatchBuilder` case `0x412`
- current evidence says it is a generic scripting command builder row
- it is not yet proven to be the ally-specific sibling I previously suspected

Current interpretation:

- the `WHEN IN DARK / OFFSCREEN / UNSUMMON` options are real shipped scripting
  authoring data
- but they should currently be treated as command-removal / despawn trigger
  options, not specifically NPC ally control

### `0x004D3AF0` -> `NpcCommands_BuildAllyDurationOptions`

Verified option string:

- `FOR A DURATION[1]|UNTIL NO MONSTERS ARE LEFT[2]|UNTIL MONSTER COUNT IS UNDER[3]|UNTIL NO BOSSES ARE LEFT[5]|UNTIL MANUALLY RESTARTED[4]`

Verified follow-up behavior:

- mode `1`
  - emits a duration value
  - renders `SECONDS` or `MINUTES`
- mode `3`
  - emits a numeric threshold
  - renders `MONSTERS REMAIN`

This confirms ally control is broader than just HP/follow mode:

- HP mode
- follow/roam mode
- duration / restart / boss-count / monster-count conditions
- help urgency mode

Still unresolved:

- whether `CHANGE NPCs TO ALLIES (0x447)` rematerializes its output as another `GameNpc (0x1397)` actor or only the clone/player rail after native `GameNpc` targets have already been selected
- how ally duration/restart state is decremented, enforced, and reverted at runtime

### Runtime survival and execution status of ally command ids

Current exact-id result:

- `0x42D` does survive into runtime-side parsed scripting objects
  - `WaveData_Parse` xrefs into `0x0062E870`
  - `0x0062E870` allocates a runtime `Trigger`
  - that trigger owns live `CodeLine` nodes from `0x006821B0`
  - helpers `0x0062C6E0` and `0x0062C790` write `*(line + 4) = 0x42D`
- `0x411`, `0x412`, `0x417`, `0x41D`, `0x445`, `0x447`, and `0x448` now have verified runtime helper paths
  - the broad dispatcher is `0x00689750`
  - `0x411` -> `0x00687700`
  - `0x412` -> `0x00684AB0`
  - `0x417` -> `0x00684E90`
  - `0x41D` -> `0x00687B10`
  - `0x445` -> `0x00684F60`
  - `0x447` -> `0x00684FE0`
  - `0x448` -> `0x00685180`
- runtime boundary is now clearer too:
  - `0x006821B0` is the live `CodeLine` constructor
  - `0x00684040` is the live `Trigger` constructor
  - `Game_OnStartGame` and `WaveData_Parse` both allocate these objects and
    push them into the gameplay trigger collection at `gameplay + 0x8548`
  - `0x00689750` is the broad runtime action dispatcher keyed by
    `action_record + 0x04`
- current conservative interpretation:
  - `0x42D` is definitely part of the parsed runtime trigger rail
  - `0x411/0x417/0x41D/0x445/0x447/0x448` are definitely runtime-implemented action ids
  - `0x411` proves the command rail can explicitly select native `GameNpc (0x1397)` targets at runtime
  - `0x41D` is the hostile/monster-targeting sibling that rebuilds the same action-owned target set for actor group `0x2`
  - what is still not proven is whether `0x447` turns those selected NPCs into
    another `GameNpc` rail or only the clone/player rail reached through
    `WizardCloneFromSourceActor`

### Runtime payload shape for `0x42D`

### Verified runtime helper cases

### Verified `0x411` NPC-reference helper chain

- `0x00687700` (`GameplayAction_ReferenceNpcs`) is the runtime helper reached from action id `0x411`
- builder-side `0x004D86D0` now resolves as the authoring counterpart
  - emits `ALL NPCs AT|CLOSEST NPC TO`
- current recovered behavior:
  - clears or retags the action-owned target cache at `action + 0x6C/+0x74/+0x78` to actor group `0x20`
  - chunk `0` selects `ALL NPCs AT[0]` vs `CLOSEST NPC TO[1]`
  - mode `1` scans the live actor table at `DAT_0081F614 + 4 -> +0x318/+0x324`
  - keeps only actors whose gameplay type is `0x1397`
  - de-duplicates through `0x006853D0`
  - chooses the nearest candidate to the resolved point and registers it through `0x00685350`
  - mode `0` uses the shared region/box/polygon/player-relative collectors and then registers each resulting actor through `0x00685350`
- `0x00685350` and `0x006853D0` are the shared target-set helpers:
  - `0x00685350` appends a unique actor identity from `actor + 0x5C/+0x5E` into the action-owned target list
  - `0x006853D0` is the duplicate check used by the nearest-single path
- current conservative interpretation:
  - `0x411` is the runtime `REFERENCE NPCs` rail
  - it proves the ally/NPC scripting system can explicitly target native `GameNpc (0x1397)` actors at runtime before downstream actions like `0x417`, `0x445`, and `0x447` consume that target list
  - the remaining open question is now the output rail of `0x447`, not whether native `GameNpc`s can be selected

### Verified `0x41D` monster-reference helper chain

- `0x00687B10` (`GameplayAction_ReferenceMonsters`) is the hostile/monster-targeting sibling of `0x00687700`
- builder-side `0x004D8790` is currently named `MonsterCommands_BuildReferenceMonstersOptions`
  - this name is inferred from the runtime counterpart because the authoring strings are generic: `REFERENCE` plus `AT|CLOSEST TO`
- current recovered behavior:
  - clears or retags the action-owned target cache at `action + 0x6C/+0x74/+0x78` to actor group `0x2`
  - mode `1` scans the live actor table and keeps only actors whose group field at `actor + 0x14` equals `2`
  - mode `0` uses the same shared group/radius/rect/polygon/player-relative collectors as the `0x411` NPC rail, but passes group `0x2` instead of `0x20`
  - final registration still flows through `0x00685350`, with an extra subtype gate against `actor + 0x1D0`
- current conservative interpretation:
  - `0x41D` is not an NPC rail and should not be named as one
  - it is the hostile/monster reference sibling that prepares target sets for downstream monster-facing actions

### Shared world collector helpers behind `0x411/0x41D`

- `0x006425C0` -> `ActorWorld_CollectActorsByGroup`
  - clears the world query scratch list at `actor_world + 0x8C2C` and appends every live actor whose group bits overlap the requested mask
- `0x00642090` -> `ActorWorld_CollectActorsInRadiusByGroup`
  - builds a broadphase list, filters it by circle overlap, and appends the survivors into the same scratch list
- `0x00642280` -> `ActorWorld_CollectActorsInRectByGroup`
  - axis-aligned area query helper reused by the selector rails and by `Coffin_Tick`
- `0x00642680` -> `ActorWorld_CollectActorsInPolygonByGroup`
  - polygon/region query helper that filters candidates against the active shape before appending them
- `0x00642410` -> `ActorWorld_CollectActorsNearCurrentPlayerByGroup`
  - player-relative query helper that resolves the current player slot through `DAT_0081F610 + 0x96` / `DAT_0081C264 + 0x1358` and builds a nearby target list
- current conservative interpretation:
  - these helpers are group-parameterized world queries, not NPC-specific helpers
  - the `0x411` and `0x41D` rails are thin wrappers that select the actor family (`0x20` vs `0x2`) and then feed the resulting targets into the common action-owned target-set machinery

### Verified `0x412` state-setting helper chain

- `0x00684AB0` (`GameplayAction_SetNpcBranchState`) is the runtime helper reached from action id `0x412`
- current recovered behavior:
  - iterates the target list
  - resolves each target actor from the current world bucket table
  - writes action chunk `0` into target field `actor + 0x181`
- current conservative interpretation:
  - this is the first direct runtime bridge from the action dispatcher into the native `GameNpc` branch-state byte already used by `GameNpc_Tick`
  - if the resolved targets for `0x412` are `GameNpc` actors, this helper can drive that state machine directly
  - this makes the old builder-only reading of `0x412` too narrow on the runtime side

### Verified `0x417` follow/help helper chain

- `0x00684E90` (`GameplayAction_NpcsNeedHelp`) is the runtime helper for action id `0x417`
- its current recovered behavior is narrower than the authoring text suggests:
  - iterates the target list
  - resolves each target actor from the current world bucket table
  - reads chunk `0` from the action record
  - calls `0x005EA450`
- `0x005EA450` now resolves as:
  - store gameplay slot into `npc + 0x1C2`
  - call `0x005E9D50` to prime follow/move state
  - set callback flag `+0x1C3` when the third parameter requests it
- `0x005E9D50` now resolves as the lower follow/move helper that:
  - sets move flag `+0x198`
  - sets mode byte `+0x1AC`
  - writes desired goal to `+0x19C/+0x1A0`
  - snapshots that goal at `+0x1A4/+0x1A8`
  - resets cadence/timing at `+0x1B0/+0x1B8`
- current conservative interpretation:
  - `NPCs NEED HELP` is now proven to have a live assist/follow-style runtime path
  - current evidence points more toward target-slot assistance / escort behavior than a direct attack issue

- `0x00689750` is the missing execution seam
  - earlier local naming as a create-screen action handler was too narrow
  - it is a broad runtime action dispatcher over ids in the `0x3E9..0x448` band
- `0x42D`
  - is executed directly inside `0x00689750`
  - mode/tag comes from chunk `0`
  - live record payload is resolved through `0x00683B90(1)`
  - runtime fields at `record + 0x8C` and `record + 0x90` are updated from the
    action payload
- `0x417` -> `0x00684E90`
  - iterates the target list at `action + 0x74/+0x78`
  - resolves each target actor from the current world bucket table
  - calls `0x005EA450` using chunk `0` as the help/urgency mode
- `0x445` -> `0x00684F60`
  - iterates the same target list
  - resolves each target actor
  - calls `0x005E3050(target_actor)`
- `0x447` -> `0x00684FE0`
  - iterates the target list
  - resolves each target actor
  - runs `WizardCloneFromSourceActor`
  - then applies extra ally parameters from chunks `0..2`
- `0x448` -> `0x00685180`
  - if `action + 0x6C == 2`, iterates the target list
  - resolves each hostile actor
  - scales target field `+0x174` downward using a percentage payload

- `FUN_0062C6E0`
  - allocates a live `CodeLine`
  - writes `*(line + 4) = 0x42D`
  - writes payload chunks:
    - chunk `0` -> `0`
    - chunk `1` -> caller-supplied value
    - chunk `2` -> `4`
- `FUN_0062C790`
  - allocates a live `CodeLine`
  - writes `*(line + 4) = 0x42D`
  - writes payload chunks:
    - chunk `0` -> `1`
    - chunk `1` -> caller-supplied value
- current conservative interpretation:
  - `0x42D` has at least two distinct runtime encodings
  - they look like mode-tagged variants of the ally-duration / restart family,
    not just one monolithic text row
  - this is the strongest current proof that the ally-duration builder has a
    real runtime representation

### `UNTIL LULL` status

- direct refs to the exact literal `UNTIL LULL` at `0x0078EB62` are `0`
- but the pooled combined row
  - `FOR A DURATION[1]|UNTIL LULL[6]|...`
  - lives at `0x0078EB50`
  - and is referenced from `caseD_3` (`0x004E0739`) in the
    `ScriptCmd_TripOrTry` path
- recovered `ScriptCmd_TripOrTry (0x004E0640)` behavior now clarifies the owner:
  - case `3` is a generic `PAUSE` builder
  - mode `1` renders `OF <duration> SECONDS|MINUTES`
  - mode `3` renders a numeric threshold
  - mode `6` is the `UNTIL LULL` branch and emits:
    - a mode label from the owner
    - a duration
    - `OR LESS THAN`
    - a monster-count threshold
    - `MONSTERS REMAIN`
- current interpretation:
  - `UNTIL LULL` is real shipped command data
  - it belongs to the generic pause/trip builder family, not the direct
    `CHANGE NPCs TO ALLIES` builder cluster

## NPC_SETUP Authoring Side

### `FUN_004BE400` -> editor-side NPC setup mutation handler

- reacts to editor/property labels including:
  - `MAKE NEW NPC`
  - `CAN TALK`
  - `REMOVE NPC WHEN DONE`
  - `TYPE:`
- `MAKE NEW NPC` allocates factory type `0x1774`
- when the selected setup record is active, or when key NPC-side properties
  change, it calls `FUN_004B53F0` to rebuild the current setup object
- current conservative interpretation:
  - this is setup-data/editor plumbing
  - it is not the native `GameNpc` actor constructor

### `FUN_004B53F0` -> `NPC_SETUP` record parser / refresher

- parses fields under the `NPC_SETUP` namespace into the object at
  `param_1 + 0x210`
- recovered inputs include:
  - `NPC_SETUP|REFERENCE_NAME:`
  - `NPC_SETUP|DISPLAY_NAME:`
  - `CAN TALK`
  - `REMOVE NPC WHEN DONE`
  - `TYPE:`
  - `WIZARD'S MAGIC TYPE`
- also refreshes several visual / variant fields around:
  - `+0x54`
  - `+0x55`
  - `+0x56`
  - `+0x74`
  - `+0x78..+0x79`
  - `+0xA0..+0xA8`
- current conservative interpretation:
  - this object is the editor/setup-data counterpart for shipped NPC records
  - it is a separate rail from factory type `0x1397`

### `FUN_004BE530` -> editor selection / record handoff helper

- xrefs from the `NPC_SETUP` parser land in `FUN_004BE530`
- when the visible row and current setup record line up, it refreshes through
  `FUN_004B53F0`
- current conservative interpretation:
  - this is selection-state/editor synchronization, not gameplay actor logic

### `FUN_004B5110` -> NPC setup list builder

- the `NPC_SETUP` string xref at `0x0078AD0C` lands here
- current recovered behavior:
  - walks the global NPC setup table under `DAT_0081993C + 0x8A00/0x8A0C`
  - allocates `0x1B0` row objects
  - publishes them into the owning editor/list surface
- current interpretation:
  - this is the shipped NPC setup browser/list rail
  - it should not be treated as proof that the same object layout is a live
    hub/gameplay actor

## GameNPC Runtime Side

### `0x005E9A90` -> `GameNpc_Ctor`

Recovered facts:

- installs `GameNPC::vftable`
- writes gameplay object type `0x1397`
- seeds kind/group `0x20`
- initializes a wide block of movement/render/runtime fields
- seeds two float4-like color blocks near `+0x244..+0x263`
- zeros a large set of state bytes including:
  - `+0x1C2 = 0xFF`
  - `+0x1C3 = 0`

Current caution:

- the earlier `0x00797B7C` association was wrong
- current verified ctor write is:
  - `GameNPC::vftable = 0x0079CEBC`
- matching scalar-deleting destructor:
  - `0x005E9CB0`
- adjacent vtable at `0x0079CF34` is unrelated:
  - `UnholySpit::vftable`
- the factory bridge is now verified too:
  - `FUN_005B7080` case `0x1397`
  - `Object_Allocate(0x268)`
  - `GameNpc_Ctor`

Working interpretation:

- this is a real native gameplay actor family in the object factory
- factory type `0x1397` -> `GameNpc_Ctor`
- the object/vtable identity is now materially stronger than before

### `GameNPC::vftable` (`0x0079CEBC`) current slot map

- shared/base slots still match the broader actor rail:
  - `+0x00` -> `GameNpc_Dtor (0x005E9CB0)`
  - `+0x18` -> `ActorVisual_SetInitFlag (0x00401FD0)`
  - `+0x38` -> `ActorMoveByDelta (0x00623C60)`
  - `+0x44` -> `0x00622F90`
  - `+0x48` -> `0x00622FB0`
  - `+0x5C` -> `0x00628AD0`
- unique `GameNpc`-side slots now recovered:
  - `+0x08` -> `0x00608110`
    - main update / state-machine path
    - lazily resolves a handle into `param_1[0x5E]`
    - branches on state byte `+0x181`
    - can steer facing toward the local player when `(short)+0x1C0 == 1`
  - `+0x0C` -> `0x00518280`
    - overlay/icon render path gated by state around `+0x154`
  - `+0x14` -> `0x005E3330`
    - serializes / restores a wide NPC-owned state block
    - on non-editor loads can dispatch another virtual slot when a persisted
      flag is set
  - `+0x1C` -> `0x00622430`
    - larger HUD/icon render path branching on mode at `+0x174`
  - `+0x28` -> `0x006046C0`
    - complex world/render effect path
  - `+0x30` -> `0x005EA110`
    - chooses a marker asset, calls an owner-region virtual, then calls
      `0x0057FE40`
  - `+0x4C` -> `0x00627F80`
    - copies global palette/alpha values into `+0x78..+0x90`
    - then delegates into `0x00625150`
  - `+0x50` -> `0x00622FD0`
    - dispatches slot `+0x18` and returns `1`
- current conservative interpretation:
  - `GameNpc` is not just a dead preview shell
  - it has its own tick/state, render/marker, and serialization hooks
  - but I still do **not** have proof that `CHANGE NPCs TO ALLIES` targets this
    exact class at runtime

### Correction: `0x006B2B10` is not GameNPC

- this function was previously mislabeled in local artifacts
- current verified identity:
  - libcurl-style easy-setopt helper
  - cookies, strings, slists, timeouts, callback pointers, and option bits
- consequence:
  - current ally/NPC branch must not rely on `0x006B2B10`
  - a real NPC-side property handler still needs to be found elsewhere

## Relation To Bot / Companion Work

- earlier badguy/pathfinding work showed hostile AI lives on the `Badguy` chain
- NPC ally control is now visibly separate:
  - explicit “change NPCs to allies” UI/builder logic
  - a dedicated native NPC/runtime actor class at factory type `0x1397`
- `GoodGuy` family is now narrower than earlier guesses:
  - `Puppet_Ctor (0x006287D0)` is the shared lower player-style layer
  - `GoodGuy_Ctor (0x0052A410)` is called by:
    - `Player_Ctor (0x0052A500)`
    - `Golem_Ctor (0x005F57E0)`
  - `PlayerWizard (0x0052B4C0)` and `PlayerTarget (0x0052C790)` both extend
    `Player_Ctor`, not `GoodGuy` directly
- current interpretation:
  - `GoodGuy` is real player/ally infrastructure
  - but it is not the same thing as the native NPC actor family at `0x1397`
  - golem/summon-side reuse still exists inside that branch

## Current GameNpc Combat AI Model

### Main update rail

- current strongest combat/AI anchor is `GameNpc::vftable + 0x08`
  - `0x00608110`
- this function is **not** the stock hostile `Badguy` chase rail
- current recovered model is a state-machine NPC brain with:
  - lazy behavior-record lookup from `+0x17C -> +0x178` through `0x006451D0`
  - optional owner-side active-list registration when mode `+0x174` is `1` or `3`
  - optional movement/follow handling through `0x006042C0` when `+0x198 != 0`
  - branch-specific gate logic driven by state byte `+0x181`
  - late action dispatch through `0x005E9F70`
  - late cadence / facing maintenance using `+0x18C..+0x1C4`

### Behavior record dependency

- `0x006451D0` is the current resolver for the record id at `GameNpc + 0x17C`
- it scans multiple owner-side tables and returns the first record whose id field
  matches
- current conservative interpretation:
  - `GameNpc` combat behavior is descriptor-driven, not hard-coded per NPC type
  - the resolved record at `+0x178` is likely where spell/action metadata lives
  - this is different from the hostile monster rail, which reads
    `enemy_config/pathfinding_mode` through `+0x1D0`

### Branch state at `+0x181`

Current recovered states:

- state `1`
  - runs an owner callback and a line/visibility gate before allowing the late
    action dispatch
  - current interpretation: visibility-gated action state
- state `2`
  - calls `0x0064AA80`, which iterates live gameplay slot actors and tests the
    NPC's projected trigger/interaction volume against them
  - current interpretation: proximity / overlap-gated action state
- state `3`
  - calls `0x00640830`, which allocates and attaches multiple effect/helper
    objects into owner-managed lists
  - current interpretation: explicit spawned action/effect state
- state `4`
  - falls straight through to the late dispatch path with no extra gate
  - current interpretation: passive/immediate action state

### Movement and follow logic

- `0x006042C0` is the clearest current movement helper for this class
- it is **not** the `Badguy_CommonChaseTick` path
- recovered behavior:
  - tracked gameplay-slot index lives at `+0x1C2`
  - if the tracked slot actor exists, the NPC rebuilds a desired goal at
    `+0x19C/+0x1A0` around that actor
  - when the NPC reaches the goal it clears `+0x1C2`, clears move flag `+0x198`,
    and can fire vtable slot `+0x68` when `+0x1C3 != 0`
  - when the direct goal is not ready, it recomputes a waypoint every ~200 ticks
    and ultimately moves through the stock `PlayerActor_MoveStep (0x00525800)`
  - move scalar ramps through `+0x1B4` and is capped from byte `+0x1AC`
- current interpretation:
  - this class supports escort/follow-style movement around live slot actors
  - it does not look like stock monster pursuit/pathfinding

### Late action dispatch

- after branch gating, `0x00608110` falls into `0x005E9F70`
- `0x005E9F70`:
  - ensures the actor has passed the stock visual-init path when needed
  - reads two fields from the resolved record at `+0x178`
    - `record + 0x90`
    - `record + 0x98`
  - forwards them together with current NPC context into `0x0068BB10`
- current interpretation:
  - this is the strongest current seam for actual combat/action execution
  - if ally-converted NPCs really fight, this dispatch path is a prime runtime
    candidate for where that action is issued

### Facing, readiness, and combat cadence

- the tail of `0x00608110` maintains several transient fields:
  - `+0x18C` is reset each tick before late cadence work
  - `+0x1B8` / `+0x1BC` accumulate runtime timing/state
  - `+0x1C4` decays over time and is also read by render-side vtable slots
    `+0x0C` / `+0x1C`
  - when `+0x1C0 == 1`, the NPC can recompute heading from the local player
    actor position
- current interpretation:
  - the class has explicit combat-readiness / presentation timing, not just
    one-shot scripted actions

### Current bottom line

- there is now good evidence for a native `GameNpc` combat-capable AI rail
  with:
  - descriptor-driven behavior lookup
  - follow/goal movement
  - gated action states
  - a final action dispatch seam
- what is still **not** proven:
  - that `CHANGE NPCs TO ALLIES (0x447)` rematerializes its output as another `GameNpc (0x1397)` actor instead of only the clone/player rail
  - which exact record family `0x006451D0` resolves for ally-converted NPCs
  - whether the late dispatch path creates direct attacks, support effects, or
    both

Direct loader-side evidence now leans toward the clone/player reading:

- `WizardCloneFromSourceActor` returns a `PlayerWizard`-family actor
  (`PlayerActorCtor` writes gameplay object type `0x1`)
- the loader's 2026-04-20 shared-hub crash came from binding that clone as
  `RegisteredGameNpc` and then driving `GameNpc_SetMoveGoal`
- so the current conservative model should treat clone-handoff output as
  player/ally rail until contrary stock evidence is recovered

## Current Live Runtime Surface

- the Lua exec bridge is live in the current workspace session
- current semantic gameplay surfaces are:
  - `sd.world`
    - `get_scene`
    - `get_state`
    - `list_actors`
    - `spawn_enemy`
    - `spawn_reward`
  - `sd.gameplay`
    - `get_selection_debug_state`
    - `start_waves`
- current live scene observations from this pass:
  - one validated `testrun` sample reported `scene.kind = arena`, `region_index = 5`, and no live actor with type `0x1397` or vtable `0x0079CEBC`
  - a fresh post-launch sample also showed an earlier boot state where the Lua pipe was live but `sd.world.get_scene()` still returned `nil`
- current `sd.world.list_actors()` status:
  - implemented in the loader, rebuilt successfully, and verified live through Lua
  - current validated `testrun` sample returns 4 live actors
  - current validated `testrun` sample contains no actor with type `0x1397` or vtable `0x0079CEBC`

- current limitation:
  - typed scene-actor enumeration now exists, but live validation is still constrained by scene activation / switching instability
  - the current process can reach a pipe-live / scene-nil state before gameplay scene ownership settles
  - switching `testrun -> hub` through `sd.debug.switch_region(0)` currently faults inside the loader path with `0xC0000005`
- current runtime caveat from the live pass:
  - switching `testrun -> hub` through `sd.debug.switch_region(0)` currently faults inside the loader path with `0xC0000005`
  - the staged loader log captured the exception while the game was in `testrun`
  - current interpretation: this is a loader/runtime instability around scene switching, not ally-specific proof by itself, but it currently limits live scene-to-scene validation

- current manual hub bucket scan result:
  - filtering by owner/world match plus executable first vtable slot yields a
    stable set of live hub actors
  - current hub sample contains actor types `0x1389`, `0x138A`, `0x138B`,
    `0x138C`, `0x138D`, `0x138F`, `0x1390`, `0x7D7`, and `0x7D8`
  - recovered ctor identities now tie the visible hub actor family to:
    - `0x1389` -> `PerkWitch`
    - `0x138A` -> `Student`
    - `0x138B` -> `Annalist`
    - `0x138C` -> `PotionGuy`
    - `0x138D` -> `ItemsGuy`
    - `0x138F` -> `Tyrannia`
    - `0x1390` -> `Teacher`
  - current hub sample does **not** contain any actor whose vtable resolves to
    `GameNPC::vftable (0x0079CEBC)`
  - current conservative interpretation:
    - the currently visible hub NPCs are a separate native actor family from
      `GameNpc (0x1397)`
    - native hub NPCs in the present scene are not materialized as `GameNpc`
      objects, or the relevant `GameNpc` instances are not published through the
      scanned world-bucket window

## Monster Brain Side

Separate from the editor-side ally builders, a nearby actor cluster now looks more
like concrete monster-family runtime behavior than teammate-NPC command execution:

- `0x0052BB60` (`SpellCast_Family3EF`)
  - creates `Anim_Iceblast`
  - conditionally spawns gameplay object type `0x7E2`
  - clearly lives on the combat / summon side, not the scripting-editor side
- `0x00484B90` -> `Skeleton_Tick`
  - uses slot byte `+0x236`, target pointer `+0x168`, and leash distance at `+0x23C`
  - can snap or drag a linked slot actor back toward the owner
  - spawns visual/effect actor `0x7E3`
- `0x00485200` -> `SkeletonArcher_Tick`
  - drives a target-focused behavior using `actor + 0x168` / `+0x5A`
  - uses timers `+0x97/+0x98/+0x99`
  - also spawns type `0x7E3`
- `0x00487300` -> `Demon_Tick`
  - owns a large orbit/effect state block around `+0x260..+0x2B8`
  - performs demon-specific helper/effect updates
- `0x00489000` -> `Heartmonger_Tick`
  - manages child/object lists at `+0x268/+0x25C`
  - maintains timers and counters at `+0x2A0..+0x2B8`
  - registers helper/child actors and iterates them through a virtual callback
- `0x0052C1A0` -> `GoodImp_Tick`
  - slot-2 method on `GoodImp::vftable`
  - resolves targets from region slot tables through `+0x90/+0x242`

Current conservative reading:

- this cluster is not the teammate-NPC ally brain
- it is concrete monster-family runtime logic
- it is concrete runtime behavior
- but it is not yet the clean NPC-side apply path for the `CHANGE NPCs TO ALLIES`
  command family

## Best Next Targets

- trace the runtime decrement / revert path for `0x42D`
  - the dispatcher write into `record + 0x8C/+0x90` is mapped, but the timer / threshold enforcement path is still missing
- trace `ActionRecord_ReadChunkPayload (0x00683B90)` callsites that consume the `0x42D` record and identify the duration/revert enforcement path
- prove whether `0x447` output is always clone/player-like even when `0x411` has already selected native `GameNpc (0x1397)` targets
- turn the currently anonymous `GameNpc` vtable slots into named behaviors with
  field-level meanings
- keep using `sd.world.list_actors()` once scene switching is stable so ally conversion can be validated live across hub and combat scenes
