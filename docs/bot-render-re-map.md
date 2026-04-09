# Bot Render RE Map

This note records the recovered Solomon Dark standalone wizard path now used by the loader for visible bot puppets.

## Loader Path

- The loader materializes wizard bots through the player ctor directly, not through `Gameplay_CreatePlayerSlot`.
- The live standalone pipeline is:
  - allocate `0x398` bytes with `_aligned_malloc(..., 16)`
  - zero the allocation
  - call `FUN_0052B4C0(self)` at `0x0052B4C0`
  - assign the scene/world pointer at `actor + 0x58`
  - build standalone progression and equip wrappers
  - seed wizard visuals from `wizard_id` through the runtime/progression state
  - allow stock `PlayerActorTick` to run so the render pipeline advances the bot sprite
  - call `ActorWorld_Register(world, actor)` at `0x0063F6D0`
  - publish the actor into a real gameplay slot at `gameplay + 0x1358 + slot * 4` (`slot 1..3`)
  - keep `actor + 0x04` non-null so the bot has a scene attachment for sprite rendering
  - clear slot identity mirrors only when they interfere with standalone ownership, not the render slot table itself
- The loader still does not use `Gameplay_CreatePlayerSlot`, but arena rendering does require the bot to exist in the gameplay slot table.

## Recovered Standalone Spawn Sequence

- Standalone actor allocation size: `0x398`
- Player ctor: `FUN_0052B4C0` (`0x0052B4C0`)
- World register: `ActorWorld_Register` (`0x0063F6D0`)
- World unregister: `ActorWorld_Unregister` (`0x0063F600`)
- Standalone puppets remain world actors only. They are not allied slot actors and do not rely on the built-in ally roster.

## Constructor Chain

- `FUN_00401FF0` (`0x00401FF0`): `Object_Ctor`
- `FUN_006287D0` (`0x006287D0`): `Puppet_Ctor`
- `FUN_0052A410` (`0x0052A410`): `GoodGuy_Ctor`
- `FUN_0052A500` (`0x0052A500`): `Player_Ctor`
- `FUN_0052B4C0` (`0x0052B4C0`): final `PlayerActor` ctor
- Each constructor layer writes its own vtable before handing off to the next layer in the chain.
- `Object_Ctor` seeds `actor + 0x04` with a temporary ctor sentinel and live game initialization later replaces that slot with the heap-backed render context used for arena sprite attachment.

## Verified Functions

- `Object_Ctor` (`0x00401FF0`): base object constructor. Seeds the render-context slot at `actor + 0x04` and participates in the allocator/global tracking path.
- `Object_Allocate` (`0x00402030`): allocator that calls `operator_new` and stores the result in `DAT_00B4019C`. Swapping it in for `_aligned_malloc` caused heap corruption during bot render-node probes.
- `Puppet_Ctor` (`0x006287D0`): puppet-layer constructor in the player actor chain.
- `GoodGuy_Ctor` (`0x0052A410`): ally/good-guy constructor in the player actor chain.
- `Player_Ctor` (`0x0052A500`): player-layer constructor in the player actor chain.
- `FUN_0052B4C0` (`0x0052B4C0`): player actor ctor used for standalone wizard materialization.
- `ActorVisual_SetInitFlag` (`0x00401FD0`): tiny vtable helper that writes `*(uint8_t *)(actor + 0x05) = 1`.
- `FUN_00513090` (`0x00513090`): render/update path that requires a valid world/context pointer at `actor + 0x58`.
- `FUN_0061AA00` (`0x0061AA00`): stock wizard-puppet factory used by the game to clone a renderable wizard actor from an existing wizard source.
- `PlayerActorDtor` (`0x0052D340`): player actor destructor at vtable slot `0`.
- `PlayerActorTick` (`0x00548B00`): stock player tick. This must run on the bot for visible sprite rendering.
- `PlayerActorMoveStep` (`0x00525800`): stock movement step helper used as reference for puppet movement support.
- `ActorWorld_Register` (`0x0063F6D0`): inserts the actor into the live world bucket table.
- `ActorWorld_Unregister` (`0x0063F600`): used during loader-owned bot cleanup.

