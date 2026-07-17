# Inventory And Item Investigation

Date: 2026-04-13

## Current Repo State

- Item and inventory work is split across three layers:
  - stock gameplay/item structures and pseudo-source in `Decompiled Game/reverse-engineering/`
  - loader runtime state exposure in `Mod Loader/SolomonDarkModLoader/src/mod_loader_gameplay/public_api.inl`
  - UI-only surfaces like `Inventory_Build` and `Storage_Build`
- current loader runtime does **not** expose a first-class `sd.items` namespace yet
- current live player state does expose:
  - `gold`
  - `progression_handle_address`
  - `equip_handle_address`
  - `equip_runtime_state_address`
  - visual/equip sink lane snapshots

## Recovered Stock Types

Key recovered layouts in `sd_state.h`:

- `SdItemBase`
  - `+0x08` item type id
  - `+0x1C` slot / side / reset-state field
  - `+0x58` active flag
- `SdEquipVisualItem`
  - item-derived helper object
  - color float4s at `+0x88` and `+0x98`
- `SdPotionItem`
  - item-derived potion object
  - stack count at `+0x88`
- `SdItemListRoot`
  - embedded list root with:
    - `+0x14` item count
    - `+0x20` item pointer array
- `SdStandaloneWizardEquipRuntime`
  - sink holders at:
    - `+0x18` secondary/hat
    - `+0x1C` primary/robe
    - `+0x30` attachment/staff
- `SdGameplayScene`
  - embedded item list root at `+0x13B8`
  - sink holders at `+0x1428`, `+0x142C`, `+0x1440`

## Verified Stock Inventory / Item Functions

### Inventory insertion and potion stacking

- `0x0055FF20` -> `Inventory_InsertOrStackItem`
  - inserts items into the embedded inventory list
  - potion item type is `0x1B59`
  - if a potion with the same side/index at `item + 0x1C` already exists, stacks into existing `potion + 0x88`
  - optional flag removes placeholder item type `7000`

### Recursive potion lookups

- `0x005529A0` -> `Inventory_FindPotionSlot0Recursive`
  - searches for potion type `0x1B59` with `+0x1C == 0`
- `0x00552B70` -> `Inventory_FindPotionSlot1Recursive`
  - searches for potion type `0x1B59` with `+0x1C == 1`
- both recurse into nested container item type `0x1B60`

### Starter inventory / equip ownership

- `0x005CFA80` -> `Gameplay_FinalizePlayerStart`
  - creates:
    - robe helper item `0x1B5E`
    - hat helper item `0x1B5D`
    - default staff
    - two potion items `0x8C` ctor path
  - inserts potions into gameplay-owned `item_list_root`
  - routes robe/hat/staff through gameplay-owned sink holders

### Sink ownership path

- `0x00575850` -> `EquipAttachmentSink_Attach`
  - for non-type-7 sinks:
    - `sink + 0x04` stores the attached item pointer
    - `sink + 0x08` stores a current owner/global pointer
  - type-7 sinks route through the live inventory attach path instead of the direct pointer store
- `0x00570D80` -> `EquipAttachmentSink_GetCurrentItem`
  - trivial accessor for `sink + 0x04`

This matches the live holder readback:

- holder object -> first pointer is sink self
- sink self + `0x04` -> current attached item

### Drop / reward spawning

- `0x0046AA90` -> `Drop_Spawn`
  - spawns one or more drop actors
  - verified current factory path:
    - gameplay object type `0x7DC`
    - `0x7DC` -> `Gold_Ctor (0x005E12C0)`
  - marks each with:
    - `drop + 0x13C` amount tier byte
    - `drop + 0x140` amount
    - `drop + 0x144` lifetime
    - `drop + 0x148` state byte
  - stages them in a temporary pointer list
  - registers each into the live world through `ActorWorld_Register (0x0063F6D0)`
- `0x005E13C0` -> `Gold_SetAmountTier`
  - derives tier byte from amount:
    - `<3` -> 0
    - `<5` -> 1
    - `<8` -> 2
    - else -> 3
