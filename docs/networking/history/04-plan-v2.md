# Solomon's Dark: Netcode Plan v2 (post-Codex-round-1)

Date: 2026-04-19
Status: Living document. v1 was `/tmp/sd-netcode/brainstorm.md`. v2 folds in round-1 Codex critique + 2025-2026 research.

## Non-negotiable requirements

1. Synchronize enemies, players, drops.
2. Dedicated server + P2P host (same client/server topology; different session discovery).

## Defaulted decisions (baked from round-1 Codex, open for pushback)

- **Ship order**: P2P-host-first → generic participant rail → true dedicated last. Dedicated only ships after `SteamGameServer_Init` bootstrap + a safe non-slot-0 pump exist.
- **Authority model**: Host-authoritative simulation + client-side prediction + reconciliation for the locally-controlled player. Snapshot interpolation for remote players and enemies. Optimistic cast animations with host hit validation. This replaces v1's "client owns its own pose."
- **Steam transport**: `ISteamNetworkingSockets` + Steam Datagram Relay (SDR). `ISteamNetworking` is deprecated; we don't build on it.
- **Off-Steam transport**: Standalone **GameNetworkingSockets** (API symmetry with Steam path) OR **ENet** for minimum integration cost. Not QUIC in v1.
- **Reliability split**: Unreliable lanes for pose / state / snapshots. Reliable lanes for casts, drops, joins, confirmations, progression.
- **Tick rates**: Input at 30-60 Hz. Nearby enemy snapshots at 15-20 Hz floor. Bosses at 30 Hz or explicit eventization. Decoupled from render FPS via a sim-tick scheduler sampling after stock updates on the game thread.
- **Anti-cheat scope**: Skip EAC/BattleEye in v1. Disable the named-pipe Lua exec server and `sd.debug` in multiplayer builds. Partition "trusted private host" from "dedicated/secure." Accept that host abuse is unsolved in host-auth P2P.
- **Matchmaking**: Steam lobbies for party/invite/readiness → handoff to host/dedicated connection. Server browser + direct IP for dedicated. Defer PlayFab/GameLift/EOS.
- **World/save**: Treat save/world/server identity as a first-class replicated object. Versioning, mod-manifest compatibility, backup/restore from day one.

## What exists today

### Real (working)
- Participant rail data model: `multiplayer_runtime_state.h` — `ParticipantInfo`, `ParticipantKind{LocalHuman, RemoteParticipant}`, `ParticipantControllerKind{Native, LuaBrain}`.
- Bot runtime materializes real `PlayerActor` entities; slots 1-3; hostile targeting validated; takes damage; movement via native collision.
- Service loop (50 ms) pumping Steam callbacks, mirroring into `RuntimeState`.
- Steam client-side bootstrap: `SteamAPI_Init`, friends/matchmaking/networking/user interfaces.

### Drafted but not wired
- `multiplayer_runtime_protocol.h` — fixed structs (`StatePacket`, `LaunchPacket`, `CastPacket`, `ProgressionPacket`). **To be replaced.**

### Known liabilities (round-1 critique findings)
1. **Bots are not a drop-in remote-human rail.** `ReadBotSnapshot` and dispatch path only accept `LuaBrain`; a `RemoteParticipant + Native` sync request is treated as stale. Needs generic `ReadParticipantSnapshot` + controller-source interface keyed by `participant_id`.
2. **No `SteamGameServer_Init`.** Dedicated bootstrap does not exist in the repo today.
3. **World-mutation rail is slot-0 coupled.** Safe mutations live on local slot-0 `PlayerActorTick`; no dedicated-side pump exists.
4. **Lua surface is multiplayer-fatal.** Every mod gets `sd.debug` (arbitrary memory writes + native calls). Named-pipe exec server always starts with Lua. Public APIs (`sd.input.*`, `sd.hub.start_testrun`, `sd.gameplay.start_waves`, `sd.world.spawn_*`, `sd.bots.*`) mutate gameplay directly.
5. **Drop sync readiness is gold-only.** No generic walk-over pickup bridge; non-gold drop factories aren't REd.
6. **Enemy replication seams are thin.** Spawn and death are hooked; damage, attack-start, teleport, boss-phase transitions are not.

## Authority table (v2)

| Entity | Authority | Sync | Rate |
|---|---|---|---|
| Local player | Host (simulation) + local client (prediction) | Input→host; host→all snapshot; reconcile on mismatch | Input 30-60 Hz; pose snapshot 20-30 Hz |
| Remote player | Their owning client's host | Snapshot interpolation | 20-30 Hz |
| Enemies | Host | Snapshot burst (pos + vel + hp_delta + state) | 15-20 Hz normal, 30 Hz bosses |
| Drops | Host | Reliable spawn / pickup / despawn events | event-driven |
| Spells (cast init) | Caster optimistic, host validates hits | Reliable | event-driven |
| Damage / death | Host | Reliable event | event-driven |

