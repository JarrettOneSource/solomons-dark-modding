# Bot Render RE Map

This note records the recovered Solomon Dark gameplay-slot wizard path now used by the loader for visible bot puppets.

## Current Late-April 12 Read
- High-confidence current state:
  - the bad extra-prop / wrong-sprite-composition bug is no longer the active problem
  - current remaining issue is robe/orb color correctness
  - correct slot progression ids alone are not enough to fix that color path
- Newly ruled-out branch:
  - in a stable water-bot run, the bot's source-profile cloth payload was already blue
  - actor-side selector windows also matched the stock player
  - zeroing the bot-local equip runtime pointers (`actor +0x304`, `actor +0x1FC`) did not remove the orange orb lane
  - so the remaining mismatch is not just “wrong wizard id” and not just “bot-local equip runtime exists”
- New direct lane comparison result:
  - stock player lane objects and bot lane objects can now be read directly from Lua
  - attachment lane:
    - player and bot both carry type `0x1B5C`
    - they do **not** share the same live object
    - their payload bytes differ early in the object head
  - holder-kind/type ordering:
    - stock player rails show `kind=1 -> type=0x1B5D`
    - stock player rails show `kind=2 -> type=0x1B5E`
    - the bot rails follow that same holder-kind/type ordering
    - our current `primary` / `secondary` names are therefore likely reversed relative to stock semantics
- Current investigation seam:
  - follow the stock player's robe/hat/staff/orb objects through gameplay-owned sink holders and asset/model accessors
  - do not start by watching raw `.bundle` memory pages
- New rich item-path finding:
  - `0x005E3080` is not the full stock orb/staff initialization path; it only creates a bare `0x1B5C` / `0x1B63` object and stores it at `actor +0x264`
  - the richer stock item builder path is `0x004645B0` / `0x004699B0`
  - `0x0046A360` proved `0x004699B0` is called as `cdecl` with one template-pointer argument
  - a direct bot experiment using `0x004699B0(source_attachment)` was reverted because it regressed the bot attachment lane / frame
  - the remaining unknown is the template record contract that feeds those richer builders during stock startup
- New late-pass attachment finding:
  - `TransferSourceActorAttachmentToTargetEquipVisualLane()` is not leaving a dangling pointer through source cleanup
  - source cleanup logs now show the transferred `0x1B5C` attachment item head is byte-identical before and after `DestroyWizardCloneSourceActor()`
  - that rules out temporary-source lifetime as the cause of the remaining orb mismatch
  - the active root cause is narrower:
    - the source-built `0x1B5C` created under `0x005E3080` is missing stock player-start state in the mid-object region
    - full `0x88` snapshot diff against the player item shows missing/nonzero clusters around `+0x34`, `+0x50`, `+0x58`, `+0x6A..+0x73`, and `+0x7E..+0x85`
    - robe/hat helper items already carry valid element-sensitive float4 blocks at `+0x88..+0xA4`
    - so the remaining bug is attachment-item construction/finalization, not helper-item color seeding
 - New player-vs-bot same-element result:
 - controlled manual Air / Fire / Earth player runs showed the stock player helper float4s change per element, but same-element bots still do not match them
  - the synthetic source-profile palette in `GetWizardElementColor()` was originally approximate and measurably wrong for Fire/Water/Earth/Air
  - the source-profile path expects the **pre-transform** cloth color, while the measured stock player helper values are **post-transform**
  - the stock helper transform is `helper = 0.2 * source + 0.8 * grayscale(source)` with grayscale weights `0.3086 / 0.6094 / 0.0820`
  - after replacing `GetWizardElementColor()` with reconstructed pre-transform source values, a fresh Earth bot run produced helper float4s that matched the measured stock Earth helper colors exactly
  - that fixes the helper-color side of the remaining visual mismatch
 - New stock-clone result:
  - a diagnostic call to `WizardCloneFromSourceActor` immediately after source descriptor build produced a clone attachment item that matched the source-built `0x1B5C`
  - that means `0x0061AA00` is not the place where the stock player-start path adds the missing `0x1B5C` mid-object state
  - the richer player-start item-build path remains the only strong candidate for the missing attachment contract
 - New attachment-lane regression finding:
  - the temporary `stock_clone_diagnostic` call was mutating the source actor by transferring `source +0x264` into the diagnostic clone before the gameplay-slot bot path reused it
  - removing that diagnostic restored the gameplay-slot bot attachment lane immediately in fresh runs
  - fresh attach logs now show `EquipAttachmentSink_Attach` on the gameplay-slot bot's attachment holder storing the `0x1B5C` object successfully, and the final `slot_actor_attachment_seeded` summary keeps that object live
