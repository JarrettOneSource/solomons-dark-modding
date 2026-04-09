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
  - rebuild the actor-side visual state through the actor vtable slot at `+0x18`
  - build the visual-link objects from the bot actor's own descriptor block, not from the local player's render window
  - call `ActorWorld_Register(world, actor)` at `0x0063F6D0`
  - attach the actor to gameplay/world state without inserting it into the gameplay slot table
  - clear slot identity mirrors only: `actor + 0x5C`, `actor + 0x164`, `actor + 0x166`
- The loader does not call `Gameplay_CreatePlayerSlot` and does not populate `gameplay + 0x1358`.

## Recovered Standalone Spawn Sequence

- Standalone actor allocation size: `0x398`
- Player ctor: `FUN_0052B4C0` (`0x0052B4C0`)
- World register: `ActorWorld_Register` (`0x0063F6D0`)
- World unregister: `ActorWorld_Unregister` (`0x0063F600`)
- Standalone puppets remain world actors only. They are not allied slot actors and do not rely on the built-in ally roster.

## Verified Functions

- `FUN_0052B4C0` (`0x0052B4C0`): player actor ctor used for standalone wizard materialization.
- `FUN_00513090` (`0x00513090`): render/update path that requires a valid world/context pointer at `actor + 0x58`.
- `FUN_0061AA00` (`0x0061AA00`): stock wizard-puppet factory used by the game to clone a renderable wizard actor from an existing wizard source.
- `PlayerActorTick` (`0x00548B00`): stock player tick. Unsafe for standalone puppets because it pulls in player-slot/input behavior.
- `PlayerActorMoveStep` (`0x00525800`): stock movement step helper used as reference for puppet movement support.
- `ActorWorld_Register` (`0x0063F6D0`): inserts the actor into the live world bucket table.
- `ActorWorld_Unregister` (`0x0063F600`): used during loader-owned bot cleanup.

## Verified Gameplay Offsets

- Gameplay player table: `gameplay + 0x1358 + slot * 4`
- Gameplay progression wrapper table: `gameplay + 0x1654 + slot * 4`
- These tables must remain untouched for standalone puppets.

## Verified Actor Offsets

- World/context pointer: `actor + 0x58`
- Gameplay slot byte: `actor + 0x5C`
- World bucket slot short: `actor + 0x5E`
- Position: `actor + 0x18`, `actor + 0x1C`
- Heading: `actor + 0x6C`
- Animation drive byte: `actor + 0x160`
- Animation state pointer: `actor + 0x21C`
- Render descriptor block: `actor + 0x244`
- Actor-side visual attachment field: `actor + 0x264`
- Progression runtime pointer: `actor + 0x200`
- Equip runtime pointer: `actor + 0x1FC`
- Progression wrapper pointer: `actor + 0x300`
- Equip wrapper pointer: `actor + 0x304`
- Registered slot mirrors: `actor + 0x164`, `actor + 0x166`

## Critical Invariants

- `actor + 0x58` must stay valid after spawn. It is a required world/context pointer for render and update code.
- `actor + 0x5C`, `actor + 0x164`, and `actor + 0x166` can be cleared for standalone puppets.
- Detaching by nulling `actor + 0x58` is invalid and crashes on the next frame.
- Standalone puppets should not run the full stock `PlayerActorTick`. The safe path is:
  - keep the world/context pointer
  - bypass the stock player tick for standalone bots
  - drive animation/movement from loader-owned puppet state only
- `actor + 0x264` is not a stable "copy me from the local player" field. In the stock clone path it is consumed into the equip-runtime visual sink and then cleared on the source actor.
- `actor + 0x264` is not a stable readiness signal for gameplay donor actors. In live arena runs the local player can render correctly while the equip-runtime visual-link probes and `+0x264` both read back as `0`.
- The current temporary fix is to copy the donor actor's resolved render-state windows directly into the standalone bot before finalization:
  - `actor + 0x138 .. +0x163`
  - `actor + 0x174 .. +0x1FB`
  - `actor + 0x21C .. +0x263`
- This mirrors the local player's final 2D sprite-selection state even when the live donor visual-link objects are not readable from gameplay.

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

- The black-robe/no-staff bug came from leaving the standalone actor with only its partially seeded descriptor state. The bot registered and animated, but its resolved 2D sprite-selection bytes did not match the live player actor, so the robe/staff atlases fell back to the dark silhouette path.
- The current working loader fix is:
  - keep the standalone progression/equip runtime path and world-only spawn path
  - copy the donor actor's resolved render-state windows into the standalone bot after runtime-handle setup
  - keep the donor descriptor block and render-variant bytes in sync with the donor actor
  - finalize the standalone actor through the normal gameplay attach path so its own equip runtime sinks and attachment state are rebuilt
- This is a temporary visual workaround. It makes the standalone bot render like the local player. Independent `wizard_id` sprite selection is still a follow-up task.

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

## Validation

- Live validation on April 8, 2026 21:28 local time showed:
  - the standalone bot materialized again through the direct ctor path
  - the bot's render selector and variant bytes matched the player exactly: `render=0 variants=0/0/0/1`
  - the bot's descriptor hash matched the player exactly: `0x54DA173A`
  - the bot patrolled independently at a stable offset from the player under Lua `move_to`
  - the gameplay capture `runtime/window_capture_bot_visual_separated.png` showed a properly rendered wizard sprite instead of the earlier black silhouette path

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
  - skip the stock player tick for standalone puppets and advance animation from the loader hook

## Validation

- Staged live validation on April 8, 2026 18:52 local time passed:
  - bot creation log reached `created remote wizard entity`
  - patrol loop continued for over a minute afterward
  - no new crash dump was generated after the 18:47 dump
- The staged log shows the standalone actor surviving and patrolling under Lua `move_to` control only.
