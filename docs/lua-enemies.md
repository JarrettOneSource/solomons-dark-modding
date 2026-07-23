# Lua enemy registration and spawning

`sd.enemies` binds deterministic mod content identities to supported hostile
stock classes and queues one authority-owned spawn through the retail exact-group
spawner. It never calls the old hand-built `Enemy_Create` shape.

## Registration

Registration is allowed only while the owning mod's entry script is loading:

```lua
local enemy = sd.enemies.register({
  key = "grave_tyrant",
  base = "skeleton",
  hp = 250,
  speed = 2.5,
  scale = 1.2,
  loot = "gold",
})
```

`key` participates in the shared `sd.content.v1` identity. `base` is a semantic stock-class name,
never an author-chosen numeric type. The supported bases are:

| Base | Native type | Base | Native type |
|---|---:|---|---:|
| `skeleton` | `0x3E9` | `skeleton_archer` | `0x3EA` |
| `skeleton_mage` | `0x3EB` | `imp` | `0x3EC` |
| `zombie` | `0x3EE` | `wraith` | `0x3EF` |
| `demon_skull` | `0x3F0` | `demon` | `0x3F1` |
| `dire_faculty` | `0x3F2` | `heartmonger` | `0x3F3` |
| `coffin` | `0x3F5` | `green_imp` | `0x7FC` |
| `maggot` | `0x7FD` | `spider` | `0x809` |
| `portal` | `0x139D` | | |

Good Imp and Crow are excluded because they are an ally and an owner-managed
helper rather than public hostile archetypes. A mod may register at most 256
enemy definitions. Duplicate keys, cross-kind key reuse, and content-ID
collisions fail through the shared content registry.

`hp`, `speed`, `scale`, and `loot` are optional defaults. `speed` is the stock
chase-speed field. `loot` accepts `stock`, `none`, `orb`, `gold`, `item`,
`powerup`, or `potion`.

## Lookup

```lua
local own = sd.enemies.get("grave_tyrant")
local any = sd.enemies.get(own.id)
local all = sd.enemies.list()
```

Descriptors contain `id`, `mod_id`, `key`, `base`, `native_type_id`, the
declared defaults, and `loot`. They contain no config, actor, arena, or spawner
addresses. The corresponding capabilities are `enemies.register` and
`enemies.read`.

## Authority-owned spawning

```lua
local queued = sd.enemies.spawn("grave_tyrant", {
  x = 620,
  y = 410,
  hp = 400,
  speed = 3.0,
  scale = 1.35,
  loot = "item",
})
```

`x` and `y` are required. The other fields override the registered defaults for
that spawn only. The call is accepted only by the offline or host simulation
authority, in an active combat arena, after a valid stock wave spawner has been
observed. The `enemies.spawn.authority` capability advertises availability.

The returned table confirms queue acceptance and contains `request_id`,
`content_id`, `native_type_id`, `x`, and `y`. Construction is asynchronous on
the gameplay pump. The queue is bounded to 16 outstanding exact spawns.

The native path calls `kSpawnExactEnemyGroup` with one actor and a valid empty
modifier array, then lets the retail engine choose its config and invoke the
exact constructor ABI. The loader transactionally overlays HP, chase speed,
attack speed, and scale on that captured config, runs authority-side
`enemy.spawning` filters, constructs the actor, and restores the shared stock
config. It then relocates the actor and rebinds its spatial cell. A cancellation,
capture failure, rewrite failure, wrong class, or failed cell rebind completes
the request as a failure instead of falling back to a direct constructor call.

Registered loot policy is attached to the resulting actor, not its shared
config. At death it becomes the starting `drop.rolling` policy; ordered filters
may still change it or cancel the roll. `none` suppresses the selector. Clients
do not execute the authority loot policy.

## Multiplayer identity and events

Protocol 77 carries the positive 63-bit content ID and the effective common spawn
config to each registered enemy's world snapshot. A client materializes the
same semantic stock class through the same exact-spawn path, applies the
authority's effective constructor values, and then follows normal snapshot
health, transform, status, target, and death reconciliation. Raw actor/config
addresses never cross the wire.

`enemy.spawned` and `enemy.death` now include `content_id` on every peer. It is
zero for stock enemies and the deterministic registered ID for a Lua enemy.
The identity is retained in death tombstones so the notify payload remains
stable when an actor is retired before a client sees the final live snapshot.

The disabled-by-default `sample.lua.enemies_registry_lab` mod registers a
`grave_tyrant` descriptor without spawning anything. `tools/verify_lua_enemies.py`
is read-only. `tools/verify_lua_enemy_spawn.py --confirm-mutation` performs the
opt-in live spawn check and must be run only in a disposable active arena.