- New tooling available for this pass:
  - `sd.debug.dump_ptr_chain` / `resolve_ptr_chain`
  - `sd.debug.get_trace_hits` / `get_write_hits`
  - `sd.debug.dump_struct`
  - `sd.debug.dump_vtable`
  - see `docs/lua-memory-tooling.md`

## April 12 Attachment Finding
- Final gameplay-slot result:
  - the gameplay-slot bot actor is correctly isolated from the slot-table progression wrapper and can be seeded with the stock water actor-side render window
  - the source-built descriptor block at `actor +0x244..+0x263` is **not** safe to keep live on gameplay-slot bots
  - improved crash logs showed the failing path as `__CxxThrowException -> operator_new -> FUN_0043A6B0 -> FUN_0053B680 -> ActorAnimation_Advance`
  - `FUN_0053B680` is entered from `ActorAnimation_Advance` when `actor +0x248 != 0` and it reuses `actor +0x244` as a count/capacity input, so leaving transformed color payload bytes there produces `std::bad_alloc`
  - the final fix is: use the built descriptor to seed robe/hat helper lanes and selector bytes, then clear the descriptor block back off the bot actor before stock animation/update uses it
- Final attachment conclusion:
  - gameplay-slot bots do **not** need a live standalone `0x1B5C` attachment item for the visible orb/staff presentation in this path
  - live probing showed the visible orb/staff remained after clearing both `actor +0x264` and the equip attachment sink object
  - the final gameplay-slot path therefore removed the live attachment-item construction experiment instead of trying to repair its runtime contract

## Gameplay-Owned Sink Chain
- The live player visuals are not just actor-local fields.
- Current recovered ownership chain:
  - gameplay object owns sink-holder wrappers at:
    - `gameplay +0x1428`
    - `gameplay +0x142C`
    - `gameplay +0x1440`
  - each holder points to a sink object
  - sink object `+0x04` points at the current attached runtime item/object
- This chain is now one of the main comparison seams for the remaining color issue.

## Loader Path

- The loader now materializes the visible bot through the gameplay-slot path, not the older direct standalone ctor path.
- The live gameplay-slot pipeline is:
  - call `Gameplay_CreatePlayerSlot(slot)` so the gameplay slot tables and stock slot actor exist
  - replace the slot actor's shared progression contamination with an actor-owned progression wrapper/runtime
  - seed the actor's wizard appearance/runtime selection state from `wizard_id`
  - create a temporary stock source actor only to compile the canonical wizard render window
  - attach robe/hat helper lanes from the built descriptor
  - mirror the selector bytes from the source actor onto the gameplay-slot bot actor
  - immediately clear the actor-local descriptor block back to zero
  - register the slot actor through `ActorWorld_RegisterGameplaySlotActor`
  - allow stock `PlayerActorTick`, `PlayerActor_SlotOverlayCallback`, and `ActorAnimation_Advance` to run while clearing the transient descriptor block before/after those passes
- Historical note:
  - older sections below that talk about direct standalone actor creation and live staff attachment are useful RE history, but they are no longer the active gameplay-slot bot implementation
- The April 10, 2026 residual fix changed the standalone actor path from raw `_aligned_malloc` ownership to the same `Object_Allocate` / scalar-deleting-destructor contract used by stock actor creation. Runtime validation of a truly independent `+0x04` render transition is still pending, but the older donor-fallback note is stale in the current source tree.
- Fresh April 11 RE on `ActorWorld_Register` / `ActorWorld_Unregister` tightened the remaining bug:
  - the generic register path already inserts the actor into `Region +0x310`, `Region +0x360`, and `Region +0x500`
  - it keys `Region +0x500` by `(actor_group, resolved_world_slot)` and writes that exact pair into `actor +0x5C/+0x5E`
  - the loader then rewrites `actor +0x5C` to the gameplay slot later, without rerunning stock registration through the slot-owned path
  - the stock slot-owned path instead uses `ActorWorld_RegisterGameplaySlotActor` so the Region bucket identity, slot-active byte, and gameplay slot all agree on the same pair