- loader-side reward support is narrower right now:
  - `SpawnReward(...)` currently supports gold plus debug-spawned health/mana
    orbs for multiplayer pickup verification
  - native reward function resolved through `kSpawnRewardGold`

## UI Surfaces

- `0x004EB0F0` -> `Inventory_Build`
  - asset-backed inventory overlay builder
  - chooses `Inventory` vs `Inventory@2X`
- `0x004F2EB0` -> `Storage_Build`
  - storage UI builder
- `0x005D08C0` -> `InventoryHint_Render`
  - renders the HUD prompt for inventory access

These are UI surfaces only. They do not prove item ownership by themselves.

## Loader Runtime Exposure Today

Current `sd.player.get_state()` exposes:

- `gold`
- `progression_address`
- `progression_handle_address`
- `equip_handle_address`
- `equip_runtime_state_address`
- `hub_visual_attachment_ptr`
- `primary_visual_lane`
- `secondary_visual_lane`
- `attachment_visual_lane`

Current `sd.player.get_inventory_state()` exposes a typed read-only inventory
audit surface:

- gameplay scene address and embedded `SdItemListRoot` address
- item row count, item pointer array address, truncation flag, and up to 64
  decoded item rows
- raw stock-list count remains separately visible for diagnosis; base `Item`
  objects (`0x1B58`) used as empty shop/inventory grid placeholders are excluded
  from participant-owned item counts and replication
- item row fields: native item address, type id, exact recipe UID, slot/side
  field, potion stack count for potion rows (`0x1B59`), and wearable color state
- gameplay-owned primary/secondary/attachment visual sink lanes, including the
  current object address, type id, recipe UID, and wearable color state
- live verification maps the loader's `primary_visual_lane` field to the
  `0x1428` sink and helper type `0x1B5D` (hat), while
  `secondary_visual_lane` maps to the `0x142C` sink and helper type `0x1B5E`
  (robe); this follows the existing loader offset labels, not the older prose
  shorthand that called `0x1428` the secondary sink

Current multiplayer ownership state:

- local UDP `StatePacket` protocol v30 introduced a bounded full participant-owned
  inventory snapshot with up to 64 decoded item rows and a total/truncated
  marker, so peers can inspect each other's current native inventory item rows
- `sd.player.get_progression_book_state()` reads the local native progression
  table; the current verified starter state has 83 rows, and protocol v30
  mirrors up to 128 participant-owned progression-book/statbook/skillbook/
  spellbook rows plus total/truncated metadata
- local UDP also mirrors the current ability loadout as participant-owned state
- host-authorized item/potion carrier pickup credits the requesting participant
  by exact item type and recipe identity, wearable color when applicable, slot,
  and stack count
- the owning client clones exact recipe-backed native items, transfers them
  through stock `Inventory_InsertOrStackItem`, and verifies the resulting native
  inventory quantity; potion stacking uses the same stock insertion ABI
- `sd.player.equip_inventory_item(recipe_uid)` queues an owner-local stock
  inventory-to-equipment transaction for hats, robes, staffs, wands, rings,
  and amulets; it returns the previous item to inventory, dirties the view,
  refreshes native progression, and verifies exact recipe ownership against
  the same native holder selected at transaction start
- protocol v60 carries exact hat, robe, staff/wand, three-ring-slot, and amulet
  recipe identity plus wearable colors; native remote participant actors
  reconcile visible lanes and retry divergence, while every peer retains the
  complete owner-authored equipment snapshot
- observer processes intentionally retain replicated inventory rows rather than
  a second participant-owned native inventory root
- host-authorized Random Skill, Damage x4, and Bonus Skill powerups apply to
  participant-owned progression/status and are verified in both ownership
  directions
- the native progression book is exposed as progression-book, statbook, skillbook,
  and spellbook views so every instance can inspect the same owner-authored rows

Multiplayer exposure:

- `sd.world.get_replicated_loot()` exposes host-owned run loot metadata received
  by a client, including gold drops (`0x7DC`), health/mana orbs (`0x7DB`), and
  item/potion carrier drops (`0x7DD`)
