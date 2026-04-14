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
    - `drop + 0x148` active flag
  - stages them in a temporary pointer list
  - registers each into the live world through `ActorWorld_Register (0x0063F6D0)`
- `0x005E13C0` -> `Gold_SetAmountTier`
  - derives tier byte from amount:
    - `<3` -> 0
    - `<5` -> 1
    - `<8` -> 2
    - else -> 3
- loader-side reward support is narrower right now:
  - `SpawnReward(...)` currently only supports gold
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

Current gaps:

- no general item enumeration API
- no inventory container dump API
- no potion slot enumeration API
- no equip inner-object decode beyond visual sink lanes

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

## Current Best Next Targets

- static:
  - inspect item base / container vtables around `0x00572F20` and `0x00575850`
  - inspect `Gameplay_FinalizePlayerStart` neighbors for exact item-list insertion order
  - resolve the actual drop actor type created by `Drop_Spawn`
- live:
  - add a typed debug helper to enumerate `SdGameplayScene.item_list_root`
  - verify current player potion objects and placeholder-item removal path
  - trace `Inventory_InsertOrStackItem` during player-start or reward grants