## Current Code Audit (2026-04-11)

Historical note:
- this section captures the intermediate hybrid path that led to the final gameplay-slot cutover
- where it conflicts with the April 12 attachment finding / loader path sections above, treat it as investigation history rather than the active design

- The current loader still calls `FUN_005E3080` through a guarded wrapper while synthetic or donor source-profile staging is live.
- The current loader no longer calls the old standalone `ApplyWizardElementAppearanceToDescriptor()` helper. Fresh April 11 decompile proved the stock slot-0 appearance path is not a grouped `ApplyChoice x4` contract.
- The current loader also no longer calls player vtable slot `+0x18` during standalone priming. That helper is only `ActorVisual_SetInitFlag` and prematurely setting `actor +0x05 = 1` was blocking the stock slot-register attach init.
- The loader clears `actor +0x174/+0x178` again after that staging step, so synthetic source state is intentionally temporary.
- Keeping the actor-side descriptor block at `+0x244..+0x263` live regressed the bot back to a one-wizard frame. The current code therefore clears that bundle before helper creation, again after gameplay attach, and again during standalone bot tick repair.
- That means the current code path is still a hybrid: it uses source-profile descriptor building as a setup step, but intentionally does not leave that state live across gameplay/tick.
- The remaining April 11 duplication bug was also hybrid: the bot's standalone equip attachment lane was correct, but the loader contaminated the actor-side body sprite selector lane by copying donor `+0x23C/+0x23D/+0x23F/+0x240` into the synthetic source profile before `FUN_005E3080`.
- The current code now keeps those selector bytes wizard-owned. Live validation shows the bot at `variants=0/0/0/0` while the equip attachment sink remains populated.
- April 11 teardown analysis corrected an older assumption about the stock slot-actor sweep:
  - the stack-local object at vtable `0x007846CC` is a generic growable pointer list, not an actor-dispatch shim
  - `GameplayHud_RenderDispatch` (`0x00512060`) case `100` collects gameplay-slot actors into that temporary list through `0x402720 -> 0x4013C0 -> 0x4013E0`
  - after collection, the same case iterates the list and calls each actor's vtable slots `+0x28` and `+0x1C`
  - actor vtable slot `+0x28` is now named `PlayerActor_SlotOverlayCallback` (`0x00528AD0`)
  - `PlayerActor_SlotOverlayCallback` does not contain a direct delete call in the recovered decompile, so the active delete/crash investigation has shifted into deeper nested stock helpers
  - `PointerList_DeleteBatch` (`0x004024C0`) is now named as the shared list deleter reached by the embedded `PuppetManager` core
  - the first direct hook on `PointerList_DeleteBatch` crashed immediately because the loader patched 6 bytes and split the prologue instruction at `0x004024C5`; the safe whole-instruction prologue boundary is 5 bytes
  - the earlier `Region_DeleteActor` name was too specific: `0x00641070` is actually `PuppetManager_DeletePuppet`, the embedded `PuppetManager` vtable slot `+0x28` callback
  - `Region_Ctor` (`0x00652830`) installs that `PuppetManager` subobject at `Region + 0x310` and points manager `+0x4C` back at the owning Region
  - `ManagedPointerList_SweepParityLane` (`0x004022A0`) is the generic parity-lane sweep helper used under that manager and keyed off `g_pGameWorldState + 0x28`
  - `ManagedPointerList_RemoveFromAllLanes` (`0x00402450`) removes one tracked pointer from the owner's main list and both side lanes
  - stock persistent gameplay-slot actors do not use only `ActorWorld_Register`; they are rebound through `ActorWorld_RegisterGameplaySlotActor` (`0x00641090`), `ActorWorld_UnregisterGameplaySlotActor` (`0x00641130`), and `WorldCellGrid_RebindActor` (`0x005217B0`)
  - the current live teardown problem is therefore a Region/PuppetManager ownership failure caused by a slot-registration contract mismatch, not a direct call from the HUD overlay loop into a Region method

## Recovered Standalone Spawn Sequence

