# Hub NPC Investigation

Date: 2026-04-15

## Scope

This note focuses on the native actors visible in the shared hub:

- roaming friendly NPCs running around the courtyard
- named traders or other stationary hub characters
- nearby static hub-side world actors that are easy to confuse with NPC runtime

The goal is to separate those families, identify their factory types, and recover
their movement stack.

## Live Hub Census

Live runtime sampling in the shared hub through the Region-side actor manager at
`world + 0x310` shows these active gameplay-object families:

- `0x138A` x14
- `0x1389` x1
- `0x138B` x1
- `0x138C` x1
- `0x138D` x1
- `0x138F` x1
- `0x1390` x1
- `0x7D7` x8
- `0x7D8` x1
- `0x1` x2
  - local player plus one loader bot in the sampled run

Important negative result:

- live shared-hub sampling found **no** active `0x1397` objects
- the previously recovered `GameNpc_Ctor (0x005E9A90)` therefore does **not**
  describe the roaming hub courtyard population in the sampled shared hub

## Type Mapping

### Roaming family

- `0x138A` allocates `0x250` bytes in the factory and runs ctor
  `0x00501B80`
- the recovered ctor writes:
  - `Student::vftable`
  - gameplay object type `0x138A`
  - randomized movement-state fields and a small per-instance count/state block

Current interpretation:

- the roaming hub NPCs are a dedicated `Student` actor family
- they are not the `GameNPC` / `0x1397` family
- they are also not the `GoodGuy` / player-chain family

### Named hub characters

The existing hub backend decompile for the hub region builder maps the one-off
named hub characters directly:

- `0x1389` -> witch
- `0x138C` -> potion guy
- `0x138B` -> Annal
- `0x138D` -> scavenger
- `0x138F` -> enforcer
- `0x1390` -> teacher

Those mappings come from the builder's dialogue and label strings such as:

- `WITCH_INTRO`
- `POTIONGUY_INTRO`
- `ANNAL_INTRO`
- `SCAVENGER_INTRO`
- `ENFORCER_INTRO`
- `TEACHER_INTRO`

### Static world actors

Two nearby hub-side families are easy to mistake for NPC runtime if only their
world presence is sampled:

- `0x7D7` -> `CollegeObstacle`
- `0x7D8` -> `CollegeStatue`

These are not roaming NPCs.

## Movement And Pathing

### What actually moves in the shared hub

A repeated live position sample over roughly 2.5 seconds showed measurable
motion only for `0x138A` actors.

In the same sampling window:

- named hub characters (`0x1389/0x138B/0x138C/0x138D/0x138F/0x1390`) stayed
  fixed
- `0x7D7` / `0x7D8` static world actors stayed fixed

### Shared stock movement executor

Tracing `PlayerActor_MoveStep (0x00525800)` in the shared hub showed only
`0x138A` actors in the captured hit window.

For those hits:

- `arg0` was always a live `0x138A` actor pointer
- `ecx` was always the shared world movement controller at `world + 0x378`
- the return address was inside the `0x138A` slot-2 update path at `0x0070A4E0`

This is the strongest current movement conclusion:

- roaming students use the same stock collision-aware movement executor as other
  gameplay actors
- they are not moving through a separate hub-only kinematic path
- hub roaming therefore still sits on the native cell-grid plus movement
  controller stack

### High-level steering owner

Live vtable dumping on `0x138A` actors showed:

- `Student::vftable`
- slot `+0x08` / vtable slot 2 points at `0x0070A4E0`

Tracing `0x0070A4E0` directly hit only `0x138A` actors.

Current interpretation:

- `0x0070A4E0` is the effective `Student` update or tick entry used for roaming
- the `Student` family owns its own high-level steering
- that steering eventually routes into the stock `PlayerActor_MoveStep`
  executor

## Pathfinding Model

Current best model for roaming hub NPCs:

- native family: `Student` (`0x138A`)
- high-level behavior: dedicated `Student` wander or roam controller
- low-level movement: shared stock movement controller at `world + 0x378`
- collision and placement substrate: the same stock grid and collision movement
  path used elsewhere via `PlayerActor_MoveStep`

What this does **not** currently look like:

- `Badguy` hostile chase logic
- `MonsterPathfinding_RefreshTarget`
- `GameNPC` / `0x1397`
- a separate hub-only navmesh system

## Caveats And Open Questions

- `0x0070A4E0` currently decompiles poorly because Ghidra treats it as a
  mid-function entry inside a larger recovered function body
- the current evidence strongly suggests `Student` roaming does not reuse the
  hostile `Badguy` / `MonsterPathfinding_*` path, but that is not yet proven by
  a full static call-tree recovery from `0x0070A4E0`
- the exact shared-hub spawn or init site that creates the `Student` population
  is still not recovered
- `GameNPC` / `0x1397` remains real, but in the sampled shared hub it is not the
  roaming NPC family
- the named hub-character families above are mapped from the hub backend builder,
  but their own tick or interaction methods still need a dedicated pass if we
  want trader-specific runtime behavior rather than type identity only
