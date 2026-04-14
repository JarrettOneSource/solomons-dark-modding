# NPC And Ally Investigation

Date: 2026-04-13

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
- ally-relevant verified cases:
  - `0x412` -> `ScriptCmd_BuildDespawnTriggerOptions`
  - `0x417` -> `NPCs NEED HELP` with `WHEN CONVENIENT|URGENTLY`
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

- exact builder owner for the `UNTIL LULL` variant
- actual runtime apply path after these builder rows are authored

### Runtime survival status of ally command ids

Current exact-id sweep result:

- `0x42D` does survive into runtime-side parsed scripting objects
  - `WaveData_Parse` xrefs into `0x0062E870`
  - `0x0062E870` allocates a runtime `Trigger`
  - that trigger owns live `CodeLine` nodes from `0x006821B0`
  - helpers `0x0062C6E0` and `0x0062C790` write `*(line + 4) = 0x42D`
- current sweep did **not** find analogous runtime `CodeLine` writers for:
  - `0x412`
  - `0x417`
  - `0x445`
  - `0x447`
- runtime boundary is now clearer too:
  - `0x006821B0` is the live `CodeLine` constructor
  - `0x00684040` is the live `Trigger` constructor
  - `Game_OnStartGame` and `WaveData_Parse` both allocate these objects and
    push them into the gameplay trigger collection at `gameplay + 0x8548`
- current conservative interpretation:
  - ally duration/restart semantics are definitely part of live parsed trigger data
  - the direct `CHANGE NPCs TO ALLIES` / `NPCs NEED HELP` rows are still only
    proven in authoring/display surfaces so far
  - current static dead end is meaningful: in the recovered parsed-script paths
    (`WaveData_Parse`, `Game_OnStartGame`, `FUN_00686400`) I still do not see
    `0x412/0x417/0x445/0x447` being emitted into runtime `CodeLine` objects

### `UNTIL LULL` status

- direct refs to the exact literal `UNTIL LULL` at `0x0078EB62` are `0`
- but the pooled combined row
  - `FOR A DURATION[1]|UNTIL LULL[6]|...`
  - lives at `0x0078EB50`
  - and is referenced from `caseD_3` (`0x004E0739`) in the
    `ScriptCmd_TripOrTry` path
- current interpretation:
  - `UNTIL LULL` is real shipped command data
  - but it is currently anchored in the generic scripting command display/build
    path, not in the ally-only builder cluster

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

Working interpretation:

- this is a real native gameplay actor family in the object factory
- factory type `0x1397` -> `GameNpc_Ctor`
- the object/vtable identity is now materially stronger than before

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
  - likely a dedicated NPC/runtime actor class, though exact vtable identity is still provisional
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

- find the real NPC-side property or command applier used after the ally builders
- recover the sibling builder that owns:
  - `UNTIL LULL`
- distinguish true NPC ally runtime from adjacent monster-family brains and
  summon-side spell handlers