## Revised packet catalog

v1 packet set (`State`/`Launch`/`Cast`/`Progression`) is replaced with variable-size envelope + payload families:

- **Session setup**: `hello/version/mod-manifest`, `join/auth`, `clock-sync`
- **Join-in-progress / reconnect**: reliable chunked `full-state-bootstrap` (participant list, run header, live enemies, live drops, per-player progression/loadout/vitals)
- **State stream**: `delta-snapshot` (unreliable, variable-size, per-tick)
- **Entity lifecycle**: `spawn`, `despawn` (reliable)
- **Gameplay events**: `reliable-gameplay-event` (cast, interact, hit-confirm), `damage/result`, `inventory/drop/pickup`, `boss/world-transition`
- **Connectivity**: `disconnect/reconnect`, `ping/heartbeat`
- **Save/world identity**: `save-provenance` (version, mod-manifest hash)

Header: `SDMP` magic, protocol version, envelope size, payload family tag, sequence/ack, reliability flag, channel id.

## Transport abstraction

```
ITransport {
    connect(peer_address) -> connection
    send(connection, channel, reliability, bytes)
    broadcast(channel, reliability, bytes)
    poll() -> events (connect / disconnect / data)
}
```

Implementations:
- **SteamSocketsTransport** — wraps `ISteamNetworkingSockets` (+ SDR when available)
- **GameNetSocketsTransport** (or **ENetTransport**) — off-Steam dedicated path
- **LoopbackTransport** — in-process testing

Above this seam: replication, participant rail, snapshot logic — identical on host-client P2P and dedicated.

## Phased roadmap

### Phase 0: Pre-multiplayer gating (must land before ANY network code is trusted)
- Multiplayer build flag that:
  - disables named-pipe Lua exec server
  - refuses to register `sd.debug`
  - routes `sd.world.spawn_*`, `sd.gameplay.start_waves`, `sd.input.*`, `sd.bots.*` through a host-intent RPC (or disables entirely for non-host clients)
- Generic `ReadParticipantSnapshot` + controller-source interface; prove a live `LuaBrain → Native` swap on a single actor without respawn.

### Phase 1: Host-client P2P (hidden local player = host)
- Transport abstraction + Steam `ISteamNetworkingSockets` impl.
- Session: Steam lobby → transport handoff.
- Join/auth + mod-manifest handshake + clock-sync.
- Full-state-bootstrap packet.
- Participant join/leave; local player as native participant.
- Snapshot interpolation for remote players.
- Client prediction + reconciliation for local player.
- Reliable cast / damage / death events.
- Wave / run lifecycle sync.

### Phase 2: Enemy + drop sync
- Enemy seam recovery: damage, attack-start, teleport, boss phase.
- 15-20 Hz enemy snapshot burst.
- 30 Hz boss burst or eventization.
- Drop spawn / pickup / despawn reliable events (start with gold-only; scope beta accordingly).

### Phase 3: Dedicated server
- `SteamGameServer_Init` anonymous bootstrap.
- Safe no-slot-0 game-thread pump (separate from `PlayerActorTick`).
- Headless D3D9 stub, `--server` loader flag.
- Server browser + direct IP connect.
- Save/world identity object with version + mod-manifest check.

### Phase 4: Hardening
- Reconnect reliability / drop-and-rejoin.
- Persistent save with backup/restore.
- Admin tooling (adminlist, banlist, kick/ban commands).
- Migration: reliability audit, latency simulation, stress test.

## Open questions for round-2 review

1. Is the v2 authority model (host sim + client prediction + reconciliation for local player) implementable on this engine? `PlayerActorTick` runs on the game thread every frame; does that allow reconciliation at all, or does the engine assume single-authority-per-actor?
2. Is the phase order safe? Specifically, can Phase 1 ship cleanly without secretly requiring a Phase 3 capability (e.g. host-authoritative simulation needing the no-slot-0 pump before we realize)?
3. Is the revised packet catalog overdesigned for v1, or is any family actually missing (e.g. input replay for prediction rollback, chat/voice, admin command envelope)?
4. What's the smallest Phase 0 that is credibly multiplayer-safe? I want to block progression on this and not rush.
5. Does the mod-manifest handshake need to be per-file hash, or is a content-version sufficient?
6. Does the `LuaBrain → Native` participant-controller swap happen pre-materialization (at actor create) or runtime (hot-swap on an existing actor)? Both have implications.
