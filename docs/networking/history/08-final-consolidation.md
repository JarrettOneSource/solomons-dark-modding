### 1. Final verdict on v3
v3 is mostly the right landing once I stop optimizing for the stricter threat model I used in rounds 1-2. The core is right: host-authoritative-lite, local cosmetic responsiveness, reliable gameplay events, and a locked multiplayer runtime instead of a real anti-cheat stack. It still over-engineers by carrying dedicated-server prep, off-Steam transport, and Phase-0 slot-0 decoupling into the first ship. It still under-engineers one thing that will absolutely sink the project if omitted: real session/run identity plus live progression and run-lifecycle sync, because “same world state” breaks immediately on late join, gold/XP changes, pickups, and wave/run transitions if those are not first-class.

### 2. The actual minimum viable netcode
Authority model: the host is the only authoritative world simulator; clients send intent packets and render immediate local echo, then hard-snap to host state when they differ.

Transport choice: Steam `ISteamNetworkingSockets` with SDR only for v1. Drop standalone GameNetworkingSockets, ENet, direct IP, and dedicated-server transport from the MVP. Those are later work, not minimum shippable co-op.

Packet families:
- `hello/manifest` for protocol version and exact loaded-mod manifest
- `join/bootstrap` for participant upsert and chunked full-state join-in-progress
- `input` for movement/cast/pickup intent with per-client sequence numbers
- `snapshot-delta` for player/enemy state bursts
- `spawn/despawn` for enemies and drops
- `gameplay-event` for casts, damage, death, pickups, run start/end, wave/boss transitions
- `progression-delta` for gold, XP, level, and any live loadout/inventory mutation that remains enabled

Tick rates:
- Client input: `30 Hz`
- Player snapshots: `20 Hz`
- Enemy snapshots: `20 Hz` baseline, `30 Hz` for bosses and hot states
- Reliable events: immediate
- Sampling happens on the stock game thread after native updates; no extra sim thread

Anti-cheat: none in the serious sense. Do exact manifest matching, connection-bound identity, host-owned authority over spawn/damage/pickups/progression, malformed/stale packet rejection, and disable the direct dev/debug mutators in multiplayer. Accept trusted-host cheating. If the host wants to cheat in their own session, that is out of scope.

Replacement for v3: cut dedicated and alternate transports out of the MVP entirely. Keep one hosted Steam path and make that work first.

### 3. Phase 0 absolute minimum
- Add a real multiplayer runtime profile.
- In that profile, disable the named-pipe Lua exec server, `sd.debug`, debug-UI mutation paths, and non-host gameplay-mutating Lua automation.
- Enforce exact protocol-version plus loaded-mod-manifest match on join; mismatch refuses connection.
- Bind network identity to the connection; never trust client-declared player or actor identity.
- Replace the Lua-only bot snapshot path with a generic participant snapshot/controller source that can create `RemoteParticipant + Native` actors.
- Seed and carry a real `run_nonce` or equivalent session/run identity.
- Add basic packet sanitation: size/version/family checks and stale-sequence rejection.

That is enough to prevent accidental world corruption and identity spoofing without pretending to stop a determined attacker.

### 4. What v3 dropped that should be un-dropped
- Last-processed input sequence in authoritative player snapshots. No rollback is needed, but clients still need a correction baseline.
- Exact mod compatibility, not a tolerant policy. The main real failure mode here is accidental divergence, not hostile cheating.
- Live inventory/loadout delta if non-gold loot stays enabled. Otherwise ship v1 as gold-only drops.

### 5. What v3 kept that should be further dropped
- Dedicated server work in the first shipping target.
- Standalone GameNetworkingSockets, ENet, direct IP, and server browser work in the first shipping target.
- Phase-0 slot-0 decoupling. That is only needed once you truly pursue dedicated hosting.

### 6. The landing answer — one paragraph
You’re building a hosted co-op sync layer for Solomon Dark where one player hosts inside the normal game, every other player sends movement and gameplay intents to that host, and the host broadcasts the authoritative player, enemy, drop, and run state about twenty times per second plus reliable gameplay events like casts, damage, pickups, and wave transitions. Clients can feel immediate locally, but they do not own the world; if the host disagrees, they snap back. Multiplayer mode disables the dev/debug mutation backdoors and refuses mismatched mod sets so peers do not accidentally diverge. There is no rollback, no serious anti-cheat, no dedicated server, and no persistent-world machinery in the first ship, just one trusted-host Steam session that keeps everyone in the same fight and the same run state.