- `sd.world.request_loot_pickup(network_drop_id)` sends a reliable local UDP
  pickup request for a host-owned replicated drop and exposes the last
  `LootPickupResult` through the replicated loot view
- `sd.runtime.get_multiplayer_state()` exposes each participant's
  `ParticipantOwnedProgressionState`: initialized flag, gold, gold revision,
  compact inventory item rows, compact progression-book/statbook rows, current
  ability loadout, and inventory/spellbook/statbook/loadout revision counters
- `tools/verify_multiplayer_inventory_audit.py` launches a local host/client
  pair, checks `sd.player.get_inventory_state()` on both clients for the native
  starter inventory shape, checks `sd.player.get_progression_book_state()` for
  the native book table, and verifies that each peer receives the other's
  participant-owned starter potion rows, compact statbook rows, and ability
  loadout
- `tools/verify_multiplayer_native_item_inventory_sync.py` proves an exact
  recipe-backed item pickup enters the owning client's stock inventory, can be
  equipped by recipe UID, returns the prior item to inventory, advances both
  inventory revisions, and reaches the host's native remote actor with matching
  type, recipe, and wearable color

## Live Runtime Check

Using the current `sd.world.get_scene().id` as a direct memory anchor:

- `scene + 0x13CC` item count was `2`
- `scene + 0x13D8` item pointer array was non-null
- enumerated live items were:
  - `item[0]`: type `0x1B59`, slot `0`, stack `1`
  - `item[1]`: type `0x1B59`, slot `1`, stack `1`
- gameplay sink holders were also populated:
  - `scene + 0x1428` secondary sink -> item type `0x1B5D` (hat helper)
  - `scene + 0x142C` primary sink -> item type `0x1B5E` (robe helper)
  - `scene + 0x1440` attachment sink -> item type `0x1B5C` (staff / attachment helper)

That live state matches the recovered `Gameplay_FinalizePlayerStart` story:

- embedded item list root holds the two potion items
- gameplay sink holders own the robe, hat, and attachment items

Important loader/runtime caveat:

- local `sd.player.get_state()` still reported:
  - `equip_handle_address = 0`
  - `equip_runtime_state_address = 0`
- while the gameplay scene sink holders were clearly populated
- current interpretation:
  - local-player item/equip ownership in the stock gameplay path does not require the same standalone wrapper/runtime handles used by bot/clone work
  - the gameplay scene sink holders are currently the more trustworthy live anchor for local player item ownership

## Intersection With Pathfinding / Badguy Work

- monster definitions already carry item/drop-facing flags:
  - `DROP ORBS` at `+0xCC`
  - `DROP POWERUPS` at `+0xCD`
  - `DROP ITEMS` at `+0xCE`
  - `DROP GOLD` at `+0xCF`
  - `DROP SPECIFIC ITEMS` at `+0xD0`
  - `DROP POTIONS` at `+0xD1`
- that means badguy AI and item drops meet in the same monster-definition blob that also carries:
  - chase speed `+0x6C`
  - attack speed `+0x70`
  - flanking `+0xB8`
  - pathfinding mode `+0xB9`
- `Drop_Spawn` then routes resulting drop actors back through the same world registration machinery used by other live actors

## Follow-Up Findings

Date: 2026-04-15

### Inventory screen object and category caches

- `0x00560380` -> `InventoryScreen_Ctor`
  - constructs the standalone inventory screen object that backs `Inventory_Build`
  - stores the active screen singleton in `DAT_00819E58`
  - current browsed inventory root lives at `screen + 0x88`
  - the 13 UI category arrays live at `screen + 0xE00..+0xEC0`
  - their paired counts live at `screen + 0xE08..+0xEC8`
- `0x00570C10` -> `InventoryScreen_GetCurrentInventoryRoot`
  - trivial accessor for `screen + 0x88`
  - this is the active inventory root used by drag/drop, equip, and sack browsing
- `0x005B4C10` -> `InventoryScreen_ResetCategoryCaches`
  - destroys and zeroes the same `+0xE00..+0xEC8` category arrays/counts that `Inventory_Build` later renders