Historical branch:
- this section documents the older direct standalone/world-actor path for RE continuity
- it is no longer the active gameplay-slot bot implementation

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
- `Object_Allocate` (`0x00402030`): allocator that calls `operator_new` and stores the result in `DAT_00B4019C`. Both recovered stock actor creation paths use it for player actors.
- `Puppet_Ctor` (`0x006287D0`): puppet-layer constructor in the player actor chain.
- `GoodGuy_Ctor` (`0x0052A410`): ally/good-guy constructor in the player actor chain.
- `Player_Ctor` (`0x0052A500`): player-layer constructor in the player actor chain.
- `FUN_0052B4C0` (`0x0052B4C0`): player actor ctor used for standalone wizard materialization.
- `ActorVisual_SetInitFlag` (`0x00401FD0`): tiny vtable helper that writes `*(uint8_t *)(actor + 0x05) = 1`.
- Loader-side note: this helper is not a visual refresh. The standalone bot path should leave `actor +0x05` clear until `ActorWorld_RegisterGameplaySlotActor` is ready to run the actor's `+0x44` attach init.
- `FUN_00513090` (`0x00513090`): render/update path that requires a valid world/context pointer at `actor + 0x58`.
- `FUN_0061AA00` (`0x0061AA00`): stock wizard-puppet factory used by the game to clone a renderable wizard actor from an existing wizard source.
- `Region_Ctor` (`0x00652830`): Region constructor. Installs the embedded `PuppetManager` at `Region + 0x310`, seeds its owner pointer, and initializes nearby helper subobjects.
- `PlayerActorDtor` (`0x0052D340`): player actor destructor at vtable slot `0`.
- `PlayerActorTick` (`0x00548B00`): stock player tick. This must run on the bot for visible sprite rendering.
- `PlayerActorMoveStep` (`0x00525800`): stock movement step helper used as reference for puppet movement support.
- `ActorWorld_Register` (`0x0063F6D0`): inserts the actor into the live world bucket table.
- `ActorWorld_Unregister` (`0x0063F600`): detaches an actor from the world bucket table, clears `actor +0x58` when owned by that world, and clears any gameplay-slot actor whose registered mirrors `+0x164/+0x166` still match the removed actor's slot pair.
- More precise April 11 detail for the pair above:
  - `ActorWorld_Register` writes `actor +0x5C = actor_group` and `actor +0x5E = resolved_world_slot`, stores the actor at `Region +0x500 + (actor_group * 0x800 + resolved_world_slot) * 4`, and inserts it into the Region-side participant manager at `+0x310`
  - `ActorWorld_Unregister` removes from those same Region-side containers using the actor's *current* `+0x5C/+0x5E` pair
  - this is why the loader's post-register rewrite of `actor +0x5C` is now considered a primary ownership bug candidate
- `PuppetManager_DeletePuppet` (`0x00641070`): embedded `PuppetManager` vtable slot `+0x28`. Deletes tracked puppets by calling `ActorWorld_Unregister(actor, 0)` and then the shared object delete helper.
- `ManagedPointerList_SweepParityLane` (`0x004022A0`): shared parity sweep helper used by manager-owned pointer lists. Chooses one of two side lanes from `g_pGameWorldState + 0x28`, flushes the active lane through vtable slot `+0x2C`, then either retires or requeues each main-list item based on bytes `+0x04/+0x05`.
- `ManagedPointerList_RemoveFromAllLanes` (`0x00402450`): companion removal helper that drops one tracked pointer from the owner's main list and both embedded side lanes.
- `ActorWorld_RegisterGameplaySlotActor` (`0x00641090`): stock persistent-slot world registration helper. Inserts `g_pGameplayScene->slot_actor_table[slot]` into the Region-owned participant manager, mirrors it into `Region +0x500 + slot*0x2000`, repairs owner/slot fields, and finishes with `WorldCellGrid_RebindActor(Region +0x378, actor)`.
- `ActorWorld_UnregisterGameplaySlotActor` (`0x00641130`): stock persistent-slot unregister helper. Clears `Region +0x7C + slot` and calls `ActorWorld_Unregister(slot_actor, 1)` when the gameplay scene is live.
- `WorldCellGrid_RebindActor` (`0x005217B0`): world-cell binder called by stock slot registration. Computes the actor's grid cell from `actor +0x18/+0x1C`, removes the actor from the old cell at `actor +0x54`, and inserts it into the new cell.
- `Actor_CopyRegisteredSlotMirrorsFromSourceActor` (`0x005289E0`): copies `source +0x5C/+0x5E` into `actor +0x164/+0x166`; passing null clears both mirrors to `-1`.
- `PlayerActor_EnsureProgressionHandleFromGameplaySlot` (`0x0052B900`): ensures `actor +0x300` points at a live progression wrapper, borrowing `gameplay +0x1654 + slot*4` when the actor-side wrapper is null or empty.
- `GameplayHud_RenderDispatch` (`0x00512060`): switch-based gameplay HUD renderer. Case `100` performs the stock gameplay-slot overlay sweep and calls actor vtable slots `+0x28` then `+0x1C`.
- `PlayerActor_SlotOverlayCallback` (`0x00528AD0`): player-actor vtable slot `+0x28` used by the slot overlay sweep. Draws actor-relative overlay sprites and writes `actor +0x1F4/+0x1F8` in the long-move branch.
- `PointerList_DeleteBatch` (`0x004024C0`): shared pointer-list batch deleter. Iterates `list +0x14` for `count = list +0x08`, dispatches `this->vtable[+0x28]` for each entry, then clears or frees the list storage depending on `list +0x11`.
- `ActorSensor_GatherProximityHits` (`0x0057F0E0`): deeper stock proximity/sense helper reached through `0x00624B40`; scans nearby records and accumulates weighted hits into a caller-owned output list.
- `PuppetManager_Vtable` (`0x0079F044`): embedded manager vtable installed by `Region_Ctor` at `Region + 0x310`.

