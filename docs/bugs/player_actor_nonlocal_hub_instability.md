# Player-Actor Nonlocal Hub Instability

Date: 2026-04-17

## Summary

The current Solomon Dark client does not tolerate the loader materializing an
extra player-type participant in hub scenes through the currently tested rails.

Confirmed failing rails:

1. Gameplay-slot surrogate path
   - `Gameplay_CreatePlayerSlot(slot > 0)`
   - optional post-create priming
   - `ActorWorld_RegisterGameplaySlotActor`
   - gameplay attach
2. Gameplay-slot table-only path
   - `Gameplay_CreatePlayerSlot(slot > 0)`
   - actor kept in `slot_actor_table[1]`
   - no Region/world publication
3. Stock clone path
   - synthetic wizard source actor
   - `WizardCloneFromSourceActor (0x0061AA00)`
   - generic world publication through `ActorWorld_Register`

All three eventually reach the stock `PlayerActor_MoveStep` fault chain:

- `SolomonDark.exe + 0x001225E0`
- `SolomonDark.exe + 0x001228CC`
- `SolomonDark.exe + 0x00122D10`

Those failures are not explained by the loader's rejected visual bootstrap
experiments anymore. The minimal gameplay-slot rail still fails after all source
actor, helper-lane, and attachment experiments are removed.

## Decisive Findings

### 1. Slot-table membership itself is toxic in hub scenes

The decisive branch kept the created slot actor out of Region/world publication
and then also cleared:

- `gameplay + 0x1358 + slot * 4`
- `gameplay + 0x1654 + slot * 4`

Result:

- when the actor stayed in the gameplay slot tables, the hub still eventually
  hit the stock move-step crash
- when the actor was removed from those tables, that specific slot-reader
  exposure was gone

This proves the hub client has stock readers that do not safely tolerate the
extra player slot actor path we are synthesizing.

Relevant stock readers already recovered:

- `GameplayHud_RenderDispatch (0x00512060)` case `100`
- `GameNpc_UpdateMoveGoalAndFollow (0x006042C0)`
- `GameNpc_SetTrackedSlotAssist (0x005EA450)`
- `Badguy_ClearTargetAndNotifySlots (0x00484B30)`

### 2. Pure slot publication is not enough

Even with the visual/bootstrap rails removed, the minimal gameplay-slot actor
still eventually trips the same stock movement/collision crash. The crash
summary on the minimal branch shows:

- `equip = 0`
- `source = 0`
- `attach = 0`

So the remaining failure is not caused by the rejected helper/staff
experiments.

### 3. Stock clone path also fails in hub

The loader can successfully drive:

- `CreateWizardCloneSourceActor(...)`
- `WizardCloneFromSourceActor (0x0061AA00)`

and produce a visible non-slot clone in hub, but that branch still eventually
faults in the same stock move-step chain while idling in hub.

So:

- gameplay-slot path is not enough
- stock clone path is also not enough

The likely conclusion is that the true stock-safe nonlocal participant rail in
hub is neither of those currently tested player-type paths.

### 4. Shipped `multiplayer` symbols are remote command handlers, not a remote-player spawn rail

The recovered `multiplayer` band around `0x006822E0` is real, but its current
scope is narrower than “spawn another player in hub”:

- `FUN_00463020` dispatches command ids `0x3F1..0x3F5`
- `0x006822E0` -> `Remote_KillTrigger`
- `0x00682340` -> `Remote_DisableTrigger`
- `0x006823A0` -> `Remote_EnableTrigger`

Those functions operate on trigger/runtime records and do not construct or
publish a second `PlayerActor`.

### 5. No separate stock remote `PlayerActor` creation rail is visible in the shipped build

`PlayerActorCtor (0x0052B4C0)` xrefs currently resolve to only four places:

- `Gameplay_CreatePlayerSlot (0x005CB870)`
- `WizardCloneFromSourceActor (0x0061AA00)`
- `GameObjectFactory_Create (0x005B7080)` general factory path
- one unrelated UI-heavy constructor path at `0x005A13A0`

