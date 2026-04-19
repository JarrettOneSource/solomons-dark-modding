# Reverse Engineering Task: Solomon Dark Inventory & Item System

## Binary

- **Executable:** `SolomonDark.exe`, x86 Win32
- **Ghidra project:** `Decompiled Game/ghidra_project/SolomonDark`
- **Headless Ghidra scripts:** `Mod Loader/tools/ghidra-scripts/`
- **Curated pseudo-source:** `Decompiled Game/reverse-engineering/pseudo-source/`
- **Recovered type definitions:** `Decompiled Game/reverse-engineering/types/sd_state.h`
- **Function map:** `Decompiled Game/reverse-engineering/maps/functions.csv`
- **Stock item definitions:** `SolomonDarkAbandonware/data/items.cfg` (XML)
- **Prior investigation notes:** `Mod Loader/docs/inventory-item-investigation.md`

## Already Known (Do Not Re-Derive)

Use these as starting anchors. They are verified.

### Struct Layouts

- **`SdItemBase`** (base for all items):
  - `+0x00` vtable
  - `+0x08` item_type_id (e.g. `0x1B59` = potion, `0x1B5D` = hat helper, `0x1B5E` = robe helper, `0x1B5C` = staff helper)
  - `+0x1C` slot/side field (potions use 0 or 1 for slot index; equip items clear this)
  - `+0x58` active_flag
- **`SdPotionItem`** extends `SdItemBase`:
  - `+0x88` stack_count
- **`SdEquipVisualItem`** extends `SdItemBase`:
  - `+0x88` primary color (float4 RGBA)
  - `+0x98` secondary color (float4 RGBA)
- **`SdItemListRoot`** (inventory container):
  - `+0x0C` list_ops_vftable (embedded list-ops subobject)
  - `+0x14` item_count
  - `+0x20` item pointer array (`SdItemBase**`)
- **`SdGameplayScene`**:
  - `+0x13B8` embedded `SdItemListRoot` (holds potions at game start)
  - `+0x1428` secondary_visual_sink_holder (hat)
  - `+0x142C` primary_visual_sink_holder (robe)
  - `+0x1440` attachment_sink_holder (staff)

### Known Functions

| Address | Name | Notes |
|---------|------|-------|
| `0x0055FF20` | `Inventory_InsertOrStackItem` | `__thiscall`. Inserts item into embedded list. Stacks potions (`0x1B59`) by matching side/slot at `+0x1C`. Removes placeholder type `7000` when flagged. |
| `0x00575850` | `EquipAttachmentSink_Attach` | `__thiscall`. Non-type-7 sinks store item pointer at `sink+0x04`, owner at `sink+0x08`. Type-7 sinks route through the live inventory attach path. |
| `0x00570D80` | `EquipAttachmentSink_GetCurrentItem` | Trivial accessor: returns `sink+0x04`. |
| `0x005CFA80` | `Gameplay_FinalizePlayerStart` | Creates starter items: robe (`0x1B5E`), hat (`0x1B5D`), default staff, 2 potions. Inserts potions into `SdGameplayScene.item_list_root`. Routes equip through sink holders. |
| `0x0046AA90` | `Drop_Spawn` | Spawns drop actors. Verified factory: type `0x7DC` -> `Gold_Ctor (0x005E12C0)`. Drop fields: amount_tier `+0x13C`, amount `+0x140`, lifetime `+0x144`, active `+0x148`. Non-gold item drop path is **untraced**. |
| `0x005E13C0` | `Gold_SetAmountTier` | Derives tier byte from gold amount: `<3`->0, `<5`->1, `<8`->2, else->3. |
| `0x004EB0F0` | `Inventory_Build` | UI builder. Renders 14 separate item-slot grids with `0xC4`-stride entries. Count fields span `param_1+0xE08` through `param_1+0xEC8`. |
| `0x004F2EB0` | `Storage_Build` | UI builder. 3 item grids. Count fields at `param_1+0x59C`, `+0x5AC`, `+0x5BC`. |
| `0x005D08C0` | `InventoryHint_Render` | HUD prompt for inventory access. |
| `0x005529A0` | `Inventory_FindPotionSlot0Recursive` | Searches for potion `0x1B59` with `+0x1C == 0`. Recurses into nested container type `0x1B60`. |
| `0x00552B70` | `Inventory_FindPotionSlot1Recursive` | Same as above but `+0x1C == 1`. |

