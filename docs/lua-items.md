# Lua items

`sd.items` gives scripts deterministic identities for stock recipe bindings and
Lua-authored consumable potions without turning a peer's mutable native recipe
numbers, custom native subtypes, or memory addresses into multiplayer contracts.

## Registering an item

Registration is allowed only while the owning mod's entry script is loading:

```lua
local item = sd.items.register({
  key = "pentaclostic_ring",
  name = "Pentaclostic Ring",
  type = "ring",
})
```

`key` follows the canonical content-key rules in `lua-content-identity.md`. `name` and
`type` identify exactly one recipe in the effective staged `items.cfg`; recipe-backed
types are `ring`, `amulet`, `staff`, `hat`, `robe`, and `wand`. Authors do not register a
numeric recipe UID. The registry rejects duplicate keys, cross-kind key reuse, and a
second mod binding the same recipe name/type pair. A mod may register at most 256 items,
and the shared content registry is bounded at 4096 identities.

The returned descriptor contains:

| Field | Meaning |
|---|---|
| `id` | Stable positive `sd.content.v1` ID derived from mod ID and key |
| `mod_id`, `key` | Canonical authored identity |
| `name`, `type` | Exact native recipe binding |
| `native_type_id` | Read-only compiled type discriminator |
| `available` | Whether this peer currently has the recipe catalog and exact recipe |
| `recipe_uid` | Peer-local runtime UID, present only while available |
| `unavailable_reason` | Local lookup failure, present only while unavailable |

The `recipe_uid` is diagnostic local state, not serialized mod identity. Solomon Dark
persists and allocates these numbers independently, so replicated item operations carry
the stable `id` and resolve the receiving peer's UID from exact name/type at execution.
Catalog lookup is lazy: registration can finish before the game loads its item data.

## Registering a custom potion

Register the icon atlas first, then use the `potion` item type:

```lua
sd.sprites.register(
  "green_potion",
  "sprites/green_potion.png",
  "sprites/green_potion.bundle")

local potion = sd.items.register({
  key = "green_potion",
  name = "Green Potion",
  type = "potion",
  description = "A custom timed potion.",
  icon = {atlas = "green_potion", frame = 0},
  duration_ms = 180000,
  consume_vfx = {
    kind = "spell_glow",
    color = {0.15, 1.0, 0.25, 1.0},
  },
  on_consume = function(event)
    print("local owner consumed", event.content_id, event.use_id)
  end,
})
```

`description` contains 1 through 1,024 bytes. `icon.atlas` must be a sprite key
registered by the same mod, and `icon.frame` must resolve inside that atlas.
`duration_ms` is immutable metadata from 0 through 86,400,000; the mod decides
what the duration means. `on_consume` is required and runs only on the consuming
participant's process. `consume_vfx` is optional; the current semantic
`spell_glow` kind constructs the game's native `SpellGlow` animation around the
participant on every peer using the supplied finite RGBA color.

Custom potions use peer-local native subtype reservations only to enter the
stock inventory. Their descriptors add `consumable`, `description`, `icon`,
`duration_ms`, `native_subtype`, and optional `consume_vfx` fields. The subtype
is diagnostic local state. Network inventory, loot, pickup, and use messages
carry the stable content ID and resolve that peer's subtype at the native edge.

Every accepted use also queues `item.consumed` on every peer:

```lua
sd.events.on("item.consumed", function(event)
  -- content_id, mod_id, key, participant_id, use_id, duration_ms, local_owner
end)
```

`use_id` is deduplicated within the current participant session and run.
`local_owner` is true only on the consuming process. This replicated event is
the correct place to maintain effect state needed by an authority-side filter;
the direct `on_consume` callback is the correct place for owner-local actions.

## Looking up registrations

```lua
local owned = sd.items.get("pentaclostic_ring") -- key owned by this mod
local any = sd.items.get(5785942626980372610)   -- global stable content ID
local all = sd.items.list()                     -- deterministic load order
```

Missing registrations return `nil`. Descriptors never include recipe pointers, item
addresses, or catalog addresses. `items.register` and `items.read` are the corresponding
runtime capabilities.