The create-wizard remote-state path and the gameplay multiplayer-flag path do
not reveal another stock “spawn extra player wizard into the hub world” helper.

The stronger April 17 reduction is on the shared player ctor layer itself:

- direct refs to `Player_Ctor (0x0052A500)` currently resolve to only:
  - `PlayerWizard (0x0052B4C0)`
  - `PlayerTarget (0x0052C790)`
- `PlayerTarget` is factory type `2`, size `0x224`, with vtable `0x00793E44`
- its ctor writes:
  - object type `2` at `+0x08`
  - class/group id `0x801` at `+0x14`
  - selector fields `+0x220 = 0xFF`, `+0x222 = 0xFFFF`
- its main virtual at vtable slot `+0x08` (`0x0052C860`) resolves another
  actor from the owning Region bucket table using `self +0x220/+0x222`,
  mirrors that actor's `x/y`, and then drives motion through the owning Region
  grid/collider path at `owner_region + 0x378`
- `PlayerDescriptor_SpawnType2 (0x005E3050)` publishes it with the generic
  register rail:
  - `ActorWorld_Register(world=source + 0x58, actor_group=0, actor=target, slot_index=-1, use_alt_list=0)`

Current interpretation:

- `PlayerTarget` is a stock target/follower helper that borrows another
  actor's world identity
- it is not a second independent hub participant rail
- so the shipped client still shows no hidden stock remote-player family beyond
  gameplay slots, standalone clones, and this helper

So the shipped client currently provides no evidence for a hidden
remote/nonlocal hub participant rail built on additional live `PlayerActor`
instances beyond:

- gameplay slots
- or the standalone clone path

### 6. The strongest stock nonlocal-like actor rail is a create-wizard preview `GameNpc (0x1397)`, not a player-family actor

The clearest stock non-slot publication path recovered in the current pass is
the unnamed create-wizard preview/source spawner at `0x00466FA0`.

Verified behavior:

- calls `GameObjectFactory_Create(0x1397)`
- that resolves to `GameNpc_Ctor (0x005E9A90)`
- `GameNpc_Ctor` seeds:
  - gameplay object type `0x1397`
  - gameplay family/kind field `+0x14 = 0x20`
  - source/profile-related fields at `+0x174/+0x178/+0x17C`
- `0x00466FA0` then writes:
  - `actor +0x174 = source_record +0x4C`
  - `actor +0x178 = source_record`
  - `actor +0x17C = source_record +0x50`
- resolves preview position through `CreateWizard_ResolvePreviewPosition (0x00466600)`
- publishes the actor through the generic world register helper
- then immediately runs `ActorBuildRenderDescriptorFromSource (0x005E3080)`

This is the current strongest stock “nonlocal-like” actor family because it is:

- non-slot
- Region-published
- source-profile driven
- and not another live `PlayerActor`

### 7. Exact Region registration contract recovered for that preview `GameNpc`

Raw instructions at `0x00467125..0x0046712E` in `0x00466FA0` show the exact
register call:

- `ActorWorld_Register(world=self, actor_group=0, actor=preview_npc, slot_index=-1, use_alt_list=0)`

That means the preview actor uses the generic Region registration contract, not
the persistent gameplay-slot contract.

Verified consequences from `ActorWorld_Register (0x0063F6D0)` plus the callsite:

- actor enters the Region-side participant manager at `Region +0x310`
- actor uses the normal list variant selected by `use_alt_list = 0`
- actor receives an auto-assigned world slot because `slot_index = -1`
- actor is mirrored into `Region +0x500 + resolved_world_slot * 4`
  - group `0`, not gameplay slot `1+`
- actor owner is set to the Region/world
- actor registered pair becomes:
  - `actor +0x5C = 0`
  - `actor +0x5E = resolved_world_slot`
- attach/init vtable slot `+0x44` can run if the visual-init flag is still
  clear
- if `actor +0x14 == 0x400`, the generic path also mirrors the actor into the
  parallel Region lane at `Region +0x360`
