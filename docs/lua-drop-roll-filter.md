# Lua drop-roll filter

`sd.events.filter("drop.rolling", handler)` runs synchronously before the
retail enemy-death selector builds and chooses its reward candidate. It can
retain the stock policy, rewrite the six native selector values, force one
supported reward category, or cancel reward selection entirely.

## Minimal example

```lua
sd.events.filter("drop.rolling", function(event)
  if event.native_type_id == 1001 then
    return {kind = "gold"}
  end
end)
```

The opt-in `sample.lua.drop_roll_filter_lab` mod forces owner-simulated enemy
rewards through the stock gold materializer.

## Payload

Every handler receives a fresh table containing the result of earlier
handlers:

```lua
{
  event = "drop.rolling",
  kind = "stock", -- or an earlier handler's forced category
  native_type_id = 1001,
  enemy_address = 12345678,
  arena_address = 23456789,
  config_address = 34567890,
  x = 640.0,
  y = 360.0,
  arena_disable_mask = 0,
  selectors = {
    0, 0, 0, 0, 0, 0,
    orb = 0,
    powerup = 0,
    item = 0,
    gold = 0,
    specific_item = 0,
    potion = 0,
  },
  orb_selector = 0,
  powerup_selector = 0,
  item_selector = 0,
  gold_selector = 0,
  specific_item_selector = 0,
  potion_selector = 0,
}
```

The six selector bytes are the retail monster-definition fields at
`+0xCC..+0xD1`. Values `0..5` are native policy codes, not percentages. They
are exposed for advanced stock-policy tuning; portable mods should normally
use `kind` instead. Addresses are process-local diagnostics and are valid only
during the callback.

## Handler results

A handler may return:

- `nil` or `true` to retain the current outcome;
- `false`, `{cancel = true}`, or `{kind = "none"}` to cancel the roll;
- `{kind = "orb"}`, `{kind = "gold"}`, `{kind = "item"}`,
  `{kind = "powerup"}`, or `{kind = "potion"}` to force a category;
- `{kind = "stock"}` to clear an earlier forced category;
- a partial `selectors` table, or named `*_selector` fields, containing
  integer native policy codes in `0..5`.

Named selector fields are applied after the nested table and therefore take
precedence. A forced `kind` takes precedence over selector rewrites when the
native transaction is built. Invalid patches and handler errors are logged
and fail open without discarding earlier valid rewrites.

Handlers execute in stable mod-load order and registration order. Each later
handler sees earlier selector and `kind` changes. Cancellation is monotonic:
later handlers and the native selector do not run.

Registered enemies begin this chain with their per-actor `loot` policy from
`sd.enemies.register`/`spawn`. A handler can replace that forced category with
another category or `stock`; a starting `none` policy suppresses the selector.

## Native safety and ownership

The loader hooks `EnemyDeath_SelectAndSpawnRewards (0x0047C070)`, not the orb
initializer or Sack constructor. Ghidra proves this `void __fastcall(enemy)`
routine is called directly by the stock death handler and owns candidate
construction, the single uniform choice, and category materialization. The
constructors named in the original roadmap are downstream of that decision
and cannot safely cancel the whole roll.

For a forced category, all six selector bytes are temporarily set to the
native forced value and arena mask bits `0..5` suppress every category except
the requested one. This also bypasses the selector's separate quick-potion
branch, leaving exactly one candidate while preserving the stock category
factory, position, RNG initialization, registration, and object ownership.
The shared config bytes and arena mask are restored immediately after the
native selector returns. Partial writes are rolled back; an unrecoverable
rollback cancels the roll instead of executing against corrupted policy.

Cancellation simply skips the `void` selector. No partially constructed
reward exists and the caller consumes no return value.

The filter runs in single-player and on the multiplayer authority. Transport
clients skip it because host-authored loot snapshots already carry the chosen
native actor and exact item metadata. This prevents clients from rolling or
rewriting the same death twice.

## Capability and verification

The seam advertises `events.filters.drop_roll`.

The static contract verifier checks the registered name, native seam,
transaction, client gate, project membership, documentation, and sample mod:

```powershell
py -3 tools/verify_lua_drop_filter_contract.py
```

The live verifier uses two ordered handlers, proves the second sees the first
rewrite, forces an actual stock gold actor, then cancels the next enemy's roll
and proves no reward actor appears:

```powershell
py -3 tools/verify_lua_drop_filters.py --pipe SolomonDarkModLoader_LuaExec
```

The stock `testrun` fixture spawns definition-less enemies whose native
`actor+0x1D0` field is null, so they have no retail drop policy to exercise.
For that disposable acceptance run only, the verifier attaches a zeroed
definition block around a deferred game-thread death probe. The probe runs
after the Lua callback releases the engine lock and restores the actor's
original definition pointer before publishing completion. The selector bytes,
arena mask, gold materializer, and cancellation path remain the retail code
used by normal definition-backed enemies.