Current interpretation:

- `Inventory_Build`'s `param_1` is an inventory-screen UI object, not the gameplay scene
- the rendered slot groups are cached UI category views built on top of the currently selected inventory root, not separate ownership containers in gameplay memory

### Additional inventory and equip helpers

- `0x00550450` -> `Item_IsEquipmentOrContainer`
  - returns true for ring / amulet / staff / hat / robe / sack / wand
- `0x00552650` -> `Inventory_FindItemByTypeRecursive`
  - recursive embedded-list scan by runtime item type id
  - descends into `0x1B60`
- `0x00570CD0` -> `EquipAttachmentSink_AcceptsItem`
  - validates item types against sink kinds before attach / drag-drop
  - kind `1` = hat, `2` = robe, `4` = staff or wand, `5` = ring, `6` = amulet
- `0x0066F020` -> `EquipAttachmentSink_UnequipCurrentIntoInventory`
  - clears the selected equip sink
  - reinserts the detached item into the active inventory root
  - refreshes progression/runtime state after the move

### Item definition parse layer

- `0x00574D60` -> `ItemSet_Parse`
  - parses `ITEMSET`
  - owns a display name, a set-bonus FX list, and a nested item-recipe list
- `0x00573570` -> `ItemRecipe_Parse`
  - parses one `ITEM` definition from `items.cfg`
  - this is a blueprint / recipe object, not a live `SdItemBase`
  - verified recipe fields:
    - `+0x84` runtime item type id
    - `+0x89` rarity byte
    - `+0x8C` primary color float4
    - `+0x9C` secondary color float4
    - `+0x6C` parsed FX list
- `0x005722A0` -> `ItemFx_Parse`
  - parses one `FX_*` token into a compact FX object
  - writes the effect-kind byte at `fx + 0x14`
  - writes optional numeric magnitude at `fx + 0x20`
  - item recipes and item sets both route through this parser
- `0x00571980` -> `Item_GetDisplayTypeName`
  - formats item-facing type labels
  - `0x1B60` displays as `Sack`

### Nested container type `0x1B60`

- `0x1B60` is now best interpreted as a real nested inventory item
- stock display name is `Sack`
- the recursive potion and type-search helpers descend into it as another embedded item-list root
- the inventory action flow opens it as a nested inventory browse target instead of consuming or equipping it

### FX runtime interpretation

- current high-confidence runtime seam remains `ActorProgressionRefresh (0x0065F9A0)`
- parser-side findings now separate:
  - item / set definition parsing
  - FX object parsing and storage
  - runtime stat rebuild after equip/use changes
- still unresolved:
  - the exact native function that walks the parsed FX lists and applies the final stat deltas into live progression fields

### Remaining gaps after follow-up pass

- unresolved runtime item factory:
  - we now have the parse-layer objects (`ItemRecipe_Parse`, `ItemSet_Parse`, `ItemFx_Parse`)
  - we still do not have the exact function that materializes a parsed equipment recipe into a live `SdItemBase`-derived object on demand
- unresolved non-gold drop factory:
  - `Drop_Spawn` remains gold-only in the verified path
  - monster drop flags are still verified on the config side only
- unresolved walk-over pickup bridge:
  - `MovementCollision_ResolveDynamicObjects` is too broad to claim as the pickup transfer path
  - we still need the specific drop-actor callback / collision branch that leads into `Inventory_InsertOrStackItem`

## Current Best Next Targets (April 15 Snapshot)

- static:
  - follow the parse-layer handoff from `ItemRecipe_Parse (0x00573570)` into the runtime item factory that produces live `SdItemBase`-derived objects
  - identify the exact item/equip UI functions behind current placeholders `0x00562520` and `0x0056DE50`
  - resolve the actual non-gold drop actor / factory path beyond `Drop_Spawn`'s verified gold branch
