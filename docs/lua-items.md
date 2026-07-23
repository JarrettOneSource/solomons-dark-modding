# Lua items

`sd.items` gives scripts deterministic identities for item recipes without turning a
peer's mutable native recipe numbers or memory addresses into multiplayer contracts.

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
`type` identify exactly one recipe in the effective staged `items.cfg`; supported types
are `ring`, `amulet`, `staff`, `hat`, `robe`, and `wand`. Authors do not register a
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
`Pentaclostic Ring` recipe. Enable it to run the read-only live verifier:

```powershell
py tools/verify_lua_items.py
```

The verifier checks the fixed ID, exact lookup, local recipe resolution, strict input
rejection, and absence of address-shaped fields without granting or changing an item.