`sample.lua.items_registry_lab` is disabled by default and binds the stock
`Pentaclostic Ring` recipe.

## Granting a registered item

`sd.items.grant` accepts an owned recipe-backed content key or any registered
recipe-backed stable content ID:

```lua
local local_request = sd.items.grant("pentaclostic_ring")

local remote_request = sd.items.grant(item.id, {
  participant_id = remote_participant_id,
})
```

Only the offline or host simulation authority may grant a recipe-backed item.
Custom consumable potions enter inventory through the loot path described
below. Omitting
`participant_id` targets the authority's local participant. A multiplayer host may use
the positive ID from a connected participant descriptor to target that participant;
unknown and disconnected IDs are rejected before queueing. A client cannot author a
grant.

The returned table confirms queue acceptance, not native completion:

| Field | Meaning |
|---|---|
| `request_id` | Authority-owned deduplication ID for this grant |
| `content_id` | Stable registered item ID carried by the request |
| `target_participant_id` | Semantic local ID (`1`) or the selected remote ID |
| `local_target` | Whether the authority queued its own inventory mutation |

The target owner resolves the registered name/type to its own recipe UID immediately
before calling the stock inventory insertion routine on the gameplay pump. Protocol 81
carries only the authority ID, target ID, request ID, stable content ID, and optional
color state; recipe UIDs and native addresses never cross the wire. Steam delivery is
reliable, the receiver accepts the command only from its configured host, and bounded
request-ID memory suppresses duplicates. Eventual native failures are written to the
loader log.

Hats and robes may carry their complete wearable color block:

```lua
sd.items.grant("ceremonial_robe", {
  participant_id = remote_participant_id,
  color_state = { -- exactly 32 integer bytes, indexed 1 through 32
    0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0,
  },
})
```

`color_state` is rejected for every other item type. Granting advertises the
`items.grant.authority` capability.

## Registering custom loot

`sd.loot.register` adds a registered consumable to the shared additive loot
pool while the owning entry script is loading:

```lua
sd.loot.register({
  item = potion.id, -- an owned key is also accepted
  chance = 0.5,
  boss_chance = 1.0,
})
```

Both chances are finite values from 0 through 1. The authority rolls every
entry independently after a supported hostile enemy dies. `chance` applies to
ordinary enemies; `boss_chance` applies to the exact stock Demon Skull, Demon,
Dire Faculty, and Heartmonger boss types. A successful roll creates the custom
potion through the stock item-drop actor. The drop's stable content ID,
peer-local subtype resolution, pickup request/result, inventory stack, name,
description, icon, and use action all follow the existing multiplayer loot and
native inventory paths.

`sd.loot.list()` returns the current additive entries. The capabilities are
`loot.register` and `items.consumables.register`.

## Verification

Enable the sample mod to run the read-only registry verifier:

```powershell
py tools/verify_lua_items.py
```

The verifier checks the fixed ID, exact lookup, local recipe resolution, strict input
rejection, and absence of address-shaped fields without granting or changing an item.

With the authority in an active gameplay scene, the separate verifier below performs
one real local inventory mutation and therefore requires an explicit confirmation flag:

```powershell
py tools/verify_lua_item_grant.py --confirm-mutation
```

The two-peer verifier stages only the item registry lab, enters an isolated
host/client run, and performs one real grant to each participant:

```powershell
py tools/verify_lua_items_multiplayer.py --launch-pair --confirm-mutation
```

It proves that a client cannot author a grant, a host-to-client command changes
only the client's inventory through that peer's resolved recipe UID, and a
host-local command changes only the host's inventory. Both mutations must add
exactly one recipe unit. The verifier records each peer's local recipe UID and
stops only the exact processes it launched.

`canary.lua.invincibility_potion` is the end-to-end custom-content canary. Its
manually baked bright-green potion drops at 50 percent from ordinary enemies
and 100 percent from bosses, enters the stock inventory, emits native
`SpellGlow`, and combines a replicated three-minute effect with damage and mana
filters.