### Known Item Types from `items.cfg`

Equipment slot types: Hat, Robe, Staff, Wand, Ring, Amulet. Items carry `FX_` effect modifiers (e.g. `FX_SPELLDAMAGE +50%`, `FX_ADDSKILL "Fireball" 2`, `FX_MAXHP +25`). Items have rarity (`RARE`, `EPIC`) and can belong to item sets (`<ITEMSET>`) with set bonuses.

### Monster Drop Flags

Monster definition struct carries drop control flags:
- `+0xCC` DROP ORBS
- `+0xCD` DROP POWERUPS
- `+0xCE` DROP ITEMS
- `+0xCF` DROP GOLD
- `+0xD0` DROP SPECIFIC ITEMS
- `+0xD1` DROP POTIONS

## Investigation Scope

The following are **not known**. Investigate as many as you can, in priority order.

### 1. The Inventory Container Object

What is the object behind `Inventory_Build`'s `param_1`? It has 14 typed slot grids with count fields at `+0xE08` through `+0xEC8` and `0xC4`-stride render entries. What struct holds these? How are items organized by equipment type? Where does this object live at runtime (is it a global, a field on the gameplay scene, or allocated separately)?

**Entry points:** `Inventory_Build (0x004EB0F0)` callers and the `param_1` origin. Cross-reference `param_1+0xE08`.

### 2. Equip / Unequip Flow

How does an item move from inventory into an equipment sink and back? What function handles the equip transaction? What function handles unequip? Is there a swap operation?

**Entry points:** `EquipAttachmentSink_Attach (0x00575850)` callers, especially the "type-7 sink" path that routes through inventory. Xrefs to `sink+0x04` writes.

### 3. Item Creation From Definitions

How does the game parse `items.cfg` XML and create runtime `SdItemBase`-derived objects? Where is the item factory/constructor for equipment items (hats, robes, rings, etc.)? What determines the item_type_id written to `+0x08`?

**Entry points:** String references to `"<ITEM>"`, `"<TYPE>"`, `"<FX>"`, `"<RARITY>"` in the binary. `SdItemBase` vtable constructors. The `0x1B5D`/`0x1B5E`/`0x1B5C` type IDs used in `Gameplay_FinalizePlayerStart`.

### 4. The FX Effect Pipeline

How do item effect strings like `FX_SPELLDAMAGE +50%` get applied to player stats at runtime? Where are effects parsed, stored on the item object, and evaluated during gameplay?

**Entry points:** String references to `"FX_SPELLDAMAGE"`, `"FX_ADDSKILL"`, `"FX_MAXHP"`, etc. in the binary. Whatever writes derived stats after item changes.

### 5. Non-Gold Item Drops

`Drop_Spawn` currently only has the gold factory path verified (`0x7DC` -> `Gold_Ctor`). What factory path creates droppable equipment from monster kills? How do the monster drop flags at `+0xCC..+0xD1` route into item creation?

**Entry points:** `Drop_Spawn (0x0046AA90)` -- look for branches that use factory type IDs other than `0x7DC`. Callers of `Drop_Spawn`. Xrefs to the monster drop flag offsets.

### 6. Item Pickup

When a player walks over a drop actor, what function transfers it into inventory? What is the collision/trigger path from the drop actor to `Inventory_InsertOrStackItem`?

**Entry points:** Callers of `Inventory_InsertOrStackItem (0x0055FF20)` beyond `Gameplay_FinalizePlayerStart`. The drop actor's vtable methods. Collision dispatch in `PlayerActor_MoveStep (0x00525800)` helper `0x00526520`.

### 7. Nested Container Type 0x1B60

The potion search functions recurse into items with type `0x1B60`. What is this object? Is it a bag, a container, an inventory page?

**Entry points:** The recursion branch in `Inventory_FindPotionSlot0Recursive (0x005529A0)`. Xrefs to `0x1B60` as an immediate value. Constructor for type `0x1B60` objects.

## Deliverables

For each question (1-7):

- Report what you found: function addresses, struct field meanings, call chains
- Name functions and fields where possible
- Provide decompiled pseudo-code for key functions you identify
- State your confidence level (verified, high-confidence inference, speculative)
- Be explicit about what you confirmed vs. what you inferred from patterns
- List the best next entry points for anything you could not fully resolve

Do not fabricate addresses or struct layouts. If you cannot determine something, say so and explain what blocked you.