- live:
  - add a typed debug helper to enumerate `SdGameplayScene.item_list_root`
  - verify current player potion objects and placeholder-item removal path
  - trace `Inventory_InsertOrStackItem` during reward pickup / equip swap flows
  - confirm the sack (`0x1B60`) inner item-list layout directly at runtime

## Follow-Up Findings

Date: 2026-04-30

Focus: participant-owned inventory prep, with native pickup seams for item loot,
gold, orbs, and powerup bonuses.

### Core ownership model

- the stock local inventory root is the embedded `SdItemListRoot` at
  `DAT_0081C264 + 0x13B8`
- `Inventory_InsertOrStackItem (0x0055FF20)` already accepts a caller-supplied
  `SdItemListRoot`-compatible root
- `InventoryScreen + 0x88` / `InventoryScreen_GetCurrentInventoryRoot
  (0x00570C10)` is the UI browse root, not a separate ownership container
- stock gold is still a global scalar at `DAT_0081A388`
- `Gold_ChangeGlobal (0x005A7C60)` changes that global scalar and has no
  actor / participant context

Current interpretation:

- participant-owned inventories should be represented as per-participant
  `SdItemListRoot`-compatible roots
- the existing insertion primitive can probably be reused after the pickup seam
  chooses the participant root
- global gold cannot become participant-owned by only patching
  `Gold_ChangeGlobal`, because the participant identity is already lost by then

### Item loot pickup seam

- `0x005E6B50` -> `ItemDropActor_TickPickup`
  - vtable slot `+0x08` on the world item-drop carrier vtable `0x0079C98C`
  - world actor type `0x7DD`
  - the decompiler labels the vtable area near this actor as `Sack::vftable`,
    but the tick path is the walk-over world pickup carrier, not the inventory
    sack container item
- stock pickup hard-codes local gameplay slot 0:
  - actor: `DAT_0081C264 + 0x1358`
  - progression handle: `DAT_0081C264 + 0x1654`
- when pickup succeeds:
  - unregisters / destroys the drop actor
  - shows pickup text
  - inserts `drop + 0x148` into `DAT_0081C264 + 0x13B8`
  - sets the inventory dirty byte at `DAT_0081C264 + 0x7C`
  - clears `drop + 0x148`

Key instruction proof:

```asm
005e6d7a  MOV ECX,dword ptr [ESI + 0x148]
005e6d80  PUSH 0x1
005e6d82  PUSH 0x1
005e6d84  PUSH ECX
005e6d85  MOV ECX,dword ptr [0x0081c264]
005e6d8b  ADD ECX,0x13b8
005e6d91  CALL 0x0055ff20
005e6d96  MOV EDX,dword ptr [0x0081c264]
005e6d9c  MOV byte ptr [EDX + 0x7c],0x1
005e6da0  MOV dword ptr [ESI + 0x148],0x0
```

Participant inventory seam:

- this is the best first hook for item loot ownership
- replace the local slot-0 pickup decision with a participant resolver
- route `drop->held_item` into that participant's inventory root via
  `Inventory_InsertOrStackItem`
- dirty / refresh the selected participant inventory view if the UI is browsing
  that same root

### Gold pickup seam

- `0x005E66B0` -> `GoldActor_TickPickup`
  - vtable slot `+0x08` at `0x0079C924`
  - world actor type `0x7DC`
- fields:
  - `+0x13C` amount tier byte
  - `+0x140` amount
  - `+0x144` lifetime
  - `+0x148` state byte; live verification showed this is not a reliable
    "available for pickup" predicate because newly spawned claimable gold can
    report zero here while still carrying a positive amount
- stock pickup also hard-codes local gameplay slot 0:
  - actor: `DAT_0081C264 + 0x1358`
  - progression handle: `DAT_0081C264 + 0x1654`
- on pickup, stock code calls `Gold_ChangeGlobal(gold->amount, 0)`

Recovered global-gold helper:

```c
int Gold_ChangeGlobal(int delta, char allow_negative) {
  if (!allow_negative && DAT_0081A388 + delta < 0) {
    return 0;
  }
  DAT_0081A388 += delta;
  if (DAT_0081A388 < 0) {
    DAT_0081A388 = 0;
  }
  return 1;
}
```