- no gameplay-slot table publication occurs
- no `Region +0x7C + slot` active-byte publication occurs
- no `WorldCellGrid_RebindActor(Region +0x378, actor)` call occurs here
- no slot-owned unregister mirror at `actor +0x164/+0x166` is established by
  this path

This is materially different from:

- `ActorWorld_RegisterGameplaySlotActor (0x00641090)` for persistent slot actors
- that stock slot-owned path additionally:
  - marks `Region +0x7C + slot`
  - mirrors the actor at `Region +0x500 + slot * 0x2000`
  - rewrites the actor identity to `actor +0x5C = slot`, `actor +0x5E = 0`
  - calls `WorldCellGrid_RebindActor(Region +0x378, actor)`
- and from the loader’s current “register clone, then treat it like a
  participant” experiments

### 8. The gameplay multiplayer flag changes startup sequencing, not actor family

`GameplayScene_Ctor (0x005D76C0)` and its follow-up init path now show a real
multiplayer branch:

- when `gameplay +0x6AF == 0`
  - stock code creates slot `0` through `Gameplay_CreatePlayerSlot(0)`
  - then runs `Gameplay_StartPlayerInitialization (0x005D07D0)`
- when `gameplay +0x6AF != 0`
  - stock code skips that slot-0 initialization path
  - and routes through `Gameplay_FinalizePlayerStart (0x005CFA80)` instead

Important negative result:

- this branch changes startup sequencing and startup item/region finalization
- it does **not** expose a separate stock remote-player actor family or Region
  registration helper

So the multiplayer flag is real, but it currently does not rescue the “extra
hub `PlayerActor`” hypothesis.

### 9. Live verification was unavailable in this workspace session, but the latest crash artifacts are still consistent

The Lua exec pipe was unavailable during this pass because no live game process
was running.

Useful blocker context from the current loader logs:

- `python3 tools/lua-exec.py ...` failed with “Game process not detected”
- the latest crash artifacts still show the same stock move-step fault chain:
  - `SolomonDark.exe + 0x001225E0`
  - `SolomonDark.exe + 0x001228CC`
- the recent runtime log still contains the standalone clone branch idling in
  hub immediately before that crash

So the new static findings did not contradict the existing live evidence; they
refined the stock-model interpretation around it.

## Accepted Stable Constraints

Do not reintroduce these rejected hybrids on top of the current investigation:

- temp source-actor compile + helper-lane graft onto gameplay-slot actors
- in-place `ActorBuildRenderDescriptorFromSource (0x005E3080)` on gameplay-slot actors
- post-attach staff item grafts on gameplay-slot actors
- gameplay-slot bots riding the standalone tick/owner-repair rail
- raw gameplay-slot table publication as the assumed final multiplayer path

## Current Best Direction

The next RE slice should recover the stock nonlocal/online participant actor
family and publication path instead of continuing to force extra player actors
through:

- gameplay slot tables
- or standalone clone registration

Current best interpretation after the latest static pass:

- the shipped client does not currently expose a hidden stock remote-player hub
  rail built from extra `PlayerActor`s
- the only extra `Player_Ctor` subclass recovered beyond `PlayerWizard` is
  `PlayerTarget`, and that path is a generic group-`0` target/follower helper
  rather than a second autonomous participant
- the clearest stock non-slot publication path is a preview/source `GameNpc`
  (`0x1397`) registered with:
  - `actor_group = 0`
  - `slot_index = -1`
  - `use_alt_list = 0`
  - followed by `ActorBuildRenderDescriptorFromSource`
- the gameplay multiplayer flag changes player-start sequencing but not the
  actor-family conclusion above

Updated next target:

- if hub co-presence is still the goal, investigate whether the create-wizard
  preview/source rail or another non-player family can be adapted safely for
  shared-hub presence
- or recover the upstream actor supplier that is expected to exist before the
  `gameplay +0x6AF` multiplayer branch finalizes startup
- do **not** keep assuming the missing stock contract is “another
  Region-registered `PlayerActor` just like slot/clone, but with one more
  helper call”