## Player Actor Vtable Dump

- Base address: `0x00793F74`
- Dumped from the analyzed `SolomonDark.exe` image on April 9, 2026.

```text
[00] +0x00  0x0052D340  PlayerActorDtor
[01] +0x04  0x0052B900  FUN_0052B900
[02] +0x08  0x00548B00  PlayerActorTick
[03] +0x0C  0x00528A60  FUN_00528A60
[04] +0x10  0x0042E260  FUN_0042E260
[05] +0x14  0x00529C90  FUN_00529C90
[06] +0x18  0x00401FD0  ActorVisual_SetInitFlag
[07] +0x1C  0x0054BA80  ActorAnimationAdvance
[08] +0x20  0x005468C0  FUN_005468C0
[09] +0x24  0x0052C2A0  FUN_0052C2A0
[10] +0x28  0x00528AD0  FUN_00528AD0
[11] +0x2C  0x0055C300  FUN_0055C300
[12] +0x30  0x005299A0  FUN_005299A0
[13] +0x34  0x00448D50  FUN_00448D50
[14] +0x38  0x00623C60  ActorMoveByDelta
[15] +0x3C  0x00448D60  FUN_00448D60
[16] +0x40  0x005489E0  FUN_005489E0
[17] +0x44  0x00622F90  FUN_00622F90
[18] +0x48  0x00622FB0  FUN_00622FB0
[19] +0x4C  0x00548150  FUN_00548150
[20] +0x50  0x00534120  FUN_00534120
[21] +0x54  0x00528A70  FUN_00528A70
[22] +0x58  0x00550180  FUN_00550180
[23] +0x5C  0x00628AD0  FUN_00628AD0
```

## Verified Gameplay Offsets

- Gameplay player table: `gameplay + 0x1358 + slot * 4`
- Gameplay progression wrapper table: `gameplay + 0x1654 + slot * 4`
- The gameplay player table is part of the arena render gate: the bot must be published into slot `1..3`.
- Slot `-1` stays invisible, and slot `0` conflicts with the local player path.
- The progression wrapper table is still separate from the immediate sprite-visibility gate.

## Verified Actor Offsets

- Render context / scene-graph node pointer: `actor + 0x04`
- Init flag byte: `actor + 0x05`
- World/context pointer: `actor + 0x58`
- Gameplay slot byte: `actor + 0x5C`
- World bucket slot short: `actor + 0x5E`
- Position: `actor + 0x18`, `actor + 0x1C`
- Heading: `actor + 0x6C`
- Animation drive byte: `actor + 0x160`
- Source profile pointer: `actor + 0x178`
- Equip runtime pointer: `actor + 0x1FC`
- Progression runtime pointer: `actor + 0x200`
- Animation state pointer: `actor + 0x21C`
- Render frame table pointer: `actor + 0x22C`
- Render descriptor block: `actor + 0x244`
- Actor-side visual attachment field: `actor + 0x264`
- Progression wrapper pointer: `actor + 0x300`
- Equip wrapper pointer: `actor + 0x304`
- Registered slot mirrors: `actor + 0x164`, `actor + 0x166`

## Arena vs. Hub Visual State

- Arena rendering does not require the hub visual-link path to be populated.
- In live arena probes, the local player still renders with these fields unset:
  - `actor + 0x178` (source profile)
  - `actor + 0x1FC` (equip runtime)
  - `actor + 0x200` (progression runtime)
  - `actor + 0x21C` (anim state pointer)
  - `actor + 0x22C` (render frame table)
- Those fields matter in the hub clone path, but they are not the arena sprite-visibility gate.

## Live April 9 Probe

- Local player dump after bot materialization:
  - `+0x04 = 0x14010000`
  - `+0x05 = 0`
- Fresh standalone bot dump after ctor/register:
  - `+0x04 = 0x00010101`
  - `+0x05 = 1`