## Player Actor Vtable Dump

- Base address: `0x00793F74`
- Dumped from the analyzed `SolomonDark.exe` image on April 9, 2026.

```text
[00] +0x00  0x0052D340  PlayerActorDtor
[01] +0x04  0x0052B900  PlayerActor_EnsureProgressionHandleFromGameplaySlot
[02] +0x08  0x00548B00  PlayerActorTick
[03] +0x0C  0x00528A60  FUN_00528A60
[04] +0x10  0x0042E260  FUN_0042E260
[05] +0x14  0x00529C90  FUN_00529C90
[06] +0x18  0x00401FD0  ActorVisual_SetInitFlag
[07] +0x1C  0x0054BA80  ActorAnimationAdvance
[08] +0x20  0x005468C0  FUN_005468C0
[09] +0x24  0x0052C2A0  FUN_0052C2A0
[10] +0x28  0x00528AD0  PlayerActor_SlotOverlayCallback
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

- Object-header word / ctor sentinel lane: `actor + 0x04`
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
- Packed discrete frame offset/countdown field: `actor + 0x22C`
- Render descriptor block: `actor + 0x244`
- Actor-side visual attachment field: `actor + 0x264`
- Progression wrapper pointer: `actor + 0x300`
- Equip wrapper pointer: `actor + 0x304`
- Registered slot mirrors: `actor + 0x164`, `actor + 0x166`

## Wizard Source Profile Layout

- `FUN_00466FA0` (`0x00466FA0`) is the preview / selector-side bridge into the live wizard render path.
- That function allocates a type `0x1397` object through `FUN_005B7080`, then seeds:
  - `actor + 0x174 = *(int *)(source + 0x4C)`
  - `actor + 0x178 = source`
  - `actor + 0x17C = source + 0x50`
  - `FUN_005E3080(actor)` immediately after
- `FUN_005E3080` (`0x005E3080`) expects `*(int *)(source + 0x4C) == 3` for wizard visuals.
- Source-profile selector fields consumed by `FUN_005E3080`:
  - `source + 0x9C`: `Hat Type`
  - `source + 0x9D`: `Robe Type`
  - `source + 0xA0`: render-helper / pose selector
  - `source + 0xA4`: weapon type (`1 = staff`, `2 = wand`)
  - `source + 0xA8`: tertiary visual variant
- Source-profile color payload consumed by `FUN_005E3080`:
  - `source + 0xB4 .. +0xC0`: cloth color `float4`
  - `source + 0xC4 .. +0xD0`: trim color `float4`
  - `source + 0xC0` and `source + 0xD0` are the final float lanes of those blocks and are tested as floats before descriptor generation
- `FUN_005E3080` copies both 16-byte color blocks to stack and passes them through `FUN_0040FC60(..., DAT_00785368)`, then writes the results into `actor + 0x244 .. +0x260`.
- If cloth alpha `source + 0xC0` or trim alpha `source + 0xD0` is `0.0`, `FUN_005E3080` replaces that 16-byte block with the default returned by `FUN_004630E0`.
- The actor-side selector bytes populated by `FUN_005E3080` are:
  - `actor + 0x23C`: hat type
  - `actor + 0x23D`: robe type
  - `actor + 0x23E`: weapon type
  - `actor + 0x23F`: render-helper / pose selector
  - `actor + 0x240`: tertiary variant
- Loader-specific caveat:
  - `CreateSyntheticWizardSourceProfile(wizard_id)` already seeds wizard-correct selector bytes
  - the old duplication bug came from `PrimeStandaloneWizardBotActor` overwriting those selector bytes with donor actor values before calling `FUN_005E3080`
  - the current code no longer does that, so the actor-side base sprite selector lane stays wizard-correct

## Wizard Render Dispatch

- `FUN_00622430` (`0x00622430`) is the render dispatch that checks `actor + 0x174`.
- When `actor + 0x174 == 3`, it calls `FUN_00621780` (`0x00621780`) for the wizard sprite path.
- `FUN_00621780` reads the actor-side selectors above plus the descriptor block at `actor + 0x244 .. +0x260`.
- `actor + 0x23C` and `actor + 0x23D` are the discrete atlas selectors for hat / robe type.
- `actor + 0x23F` is not the main robe-color selector; it switches among the render helpers reached through `FUN_005E9FC0`.
- `FUN_00621780` specifically branches on `actor +0x23E`; when that byte is `0`, it falls back to `actor +0x240` and chooses alternate body sprite rows from that tertiary variant.
- In other words, `+0x240` is a structural body/accessory selector, not just a cosmetic tint flag.

## Actor-Side Setup Writer

- `FUN_00462790` is a stock setup writer that copies source-profile fields into actor-side render state for several source kinds.
- Relevant recovered writes:
  - `actor +0x240 = source +0x97` for source kinds `0x3E9`, `0x3EA`, and `0x3EB`
  - `actor +0x264` bitfield assembly for source kind `0x3F0`
  - `actor +0x23C = source +0x8C` and `actor +0x244 = source +0x94` for source kind `0x3F2`
- This matters because it confirms the body/accessory selector lane is populated from source-profile state before the live wizard render path ever samples it.

## Slot-0 Appearance Pipeline Correction

- `FUN_005D0290` is still the slot-0 "apply selected wizard" stage, but the earlier grouped-helper model was wrong.
- Fresh April 11 decompile shows the actual contract:
  - map the selected wizard element to three primary choice ids plus one secondary id
  - call `FUN_00660320(choice_id, 0)` for the three primary ids
  - write those ids into the slot-0 progression/runtime object at `+0x82C/+0x86C/+0x870`
  - resolve the secondary id and call `FUN_00660320(choice_id, 1)`
  - update `g_pGameplayIndexStateTable + 0x30`
  - call `FUN_0065F9A0`
  - write the secondary id into `+0x830`
- `FUN_00660320` itself is therefore a per-choice processor with an `ensure_assets` flag, not a `group = 0..3` dispatcher.

## Arena vs. Hub Visual State

- Arena rendering does not require the hub visual-link path to be populated.
- In live arena probes, the local player still renders with these fields unset:
  - `actor + 0x178` (source profile)
  - `actor + 0x1FC` (equip runtime)
  - `actor + 0x200` (progression runtime)
  - `actor + 0x21C` (anim state pointer)
  - `actor + 0x22C` (packed discrete frame state, not a pointer)
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

- `Object_Ctor` seeds `actor + 0x04` with a ctor/header sentinel pattern.
- Current April 11 teardown work no longer treats `actor +0x04` as a proven transferable render-node pointer. The live bot still shows sentinel-like values there during the failing teardown run, so the older “copy player +0x04 to make the bot visible” theory is now considered stale.
- `Object_Allocate` writes its allocation to `DAT_00B4019C`, and `Object_Ctor` checks that global. The earlier heap-corruption probe was most likely mixing stock allocation with raw-allocation cleanup.
- `actor + 0x05` is checked by `ActorWorld_Register`, and `ActorVisual_SetInitFlag` (`0x00401FD0`) writes it to `1`. Live probes show player `= 0`, fresh bot `= 1`.
- `actor + 0x58` must stay valid after spawn. It is a required world/context pointer for render and update code.
- Detaching by nulling `actor + 0x58` is invalid and crashes on the next frame.
- Standalone puppets still need the full stock `PlayerActorTick` if they are expected to render a sprite. Loader hooks should scrub player-control state, not bypass the tick entirely.
- The bot must live in a real gameplay slot (`1..3`) at `gameplay + 0x1358 + slot * 4` for the arena render pipeline to process it. Slot `-1` is invisible; slot `0` collides with the local player path.
- `actor + 0x264` is not a stable "copy me from the local player" field. In the stock clone path it is consumed into the equip-runtime visual sink and then cleared on the source actor.
- `actor + 0x264` is not a stable readiness signal for gameplay donor actors. In live arena runs the local player can render correctly while the equip-runtime visual-link probes and `+0x264` both read back as `0`.
- The April 10, 2026 bot fix stops donor-clobbering bot-owned animation state. Standalone bots now keep their own `+0x21C` selection state and their own `+0x220..+0x263` frame/motion state after runtime wiring.
- The resolved render-state windows (`0x138..0x268`), descriptor blocks, visual-link objects, and source profiles are not the hard gate for arena sprite rendering. The local player can have these read back as null/zero and still render.
- `FUN_005E3080` does fill the descriptor block from the external source-profile color payload at `source + 0xB4 .. +0xD0`.
- A synthetic source profile that sets only `source + 0xC0` / `source + 0xD0` to `1.0f` while leaving the RGB lanes at zero produces cloth / trim color vectors `[0, 0, 0, 1]`, which yields black robes.
- Current loader caveat: even after `FUN_005E3080` fills the actor-side descriptor block, `ClearActorLiveDescriptorBlock` zeros `+0x244..+0x263` again during priming, attach, and tick repair. If the recovered body-render path is right, this is still a likely source of wrong or unstable body visuals.

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
- The April 10, 2026 animation fix is:
  - do not donor-copy `+0x220..+0x263` after `WireStandaloneWizardRuntimeHandles` has created the bot's own selection/progression state
  - do not overwrite the bot's `+0x21C` value with the donor's resolved animation state during spawn or per-tick repair
  - transfer the stock-built attachment from actor `+0x264` into equip sink `+0x30`
- The remaining non-stock rendering issues visible in code are:
  - the shared `actor + 0x04` render-context fallback is still present when standalone initialization does not produce a live node on its own
  - the actor-side descriptor block is still cleared after setup, attach, and tick repair, even though the recovered body-render path says it consumes `+0x244..+0x263`

## Confirmed April 11 Duplication Root Cause

- Symptom:
  - the orange standalone bot renders the correct orb/staff
  - but also shows an extra right-side staff and left-side scroll bundle
- Confirmed visual ownership split:
  - the correct orb/staff is the standalone attachment moved from actor `+0x264` into equip sink `+0x30`
  - the extra props are actor-side body sprite art selected by `+0x23E/+0x240`
- Live proof:
  - baseline bot was `variants=0/0/0/1`
  - writing only `bot +0x240 = 0` removed the extra side staff / scroll bundle while the orb/staff remained visible
  - restoring only `bot +0x240 = 1` brought the extra props back
- Root cause:
  - the old loader path copied donor selector bytes into the synthetic source profile before `FUN_005E3080`
  - that contaminated the bot's actor-side body sprite lane with the local player's structural accessory variant
  - the bot therefore renders both:
    - player-style body/accessory art from the actor-side lane
    - standalone orb/staff art from the equip attachment lane
- This is the clean root-level issue to fix before custom-art work. The problem is not the attachment sink itself; it is the actor-side selector contamination that makes the body renderer draw accessory-bearing base art in parallel with the attachment-owned staff.
- The current code now applies that root-level fix by keeping the synthetic selector bytes wizard-owned.

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

- Live validation on April 9, 2026 showed the pre-fix behavior:
  - the standalone bot materialized again through the direct ctor path
  - the bot rendered as a visible wizard sprite in the arena
  - the bot kept collision, stayed in place, and pathfound back when pushed
  - the bot patrolled independently at a stable offset from the player under Lua `move_to`
  - the current visibility proof still depends on the shared `actor + 0x04` render context, so the bot remains parented to the player transform and the sprite stays in the black-robes / T-pose-like path
- The April 10, 2026 residual fix changes the allocator/cleanup contract and removes the explicit `+0x04` alias write. That new path has not been runtime-validated yet.

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
