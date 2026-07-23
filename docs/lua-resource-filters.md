# Lua XP, gold, and mana resource filters

`sd.events.filter("xp.gaining", handler)` and
`sd.events.filter("gold.changing", handler)` run synchronously before their
stock resource mutations. `sd.events.filter("mana.changing", handler)` wraps
the native wizard mana-delta writer on the process that simulates that wizard.
All three use the same stable mod-load and registration ordering as every other
mutable event filter. Each handler sees earlier rewrites, and cancellation
stops the chain.

The capability for all three filters is `events.filters.resources`.

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

## Mana payload

The native hook runs at `PlayerActor::ApplyManaDelta` before the stock writer:

```lua
{
  event = "mana.changing",
  participant_id = 123, -- standalone local player uses semantic ID 1
  actor_address = 12345678,
  progression_address = 23456789,
  current_mana = 35.0,
  maximum_mana = 100.0,
  delta = -12.0,
  resulting_mana = 23.0,
  allow_prompt = false,
  source = "native",
}
```

`resulting_mana` is the arithmetic pre-native result for the current rewritten
`delta`; the stock writer still owns its final clamping and prompt behavior.
The handler may rewrite the signed change with `{delta = number}`. Values must
be finite and within `-1,000,000..1,000,000`.

Returning `{delta = 0}` for a negative change makes mana spending free while
preserving the stock cast, cooldown, animation, and replication paths:

```lua
sd.events.filter("mana.changing", function(event)
  if infinite_mana[event.participant_id] and event.delta < 0 then
    return {delta = 0}
  end
end)
```

`sd.player.restore_mana()` is the complementary owner-local semantic action.
It takes no arguments, restores the calling process's local wizard through the
native mana writer, and returns `true, resulting_mana` or `false, error`. It
advertises `player.resources.owner`. The action deliberately calls the native
writer beneath the hook so it can be used safely from a Lua callback without
recursively re-entering `mana.changing`.

## Handler results

All three filters accept:

- `nil` or `true` to keep the current outcome;
- `false` or `{cancel = true}` to cancel before stock mutation;
- `{amount = number}` for XP;
- `{delta = integer}` for gold.
- `{delta = number}` for mana.

Patches are transactional. A bad field rejects the whole patch, logs the owning
mod ID, and fails open with the prior handler's outcome. Callback errors and
Lua-engine re-entry also fail open. Filters cannot yield.

## Ownership and replication

Standalone XP, gold, and mana changes run locally. In multiplayer, native XP
and mana changes run where that participant progression is simulated and
ordinary progression replication carries the result.

Gold pickup authority is more explicit. The host filters its local stock
pickup at `Gold_ChangeGlobal`. For a remote participant, the host filters the
signed pickup delta before deactivating the authoritative drop and records the
rewritten total in the pickup result. The client then applies that accepted
result and may replay the stock pickup only for sound, text, and actor removal.
That accepted feedback replay is explicitly excluded from `gold.changing`, so
the same pickup is never filtered twice.

## Sample and verification

The opt-in `sample.lua.resource_filter_lab` mod doubles positive XP and gold
gains while leaving spends unchanged. The
`canary.lua.invincibility_potion` mod uses `mana.changing` together with
`sd.player.restore_mana()` to implement three minutes of true infinite mana.
Run the static contract with:

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