- Copying or sharing the player's `+0x04` value makes the bot sprite appear, but also parents the bot transform to the player.

## Critical Invariants

- `actor + 0x04` is the current arena render-context gate. A null or unresolved value gives the bot collision without a visible sprite. Sharing the player's value makes the bot visible but also parents it to the player transform, so the bot needs its own render node.
- `Object_Ctor` seeds `actor + 0x04` with a ctor sentinel, and real initialized actors later get a heap pointer there during game initialization.
- `Object_Allocate` writes its allocation to `DAT_00B4019C`, and `Object_Ctor` checks that global. Replacing `_aligned_malloc` with `Object_Allocate` caused heap corruption, so the correct render-node allocation path is still unresolved.
- `actor + 0x05` is checked by `ActorWorld_Register`, and `ActorVisual_SetInitFlag` (`0x00401FD0`) writes it to `1`. Live probes show player `= 0`, fresh bot `= 1`.
- `actor + 0x58` must stay valid after spawn. It is a required world/context pointer for render and update code.
- Detaching by nulling `actor + 0x58` is invalid and crashes on the next frame.
- Standalone puppets still need the full stock `PlayerActorTick` if they are expected to render a sprite. Loader hooks should scrub player-control state, not bypass the tick entirely.
- The bot must live in a real gameplay slot (`1..3`) at `gameplay + 0x1358 + slot * 4` for the arena render pipeline to process it. Slot `-1` is invisible; slot `0` collides with the local player path.
- `actor + 0x264` is not a stable "copy me from the local player" field. In the stock clone path it is consumed into the equip-runtime visual sink and then cleared on the source actor.
- `actor + 0x264` is not a stable readiness signal for gameplay donor actors. In live arena runs the local player can render correctly while the equip-runtime visual-link probes and `+0x264` both read back as `0`.
- The resolved render-state windows (`0x138..0x268`), descriptor blocks, visual-link objects, and source profiles are not the hard gate for arena sprite rendering. The local player can have these read back as null/zero and still render.
- `FUN_005E3080` can synthesize the weapon attachment and variant bytes, but it does not fill the descriptor block without live atlas context. Donor descriptor copy is still required for correct independent wizard visuals.

## Stock Wizard Clone Path

- `FUN_0061AA00` creates a standalone wizard puppet from an existing wizard actor only when `source_actor + 0x174 == 3`.
- The native sequence is:
  - allocate a fresh `0x398` actor and call `FUN_0052B4C0`
  - register it in the world with `ActorWorld_Register`
  - allocate standalone progression (`0x8E4`) and equip (`0x64`) runtimes and assign them to `actor + 0x300` / `actor + 0x304`
  - refresh runtime handles through `FUN_0052A370`
  - create two `0xA8` visual-link objects (`FUN_00461F70`, `FUN_00461ED0`)
  - copy the eight dwords from the source descriptor block (`source + 0x244 .. source + 0x260`) into each visual-link object at `+0x88 .. +0xA4`
  - attach those visual-link objects into the equip runtime sinks reached from `actor + 0x1FC` at nested offsets `+0x1C` and `+0x18`
  - map `source + 0x23F` to selection states `0x08,0x10,0x18,0x20,0x28,0xFFFFFFFE`
  - mark the selected progression entry active/visible and call `FUN_0065F9A0`
  - move the source actor's `+0x264` attachment object into the equip-runtime sink at nested offset `+0x30`
  - clear `source + 0x264`
  - call gameplay attach through the gameplay subobject at `gameplay + 0x1388`

## Wizard Visual Fix

- The current arena proof-of-life does not come from donor render-window copying. The hard gates recovered so far are:
  - a non-null render / scene attachment value at `actor + 0x04`
  - a real gameplay slot entry at `gameplay + 0x1358 + slot * 4`
  - stock `PlayerActorTick` running on the bot