Participant inventory seam:

- hook `GoldActor_TickPickup`, not only `Gold_ChangeGlobal`
- choose the participant before crediting the amount
- credit a participant-owned gold bucket instead of the global scalar
- leave `Gold_ChangeGlobal` available for stock UI / legacy paths until shops
  and traders are deliberately rerouted

### Orb and powerup pickup seams

- enemy reward selection now resolves to
  `EnemyDeath_SelectAndSpawnRewards (0x0047C070)`
- monster definition drop flags are read from:
  - `+0xCC` `DROP ORBS`
  - `+0xCD` `DROP POWERUPS`
  - `+0xCE` `DROP ITEMS`
  - `+0xCF` `DROP GOLD`
  - `+0xD0` `DROP SPECIFIC ITEMS`
  - `+0xD1` `DROP POTIONS`
- orb rewards:
  - actor type `0x7DB`
  - ctor `Orb_Ctor (0x005E1150)`
  - reset/value helper `Orb_ResetPullAndValue (0x005E1220)`
  - pickup tick `Orb_TickPickup (0x005E62E0)`
  - the tick scans native slots `0..3` for attraction / pickup range
  - the recovered health / mana reward branch is gated to `slot == 0`
- powerup bonuses:
  - actor type `0x7F6`
  - ctor `Bonus_Ctor (0x005E2D90)`
  - pickup tick `Bonus_TickPickup (0x006039C0)`
  - this path checks and credits only local slot 0

Current interpretation:

- orbs are not inventory items; they are resource reward actors
- powerups are also reward actors, not inventory roots
- multiplayer request/result pickup now covers host-owned health/mana orbs
  without relying on the stock slot-0 application branch
- physical walk-over orb pickup still needs a stock tick hook if we want local
  collision pickup to route through the same participant-owned authority path
- powerups still need their own participant-owned reward path

### Drop selector and factory paths

- `Drop_Spawn (0x0046AA90)` remains the verified gold factory path
- item, potion, orb, and powerup reward selection lives one layer higher in
  `EnemyDeath_SelectAndSpawnRewards (0x0047C070)`
- the selector builds a random candidate list from the monster definition flags
  and dispatches to separate creation paths:
  - orbs create type `0x7DB`
  - gold routes through the owner-side gold drop method / `Drop_Spawn`
  - item drops route through an owner-side vtable method at `+0x140`
  - powerups create type `0x7F6`
  - potion drops route through an owner-side vtable method at `+0x148`

### Participant-owned inventory implementation sketch

```c
struct ParticipantInventoryState {
  SdItemListRoot inventory_root;
  int gold;
  SdEquipAttachmentSink hat_sink;
  SdEquipAttachmentSink robe_sink;
  SdEquipAttachmentSink staff_sink;
  bool inventory_dirty;
};

Participant *ResolvePickupParticipant(SdActorEntity *drop_actor, float radius) {
  Participant *best = 0;
  float best_dist_sq = radius * radius;

  for each participant with a live actor {
    float dist_sq = DistanceSquared(participant.actor, drop_actor);
    if (dist_sq < best_dist_sq) {
      best = participant;
      best_dist_sq = dist_sq;
    }
  }

  return best;
}

void HookedItemDropPickup(SdItemDropActor *drop) {
  Participant *participant = ResolvePickupParticipant(drop, item_pickup_radius);
  if (!participant || !drop->held_item) {
    return;
  }

  Actor_UnregisterOrDestroy(drop);
  Inventory_InsertOrStackItem(&participant->inventory.inventory_root,
                              drop->held_item,
                              1);
  participant->inventory.inventory_dirty = true;
  drop->held_item = 0;
}

void HookedGoldPickup(SdGoldDropActor *gold) {
  Participant *participant = ResolvePickupParticipant(gold, gold_pickup_radius);
  if (!participant) {
    return;
  }

  Actor_UnregisterOrDestroy(gold);
  participant->inventory.gold += gold->amount;
}

void BindInventoryScreenToParticipant(InventoryScreen *screen,
                                      Participant *participant) {
  screen->current_inventory_root = &participant->inventory.inventory_root;
  InventoryScreen_ResetCategoryCaches(screen);
}
```

