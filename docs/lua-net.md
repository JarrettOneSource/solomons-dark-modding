# Raw participant messaging with `sd.net`

`sd.net` is the bounded escape hatch for a mod that cannot express a message as
replicated `sd.state` or an authority broadcast. It carries binary-safe,
mod-owned payloads between participants without exposing sockets, Steam handles,
native packet structures, or addresses to Lua.

Most mods should not use this namespace. Prefer:

- `sd.state` for durable shared state and late-join convergence;
- `sd.events.broadcast` for an authority-authored ordered event;
- `sd.bus` for communication between mods in one process.

Raw messages are transient. They are not checkpointed for a late joiner and do
not become part of the simulation authority model automatically.

## API

```lua
local subscription = sd.net.on("example.chunk", function(bytes, message)
  print("received " .. #bytes .. " bytes from " ..
    message.sender_participant_id)

  if not message.broadcast then
    print("target " .. message.target_participant_id)
  end
end)

local sequence = sd.net.broadcast("example.chunk", "binary\0payload")
local reply_sequence = sd.net.send(
  target_participant_id,
  "example.reply",
  encoded_bytes)

assert(sd.net.off(subscription))
local limits = sd.net.get_limits()
```

The functions are:

- `send(target_participant_id, channel, payload) -> sequence`
- `broadcast(channel, payload) -> sequence`
- `on(channel, callback) -> subscription_id`
- `off(subscription_id) -> boolean`
- `get_limits() -> table`

Targets and senders use the semantic participant IDs returned by the existing
multiplayer runtime APIs. A unicast target must be a connected participant.
Offline games have no positive participant ID, so local testing uses
`broadcast`; it queues one local callback with sender and target IDs set to `0`.

Payloads are Lua strings and are binary-safe, including embedded NUL bytes.
`sd.net` does not serialize tables or define an application schema. Each mod
owns the encoding and versioning of its channels.

The callback receives the raw payload first and this metadata table second:

```lua
{
  channel = "example.chunk",
  sender_participant_id = 7656119,
  target_participant_id = 0, -- zero means broadcast
  sequence = 12,             -- scoped to this sender's active session
  broadcast = true,
}
```

Callbacks run later from the normal Lua game-thread pump. They never execute in
the UDP receive loop, Steam service thread, render hook, or game window
procedure. Unsubscribing or unloading a mod releases its Lua registry
references; queued deliveries are isolated by mod ID.

## Topology and authentication

Clients do not send directly to another client. Every client message goes to
the session host. The host verifies the sending endpoint, participant ID,
current participant session nonce, fragment envelope, target, and replay key,
then relays an accepted message to the requested participant or all connected
participants. Relayed packets distinguish the authenticated transport hop from
the original logical sender, so a client cannot claim another participant's
identity.

Steam fragments use reliable, no-Nagle delivery. The local UDP backend remains
a development transport and inherits UDP datagram loss behavior. Each completed
message is deduplicated by sender and per-session sequence, but there is no
global order between different senders. A mod that needs durable convergence or
authority stream ordering should use `sd.state` or `sd.events.broadcast`.

Transport authentication proves who sent a message; it does not make the
payload trusted game authority. A host callback that turns a client message into
a simulation mutation must validate its channel schema, sender permissions, and
application state before calling authority-only APIs.

## Bounds

`get_limits` returns the Lua-facing identity and queue limits below. The
transport-only fragment, assembly, expiry, and replay limits are fixed protocol
safeguards rather than values a mod can tune.

- channel identifiers: 1–64 bytes;
- raw payload: at most 60 KiB;
- subscriptions: 64 per mod;
- outbound queue: 16 messages and 256 KiB total;
- pending Lua delivery queue: 64 messages and 512 KiB total;
- wire envelope: at most 64 fragments of 1,024 bytes;
- transport assembly: 32 concurrent messages and 512 KiB total;
- replay memory: 256 completed sequences per participant session.

Assemblies expire after ten seconds. Disconnect and session-epoch teardown
remove affected assemblies, remembered sequences, and queued relays. Protocol 80
makes the new packet shape an explicit compatibility boundary.

## Capabilities and verification

The namespace advertises `net.raw.fragmented`,
`net.participant.unicast`, and `net.participant.broadcast`.
`tools/verify_lua_net.py` checks the address-free API, binary-safe local
broadcast, subscription lifetime, limits, and validation behavior against an
already-running loader.

`tools/verify_lua_net_multiplayer.py --launch-pair` stages one exact Lua mod on
an isolated host/client pair and verifies fragmented binary unicast in both
directions plus broadcast in both directions. It requires the exact sender,
target, sequence, broadcast flag, payload length, and boundary bytes on each
recipient, so host relay, source attribution, binary preservation, and
deduplication are live acceptance conditions. The launcher preserves unrelated
game processes and cleans up only the exact process IDs it started.

The static contract additionally checks packet bounds, hop/source
authentication, host relay rules, replay suppression, lifecycle cleanup, docs,
and the disabled sample mod.