- The current broken visual state is:
  - sharing the player's `+0x04` makes the bot visible but parents it to the player transform
  - the sprite lands in the black-robes / T-pose-like path because frame selection is still wrong
  - synthetic source profiles passed through `FUN_005E3080` can create the weapon attachment and set the variant bytes, but the descriptor block bytes stay empty without live atlas context
- Independent `wizard_id` sprite selection is still the follow-up task after the bot gets its own render node.

## Create Screen Wizard Selection Probe

- Live probe date: April 8, 2026 22:41 local time
- The create screen is reachable and its semantic actions still dispatch through `sd.ui.activate_action(..., "create")`, even when `sd.ui.get_snapshot()` reports no active `create` surface.
- During the live probe, all create element and discipline actions dispatched against a single owner object:
  - `create.select_element_earth` through `create.select_discipline_arcane` all resolved `owner=0x1417CA30`
  - this owner came from the engine's own semantic-dispatch log, not from `sd.ui.get_action_dispatch()`
- The raw create global at `0x008203F0` now looks like the live create-owner slot:
  - on probe start its first dword was `0x1417CA30`, matching the semantic dispatch owner exactly
  - on `create.select_discipline_body`, that first dword flipped from `0x1417CA30` to `0x00000000`
  - the adjacent bytes at `+0x04` and `+0x08` stayed stable in the same run (`0x008A9F04`, `0x008EC628`)
- The older candidate global at `0x0081F618` stayed zeroed throughout the same create-screen run and did not behave like the active owner object.
- The create-screen probe did not observe any changes on the gameplay local-player actor watchers:
  - `actor + 0x174`
  - `actor + 0x17C`
  - `actor + 0x23C .. +0x243`
  - `actor + 0x244 .. +0x263`
  - `actor + 0x264`
- In the current runtime surface, `sd.player.get_state()` and `sd.world.get_scene()` both stayed empty on the create screen, so the reliable live source of truth is:
  - engine semantic-dispatch logs for the create owner pointer
  - raw watch output on `0x008203F0`
- Working hypothesis:
  - wizard selection is mutating create-owner or preview-chain state, not the gameplay local-player actor exported by `0x0081D5BC`
  - the next native RE step should walk the object rooted at the first dword of `0x008203F0`, then follow its preview pointer and source-profile pointer into `FUN_00466FA0 -> FUN_005E3080`

## Current Validation

- Live validation on April 9, 2026 showed:
  - the standalone bot materialized again through the direct ctor path
  - the bot rendered as a visible wizard sprite in the arena
  - the bot kept collision, stayed in place, and pathfound back when pushed
  - the bot patrolled independently at a stable offset from the player under Lua `move_to`
  - the current visibility proof still depends on the shared `actor + 0x04` render context, so the bot remains parented to the player transform and the sprite stays in the black-robes / T-pose-like path

## Crash Investigation

- Crash dump: `SolomonDark.exe.17536.dmp`
- Timestamp: April 8, 2026 18:47 local time
- Fault:
  - exception address `0x005136DB`
  - `fld dword ptr [ecx]`
  - `ecx = 0x00008BDC`
- Stack:
  - `SolomonDark+0x36db`
  - `SolomonDark+0x224c1f`
  - `SolomonDark+0x28c20f`
  - `SolomonDark+0x28c4d6`
  - `SolomonDark+0x6fdaf`
- Root cause:
  - The loader briefly tested nulling `actor + 0x58` to break shared input ownership.
  - `FUN_00513090` immediately dereferences the world/context family behind `actor + 0x58`.
  - With owner/world cleared, the function walks invalid state and faults on the first post-spawn render/update frame.
- Fix:
  - preserve `actor + 0x58`
  - clear only slot identity mirrors
  - keep the stock `PlayerActorTick` running and isolate input through puppet drive state / control scrubbing instead of bypassing the tick

## Post-Crash Validation

- Staged live validation on April 8, 2026 18:52 local time passed:
  - bot creation log reached `created remote wizard entity`
  - patrol loop continued for over a minute afterward
  - no new crash dump was generated after the 18:47 dump
- The staged log shows the standalone actor surviving and patrolling under Lua `move_to` control only.
