# Replicated Lua state and events

`sd.state` and `sd.events.broadcast` are the loader's default multiplayer
contract for Lua mods. Mod authors do not open sockets or identify peers. The
simulation authority writes shared state and publishes events; the loader
orders those operations, applies them on clients, and synchronizes current
state to late joiners.

## Authority model

Single-player and the multiplayer host are simulation authorities. A client
can read `sd.state`, but `sd.state.set`, `sd.state.delete`, `sd.state.clear`,
and `sd.events.broadcast` raise a Lua error on a client. Use
`sd.state.is_authority()` when a script needs to choose between simulation and
presentation work.

The APIs are scoped to the calling mod. A mod can neither read another mod's
state nor publish into another mod's event namespace. Cross-mod communication
belongs in the future `sd.bus` seam.

The capability names are:

- `state.replicated.read`
- `state.replicated.write`
- `events.replicated.broadcast`

The write capability means the API is installed. Runtime authority still
decides whether a particular call may mutate shared simulation state.

## `sd.state`

```lua
if sd.state.is_authority() then
  local revision = sd.state.set("round", {
    phase = "combat",
    wave = 3,
    objectives = {"survive", "protect_orb"},
  })
  print("shared-state revision", revision)
end

local round = sd.state.get("round", {phase = "waiting"})
local all_values_for_this_mod = sd.state.snapshot()
local revision = sd.state.get_revision()
```

The namespace exposes:

| Function | Result | Contract |
|---|---|---|
| `get(key[, default])` | stored value or `default`/`nil` | Readable on every peer. Returned tables are copies. |
| `set(key, value)` | new state revision | Authority-only. Replaces one key. |
| `delete(key)` | boolean | Authority-only. Returns `false` when the key was absent. |
| `clear()` | boolean | Authority-only. Clears only the calling mod's keys. |
| `snapshot()` | table | Copy of every key owned by the calling mod. |
| `get_revision()` | integer | Current global replicated-state revision. |
| `is_authority()` | boolean | `true` in single-player and on the multiplayer host. |

State revisions order mutations across every mod. A no-op `delete` or `clear`
does not advance the revision.

## `sd.events.broadcast`

Register a custom event with the ordinary event API, then publish it from the
authority:

```lua
sd.events.on("director.intensity_changed", function(payload, context)
  print(payload.intensity)
  print(context.event)
  print(context.mod_id)
  print(context.authority_participant_id)
  print(context.stream_sequence)
end)

if sd.state.is_authority() then
  sd.state.set("intensity", 0.75)
  local sequence = sd.events.broadcast(
    "director.intensity_changed",
    {intensity = 0.75}
  )
end
```

The returned sequence is positive in multiplayer and is `0` in single-player.
The authority also receives its own event through the queued gameplay-thread
dispatcher. All peers observe custom events in stream order. A state mutation
sequenced before an event is visible when that event's handler runs.

Custom names use letters, digits, `.`, `_`, `-`, and `:` and are at most 128
bytes. Built-in event names such as `runtime.tick`, `run.started`, and
`spell.cast` are reserved and cannot be broadcast. A custom event is delivered
only to handlers registered by the publishing mod.

Events are transient. A late joiner receives current `sd.state`, not historical
events. Put durable facts in state and use events for ordered notifications.

## Value model and limits

The replicated value model accepts:

- `nil` event payloads, booleans, integers, finite numbers, and strings;
- dense, one-indexed arrays;
- tables whose keys are all strings.

`sd.state.set(key, nil)` is rejected; use `sd.state.delete(key)` instead. An
empty Lua table is encoded as an object. Cyclic tables, sparse arrays,
mixed array/object keys, non-string object keys, functions, userdata, threads,
NaN, and infinities are rejected before state changes or packets are emitted.

| Limit | Value |
|---|---:|
| Mod id, event name, or state key | 128 bytes |
| String | 16 KiB |
| Encoded value/event payload | 32 KiB |
| Encoded complete state checkpoint | 64 KiB |
| Nesting depth | 16 |
| Nodes in one value | 2,048 |

Object keys are serialized in bytewise map order. Integers remain integers and
numbers use their exact IEEE-754 bytes, so equivalent accepted values produce
the same binary representation.

## Network behavior

Protocol version 72 adds a host-authored Lua stream. Each mutation and event
has a 64-bit stream sequence. Messages are split into bounded 1 KiB fragments,
reassembled with fixed memory/count limits, authenticated as coming from the
configured authority, and applied only when the next contiguous sequence is
available. Steam sends every fragment through its reliable ordered channel.

The host sends a complete versioned state checkpoint when it learns a peer and
periodically thereafter. A checkpoint establishes the stream baseline, so a
late joiner can begin at current state without replaying old events. Duplicate
or older state revisions are idempotently ignored. The local UDP backend is a
development transport without retransmission; periodic checkpoints guarantee
state convergence there, while transient event delivery assumes localhost's
loss-free test conditions.

Authority migration remains intentionally out of scope. The current session
model ends or reconnects when the authority leaves; it does not transfer a
live Lua simulation to another participant.

## Verification

The namespace smoke test covers every exported function:

```powershell
py -3 tools/verify_lua_runtime_contract.py --launch-pair
```

The replication acceptance test registers handlers on both peers, publishes a
nested state value followed by two events, checks ordered client delivery and
state visibility inside the handlers, then launches a third client and proves
late-join checkpoint convergence:

```powershell
py -3 tools/verify_lua_mod_replication.py --launch-pair
```