### Why not hook lower-level helpers first

- `Inventory_InsertOrStackItem` is a useful primitive but a poor policy hook
  because it is shared by starter inventory, UI moves, equip changes, shop /
  trader flows, scripts, and nested container operations
- `Gold_ChangeGlobal` is too late to infer the pickup owner and is also used by
  non-pickup economy flows
- `InventoryScreen + 0x88` is the right UI browse seam, but changing it alone
  does not make walk-over pickup participant-owned

### Live Lua sanity check

The staged loader was launched with:

```text
dist/launcher/SolomonDarkModLauncher.exe launch --json
```

Startup reached `startup-complete`, then a read-only Lua probe confirmed the
same root offsets were readable in the live scene:

```text
scene=transition base=0x14050678 gold=nil inv_root=0x14051A30 item_count=0 items=0x0 actor0=0x1405C738 prog0=0x14154538
```

This was an offset sanity check in a transition scene, not a gameplay pickup
proof. The older live gameplay inventory probe remains the stronger proof for
the initial two-potion inventory state.

### Multiplayer reward sync probe

`python3 tools/probe_run_reward_sync.py --attempts 3` is the current local UDP
reward boundary probe. It confirmed that host-spawned gold rewards appear in
the host actor list as type `0x7DC`, with amount tier at `+0x13C`, amount at
`+0x140`, lifetime at `+0x144`, and a state byte at `+0x148`. The same run
client receives host-owned gold metadata through `sd.world.get_replicated_loot()`
while still receiving zero `WorldSnapshot` gold actors. The probe now parks both
players outside pickup range before checking materialization, because a
pickup-range native gold actor can be zeroed by the stock tick before the next
sample. Later pickup-authority testing showed that `+0x148` is not a valid
"available for pickup" predicate by itself: live, spawned gold can report state
byte `0` while still carrying a valid amount and stable host network drop id.
`tools/verify_multiplayer_gold_pickup_authority.py` owns the pickup assertion:
clients request the host-owned drop id, the host range-checks the request, the
owning participant ledger is credited once, the host-native drop is deactivated,
and duplicate pickup attempts are rejected without a second credit.

For multiplayer, synced loot is required, but pickup credit must be
participant-owned. Gold, item, potion, orb, and powerup drops should be
host-owned lifecycle objects. `LootSnapshot` now drives client-side
presentation actors for host-owned gold, health/mana orb, potion, and exact
recipe-backed item drops; those actors are marked as replicated presentations
and stock pickup ticks are suppressed on the client so they cannot mutate
local/global progression state. Gold has the first
host-authoritative pickup slice: clients call `sd.world.request_loot_pickup(network_drop_id)`, the host
sanity-checks run nonce, range, duplicate pickup state, and drop identity, then
confirms or denies the request. Accepted gold pickup results credit the owning
participant's gold ledger, advance `gold_revision`, zero the host gold actor
amount, and suppress that drop id from later metadata snapshots. Duplicate
requests return `AlreadyGone` and do not credit again. This keeps a joined
client's primary single-player save isolated from the host's world and prevents
client-local stock pickup from mutating the wrong process-global state.
Health/mana orb pickup now uses the same request/result boundary. The host
snapshots type `0x7DB` orbs from the transient actor list, including resource
kind, raw value, lifetime, and position. Accepted orb pickup results apply the
host-authored health or mana resource value to the requesting participant's
runtime vitals and to the client's local HP/MP presentation. Item/potion
carrier pickup now uses the same host request/result boundary for type `0x7DD`:
the host snapshots `drop + 0x148` held-item metadata, including recipe identity
and wearable color, clears that held-item pointer on accepted pickup, and
credits the requesting participant's replicated inventory state. The owning
client transfers a native held object into its active inventory through
`Inventory_InsertOrStackItem`, confirms the exact native identity delta, and
deduplicates by run/drop identity. Potion stacking and a recipe-backed wearable
pickup/equip round trip are proven live. Powerup, independently rewarded
spellbook/statbook, and non-shop quest reward paths still need
participant-owned native mutation seams.

