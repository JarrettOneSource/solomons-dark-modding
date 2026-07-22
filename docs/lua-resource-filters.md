# Lua XP and gold resource filters

`sd.events.filter("xp.gaining", handler)` and
`sd.events.filter("gold.changing", handler)` run synchronously before the
stock resource mutation. They use the same stable mod-load and registration
ordering as every other mutable event filter. Each handler sees earlier
rewrites, and cancellation stops the chain.

The capability for both filters is `events.filters.resources`.

## XP payload

The loader hooks the retail progression gain routine at its `0x00680AD8`
post-eligibility convergence point, before it applies optional stock XP
multipliers, writes `progression + 0x34`, or invokes the native level-up
routine. The handler receives:

```lua
{
  event = "xp.gaining",
  progression_address = 12345678,
  participant_id = 123, -- nil outside a known multiplayer participant
  current_xp = 18.0,
  amount = 4.0,
  native_scaling = true,
  source = "reward", -- "reward" or "script"
}
```

`amount` is the input to the native routine. When `native_scaling` is true,
the retail level and XP-bonus multipliers still run after Lua returns. A handler
can preserve that stock behavior while changing the base reward:

```lua
sd.events.filter("xp.gaining", function(event)
  return {amount = event.amount * 1.5}
end)
```

XP replacements must be finite and within `0..1,000,000`.

## Gold payload

The native hook runs at `Gold_ChangeGlobal` (`0x005A7C60`) before its
affordability check or global write:

```lua
{
  event = "gold.changing",
  participant_id = 123, -- nil in standalone play
  current_gold = 80,
  delta = -25,
  resulting_gold = 55,
  allow_negative = false,
  would_succeed = true,
  source = "spend", -- "pickup", "spend", "script", or "unknown"
}
```

`resulting_gold` and `would_succeed` are recalculated for every handler from
the current rewritten `delta`. They describe the stock result if that delta is
committed. A handler rewrites the signed change with `{delta = integer}`.
Rewrites must fit a signed 32-bit integer and may not overflow the native total.

The existing queued `gold.changed` notification is post-mutation telemetry. It
reports the actual applied delta after clamping, so it may differ from the
pre-event request.

## Handler results

Both filters accept:

- `nil` or `true` to keep the current outcome;
- `false` or `{cancel = true}` to cancel before stock mutation;
- `{amount = number}` for XP;
- `{delta = integer}` for gold.

Patches are transactional. A bad field rejects the whole patch, logs the owning
mod ID, and fails open with the prior handler's outcome. Callback errors and
Lua-engine re-entry also fail open. Filters cannot yield.

## Ownership and replication

Standalone XP and gold changes run locally. In multiplayer, native XP gains run
where that participant progression is simulated and ordinary progression
replication carries the result.

Gold pickup authority is more explicit. The host filters its local stock
pickup at `Gold_ChangeGlobal`. For a remote participant, the host filters the
signed pickup delta before deactivating the authoritative drop and records the
rewritten total in the pickup result. The client then applies that accepted
result and may replay the stock pickup only for sound, text, and actor removal.
That accepted feedback replay is explicitly excluded from `gold.changing`, so
the same pickup is never filtered twice.

## Sample and verification

The opt-in `sample.lua.resource_filter_lab` mod doubles positive XP and gold
gains while leaving spends unchanged. Run the static contract with:

```powershell
py -3 tools/verify_lua_resource_filter_contract.py
```

The disposable-process live verifier exercises ordered rewrites and
cancellation through the native XP and gold routines. Its XP call is queued
until after the registering Lua callback returns, so the synchronous filter is
tested without triggering the runtime's intentional re-entry fail-open guard:

```powershell
py -3 tools/verify_lua_resource_filters.py --pipe SolomonDarkModLoader_LuaExec
```
