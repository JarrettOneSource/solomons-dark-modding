# Lua cross-mod bus

`sd.bus` is a bounded local publish/subscribe channel between loaded Lua mods.
It advertises the `bus.local.contracts` capability and uses manifest contracts
to make framework dependencies explicit.

## Manifest contracts

A Lua mod may declare lowercase contract identifiers at the top level of
`manifest.json`:

```json
{
  "id": "example.quests",
  "runtime": {
    "apiVersion": "0.2.0",
    "entryScript": "scripts/main.lua",
    "requiredCapabilities": ["bus.local.contracts"]
  },
  "provides": ["example.quests.v1"],
  "requires": ["example.ui.v1"]
}
```

Contract identifiers are 1 through 128 ASCII characters using lowercase
letters, digits, `.`, `_`, `-`, or `:`. A mod cannot both provide and require
the same contract.

`requiredMods` and `requires` solve different problems. `requiredMods` names
packages that the launcher should enable together. `requires` names an
interface and may be satisfied by any enabled provider. The launcher rejects
an enabled set with no provider. The loader then resolves contracts again
against Lua mods that passed their API, capability, and entry-script gates.
Consumers load only after at least one real provider has loaded; provider
failure leaves the consumer unloaded with an explicit log message.

## API

```lua
local subscription = sd.bus.subscribe("example.quests.changed", function(payload, context)
  print(context.topic, context.publisher_mod_id, payload.quest_id)
end)

local delivered = sd.bus.publish("example.quests.changed", {
  quest_id = "intro",
  state = "complete",
})

local removed = sd.bus.unsubscribe(subscription)
local available = sd.bus.has("example.quests.v1")
local provider_mod_ids = sd.bus.providers("example.quests.v1")
```

`subscribe` returns a handle owned by the calling mod. `unsubscribe` returns
`true` only while that handle is active. All handles and registry references
are released when the mod unloads.

`publish` is synchronous and returns the number of callbacks invoked. Delivery
order is loaded-mod order, then subscription order. Each callback receives a
bounded copied payload and a context table containing `topic` and
`publisher_mod_id`. Callback failures are logged against the subscriber and do
not abort remaining deliveries.

Subscriptions are snapshotted before dispatch. A handler added during a
publish starts with the next publish; a handler removed before its turn does
not run. A mod may retain at most 128 subscriptions, one publish may match at
most 256 subscriptions, and nested publishes are limited to depth 16. Payloads
use the same deterministic nil/boolean/number/string/array/object codec and
32-KiB bound as `sd.state` events; cycles and unsupported Lua values fail before
any subscriber runs.

The bus does not retain or replay messages. Register subscriptions before
publishing lifecycle messages. Declare `requires` when entry-script startup
needs a provider to have registered first.

## Multiplayer

The bus is process-local and never replicated. Use it for contracts between
mods installed in the same game process. For a message that must reach every
peer, use `sd.events.broadcast`; for durable shared state, use `sd.state`.

The opt-in `sample.lua.bus_provider_lab` and
`sample.lua.bus_consumer_lab` mods demonstrate provider-first loading and a
nested cross-state request/response round trip.

## Verification

The single-process verifier attaches to an already running loader whose exact
enabled set contains both lab mods:

```powershell
py tools/verify_lua_bus.py
```

For the complete multiplayer-local lifecycle, use a disposable pair:

```powershell
py tools/verify_lua_bus_multiplayer.py --launch-pair
```

The pair verifier stages the provider and consumer as one ordered exact mod set
on both peers. It proves provider-first resolution and nested cross-state
request/response independently in each process, then publishes host-only and
client-only marker messages to demonstrate that subscriptions and deliveries
never cross the network boundary. The host also fills the remaining 127 slots
beside the provider's entry-script subscription, rejects the 129th total
subscription, releases every temporary handle, and proves the consumer
round-trip still works. Window tiling and global process cleanup are disabled;
only the two process IDs returned by this launch are stopped.