`python3 tools/verify_multiplayer_gold_pickup_authority.py --attempts 3` is the
focused proof for that gold slice. The latest run verified amount/tier identity,
single client credit, host participant-ledger update, unchanged host process
gold, consumed host actor amount, client metadata despawn, and duplicate
rejection.

`python3 tools/verify_multiplayer_orb_pickup_authority.py --attempts 3` is the
focused proof for health/mana orb pickup authority. The latest run verified both
resource kinds, accepted host resource deltas, host participant-vital update,
client local HP/MP convergence, metadata despawn, and duplicate rejection.

### Hub inventory-shop ownership boundary

`InventoryShop` (`0x004F59A0`, vtable `0x0079044C`) and its transfer callback
at `0x0056CD00` do not implement a shared merchant catalog or spend gold. The
Luthacus' Scavenged Goods screen moves objects between the active player's
backpack and that player's persistent scavenged storage. That storage is
participant-private: peers synchronize the owner's resulting active backpack,
not the contents of another player's storage container.

`tools/verify_multiplayer_hub_inventory_shop_sync.py` drives the stock dialog
and inventory screen with real window input. It transfers a starter potion into
Luthacus storage and back, checks both inventory revisions on the observing
peer, proves the other participant's native backpack never changes, and
exercises the placeholder-heavy stock list created by the grid UI. Base `Item`
placeholder objects remain visible only through `raw_item_count`; they never
become replicated inventory rows.

The gold-spending `Shop` callback at `0x0056BF70` remains stock-owned on the
purchasing process. A live Fomentius purchase spends only the buyer's native
gold, stacks the bought potion only in that buyer's active backpack, and then
advances the participant gold and inventory revisions. The other process keeps
its own native gold and backpack unchanged while observing the buyer's exact
post-purchase values.

`PerkShop` (`0x0056C340`) is also owner-local. The focused Hagatha proof buys a
600-gold Life Charm through the stock two-stage catalog button. It raises only
the buyer's native max/current HP from 50 to 62.5; the other player remains at
50 HP and keeps all gold/items, while its remote participant view converges to
the buyer's 62.5 HP and exact post-purchase gold. Both merchant cases are in
`tools/verify_multiplayer_hub_shop_ownership.py`.

### Remaining gaps after native recipe-item equipment

- remote observer/host views still use replicated rows rather than a second
  stock-native inventory root; this is the intended ownership boundary because
  stock inventory/equip/storage/merchant code consumes the one process-local
  scene root without a participant parameter
- exact equipment sync covers hat, robe, staff, wand, all three ring sinks, and
  the amulet sink; the focused live matrix passes every supported item type,
  including remote wearable-color convergence for hat and robe
- nested sack ownership and inventory-screen browsing have not had an
  owner-sensitive multiplayer pass
- per-run owner-authored spellbook/statbook rows and native participant-clone
  reconciliation are verified; durable storage/lifetime rules are still needed
  before loot or progression can mutate those books independently across runs
- the remaining Hagatha charm/curse catalog needs a behavior matrix beyond the
  verified Life Charm slice; invisible loadout identity only needs replication
  when a peer cannot reconstruct the observable stat/status/cast outcome

## Current Best Next Targets

- verify third-ring unlock behavior through the stock inventory UI; protocol
  capture already includes the progression-gated third sink, while the semantic
  equip API intentionally fills only the two unconditional ring slots
- extend the verified per-run spellbook/statbook ownership into durable reward
  and persistence rules before new loot paths mutate those books
- keep `InventoryScreen + 0x88` on the local owner root and verify nested sack
  browsing does not cross participant boundaries; the Luthacus top-level
  storage boundary is now explicitly participant-private
- extend the Hagatha pass across charms/curses that alter movement, potion use,
  casting, or statuses, and verify each result through the existing participant
  stat/status/effect channels
